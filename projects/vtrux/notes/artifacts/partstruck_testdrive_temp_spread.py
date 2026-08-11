import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
import cantools

dbc_path = os.path.join(os.path.dirname(__file__), '..', '..', 'epri-pt-bus.dbc')
log_path = os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'vtrux_partstruck_testdrive.log')

db = cantools.db.load_file(dbc_path)

from canre.parsers.autodetect import parse_file

frames = list(parse_file(log_path))

rows = []
for f in frames:
    if f.arbitration_id == 0x430:
        try:
            decoded = db.decode_message(0x430, bytes(f.data))
        except Exception:
            continue
        tmax = decoded.get('bcm_cell_tmax')
        tmin = decoded.get('bcm_cell_tmin')
        if tmax is None or tmin is None:
            continue
        rows.append((f.timestamp, tmax, tmin, tmax - tmin))

if not rows:
    print("No 0x430 frames decoded")
    sys.exit(1)

print(f"Frames decoded: {len(rows)}")
print(f"Time range: {rows[0][0]:.1f}s - {rows[-1][0]:.1f}s")
print()

spreads = [r[3] for r in rows]
tmaxes = [r[1] for r in rows]
tmins  = [r[2] for r in rows]

print(f"bcm_cell_tmax: min={min(tmaxes):.1f} max={max(tmaxes):.1f} degC")
print(f"bcm_cell_tmin: min={min(tmins):.1f}  max={max(tmins):.1f} degC")
print(f"Spread (tmax-tmin): min={min(spreads):.1f}  max={max(spreads):.1f}  mean={sum(spreads)/len(spreads):.2f} degC")
print()

BUCKET_SIZE = 0.5
bucket_counts = {}
for s in spreads:
    b = round(s / BUCKET_SIZE) * BUCKET_SIZE
    bucket_counts[b] = bucket_counts.get(b, 0) + 1

print("Spread distribution (0.5 degC buckets):")
for b in sorted(bucket_counts):
    pct = 100.0 * bucket_counts[b] / len(spreads)
    bar = '#' * int(pct / 2)
    print(f"  {b:5.1f} degC: {bucket_counts[b]:5d} frames ({pct:5.1f}%) {bar}")

print()
print("Spread over time (sampled every ~30s):")
print(f"{'time_s':>8}  {'tmax':>6}  {'tmin':>6}  {'spread':>6}")
step = max(1, len(rows) // 30)
for i in range(0, len(rows), step):
    ts, tmax, tmin, sp = rows[i]
    print(f"  {ts:7.1f}  {tmax:6.1f}  {tmin:6.1f}  {sp:6.1f}")
