"""
Thermal correlation scan -- vtruxunpluggedpumpoverheattest.log

Correlates all PT bus (bus 3) byte/word timeseries against the confirmed
DCDC temperature reference (0x18FFD6B3 B6-B7, LE signed x0.1 degC).

Rules applied per CLAUDE.md correlation methodology:
  1. Full-log per-byte r AND windowed per-byte r (t=100-411s stable ramp)
     -- windowed catches multi-byte signals whose MSB steps mid-log
  2. Per-byte tests alongside LE/BE uint16 pair tests
     -- zone+fine signals show high pair r but near-zero low-byte r
  3. No delta correlation first pass (staircase reference makes it noisy)

Reference: 0x18FFD6B3 B6-B7, LE signed x0.1 degC  (already in overheat_dcdc_temp.csv)
Stable window: t=100-411s  (after DCDC startup transient, before key-off gap at t=411.7s)
"""

import sys, os, csv
from pathlib import Path
from collections import defaultdict
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from canre.parsers.autodetect import parse_file

LOG     = ROOT / "projects/vtrux/logs/vtruxunpluggedpumpoverheattest.log"
PT_BUS  = 3
REF_ID  = 0x18FFD6B3
WINDOW_START = 100.0
WINDOW_END   = 411.0
MIN_FULL = 10
MIN_WIN  = 5
R_THRESH = 0.35   # only report candidates above this

# ---- load reference ----
ref_csv = ROOT / "projects/vtrux/notes/artifacts/overheat_dcdc_temp.csv"
ref_rows = list(csv.DictReader(open(ref_csv)))
ref_t = np.array([float(r["timestamp"]) for r in ref_rows])
ref_v = np.array([float(r["value"])     for r in ref_rows])   # raw signed int16

win_mask_ref = (ref_t >= WINDOW_START) & (ref_t <= WINDOW_END)
ref_t_win = ref_t[win_mask_ref]
ref_v_win = ref_v[win_mask_ref]

print("Reference: %d full-log samples, %d windowed samples" % (len(ref_t), len(ref_t_win)))
print("Reference range: %.1fC to %.1fC" % (ref_v.min()*0.1, ref_v.max()*0.1))

# ---- parse log: collect all PT bus frames by ID ----
print("Parsing log ...", flush=True)
frames_by_id = defaultdict(lambda: {"t": [], "data": []})
for frame in parse_file(str(LOG)):
    if frame.bus != PT_BUS:
        continue
    if frame.arbitration_id == REF_ID:
        continue
    frames_by_id[frame.arbitration_id]["t"].append(frame.timestamp)
    frames_by_id[frame.arbitration_id]["data"].append(bytes(frame.data))

print("Loaded %d IDs from PT bus (reference excluded)" % len(frames_by_id))

# ---- helpers ----
def pearson_r(x, y):
    if len(x) < 2:
        return np.nan
    sx, sy = x.std(), y.std()
    if sx < 1e-9 or sy < 1e-9:
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])

def best_r(r_full, r_win):
    a = abs(r_full) if not np.isnan(r_full) else 0.0
    b = abs(r_win)  if not np.isnan(r_win)  else 0.0
    return max(a, b)

# ---- scan ----
results = []   # (best, r_full, r_win, can_id, label, n_full, n_win)

for can_id, rec in sorted(frames_by_id.items()):
    t_all  = np.array(rec["t"], dtype=float)
    data_all = rec["data"]
    n_full = len(t_all)
    if n_full < MIN_FULL:
        continue

    dlc = max(len(d) for d in data_all)

    # build byte arrays (pad short frames with 0)
    byte_arrs = np.zeros((dlc, n_full), dtype=float)
    for i, d in enumerate(data_all):
        for b in range(len(d)):
            byte_arrs[b, i] = d[b]

    # windowed mask
    wmask = (t_all >= WINDOW_START) & (t_all <= WINDOW_END)
    n_win = int(wmask.sum())
    t_win = t_all[wmask]

    # interpolate reference onto candidate timestamps
    ref_interp_full = np.interp(t_all, ref_t, ref_v)
    ref_interp_win  = np.interp(t_win, ref_t_win, ref_v_win) if n_win >= MIN_WIN else None

    # --- per-byte ---
    for b in range(dlc):
        v = byte_arrs[b]

        rf = pearson_r(v, ref_interp_full) if n_full >= MIN_FULL else np.nan
        rw = np.nan
        if ref_interp_win is not None and n_win >= MIN_WIN:
            rw = pearson_r(v[wmask], ref_interp_win)

        br = best_r(rf, rw)
        if br >= R_THRESH:
            results.append((br, rf, rw, can_id, "B%d" % b, n_full, n_win))

    # --- LE uint16 pairs ---
    for b in range(dlc - 1):
        v16 = byte_arrs[b] + byte_arrs[b+1] * 256.0

        rf = pearson_r(v16, ref_interp_full) if n_full >= MIN_FULL else np.nan
        rw = np.nan
        if ref_interp_win is not None and n_win >= MIN_WIN:
            rw = pearson_r(v16[wmask], ref_interp_win)

        br = best_r(rf, rw)
        if br >= R_THRESH:
            results.append((br, rf, rw, can_id, "B%d-%d_LE" % (b, b+1), n_full, n_win))

    # --- BE uint16 pairs ---
    for b in range(dlc - 1):
        v16 = byte_arrs[b+1] + byte_arrs[b] * 256.0

        rf = pearson_r(v16, ref_interp_full) if n_full >= MIN_FULL else np.nan
        rw = np.nan
        if ref_interp_win is not None and n_win >= MIN_WIN:
            rw = pearson_r(v16[wmask], ref_interp_win)

        br = best_r(rf, rw)
        if br >= R_THRESH:
            results.append((br, rf, rw, can_id, "B%d-%d_BE" % (b, b+1), n_full, n_win))

# ---- output ----
results.sort(key=lambda x: -x[0])

out_path = ROOT / "projects/vtrux/notes/artifacts/overheat_thermal_candidates.txt"
hdr = "%-16s %-12s %8s %8s %6s %7s %6s" % ("ID", "Bytes", "r_full", "r_win", "best", "n_full", "n_win")
sep = "-" * len(hdr)

lines = [
    "Thermal correlation scan -- vtruxunpluggedpumpoverheattest.log",
    "Reference: 0x18FFD6B3 B6-B7 (DCDC temp, LE signed x0.1 degC)",
    "Window: t=%.0f-%.0fs  |  Threshold: |r|>=%.2f" % (WINDOW_START, WINDOW_END, R_THRESH),
    "",
    hdr, sep
]

for best, rf, rw, can_id, label, n_full, n_win in results:
    id_str = "0x%X" % can_id
    rf_s = "%+.4f" % rf if not np.isnan(rf) else "     nan"
    rw_s = "%+.4f" % rw if not np.isnan(rw)  else "     nan"
    flag = " <-- win>full" if (not np.isnan(rw) and not np.isnan(rf) and abs(rw) > abs(rf) + 0.15) else ""
    lines.append("%-16s %-12s %8s %8s %6.4f %7d %6d%s" % (
        id_str, label, rf_s, rw_s, best, n_full, n_win, flag))

output = "\n".join(lines)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(output + "\n")

# print to stdout (top 60 lines)
for line in lines[:60]:
    print(line)
if len(lines) > 60:
    print("... (%d more lines, see %s)" % (len(lines) - 60, out_path))

print()
print("Total candidates: %d  |  Saved to: %s" % (len(results), out_path))
