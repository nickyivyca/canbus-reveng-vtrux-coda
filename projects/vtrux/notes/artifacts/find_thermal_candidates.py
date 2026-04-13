"""
find_thermal_candidates.py

Phase 3A -- Thermal candidate discovery for Vtrux PT bus.

Loads vtruxevapdrivelog4.log (PT bus) and correlates every unattributed (ID, byte)
pair against four reference signals:
  1. Synthetic gen-on ramp (t=90-1100s rise, exponential decay) -- broad proxy
  2. Gen torque magnitude |0x051 B1-B2 LE_uint16 - 32768| -- targets gen inverter
  3. Drivetrain torque magnitude |0x5A2 B4-B5 LE_uint16 - 32768| -- targets traction inverter
  4. Negated pump speed -(0x18FF0320 B5) -- validator; real thermals cool with pump

Ranking: max(|r|) across all four references.
Output: evap4_thermal_candidates.txt -- top 40 with all four r values shown.

Usage: run from project root
    py -3.12 projects/vtrux/notes/artifacts/find_thermal_candidates.py
"""

import sys, json, math
from collections import defaultdict

sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG    = "projects/vtrux/logs/vtruxevapdrivelog4.log"
SURVEY = "projects/vtrux/notes/artifacts/evaplog4_p1_survey.json"
OUT    = "projects/vtrux/notes/artifacts/evap4_thermal_candidates.txt"

# Known PT bus standard IDs -- fully attributed, skip
KNOWN_PT_IDS = {
    0x051, 0x052, 0x395,
    0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x470, 0x471, 0x472, 0x482,
    0x506, 0x507,
    0x592, 0x596, 0x597, 0x598, 0x5A2,
    0x600, 0x63C, 0x639, 0x63A, 0x63D, 0x63F,
    0x640, 0x644, 0x645, 0x646, 0x647,
    0x648, 0x649, 0x64A, 0x64B, 0x651,
    0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
    0x400,
}

# Known extended ID source addresses -- skip
KNOWN_EXT_SRCS = {0xC0, 0x40, 0x80, 0xB3}  # Bel charger variants, Bel DCDC

# Generator on/off in evap4 part 1
GEN_ON_T  = 90.0
GEN_OFF_T = 1100.0


def interp(ref_times, ref_vals, query_times):
    """Linear interpolation of ref_vals at query_times (assumes ref_times sorted)."""
    out = []
    j = 0
    n = len(ref_times)
    for t in query_times:
        # advance j until ref_times[j] >= t
        while j < n - 1 and ref_times[j + 1] < t:
            j += 1
        if j >= n - 1:
            out.append(ref_vals[-1])
        elif j == 0 and t <= ref_times[0]:
            out.append(ref_vals[0])
        else:
            t0, t1 = ref_times[j], ref_times[j + 1]
            v0, v1 = ref_vals[j], ref_vals[j + 1]
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            out.append(v0 + frac * (v1 - v0))
    return out


def build_ramp_ref(times):
    """Synthetic gen-on thermal ramp: 0 before gen-on, linear rise, exp decay after."""
    ref = []
    for t in times:
        if t < GEN_ON_T:
            ref.append(0.0)
        elif t <= GEN_OFF_T:
            ref.append((t - GEN_ON_T) / (GEN_OFF_T - GEN_ON_T))
        else:
            ref.append(math.exp(-(t - GEN_OFF_T) / 200.0))
    return ref


def pearson_r(xs, ys):
    n = len(xs)
    if n < 10:
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


def le_uint16(data, byte_offset):
    return data[byte_offset] | (data[byte_offset + 1] << 8)


def main():
    print("Parsing log (this takes ~30s)...")
    frames = list(parse_file(LOG))
    print(f"  {len(frames)} frames loaded")

    # Identify PT bus: has 0x051 at high rate
    bus_cnt = defaultdict(lambda: defaultdict(int))
    for fr in frames:
        bus_cnt[fr.bus][fr.arbitration_id] += 1
    pt_bus = next((b for b, cnt in bus_cnt.items() if cnt.get(0x051, 0) > 10000), None)
    if pt_bus is None:
        sys.exit("ERROR: could not identify PT bus")
    print(f"  PT bus = {pt_bus}")

    # Build per-(id,byte) timeseries on PT bus; also collect reference signals
    ts          = defaultdict(lambda: defaultdict(list))  # ts[id][byte] = [(t,v)]
    gen_torq_ts = []   # (t, |torque_magnitude|) from 0x051 B1-B2
    drv_torq_ts = []   # (t, |torque_magnitude|) from 0x5A2 B4-B5
    pump_ts     = []   # (t, pump_speed_B5)      from 0x18FF0320

    t0 = None
    for fr in frames:
        if fr.bus != pt_bus:
            continue
        if t0 is None:
            t0 = fr.timestamp
        t = fr.timestamp - t0
        aid = fr.arbitration_id
        data = fr.data

        # Collect reference signals
        if aid == 0x051 and len(data) >= 3:
            raw = le_uint16(data, 1)
            gen_torq_ts.append((t, abs(raw - 32768)))
        if aid == 0x5A2 and len(data) >= 6:
            raw = le_uint16(data, 4)
            drv_torq_ts.append((t, abs(raw - 32768)))
        if aid == 0x18FF0320 and len(data) >= 6:
            pump_ts.append((t, data[5]))

        # Accumulate all bytes
        for bi, byte_val in enumerate(data):
            ts[aid][bi].append((t, byte_val))

    print(f"  {len(ts)} unique IDs on PT bus")
    print(f"  Reference sizes: gen_torq={len(gen_torq_ts)}, drv_torq={len(drv_torq_ts)}, pump={len(pump_ts)}")

    # Unpack reference timeseries
    gt_t, gt_v = zip(*gen_torq_ts) if gen_torq_ts else ([], [])
    dt_t, dt_v = zip(*drv_torq_ts) if drv_torq_ts else ([], [])
    pm_t, pm_v = zip(*pump_ts)     if pump_ts     else ([], [])
    gt_t, gt_v = list(gt_t), list(gt_v)
    dt_t, dt_v = list(dt_t), list(dt_v)
    pm_t, pm_v = list(pm_t), list(pm_v)

    results = []
    for aid, byte_dict in ts.items():
        # Skip known IDs
        is_ext = bool(aid & 0x80000000)
        if not is_ext and aid in KNOWN_PT_IDS:
            continue
        if is_ext and (aid & 0xFF) in KNOWN_EXT_SRCS:
            continue

        for bi, samples in byte_dict.items():
            if len(samples) < 50:
                continue
            times = [t for t, _ in samples]
            vals  = [v for _, v in samples]
            unique = len(set(vals))
            rng = max(vals) - min(vals)

            # Thermal filter: slowly varying, moderate range
            if unique < 4 or rng < 3:
                continue
            mac = median_abs_change(vals)
            if mac > 10:
                continue

            # Reference 1: synthetic gen-on ramp
            r_ramp = pearson_r(build_ramp_ref(times), vals)

            # Reference 2: gen torque magnitude (interpolated)
            r_gen = pearson_r(interp(gt_t, gt_v, times), vals) if gt_t else 0.0

            # Reference 3: drivetrain torque magnitude (interpolated)
            r_drv = pearson_r(interp(dt_t, dt_v, times), vals) if dt_t else 0.0

            # Reference 4: negated pump speed (real thermals should track negatively)
            # We negate pump speed so positive r_pump means the signal rises when pump slows
            r_pump = pearson_r([-v for v in interp(pm_t, pm_v, times)], vals) if pm_t else 0.0

            best_r = max(abs(r_ramp), abs(r_gen), abs(r_drv), abs(r_pump))
            score  = best_r - 0.05 * mac

            results.append({
                'id': aid, 'byte': bi,
                'unique': unique, 'range': rng,
                'min': min(vals), 'max': max(vals),
                'mac': mac,
                'r_ramp': r_ramp, 'r_gen': r_gen, 'r_drv': r_drv, 'r_pump': r_pump,
                'best_r': best_r, 'score': score,
                'n': len(samples),
                'hz': len(samples) / (times[-1] - times[0]) if times[-1] > times[0] else 0,
            })

    results.sort(key=lambda x: -x['score'])

    lines = [
        "Vtrux PT Bus Thermal Candidates -- evap4 Part 1",
        "Ranked by score = max(|r| across 4 refs) - 0.05*MAC",
        "  r_ramp: vs synthetic gen-on ramp",
        "  r_gen:  vs gen torque magnitude (|0x051 B1-B2 - 32768|)",
        "  r_drv:  vs drivetrain torque magnitude (|0x5A2 B4-B5 - 32768|)",
        "  r_pump: vs negated pump speed (positive = rises when pump slows)",
        f"Gen-on window: t={GEN_ON_T}s to t={GEN_OFF_T}s",
        "",
        f"{'Rank':>4}  {'ID':>12}  {'B':>2}  {'r_ramp':>7}  {'r_gen':>7}  "
        f"{'r_drv':>7}  {'r_pump':>7}  {'MAC':>5}  {'Uniq':>4}  "
        f"{'Range':>10}  {'Score':>6}  {'Hz':>5}",
        "-" * 100,
    ]

    for rank, res in enumerate(results[:40], 1):
        id_str = f"0x{res['id']:08X}" if res['id'] > 0x7FF else f"0x{res['id']:03X}"
        lines.append(
            f"{rank:>4}  {id_str:>12}  {res['byte']:>2}  "
            f"{res['r_ramp']:>+7.3f}  {res['r_gen']:>+7.3f}  "
            f"{res['r_drv']:>+7.3f}  {res['r_pump']:>+7.3f}  "
            f"{res['mac']:>5.2f}  {res['unique']:>4}  "
            f"{res['min']:>4}-{res['max']:>4}  {res['score']:>+6.3f}  {res['hz']:>5.1f}"
        )

    lines += ["", f"Total candidates before ranking: {len(results)}"]
    output = "\n".join(lines)
    print("\n" + output)
    with open(OUT, 'w', encoding='ascii') as f:
        f.write(output)
    print(f"\nWritten to {OUT}")


if __name__ == '__main__':
    main()
