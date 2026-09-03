"""
Cross-validate DCDC_LV_Curr (0x18FFD6B3 B2-B3, x0.05 A) against the HV side using
the battery-conditioning ON/OFF step as a known switched load.

Test: on 2026-07-14 the cooling package energised at 20:37:04 while the truck was
parked and AC-charging. The 12V step is ~+95 A at ~14.3 V (~1.36 kW). If the
DCDC_LV_Curr scale is right, an equal amount of power (divided by DCDC efficiency)
must appear on the HV side -- either as extra charger DC output, less pack charge
current, or extra AC draw from the wall.

Phase A: parse the chunks bracketing each cooling edge, cache samples to CSV.
Phase B: edge analysis -- linear detrend either side of the edge, extrapolate to
         the edge time, compare the 12V step to the HV-side step.

Run from project root:  python3.13 projects/vtrux/notes/artifacts/dcdc_hv_crosscheck.py
"""
import sys
sys.path.insert(0, ".")

import csv
import os
from canre.parsers import parse_file
import cantools

RUN_A = True   # parse the bracketing chunks -> CSV cache (skipped if cache exists)
RUN_B = True   # edge analysis: 12V step vs HV-side step
RUN_C = True   # robustness: time-resolved edge, window sensitivity, alternative scales
RUN_D = True   # coarse corroboration from the existing cross-session cache

LOGDIR = "../../CANLogs/VtruxLogs"
STEM = "vtrux_20260714_161319_T"
ART = "projects/vtrux/notes/artifacts"
CACHE = os.path.join(ART, "dcdc_hv_crosscheck_samples.csv")

# T56..T60 brackets the 20:37:04 ON edge; T72..T76 brackets the 21:55:53 OFF edge
CHUNKS = list(range(56, 61)) + list(range(72, 77))

BUS = 29          # PT bus in this capture (identified by 0x410/0x430/0x18FFD6B3 content)
ID_BMS = 0x410
ID_DCDC = 0x18FFD6B3
ID_CHG = 0x18FFD7C0
ID_506 = 0x506
ID_508 = 0x508
WANT = {ID_BMS, ID_DCDC, ID_CHG, ID_506, ID_508}

PT_DBC = "projects/vtrux/epri-pt-bus.dbc"
BEL_DBC = "projects/vtrux/BelInverter-v2.dbc"


def phase_a():
    pt = cantools.database.load_file(PT_DBC)
    bel = cantools.database.load_file(BEL_DBC)
    m_bms = pt.get_message_by_frame_id(ID_BMS)
    m_dcdc = pt.get_message_by_frame_id(ID_DCDC)
    m_chg = bel.get_message_by_frame_id(ID_CHG)

    with open(CACHE, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t", "kind", "a", "b", "c", "d"])
        for i in CHUNKS:
            path = os.path.join(LOGDIR, STEM + str(i) + ".log")
            if not os.path.exists(path):
                print("MISSING", path)
                continue
            n = 0
            for f in parse_file(path, absolute=True):
                if f.bus != BUS or f.arbitration_id not in WANT:
                    continue
                aid = f.arbitration_id
                t = f.timestamp
                if aid == ID_BMS and len(f.data) == 8:
                    d = m_bms.decode(f.data)
                    w.writerow([f"{t:.4f}", "bms", d["bcm_ibat"], d["bcm_vbat"], d["bcm_soc"], ""])
                elif aid == ID_DCDC and len(f.data) == 8:
                    d = m_dcdc.decode(f.data)
                    w.writerow([f"{t:.4f}", "dcdc", d["DCDC_LV_Curr"], d["DCDC_LV_Volt"],
                                d["DCDC_HV_Volt"], d["DCDC_Temperature"]])
                elif aid == ID_CHG and len(f.data) == 8:
                    d = m_chg.decode(f.data)
                    w.writerow([f"{t:.4f}", "chg", d["BELINV_hvBatteryCurrent"], d["BELINV_hvBatteryVoltage"],
                                d["BELINV_chargerInputCurrent"], d["BELINV_chargerInputVoltage"]])
                elif aid == ID_506 and len(f.data) >= 1:
                    w.writerow([f"{t:.4f}", "c506", (f.data[0] >> 5) & 1, f.data[0], "", ""])
                elif aid == ID_508:
                    w.writerow([f"{t:.4f}", "c508", 1, "", "", ""])
                n += 1
            print(f"T{i}: {n} frames of interest")


def hms(t):
    t = float(t)
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"


def load():
    rows = {"bms": [], "dcdc": [], "chg": [], "c506": [], "c508": []}
    with open(CACHE) as fh:
        r = csv.reader(fh)
        next(r)
        for t, kind, a, b, c, d in r:
            vals = [float(x) if x != "" else None for x in (a, b, c, d)]
            rows[kind].append((float(t), *vals))
    for k in rows:
        rows[k].sort(key=lambda x: x[0])
    return rows


def linfit(pts):
    """least squares y = m*x + k over (x, y) pairs; returns (m, k, n)"""
    n = len(pts)
    if n < 2:
        return None
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    den = n * sxx - sx * sx
    if den == 0:
        return None
    m = (n * sxy - sx * sy) / den
    k = (sy - m * sx) / n
    return m, k, n


def step_at(series, t_edge, guard, span):
    """Fit a line to [t_edge-guard-span, t_edge-guard] and [t_edge+guard, t_edge+guard+span],
    extrapolate both to t_edge, return (pre, post, delta, slope_pre, slope_post, n_pre, n_post)."""
    pre = [(t - t_edge, v) for t, v in series if -guard - span <= t - t_edge <= -guard]
    post = [(t - t_edge, v) for t, v in series if guard <= t - t_edge <= guard + span]
    fp, fq = linfit(pre), linfit(post)
    if fp is None or fq is None:
        return None
    return fq[1] - fp[1], fp[1], fq[1], fp[0], fq[0], fp[2], fq[2]


def find_edges(rows):
    """Cooling ON/OFF edges from 0x508 presence (gap-merged), cross-checked vs 0x506 bit5."""
    ts = [t for (t, *_r) in rows["c508"]]
    if not ts:
        return []
    runs = []
    start = prev = ts[0]
    for t in ts[1:]:
        if t - prev > 30.0:
            runs.append((start, prev))
            start = t
        prev = t
    runs.append((start, prev))
    return [r for r in runs if r[1] - r[0] > 60.0]


def report_edge(rows, t_edge, label, guard=20.0, span=120.0):
    print()
    print("=" * 78)
    print(f"{label}   t = {hms(t_edge)}")
    print(f"windows: pre [-{guard + span:.0f}s, -{guard:.0f}s], post [+{guard:.0f}s, +{guard + span:.0f}s]"
          f"  (linear detrend, extrapolated to the edge)")
    print("=" * 78)

    dcdc = rows["dcdc"]
    bms = rows["bms"]
    chg = rows["chg"]

    ser = {
        "DCDC_LV_Curr (A)": [(t, a) for t, a, b, c, d in dcdc],
        "DCDC_LV_Volt (V)": [(t, b) for t, a, b, c, d in dcdc],
        "DCDC_HV_Volt (V)": [(t, c) for t, a, b, c, d in dcdc],
        "P_12V = LVxLV (W)": [(t, a * b) for t, a, b, c, d in dcdc],
        "bcm_ibat (A)": [(t, a) for t, a, b, c, d in bms],
        "bcm_vbat (V)": [(t, b) for t, a, b, c, d in bms],
        "P_pack = VxI (W)": [(t, a * b) for t, a, b, c, d in bms],
        "chg hvBattCurr (A)": [(t, a) for t, a, b, c, d in chg],
        "chg hvBattVolt (V)": [(t, b) for t, a, b, c, d in chg],
        "P_dc = -VxI (W)": [(t, -a * b) for t, a, b, c, d in chg],
        "chg AC curr (A)": [(t, c) for t, a, b, c, d in chg if 0 <= c <= 60],
        "chg AC volt (V)": [(t, d) for t, a, b, c, d in chg if 80 <= d <= 300],
        "S_ac = VxI (VA)": [(t, c * d) for t, a, b, c, d in chg if 0 <= c <= 60 and 80 <= d <= 300],
    }

    print(f"{'signal':22s} {'pre':>12s} {'post':>12s} {'step':>12s} "
          f"{'pre slope/min':>14s} {'n pre/post':>12s}")
    out = {}
    for name, s in ser.items():
        r = step_at(s, t_edge, guard, span)
        if r is None:
            print(f"{name:22s}  (insufficient samples)")
            continue
        delta, pre, post, mp, mq, npre, npost = r
        out[name] = delta
        print(f"{name:22s} {pre:12.2f} {post:12.2f} {delta:12.2f} "
              f"{mp * 60:14.2f} {str(npre) + '/' + str(npost):>12s}")

    print()
    d12 = out.get("P_12V = LVxLV (W)")
    dpack = out.get("P_pack = VxI (W)")
    ddc = out.get("P_dc = -VxI (W)")
    dac = out.get("S_ac = VxI (VA)")
    if d12 is None:
        return
    print(f"  12V step               : {d12:9.0f} W  ({out.get('DCDC_LV_Curr (A)', 0):.1f} A at "
          f"{out.get('DCDC_LV_Volt (V)', 0) + ser['DCDC_LV_Volt (V)'][0][1]:.2f} V nominal)")
    if ddc is not None and dpack is not None:
        aux = ddc - dpack
        print(f"  charger DC out step    : {ddc:9.0f} W")
        print(f"  pack power step        : {dpack:9.0f} W")
        print(f"  -> HV aux step (dc-pack): {aux:9.0f} W")
        if abs(d12) > 1:
            print(f"  -> implied DCDC eff     : {100 * d12 / aux:7.1f} %   "
                  f"(P_12V / P_HVaux; expect 85-95%)")
            print(f"  -> scale error factor   : {aux * 0.90 / d12:7.3f}   "
                  f"(1.00 = DBC scale correct at 90% eff)")
    if dac is not None and abs(d12) > 1:
        print(f"  charger AC in step     : {dac:9.0f} VA")
        print(f"  -> P_12V / S_ac         : {100 * d12 / dac:7.1f} %   "
              f"(expect ~= eff_charger x eff_dcdc x PF, ~80-88%)")


def phase_b():
    rows = load()
    print(f"loaded: " + ", ".join(f"{k}={len(v)}" for k, v in rows.items()))
    runs = find_edges(rows)
    print("\n0x508 cooling runs found in the cached window:")
    for a, b in runs:
        print(f"  {hms(a)} -> {hms(b)}   ({b - a:.0f} s)")

    if not runs:
        return
    report_edge(rows, runs[0][0], "COOLING ON EDGE (parked, AC charging)")
    report_edge(rows, runs[-1][1], "COOLING OFF EDGE (coincides with charge end -- CONFOUNDED)")




# ---------------------------------------------------------------- Phase C
# Robustness: is the answer stable against window choice, and do the 12V and HV
# steps land at the same instant (i.e. is this really one event)?

def bucket_medians(series, t_edge, lo, hi, width):
    out = []
    b = lo
    while b < hi:
        vals = sorted(v for t, v in series if b <= t - t_edge < b + width)
        if vals:
            out.append((b, vals[len(vals) // 2], len(vals)))
        b += width
    return out


def phase_c():
    rows = load()
    runs = find_edges(rows)
    t_edge = runs[0][0]
    dcdc, bms, chg = rows["dcdc"], rows["bms"], rows["chg"]

    p12 = [(t, a * b) for t, a, b, c, d in dcdc]
    ppack = [(t, a * b) for t, a, b, c, d in bms]
    pdc = [(t, -a * b) for t, a, b, c, d in chg]

    print()
    print("=" * 78)
    print("PHASE C1 -- time-resolved, 5 s medians around the ON edge")
    print("=" * 78)
    print(f"{'t rel (s)':>10s} {'P_12V (W)':>11s} {'P_pack (W)':>11s} {'P_dc (W)':>11s} "
          f"{'P_dc-P_pack':>12s}")
    b12 = dict((b, v) for b, v, n in bucket_medians(p12, t_edge, -40, 45, 5))
    bpk = dict((b, v) for b, v, n in bucket_medians(ppack, t_edge, -40, 45, 5))
    bdc = dict((b, v) for b, v, n in bucket_medians(pdc, t_edge, -40, 45, 5))
    for b in sorted(b12):
        if b in bpk and b in bdc:
            print(f"{b:10d} {b12[b]:11.0f} {bpk[b]:11.0f} {bdc[b]:11.0f} {bdc[b] - bpk[b]:12.0f}")

    print()
    print("=" * 78)
    print("PHASE C2 -- window sensitivity (guard g, span s), detrended step")
    print("=" * 78)
    print(f"{'g':>4s} {'s':>5s} {'dP_12V (W)':>12s} {'dP_HVaux (W)':>14s} "
          f"{'ratio 12V/aux':>14s} {'implied eff':>12s}")
    for guard in (10, 20, 30, 60):
        for span in (60, 120, 240, 420):
            r12 = step_at(p12, t_edge, guard, span)
            rpk = step_at(ppack, t_edge, guard, span)
            rdc = step_at(pdc, t_edge, guard, span)
            if not (r12 and rpk and rdc):
                continue
            aux = rdc[0] - rpk[0]
            print(f"{guard:4d} {span:5d} {r12[0]:12.0f} {aux:14.0f} "
                  f"{r12[0] / aux:14.3f} {100 * r12[0] / aux:11.1f}%")

    print()
    print("=" * 78)
    print("PHASE C3 -- what the alternative scales would imply")
    print("=" * 78)
    r12 = step_at(p12, t_edge, 20, 120)
    rpk = step_at(ppack, t_edge, 20, 120)
    rdc = step_at(pdc, t_edge, 20, 120)
    aux = rdc[0] - rpk[0]
    di = step_at([(t, a) for t, a, b, c, d in dcdc], t_edge, 20, 120)[0]
    volt = 14.30
    print(f"measured HV aux step = {aux:.0f} W; raw-count step = {di / 0.05:.0f} counts at {volt:.2f} V")
    for scale, tag in ((0.0125, "x0.25"), (0.025, "x0.5"), (0.05, "DBC"), (0.1, "x2"), (0.2, "x4")):
        p = (di / 0.05) * scale * volt
        print(f"  scale {scale:6.4f} A/count ({tag:5s}): P_12V step = {p:8.0f} W  "
              f"-> implied DCDC eff = {100 * p / aux:7.1f} %")




# ---------------------------------------------------------------- Phase D
# Corroboration across other sessions, using the existing 1 Hz cross-session cache
# (cooling_xsession_samples.csv from battery_cooling_xsession_raw.py). That cache has
# ibat and DCDC_LV_Curr but no pack voltage and no charger data, so this is a coarse
# check only: assume V_pack ~ 385 V and V_lv ~ 14.3 V and see whether the ratio lands
# near 1, i.e. whether the 2026-07-14 result generalises.

XSESS = os.path.join(ART, "cooling_xsession_samples.csv")
V_PACK_ASSUMED = 385.0
V_LV_ASSUMED = 14.3


def phase_d():
    by_sess = {}
    with open(XSESS) as fh:
        for row in csv.DictReader(fh):
            if row["ibat"] == "" or row["lv"] == "":
                continue
            by_sess.setdefault(row["session"], []).append(
                (float(row["t"]), float(row["ibat"]), float(row["lv"]), int(row["cool"])))

    print()
    print("=" * 78)
    print("PHASE D -- charging cooling-ON edges in other sessions (coarse, 1 Hz cache)")
    print("=" * 78)
    print(f"{'session':24s} {'d_lv (A)':>9s} {'d_ibat (A)':>11s} {'dP_12V':>9s} "
          f"{'dP_HV':>9s} {'ratio':>7s}")
    hits = 0
    for sess, pts in sorted(by_sess.items()):
        pts.sort()
        for i in range(1, len(pts)):
            if pts[i][3] == 1 and pts[i - 1][3] == 0:
                te = pts[i][0]
                pre = [p for p in pts if -140 <= p[0] - te <= -20]
                post = [p for p in pts if 20 <= p[0] - te <= 140]
                if len(pre) < 30 or len(post) < 30:
                    continue
                mean = lambda s, k: sum(p[k] for p in s) / len(s)
                # charging only, and steady: require ibat > +5 A both sides
                if mean(pre, 1) < 5 or mean(post, 1) < 5:
                    continue
                # require the whole pre window to be cooling-off and post to be cooling-on
                if any(p[3] for p in pre) or not all(p[3] for p in post):
                    continue
                dlv = mean(post, 2) - mean(pre, 2)
                dib = mean(post, 1) - mean(pre, 1)
                if dlv < 40:
                    continue
                p12 = dlv * V_LV_ASSUMED
                phv = -dib * V_PACK_ASSUMED
                hits += 1
                print(f"{sess:24s} {dlv:9.1f} {dib:11.2f} {p12:9.0f} {phv:9.0f} "
                      f"{(p12 / phv if phv else float('nan')):7.2f}")
    if hits == 0:
        print("  no clean charging ON edges with both signals in the cache")
    else:
        print(f"\n  {hits} edge(s). Ratio ~1 corroborates the DBC scale; the pack voltage is")
        print(f"  assumed ({V_PACK_ASSUMED:.0f} V) so treat these as order-of-magnitude only.")


if __name__ == "__main__":
    if RUN_A:
        if os.path.exists(CACHE):
            print(f"cache exists ({CACHE}), skipping parse -- delete it to re-parse")
        else:
            phase_a()
    if RUN_B:
        phase_b()
    if RUN_C:
        phase_c()
    if RUN_D:
        phase_d()
