"""
Scan for BMS-side CCL source that drives 0x050.

0x050 CCL = (B1 & 0x03) << 8 | B0  drops from ~300 to ~0 at t=348.6-365.6s
in vtruxcurrentlimitingtest.log.

Applies three passes per the updated correlation methodology:
  Pass A -- binary step-change: mode in baseline vs limit window
  Pass B -- analog Pearson r (multi-window stable): CCL as reference
  Pass C -- delta correlation: frame-to-frame diffs vs CCL diffs

BMS-originated IDs to scan:
  0x370-0x375, 0x400, 0x410-0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507

Also scans VCU BMS cluster (0x596, 0x639-0x64B, 0x651) since VCU may relay
BMS limits, and extended IDs from BMS area.

For each candidate: also checks adjacent 16-bit LE and BE pairs.
"""

import os, sys, math, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                                   'vtruxcurrentlimitingtest.log'))

# Windows (seconds within the log)
T_REF_START, T_REF_END     = 100.0, 300.0   # baseline: unrestricted regen downhill
T_LIM_START, T_LIM_END     = 348.6, 365.6   # regen limit active (CCL near 0)
T_REC_START, T_REC_END     = 366.0, 500.0   # recovery window
T_ANAL_START, T_ANAL_END   = 280.0, 500.0   # full transition window for analog correlation
T_DELTA_START, T_DELTA_END = 340.0, 380.0   # tight window for delta correlation

# BMS-originated IDs to scan
BMS_IDS = set([
    0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
    0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x506, 0x507,
])
# VCU BMS cluster (may relay limits)
VCU_BMS_IDS = set([
    0x596, 0x639, 0x63A, 0x63B, 0x63C, 0x63D, 0x63E, 0x63F,
    0x640, 0x641, 0x642, 0x643, 0x644, 0x645, 0x646, 0x647, 0x648, 0x649, 0x64A, 0x64B,
    0x651,
])
SCAN_IDS = BMS_IDS | VCU_BMS_IDS

def decode_ccl(data):
    if len(data) < 2: return None
    return ((data[1] & 0x03) << 8) | data[0]

def pearson(xs, ys):
    n = len(xs)
    if n < 3: return None
    mx = sum(xs)/n; my = sum(ys)/n
    sxx = sum((x-mx)**2 for x in xs)
    syy = sum((y-my)**2 for y in ys)
    sxy = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    denom = math.sqrt(sxx*syy)
    if denom < 1e-9: return None
    return sxy/denom

def main():
    print(f"Loading {os.path.basename(LOG)} ...")
    frames = list(parse_file(LOG))
    print(f"  {len(frames)} frames loaded")

    # -- Identify PT bus (has 0x051 at >50 Hz) --
    bus_0051 = collections.Counter(f.bus for f in frames if f.arbitration_id == 0x051)
    pt_bus = bus_0051.most_common(1)[0][0] if bus_0051 else None
    print(f"  PT bus: {pt_bus}")

    # -- Build 0x050 CCL timeseries on PT bus --
    ccl_ts = []  # (t, ccl)
    for f in frames:
        if f.arbitration_id == 0x050 and f.bus == pt_bus:
            v = decode_ccl(f.data)
            if v is not None:
                ccl_ts.append((f.timestamp, v))
    print(f"  0x050 frames: {len(ccl_ts)}")

    # Interpolate CCL at an arbitrary timestamp
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

    # CCL stats in windows
    ccl_ref = [v for t,v in ccl_ts if T_REF_START <= t <= T_REF_END]
    ccl_lim = [v for t,v in ccl_ts if T_LIM_START <= t <= T_LIM_END]
    ccl_rec = [v for t,v in ccl_ts if T_REC_START <= t <= T_REC_END]
    print(f"  CCL ref window:   n={len(ccl_ref)}, mean={sum(ccl_ref)/max(1,len(ccl_ref)):.1f}")
    print(f"  CCL limit window: n={len(ccl_lim)}, mean={sum(ccl_lim)/max(1,len(ccl_lim)):.1f}")
    print(f"  CCL rec window:   n={len(ccl_rec)}, mean={sum(ccl_rec)/max(1,len(ccl_rec)):.1f}")

    # -- Collect per-ID per-byte data --
    # Structure: id -> byte -> list of (t, val)
    id_byte_data = collections.defaultdict(lambda: collections.defaultdict(list))

    for f in frames:
        if f.arbitration_id not in SCAN_IDS: continue
        if f.arbitration_id in VCU_BMS_IDS and f.bus != pt_bus: continue
        for bi, bval in enumerate(f.data):
            id_byte_data[f.arbitration_id][bi].append((f.timestamp, bval))

    print(f"  IDs found in scan set: {sorted(id_byte_data.keys())}")

    # -- Pass A: binary step-change --
    step_candidates = []
    for cid, byte_data in sorted(id_byte_data.items()):
        for bi, ts in sorted(byte_data.items()):
            ref_vals = [v for t,v in ts if T_REF_START <= t <= T_REF_END]
            lim_vals = [v for t,v in ts if T_LIM_START <= t <= T_LIM_END]
            rec_vals = [v for t,v in ts if T_REC_START <= t <= T_REC_END]
            if not ref_vals or not lim_vals: continue
            ref_mode = max(set(ref_vals), key=ref_vals.count)
            lim_mode = max(set(lim_vals), key=lim_vals.count)
            rec_mode = max(set(rec_vals), key=rec_vals.count) if rec_vals else None
            delta = abs(int(lim_mode) - int(ref_mode))
            if delta >= 2:  # any non-trivial step
                step_candidates.append((delta, cid, bi, ref_mode, lim_mode, rec_mode,
                                        len(set(ref_vals+lim_vals))))

    step_candidates.sort(key=lambda x: -x[0])

    print(f"\n--- Pass A: Binary step-change (baseline vs limit window) ---")
    print(f"  (threshold: |delta_mode| >= 2)")
    print(f"  {'ID':>8} {'B':>2}  {'ref_mode':>8} {'lim_mode':>8} {'rec_mode':>8}  {'delta':>5}  uniq")
    for delta, cid, bi, ref_m, lim_m, rec_m, nuniq in step_candidates[:40]:
        rec_str = str(rec_m) if rec_m is not None else '?'
        print(f"  {cid:#08x}  {bi:>2}  {ref_m:>8}  {lim_m:>8}  {rec_str:>8}  {delta:>5}  {nuniq}")

    # -- Pass B: analog Pearson r vs CCL (multi-window) --
    # Window list: ref, limit, recovery, and the full transition window
    windows = [
        ('ref',     T_REF_START,  T_REF_END),
        ('limit',   T_LIM_START,  T_LIM_END),
        ('rec',     T_REC_START,  T_REC_END),
        ('trans',   T_ANAL_START, T_ANAL_END),
    ]

    analog_candidates = []
    for cid, byte_data in sorted(id_byte_data.items()):
        for bi, ts in sorted(byte_data.items()):
            # Build paired (ccl, byte_val) for each window
            window_r = {}
            for wname, ws, we in windows:
                pairs = [(ccl_at(t), v) for t,v in ts if ws <= t <= we if ccl_at(t) is not None]
                if len(pairs) < 5: continue
                xs, ys = zip(*pairs)
                r = pearson(list(xs), list(ys))
                if r is not None:
                    window_r[wname] = r

            if not window_r: continue
            # Count windows with |r| >= 0.50
            high_r_wins = sum(1 for r in window_r.values() if abs(r) >= 0.50)
            if high_r_wins < 1: continue
            # Summary: best r across windows
            best_r = max(window_r.values(), key=abs)
            trans_r = window_r.get('trans', None)
            analog_candidates.append((high_r_wins, abs(best_r), cid, bi,
                                       window_r.get('ref'), window_r.get('limit'),
                                       window_r.get('rec'), trans_r))

    analog_candidates.sort(key=lambda x: (-x[0], -x[1]))

    print(f"\n--- Pass B: Analog Pearson r vs CCL (multi-window) ---")
    print(f"  (min |r|>=0.50 in at least 1 window)")
    print(f"  {'ID':>8} {'B':>2}  {'r_ref':>7} {'r_lim':>7} {'r_rec':>7} {'r_trans':>7}  n_hi")
    for n_hi, br, cid, bi, r_ref, r_lim, r_rec, r_trans in analog_candidates[:40]:
        def fmt(v): return f"{v:+.3f}" if v is not None else "  n/a "
        print(f"  {cid:#08x}  {bi:>2}  {fmt(r_ref)} {fmt(r_lim)} {fmt(r_rec)} {fmt(r_trans)}  {n_hi}")

    # -- Pass C: delta correlation --
    # Compute frame-to-frame CCL deltas in tight window around transition
    ccl_in_delta = [(t,v) for t,v in ccl_ts if T_DELTA_START <= t <= T_DELTA_END]
    ccl_deltas = [(ccl_in_delta[i+1][0], ccl_in_delta[i+1][1]-ccl_in_delta[i][1])
                  for i in range(len(ccl_in_delta)-1)]

    delta_candidates = []
    for cid, byte_data in sorted(id_byte_data.items()):
        for bi, ts in sorted(byte_data.items()):
            in_range = [(t,v) for t,v in ts if T_DELTA_START <= t <= T_DELTA_END]
            if len(in_range) < 5: continue
            # For each CCL delta, find the nearest byte delta
            byte_deltas_d = {}  # t -> byte_delta
            for i in range(len(in_range)-1):
                byte_deltas_d[in_range[i+1][0]] = in_range[i+1][1] - in_range[i][1]

            # Match CCL deltas to nearest byte deltas
            pairs = []
            for tccl, dccl in ccl_deltas:
                closest = min(byte_deltas_d.keys(), key=lambda x: abs(x-tccl), default=None)
                if closest is not None and abs(closest-tccl) < 1.0:
                    pairs.append((dccl, byte_deltas_d[closest]))

            if len(pairs) < 5: continue
            xs, ys = zip(*pairs)
            r = pearson(list(xs), list(ys))
            if r is not None and abs(r) >= 0.35:
                delta_candidates.append((r, cid, bi, len(pairs)))

    delta_candidates.sort(key=lambda x: -abs(x[0]))

    print(f"\n--- Pass C: Delta correlation (frame-to-frame diffs, t={T_DELTA_START}-{T_DELTA_END}s) ---")
    print(f"  (|r_delta| >= 0.35)")
    print(f"  {'ID':>8} {'B':>2}  {'r_delta':>8}  n_pairs")
    for r, cid, bi, np in delta_candidates[:30]:
        print(f"  {cid:#08x}  {bi:>2}  {r:+.4f}  {np}")

    # -- 16-bit pair scan for top Pass A + B candidates --
    # Collect unique (cid, bi) from top candidates
    top_ids_bytes = set()
    for delta, cid, bi, *_ in step_candidates[:20]:
        top_ids_bytes.add((cid, bi))
    for _, _, cid, bi, *_ in analog_candidates[:20]:
        top_ids_bytes.add((cid, bi))
    for _, cid, bi, _ in delta_candidates[:10]:
        top_ids_bytes.add((cid, bi))

    # For each byte, also check adjacent pair (bi, bi+1) as LE and BE uint16
    pair_candidates = []
    checked_pairs = set()
    for cid, bi in sorted(top_ids_bytes):
        byte_data = id_byte_data[cid]
        for b_lo, b_hi in [(bi, bi+1), (bi-1, bi)]:
            if (cid, b_lo, b_hi) in checked_pairs: continue
            if b_lo < 0: continue
            if b_lo not in byte_data or b_hi not in byte_data: continue
            checked_pairs.add((cid, b_lo, b_hi))
            # Align by timestamp (both bytes are in same frame)
            lo_d = dict(byte_data[b_lo]); hi_d = dict(byte_data[b_hi])
            shared_t = sorted(set(lo_d) & set(hi_d))
            if len(shared_t) < 5: continue
            for endian, decode in [('LE', lambda lo,hi: lo|(hi<<8)),
                                    ('BE', lambda lo,hi: (lo<<8)|hi)]:
                pairs_v = [(t, decode(lo_d[t], hi_d[t])) for t in shared_t]

                # Analog r vs CCL in transition window
                anal = [(ccl_at(t), v) for t,v in pairs_v
                        if T_ANAL_START <= t <= T_ANAL_END if ccl_at(t) is not None]
                if len(anal) < 5: continue
                xs, ys = zip(*anal)
                r = pearson(list(xs), list(ys))
                # Step change
                ref_v = [v for t,v in pairs_v if T_REF_START <= t <= T_REF_END]
                lim_v = [v for t,v in pairs_v if T_LIM_START <= t <= T_LIM_END]
                if not ref_v or not lim_v: continue
                ref_med = sorted(ref_v)[len(ref_v)//2]
                lim_med = sorted(lim_v)[len(lim_v)//2]
                delta16 = abs(int(lim_med) - int(ref_med))
                if r is not None and abs(r) >= 0.30 or delta16 >= 50:
                    pair_candidates.append((abs(r) if r else 0, delta16, cid, b_lo, b_hi,
                                            endian, ref_med, lim_med, r))

    pair_candidates.sort(key=lambda x: -(x[0]+x[1]/1000))

    print(f"\n--- 16-bit pair scan (adjacent bytes from top candidates) ---")
    print(f"  {'ID':>8} {'BLo':>3} {'BHi':>3} {'end':>4}  {'ref_med':>8} {'lim_med':>8} {'delta':>6}  {'r_trans':>8}")
    for absr, d16, cid, blo, bhi, end, rm, lm, r in pair_candidates[:20]:
        rs = f"{r:+.4f}" if r is not None else "  n/a "
        print(f"  {cid:#08x}  {blo:>3}  {bhi:>3}  {end:>4}  {rm:>8}  {lm:>8}  {d16:>6}  {rs}")

    print("\nDone.")

if __name__ == '__main__':
    main()
