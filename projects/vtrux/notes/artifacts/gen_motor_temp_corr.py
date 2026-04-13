"""
gen_motor_temp_corr.py

Correlation scan to find generator motor temperature signal.

Reference: 0x483 B0 (unknown thermal source, not PE coolant loop, slowly rising
during the drivetrain overheat test). Using t >= 800s only to skip the byte
overflow/wrap artifact observed in the early portion of the log.

Log:  vtruxdrivetrainoverheattest.log
Bus:  PT bus (Bus 3, identified by 0x051)
Output: gen_motor_temp_corr.txt

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/gen_motor_temp_corr.py
"""

import sys, math
from collections import defaultdict

sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG    = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
OUT    = "projects/vtrux/notes/artifacts/gen_motor_temp_corr.txt"
T_MIN  = 800.0   # skip byte overflow in 0x483 B0 early portion

# Already attributed -- skip these to reduce noise
KNOWN_PT_IDS = {
    0x051, 0x052, 0x395,
    0x308, 0x400, 0x08C,
    0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x470, 0x471, 0x472, 0x479, 0x480, 0x481, 0x482,
    0x505, 0x506, 0x507, 0x55C,
    0x592, 0x594, 0x596, 0x597, 0x598, 0x5A2,
    0x599, 0x5A0,
    0x600, 0x601, 0x617, 0x619,
    0x639, 0x63A, 0x63C, 0x63D, 0x63F,
    0x640, 0x644, 0x645, 0x646, 0x647,
    0x648, 0x649, 0x64A, 0x64B, 0x651,
    0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
    0x681, 0x6A0,
}

# Skip known extended source addresses
KNOWN_EXT_SRCS = {0xC0, 0x40, 0x80, 0xB3, 0x20}  # charger, DCDC, PE pump

REF_ID   = 0x483
REF_BYTE = 0


def interp(ref_times, ref_vals, query_times):
    out = []
    j = 0
    n = len(ref_times)
    for t in query_times:
        while j < n - 1 and ref_times[j + 1] < t:
            j += 1
        if j >= n - 1:
            out.append(ref_vals[-1])
        elif t <= ref_times[0]:
            out.append(ref_vals[0])
        else:
            t0, t1 = ref_times[j], ref_times[j + 1]
            v0, v1 = ref_vals[j], ref_vals[j + 1]
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            out.append(v0 + frac * (v1 - v0))
    return out


def pearson_r(xs, ys):
    n = len(xs)
    if n < 20:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx < 1e-9 or dy < 1e-9:
        return 0.0
    return num / (dx * dy)


def median_abs_change(vals):
    diffs = sorted(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1))
    return diffs[len(diffs) // 2] if diffs else 0.0


def main():
    print(f"Parsing {LOG} (t >= {T_MIN}s only, PT bus)...")
    ts_all = defaultdict(lambda: defaultdict(list))  # id -> byte -> [(t, v)]
    ref_ts = []

    pt_bus = None
    frame_count = 0

    for frame in parse_file(LOG):
        t = frame.timestamp
        if t < T_MIN:
            continue

        # Identify PT bus on first qualifying frame
        if pt_bus is None:
            # Quick scan approach: just collect until we can identify
            pass

        bus = frame.bus
        aid = frame.arbitration_id

        # Identify PT bus by 0x051 presence (collected across all buses first pass)
        if aid == 0x051:
            pt_bus = bus

        ts_all[(bus, aid)][0]  # touch -- we'll filter by bus below after scan

        for bi, bv in enumerate(frame.data):
            ts_all[(bus, aid)][bi].append((t, bv))

        frame_count += 1

    print(f"  {frame_count} frames loaded (t >= {T_MIN}s)")
    print(f"  PT bus = {pt_bus}")

    if pt_bus is None:
        sys.exit("ERROR: PT bus not identified")

    # Extract reference signal 0x483 B0 on PT bus
    ref_samples = ts_all[(pt_bus, REF_ID)].get(REF_BYTE, [])
    if len(ref_samples) < 20:
        sys.exit(f"ERROR: reference 0x{REF_ID:X} B{REF_BYTE} has only {len(ref_samples)} samples")

    ref_t = [t for t, _ in ref_samples]
    ref_v = [v for _, v in ref_samples]
    print(f"  Reference 0x{REF_ID:X} B{REF_BYTE}: {len(ref_samples)} samples, "
          f"range {min(ref_v)}-{max(ref_v)}, mean {sum(ref_v)/len(ref_v):.1f}")

    # Correlate all PT bus candidates
    results = []
    for (bus, aid), byte_dict in ts_all.items():
        if bus != pt_bus:
            continue

        is_ext = bool(aid & 0x80000000)
        if not is_ext and aid in KNOWN_PT_IDS:
            continue
        if is_ext and (aid & 0xFF) in KNOWN_EXT_SRCS:
            continue
        if aid == REF_ID:  # skip self
            continue

        for bi, samples in byte_dict.items():
            if len(samples) < 20:
                continue
            times = [t for t, _ in samples]
            vals  = [v for _, v in samples]
            uniq  = len(set(vals))
            rng   = max(vals) - min(vals)

            # Skip constants and counters
            if uniq < 4 or rng < 3:
                continue
            mac = median_abs_change(vals)
            if mac > 15:   # likely a counter or fast-varying signal
                continue

            # Interpolate reference to candidate timestamps
            ref_interp = interp(ref_t, ref_v, times)
            r = pearson_r(ref_interp, vals)

            results.append({
                'id': aid, 'byte': bi,
                'r': r, 'abs_r': abs(r),
                'unique': uniq, 'range': rng,
                'min': min(vals), 'max': max(vals),
                'mac': mac, 'n': len(samples),
                'hz': len(samples) / (times[-1] - times[0]) if times[-1] > times[0] else 0,
            })

    results.sort(key=lambda x: -x['abs_r'])

    header = [
        f"Vtrux PT Bus -- Generator Motor Temperature Correlation Scan",
        f"Reference: 0x{REF_ID:X} B{REF_BYTE} (0x483 B0, unknown thermal, not PE coolant loop)",
        f"Window: t >= {T_MIN}s (skip early byte overflow)",
        f"Log: {LOG}",
        f"Filters: MAC <= 15, unique >= 4, range >= 3, n >= 20",
        f"Known IDs skipped: {len(KNOWN_PT_IDS)} standard + known ext src addrs",
        "",
        f"{'Rank':>4}  {'ID':>12}  {'B':>2}  {'r':>7}  {'MAC':>5}  "
        f"{'Uniq':>4}  {'Range':>10}  {'n':>6}  {'Hz':>5}",
        "-" * 80,
    ]

    rows = []
    for rank, res in enumerate(results[:50], 1):
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
