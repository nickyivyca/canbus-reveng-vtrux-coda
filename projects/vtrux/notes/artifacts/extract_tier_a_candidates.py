"""
extract_tier_a_candidates.py

Extract key byte timeseries from Tier A inverter candidates (0x619, 0x481)
across both evap4 log parts. Print decile snapshots and statistics to assess
whether bytes are temperature-like (slow monotonic rise) vs current/voltage.

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/extract_tier_a_candidates.py
"""
import sys, math
from collections import defaultdict
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOGS = [
    ("evap4p1", "projects/vtrux/logs/vtruxevapdrivelog4.log"),
    ("evap4p2", "projects/vtrux/logs/vtruxevapdrivelog4part2.log"),
]

# Generator on/off in part 1 (approx)
GEN_ON_T  = 90.0
GEN_OFF_T = 1100.0   # end of part 1
# Part 2: generator shuts off ~t=290s into part 2 (from evap cycle analysis)
P2_GEN_OFF = 290.0

TARGETS = {
    # 0x619: B0 (top r_gen hit, Tier A), B2/B4/B5 (secondary bytes)
    0x619: [0, 2, 4, 5],
    # 0x481: B1 and B3 are MSBs of two LE uint16 words (r_gen=0.94)
    #        B0 and B2 are noisy LSBs -- also extract to see full word
    0x481: [0, 1, 2, 3],
}


def identify_pt_bus_streaming(log_path):
    """Stream log once to identify PT bus (has 0x051) and return (bus, t0)."""
    cnt = defaultdict(lambda: defaultdict(int))
    first_ts = {}
    for fr in parse_file(log_path):
        cnt[fr.bus][fr.arbitration_id] += 1
        if fr.bus not in first_ts:
            first_ts[fr.bus] = fr.timestamp
    pt_bus = next(b for b, c in cnt.items() if c.get(0x051, 0) > 1000)
    return pt_bus, first_ts[pt_bus]


def le_uint16(data, lo_byte):
    if lo_byte + 1 >= len(data):
        return None
    return data[lo_byte] | (data[lo_byte + 1] << 8)


def summarize(label, ts_vals):
    """Print decile summary of timeseries."""
    if not ts_vals:
        print(f"  {label}: NO DATA")
        return
    times, vals = zip(*ts_vals)
    n = len(vals)
    mn, mx = min(vals), max(vals)
    mean = sum(vals) / n

    # Deciles: show value at t=0%, 10%, 20%, ... 100% of time span
    t_min, t_max = times[0], times[-1]
    span = t_max - t_min
    deciles = []
    j = 0
    for pct in range(0, 110, 10):
        t_target = t_min + span * pct / 100
        while j < n - 1 and times[j + 1] <= t_target:
            j += 1
        deciles.append(vals[j])

    print(f"  {label:20s}: min={mn:4d}  max={mx:4d}  mean={mean:6.1f}  "
          f"range={mx-mn:3d}  n={n:6d}")
    pct_labels = " ".join(f"{p:4d}%" for p in range(0, 110, 10))
    val_line   = " ".join(f"{v:5d}" for v in deciles)
    print(f"    time%: {pct_labels}")
    print(f"    value: {val_line}")


def main():
    for log_name, log_path in LOGS:
        print(f"\n{'='*70}")
        print(f"Log: {log_name}  ({log_path})")
        print(f"{'='*70}")

        # Pass 1: identify PT bus and t0 (streaming, no list())
        pt_bus, t0 = identify_pt_bus_streaming(log_path)

        # Pass 2: collect per-ID timeseries and LE uint16 words (streaming)
        raw_ts = defaultdict(lambda: defaultdict(list))
        le_ts_481 = defaultdict(list)
        for fr in parse_file(log_path):
            if fr.bus != pt_bus:
                continue
            t = fr.timestamp - t0
            if fr.arbitration_id in TARGETS:
                for bi in TARGETS[fr.arbitration_id]:
                    if bi < len(fr.data):
                        raw_ts[fr.arbitration_id][bi].append((t, fr.data[bi]))
            if fr.arbitration_id == 0x481:
                w01 = le_uint16(fr.data, 0)
                w23 = le_uint16(fr.data, 2)
                if w01 is not None:
                    le_ts_481['W01'].append((t, w01))
                if w23 is not None:
                    le_ts_481['W23'].append((t, w23))

        for aid in sorted(TARGETS):
            print(f"\n  ID 0x{aid:03X}:")
            for bi in TARGETS[aid]:
                summarize(f"B{bi}", raw_ts[aid][bi])

        if le_ts_481:
            print(f"\n  0x481 LE uint16 words (centered at 32768, so subtract 32768 for signed value):")
            for k in ['W01', 'W23']:
                ts_vals = le_ts_481[k]
                if ts_vals:
                    times, vals = zip(*ts_vals)
                    signed = [v - 32768 for v in vals]
                    mn, mx = min(signed), max(signed)
                    mean = sum(signed) / len(signed)
                    span = times[-1] - times[0]
                    deciles = []
                    j = 0
                    for pct in range(0, 110, 10):
                        t_target = times[0] + span * pct / 100
                        while j < len(times) - 1 and times[j+1] <= t_target:
                            j += 1
                        deciles.append(signed[j])
                    print(f"  {k} signed:              min={mn:6d}  max={mx:6d}  "
                          f"mean={mean:6.1f}  range={mx-mn}")
                    pct_labels = " ".join(f"{p:5d}%" for p in range(0, 110, 10))
                    val_line   = " ".join(f"{v:6d}" for v in deciles)
                    print(f"    time%: {pct_labels}")
                    print(f"    value: {val_line}")

    print()


if __name__ == '__main__':
    main()
