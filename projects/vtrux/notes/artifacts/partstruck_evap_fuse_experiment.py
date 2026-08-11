"""
Analyze vtrux_partstruck_evapfuseexperiment.log across experiment phases.

Sidecar notes:
  Phase 1: start with fuse in, engine starts for evap, shuts off (isolation fault)
  Phase 2: 12V disconnect to reset fault, remove fuse, reconnect -> precharge fail
  Phase 3: Via fusebox 12V disconnect to reset HCU, reconnect
  Phase 4: run with fuse out, attempt to latch missing generator state / evap reset
  Phase 5: key off, wait for HCU sleep (CAN traffic stops)
  Phase 6: reconnect fuse, key on -> generator starts then isolation fault again
  Conclusion: unable to latch evap reset by pulling fuse

Key signals:
  0x649 B0 (evap NVM flag, bit7=evap active), B4 (real-time flag), ec=(B2&0x0F)<<8|B3
  0x600 B0 bit4 (gen active: 0x34=on)
  0x63C B6 (gen RPM, zero=6, scale=16 rpm/count)
  GENE MCU presence: 0x054, 0x471, 0x479, 0x482 (absent = fuse pulled)
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

LOG = Path(r"projects\vtrux\logs\vtrux_partstruck_evapfuseexperiment.log")

TARGET_IDS = {0x649, 0x600, 0x63C, 0x054, 0x471, 0x479, 0x482}
GENE_IDS = {0x054, 0x471, 0x479, 0x482}

print(f"Streaming {LOG.name}...", flush=True)

frames_by_id = defaultdict(list)
all_timestamps = []
n_total = 0

for f in parse_file(str(LOG)):
    n_total += 1
    all_timestamps.append(f.timestamp)
    if f.arbitration_id in TARGET_IDS:
        data = list(f.data) + [None] * (8 - len(f.data))
        frames_by_id[f.arbitration_id].append((f.timestamp, f.bus, data[:8]))
    if n_total % 2_000_000 == 0:
        print(f"  {n_total//1_000_000}M frames...", flush=True)

print(f"Done. {n_total:,} total frames  t={all_timestamps[0]:.2f}-{all_timestamps[-1]:.2f}s", flush=True)
for id_, flist in sorted(frames_by_id.items()):
    print(f"  0x{id_:03X}: {len(flist):,} frames  t={flist[0][0]:.2f}-{flist[-1][0]:.2f}s")

def any_bus(id_):
    return [(t, d) for t, bus, d in frames_by_id.get(id_, [])]

def evap_counter(d):
    b2, b3 = d[2], d[3]
    if b2 is None or b3 is None:
        return None
    return ((b2 & 0x0F) << 8) | b3

print("\n" + "="*70)
print("SECTION 1: CAN GAPS (key-off / 12V disconnect / sleep events)")
print("  Gaps > 2s in the overall frame stream")
print("="*70)

gaps = []
for a, b in zip(all_timestamps, all_timestamps[1:]):
    if b - a > 2.0:
        gaps.append((a, b, b - a))

for t0, t1, dur in gaps:
    print(f"  gap: t={t0:.2f}-{t1:.2f}s  ({dur:.1f}s silence)")

print("\n" + "="*70)
print("SECTION 2: GENE MCU PRESENCE (fuse state indicator)")
print("  Tracks first/last appearance of any GENE ID per continuous window")
print("="*70)

gene_frames = sorted(
    (t, id_) for id_ in GENE_IDS for t, _, _ in frames_by_id.get(id_, [])
)

if gene_frames:
    windows = []
    win_start = gene_frames[0][0]
    win_last = gene_frames[0][0]
    for t, id_ in gene_frames[1:]:
        if t - win_last > 5.0:
            windows.append((win_start, win_last))
            win_start = t
        win_last = t
    windows.append((win_start, win_last))
    for ws, we in windows:
        print(f"  GENE online: t={ws:.2f}-{we:.2f}s  ({we-ws:.1f}s)")

print("\n" + "="*70)
print("SECTION 3: 0x649 EVAP STATE — snapshots every 20s + all transitions")
print("="*70)

f649 = any_bus(0x649)
if f649:
    print(f"\n  {len(f649):,} frames  t={f649[0][0]:.2f}-{f649[-1][0]:.2f}s")

    print(f"\n  B0 transitions:")
    prev_b0 = None
    for t, d in f649:
        if d[0] != prev_b0:
            evap_on = "EVAP_ON" if d[0] is not None and (d[0] >> 7) & 1 else "evap_off"
            prev_str = f"{prev_b0:#04x}" if prev_b0 is not None else "----"
            print(f"    t={t:.3f}s: {prev_str} -> {d[0]:#04x}  {evap_on}")
            prev_b0 = d[0]

    print(f"\n  B4 transitions:")
    prev_b4 = None
    for t, d in f649:
        if d[4] != prev_b4:
            prev_str = f"{prev_b4:#04x}" if prev_b4 is not None else "----"
            print(f"    t={t:.3f}s: {prev_str} -> {d[4]:#04x}")
            prev_b4 = d[4]

    print(f"\n  Evap counter transitions:")
    prev_ec = None
    for t, d in f649:
        ec = evap_counter(d)
        if ec != prev_ec:
            print(f"    t={t:.3f}s: ec={ec:#05x} ({ec})")
            prev_ec = ec

    print(f"\n  Snapshot every 20s:")
    print(f"  {'t':>8}  B0    B4    B5    ec      notes")
    prev_snap = -999
    for t, d in f649:
        if t - prev_snap >= 20:
            ec = evap_counter(d)
            evap_on = "EVAP" if d[0] is not None and (d[0] >> 7) & 1 else "----"
            print(f"  {t:>8.1f}  {d[0]:#04x}  {d[4]:#04x}  {d[5]:#04x}  {ec:#05x}  {evap_on}")
            prev_snap = t

print("\n" + "="*70)
print("SECTION 4: GENERATOR ACTIVE (0x600 B0) + RPM (0x63C B6)")
print("="*70)

f600 = any_bus(0x600)
if f600:
    print(f"\n  0x600: {len(f600):,} frames")
    prev_b0 = None
    for t, d in f600:
        if d[0] != prev_b0:
            gen = "GEN_ON" if d[0] is not None and (d[0] >> 4) & 1 else "gen_off"
            print(f"    t={t:.3f}s: {d[0]:#04x}  {gen}")
            prev_b0 = d[0]

f63c = any_bus(0x63C)
if f63c:
    print(f"\n  0x63C B6 RPM (zero=6, scale=16 rpm/count) — transitions only:")
    prev_b6 = None
    for t, d in f63c:
        b6 = d[6]
        if b6 != prev_b6:
            rpm = (b6 - 6) * 16 if b6 is not None else None
            print(f"    t={t:.3f}s: B6={b6}  ({rpm} rpm above zero)")
            prev_b6 = b6

print("\nDone.")
