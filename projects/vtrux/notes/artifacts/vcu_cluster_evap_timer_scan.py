"""
Scan every byte (and 16-bit LE/BE pair) in the VCU cluster 0x639-0x64B across
both evap log series to find any signal that counts down/up monotonically during
engine-running/evap windows but NOT during non-evap engine runs (M-mode control).

Reference windows (from evap-cycle-analysis.md):
  evaplog4 part1: engine on t=431.7s, evap signaled t~540s, log ends t=1462s
  evaplog4 part2: evap completes t~12s, engine off t~16.7s
  anotherevap part2: engine on t=12.31s, evap completes t=1386.8s, engine off t=1392.8s
  anotherevap part2 M-mode: t=1455.7s - 1669.9s  (engine running, evap already done)
  anotherevap part2 stall: t=808-816s (engine stopped briefly mid-evap)
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

VCU_IDS = list(range(0x639, 0x64C))

LOGS = {
    "evap4_p1":    (r"projects\vtrux\logs\vtruxevapdrivelog4.log",        None,   None),
    "evap4_p2":    (r"projects\vtrux\logs\vtruxevapdrivelog4part2.log",   None,   None),
    "another_p1":  (r"projects\vtrux\logs\vtruxanotherevaplogpart1.log",  None,   None),
    "another_p2":  (r"projects\vtrux\logs\vtruxanotherevaplogpart2.log",  None,   None),
    "another_p3":  (r"projects\vtrux\logs\vtruxanotherevaplogpart3.log",  None,   None),
}

def is_pt_bus(bus_ids_map):
    pt_anchors = {0x051}
    for bus, ids in bus_ids_map.items():
        if ids & pt_anchors:
            return bus
    return None

def extract_byte_series(frames, arb_id, byte_idx, pt_bus, t_start=None, t_end=None):
    out = []
    for f in frames:
        if f.arbitration_id != arb_id:
            continue
        if pt_bus is not None and f.bus != pt_bus:
            continue
        if t_start is not None and f.timestamp < t_start:
            continue
        if t_end is not None and f.timestamp > t_end:
            continue
        if len(f.data) > byte_idx:
            out.append((f.timestamp, f.data[byte_idx]))
    return out

def monotonicity_score(series):
    if len(series) < 10:
        return 0.0, 0
    vals = [v for _, v in series]
    ups = sum(1 for a, b in zip(vals, vals[1:]) if b > a)
    downs = sum(1 for a, b in zip(vals, vals[1:]) if b < a)
    total = ups + downs
    if total == 0:
        return 0.0, 0
    dominant = max(ups, downs)
    score = dominant / total
    direction = 1 if ups > downs else -1
    return score, direction

def net_change(series):
    if len(series) < 2:
        return 0
    return series[-1][1] - series[0][1]

def unique_count(series):
    return len(set(v for _, v in series))

print("Loading logs...")
log_data = {}
for name, (path, _, _) in LOGS.items():
    p = Path(path)
    if not p.exists():
        print(f"  {name}: NOT FOUND")
        continue
    frames = list(parse_file(str(p)))
    bus_ids_map = defaultdict(set)
    for f in frames:
        bus_ids_map[f.bus].add(f.arbitration_id)
    pt_bus = is_pt_bus(bus_ids_map)
    log_data[name] = (frames, pt_bus)
    print(f"  {name}: {len(frames):,} frames  PT bus={pt_bus}  span={frames[0].timestamp:.1f}s-{frames[-1].timestamp:.1f}s")

print("\n")

evap4_p2_frames, evap4_p2_ptbus = log_data.get("evap4_p2", ([], None))
another_p2_frames, another_p2_ptbus = log_data.get("another_p2", ([], None))

WINDOWS = {
    "evap4_engine_run":  ("evap4_p1",   431.7,   1462.0,   "evap4: full engine run window"),
    "evap4_evap_start":  ("evap4_p1",   540.0,   1462.0,   "evap4: evap signaled -> end of part1"),
    "evap4_p2_evap":     ("evap4_p2",   0.0,     12.0,     "evap4 p2: evap completion window"),
    "another_evap_run":  ("another_p2", 12.31,   1386.8,   "another: engine on -> evap complete"),
    "another_mmode":     ("another_p2", 1455.7,  1669.9,   "another: M-mode engine run (no evap)"),
    "another_stall":     ("another_p2", 808.0,   816.0,    "another: involuntary stall (control)"),
    "another_p3":        ("another_p3", 0.0,     521.0,    "another part3: post-evap engine use"),
}

print("=" * 70)
print("PER-BYTE ANALYSIS: VCU cluster 0x639-0x64B")
print("Candidates = bytes that change monotonically during evap windows")
print("and show DIFFERENT behavior in M-mode control window")
print("=" * 70)

candidates = []

for arb_id in VCU_IDS:
    for byte_idx in range(8):
        results = {}
        for wname, (log_name, t0, t1, desc) in WINDOWS.items():
            if log_name not in log_data:
                continue
            frames, pt_bus = log_data[log_name]
            series = extract_byte_series(frames, arb_id, byte_idx, pt_bus, t0, t1)
            if len(series) < 5:
                results[wname] = None
                continue
            mono, direction = monotonicity_score(series)
            nc = net_change(series)
            uq = unique_count(series)
            results[wname] = (mono, direction, nc, uq, series[0][1], series[-1][1])

        evap_windows = ["evap4_engine_run", "another_evap_run"]
        ctrl_windows  = ["another_mmode", "another_stall"]

        evap_scores = [results[w][0] for w in evap_windows if results.get(w)]
        ctrl_scores  = [results[w][0] for w in ctrl_windows if results.get(w)]
        evap_uq      = [results[w][3] for w in evap_windows if results.get(w)]

        if not evap_scores:
            continue

        avg_evap_mono = sum(evap_scores) / len(evap_scores)
        avg_ctrl_mono = sum(ctrl_scores) / len(ctrl_scores) if ctrl_scores else 0.0
        avg_evap_uq   = sum(evap_uq) / len(evap_uq) if evap_uq else 0

        if avg_evap_mono >= 0.60 and avg_evap_uq >= 5:
            candidates.append((
                avg_evap_mono, avg_ctrl_mono, avg_evap_uq,
                arb_id, byte_idx, results
            ))

candidates.sort(key=lambda x: (x[0] - x[1]), reverse=True)

print(f"\n{len(candidates)} candidate bytes (mono >= 0.60 during evap, >= 5 unique values):\n")

for avg_evap_mono, avg_ctrl_mono, avg_evap_uq, arb_id, byte_idx, results in candidates:
    print(f"  0x{arb_id:03X} B{byte_idx}   evap_mono={avg_evap_mono:.2f}  ctrl_mono={avg_ctrl_mono:.2f}  "
          f"evap_uq~{avg_evap_uq:.0f}")
    for wname, r in results.items():
        if r is None:
            print(f"    [{wname:22s}] no data")
        else:
            mono, direction, nc, uq, v0, v1 = r
            dirstr = "up" if direction > 0 else "dn"
            print(f"    [{wname:22s}] mono={mono:.2f} {dirstr}  net={nc:+4d}  uq={uq:3d}  "
                  f"{v0:#04x}->{v1:#04x}")
    print()

print("\n" + "=" * 70)
print("16-BIT PAIR SCAN (LE and BE) across evap windows")
print("=" * 70)

pair_candidates = []
for arb_id in VCU_IDS:
    for b0 in range(7):
        b1 = b0 + 1
        for endian in ("LE", "BE"):
            results = {}
            for wname, (log_name, t0, t1, _) in WINDOWS.items():
                if log_name not in log_data:
                    continue
                frames, pt_bus = log_data[log_name]
                series_raw = []
                for f in frames:
                    if f.arbitration_id != arb_id:
                        continue
                    if pt_bus is not None and f.bus != pt_bus:
                        continue
                    if t0 is not None and f.timestamp < t0:
                        continue
                    if t1 is not None and f.timestamp > t1:
                        continue
                    if len(f.data) > b1:
                        if endian == "LE":
                            val = f.data[b0] | (f.data[b1] << 8)
                        else:
                            val = (f.data[b0] << 8) | f.data[b1]
                        series_raw.append((f.timestamp, val))
                if len(series_raw) < 5:
                    results[wname] = None
                    continue
                mono, direction = monotonicity_score(series_raw)
                nc = series_raw[-1][1] - series_raw[0][1]
                uq = len(set(v for _, v in series_raw))
                results[wname] = (mono, direction, nc, uq, series_raw[0][1], series_raw[-1][1])

            evap_scores = [results[w][0] for w in ["evap4_engine_run", "another_evap_run"] if results.get(w)]
            ctrl_scores  = [results[w][0] for w in ["another_mmode"] if results.get(w)]
            evap_uq      = [results[w][3] for w in ["evap4_engine_run", "another_evap_run"] if results.get(w)]

            if not evap_scores:
                continue
            avg_evap_mono = sum(evap_scores) / len(evap_scores)
            avg_ctrl_mono = sum(ctrl_scores) / len(ctrl_scores) if ctrl_scores else 0.0
            avg_evap_uq   = sum(evap_uq) / len(evap_uq) if evap_uq else 0

            if avg_evap_mono >= 0.65 and avg_evap_uq >= 20:
                pair_candidates.append((
                    avg_evap_mono, avg_ctrl_mono, avg_evap_uq,
                    arb_id, b0, b1, endian, results
                ))

pair_candidates.sort(key=lambda x: (x[0] - x[1]), reverse=True)
print(f"\n{len(pair_candidates)} candidate pairs:\n")

for avg_evap_mono, avg_ctrl_mono, avg_evap_uq, arb_id, b0, b1, endian, results in pair_candidates:
    print(f"  0x{arb_id:03X} B{b0}-B{b1} {endian}  evap_mono={avg_evap_mono:.2f}  ctrl_mono={avg_ctrl_mono:.2f}  "
          f"evap_uq~{avg_evap_uq:.0f}")
    for wname, r in results.items():
        if r is None:
            print(f"    [{wname:22s}] no data")
        else:
            mono, direction, nc, uq, v0, v1 = r
            dirstr = "up" if direction > 0 else "dn"
            print(f"    [{wname:22s}] mono={mono:.2f} {dirstr}  net={nc:+6d}  uq={uq:4d}  "
                  f"{v0:#06x}->{v1:#06x}")
    print()

print("Done.")
