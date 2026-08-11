"""
Extended 0x649 analysis across multiple logs:

1. B1 + B2[7:4] as a 12-bit counter hypothesis:
   - B1 steps by +1, B2 upper nibble steps by +16.
   - If B2[7:4] increments each time B1 wraps 0xFF->0x00, they form a 12-bit counter.
   - Expect: counter = (B2[7:4] << 8) | B1

2. Characterize 0x649 in new logs:
   - vtruxgeneratoroverheattest.log  (no evap expected)
   - vtrux_partstruck_testdrive.log  (truck reawakened - evap likely)
   - vtrux_partstruck_testdrive_part2.log (continuation)

3. B0 vs B4 evap flag comparison across all logs:
   - When does each set (key-on vs engine-start)?
   - Do they clear simultaneously?
   - Exact transition values and timing.
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

LOGS = Path(r"projects\vtrux\logs")
ARTIFACTS = Path(r"projects\vtrux\notes\artifacts")

TARGET_ID = 0x649

def pt_bus(frames):
    from collections import Counter
    bus_ids = defaultdict(set)
    for f in frames[:5000]:
        bus_ids[f.bus].add(f.arbitration_id)
    for bus, ids in bus_ids.items():
        if 0x051 in ids:
            return bus
    return None

def stream_649(log_path):
    """Stream a log file and return only 0x649 frames as (t, data[8]) tuples."""
    frames = []
    n = 0
    pt_b = None
    bus_sample = []
    for f in parse_file(str(log_path)):
        n += 1
        if len(bus_sample) < 5000:
            bus_sample.append(f)
        elif pt_b is None:
            pt_b = pt_bus(bus_sample)
        if f.arbitration_id == TARGET_ID:
            if pt_b is None:
                pt_b = pt_bus(bus_sample)
            if pt_b is not None and f.bus != pt_b:
                continue
            data = list(f.data) + [None] * (8 - len(f.data))
            frames.append((f.timestamp, data[:8]))
        if n % 2_000_000 == 0:
            print(f"  {n//1_000_000}M frames scanned, {len(frames)} 0x649 kept...", flush=True)
    if pt_b is None and bus_sample:
        pt_b = pt_bus(bus_sample)
    return frames, pt_b, n

def fmt8(data):
    return "  ".join(f"{v:#04x}" if v is not None else " -- " for v in data)

def evap_counter(data):
    b2, b3 = data[2], data[3]
    if b2 is None or b3 is None:
        return None
    return ((b2 & 0x0F) << 8) | b3

def b1_b2high_counter(data):
    b1, b2 = data[1], data[2]
    if b1 is None or b2 is None:
        return None
    return ((b2 >> 4) << 8) | b1

def transitions(frames, byte_idx):
    """Return list of (t, old, new) for all value changes in byte_idx."""
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

def wrap_events(frames, byte_idx):
    """Return (t, before, after) for each 0xFF->0x00 wrap in byte_idx."""
    result = []
    prev_t, prev_v = None, None
    for t, d in frames:
        v = d[byte_idx]
        if v is None:
            continue
        if prev_v is not None and prev_v > 0xF0 and v < 0x10:
            result.append((t, prev_v, v))
        prev_t, prev_v = t, v
    return result

print("="*70)
print("SECTION 1: B1 + B2[7:4] AS 12-BIT COUNTER HYPOTHESIS")
print("Using another_p2 CSV (already extracted) for detailed analysis")
print("="*70)

csv_p2 = ARTIFACTS / "vcu_another_p2.csv"
import csv as csvmod
p2_frames = []
if csv_p2.exists():
    with open(csv_p2, newline="") as f:
        reader = csvmod.DictReader(f)
        for row in reader:
            if int(row["id"], 16) != TARGET_ID:
                continue
            t = float(row["t"])
            data = [int(row[f"b{i}"]) if row.get(f"b{i}", "") != "" else None for i in range(8)]
            p2_frames.append((t, data))
    print(f"\nLoaded {len(p2_frames):,} 0x649 frames from another_p2 CSV", flush=True)

if p2_frames:
    print("\n--- B1 step distribution (full session) ---")
    b1_vals = [d[1] for _, d in p2_frames if d[1] is not None]
    b1_steps = [b - a for a, b in zip(b1_vals, b1_vals[1:]) if b != a]
    from collections import Counter
    sc = Counter(b1_steps)
    print(f"  B1 total changes: {len(b1_steps)}")
    print(f"  Top steps: {sc.most_common(8)}")

    b2_vals = [d[2] for _, d in p2_frames if d[2] is not None]
    b2high = [v >> 4 for v in b2_vals]
    b2high_changes = [(b - a) for a, b in zip(b2high, b2high[1:]) if b != a]
    sc2 = Counter(b2high_changes)
    print(f"\n  B2[7:4] (upper nibble) total changes: {len(b2high_changes)}")
    print(f"  Top steps (in nibble units): {sc2.most_common(8)}")

    print("\n--- B1 wrap events and B2[7:4] behavior at each wrap ---")
    b1_wraps = wrap_events(p2_frames, 1)
    print(f"  B1 wraps (0xFF->0x00): {len(b1_wraps)}")
    for t, bef, aft in b1_wraps[:10]:
        idx = next(i for i, (ts, _) in enumerate(p2_frames) if ts >= t)
        b2_before = p2_frames[idx-1][1][2] if idx > 0 else None
        b2_after  = p2_frames[idx][1][2]
        b2h_before = (b2_before >> 4) if b2_before is not None else None
        b2h_after  = (b2_after  >> 4) if b2_after  is not None else None
        print(f"  t={t:.2f}s: B1 {bef:#04x}->{aft:#04x}  B2 {b2_before:#04x}->{b2_after:#04x}"
              f"  B2[7:4] {b2h_before}->{b2h_after}")

    print("\n--- B1 rate vs time (120s windows, 60s steps, evap window only) ---")
    evap_frames = [(t, d) for t, d in p2_frames if 12.31 <= t <= 1386.8]
    if evap_frames:
        t0 = evap_frames[0][0]
        t_end = evap_frames[-1][0]
        t = t0
        ws = 120.0
        print(f"  {'t_start':>8}  {'t_end':>8}  {'b1_v0':>6}  {'b1_v1':>6}  {'counts':>7}  {'c/s':>6}  b2hi_start  b2hi_end")
        while t + ws <= t_end:
            seg = [(ts, d) for ts, d in evap_frames if t <= ts <= t + ws]
            if len(seg) >= 2:
                v0, v1 = seg[0][1][1], seg[-1][1][1]
                b2h0 = seg[0][1][2] >> 4
                b2h1 = seg[-1][1][2] >> 4
                dt = seg[-1][0] - seg[0][0]
                raw_net = v1 - v0
                counts = raw_net if raw_net >= 0 else raw_net + 256
                rate = counts / dt if dt > 0 else 0
                print(f"  {t:>8.0f}  {t+ws:>8.0f}  {v0:#6x}  {v1:#6x}  {counts:>7}  {rate:>6.4f}  {b2h0:>10}  {b2h1:>8}")
            t += 60.0

print("\n" + "="*70)
print("SECTION 2: GENERATOR OVERHEAT LOG (no evap expected)")
print("="*70)

overheat_log = LOGS / "vtruxgeneratoroverheattest.log"
print(f"\nStreaming {overheat_log.name}...", flush=True)
oh_frames, oh_ptbus, oh_total = stream_649(overheat_log)
print(f"Done. {oh_total:,} total frames, {len(oh_frames):,} 0x649 frames  PT bus={oh_ptbus}", flush=True)

if oh_frames:
    print(f"\n  t span: {oh_frames[0][0]:.2f}s - {oh_frames[-1][0]:.2f}s")
    print(f"\n  First frame: t={oh_frames[0][0]:.3f}s")
    print(f"    {fmt8(oh_frames[0][1])}")
    print(f"    B0={oh_frames[0][1][0]:#04x}  B4={oh_frames[0][1][4]:#04x}")
    print(f"    evap_counter(B2[3:0]:B3) = {evap_counter(oh_frames[0][1]):#05x}")
    print(f"    b1_b2high_counter = {b1_b2high_counter(oh_frames[0][1]):#05x}")

    print(f"\n  Last frame: t={oh_frames[-1][0]:.3f}s")
    print(f"    {fmt8(oh_frames[-1][1])}")
    print(f"    B0={oh_frames[-1][1][0]:#04x}  B4={oh_frames[-1][1][4]:#04x}")
    print(f"    evap_counter = {evap_counter(oh_frames[-1][1]):#05x}")
    print(f"    b1_b2high_counter = {b1_b2high_counter(oh_frames[-1][1]):#05x}")

    print(f"\n  B0 transitions:")
    for t, bef, aft in transitions(oh_frames, 0):
        print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}")
    if not transitions(oh_frames, 0):
        print(f"    none (constant {oh_frames[0][1][0]:#04x})")

    print(f"\n  B4 transitions:")
    for t, bef, aft in transitions(oh_frames, 4):
        print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}")
    if not transitions(oh_frames, 4):
        print(f"    none (constant {oh_frames[0][1][4]:#04x})")

    print(f"\n  B3 unique values: {len(set(d[3] for _, d in oh_frames if d[3] is not None))}")
    b3_vals_oh = [d[3] for _, d in oh_frames if d[3] is not None]
    if b3_vals_oh:
        print(f"  B3 range: {min(b3_vals_oh):#04x} - {max(b3_vals_oh):#04x}")

    print(f"\n  Snapshot every 60s: t / B0 / B1 / B2 / B3 / B4 / evap_ctr / b1b2h_ctr")
    prev_snap = -999
    for t, d in oh_frames:
        if t - prev_snap >= 60:
            ec = evap_counter(d)
            bc = b1_b2high_counter(d)
            print(f"    t={t:7.1f}  B0={d[0]:#04x} B1={d[1]:#04x} B2={d[2]:#04x} B3={d[3]:#04x} "
                  f"B4={d[4]:#04x} B5={d[5]:#04x}  ec={ec:#05x}  b1c={bc:#05x}")
            prev_snap = t

print("\n" + "="*70)
print("SECTION 3: PARTSTRUCK TESTDRIVE (evap likely - truck reawakened)")
print("="*70)

for log_name, label in [
    ("vtrux_partstruck_testdrive.log",       "testdrive part1"),
    ("vtrux_partstruck_testdrive_part2.log",  "testdrive part2"),
]:
    log_path = LOGS / log_name
    print(f"\nStreaming {log_name}...", flush=True)
    frames, ptbus, n_total = stream_649(log_path)
    print(f"Done. {n_total:,} total frames, {len(frames):,} 0x649 frames  PT bus={ptbus}", flush=True)

    if not frames:
        print("  no 0x649 data")
        continue

    print(f"\n  [{label}] t={frames[0][0]:.2f}s - {frames[-1][0]:.2f}s")
    print(f"\n  First frame: t={frames[0][0]:.3f}s")
    print(f"    {fmt8(frames[0][1])}")
    print(f"    B0={frames[0][1][0]:#04x}  B4={frames[0][1][4]:#04x}  evap_ctr={evap_counter(frames[0][1]):#05x}")

    print(f"\n  Last frame: t={frames[-1][0]:.3f}s")
    print(f"    {fmt8(frames[-1][1])}")
    print(f"    B0={frames[-1][1][0]:#04x}  B4={frames[-1][1][4]:#04x}  evap_ctr={evap_counter(frames[-1][1]):#05x}")

    print(f"\n  B0 transitions:")
    b0_tr = transitions(frames, 0)
    if b0_tr:
        for t, bef, aft in b0_tr:
            print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}")
    else:
        print(f"    none (constant {frames[0][1][0]:#04x})")

    print(f"\n  B4 transitions:")
    b4_tr = transitions(frames, 4)
    if b4_tr:
        for t, bef, aft in b4_tr:
            print(f"    t={t:.3f}s: {bef:#04x} -> {aft:#04x}")
    else:
        print(f"    none (constant {frames[0][1][4]:#04x})")

    print(f"\n  B3 unique values: {len(set(d[3] for _, d in frames if d[3] is not None))}")
    b3_v = [d[3] for _, d in frames if d[3] is not None]
    if b3_v:
        print(f"  B3 range: {min(b3_v):#04x} - {max(b3_v):#04x}  net change: {b3_v[-1]-b3_v[0]:+d}")

    print(f"\n  Snapshot every 60s: t / B0 / B1 / B2 / B3 / B4 / B5 / evap_ctr / b1b2h_ctr")
    prev_snap = -999
    for t, d in frames:
        if t - prev_snap >= 60:
            ec = evap_counter(d)
            bc = b1_b2high_counter(d)
            print(f"    t={t:7.1f}  B0={d[0]:#04x} B1={d[1]:#04x} B2={d[2]:#04x} B3={d[3]:#04x} "
                  f"B4={d[4]:#04x} B5={d[5]:#04x}  ec={ec:#05x}  b1c={bc:#05x}")
            prev_snap = t

print("\n" + "="*70)
print("SECTION 4: B0 vs B4 EVAP FLAG COMPARISON ACROSS ALL LOGS")
print("  For each log: first B0/B4, any transitions, do they move together?")
print("="*70)

all_logs = [
    ("vtruxevapdrivelog4.log",             "evap4_p1",      "evap run (no completion)"),
    ("vtruxevapdrivelog4part2.log",        "evap4_p2",      "evap completion here"),
    ("vtruxanotherevaplogpart1.log",       "another_p1",    "pre-evap drive"),
    ("vtruxanotherevaplogpart2.log",       "another_p2",    "full evap cycle"),
    ("vtruxanotherevaplogpart3.log",       "another_p3",    "post-evap drive"),
    ("vtruxgeneratoroverheattest.log",     "gen_overheat",  "no evap (gen overheat test)"),
    ("vtrux_partstruck_testdrive.log",     "partstruck_p1", "reawakened truck"),
    ("vtrux_partstruck_testdrive_part2.log","partstruck_p2","continuation"),
    ("generator-on-then-off.log",          "gen_on_off",    "M-mode only, no evap"),
    ("oghighwaydrive.log",                 "og_highway",    "evap completion in this log"),
]

print(f"\n  {'log':20s}  {'B0_start':10s}  {'B4_start':10s}  {'B0_end':8s}  {'B4_end':8s}  "
      f"{'B0_changes':10s}  {'B4_changes':10s}  notes")
for log_name, short, note in all_logs:
    lp = LOGS / log_name
    if not lp.exists():
        print(f"  {short:20s}  NOT FOUND")
        continue
    frames = []
    for f in parse_file(str(lp)):
        if f.arbitration_id == TARGET_ID:
            data = list(f.data) + [None] * (8 - len(f.data))
            frames.append((f.timestamp, data[:8]))
    if not frames:
        print(f"  {short:20s}  no 0x649 data")
        continue

    b0_s = frames[0][1][0]
    b4_s = frames[0][1][4]
    b0_e = frames[-1][1][0]
    b4_e = frames[-1][1][4]
    b0_tr = transitions(frames, 0)
    b4_tr = transitions(frames, 4)

    b0_str = f"{b0_s:#04x}->{b0_e:#04x}" if b0_s != b0_e else f"{b0_s:#04x}(const)"
    b4_str = f"{b4_s:#04x}->{b4_e:#04x}" if b4_s != b4_e else f"{b4_s:#04x}(const)"

    simultaneous = ""
    if b0_tr and b4_tr:
        dt = b0_tr[0][0] - b4_tr[0][0]
        if abs(dt) < 0.05:
            simultaneous = f"B0/B4 together dt={dt*1000:.1f}ms"
        else:
            simultaneous = f"B0 at {b0_tr[0][0]:.3f}s, B4 at {b4_tr[0][0]:.3f}s (dt={dt:.3f}s)"

    b0_cnt = f"{len(b0_tr)} changes"
    b4_cnt = f"{len(b4_tr)} changes"
    print(f"  {short:20s}  {b0_str:10s}  {b4_str:10s}  {b0_cnt:12s}  {b4_cnt:12s}  {simultaneous}")

    if b0_tr:
        for t, bef, aft in b0_tr[:3]:
            print(f"    B0: t={t:.3f}s  {bef:#04x}->{aft:#04x}")
    if b4_tr:
        for t, bef, aft in b4_tr[:3]:
            print(f"    B4: t={t:.3f}s  {bef:#04x}->{aft:#04x}")

print("\nDone.")
