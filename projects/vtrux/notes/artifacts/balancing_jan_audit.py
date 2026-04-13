"""
balancing_jan_audit.py

Full balancing audit of the January 2026 charge sessions:
  Jan 16-17: charge_M0   (after-battery-swap-charges/charge_M0_T*)
  Jan 17:    charge_9pm  (after-battery-swap-charges/charge_9pm.log)
  Jan 23:    another_M0  (after-battery-swap-charges/another_M0_T*)
  Jan 25:    vtrux_charge_M1 (logs/vtrux_charge_M1_T*)

For each session: SOC, onset, peak, timeline with vmax/vmin/vavg/spread/cnt.

Usage:
  py -3.12 projects/vtrux/notes/artifacts/balancing_jan_audit.py
"""

import os, sys, re, collections
from pathlib import Path
import cantools

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from canre.utils.merge import merge_files
from canre.utils.sessions import group_files_by_session

DBC_PATH  = os.path.join(PROJECT_ROOT, "projects", "vtrux", "epri-pt-bus.dbc")
LOGS_ROOT = os.path.join(PROJECT_ROOT, "projects", "vtrux", "logs")
SWAP_ROOT = os.path.join(LOGS_ROOT, "after-battery-swap-charges")
PT_BUS_ANCHOR_IDS = {0x410, 0x420, 0x430, 0x440, 0x471}
SAMPLE_LIMIT = 200000


def t_key(path):
    m = re.search(r"_T(\d+)", str(path))
    return int(m.group(1)) if m else 0


def identify_pt_bus(file_paths):
    counts = {}
    for i, frame in enumerate(merge_files(file_paths)):
        if frame.arbitration_id in PT_BUS_ANCHOR_IDS:
            counts[frame.bus] = counts.get(frame.bus, 0) + 1
        if i >= SAMPLE_LIMIT:
            break
    return max(counts, key=counts.get) if counts else None


CELL_COUNT = 116


def process_session(name, files, db):
    file_paths = [str(f) for f in files]
    pt_bus = identify_pt_bus(file_paths)
    if pt_bus is None:
        return None

    msg_410 = db.get_message_by_frame_id(0x410)
    msg_430 = db.get_message_by_frame_id(0x430)
    soc_samples  = []
    vbat_samples = []
    cnt_samples  = []
    spread_ts    = []

    for frame in merge_files(file_paths):
        if frame.bus != pt_bus:
            continue
        t = frame.timestamp
        if frame.arbitration_id == 0x410 and len(frame.data) >= 8:
            raw_soc = frame.data[3]
            if raw_soc < 0xFE:
                soc_samples.append((t, raw_soc * 0.5))
            try:
                dec  = msg_410.decode(frame.data, decode_choices=False)
                vbat = dec.get("bcm_vbat")
                raw_vbat = ((frame.data[6] & 0x0F) << 8) | frame.data[7]
                if vbat is not None and raw_vbat != 0xFFE and vbat > 0:
                    vbat_samples.append((t, vbat))
            except Exception:
                pass
        elif frame.arbitration_id == 0x430 and len(frame.data) >= 4:
            try:
                dec  = msg_430.decode(frame.data, decode_choices=False)
                vmax = dec.get("bcm_cell_vmax")
                vmin = dec.get("bcm_cell_vmin")
                if vmax is not None and vmin is not None and vmax < 8.0 and vmin > 0:
                    spread_ts.append((t, vmax, vmin))
            except Exception:
                pass
        elif frame.arbitration_id == 0x440 and len(frame.data) >= 8:
            raw = frame.data[7]
            if raw < 0xFE:
                cnt_samples.append((t, raw))

    if not soc_samples:
        return None

    return {
        "name":         name,
        "soc_samples":  soc_samples,
        "vbat_samples": vbat_samples,
        "cnt_samples":  cnt_samples,
        "spread_ts":    spread_ts,
        "t0":           soc_samples[0][0],
        "duration_s":   soc_samples[-1][0] - soc_samples[0][0],
        "soc_min":      min(v for _, v in soc_samples),
        "soc_max":      max(v for _, v in soc_samples),
    }


def nearest_spread(spread_ts, t):
    if not spread_ts:
        return None, None
    _, vmax, vmin = min(spread_ts, key=lambda x: abs(x[0] - t))
    return vmax * 1000, vmin * 1000


def report_session(s):
    name = s["name"]
    t0   = s["t0"]
    dur  = s["duration_s"] / 60

    print(f"\n{'='*75}")
    print(f"Session: {name}")
    print(f"  Duration: {dur:.0f} min  |  SOC: {s['soc_min']:.1f}% -> {s['soc_max']:.1f}%")

    cnt_vals = [c for _, c in s["cnt_samples"]]
    if not cnt_vals:
        print("  No bcm_balancing_cnt data.")
        return

    nonzero = [(t, c) for t, c in s["cnt_samples"] if c > 0]
    if not nonzero:
        print("  bcm_balancing_cnt = 0 throughout (no balancing).")
        if s["spread_ts"]:
            all_spreads = [(vx - vn) * 1000 for _, vx, vn in s["spread_ts"]]
            print(f"  Spread (vmax-vmin): min={min(all_spreads):.0f} mV  max={max(all_spreads):.0f} mV  mean={sum(all_spreads)/len(all_spreads):.0f} mV")
        return

    onset_t, onset_c = nonzero[0]
    last_t,  last_c  = nonzero[-1]
    peak_t,  peak_c  = max(s["cnt_samples"], key=lambda x: x[1])
    onset_soc = min(s["soc_samples"], key=lambda x: abs(x[0] - onset_t))[1]
    onset_vmax, onset_vmin = nearest_spread(s["spread_ts"], onset_t)

    print(f"  Onset: t+{onset_t - t0:.0f}s ({(onset_t-t0)/60:.1f} min)  cnt={onset_c}  SOC~{onset_soc:.1f}%", end="")
    if onset_vmax:
        print(f"  vmax={onset_vmax:.0f} mV  vmin={onset_vmin:.0f} mV  spread={(onset_vmax-onset_vmin):.0f} mV")
    else:
        print()
    print(f"  Peak:  t+{peak_t - t0:.0f}s ({(peak_t-t0)/60:.1f} min)  cnt={peak_c}")
    print(f"  Last non-zero: t+{last_t - t0:.0f}s ({(last_t-t0)/60:.1f} min)")

    dist = collections.Counter(cnt_vals)
    total_nonzero = sum(v for k, v in dist.items() if k > 0)
    print(f"  Total non-zero cnt frames: {total_nonzero}")
    print(f"  Notable count values (>2% of non-zero frames or known spikes):")
    NOTABLE = {1, 12, 52, 103, 104, 115, 116}
    for val in sorted(k for k in dist if k > 0):
        pct = dist[val] / total_nonzero * 100
        if pct >= 2.0 or val in NOTABLE:
            bar = "#" * int(pct / 0.5)
            print(f"    cnt={val:3d}: {dist[val]:6d}  ({pct:5.1f}%)  {bar}")

    print(f"\n  Timeline (10-min buckets):")
    print(f"  {'t+':>6}  {'SOC':>6}  {'vavg mV':>8}  {'vmid mV':>8}  {'spread mV':>10}  {'cnt_mean':>9}  {'cnt_max':>8}")
    print(f"  {'':>6}  {'':>6}  {'vbat/116':>8}  {'(vmax+vmin)/2':>8}")

    soc_b  = {}
    cnt_b  = {}
    vmax_b = {}
    vmin_b = {}
    vbat_b = {}

    for t, v in s["soc_samples"]:
        b = int((t - t0) / 600)
        soc_b.setdefault(b, []).append(v)
    for t, c in s["cnt_samples"]:
        b = int((t - t0) / 600)
        cnt_b.setdefault(b, []).append(c)
    for t, vx, vn in s["spread_ts"]:
        b = int((t - t0) / 600)
        vmax_b.setdefault(b, []).append(vx * 1000)
        vmin_b.setdefault(b, []).append(vn * 1000)
    for t, vb in s["vbat_samples"]:
        b = int((t - t0) / 600)
        vbat_b.setdefault(b, []).append(vb)

    all_b = sorted(set(list(soc_b) + list(cnt_b) + list(vmax_b)))
    for b in all_b:
        sv   = soc_b.get(b, [])
        cv   = cnt_b.get(b, [])
        vxv  = vmax_b.get(b, [])
        vnv  = vmin_b.get(b, [])
        vbv  = vbat_b.get(b, [])
        avg_soc  = f"{sum(sv)/len(sv):.1f}%" if sv else "   n/a"
        avg_cnt  = f"{sum(cv)/len(cv):.1f}"  if cv else "n/a"
        max_cnt  = f"{max(cv)}"               if cv else "n/a"
        if vbv:
            vavg_s = f"{sum(vbv)/len(vbv)/CELL_COUNT*1000:.0f}"
        else:
            vavg_s = "n/a"
        if vxv and vnv:
            vmid   = (sum(vxv)/len(vxv) + sum(vnv)/len(vnv)) / 2
            spread = sum(vxv)/len(vxv) - sum(vnv)/len(vnv)
            vmid_s   = f"{vmid:.0f}"
            spread_s = f"{spread:.0f}"
        else:
            vmid_s = spread_s = "n/a"
        print(f"  t+{b*10:>4}min  {avg_soc:>6}  {vavg_s:>8}  {vmid_s:>8}  {spread_s:>10}  {avg_cnt:>9}  {max_cnt:>8}")


def main():
    print("Loading DBC...")
    db = cantools.database.load_file(DBC_PATH)

    sessions = []
    swap_groups = group_files_by_session(Path(SWAP_ROOT))
    session_labels = {
        "M0":         "charge_M0   (Jan 16-17)",
        "charge_9pm": "charge_9pm  (Jan 17)",
        "M0_b":       "another_M0  (Jan 23)",
    }
    for gname, files in sorted(swap_groups.items()):
        label = session_labels.get(gname, gname)
        sessions.append((label, files))

    jan25_files = sorted(Path(LOGS_ROOT).glob("vtrux_charge_M1_T*.log"), key=t_key)
    if jan25_files:
        sessions.append(("vtrux_charge_M1 (Jan 25)", jan25_files))

    print(f"Sessions: {[s[0] for s in sessions]}")
    print("Processing...\n")

    for name, files in sessions:
        print(f"  {name} ({len(files)} file(s))...")
        s = process_session(name, files, db)
        if s:
            report_session(s)
        else:
            print(f"  [{name}] no data.")


if __name__ == "__main__":
    main()
