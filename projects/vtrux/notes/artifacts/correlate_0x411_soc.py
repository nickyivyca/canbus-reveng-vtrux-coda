"""
Correlate 0x411 B0:B1 combined counter against 0x596 B6 SoC across multiple logs.

Combined formula: combined = B0*64 + B1//4  (= B0*64 + (B1 >> 2))
Export session showed combined/100 ~= SoC% with r=0.9998.

Goal: check whether combined tracks proportionally in drive logs with non-linear discharge,
not just in steady-discharge export sessions.
"""
import sys
import os
import bisect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')

LOGS = [
    ('charge-80pct', os.path.join(LOG_DIR, 'vtruxchargeafterexportchargetest-80pctcv.log')),
    ('rainycharge1', os.path.join(LOG_DIR, 'rainychargedebug.log')),
]

ID_411 = 0x411
ID_596 = 0x596


def pearson_r(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx)**2 for x in xs) ** 0.5) * (sum((y - my)**2 for y in ys) ** 0.5)
    return num / den if den > 0 else 0.0


def linear_fit(xs, ys):
    n = len(xs)
    sx = sum(xs); sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    a = (n * sxy - sx * sy) / (n * sx2 - sx**2)
    b = (sy - a * sx) / n
    return a, b


def analyse_log(label, path):
    print(f"\n{'='*60}")
    print(f"LOG: {label}  ({os.path.basename(path)})")
    print(f"{'='*60}")

    data_411 = []
    data_596 = []

    print("  Parsing...")
    for frame in parse_file(path):
        aid = frame.arbitration_id
        if aid == ID_411 and len(frame.data) >= 2:
            b0 = frame.data[0]
            b1 = frame.data[1]
            combined = b0 * 64 + (b1 >> 2)
            data_411.append((frame.timestamp, combined))
        elif aid == ID_596 and len(frame.data) >= 7:
            soc = frame.data[6]
            data_596.append((frame.timestamp, soc))

    print(f"  0x411 frames: {len(data_411)}")
    print(f"  0x596 frames: {len(data_596)}")

    if not data_411:
        print("  ERROR: No 0x411 data")
        return
    if not data_596:
        print("  ERROR: No 0x596 data")
        return

    combined_start = data_411[0][1]
    combined_end   = data_411[-1][1]
    soc_start = data_596[0][1]
    soc_end   = data_596[-1][1]
    print(f"  0x411 combined: {combined_start} -> {combined_end}  "
          f"(t={data_411[0][0]:.0f}s to t={data_411[-1][0]:.0f}s)")
    print(f"  0x596 SoC:      {soc_start}% -> {soc_end}%  "
          f"(t={data_596[0][0]:.0f}s to t={data_596[-1][0]:.0f}s)")

    # Time-align: for each 0x596 sample, snap to nearest 0x411 (within 2s)
    times_411 = [r[0] for r in data_411]
    comb_411  = [r[1] for r in data_411]

    paired = []
    for t_soc, soc in data_596:
        idx = bisect.bisect_left(times_411, t_soc)
        if idx == 0:
            best = 0
        elif idx >= len(times_411):
            best = len(times_411) - 1
        else:
            best = idx - 1 if abs(times_411[idx-1] - t_soc) <= abs(times_411[idx] - t_soc) else idx
        if abs(times_411[best] - t_soc) < 2.0:
            paired.append((t_soc, soc, comb_411[best]))

    print(f"  Paired samples: {len(paired)}")
    if len(paired) < 10:
        print("  ERROR: Too few paired samples")
        return

    soc_vals  = [p[1] for p in paired]
    comb_vals = [p[2] for p in paired]

    r = pearson_r(soc_vals, comb_vals)
    a, b = linear_fit(soc_vals, comb_vals)

    print(f"\n  Pearson r (combined vs SoC):  {r:.4f}")
    print(f"  SoC range:     {min(soc_vals)}-{max(soc_vals)}%")
    print(f"  Combined range: {min(comb_vals)}-{max(comb_vals)}")
    print(f"  Linear fit:    combined = {a:.1f} * SoC + {b:.1f}")
    print(f"    At SoC=100%: {a*100+b:.0f}   (expected ~10000)")
    print(f"    At SoC=0%:   {b:.0f}         (expected ~0)")

    # Spot-check samples across the session
    print(f"\n  {'t(s)':>7}  {'SoC%':>5}  {'combined':>9}  {'comb/100':>9}")
    step = max(1, len(paired) // 15)
    shown = set()
    for i in list(range(0, len(paired), step)) + [len(paired)-1]:
        if i in shown:
            continue
        shown.add(i)
        t, soc, comb = paired[i]
        print(f"  {t:7.0f}  {soc:5}  {comb:9}  {comb/100:8.1f}%")


for label, path in LOGS:
    analyse_log(label, path)
