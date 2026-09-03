"""
Is the (charger DC out - pack terminal power) gap a conversion loss or a fixed load?

Correction from the user 2026-08-18: the HV draw during charging is waste in the
charger on the AC->HV DC conversion side, not a 12V dissipation and not an external
HV load. This checks that against the taper: a conversion loss scales with throughput,
a fixed auxiliary load does not.

Uses the grep-prefiltered charge logs in artifacts/filtered/.
Run from project root:  python3.13 projects/vtrux/notes/artifacts/charger_dc_gap_vs_load.py
"""
import sys
sys.path.insert(0, ".")

import bisect
import os
from collections import defaultdict
from canre.parsers import parse_file
import cantools

ART = "projects/vtrux/notes/artifacts"
FILT = os.path.join(ART, "filtered")

ID_BMS, ID_DCDC, ID_CHG = 0x410, 0x18FFD6B3, 0x18FFD7C0

pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
bel = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc")
M_BMS = pt.get_message_by_frame_id(ID_BMS)
M_DCDC = pt.get_message_by_frame_id(ID_DCDC)
M_CHG = bel.get_message_by_frame_id(ID_CHG)

RUN_1 = True
RUN_2 = True

LOGS = ["vtruxchargeblueevse", "vtruxchargeafterucsc", "rainychargedebug",
        "vtruxchargeafteroverheattest-16asetpoint",
        "vtruxchargeafterscottsvalley2-16asetpoint",
        "vtruxchargeafterexportchargetest-80pctcv",
        "vtruxchargeafterucsc2", "vtruxchargeafterafterucscexport",
        "vtrux_partstruck_charge"]


def med(v):
    v = sorted(v)
    return v[len(v) // 2] if v else float("nan")


def collect(name):
    path = os.path.join(FILT, name + ".log")
    votes = defaultdict(int)
    frames = []
    for f in parse_file(path, absolute=True):
        if f.arbitration_id == ID_BMS:
            votes[f.bus] += 1
        frames.append((f.timestamp, f.bus, f.arbitration_id, f.data))
    ptbus = max(votes, key=votes.get)
    bms, dcdc, chg = [], [], []
    for t, bus, aid, data in frames:
        if bus != ptbus or len(data) != 8:
            continue
        if aid == ID_BMS:
            d = M_BMS.decode(data)
            bms.append((t, d["bcm_ibat"], d["bcm_vbat"]))
        elif aid == ID_DCDC:
            d = M_DCDC.decode(data)
            dcdc.append((t, d["DCDC_LV_Curr"], d["DCDC_LV_Volt"]))
        elif aid == ID_CHG:
            d = M_CHG.decode(data)
            v, i = d["BELINV_hvBatteryVoltage"], d["BELINV_hvBatteryCurrent"]
            ac_v, ac_i = d["BELINV_chargerInputVoltage"], d["BELINV_chargerInputCurrent"]
            chg.append((t, i, v, ac_i, ac_v))
    return bms, dcdc, chg


def nearest(arr, times, t, tol=2.0):
    k = bisect.bisect_left(times, t)
    best = None
    for kk in (k - 1, k):
        if 0 <= kk < len(arr) and abs(arr[kk][0] - t) < tol:
            if best is None or abs(arr[kk][0] - t) < abs(best[0] - t):
                best = arr[kk]
    return best


def run(name):
    bms, dcdc, chg = collect(name)
    bt = [b[0] for b in bms]
    dt = [d[0] for d in dcdc]
    rows = []
    for t, i, v, ac_i, ac_v in chg:
        b = nearest(bms, bt, t)
        d = nearest(dcdc, dt, t)
        if not b or not d:
            continue
        idc = -i                      # sign correction per BelInverter-v2.dbc comment
        if idc < 3.0:                 # exclude CV-hold idling, per charger-efficiency note
            continue
        if not (80 <= ac_v <= 300 and 0 <= ac_i <= 60):
            continue
        p_dc = idc * v
        p_pack = b[1] * b[2]
        p_12v = d[1] * d[2]
        rows.append((idc, p_dc, p_pack, p_12v, ac_i * ac_v))
    if not rows:
        print(f"{name}: no usable samples")
        return
    print(f"\n{name}  ({len(rows)} samples, CV-hold and Idc<3A excluded)")
    print(f"{'Idc bin':>10s} {'n':>7s} {'P_dc':>8s} {'P_pack':>8s} {'gap':>7s} "
          f"{'gap/P_dc':>9s} {'P_12V':>7s} {'gap-P12V/0.9':>13s} {'S_ac':>8s}")
    bins = defaultdict(list)
    for r in rows:
        bins[int(r[0] // 2) * 2].append(r)
    for b in sorted(bins):
        v = bins[b]
        if len(v) < 100:
            continue
        p_dc = med([x[1] for x in v])
        p_pack = med([x[2] for x in v])
        p12 = med([x[3] for x in v])
        s_ac = med([x[4] for x in v])
        gap = p_dc - p_pack
        print(f"{b:6d}-{b + 2:<3d} {len(v):7d} {p_dc:8.0f} {p_pack:8.0f} {gap:7.0f} "
              f"{100 * gap / p_dc:8.1f}% {p12:6.0f}W {gap - p12 / 0.9:12.0f}W {s_ac:8.0f}")


def phase1():
    print("=" * 104)
    print("charger DC-out minus pack-terminal power, binned by DC current")
    print("conversion loss -> gap grows with throughput; fixed HV load -> gap flat")
    print("=" * 104)
    for n in LOGS:
        run(n)





# ------------------------------------------------------------------ Phase 2
# Consequence of the correction: if (P_dc - P_pack) is charger conversion waste plus
# the DCDC's HV input, and that waste is a fixed overhead, then across sessions
#
#     residual = (P_dc - P_pack) - P_12V / eta_dcdc
#
# should be CONSTANT regardless of how much 12V load each session carries. That makes
# the DCDC_LV_Curr scale testable without any switched load: sweep a scale factor on
# DCDC_LV_Curr and pick the one that minimises the spread of residual across sessions.
# The sessions span 70 W to 425 W of 12V load, so a wrong scale cannot hide.

MAIN_14_16 = [
    # (session, gap W, P_12V W at DBC scale)  -- medians of the 14-16 A Idc bin above
    ("vtruxchargeblueevse", 469, 110),
    ("vtruxchargeafterucsc", 495, 117),
    ("rainychargedebug", 454, 84),
    ("vtruxchargeafterexportchargetest-80pctcv", 507, 73),
    ("vtruxchargeafterucsc2", 804, 425),
    ("vtruxchargeafterafterucscexport", 575, 194),
]


def phase2(eta=0.92):
    print()
    print("=" * 104)
    print("PHASE 2 -- scale sweep on DCDC_LV_Curr, main truck, Idc 14-16 A bin")
    print(f"residual = gap - P_12V/{eta}; correct scale -> residual constant across sessions")
    print("=" * 104)
    print(f"{'scale':>8s} " + " ".join(f"{n.split('charge')[-1][:9]:>10s}" for n, _g, _p in MAIN_14_16)
          + f" {'mean':>8s} {'spread':>8s} {'stdev':>8s}")
    best = None
    for k in (0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 4.0):
        res = [g - (p * k) / eta for _n, g, p in MAIN_14_16]
        mean = sum(res) / len(res)
        spread = max(res) - min(res)
        sd = (sum((r - mean) ** 2 for r in res) / len(res)) ** 0.5
        flag = ""
        if min(res) < 0:
            flag = "  <- negative residual: physically impossible"
        print(f"{k:8.2f} " + " ".join(f"{r:10.0f}" for r in res)
              + f" {mean:8.0f} {spread:8.0f} {sd:8.0f}{flag}")
        if best is None or sd < best[1]:
            best = (k, sd)
    print()
    print(f"minimum spread at scale factor {best[0]:.2f}x the DBC value "
          f"(0.05 A/count), stdev {best[1]:.0f} W")
    print("12V load across these sessions spans 73-425 W, a 5.8x range, so the")
    print("sweep has real leverage.")


if __name__ == "__main__":
    if RUN_1:
        phase1()
    if RUN_2:
        for e in (0.88, 0.92, 0.95):
            phase2(e)
