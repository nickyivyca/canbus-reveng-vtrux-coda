"""
12V standing (idle) draw during AC charging: parts truck vs main truck.

Context: the 2026-07-14 main-truck charge sat at only 86 W of 12V load
(DCDC_LV_Curr 5.99 A at 14.35 V) before the conditioning package engaged.
The parts truck runs its PE coolant pump uncontrolled -- 0x18FF0320 has zero
frames, so the VFD never receives a speed command and free-runs at full speed
(charger-efficiency-and-grid-consumption.md, warning-lamp-investigation.md).
That should show up as a materially higher standing 12V draw.

Phase E: per-log steady-state 12V load during charging, cooling off.
Phase F: vtrux_partstruck_pumpplugin.log -- does 0x18FF0320 appear mid-log
         (pump reconnected to CAN)? If so the free-run -> commanded transition
         is a second known-load step for the DCDC_LV_Curr scale.

Inputs are grep-prefiltered copies in artifacts/filtered/ (the raw logs are up
to 6.2 GB; the filter keeps only the handful of IDs used here plus the
BUSMASTER header, so the canre parser still handles them normally).

Run from project root:  python3.13 projects/vtrux/notes/artifacts/dcdc_idle_draw_pump.py
"""
import sys
sys.path.insert(0, ".")

import os
from collections import defaultdict
from canre.parsers import parse_file
import cantools

RUN_E = True
RUN_F = True
RUN_G = True

ART = "projects/vtrux/notes/artifacts"
FILT = os.path.join(ART, "filtered")

ID_BMS = 0x410
ID_DCDC = 0x18FFD6B3
ID_CHG = 0x18FFD7C0
ID_PUMP = 0x18FF0320
ID_508 = 0x508

LOGS = [
    ("vtrux_partstruck_charge", "parts", "9.5 h overnight charge 2026-04-22"),
    ("vtrux_partstruck_chargeagain2", "parts", "short charge 2026-04-25"),
    ("vtruxchargeafteroverheattest-32asetpoint", "main", "32 A setpoint charge"),
    ("rainychargedebug", "main", "charge"),
    ("vtruxchargeafterucsc", "main", "charge"),
    ("vtruxchargeblueevse", "main", "charge"),
]

pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
bel = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc")
M_BMS = pt.get_message_by_frame_id(ID_BMS)
M_DCDC = pt.get_message_by_frame_id(ID_DCDC)
M_CHG = bel.get_message_by_frame_id(ID_CHG)


def med(v):
    v = sorted(v)
    return v[len(v) // 2] if v else float("nan")


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))] if v else float("nan")


def scan(name):
    """Return per-log samples. PT bus is identified by which bus carries 0x410,
    never by channel number (it varies with dongle insertion order)."""
    path = os.path.join(FILT, name + ".log")
    if not os.path.exists(path):
        return None
    bus_votes = defaultdict(int)
    frames = []
    for f in parse_file(path, absolute=True):
        if f.arbitration_id == ID_BMS:
            bus_votes[f.bus] += 1
        frames.append((f.timestamp, f.bus, f.arbitration_id, f.data))
    if not bus_votes:
        return None
    ptbus = max(bus_votes, key=bus_votes.get)

    bms, dcdc, chg = [], [], []
    n_pump = n_508 = 0
    pump_times = []
    for t, bus, aid, data in frames:
        if bus != ptbus:
            continue
        if aid == ID_PUMP:
            n_pump += 1
            pump_times.append(t)
            continue
        if aid == ID_508:
            n_508 += 1
            continue
        if len(data) != 8:
            continue
        if aid == ID_BMS:
            d = M_BMS.decode(data)
            bms.append((t, d["bcm_ibat"], d["bcm_vbat"]))
        elif aid == ID_DCDC:
            d = M_DCDC.decode(data)
            dcdc.append((t, d["DCDC_LV_Curr"], d["DCDC_LV_Volt"]))
        elif aid == ID_CHG:
            d = M_CHG.decode(data)
            chg.append((t, d["BELINV_hvBatteryCurrent"], d["BELINV_hvBatteryVoltage"]))
    return dict(bus=ptbus, bms=bms, dcdc=dcdc, chg=chg, n_pump=n_pump,
                n_508=n_508, pump_times=pump_times)


def charging_mask(bms, dcdc):
    """DCDC samples whose nearest BMS sample within 2 s shows charging (ibat > +5 A)."""
    if not bms:
        return []
    bt = [b[0] for b in bms]
    import bisect
    out = []
    for t, i, v in dcdc:
        k = bisect.bisect_left(bt, t)
        best = None
        for kk in (k - 1, k):
            if 0 <= kk < len(bms) and abs(bms[kk][0] - t) < 2.0:
                if best is None or abs(bms[kk][0] - t) < abs(best[0] - t):
                    best = bms[kk]
        if best and best[1] > 5.0:
            out.append((t, i, v, best[1], best[2]))
    return out


def phase_e():
    print("=" * 96)
    print("PHASE E -- 12V standing load during AC charging (cooling off), parts vs main")
    print("=" * 96)
    print(f"{'log':44s} {'truck':6s} {'0x18FF0320':>11s} {'n':>7s} "
          f"{'LV_Curr med':>12s} {'p10':>7s} {'p90':>7s} {'LV_V':>6s} {'P_12V':>8s}")
    for name, truck, _desc in LOGS:
        r = scan(name)
        if r is None:
            print(f"{name:44s}  (filtered log missing)")
            continue
        ch = charging_mask(r["bms"], r["dcdc"])
        if r["n_508"]:
            print(f"  note: {name} has {r['n_508']} 0x508 frames (cooling active somewhere)")
        cur = [c[1] for c in ch]
        volt = [c[2] for c in ch]
        if not cur:
            print(f"{name:44s} {truck:6s} {r['n_pump']:11d} {0:7d}   (no charging samples)")
            continue
        p12 = med(cur) * med(volt)
        print(f"{name:44s} {truck:6s} {r['n_pump']:11d} {len(cur):7d} "
              f"{med(cur):12.2f} {pct(cur, 0.10):7.2f} {pct(cur, 0.90):7.2f} "
              f"{med(volt):6.2f} {p12:7.0f}W")
    print()
    print("0x18FF0320 = PE coolant pump on CAN. Zero frames = pump not on CAN = VFD")
    print("free-runs at full speed (the parts-truck condition).")


def phase_f():
    print()
    print("=" * 96)
    print("PHASE F -- vtrux_partstruck_pumpplugin.log: is there a pump-reconnect step?")
    print("=" * 96)
    r = scan("vtrux_partstruck_pumpplugin")
    if r is None:
        print("  filtered log missing")
        return
    print(f"PT bus = {r['bus']}; 0x18FF0320 frames = {r['n_pump']}; "
          f"0x508 frames = {r['n_508']}")
    if r["dcdc"]:
        t0 = r["dcdc"][0][0]
        print(f"log span {r['dcdc'][-1][0] - t0:.0f} s, {len(r['dcdc'])} DCDC samples")
    if r["n_pump"]:
        pts = r["pump_times"]
        print(f"pump message first seen at t+{pts[0] - t0:.1f} s, last at t+{pts[-1] - t0:.1f} s")
    else:
        print("pump never appears on CAN in this log -- no reconnect event captured,")
        print("so no free-run -> commanded step is available here.")

    print()
    print("60 s medians of DCDC_LV_Curr across the log (A):")
    if not r["dcdc"]:
        return
    buckets = defaultdict(list)
    for t, i, v in r["dcdc"]:
        buckets[int((t - t0) // 60)].append(i)
    ib = {}
    for t, i, v in r["bms"]:
        ib.setdefault(int((t - t0) // 60), []).append(i)
    print(f"{'min':>5s} {'LV_Curr':>9s} {'n':>6s} {'ibat':>8s}")
    for b in sorted(buckets):
        print(f"{b:5d} {med(buckets[b]):9.2f} {len(buckets[b]):6d} "
              f"{(med(ib[b]) if b in ib else float('nan')):8.2f}")




# ---------------------------------------------------------------- Phase G
# Time profile of the 9.5 h parts-truck charge, to check the elevated 12V load is a
# sustained standing draw and not the early 12V-battery recharge transient (which is
# what made the 2026-03-29 Phase 4 pump comparison inconclusive).

def phase_g():
    print()
    print("=" * 96)
    print("PHASE G -- 10 min profile, parts-truck 9.5 h charge vs a main-truck charge")
    print("=" * 96)
    for name in ("vtrux_partstruck_charge", "vtruxchargeblueevse"):
        r = scan(name)
        if r is None:
            continue
        ch = charging_mask(r["bms"], r["dcdc"])
        if not ch:
            continue
        t0 = ch[0][0]
        buckets = defaultdict(list)
        for t, i, v, ib, vb in ch:
            buckets[int((t - t0) // 600)].append((i, v, ib))
        print(f"\n{name}  ({len(ch)} charging samples, span {(ch[-1][0] - t0) / 3600:.2f} h)")
        print(f"{'t (h)':>7s} {'LV_Curr':>9s} {'LV_Volt':>9s} {'P_12V':>8s} "
              f"{'ibat':>8s} {'n':>7s}")
        for b in sorted(buckets):
            vals = buckets[b]
            i = med([x[0] for x in vals])
            v = med([x[1] for x in vals])
            ib = med([x[2] for x in vals])
            print(f"{b / 6:7.2f} {i:9.2f} {v:9.2f} {i * v:7.0f}W {ib:8.2f} {len(vals):7d}")
        tail = [x for b in sorted(buckets)[len(buckets) // 2:] for x in buckets[b]]
        if tail:
            i = med([x[0] for x in tail])
            v = med([x[1] for x in tail])
            print(f"  second-half median: {i:.2f} A at {v:.2f} V = {i * v:.0f} W")


if __name__ == "__main__":
    if RUN_E:
        phase_e()
    if RUN_F:
        phase_f()
    if RUN_G:
        phase_g()
