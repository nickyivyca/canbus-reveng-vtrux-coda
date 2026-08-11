"""
engine_gen_torque_correlation.py

Correlate ECM Engine_Torque_Actual_Extended_Range (0x1C3, OBD bus)
with generator motor torque feedback GENE_Mot_Trq (0x471, PT bus)
across the evap drive logs.

Phase 1: log parsing -> save aligned CSV cache (skipped on re-runs)
Phase 2: combined Pearson r + windowed correlation
Phase 3: timeseries + windowed-r + scatter plots
Phase 4: regime-separated analysis (starting / generating / idling)

Regime thresholds (based on GENE_Mot_Trq):
  STARTING  : gene_torque >  +20 Nm  (generator driving engine during engine start)
  GENERATING: gene_torque <  -30 Nm  (generator under significant generating load)
  IDLING    : -30 <= gene_torque <= +20 Nm  (low load, transitional, engine-off coast)
"""

import sys, glob, math, csv, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cantools

sys.path.insert(0, r"<repo>")
from canre.parsers import parse_file

base     = r"<repo>\projects\vtrux"
logs_dir = base + r"\logs"
out_dir  = base + r"\notes\artifacts"
CACHE    = out_dir + r"\engine_gen_torque_aligned.csv"

pt_db    = cantools.database.load_file(base + r"\epri-pt-bus.dbc")
gmlan_db = cantools.database.load_file(base + r"\GMW8762_PPEI_GMLAN.dbc")

LOGS = sorted(
    glob.glob(logs_dir + r"\vtruxevapdrivelog*.log") +
    glob.glob(logs_dir + r"\vtruxanotherevaplog*.log")
)
LOGS = [l for l in LOGS if "batteryonly" not in l]

ID_ENG_TRQ  = 0x1C3
ID_GENE_TRQ = 0x471
ID_GENE_RPM = 0x054
OBD_ANCHORS = set(range(0x040, 0x045))
GRID_DT     = 0.05

THR_STARTING   = +20.0
THR_GENERATING = -30.0

def forward_fill(samples, t_grid):
    result = []
    idx = 0
    last_v = None
    for tg in t_grid:
        while idx < len(samples) and samples[idx][0] <= tg:
            last_v = samples[idx][1]
            idx += 1
        result.append(last_v)
    return result

def pearsonr(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dxs = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dys = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dxs == 0 or dys == 0:
        return None
    return num / (dxs * dys)

def regime(gene_torque):
    if gene_torque > THR_STARTING:
        return "starting"
    if gene_torque < THR_GENERATING:
        return "generating"
    return "idling"

# ======================================================================
# Phase 1: Parse logs OR load cache
# ======================================================================

if os.path.exists(CACHE):
    print(f"Loading aligned cache: {CACHE}")
    rows = []
    with open(CACHE, newline='') as f:
        for row in csv.DictReader(f):
            rows.append((float(row['t']), float(row['eng']), float(row['gene'])))
    t_vals  = [r[0] for r in rows]
    xs_all  = [r[1] for r in rows]
    ys_all  = [r[2] for r in rows]
    print(f"  Loaded {len(rows)} aligned pairs")
    per_log_stats = []   # not available from cache

else:
    print("Cache not found -- parsing logs ...")
    all_eng  = []
    all_gene = []
    t_offset = 0.0
    per_log_stats = []

    for LOG in LOGS:
        logname = LOG.split("\\")[-1]
        print(f"Reading {logname} ...")

        eng_samples  = []
        gene_samples = []
        obd_channel  = None
        t_min        = None

        for frame in parse_file(LOG):
            ts  = frame.timestamp
            aid = frame.arbitration_id
            d   = bytes(frame.data)
            if t_min is None:
                t_min = ts
            if obd_channel is None and aid in OBD_ANCHORS:
                obd_channel = frame.bus
            if aid == ID_ENG_TRQ and len(d) >= 4:
                if obd_channel is not None and frame.bus != obd_channel:
                    continue
                try:
                    sig   = gmlan_db.decode_message(aid, d)
                    v     = sig.get("Engine_Torque_Actual_Extended_Range")
                    valid = sig.get("Engine_Torque_Actual_Extended_Range_Validity", 1)
                    if v is not None and valid:
                        eng_samples.append((ts, v))
                except Exception:
                    pass
            elif aid == ID_GENE_TRQ:
                try:
                    sig = pt_db.decode_message(aid, d)
                    v   = sig.get("GENE_Mot_Trq")
                    if v is not None:
                        gene_samples.append((ts, v))
                except Exception:
                    pass

        if not eng_samples or not gene_samples:
            print(f"  WARNING: missing data -- skipping")
            continue

        t_max  = max(eng_samples[-1][0], gene_samples[-1][0])
        t_span = t_max - t_min
        t_grid = [t_min + i * GRID_DT for i in range(int(t_span / GRID_DT) + 1)]

        eng_ff  = forward_fill(eng_samples,  t_grid)
        gene_ff = forward_fill(gene_samples, t_grid)

        pairs = [(e, g) for e, g in zip(eng_ff, gene_ff) if e is not None and g is not None]
        if len(pairs) < 20:
            print(f"  Too few aligned pairs -- skipping")
            continue

        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        r  = pearsonr(xs, ys)
        r_str = f"{r:.4f}" if r is not None else "N/A (zero variance)"

        print(f"  eng torque:  min={min(xs):.1f} max={max(xs):.1f} Nm  ({len(eng_samples)} samples)")
        print(f"  gene torque: min={min(ys):.1f} max={max(ys):.1f} Nm  ({len(gene_samples)} samples)")
        print(f"  Pearson r = {r_str}  (n={len(pairs)} aligned pairs)")

        per_log_stats.append({
            "log": logname, "r": r, "n": len(pairs),
            "eng_min": min(xs), "eng_max": max(xs),
            "gene_min": min(ys), "gene_max": max(ys),
        })

        offset = t_offset - t_min
        for ts, v in eng_samples:
            all_eng.append((ts + offset, v))
        for ts, v in gene_samples:
            all_gene.append((ts + offset, v))
        t_offset += t_span + 10.0

    t_all_min = min(all_eng[0][0], all_gene[0][0])
    t_all_max = max(all_eng[-1][0], all_gene[-1][0])
    t_all_grid = [t_all_min + i * GRID_DT for i in range(int((t_all_max - t_all_min) / GRID_DT) + 1)]

    eng_ff_all  = forward_fill(sorted(all_eng),  t_all_grid)
    gene_ff_all = forward_fill(sorted(all_gene), t_all_grid)

    rows_out = [(t, e, g) for t, e, g in zip(t_all_grid, eng_ff_all, gene_ff_all)
                if e is not None and g is not None]
    t_vals = [r[0] for r in rows_out]
    xs_all = [r[1] for r in rows_out]
    ys_all = [r[2] for r in rows_out]

    with open(CACHE, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['t', 'eng', 'gene'])
        for t, e, g in rows_out:
            w.writerow([f"{t:.4f}", f"{e:.3f}", f"{g:.3f}"])
    print(f"Saved cache: {CACHE}  ({len(rows_out)} rows)")

# ======================================================================
# Phase 2: Combined Pearson r + windowed correlation
# ======================================================================

print("\n---- Combined across all logs ----")
r_all = pearsonr(xs_all, ys_all)
r_all_str = f"{r_all:.4f}" if r_all is not None else "N/A"
print(f"Combined Pearson r = {r_all_str}  (n={len(xs_all)} pairs)")
print(f"Eng torque range:  {min(xs_all):.1f} to {max(xs_all):.1f} Nm")
print(f"Gene torque range: {min(ys_all):.1f} to {max(ys_all):.1f} Nm")

WINDOW_S = 60.0
STEP_S   = 30.0
print(f"\n---- Windowed Pearson r (window={WINDOW_S}s, step={STEP_S}s) ----")
paired = list(zip(t_vals, xs_all, ys_all))
win_results = []
i_start = 0
t_w = t_vals[0]
while t_w + WINDOW_S <= t_vals[-1]:
    while i_start < len(paired) and paired[i_start][0] < t_w:
        i_start += 1
    i_end = i_start
    while i_end < len(paired) and paired[i_end][0] <= t_w + WINDOW_S:
        i_end += 1
    chunk = paired[i_start:i_end]
    if len(chunk) >= 10:
        r_w = pearsonr([p[1] for p in chunk], [p[2] for p in chunk])
        win_results.append((t_w, r_w, len(chunk)))
    t_w += STEP_S

if win_results:
    rs = [r for _, r, _ in win_results if r is not None]
    print(f"  Window r: min={min(rs):.4f}  max={max(rs):.4f}  mean={sum(rs)/len(rs):.4f}  n_windows={len(rs)}")

# ======================================================================
# Phase 3: Timeseries + windowed-r + scatter plots
# ======================================================================

print("\nGenerating Phase 3 plots ...")

t0 = t_vals[0]

fig, axes = plt.subplots(3, 1, figsize=(16, 10))
fig.suptitle("Engine Torque (0x1C3 OBD) vs Generator Motor Torque (0x471)\nCombined evap drive logs", fontsize=11)

ax0_e = axes[0]
ax0_g = axes[0].twinx()
ax0_e.plot([t - t0 for t in t_vals], xs_all, color="steelblue",  lw=0.6, alpha=0.8, label="Eng torque actual (Nm)")
ax0_g.plot([t - t0 for t in t_vals], ys_all, color="darkorange", lw=0.6, alpha=0.8, label="Gen motor torque Fbk (Nm)")
ax0_e.set_ylabel("Engine Torque (Nm)", color="steelblue")
ax0_g.set_ylabel("Generator Torque (Nm)", color="darkorange")
ax0_e.axhline(0, color="gray", lw=0.5)
lines1, labs1 = ax0_e.get_legend_handles_labels()
lines2, labs2 = ax0_g.get_legend_handles_labels()
ax0_e.legend(lines1 + lines2, labs1 + labs2, fontsize=8, loc="upper left")
ax0_e.set_xlabel("Time (s)")
ax0_e.set_title(f"Timeseries overlay (combined r={r_all_str})")

ax1 = axes[1]
if win_results:
    wt = [t - t0 for t, r, _ in win_results if r is not None]
    wr = [r       for _, r, _ in win_results if r is not None]
    ax1.plot(wt, wr, color="purple", lw=1.2, marker=".", ms=3)
    ax1.axhline(0,    color="gray",  lw=0.5)
    ax1.axhline(0.8,  color="green", lw=0.5, ls="--", label="r=+0.8")
    ax1.axhline(-0.8, color="red",   lw=0.5, ls="--", label="r=-0.8")
    ax1.set_ylabel("Pearson r"); ax1.set_xlabel("Window start time (s)")
    ax1.set_title(f"Windowed Pearson r ({WINDOW_S}s windows, {STEP_S}s step)")
    ax1.set_ylim(-1.05, 1.05); ax1.legend(fontsize=8)

ax2 = axes[2]
ax2.scatter(xs_all, ys_all, s=1, alpha=0.15, color="teal")
ax2.set_xlabel("Engine Torque Actual (Nm)"); ax2.set_ylabel("Generator Motor Torque Fbk (Nm)")
ax2.axhline(0, color="gray", lw=0.5); ax2.axvline(0, color="gray", lw=0.5)
ax2.set_title(f"Scatter: all regimes combined  (r={r_all_str}, n={len(xs_all)})")

plt.tight_layout()
plt.savefig(out_dir + r"\engine_gen_torque_correlation.png", dpi=120)
plt.close()
print(f"  Saved engine_gen_torque_correlation.png")

# ======================================================================
# Phase 4: Regime-separated analysis
# ======================================================================

print("\n======================================================================")
print("Phase 4: Regime-separated analysis")
print(f"  STARTING   threshold: gene_torque > {THR_STARTING:+.0f} Nm")
print(f"  GENERATING threshold: gene_torque < {THR_GENERATING:+.0f} Nm")
print(f"  IDLING     threshold: {THR_GENERATING:+.0f} <= gene_torque <= {THR_STARTING:+.0f} Nm")
print("======================================================================\n")

regimes = {"starting": [], "generating": [], "idling": []}
for e, g in zip(xs_all, ys_all):
    regimes[regime(g)].append((e, g))

REGIME_COLORS = {"starting": "firebrick", "generating": "steelblue", "idling": "goldenrod"}

for name, pairs in regimes.items():
    if not pairs:
        print(f"  {name}: no data")
        continue
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    r  = pearsonr(xs, ys)
    r_s = f"{r:.4f}" if r is not None else "N/A"
    print(f"  {name.upper():12s}  n={len(pairs):7d}  r={r_s}")
    print(f"    eng  torque: {min(xs):+7.1f} to {max(xs):+7.1f} Nm  (mean={sum(xs)/len(xs):+6.1f})")
    print(f"    gene torque: {min(ys):+7.1f} to {max(ys):+7.1f} Nm  (mean={sum(ys)/len(ys):+6.1f})")
    print()

print("---- Windowed r split by dominant regime ----")
REGIME_WIN_S = 30.0
REGIME_STEP_S = 15.0
win_by_regime = {"starting": [], "generating": [], "idling": []}

i_start = 0
t_w = t_vals[0]
while t_w + REGIME_WIN_S <= t_vals[-1]:
    while i_start < len(paired) and paired[i_start][0] < t_w:
        i_start += 1
    i_end = i_start
    while i_end < len(paired) and paired[i_end][0] <= t_w + REGIME_WIN_S:
        i_end += 1
    chunk = paired[i_start:i_end]
    if len(chunk) < 8:
        t_w += REGIME_STEP_S
        continue
    gene_vals = [p[2] for p in chunk]
    counts = {"starting": 0, "generating": 0, "idling": 0}
    for g in gene_vals:
        counts[regime(g)] += 1
    dominant = max(counts, key=lambda k: counts[k])
    frac = counts[dominant] / len(chunk)
    if frac >= 0.7:
        r_w = pearsonr([p[1] for p in chunk], gene_vals)
        if r_w is not None:
            win_by_regime[dominant].append((t_w, r_w, len(chunk), frac))
    t_w += REGIME_STEP_S

for name, wins in win_by_regime.items():
    if not wins:
        print(f"  {name}: no qualifying windows")
        continue
    rs = [r for _, r, _, _ in wins]
    print(f"  {name.upper():12s}  n_windows={len(wins):4d}  "
          f"r: min={min(rs):+.4f}  max={max(rs):+.4f}  mean={sum(rs)/len(rs):+.4f}")

print("\nGenerating Phase 4 regime plot ...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("Engine vs Generator Torque -- Regime-Separated Analysis\n"
             f"Starting: gene > {THR_STARTING:+.0f} Nm  |  "
             f"Generating: gene < {THR_GENERATING:+.0f} Nm  |  "
             f"Idling: between", fontsize=10)

regime_order = [("generating", axes[0, 0]), ("starting", axes[0, 1]),
                ("idling",     axes[1, 0])]

for name, ax in regime_order:
    pairs = regimes[name]
    color = REGIME_COLORS[name]
    if not pairs:
        ax.set_title(f"{name.upper()} -- no data")
        continue
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    r  = pearsonr(xs, ys)
    r_s = f"{r:.4f}" if r is not None else "N/A"
    ax.scatter(xs, ys, s=1, alpha=0.15, color=color)
    ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
    ax.set_xlabel("Engine Torque Actual (Nm)")
    ax.set_ylabel("Generator Motor Torque Fbk (Nm)")
    ax.set_title(f"{name.upper()}  r={r_s}  n={len(pairs):,}")

ax_win = axes[1, 1]
for name, wins in win_by_regime.items():
    if not wins:
        continue
    wt = [t - t0 for t, _, _, _ in wins]
    wr = [r       for _, r, _, _ in wins]
    ax_win.scatter(wt, wr, s=8, alpha=0.6, color=REGIME_COLORS[name], label=name)
ax_win.axhline(0,    color="gray",  lw=0.5)
ax_win.axhline(-0.8, color="red",   lw=0.5, ls="--")
ax_win.axhline(0.8,  color="green", lw=0.5, ls="--")
ax_win.set_ylim(-1.05, 1.05)
ax_win.set_xlabel("Window start time (s)")
ax_win.set_ylabel("Pearson r")
ax_win.set_title(f"Windowed r by dominant regime ({REGIME_WIN_S}s windows, >=70% pure)")
ax_win.legend(fontsize=8)

plt.tight_layout()
plt.savefig(out_dir + r"\engine_gen_torque_regime.png", dpi=120)
plt.close()
print(f"  Saved engine_gen_torque_regime.png")

if per_log_stats:
    print("\n---- Per-log summary ----")
    for s in per_log_stats:
        r_s = f"{s['r']:+.4f}" if s['r'] is not None else "   N/A  "
        print(f"  {s['log']:40s}  r={r_s}  n={s['n']:6d}  "
              f"eng=[{s['eng_min']:.0f},{s['eng_max']:.0f}]  "
              f"gene=[{s['gene_min']:.0f},{s['gene_max']:.0f}] Nm")

# ======================================================================
# Phase 5: Sign-flipped overlay — engine torque vs -gene torque on same axis
# ======================================================================

print("\nGenerating Phase 5 sign-flipped overlay ...")

gene_neg = [-g for g in ys_all]

r_flip = pearsonr(xs_all, gene_neg)
r_flip_str = f"{r_flip:.4f}" if r_flip is not None else "N/A"

residuals = [e - g for e, g in zip(xs_all, gene_neg)]

gen_pairs = [(e, gn, e - gn) for e, g, gn in zip(xs_all, ys_all, gene_neg)
             if g < THR_GENERATING]
res_mean = sum(r for _, _, r in gen_pairs) / len(gen_pairs)
res_std  = math.sqrt(sum((r - res_mean) ** 2 for _, _, r in gen_pairs) / len(gen_pairs))
print(f"  Residual (eng - gene*-1), generating regime only (n={len(gen_pairs)}): "
      f"mean={res_mean:+.2f} Nm  std={res_std:.2f} Nm")

log_names = ", ".join(l.split("\\")[-1].replace(".log", "") for l in LOGS)

fig, axes = plt.subplots(3, 1, figsize=(16, 11))
fig.suptitle(f"Engine Torque vs Generator Torque * -1 (sign-flipped, same axis)\n"
             f"Logs: {log_names}", fontsize=9)

ax0 = axes[0]
ax0.plot([t - t0 for t in t_vals], xs_all,   color="steelblue",  lw=0.6, alpha=0.85, label="Engine torque actual (Nm)")
ax0.plot([t - t0 for t in t_vals], gene_neg, color="darkorange", lw=0.6, alpha=0.85, label="Generator motor torque Fbk * -1 (Nm)")
ax0.axhline(0, color="gray", lw=0.5)
ax0.set_ylabel("Torque (Nm)")
ax0.set_xlabel("Time (s)")
ax0.legend(fontsize=8, loc="upper left")
ax0.set_title(f"Timeseries overlay  (r={r_flip_str} on flipped pair)")

ax1 = axes[1]
ax1.plot([t - t0 for t in t_vals], residuals, color="crimson", lw=0.6, alpha=0.8)
ax1.axhline(0,        color="gray",   lw=0.8)
ax1.axhline(res_mean, color="purple", lw=1.0, ls="--", label=f"mean offset {res_mean:+.1f} Nm")
ax1.set_ylabel("Residual: eng - (gene * -1) (Nm)")
ax1.set_xlabel("Time (s)")
ax1.set_title(f"Residual  -- generating regime stats: mean={res_mean:+.1f} Nm, std={res_std:.1f} Nm")
ax1.legend(fontsize=8)

ax2 = axes[2]
lim_lo = min(min(xs_all), min(gene_neg))
lim_hi = max(max(xs_all), max(gene_neg))
ax2.scatter(xs_all, gene_neg, s=1, alpha=0.15, color="teal")
ax2.plot([lim_lo, lim_hi], [lim_lo, lim_hi], color="red", lw=1.0, ls="--", label="y = x")
ax2.axhline(0, color="gray", lw=0.4); ax2.axvline(0, color="gray", lw=0.4)
ax2.set_xlabel("Engine Torque Actual (Nm)")
ax2.set_ylabel("Generator Motor Torque Fbk * -1 (Nm)")
ax2.set_title(f"Scatter vs y=x  (r={r_flip_str}, n={len(xs_all):,})")
ax2.legend(fontsize=8)
ax2.set_aspect("equal", adjustable="datalim")

plt.tight_layout()
plots_dir = base + r"\notes\plots"
plt.savefig(plots_dir + r"\engine_gen_torque_flipped.png", dpi=120)
plt.close()
print(f"  Saved plots/engine_gen_torque_flipped.png")

print("\nDone.")
