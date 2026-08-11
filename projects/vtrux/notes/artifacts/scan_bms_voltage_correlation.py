"""
Three-pass BMS voltage correlation scan.

Scans all BMS-originated IDs against DCDC HV input voltage (0x18FFD6B3 B4-B5)
as reference, using the full CLAUDE.md correlation methodology:

  Pass 1: Full-log Pearson r (per-byte and LE/BE uint16 pairs)
  Pass 2: Windowed Pearson r (60s windows, MSB-stable) -- catches signals
           where MSB steps collapse full-log r
  Pass 3: Delta correlation (frame-to-frame differences) -- immune to MSB steps

Log: vtruxevapdrivelog4part2.log
Reference filter: DCDC V > 300V (exclude key-off collapse)

BMS-originated IDs (require HV battery LV connector):
  0x370-0x375, 0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507

Known signals (annotated in output but not excluded from scan):
  0x411 B0-B1 BE: high-res SoC
  0x412 B2: CCL source
  0x420 B3: isolation resistance
  0x430 B0-B3: cell min/max voltage + temp
  0x440 B3-B4: rejected (flat/latched)
"""

import sys, os, struct, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = r'<home>\<drive-root>\<library>\My Libraries\Projects\reverse-it\projects\vtrux\logs\vtruxevapdrivelog4part2.log'
OUT = os.path.join(os.path.dirname(__file__), 'scan_bms_voltage_output.txt')

REF_ID   = 0x18FFD6B3
V_FILTER = 300.0   # only use DCDC samples above this
WINDOW_S = 60.0    # window size for Pass 2
MIN_SAMP = 20      # minimum paired samples required

BMS_IDS = [0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
           0x400, 0x410, 0x411, 0x412, 0x420, 0x430,
           0x440, 0x460, 0x506, 0x507]

KNOWN = {
    (0x411, 'B0-B1 BE'): 'high-res SoC',
    (0x412, 'B2'):        'CCL source',
    (0x420, 'B3'):        'isolation resistance',
    (0x430, 'B0-B1 LE'): 'V_max cell (known)',
    (0x430, 'B2-B3 LE'): 'V_min cell (known)',
    (0x430, 'B4'):        'T_max cell (known)',
    (0x430, 'B5'):        'T_min cell (known)',
    (0x440, 'B3-B4 LE'): 'REJECTED flat/latched',
}

# ---- Parse log -------------------------------------------------------
print("Parsing log...", flush=True)
ref_ts  = []   # (t, V)
bus_ts  = {id_: [] for id_ in BMS_IDS}   # id -> [(t, bytes)]

for frame in parse_file(LOG):
    fid = frame.arbitration_id
    if fid == REF_ID and len(frame.data) >= 6:
        v = struct.unpack_from('<h', frame.data, 4)[0] * 0.05
        if v > V_FILTER:
            ref_ts.append((frame.timestamp, v))
    elif fid in bus_ts:
        bus_ts[fid].append((frame.timestamp, bytes(frame.data)))

print(f"  DCDC reference samples (V>{V_FILTER:.0f}): {len(ref_ts)}")
for id_ in BMS_IDS:
    n = len(bus_ts[id_])
    if n:
        dlc = len(bus_ts[id_][0][1])
        print(f"  0x{id_:03X}: {n} frames, DLC={dlc}")
print()

if len(ref_ts) < MIN_SAMP:
    print("ERROR: insufficient reference samples")
    sys.exit(1)

# ---- Helpers ---------------------------------------------------------

def pearson(xs, ys):
    n = len(xs)
    if n < MIN_SAMP: return None
    mx = sum(xs)/n; my = sum(ys)/n
    cov = sum((x-mx)*(y-my) for x,y in zip(xs,ys))/n
    sx  = math.sqrt(sum((x-mx)**2 for x in xs)/n)
    sy  = math.sqrt(sum((y-my)**2 for y in ys)/n)
    if sx < 1e-9 or sy < 1e-9: return None
    return cov / (sx * sy)

def nearest_ref(t, max_dt=0.5):
    """Binary-search nearest reference value."""
    lo, hi = 0, len(ref_ts)-1
    best_v, best_dt = None, max_dt
    while lo <= hi:
        mid = (lo+hi)//2
        dt = abs(ref_ts[mid][0] - t)
        if dt < best_dt:
            best_dt = dt; best_v = ref_ts[mid][1]
        if ref_ts[mid][0] < t: lo = mid+1
        else: hi = mid-1
    return best_v

def pair_nearest(cand_ts):
    """Return parallel (ref_V, cand_raw) lists via nearest-match."""
    rv, cv = [], []
    for t, raw in cand_ts:
        v = nearest_ref(t)
        if v is not None:
            rv.append(v); cv.append(raw)
    return rv, cv

def deltas(seq):
    return [seq[i+1]-seq[i] for i in range(len(seq)-1)]

# ---- Build candidates ------------------------------------------------
# For each BMS ID: single bytes + LE/BE uint16 pairs
# Return list of (label, [(t, raw_float)])

def build_candidates(id_, frames):
    if not frames: return []
    dlc = len(frames[0][1])
    cands = []
    # Single bytes
    for b in range(dlc):
        ts = [(t, float(d[b])) for t, d in frames if len(d) > b]
        cands.append((f'B{b}', ts))
    # 16-bit pairs
    for b in range(dlc-1):
        # LE uint16
        ts = [(t, float(struct.unpack_from('<H', d, b)[0])) for t, d in frames if len(d) > b+1]
        cands.append((f'B{b}-B{b+1} LE', ts))
        # BE uint16
        ts = [(t, float(struct.unpack_from('>H', d, b)[0])) for t, d in frames if len(d) > b+1]
        cands.append((f'B{b}-B{b+1} BE', ts))
    return cands

# ---- Three-pass scan -------------------------------------------------
THRESH_FULL   = 0.70
THRESH_WINDOW = 0.70
THRESH_DELTA  = 0.60

results = []   # (id_, label, r_full, r_win, r_delta, note)

for id_ in BMS_IDS:
    frames = bus_ts[id_]
    if len(frames) < MIN_SAMP: continue
    cands = build_candidates(id_, frames)
    for label, ts in cands:
        rv, cv = pair_nearest(ts)
        if len(rv) < MIN_SAMP: continue

        # Pass 1: full-log
        r_full = pearson(rv, cv)

        # Pass 2: windowed -- find max |r| over 60s windows
        t_start = ref_ts[0][0]
        t_end   = ref_ts[-1][0]
        r_win_best = None
        w = t_start
        while w + WINDOW_S <= t_end:
            w_end = w + WINDOW_S
            # Filter to this window
            rv_w = [rv[i] for i, (t, _) in enumerate(ts[:len(rv)]) if w <= t < w_end]
            cv_w = [cv[i] for i, (t, _) in enumerate(ts[:len(cv)]) if w <= t < w_end]
            # Rebuild properly
            rv_w2, cv_w2 = [], []
            for i, (t, raw) in enumerate(ts):
                if i >= len(rv): break
                if w <= t < w_end:
                    rv_w2.append(rv[i]); cv_w2.append(cv[i])
            r = pearson(rv_w2, cv_w2)
            if r is not None:
                if r_win_best is None or abs(r) > abs(r_win_best):
                    r_win_best = r
            w += WINDOW_S / 2   # 50% overlap

        # Pass 3: delta correlation
        # Need temporally-ordered paired sequence
        paired = sorted(zip([t for t,_ in ts], rv, cv), key=lambda x: x[0])
        if len(paired) >= MIN_SAMP + 1:
            _, r_seq, c_seq = zip(*paired)
            dr = deltas(list(r_seq))
            dc = deltas(list(c_seq))
            r_delta = pearson(dr, dc)
        else:
            r_delta = None

        # Decide if worth reporting
        r_full_abs   = abs(r_full)   if r_full   is not None else 0
        r_win_abs    = abs(r_win_best) if r_win_best is not None else 0
        r_delta_abs  = abs(r_delta)  if r_delta  is not None else 0

        if (r_full_abs >= THRESH_FULL or r_win_abs >= THRESH_WINDOW
                or r_delta_abs >= THRESH_DELTA):
            note = KNOWN.get((id_, label), '')
            results.append((id_, label,
                             r_full, r_win_best, r_delta, note))

# ---- Sort & output ---------------------------------------------------
results.sort(key=lambda x: -max(
    abs(x[2]) if x[2] is not None else 0,
    abs(x[3]) if x[3] is not None else 0,
    abs(x[4]) if x[4] is not None else 0))

lines = []
lines.append("BMS HV Voltage Correlation Scan")
lines.append(f"Log: vtruxevapdrivelog4part2.log  |  Ref: 0x18FFD6B3 B4-B5 (DCDC, V>{V_FILTER:.0f})")
lines.append(f"Thresholds: full={THRESH_FULL}, windowed={THRESH_WINDOW}, delta={THRESH_DELTA}")
lines.append(f"Reference samples: {len(ref_ts)}")
lines.append("")
lines.append(f"{'ID':<8} {'Bytes':<14} {'r_full':>8} {'r_win':>8} {'r_delta':>8}  Note")
lines.append("-" * 72)

def fmt(r): return f"{r:+.4f}" if r is not None else "    --  "

for id_, label, r_full, r_win, r_delta, note in results:
    flag = ""
    if note: flag = f"  [{note}]"
    lines.append(f"0x{id_:03X}    {label:<14} {fmt(r_full):>8} {fmt(r_win):>8} {fmt(r_delta):>8}{flag}")

lines.append("")
lines.append(f"Total candidates above threshold: {len(results)}")

output = "\n".join(lines)
print(output)
with open(OUT, 'w', encoding='ascii', errors='replace') as f:
    f.write(output)
print(f"\nSaved to: {OUT}")
