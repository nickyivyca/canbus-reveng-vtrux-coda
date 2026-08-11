"""
Analyze VCU cluster (0x639-0x64B) CSVs for evap timer signals.
Looks for bytes/pairs that trend monotonically during engine-running/evap windows.
Cross-validates against M-mode (engine on, no evap) and pre-engine windows.

Key reference times (from evap-cycle-analysis.md):
  evap4_p1:   engine on t=431.7s, log ends t=1462s
  evap4_p2:   evap completes t~12s, engine off t~16.7s
  another_p2: engine on t=12.31s, evap complete t=1386.794s, engine off t=1392.79s
              M-mode t=1455.7-1669.9s (engine on, evap already done)
              stall t=808-816s (engine briefly off mid-evap)

Performance: pre-groups rows by (window, arb_id) so each log is scanned once per window,
not once per (arb_id, byte) combination.
"""

import csv
import sys
from pathlib import Path
from collections import defaultdict

ARTIFACTS = Path(r"projects\vtrux\notes\artifacts")

CSVS = {
    "evap4_p1":   ARTIFACTS / "vcu_evap4_p1.csv",
    "evap4_p2":   ARTIFACTS / "vcu_evap4_p2.csv",
    "another_p1": ARTIFACTS / "vcu_another_p1.csv",
    "another_p2": ARTIFACTS / "vcu_another_p2.csv",
    "another_p3": ARTIFACTS / "vcu_another_p3.csv",
}

WINDOWS = {
    "e4_pre_engine":  ("evap4_p1",   0,       431.7,   "evap4: before engine on (baseline)"),
    "e4_engine_run":  ("evap4_p1",   431.7,   1462.0,  "evap4: full engine run (evap+hybrid)"),
    "e4_evap_only":   ("evap4_p1",   540.0,   1462.0,  "evap4: after evap signaled"),
    "e4_p2_end":      ("evap4_p2",   0.0,     12.0,    "evap4 p2: final evap completion"),
    "a2_evap_run":    ("another_p2", 12.31,   1386.8,  "another: engine on -> evap complete"),
    "a2_mmode":       ("another_p2", 1455.7,  1669.9,  "another: M-mode, no evap (control)"),
    "a2_stall":       ("another_p2", 808.0,   816.0,   "another: stall (control)"),
    "a3_post":        ("another_p3", 0.0,     521.0,   "another p3: post-evap"),
}

VCU_IDS = list(range(0x639, 0x64C))

def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = float(row["t"])
            arb_id = int(row["id"], 16)
            data = [int(row[f"b{i}"]) if row.get(f"b{i}", "") != "" else None for i in range(8)]
            rows.append((t, arb_id, data))
    return rows

print("Loading CSVs...")
log_data = {}
for name, path in CSVS.items():
    if not path.exists():
        print(f"  {name}: NOT FOUND at {path}")
        continue
    rows = load_csv(path)
    log_data[name] = rows
    print(f"  {name}: {len(rows):,} rows  t={rows[0][0]:.1f}s-{rows[-1][0]:.1f}s", flush=True)

# Pre-group by window then arb_id: window_groups[wname][arb_id] = [(t, data), ...]
print("\nPre-grouping windows...", flush=True)
window_groups = {}
for wname, (log_name, t0, t1, desc) in WINDOWS.items():
    if log_name not in log_data:
        window_groups[wname] = {}
        continue
    by_id = defaultdict(list)
    for t, arb_id, data in log_data[log_name]:
        if t0 <= t <= t1:
            by_id[arb_id].append((t, data))
    window_groups[wname] = by_id
    total = sum(len(v) for v in by_id.values())
    print(f"  {wname}: {total:,} rows in window", flush=True)

def monotonicity(vals):
    if len(vals) < 10:
        return 0.0, 0, 0
    ups   = sum(1 for a, b in zip(vals, vals[1:]) if b > a)
    downs = sum(1 for a, b in zip(vals, vals[1:]) if b < a)
    total = ups + downs
    if total == 0:
        return 0.0, 0, 0
    direction = 1 if ups >= downs else -1
    return max(ups, downs) / total, direction, total

def compute_stats(vals):
    if not vals or len(vals) < 2:
        return None
    mono, dirn, moves = monotonicity(vals)
    uq = len(set(vals))
    return {"mono": mono, "dir": dirn, "uq": uq, "net": vals[-1] - vals[0],
            "v0": vals[0], "v1": vals[-1], "n": len(vals)}

def byte_stats(wname, arb_id, byte_idx):
    rows = window_groups.get(wname, {}).get(arb_id, [])
    vals = [d[byte_idx] for _, d in rows if d[byte_idx] is not None]
    return compute_stats(vals)

def pair_stats(wname, arb_id, b0, b1, endian):
    rows = window_groups.get(wname, {}).get(arb_id, [])
    vals = []
    for _, d in rows:
        if d[b0] is None or d[b1] is None:
            continue
        v = (d[b0] | (d[b1] << 8)) if endian == "LE" else ((d[b0] << 8) | d[b1])
        vals.append(v)
    return compute_stats(vals)

print("\n" + "="*65)
print("BYTE-LEVEL SCAN")
print("="*65, flush=True)

byte_candidates = []

for arb_id in VCU_IDS:
    for byte_idx in range(8):
        wstats = {wname: byte_stats(wname, arb_id, byte_idx) for wname in WINDOWS}

        evap_wins = ["e4_engine_run", "a2_evap_run"]
        ctrl_wins = ["a2_mmode", "e4_pre_engine"]

        evap_monos = [wstats[w]["mono"] for w in evap_wins if wstats.get(w) and wstats[w]["n"] >= 10]
        ctrl_monos = [wstats[w]["mono"] for w in ctrl_wins if wstats.get(w) and wstats[w]["n"] >= 10]
        evap_uq    = [wstats[w]["uq"]   for w in evap_wins if wstats.get(w) and wstats[w]["n"] >= 10]

        if not evap_monos or not evap_uq:
            continue

        avg_emono = sum(evap_monos) / len(evap_monos)
        avg_cmono = sum(ctrl_monos) / len(ctrl_monos) if ctrl_monos else 0.0
        avg_uq    = sum(evap_uq)    / len(evap_uq)

        if avg_emono >= 0.58 and avg_uq >= 6:
            byte_candidates.append((avg_emono - avg_cmono, avg_emono, avg_cmono, avg_uq,
                                    arb_id, byte_idx, wstats))

byte_candidates.sort(reverse=True)

print(f"\n{len(byte_candidates)} byte candidates (evap_mono>=0.58, uq>=6):")
for delta, avg_em, avg_cm, avg_uq, arb_id, byte_idx, wstats in byte_candidates:
    dirn = "dn" if any(wstats.get(w) and wstats[w]["dir"] < 0
                       for w in ["e4_engine_run","a2_evap_run"]) else "up"
    print(f"\n  0x{arb_id:03X} B{byte_idx}  evap_mono={avg_em:.2f} {dirn}  ctrl_mono={avg_cm:.2f}  "
          f"delta={delta:+.2f}  evap_uq~{avg_uq:.0f}")
    for wname, (_, _, _, desc) in WINDOWS.items():
        s = wstats.get(wname)
        if s is None or s["n"] < 5:
            print(f"    [{wname:18s}] no data")
        else:
            dirstr = "up" if s["dir"] > 0 else "dn"
            print(f"    [{wname:18s}] mono={s['mono']:.2f} {dirstr}  net={s['net']:+5d}  "
                  f"uq={s['uq']:3d}  {s['v0']:#04x}->{s['v1']:#04x}  (n={s['n']:,})")

print("\n" + "="*65)
print("16-BIT PAIR SCAN (LE and BE)")
print("="*65, flush=True)

pair_candidates = []

for arb_id in VCU_IDS:
    for b0_idx in range(7):
        b1_idx = b0_idx + 1
        for endian in ("LE", "BE"):
            wstats = {wname: pair_stats(wname, arb_id, b0_idx, b1_idx, endian) for wname in WINDOWS}

            evap_wins = ["e4_engine_run", "a2_evap_run"]
            ctrl_wins = ["a2_mmode", "e4_pre_engine"]

            evap_monos = [wstats[w]["mono"] for w in evap_wins if wstats.get(w) and wstats[w]["n"] >= 10]
            ctrl_monos = [wstats[w]["mono"] for w in ctrl_wins if wstats.get(w) and wstats[w]["n"] >= 10]
            evap_uq    = [wstats[w]["uq"]   for w in evap_wins if wstats.get(w) and wstats[w]["n"] >= 10]

            if not evap_monos or not evap_uq:
                continue

            avg_em = sum(evap_monos) / len(evap_monos)
            avg_cm = sum(ctrl_monos) / len(ctrl_monos) if ctrl_monos else 0.0
            avg_uq = sum(evap_uq)    / len(evap_uq)

            if avg_em >= 0.65 and avg_uq >= 20:
                pair_candidates.append((avg_em - avg_cm, avg_em, avg_cm, avg_uq,
                                        arb_id, b0_idx, b1_idx, endian, wstats))

pair_candidates.sort(reverse=True)
print(f"\n{len(pair_candidates)} pair candidates (evap_mono>=0.65, uq>=20):")

for delta, avg_em, avg_cm, avg_uq, arb_id, b0i, b1i, endian, wstats in pair_candidates:
    dirn = "dn" if any(wstats.get(w) and wstats[w]["dir"] < 0
                       for w in ["e4_engine_run","a2_evap_run"]) else "up"
    print(f"\n  0x{arb_id:03X} B{b0i}-B{b1i} {endian}  evap_mono={avg_em:.2f} {dirn}  "
          f"ctrl_mono={avg_cm:.2f}  delta={delta:+.2f}  evap_uq~{avg_uq:.0f}")
    for wname, (_, _, _, desc) in WINDOWS.items():
        s = wstats.get(wname)
        if s is None or s["n"] < 5:
            print(f"    [{wname:18s}] no data")
        else:
            dirstr = "up" if s["dir"] > 0 else "dn"
            print(f"    [{wname:18s}] mono={s['mono']:.2f} {dirstr}  net={s['net']:+7d}  "
                  f"uq={s['uq']:4d}  {s['v0']:#06x}->{s['v1']:#06x}  (n={s['n']:,})")

print("\n" + "="*65)
print("CROSS-SESSION CONTINUITY CHECK")
print("For top byte candidates: compare end-of-session vs start-of-next")
print("="*65, flush=True)

top_bytes = [(arb_id, byte_idx) for _, _, _, _, arb_id, byte_idx, _ in byte_candidates[:8]]
top_pairs = [(arb_id, b0i, b1i, endian) for _, _, _, _, arb_id, b0i, b1i, endian, _ in pair_candidates[:5]]

session_windows = {
    "another_p1": (0, 364),
    "another_p2": (0, 2011),
    "another_p3": (0, 521),
}

# Build session groups for continuity check
session_groups = {}
for sname, (t0, t1) in session_windows.items():
    if sname not in log_data:
        session_groups[sname] = {}
        continue
    by_id = defaultdict(list)
    for t, arb_id, data in log_data[sname]:
        if t0 <= t <= t1:
            by_id[arb_id].append((t, data))
    session_groups[sname] = by_id

for arb_id, byte_idx in top_bytes:
    print(f"\n  0x{arb_id:03X} B{byte_idx} across anotherevap sessions:")
    for sname in ["another_p1", "another_p2", "another_p3"]:
        rows = session_groups.get(sname, {}).get(arb_id, [])
        vals = [(t, d[byte_idx]) for t, d in rows if d[byte_idx] is not None]
        if len(vals) < 2:
            print(f"    {sname}: no data")
            continue
        first5 = [v for _, v in vals[:5]]
        last5  = [v for _, v in vals[-5:]]
        print(f"    {sname}: start={first5}  end={last5}  uq={len(set(v for _,v in vals))}")

for arb_id, b0i, b1i, endian in top_pairs:
    print(f"\n  0x{arb_id:03X} B{b0i}-B{b1i} {endian} across anotherevap sessions:")
    for sname in ["another_p1", "another_p2", "another_p3"]:
        rows = session_groups.get(sname, {}).get(arb_id, [])
        vals = []
        for t, d in rows:
            if d[b0i] is None or d[b1i] is None:
                continue
            v = (d[b0i] | (d[b1i] << 8)) if endian == "LE" else ((d[b0i] << 8) | d[b1i])
            vals.append((t, v))
        if len(vals) < 2:
            print(f"    {sname}: no data")
            continue
        first3 = [v for _, v in vals[:3]]
        last3  = [v for _, v in vals[-3:]]
        print(f"    {sname}: start={first3}  end={last3}  uq={len(set(v for _,v in vals))}")

print("\nDone.")
