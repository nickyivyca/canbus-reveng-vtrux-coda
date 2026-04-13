"""
i2t_bms_correlation.py

Compute cumulative I^2*t from battery current (0x598 B0-B1) and correlate
each variable byte of 0x370-0x374 against it to identify BMS temperature signals.

Primary log: vtruxcurrentlimitingtest.log
Usage: py -3.12 i2t_bms_correlation.py [--log <path>] [--out <csv>]
"""
import sys
import math
import csv
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from canre.parsers.autodetect import parse_file

DEFAULT_LOG = ROOT / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"

# Variable bytes to test in each BMS ID (from thermal-investigation.md Phase 2A)
BMS_CANDIDATES = {
    0x370: [0, 1, 4, 6],
    0x371: [0, 1, 4, 6],
    0x372: [0, 2, 4, 5],
    0x373: [1, 3, 4],
    0x374: [0, 1, 4, 6],
}

CURRENT_ID = 0x598   # Battery current B0-B1, LE uint16, centered at 32768
ANCHOR_ID  = 0x051   # PT bus anchor

# Maximum dt to include in I^2*t integration (caps logging gaps)
MAX_DT = 5.0


def pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return float('nan')
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return float('nan')
    return num / (den_x * den_y)


def interp_i2t(i2t_series, t_query):
    """Linearly interpolate cumulative I^2*t series at t_query."""
    if not i2t_series or t_query <= i2t_series[0][0]:
        return 0.0
    if t_query >= i2t_series[-1][0]:
        return i2t_series[-1][1]
    lo, hi = 0, len(i2t_series) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if i2t_series[mid][0] <= t_query:
            lo = mid
        else:
            hi = mid
    t0, v0 = i2t_series[lo][0], i2t_series[lo][1]
    t1, v1 = i2t_series[hi][0], i2t_series[hi][1]
    alpha = (t_query - t0) / (t1 - t0)
    return v0 + alpha * (v1 - v0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--out", default=None, help="Output CSV (optional)")
    args = ap.parse_args()

    log_path = Path(args.log)
    print("Log: {}".format(log_path.name))

    # --- Pass 1: collect all frames ---
    bus_ids = {}          # bus -> set of arbitration IDs seen
    frames_by_key = {}    # (bus, arb_id) -> [(t, data), ...]

    for frame in parse_file(log_path):
        b = frame.bus
        aid = frame.arbitration_id
        bus_ids.setdefault(b, set()).add(aid)
        key = (b, aid)
        frames_by_key.setdefault(key, []).append((frame.timestamp, bytes(frame.data)))

    # --- Identify PT bus ---
    pt_bus = None
    for bus, ids in bus_ids.items():
        if ANCHOR_ID in ids:
            pt_bus = bus
            break

    if pt_bus is None:
        print("ERROR: PT bus not found (0x051 missing). Buses seen: {}".format(
            sorted(bus_ids.keys())))
        sys.exit(1)

    print("PT bus = {} (0x051 present)".format(pt_bus))
    print("Buses in log: {} (unique IDs: {})".format(
        sorted(bus_ids.keys()),
        {b: len(ids) for b, ids in bus_ids.items()}))

    # Report where BMS IDs appear
    print()
    print("BMS ID locations:")
    for bid in [0x370, 0x371, 0x372, 0x373, 0x374, 0x375]:
        found = []
        for bus in sorted(bus_ids.keys()):
            key = (bus, bid)
            if key in frames_by_key:
                ct = len(frames_by_key[key])
                found.append("bus{} ({} frames)".format(bus, ct))
        if found:
            print("  0x{:03X}: {}".format(bid, ", ".join(found)))
        else:
            print("  0x{:03X}: NOT FOUND".format(bid))

    # --- Build battery current timeseries on PT bus ---
    cur_key = (pt_bus, CURRENT_ID)
    cur_frames = sorted(frames_by_key.get(cur_key, []), key=lambda x: x[0])
    if not cur_frames:
        print("ERROR: No 0x598 frames on PT bus {}".format(pt_bus))
        sys.exit(1)

    print()
    print("Battery current (0x598) on PT bus: {} frames".format(len(cur_frames)))

    # Build I^2*t series: (t, cumulative_i2t, i_centered)
    i2t_series = []
    cum_i2t = 0.0
    prev_t = None

    for t, data in cur_frames:
        if len(data) < 2:
            continue
        raw = data[0] | (data[1] << 8)
        i_c = raw - 32768          # centered; positive=discharge, negative=regen
        i_sq = float(i_c * i_c)    # always non-negative

        if prev_t is not None:
            dt = t - prev_t
            if 0 < dt <= MAX_DT:
                cum_i2t += i_sq * dt

        i2t_series.append((t, cum_i2t, i_c))
        prev_t = t

    if len(i2t_series) < 10:
        print("ERROR: Too few current samples ({})".format(len(i2t_series)))
        sys.exit(1)

    t_start = i2t_series[0][0]
    t_end   = i2t_series[-1][0]
    duration = t_end - t_start
    max_i2t  = i2t_series[-1][1]
    i_vals   = [s[2] for s in i2t_series]
    max_disch = max(i_vals)
    max_regen = min(i_vals)

    n_pos  = sum(1 for v in i_vals if v > 100)
    n_neg  = sum(1 for v in i_vals if v < -100)
    n_zero = len(i_vals) - n_pos - n_neg

    print("Duration: {:.1f}s".format(duration))
    print("Max discharge: {:+} cts ({:.1f} A at 0.04 A/ct)".format(
        max_disch, max_disch * 0.04))
    print("Max regen:     {:+} cts ({:.1f} A at 0.04 A/ct)".format(
        max_regen, max_regen * 0.04))
    print("Sample split: {:.0f}% discharge / {:.0f}% regen / {:.0f}% near-zero".format(
        100*n_pos/len(i_vals), 100*n_neg/len(i_vals), 100*n_zero/len(i_vals)))
    print("Cumulative I^2*t: {:.3e} count^2*s".format(max_i2t))

    # --- Correlate BMS candidates ---
    results = []

    for can_id, byte_list in sorted(BMS_CANDIDATES.items()):
        # Find frames for this ID on any bus
        best_bus = None
        best_frames = []
        for bus in sorted(bus_ids.keys()):
            key = (bus, can_id)
            if key in frames_by_key and len(frames_by_key[key]) > len(best_frames):
                best_frames = frames_by_key[key]
                best_bus = bus

        if not best_frames:
            for b in byte_list:
                results.append(dict(id=can_id, byte=b, bus=None, r=float('nan'),
                                    unique=0, rng=0, vmin=0, vmax=0, n=0,
                                    mono=0.0, first=0, last=0))
            continue

        best_frames = sorted(best_frames, key=lambda x: x[0])

        for b in byte_list:
            bvals = []
            i2t_at = []

            for t, data in best_frames:
                if len(data) <= b:
                    continue
                val = data[b]
                i2t_at.append(interp_i2t(i2t_series, t))
                bvals.append(val)

            if len(bvals) < 5:
                results.append(dict(id=can_id, byte=b, bus=best_bus, r=float('nan'),
                                    unique=0, rng=0, vmin=0, vmax=0, n=len(bvals),
                                    mono=0.0, first=0, last=0))
                continue

            r = pearson_r(i2t_at, bvals)
            uniq = len(set(bvals))
            vmin, vmax = min(bvals), max(bvals)

            # Monotonicity: fraction of steps that are increases
            rises = sum(1 for a, b_ in zip(bvals, bvals[1:]) if b_ > a)
            drops = sum(1 for a, b_ in zip(bvals, bvals[1:]) if b_ < a)
            mono = rises / max(rises + drops, 1)

            results.append(dict(
                id=can_id, byte=b, bus=best_bus, r=r,
                unique=uniq, rng=vmax - vmin, vmin=vmin, vmax=vmax,
                n=len(bvals), mono=mono,
                first=bvals[0], last=bvals[-1],
            ))

    # Sort by |r| descending
    results.sort(key=lambda x: -abs(x['r']) if not math.isnan(x['r']) else -1)

    print()
    print("=== I^2*t Correlation Results (sorted by |r|) ===")
    hdr = "{:<10} {:>4} {:>3} {:>6} {:>6} {:>5} {:>5} {:>5} {:>5} {:>5} {:>6}"
    print(hdr.format("ID", "B", "bus", "r", "n", "uniq", "range", "min", "last", "1st", "mono%"))
    print("-" * 75)
    for res in results:
        r_str = "{:+.3f}".format(res['r']) if not math.isnan(res['r']) else "   nan"
        print(hdr.format(
            "0x{:03X}".format(res['id']),
            res['byte'],
            str(res['bus']) if res['bus'] is not None else "-",
            r_str,
            res['n'],
            res['unique'],
            res['rng'],
            res['vmin'],
            res['last'],
            res['first'],
            "{:.0f}%".format(res['mono']*100),
        ))

    print()
    print("=== Temperature candidates: |r| > 0.7, unique > 2 ===")
    top = [r for r in results
           if not math.isnan(r['r']) and abs(r['r']) > 0.7 and r['unique'] > 2]
    if not top:
        print("  None. |r| > 0.5 candidates:")
        top = [r for r in results
               if not math.isnan(r['r']) and abs(r['r']) > 0.5 and r['unique'] > 2]

    if not top:
        print("  None found.")
    else:
        for res in top:
            # Try x-40 OBD-style encoding
            note = ""
            if res['vmin'] > 30:
                note = " [{}-{}degC @ x-40]".format(res['vmin']-40, res['vmax']-40)
            elif res['vmin'] > 0:
                note = " [{:.1f}-{:.1f}degC @ x0.1]".format(
                    res['vmin']*0.1, res['vmax']*0.1)
            print("  0x{:03X} B{}: r={:+.3f}, {}->{} raw (range {}), "
                  "mono={:.0f}%{}".format(
                res['id'], res['byte'], res['r'],
                res['first'], res['last'], res['rng'],
                res['mono']*100, note))

    # --- Optional CSV output ---
    if args.out:
        out_path = Path(args.out)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Header: time, i_centered, cum_i2t, then one col per BMS candidate
            bms_keys = []
            bms_data = {}  # label -> {t: val}

            for can_id, byte_list in sorted(BMS_CANDIDATES.items()):
                for bst in bus_ids.keys():
                    key = (bst, can_id)
                    if key in frames_by_key:
                        for b in byte_list:
                            label = "0x{:03X}_B{}".format(can_id, b)
                            bms_keys.append(label)
                            bms_data[label] = {
                                t: data[b]
                                for t, data in frames_by_key[key]
                                if len(data) > b
                            }
                        break

            writer.writerow(["time_s", "i_centered", "cum_i2t"] + bms_keys)

            # Write at BMS sample times (sparse)
            all_bms_times = set()
            for label in bms_keys:
                all_bms_times.update(bms_data[label].keys())
            all_bms_times = sorted(all_bms_times)

            last_bms = {label: None for label in bms_keys}
            i2t_idx = 0

            for t in all_bms_times:
                # Get I_centered at this time (nearest sample)
                while i2t_idx + 1 < len(i2t_series) and i2t_series[i2t_idx+1][0] <= t:
                    i2t_idx += 1
                i_c = i2t_series[i2t_idx][2] if i2t_series else 0
                i2t_val = interp_i2t(i2t_series, t)

                row = ["{:.4f}".format(t), i_c, "{:.0f}".format(i2t_val)]
                for label in bms_keys:
                    val = bms_data[label].get(t, None)
                    if val is not None:
                        last_bms[label] = val
                    row.append(last_bms[label] if last_bms[label] is not None else "")
                writer.writerow(row)

        print()
        print("CSV written: {}".format(out_path))


if __name__ == "__main__":
    main()
