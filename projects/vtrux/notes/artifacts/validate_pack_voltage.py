"""
Validate 0x420 pack voltage scaling against Bel charger ground truth.

Charger ground truth: 0x18FFD7C0 B0-B1 LE signed16 * 0.05 = Volts
Candidate: 0x420 various byte/endian combinations

Resolves conflict between:
  - context-voltage-current.md: B0-B1 BE /100 = exact match at 391.7V
  - powertrain-messages.md: B2-B3 (byte position uncertain)
"""

import re
import struct
from collections import defaultdict

# Edit this path to the log with both charger + vehicle IDs
LOG_PATH = r"projects/vtrux/Bel-Inverter/other-logs/truklog_M0_T8.log"

BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)


def parse_ts(ts):
    h, m, s, t = ts.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001


charger_v = []   # (t, volts) from 0x18FFD7C0
frames_420 = []  # (t, data)
t0 = None

with open(LOG_PATH, errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, _, data_str = m.groups()
        mid = int(id_str, 16)
        ts = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]

        if mid == 0x18FFD7C0 and len(data) >= 2:
            raw = struct.unpack_from('<h', bytes(data[:2]))[0]
            volts = raw * 0.05
            charger_v.append((rel, volts))
        elif mid == 0x420 and len(data) >= 4:
            frames_420.append((rel, data))

print(f"Charger voltage samples: {len(charger_v)}")
print(f"0x420 samples:           {len(frames_420)}")
if not charger_v or not frames_420:
    print("ERROR: missing data — check log path or bus assignment")
    raise SystemExit

charger_min = min(v for _, v in charger_v)
charger_max = max(v for _, v in charger_v)
print(f"Charger voltage range: {charger_min:.2f}V – {charger_max:.2f}V")
print()

# Build lookup: nearest charger voltage at any given time
def charger_at(t):
    return min(charger_v, key=lambda x: abs(x[0] - t))[1]

# Test all candidate decodings of 0x420
print("=" * 72)
print("CANDIDATE DECODINGS vs CHARGER GROUND TRUTH")
print("(Showing at 10 evenly-spaced moments)")
print("=" * 72)

n = len(frames_420)
step = max(1, n // 10)
sample_frames = frames_420[::step][:10]

candidates = [
    ("B0-B1 BE /100",  lambda d: ((d[0]<<8)|d[1]) / 100.0),
    ("B0-B1 LE /100",  lambda d: ((d[1]<<8)|d[0]) / 100.0),
    ("B2-B3 BE /100",  lambda d: ((d[2]<<8)|d[3]) / 100.0),
    ("B2-B3 LE /100",  lambda d: ((d[3]<<8)|d[2]) / 100.0),
    ("B0-B1 BE /10",   lambda d: ((d[0]<<8)|d[1]) / 10.0),
    ("B2-B3 BE /10",   lambda d: ((d[2]<<8)|d[3]) / 10.0),
]

print(f"  {'Time':>7}  {'Charger':>9}  " +
      "  ".join(f'{c[0]:>16}' for c in candidates))
print("-" * (20 + 18 * len(candidates)))

errors = defaultdict(list)
for t, data in sample_frames:
    cv = charger_at(t)
    row = f"  {t:7.1f}  {cv:9.2f}V "
    for label, fn in candidates:
        val = fn(data)
        err = val - cv
        errors[label].append(err)
        row += f"  {val:13.2f}V"
    print(row)

print()
print("Mean absolute error vs charger ground truth:")
for label, _ in candidates:
    errs = errors[label]
    mae = sum(abs(e) for e in errs) / len(errs)
    bias = sum(errs) / len(errs)
    print(f"  {label:>16}:  MAE={mae:.3f}V  bias={bias:+.3f}V")

print()
# Best candidate summary
best_label = min(errors, key=lambda k: sum(abs(e) for e in errors[k]))
best_fn = next(fn for label, fn in candidates if label == best_label)
print(f"Best candidate: {best_label}")

# Show full timeseries for best candidate sampled every ~60s
print()
print("=" * 50)
print(f"FULL TIMESERIES: {best_label} vs charger (every ~60s)")
print("=" * 50)
print(f"  {'Time':>7}  {'Charger':>9}  {'0x420':>9}  {'Delta':>7}")
prev_t = -999
for t, data in frames_420:
    if t - prev_t < 60:
        continue
    prev_t = t
    cv = charger_at(t)
    val = best_fn(data)
    print(f"  {t:7.1f}  {cv:9.2f}V  {val:9.2f}V  {val-cv:+7.3f}V")
