"""
scan_ccl_charge.py

Scan BMS-originated bytes/bits against the CCL ramp-down in another_M0
charge session (SoC 74->99%, CCL 286->10).

Why this log is better: the CCL ramp takes ~3000s (50 min), is smooth and
monotone, and is not confounded by instant pack-condition changes. A BMS byte
that truly drives CCL should track this ramp; temperature drift, voltage sag,
and single-event correlates will not.

Passes:
  A -- Analog Pearson r vs CCL (BMS bytes, over the ramp window)
  B -- 16-bit LE/BE pair scan for top Pass A candidates
  C -- Bit scan: bits that transition once during the ramp window (CCL value
       at each transition reported -- a threshold-crossing signal will always
       transition at the same CCL value)

BMS-originated IDs: 0x370-0x375, 0x400, 0x410-0x412, 0x420, 0x430, 0x440,
                    0x460, 0x506, 0x507

Only reads chunks up to T_COLLECT_END seconds (well past the ramp) for speed.
"""

import os, sys, glob, math, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       '..', '..', 'logs',
                                       'after-battery-swap-charges'))
SESSION_GLOB = os.path.join(LOG_DIR, 'another_M0_T*.log')

BMS_IDS = set([
    0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
    0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x506, 0x507,
])

# Only collect data up to this cumulative time (saves reading 55 chunks)
# CCL hits floor at ~t=3600s; collect to t=4500s for safety
T_COLLECT_END = 4500.0

# Ramp window for correlation (auto-detected below, these are fallbacks)
T_RAMP_START_DEFAULT = 400.0
T_RAMP_END_DEFAULT   = 3700.0

# Analog correlation thresholds
MIN_R = 0.60
# Bit scan
MAX_BIT_TRANS = 8   # max transitions in window for a "digital" candidate

def pearson(xs, ys):
    n = len(xs)
    if n < 10: return None
    mx = sum(xs)/n; my = sum(ys)/n
    sxx = sum((x-mx)**2 for x in xs)
    syy = sum((y-my)**2 for y in ys)
    sxy = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    denom = math.sqrt(sxx*syy)
    if denom < 1e-9: return None
    return sxy/denom

# ---------------------------------------------------------------------------
# Find and sort chunk files
# ---------------------------------------------------------------------------
files = sorted(glob.glob(SESSION_GLOB))
print(f"Found {len(files)} chunks in another_M0")
if not files:
    raise SystemExit("No files found -- check LOG_DIR")

# ---------------------------------------------------------------------------
# Pass 0: identify PT bus from first chunk
# ---------------------------------------------------------------------------
print("Identifying PT bus ...")
bus_051 = {}
for frame in parse_file(files[0]):
    if frame.arbitration_id == 0x051:
        bus_051[frame.bus] = bus_051.get(frame.bus, 0) + 1
PT_BUS = max(bus_051, key=bus_051.get) if bus_051 else None
print(f"  PT bus = {PT_BUS}")

# ---------------------------------------------------------------------------
# Load chunks up to T_COLLECT_END
# ---------------------------------------------------------------------------
print(f"Loading chunks (collecting up to t={T_COLLECT_END}s) ...")
ccl_ts  = []   # (t, raw_ccl)
bms_data = collections.defaultdict(lambda: collections.defaultdict(list))
# bms_data[cid][bi] = [(t, val), ...]

chunk_offset = 0.0
chunks_loaded = 0
for fpath in files:
    if chunk_offset > T_COLLECT_END:
        break
    try:
        frames = list(parse_file(fpath))
    except Exception as e:
        print(f"  {os.path.basename(fpath)}: parse error -- {e}")
        continue
    if not frames:
        continue

    last_ts = frames[-1].timestamp
    for f in frames:
        t   = chunk_offset + f.timestamp
        aid = f.arbitration_id
        d   = f.data
        if t > T_COLLECT_END:
            break

        if aid == 0x050 and f.bus == PT_BUS and len(d) >= 2:
            ccl_ts.append((t, (d[1] & 0x03) << 8 | d[0]))

        if aid in BMS_IDS and f.bus == PT_BUS:
            for bi, bv in enumerate(d):
                bms_data[aid][bi].append((t, bv))

    chunk_offset += last_ts
    chunks_loaded += 1

print(f"  Loaded {chunks_loaded} chunks  CCL frames: {len(ccl_ts)}")
print(f"  BMS IDs present: {[hex(x) for x in sorted(bms_data.keys())]}")

# ---------------------------------------------------------------------------
# Auto-detect CCL ramp window
#   RAMP_START: first time CCL drops below 290 and stays below for >120s
#   RAMP_END:   first time CCL drops below 15
# ---------------------------------------------------------------------------
def first_sustained_below(ts_vals, threshold, hold_sec):
    below_since = None
    for t, v in ts_vals:
        if v < threshold:
            if below_since is None:
                below_since = t
            elif t - below_since >= hold_sec:
                return below_since
        else:
            below_since = None
    return None

T_RAMP_START = first_sustained_below(ccl_ts, 290, 120.0) or T_RAMP_START_DEFAULT
T_RAMP_END   = first_sustained_below(ccl_ts, 15,    60.0) or T_RAMP_END_DEFAULT
print(f"\nAuto-detected ramp window: t={T_RAMP_START:.0f}s -- t={T_RAMP_END:.0f}s")

# CCL stats in ramp window
ccl_ramp = [(t, v) for t, v in ccl_ts if T_RAMP_START <= t <= T_RAMP_END]
if ccl_ramp:
    vals = [v for _, v in ccl_ramp]
    print(f"  CCL in ramp: n={len(ccl_ramp)}, min={min(vals)}, max={max(vals)}, "
          f"mean={sum(vals)/len(vals):.1f}")

# CCL interpolator
def ccl_at(t):
    if not ccl_ts: return None
    lo, hi = 0, len(ccl_ts)-1
    if t <= ccl_ts[lo][0]: return ccl_ts[lo][1]
    if t >= ccl_ts[hi][0]: return ccl_ts[hi][1]
    while hi - lo > 1:
        mid = (lo+hi)//2
        if ccl_ts[mid][0] <= t: lo = mid
        else: hi = mid
    t0,v0 = ccl_ts[lo]; t1,v1 = ccl_ts[hi]
    frac = (t-t0)/(t1-t0) if t1>t0 else 0
    return v0 + frac*(v1-v0)

# ---------------------------------------------------------------------------
# Pass A: Analog Pearson r vs CCL over ramp window
# ---------------------------------------------------------------------------
print(f"\n--- Pass A: Pearson r (BMS bytes vs CCL, ramp window) ---")
print(f"  (min |r| >= {MIN_R})")
print(f"  {'ID':>8} {'B':>2}   {'r':>7}  {'n':>6}  {'uniq':>5}  note")

analog_cands = []
for cid in sorted(bms_data.keys()):
    for bi in sorted(bms_data[cid].keys()):
        ts_vals = bms_data[cid][bi]
        pairs = [(ccl_at(t), v) for t,v in ts_vals
                 if T_RAMP_START <= t <= T_RAMP_END if ccl_at(t) is not None]
        if len(pairs) < 20:
            continue
        xs, ys = zip(*pairs)
        r = pearson(list(xs), list(ys))
        if r is None or abs(r) < MIN_R:
            continue
        uniq = len(set(int(v) for v in ys))
        analog_cands.append((r, cid, bi, len(pairs), uniq))

analog_cands.sort(key=lambda x: -abs(x[0]))
for r, cid, bi, n, uniq in analog_cands[:40]:
    note = ''
    if uniq <= 5: note = 'FEW-UNIQUE (likely discrete/stepped)'
    elif uniq > 200: note = 'HIGH-ENTROPY (analog/counter)'
    print(f"  {cid:#08x}  {bi:>2}  {r:>+7.3f}  {n:>6}  {uniq:>5}  {note}")

# ---------------------------------------------------------------------------
# Pass B: 16-bit LE/BE pair scan for top Pass A candidates
# ---------------------------------------------------------------------------
top_ids_bytes = set((cid, bi) for _, cid, bi, _, _ in analog_cands[:20])

print(f"\n--- Pass B: 16-bit LE/BE pair scan (top Pass A candidates) ---")
print(f"  {'ID':>8} {'BLo':>3} {'BHi':>3}  end  {'r':>7}  {'n':>6}  note")

pair_cands = []
checked = set()
for cid, bi in sorted(top_ids_bytes):
    for b_lo, b_hi in [(bi, bi+1), (bi-1, bi)]:
        if (cid, b_lo, b_hi) in checked or b_lo < 0: continue
        if b_lo not in bms_data[cid] or b_hi not in bms_data[cid]: continue
        checked.add((cid, b_lo, b_hi))
        lo_d = dict(bms_data[cid][b_lo])
        hi_d = dict(bms_data[cid][b_hi])
        shared = sorted(set(lo_d) & set(hi_d))
        shared = [t for t in shared if T_RAMP_START <= t <= T_RAMP_END]
        if len(shared) < 20: continue
        for endian, decode in [('LE', lambda lo,hi: lo|(hi<<8)),
                                ('BE', lambda lo,hi: (lo<<8)|hi)]:
            pairs = [(ccl_at(t), decode(lo_d[t], hi_d[t])) for t in shared
                     if ccl_at(t) is not None]
            if len(pairs) < 20: continue
            xs, ys = zip(*pairs)
            r = pearson(list(xs), list(ys))
            if r is None or abs(r) < MIN_R: continue
            uniq = len(set(int(y) for y in ys))
            pair_cands.append((r, cid, b_lo, b_hi, endian, len(pairs), uniq))

pair_cands.sort(key=lambda x: -abs(x[0]))
for r, cid, blo, bhi, end, n, uniq in pair_cands[:20]:
    note = 'FEW-UNIQUE' if uniq <= 10 else ('HIGH-ENTROPY' if uniq > 500 else '')
    print(f"  {cid:#08x}  {blo:>3}  {bhi:>3}  {end:>3}  {r:>+7.3f}  {n:>6}  {uniq:>5}  {note}")

# ---------------------------------------------------------------------------
# Pass C: Bit transition scan during ramp window
# ---------------------------------------------------------------------------
print(f"\n--- Pass C: Bit scan (transitions during ramp window, n_trans <= {MAX_BIT_TRANS}) ---")
print(f"  {'ID':>8} {'B':>2} {'bit':>3}  {'n_trans':>7}  transitions (with CCL value at each)")

bit_cands = []
for cid in sorted(bms_data.keys()):
    for bi in sorted(bms_data[cid].keys()):
        ts_vals = bms_data[cid][bi]
        if len(ts_vals) < 4: continue

        # Split: pre-ramp, in-ramp, post-ramp
        pre  = [(t,v) for t,v in ts_vals if t < T_RAMP_START]
        ramp = [(t,v) for t,v in ts_vals if T_RAMP_START <= t <= T_RAMP_END]
        post = [(t,v) for t,v in ts_vals if t > T_RAMP_END]

        if not ramp: continue

        for bit in range(8):
            # State at ramp start (last pre-ramp frame, or first ramp frame)
            pre_state  = ((pre[-1][1]  if pre  else ramp[0][1])  >> bit) & 1
            post_state = ((post[0][1]  if post else ramp[-1][1]) >> bit) & 1

            # Transitions within ramp
            transitions = []
            prev = (ramp[0][1] >> bit) & 1
            for t, v in ramp[1:]:
                s = (v >> bit) & 1
                if s != prev:
                    ccl_val = ccl_at(t)
                    transitions.append((t, prev, s, ccl_val))
                    prev = s
            n = len(transitions)
            if n == 0 or n > MAX_BIT_TRANS: continue

            # Only report if bit actually changes from pre to post (not just noise)
            if n <= 2 and pre_state == post_state and n == 2:
                # Flipped and flipped back -- transient, skip unless CCL values are interesting
                pass

            bit_cands.append((n, cid, bi, bit, transitions, pre_state, post_state))

bit_cands.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
for n, cid, bi, bit, transitions, pre_s, post_s in bit_cands[:50]:
    trans_strs = []
    for t, fr, to, cv in transitions:
        cv_s = f"CCL={cv:.0f}" if cv is not None else "CCL=?"
        trans_strs.append(f"t={t:.0f}s {fr}->{to} ({cv_s})")
    change = f"pre={pre_s} post={post_s}"
    print(f"  {cid:#08x}  {bi:>2}  {bit:>3}  {n:>7}  {change}  " + ", ".join(trans_strs))

print("\nDone.")
