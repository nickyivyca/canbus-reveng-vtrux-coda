"""
gen_overheat_corr_484.py  (v3 -- 9-bit reference + LE/BE uint16 pair scan)

Correlation scan against vtruxgeneratoroverheattest.log.
Reference: 0x484 9-bit = (B1[0]<<8)|B0 (carry-extended generator motor temp candidate).

Scans three candidate types per frame:
  B   -- individual byte (as before)
  LE  -- unsigned LE uint16: (d[bi+1]<<8)|d[bi]  for adjacent byte pairs
  BE  -- unsigned BE uint16: (d[bi]<<8)|d[bi+1]  for adjacent byte pairs

LE/BE pairs catch temperature signals encoded as 16-bit words where the per-byte
Pearson r collapses to near zero due to MSB stepping (known blind spot).

Memory strategy: two-pass streaming with online Pearson accumulators.
Pass 1 collects only the reference signal (~1 Hz, tiny).
Pass 2 accumulates per-candidate sums without storing any timeseries.

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/gen_overheat_corr_484.py
"""

import sys, math
from collections import defaultdict

sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG   = "projects/vtrux/logs/vtruxgeneratoroverheattest.log"
OUT   = "projects/vtrux/notes/artifacts/gen_overheat_corr_484.txt"

KNOWN_PT_IDS = {
    0x051, 0x052, 0x395,
    0x308, 0x400, 0x08C,
    0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x470, 0x471, 0x472, 0x479, 0x480, 0x481, 0x482,
    0x505, 0x506, 0x507, 0x55C,
    # 0x592, 0x594, 0x595 -- kept in to allow discovery
    0x596, 0x597, 0x598, 0x5A2,
    0x599, 0x5A0,
    0x600, 0x601, 0x617, 0x619,
    0x639, 0x63A, 0x63C, 0x63D, 0x63F,
    0x640, 0x644, 0x645, 0x646, 0x647,
    0x648, 0x649, 0x64A, 0x64B, 0x651,
    0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
    0x681, 0x6A0,
}

KNOWN_EXT_SRCS = {0xC0, 0x40, 0x80, 0xB3, 0x20}

REF_ID    = 0x484
REF_B0    = 0   # low byte
REF_B1    = 1   # carry bit byte -- 9-bit ref = (B1[0]<<8)|B0


def interp_at(ref_t, ref_v, t, ptr):
    """Return (interpolated_ref_value, advanced_ptr).
    ptr is a monotonically-advancing index -- works because log is time-ordered.
    """
    n = len(ref_t)
    # advance pointer to bracket t
    while ptr < n - 1 and ref_t[ptr + 1] <= t:
        ptr += 1
    if t <= ref_t[0]:
        return float(ref_v[0]), ptr
    if ptr >= n - 1:
        return float(ref_v[-1]), ptr
    t0, t1 = ref_t[ptr], ref_t[ptr + 1]
    v0, v1 = ref_v[ptr], ref_v[ptr + 1]
    frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    return v0 + frac * (v1 - v0), ptr


def pearson_from_sums(n, sx, sy, sxx, syy, sxy):
    """Pearson r from running sums -- numerically equivalent to two-pass formula."""
    if n < 20:
        return 0.0
    dx2 = n * sxx - sx * sx
    dy2 = n * syy - sy * sy
    if dx2 < 1e-9 or dy2 < 1e-9:
        return 0.0
    return (n * sxy - sx * sy) / math.sqrt(dx2 * dy2)


def main():
    # ------------------------------------------------------------------
    # Pass 1: identify PT bus and collect reference signal (tiny footprint)
    # ------------------------------------------------------------------
    print(f"Pass 1: collecting reference 0x{REF_ID:X} 9-bit (B1[0]<<8)|B0 from {LOG} ...")
    pt_bus = None
    ref_raw = []  # list of (bus, t, b0, b1)

    for frame in parse_file(LOG):
        aid = frame.arbitration_id
        if aid == 0x051 and pt_bus is None:
            pt_bus = frame.bus
        if aid == REF_ID and len(frame.data) > REF_B1:
            ref_raw.append((frame.bus, frame.timestamp,
                             frame.data[REF_B0], frame.data[REF_B1]))

    print(f"  PT bus = {pt_bus}")
    if pt_bus is None:
        sys.exit("ERROR: PT bus not identified (0x051 not seen)")

    ref_samples = [(t, ((b1 & 0x01) << 8) | b0)
                   for bus, t, b0, b1 in ref_raw if bus == pt_bus]
    del ref_raw

    if len(ref_samples) < 20:
        sys.exit(f"ERROR: 0x{REF_ID:X} 9-bit has only {len(ref_samples)} samples on PT bus")

    ref_t = [t for t, _ in ref_samples]
    ref_v = [v for _, v in ref_samples]
    print(f"  Reference: {len(ref_samples)} samples, range {min(ref_v)}-{max(ref_v)}, "
          f"t={ref_t[0]:.1f}-{ref_t[-1]:.1f}s")

    # ------------------------------------------------------------------
    # Pass 2: streaming correlation via online Pearson accumulators.
    # No timeseries stored -- only 10 floats + a set per candidate.
    # ------------------------------------------------------------------
    print("Pass 2: streaming correlation ...")

    # acc[key] holds per-candidate running statistics
    acc = {}
    ref_ptr = 0

    for frame in parse_file(LOG):
        if frame.bus != pt_bus:
            continue
        aid = frame.arbitration_id
        if aid == REF_ID:
            continue
        is_ext = bool(aid & 0x80000000)
        if not is_ext and aid in KNOWN_PT_IDS:
            continue
        if is_ext and (aid & 0xFF) in KNOWN_EXT_SRCS:
            continue

        t = frame.timestamp
        rx, ref_ptr = interp_at(ref_t, ref_v, t, ref_ptr)
        d = frame.data
        nb = len(d)

        # Build candidate list: per-byte + LE uint16 + BE uint16 pairs
        candidates = []
        for bi in range(nb):
            candidates.append((aid, bi, 'B', float(d[bi])))
        for bi in range(nb - 1):
            le_val = float(d[bi] | (d[bi + 1] << 8))
            be_val = float((d[bi] << 8) | d[bi + 1])
            candidates.append((aid, bi, 'LE', le_val))
            candidates.append((aid, bi, 'BE', be_val))

        for aid_k, bi, kind, cv in candidates:
            key = (aid_k, bi, kind)
            if key not in acc:
                acc[key] = {
                    'n': 0,
                    'sx': 0.0, 'sy': 0.0,
                    'sxx': 0.0, 'syy': 0.0, 'sxy': 0.0,
                    'min_v': cv, 'max_v': cv,
                    'uniq': set(),
                    'sum_ad': 0.0, 'n_diff': 0,
                    'prev': None,
                    'first_t': t, 'last_t': t,
                }
            a = acc[key]
            a['n']    += 1
            a['sx']   += rx
            a['sy']   += cv
            a['sxx']  += rx * rx
            a['syy']  += cv * cv
            a['sxy']  += rx * cv
            if cv < a['min_v']:
                a['min_v'] = cv
            if cv > a['max_v']:
                a['max_v'] = cv
            a['uniq'].add(cv)
            if a['prev'] is not None:
                a['sum_ad'] += abs(cv - a['prev'])
                a['n_diff'] += 1
            a['prev']   = cv
            a['last_t'] = t

    print(f"  Candidate keys accumulated: {len(acc)}")

    # ------------------------------------------------------------------
    # Filter, score, and report
    # ------------------------------------------------------------------
    results = []
    for (aid, bi, kind), a in acc.items():
        n    = a['n']
        uniq = len(a['uniq'])
        rng  = a['max_v'] - a['min_v']
        mac  = a['sum_ad'] / a['n_diff'] if a['n_diff'] > 0 else 0.0
        # Per-type filters: 16-bit pairs have wider natural range and MAC
        if kind == 'B':
            if n < 20 or uniq < 4 or rng < 3 or mac > 15:
                continue
        else:  # LE or BE uint16
            if n < 20 or uniq < 8 or rng < 20 or mac > 4000:
                continue
        r  = pearson_from_sums(n, a['sx'], a['sy'], a['sxx'], a['syy'], a['sxy'])
        dt = a['last_t'] - a['first_t']
        hz = n / dt if dt > 0 else 0.0
        results.append({
            'id': aid, 'byte': bi, 'kind': kind, 'r': r, 'abs_r': abs(r),
            'unique': uniq, 'range': rng,
            'min': a['min_v'], 'max': a['max_v'],
            'mac': mac, 'n': n, 'hz': hz,
        })

    results.sort(key=lambda x: -x['abs_r'])

    header = [
        "Vtrux PT Bus -- Generator Overheat Test Correlation Scan (v3)",
        "Reference: 0x484 9-bit = (B1[0]<<8)|B0",
        f"Log: {LOG}",
        "Byte filters:   MAC<=15, uniq>=4, range>=3, n>=20",
        "LE/BE filters:  MAC<=4000, uniq>=8, range>=20, n>=20",
        "0x594/0x595 kept in (not in skip list)",
        "",
        f"{'Rank':>4}  {'ID':>12}  {'B':>2}  {'Kind':>4}  {'r':>7}  {'MAC':>7}  "
        f"{'Uniq':>4}  {'Range':>14}  {'n':>6}  {'Hz':>5}",
        "-" * 90,
    ]

    rows = []
    for rank, res in enumerate(results[:60], 1):
        id_str = f"0x{res['id']:08X}" if res['id'] > 0x7FF else f"0x{res['id']:03X}"
        rows.append(
            f"{rank:>4}  {id_str:>12}  {res['byte']:>2}  {res['kind']:>4}  "
            f"{res['r']:>+7.3f}  {res['mac']:>7.1f}  {res['unique']:>4}  "
            f"{res['min']:>6.0f}-{res['max']:>6.0f}  {res['n']:>6}  {res['hz']:>5.1f}"
        )

    footer = ["", f"Total candidates: {len(results)}",
              f"  Byte: {sum(1 for r in results if r['kind']=='B')}",
              f"  LE16: {sum(1 for r in results if r['kind']=='LE')}",
              f"  BE16: {sum(1 for r in results if r['kind']=='BE')}"]
    output = "\n".join(header + rows + footer)
    print("\n" + output)
    with open(OUT, 'w', encoding='ascii') as f:
        f.write(output)
    print(f"\nWritten to {OUT}")


if __name__ == '__main__':
    main()
