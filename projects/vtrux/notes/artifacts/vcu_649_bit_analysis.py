"""
Deep analysis of all bits in 0x649 across evap vs control windows.

Goals:
1. Bit-level discrimination: for each of the 64 bit positions, what fraction of
   frames is that bit SET in evap windows vs M-mode control?
2. Step-size analysis: how much does each byte increment per sample during evap,
   to see if B3 is the LSB of a wider counter or B2 carries MSBs.
3. Full 0x649 message trace at key transition points (evap start, completion,
   stall, M-mode start/stop) to see all 8 bytes together.
4. Adjacent byte pairing: test B2-B3 as a 16-bit counter with the hypothesis
   that B2 is the MSB (upper nibble steps in sync with B3 wrapping).
"""

import csv
from pathlib import Path
from collections import defaultdict, Counter

ARTIFACTS = Path(r"projects\vtrux\notes\artifacts")

CSVS = {
    "evap4_p1":   ARTIFACTS / "vcu_evap4_p1.csv",
    "evap4_p2":   ARTIFACTS / "vcu_evap4_p2.csv",
    "another_p2": ARTIFACTS / "vcu_another_p2.csv",
    "another_p3": ARTIFACTS / "vcu_another_p3.csv",
}

WINDOWS = {
    "e4_engine_run":  ("evap4_p1",   431.7,   1462.0),
    "a2_evap_run":    ("another_p2", 12.31,   1386.8),
    "a2_mmode":       ("another_p2", 1455.7,  1669.9),
    "a2_stall":       ("another_p2", 808.0,   816.0),
    "e4_pre_engine":  ("evap4_p1",   0.0,     431.7),
    "a3_post":        ("another_p3", 0.0,     521.0),
}

TARGET_ID = 0x649

def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = float(row["t"])
            arb_id = int(row["id"], 16)
            if arb_id != TARGET_ID:
                continue
            data = [int(row[f"b{i}"]) if row.get(f"b{i}", "") != "" else None for i in range(8)]
            rows.append((t, data))
    return rows

print("Loading CSVs (0x649 only)...")
log_data = {}
for name, path in CSVS.items():
    if not path.exists():
        print(f"  {name}: NOT FOUND")
        continue
    rows = load_csv(path)
    log_data[name] = rows
    print(f"  {name}: {len(rows):,} frames  t={rows[0][0]:.1f}-{rows[-1][0]:.1f}s", flush=True)

def get_window(log_name, t0, t1):
    return [(t, d) for t, d in log_data.get(log_name, []) if t0 <= t <= t1]

print("\nPre-building windows...", flush=True)
windows = {wname: get_window(ln, t0, t1) for wname, (ln, t0, t1) in WINDOWS.items()}
for wname, rows in windows.items():
    print(f"  {wname}: {len(rows):,} frames", flush=True)

print("\n" + "="*70)
print("SECTION 1: BIT-LEVEL DISCRIMINATION (all 64 bit positions)")
print("  set_frac_evap vs set_frac_ctrl (evap = e4+a2 runs, ctrl = mmode+pre+post)")
print("="*70)

evap_wins  = ["e4_engine_run", "a2_evap_run"]
ctrl_wins  = ["a2_mmode", "e4_pre_engine", "a3_post"]

for byte_idx in range(8):
    evap_set = evap_tot = 0
    ctrl_set = ctrl_tot = 0
    for wname in evap_wins:
        for _, d in windows[wname]:
            if d[byte_idx] is not None:
                evap_tot += 8
                evap_set += bin(d[byte_idx]).count("1")
    for wname in ctrl_wins:
        for _, d in windows[wname]:
            if d[byte_idx] is not None:
                ctrl_tot += 8
                ctrl_set += bin(d[byte_idx]).count("1")
    evap_avg = evap_set / evap_tot if evap_tot else 0
    ctrl_avg = ctrl_set / ctrl_tot if ctrl_tot else 0

    bit_lines = []
    for bit in range(7, -1, -1):
        mask = 1 << bit
        e_set = e_tot = c_set = c_tot = 0
        for wname in evap_wins:
            for _, d in windows[wname]:
                if d[byte_idx] is not None:
                    e_tot += 1
                    if d[byte_idx] & mask:
                        e_set += 1
        for wname in ctrl_wins:
            for _, d in windows[wname]:
                if d[byte_idx] is not None:
                    c_tot += 1
                    if d[byte_idx] & mask:
                        c_set += 1
        ef = e_set / e_tot if e_tot else 0
        cf = c_set / c_tot if c_tot else 0
        delta = ef - cf
        flag = " <<<" if abs(delta) >= 0.3 else ""
        bit_lines.append(f"    bit{bit}: evap={ef:.2f}  ctrl={cf:.2f}  delta={delta:+.2f}{flag}")

    print(f"\n  B{byte_idx}  (evap bit density={evap_avg:.3f}, ctrl={ctrl_avg:.3f})")
    for line in bit_lines:
        print(line)

print("\n" + "="*70)
print("SECTION 2: STEP-SIZE DISTRIBUTION (how much each byte changes per frame)")
print("  During evap run vs M-mode vs stall")
print("="*70)

for byte_idx in range(8):
    print(f"\n  B{byte_idx}:")
    for wname in ["e4_engine_run", "a2_evap_run", "a2_mmode", "a2_stall"]:
        frames = windows[wname]
        vals = [d[byte_idx] for _, d in frames if d[byte_idx] is not None]
        if len(vals) < 10:
            print(f"    [{wname:18s}] too few frames")
            continue
        steps = [b - a for a, b in zip(vals, vals[1:]) if b != a]
        if not steps:
            print(f"    [{wname:18s}] no changes")
            continue
        step_counts = Counter(steps)
        top = step_counts.most_common(5)
        total_nonzero = sum(step_counts.values())
        print(f"    [{wname:18s}] {total_nonzero} changes, top steps: {top}")

print("\n" + "="*70)
print("SECTION 3: B2 UPPER NIBBLE vs B3 COUNTER HYPOTHESIS")
print("  If B2[7:4] is the MSB of a 12-bit counter and B3 is LSB,")
print("  B2 upper nibble should increment by 1 each time B3 wraps 0xFF->0x00")
print("="*70)

for wname in ["a2_evap_run", "a2_mmode"]:
    frames = windows[wname]
    print(f"\n  Window: {wname} ({len(frames)} frames)")
    b2_vals = [d[2] for _, d in frames if d[2] is not None]
    b3_vals = [d[3] for _, d in frames if d[3] is not None]
    if not b2_vals or not b3_vals:
        print("    no data")
        continue

    b2_nibbles = [v >> 4 for v in b2_vals]
    b2_low     = [v & 0x0F for v in b2_vals]

    print(f"    B2 range: {min(b2_vals):#04x}-{max(b2_vals):#04x}  unique={len(set(b2_vals))}")
    print(f"    B2 upper nibble unique values: {sorted(set(b2_nibbles))}")
    print(f"    B2 lower nibble unique values: {sorted(set(b2_low))}")
    print(f"    B3 range: {min(b3_vals):#04x}-{max(b3_vals):#04x}  unique={len(set(b3_vals))}")

    b3_wraps = []
    for i in range(1, len(b3_vals)):
        if b3_vals[i-1] > 0xF0 and b3_vals[i] < 0x10:
            b3_wraps.append(i)
    print(f"    B3 wrap events (0xFF->0x00): {len(b3_wraps)}")
    for wi in b3_wraps[:5]:
        t = frames[wi][0]
        b2_before = b2_vals[wi-1]
        b2_after  = b2_vals[wi]
        b3_before = b3_vals[wi-1]
        b3_after  = b3_vals[wi]
        print(f"      t={t:.2f}s: B2 {b2_before:#04x}->{b2_after:#04x}  B3 {b3_before:#04x}->{b3_after:#04x}")

print("\n" + "="*70)
print("SECTION 4: FULL MESSAGE TRACE AT KEY TRANSITIONS")
print("  Show all 8 bytes of 0x649 around evap-start, evap-complete,")
print("  stall start/end, and M-mode start in another_p2")
print("="*70)

all_p2 = [(t, d) for t, d in log_data.get("another_p2", [])]

PIVOTS = [
    (12.31,   "engine auto-start (evap begin)"),
    (808.42,  "stall start"),
    (815.81,  "stall end / engine restart"),
    (1386.8,  "evap complete / B0 clears"),
    (1392.79, "engine auto-off"),
    (1455.66, "M-mode start"),
    (1669.86, "M-mode end"),
]

def frames_near(all_frames, t_pivot, n_before=3, n_after=3):
    idx = None
    for i, (t, _) in enumerate(all_frames):
        if t >= t_pivot:
            idx = i
            break
    if idx is None:
        return []
    start = max(0, idx - n_before)
    end   = min(len(all_frames), idx + n_after + 1)
    return all_frames[start:end]

header = "  t(s)      B0   B1   B2   B3   B4   B5   B6   B7"
for t_pivot, label in PIVOTS:
    print(f"\n  --- {label} (t={t_pivot}s) ---")
    print(header)
    nearby = frames_near(all_p2, t_pivot, n_before=4, n_after=4)
    for t, d in nearby:
        marker = " <--" if abs(t - t_pivot) < 0.05 else ""
        vals = "  ".join(f"{v:#04x}" if v is not None else "  -- " for v in d)
        print(f"  {t:9.3f}  {vals}{marker}")

print("\n" + "="*70)
print("SECTION 5: B3 COUNT RATE vs TIME (during a2_evap_run)")
print("  Estimate counts per second in 60-second windows to see if rate is stable")
print("="*70)

frames_evap = windows["a2_evap_run"]
if frames_evap:
    t_start = frames_evap[0][0]
    t_end   = frames_evap[-1][0]
    window_size = 120.0
    step = 60.0
    t = t_start
    print(f"  {'t_start':>8}  {'t_end':>8}  {'b3_start':>9}  {'b3_end':>7}  {'counts':>7}  {'rate c/s':>9}")
    while t + window_size <= t_end:
        seg = [(ts, d) for ts, d in frames_evap if t <= ts <= t + window_size]
        if len(seg) >= 2:
            v0 = seg[0][1][3]
            v1 = seg[-1][1][3]
            if v0 is not None and v1 is not None:
                dt = seg[-1][0] - seg[0][0]
                raw_net = v1 - v0
                counts = raw_net if raw_net >= 0 else raw_net + 256
                rate = counts / dt if dt > 0 else 0
                print(f"  {t:>8.0f}  {t+window_size:>8.0f}  {v0:#010x}  {v1:#08x}  {counts:>7}  {rate:>9.4f}")
        t += step

print("\nDone.")
