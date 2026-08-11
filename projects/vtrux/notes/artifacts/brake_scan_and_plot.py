#!/usr/bin/env python3
"""
Brake booster pressure signal search: scan + plot.
Runs optimized (bisect-based) event scan on two logs, then plots top candidates.

Log configs:
  movingaroundindriveway.log: PT=3, GM_VEH=2, GM_OBD=1
  vtruxanotherevaplogpart1.log: PT=3, GM_VEH=1, GM_OBD=2
"""
import sys, math, bisect
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

ARTIFACT_DIR = Path(__file__).parent

LOGS = [
    {
        "path":    "projects/vtrux/logs/movingaroundindriveway.log",
        "label":   "driveway",
        "PT_BUS":  3,
        "GM_BUS1": 2,   # Vehicle
        "GM_BUS2": 1,   # OBD
    },
    {
        "path":    "projects/vtrux/logs/vtruxanotherevaplogpart1.log",
        "label":   "evap",
        "PT_BUS":  3,
        "GM_BUS1": 1,   # Vehicle
        "GM_BUS2": 2,   # OBD
    },
]

PEDAL_ID        = 0x592
PEDAL_PRESS_THR = 200   # 16-bit raw; idle floor ~0-156
PEDAL_MIN_PEAK  = 500   # 16-bit raw
MIN_FRAMES      = 40
RECOVERY_WINDOW = 5.0
RECOVERY_STEPS  = 5
TOP_N           = 8   # candidates to plot per log

# ------------------------------------------------------------------ helpers --

def nearest_at(ref_t, times, vals, max_dt=0.2):
    if not times: return None
    i = bisect.bisect_left(times, ref_t)
    best_i, best_d = None, max_dt + 1
    for j in [i - 1, i]:
        if 0 <= j < len(times):
            d = abs(times[j] - ref_t)
            if d < best_d:
                best_d, best_i = d, j
    return vals[best_i] if best_i is not None and best_d <= max_dt else None

def values_in_window(start_t, end_t, times, vals):
    lo = bisect.bisect_left(times, start_t)
    hi = bisect.bisect_right(times, end_t)
    return list(zip(times[lo:hi], vals[lo:hi]))

def find_brake_events(ped_times, ped_vals):
    press_events  = []
    release_events = []
    i = 0
    while i < len(ped_times):
        if ped_vals[i] >= PEDAL_PRESS_THR:
            j = i
            while j < len(ped_times) and ped_vals[j] >= PEDAL_PRESS_THR:
                j += 1
            seg_v = ped_vals[i:j]
            pk = max(seg_v)
            if pk >= PEDAL_MIN_PEAK:
                pki = seg_v.index(pk)
                pre_idx = i - 1
                while pre_idx >= 0 and ped_vals[pre_idx] >= PEDAL_PRESS_THR:
                    pre_idx -= 1
                if pre_idx >= 0:
                    press_events.append((ped_times[i + pki], ped_times[pre_idx],
                                         pk, ped_vals[pre_idx],
                                         ped_times[i], ped_times[j - 1]))  # +window bounds
                k = j
                while k < len(ped_times) and ped_vals[k] > PEDAL_PRESS_THR:
                    k += 1
                if k < len(ped_times):
                    release_events.append((ped_times[k],))
            i = j
        else:
            i += 1
    return press_events, release_events

def score_byte(times, vals, press_events, release_events):
    if len(times) < MIN_FRAMES:
        return 0, 0, 0, 0, 0
    press_deltas = []
    for peak_t, pre_t, peak_v, pre_pv, win_s, win_e in press_events:
        pre_sig = nearest_at(pre_t, times, vals)
        at_sig  = nearest_at(peak_t, times, vals)
        if pre_sig is not None and at_sig is not None:
            press_deltas.append(at_sig - pre_sig)
    if not press_deltas:
        return 0, 0, 0, 0, 0
    pos = sum(1 for d in press_deltas if d > 0)
    neg = sum(1 for d in press_deltas if d < 0)
    n_press = len(press_deltas)
    dominant = max(pos, neg)
    press_dir = +1 if pos >= neg else -1
    press_consistency = dominant / n_press

    recovery_scores = []
    for (rel_t,) in release_events:
        assoc_press = None
        for pe in press_events:
            if pe[0] <= rel_t + 0.5:
                assoc_press = pe
        if assoc_press is None: continue
        baseline_sig = nearest_at(assoc_press[1], times, vals, max_dt=0.5)
        if baseline_sig is None: continue
        rec_pts = values_in_window(rel_t, rel_t + RECOVERY_WINDOW, times, vals)
        if len(rec_pts) < 2: continue
        first_v, last_v = rec_pts[0][1], rec_pts[-1][1]
        d_first = first_v - baseline_sig
        d_last  = last_v  - baseline_sig
        if abs(d_first) < 2: continue
        moved_toward = abs(d_last) < abs(d_first)
        step = max(1, len(rec_pts) // RECOVERY_STEPS)
        sampled = rec_pts[::step]
        dists = [abs(v - baseline_sig) for _, v in sampled]
        mono_count = sum(1 for a, b in zip(dists, dists[1:]) if b <= a + 2)
        mono_frac = mono_count / max(1, len(dists) - 1)
        recovery_scores.append(1.0 if moved_toward and mono_frac >= 0.6 else 0.0)
    n_release = len(recovery_scores)
    rec_score = sum(recovery_scores) / n_release if n_release > 0 else 0
    return press_consistency, press_dir, rec_score, n_press, n_release

def pearson(ref_times, ref_vals, cand_times, cand_vals):
    cx, cy = [], []
    for rt, rv in zip(ref_times, ref_vals):
        cv = nearest_at(rt, cand_times, cand_vals, max_dt=0.15)
        if cv is not None:
            cx.append(rv)
            cy.append(cv)
    n = len(cx)
    if n < MIN_FRAMES: return 0.0
    mx, my = sum(cx)/n, sum(cy)/n
    sxy = sum((a-mx)*(b-my) for a,b in zip(cx,cy))
    sx = math.sqrt(max(1e-12, sum((a-mx)**2 for a in cx)))
    sy = math.sqrt(max(1e-12, sum((b-my)**2 for b in cy)))
    return sxy / (sx * sy)

# --------------------------------------------------------------- main scan --

def run_scan(cfg):
    LOG     = cfg["path"]
    PT_BUS  = cfg["PT_BUS"]
    GM_BUS1 = cfg["GM_BUS1"]
    GM_BUS2 = cfg["GM_BUS2"]

    print(f"\n=== {cfg['label']} : {LOG} ===", flush=True)
    print("Parsing ...", flush=True)
    bus_data = defaultdict(lambda: defaultdict(list))
    for frame in parse_file(LOG):
        bus_data[frame.bus][frame.arbitration_id].append(
            (frame.timestamp, bytes(frame.data))
        )
    print("Done.", flush=True)

    # Pedal — 16-bit B4-B5 LE to avoid B4 overflow on hard braking
    raw_pedal = sorted(
        (t, d[4] | d[5] << 8) for t, d in bus_data[PT_BUS].get(PEDAL_ID, [])
        if len(d) > 5
    )
    ped_times = [x[0] for x in raw_pedal]
    ped_vals  = [x[1] for x in raw_pedal]

    # EBCM pressure (0x2F9 B5 on Vehicle bus)
    raw_ebcm = sorted(
        (t, d[5]) for t, d in bus_data[GM_BUS1].get(0x2F9, [])
        if len(d) > 5
    )
    ebcm_times = [x[0] for x in raw_ebcm]
    ebcm_vals  = [x[1] for x in raw_ebcm]

    press_events, release_events = find_brake_events(ped_times, ped_vals)
    print(f"Press events: {len(press_events)}, Release: {len(release_events)}", flush=True)

    results = []
    for bus_num in [PT_BUS, GM_BUS1, GM_BUS2]:
        for can_id, entries in sorted(bus_data[bus_num].items()):
            if len(entries) < MIN_FRAMES: continue
            dlc = max(len(d) for _, d in entries)
            for bi in range(dlc):
                raw = sorted((t, d[bi]) for t, d in entries if len(d) > bi)
                if len(raw) < MIN_FRAMES: continue
                if len(set(v for _, v in raw)) < 3: continue
                times = [x[0] for x in raw]
                vals  = [x[1] for x in raw]
                pc, pdir, rc, np_, nr = score_byte(times, vals, press_events, release_events)
                r_ped  = pearson(ped_times, ped_vals, times, vals)
                r_ebcm = pearson(ebcm_times, ebcm_vals, times, vals) if len(ebcm_times) >= MIN_FRAMES else 0.0
                if pc >= 0.55 or rc >= 0.50 or abs(r_ped) >= 0.25 or abs(r_ebcm) >= 0.30:
                    results.append({
                        "bus": bus_num, "id": can_id, "byte": bi,
                        "label": f"Bus{bus_num} 0x{can_id:03X} B{bi}",
                        "press_cons": pc, "press_dir": pdir, "recovery": rc,
                        "pearson_ped": r_ped, "pearson_ebcm": r_ebcm,
                        "n_press": np_, "n_rel": nr,
                        "vmin": min(vals), "vmax": max(vals),
                        # store raw ts for plotting
                        "_times": times, "_vals": vals,
                    })

    results.sort(key=lambda x: -(
        x["press_cons"]*0.4 + x["recovery"]*0.4
        + abs(x["pearson_ped"])*0.1 + abs(x["pearson_ebcm"])*0.1
    ))

    print(f"\n{'Label':<28} {'PrCons':>7} {'Dir':>4} {'RecSc':>6} {'Pr_ped':>8} {'Pr_ebcm':>8} {'np':>4} {'nr':>4} Range")
    print("-" * 95)
    for r in results[:40]:
        dir_s = '+' if r["press_dir"] > 0 else '-'
        print(f"{r['label']:<28} {r['press_cons']:7.3f} {dir_s:>4} {r['recovery']:6.3f} "
              f"{r['pearson_ped']:8.4f} {r['pearson_ebcm']:8.4f} "
              f"{r['n_press']:4} {r['n_rel']:4}  {r['vmin']}-{r['vmax']}")

    return {
        "cfg": cfg,
        "results": results,
        "ped_times": ped_times, "ped_vals": ped_vals,
        "ebcm_times": ebcm_times, "ebcm_vals": ebcm_vals,
        "press_events": press_events, "release_events": release_events,
    }

# --------------------------------------------------------------- plotting --

def plot_scan(scan_data, top_n=TOP_N):
    cfg          = scan_data["cfg"]
    results      = scan_data["results"][:top_n]
    ped_times    = scan_data["ped_times"]
    ped_vals     = scan_data["ped_vals"]
    ebcm_times   = scan_data["ebcm_times"]
    ebcm_vals    = scan_data["ebcm_vals"]
    press_events = scan_data["press_events"]

    n = len(results)
    if n == 0:
        print(f"No candidates to plot for {cfg['label']}")
        return

    ncols = 2
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(18, 4 * nrows), sharex=False)
    axes = axes.flatten() if n > 1 else [axes]

    # time range
    t0 = min(ped_times[0] if ped_times else 0,
             ebcm_times[0] if ebcm_times else 0)
    t1 = max(ped_times[-1] if ped_times else 1,
             ebcm_times[-1] if ebcm_times else 1)

    for ax, res in zip(axes, results):
        times = res["_times"]
        vals  = res["_vals"]

        # shade brake press intervals
        for pe in press_events:
            win_s, win_e = pe[4], pe[5]
            ax.axvspan(win_s, win_e, alpha=0.15, color="red", zorder=0)

        # candidate signal
        ax.plot(times, vals, color="steelblue", linewidth=0.8, label=res["label"])

        # pedal (secondary axis)
        ax2 = ax.twinx()
        ax2.plot(ped_times, ped_vals, color="red", alpha=0.4, linewidth=0.6, label="Pedal")
        ax2.set_ylabel("Pedal", color="red", fontsize=8)
        ax2.tick_params(axis="y", labelcolor="red")
        ax2.set_ylim(-100, 5500)

        # EBCM if present
        if ebcm_times:
            ax3 = ax.twinx()
            ax3.spines["right"].set_position(("axes", 1.10))
            ax3.plot(ebcm_times, ebcm_vals, color="green", alpha=0.5,
                     linewidth=0.6, label="EBCM pres")
            ax3.set_ylabel("EBCM", color="green", fontsize=8)
            ax3.tick_params(axis="y", labelcolor="green")
            ax3.set_ylim(-2, 85)

        dir_s = "+" if res["press_dir"] > 0 else "-"
        title = (f"{res['label']}  PrC={res['press_cons']:.2f}{dir_s}"
                 f"  Rec={res['recovery']:.2f}"
                 f"  r_ped={res['pearson_ped']:.2f}"
                 f"  r_ebcm={res['pearson_ebcm']:.2f}"
                 f"  [{res['vmin']}-{res['vmax']}]")
        ax.set_title(title, fontsize=8)
        ax.set_ylabel("Signal value", fontsize=8)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_xlim(t0, t1)

    # hide unused axes
    for ax in axes[n:]:
        ax.set_visible(False)

    fig.suptitle(f"Brake booster candidates -- {cfg['label']}", fontsize=11, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    out = ARTIFACT_DIR / f"brake_candidates_{cfg['label']}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {out}", flush=True)


# ------------------------------------------------------------- run both --

all_scans = []
for cfg in LOGS:
    sd = run_scan(cfg)
    all_scans.append(sd)

print("\nGenerating plots ...", flush=True)
for sd in all_scans:
    plot_scan(sd)

print("Done.", flush=True)
