"""
gen_overheat_corr_595b2.py

Windowed correlation scan against vtruxgeneratoroverheattest.log.
Reference: 0x595 B2 (PE glycol loop temp candidate).
Window: t=1700-2300s only (pump-off overheat phase + recovery).

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/gen_overheat_corr_595b2.py
"""

import sys, math
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG   = "projects/vtrux/logs/vtruxgeneratoroverheattest.log"
OUT   = "projects/vtrux/notes/artifacts/gen_overheat_corr_595b2.txt"
T_MIN = 1700.0
T_MAX = 2300.0

KNOWN_PT_IDS = {
    0x051, 0x052, 0x395,
    0x308, 0x400, 0x08C,
    0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x470, 0x471, 0x472, 0x479, 0x480, 0x481, 0x482,
    0x505, 0x506, 0x507, 0x55C,
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

REF_ID   = 0x595
REF_BYTE = 2


def interp_at(ref_t, ref_v, t, ptr):
    n = len(ref_t)
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
    if n < 20:
        return 0.0
    dx2 = n * sxx - sx * sx
    dy2 = n * syy - sy * sy
    if dx2 < 1e-9 or dy2 < 1e-9:
        return 0.0
    return (n * sxy - sx * sy) / math.sqrt(dx2 * dy2)


def main():
    # Pass 1: find PT bus and collect reference
    print(f"Pass 1: collecting reference 0x{REF_ID:X} B{REF_BYTE} (t={T_MIN}-{T_MAX}s) ...")
    pt_bus = None
    ref_raw = []
    for frame in parse_file(LOG):
        aid = frame.arbitration_id
        if aid == 0x051 and pt_bus is None:
            pt_bus = frame.bus
        if aid == REF_ID and len(frame.data) > REF_BYTE:
            t = frame.timestamp
            if T_MIN <= t <= T_MAX:
                ref_raw.append((frame.bus, t, frame.data[REF_BYTE]))

    print(f"  PT bus = {pt_bus}")
    if pt_bus is None:
        sys.exit("ERROR: PT bus not identified")

    ref_samples = [(t, v) for bus, t, v in ref_raw if bus == pt_bus]
    del ref_raw

    if len(ref_samples) < 20:
        sys.exit(f"ERROR: 0x{REF_ID:X} B{REF_BYTE} has only {len(ref_samples)} samples in window")

    ref_t = [t for t, _ in ref_samples]
    ref_v = [v for _, v in ref_samples]
    print(f"  Reference: {len(ref_samples)} samples, range {min(ref_v)}-{max(ref_v)}, "
          f"t={ref_t[0]:.1f}-{ref_t[-1]:.1f}s")

    # Pass 2: streaming correlation within window
    print("Pass 2: streaming correlation ...")
    acc = {}
    ref_ptr = 0

    for frame in parse_file(LOG):
        t = frame.timestamp
        if t < T_MIN or t > T_MAX:
            continue
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

        rx, ref_ptr = interp_at(ref_t, ref_v, t, ref_ptr)

        for bi, bv in enumerate(frame.data):
            key = (aid, bi)
            if key not in acc:
                acc[key] = {
                    'n': 0, 'sx': 0.0, 'sy': 0.0,
                    'sxx': 0.0, 'syy': 0.0, 'sxy': 0.0,
                    'min_v': bv, 'max_v': bv,
                    'uniq': set(), 'sum_ad': 0.0, 'n_diff': 0,
                    'prev': None, 'first_t': t, 'last_t': t,
                }
            a = acc[key]
            a['n']    += 1
            a['sx']   += rx
            a['sy']   += bv
            a['sxx']  += rx * rx
            a['syy']  += bv * bv
            a['sxy']  += rx * bv
            if bv < a['min_v']: a['min_v'] = bv
            if bv > a['max_v']: a['max_v'] = bv
            a['uniq'].add(bv)
            if a['prev'] is not None:
                a['sum_ad'] += abs(bv - a['prev'])
                a['n_diff'] += 1
            a['prev']   = bv
            a['last_t'] = t

    print(f"  Candidates accumulated: {len(acc)}")

    results = []
    for (aid, bi), a in acc.items():
        n    = a['n']
        uniq = len(a['uniq'])
        rng  = a['max_v'] - a['min_v']
        mac  = a['sum_ad'] / a['n_diff'] if a['n_diff'] > 0 else 0.0
        if n < 20 or uniq < 4 or rng < 3 or mac > 15:
            continue
        r  = pearson_from_sums(n, a['sx'], a['sy'], a['sxx'], a['syy'], a['sxy'])
        dt = a['last_t'] - a['first_t']
        hz = n / dt if dt > 0 else 0.0
        results.append({
            'id': aid, 'byte': bi, 'r': r, 'abs_r': abs(r),
            'unique': uniq, 'range': rng,
            'min': a['min_v'], 'max': a['max_v'],
            'mac': mac, 'n': n, 'hz': hz,
        })

    results.sort(key=lambda x: -x['abs_r'])

    header = [
        "Vtrux PT Bus -- Generator Overheat Test Windowed Correlation Scan",
        f"Reference: 0x{REF_ID:X} B{REF_BYTE} (0x595 B2, PE glycol loop temp candidate)",
        f"Log: {LOG}",
        f"Window: t={T_MIN:.0f}-{T_MAX:.0f}s",
        "Filters: mean-abs-change <= 15, unique >= 4, range >= 3, n >= 20",
        "",
        f"{'Rank':>4}  {'ID':>12}  {'B':>2}  {'r':>7}  {'MAC':>5}  "
        f"{'Uniq':>4}  {'Range':>10}  {'n':>6}  {'Hz':>5}",
        "-" * 80,
    ]

    rows = []
    for rank, res in enumerate(results[:60], 1):
        id_str = f"0x{res['id']:08X}" if res['id'] > 0x7FF else f"0x{res['id']:03X}"
        rows.append(
            f"{rank:>4}  {id_str:>12}  {res['byte']:>2}  "
            f"{res['r']:>+7.3f}  {res['mac']:>5.2f}  {res['unique']:>4}  "
            f"{res['min']:>4}-{res['max']:>4}  {res['n']:>6}  {res['hz']:>5.1f}"
        )

    footer = ["", f"Total candidates: {len(results)}"]
    output = "\n".join(header + rows + footer)
    print("\n" + output)
    with open(OUT, 'w', encoding='ascii') as f:
        f.write(output)
    print(f"\nWritten to {OUT}")


if __name__ == '__main__':
    main()
