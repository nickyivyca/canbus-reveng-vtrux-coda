"""
Analyze vtrux_no_gene_inv_fuse.log:
- 0x649 full message: evap counter (B2[3:0]:B3), B0, B4
- 0x1F5 B3/B5: gear/shift state (D vs M)
- 0x600 B0: generator active flag (bit4=1 active)
- 0x63C B6: generator RPM proxy

Hypothesis: pulling the generator inverter fuse may prevent evap from running
(VCM can't start engine with fuse pulled), which would explain why the parts truck
showed no evap active after being reawakened with fuse pulled.
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

LOG = Path(r"projects\vtrux\logs\vtrux_no_gene_inv_fuse.log")

TARGET_IDS = {0x649, 0x1F5, 0x600, 0x63C}

def pt_bus(sample):
    bus_ids = defaultdict(set)
    for f in sample:
        bus_ids[f.bus].add(f.arbitration_id)
    for bus, ids in bus_ids.items():
        if 0x051 in ids:
            return bus
    return None

print(f"Streaming {LOG.name}...", flush=True)
frames_by_id = defaultdict(list)
bus_sample = []
ptb = None
n_total = 0

for f in parse_file(str(LOG)):
    n_total += 1
    if len(bus_sample) < 5000:
        bus_sample.append(f)
    elif ptb is None:
        ptb = pt_bus(bus_sample)
    if f.arbitration_id in TARGET_IDS:
        if ptb is None:
            ptb = pt_bus(bus_sample)
        data = list(f.data) + [None] * (8 - len(f.data))
        frames_by_id[f.arbitration_id].append((f.timestamp, f.bus, data[:8]))
    if n_total % 2_000_000 == 0:
        print(f"  {n_total//1_000_000}M frames...", flush=True)

if ptb is None and bus_sample:
    ptb = pt_bus(bus_sample)

print(f"Done. {n_total:,} total frames  PT bus={ptb}", flush=True)
for id_, flist in sorted(frames_by_id.items()):
    print(f"  0x{id_:03X}: {len(flist):,} frames  t={flist[0][0]:.2f}-{flist[-1][0]:.2f}s")

def by_ptbus(id_):
    return [(t, d) for t, bus, d in frames_by_id.get(id_, []) if bus == ptb]

def any_bus(id_):
    return [(t, d) for t, bus, d in frames_by_id.get(id_, [])]

def transitions(frames, byte_idx):
    result = []
    prev = None
    for t, d in frames:
        v = d[byte_idx]
        if v is None:
            continue
        if prev is not None and v != prev:
            result.append((t, prev, v))
        prev = v
    return result

def evap_counter(d):
    b2, b3 = d[2], d[3]
    if b2 is None or b3 is None:
        return None
    return ((b2 & 0x0F) << 8) | b3

print("\n" + "="*70)
print("SECTION 1: 0x649 EVAP STATE OVERVIEW")
print("="*70)

f649 = by_ptbus(0x649)
if not f649:
    print("  No PT-bus 0x649 frames found — trying all buses")
    f649 = [(t, d) for t, _, d in frames_by_id.get(0x649, [])]

if f649:
    print(f"\n  {len(f649):,} frames  t={f649[0][0]:.2f}-{f649[-1][0]:.2f}s")
    print(f"\n  First: t={f649[0][0]:.3f}s  {' '.join(f'{v:#04x}' for v in f649[0][1])}")
    print(f"    B0={f649[0][1][0]:#04x}  B4={f649[0][1][4]:#04x}  ec={evap_counter(f649[0][1]):#05x}")
    print(f"\n  Last:  t={f649[-1][0]:.3f}s  {' '.join(f'{v:#04x}' for v in f649[-1][1])}")
    print(f"    B0={f649[-1][1][0]:#04x}  B4={f649[-1][1][4]:#04x}  ec={evap_counter(f649[-1][1]):#05x}")

    print(f"\n  B0 transitions:")
    b0_tr = transitions(f649, 0)
    if b0_tr:
        for t, bef, aft in b0_tr:
            print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}  (bit7: {(bef>>7)&1}->{(aft>>7)&1})")
    else:
        print(f"    none (constant {f649[0][1][0]:#04x})")

    print(f"\n  B4 transitions:")
    b4_tr = transitions(f649, 4)
    if b4_tr:
        for t, bef, aft in b4_tr:
            print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}")
    else:
        print(f"    none (constant {f649[0][1][4]:#04x})")

    print(f"\n  B3 unique values: {len(set(d[3] for _, d in f649 if d[3] is not None))}")
    b3v = [d[3] for _, d in f649 if d[3] is not None]
    if b3v:
        print(f"  B3 range: {min(b3v):#04x} - {max(b3v):#04x}")

    print(f"\n  Evap counter changes:")
    prev_ec = None
    ec_changes = []
    for t, d in f649:
        ec = evap_counter(d)
        if ec is not None and prev_ec is not None and ec != prev_ec:
            ec_changes.append((t, prev_ec, ec))
        prev_ec = ec
    if ec_changes:
        for t, bef, aft in ec_changes[:20]:
            print(f"    t={t:.3f}s: {bef:#05x} -> {aft:#05x}")
        if len(ec_changes) > 20:
            print(f"    ... ({len(ec_changes)} total changes)")
    else:
        print(f"    none (constant {evap_counter(f649[0][1]):#05x})")

    print(f"\n  Snapshot every 30s:")
    print(f"  {'t':>8}  B0    B1    B2    B3    B4    B5    ec     b1c   notes")
    prev_snap = -999
    for t, d in f649:
        if t - prev_snap >= 30:
            ec = evap_counter(d)
            b1c = ((d[2] >> 4) << 8) | d[1] if d[1] is not None and d[2] is not None else None
            print(f"  {t:>8.1f}  {d[0]:#04x}  {d[1]:#04x}  {d[2]:#04x}  {d[3]:#04x}  "
                  f"{d[4]:#04x}  {d[5]:#04x}  {ec:#05x}  {b1c:#05x}")
            prev_snap = t

print("\n" + "="*70)
print("SECTION 2: SHIFT PATTERN (0x1F5 B3 and B5 = gear position)")
print("  B3: 0x04=Drive, 0x09=Manual  |  B5: 0x00=Drive, 0x02=Manual")
print("="*70)

f1f5 = any_bus(0x1F5)
if f1f5:
    print(f"\n  {len(f1f5):,} frames  t={f1f5[0][0]:.2f}-{f1f5[-1][0]:.2f}s")

    b3_tr = transitions(f1f5, 3)
    b5_tr = transitions(f1f5, 5)

    print(f"\n  B3 transitions (gear D/M):")
    if b3_tr:
        for t, bef, aft in b3_tr:
            desc = "->M" if aft == 0x09 else ("->D" if aft == 0x04 else "->?")
            print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}  {desc}")
    else:
        v = f1f5[0][1][3]
        print(f"    none (constant {v:#04x} = {'Drive' if v==0x04 else 'Manual' if v==0x09 else 'unknown'})")

    print(f"\n  B5 transitions:")
    if b5_tr:
        for t, bef, aft in b5_tr:
            desc = "->M" if aft == 0x02 else ("->D" if aft == 0x00 else "->?")
            print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}  {desc}")
    else:
        v = f1f5[0][1][5]
        print(f"    none (constant {v:#04x})")
else:
    print("  No 0x1F5 frames found")

print("\n" + "="*70)
print("SECTION 3: GENERATOR ACTIVE FLAG (0x600 B0, PT bus)")
print("  bit4=1 -> generator active (0x34), bit4=0 -> inactive (0x24)")
print("  Also show B3 (engine state counter) for context")
print("="*70)

f600 = by_ptbus(0x600)
if not f600:
    f600 = [(t, d) for t, _, d in frames_by_id.get(0x600, [])]

if f600:
    print(f"\n  {len(f600):,} frames  t={f600[0][0]:.2f}-{f600[-1][0]:.2f}s")
    print(f"  First: B0={f600[0][1][0]:#04x}  B3={f600[0][1][3]:#04x}")
    print(f"  Last:  B0={f600[-1][1][0]:#04x}  B3={f600[-1][1][3]:#04x}")

    b0_tr = transitions(f600, 0)
    b3_tr = transitions(f600, 3)

    print(f"\n  B0 transitions (generator flag):")
    if b0_tr:
        for t, bef, aft in b0_tr:
            b_gen = "GEN_ON" if (aft >> 4) & 1 else "GEN_OFF"
            print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}  {b_gen}")
    else:
        v = f600[0][1][0]
        b_gen = "GEN_ON" if (v >> 4) & 1 else "GEN_OFF"
        print(f"    none (constant {v:#04x} = {b_gen})")

    print(f"\n  B3 transitions (engine state counter):")
    if b3_tr:
        for t, bef, aft in b3_tr[:30]:
            print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}")
        if len(b3_tr) > 30:
            print(f"    ... ({len(b3_tr)} total)")
    else:
        print(f"    none (constant {f600[0][1][3]:#04x})")
else:
    print("  No 0x600 frames found")

print("\n" + "="*70)
print("SECTION 4: CORRELATED TIMELINE")
print("  Show all key events together: gear shifts, gen on/off, evap counter changes")
print("="*70)

events = []
for t, bef, aft in transitions(f649 if f649 else [], 0):
    events.append((t, f"0x649 B0: {bef:#04x}->{aft:#04x} (evap_flag bit7: {(bef>>7)&1}->{(aft>>7)&1})"))
for t, bef, aft in transitions(f649 if f649 else [], 4):
    events.append((t, f"0x649 B4: {bef:#04x}->{aft:#04x}"))

ec_changes = []
prev_ec = None
for t, d in (f649 or []):
    ec = evap_counter(d)
    if ec is not None and prev_ec is not None and ec != prev_ec:
        ec_changes.append((t, prev_ec, ec))
    prev_ec = ec
for t, bef, aft in ec_changes:
    events.append((t, f"evap_counter: {bef:#05x}->{aft:#05x}"))

for t, bef, aft in transitions(f1f5 if f1f5 else [], 3):
    label = "->M_mode" if aft == 0x09 else ("->Drive" if aft == 0x04 else f"->{aft:#04x}")
    events.append((t, f"0x1F5 B3 shift {bef:#04x}{label}"))

for t, bef, aft in transitions(f600 if f600 else [], 0):
    b_gen = "GEN_ON" if (aft >> 4) & 1 else "GEN_OFF"
    events.append((t, f"0x600 B0: {bef:#04x}->{aft:#04x} ({b_gen})"))

for t, bef, aft in transitions(f600 if f600 else [], 3):
    events.append((t, f"0x600 B3 engine_ctr: {bef:#04x}->{aft:#04x}"))

events.sort()
print()
if events:
    for t, desc in events:
        print(f"  t={t:8.3f}s  {desc}")
else:
    print("  No events found")

print("\nDone.")
