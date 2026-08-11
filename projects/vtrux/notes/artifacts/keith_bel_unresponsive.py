"""Truck 3's truck 2026-08-05: Bel charger/inverter non-responsive.

Phase 1 - full Bel (SA=0xC0) telemetry timeline for the two new logs.
Phase 2 - same extraction on known-good reference charge / export logs.

Both phases share extract(); toggle with the PHASES set below.
"""
import sys
sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

PHASES = {3}

DBC = cantools.db.load_file("projects/vtrux/BelInverter-v2.dbc")

BINV_STATUS = 0x18FFD4C0
IDS = {
    0x18FFD4C0: "BINV_status",
    0x18FFD5C0: "overallTemperature",
    0x18FFD6C0: "inverterOutput",
    0x18FFD7C0: "hvBatteryAndCharger",
    0x18FFD8C0: "j1772Info",
    0x18FFD9C0: "chargeInfo",
    0x18FFDAC0: "inverterTemperature",
    0x18FFDBC0: "buckBoostTemperature",
}

MUX0_BITS = [
    "keySwitch", "pilotControlSignal", "proxEnabled", "evseConnected",
    "vehicleConnected", "auxPowerSupply", "chargerEnergyFlowEnable", "s2Switch",
    "chargingInProgress", "powerChargingInProgress", "exportEnergy", "exporting",
    "gridTied", "wakeOutput", "delayedSleepMode", "rewakedFromDelayedSleep",
    "inverterAlive", "inverterReady", "buckBoostAlive", "buckBoostReady",
    "alciResetOn", "alciActive", "evseDisconnected", "autoLowPower",
    "standby", "unitReady",
]
MUX3_BITS = [
    "acOk", "acOverVoltage", "acUnderVoltage", "systemBatteryUnderVoltage",
    "hvBatteryOverVoltage", "hvBatteryUnderVoltage", "overTemperature",
    "exportOverLoad", "inverterFault", "buckBoostFault", "wakeOutputError",
    "underFrequency", "overFrequency",
]


def decode(arb_id, data):
    try:
        return DBC.decode_message(arb_id, bytes(data), decode_choices=False)
    except Exception:
        return None


def fmt_change(t, name, old, new):
    return "  t=%8.3f  %-32s %s -> %s" % (t, name, old, new)


def extract(path, label, tmax=None):
    print("=" * 78)
    print(label)
    print("  " + path)
    print("=" * 78)

    t0 = None
    prev0, prev3 = {}, {}
    prev_state = prev_bb = prev_inv = None
    lines = []
    # numeric series: name -> list of (t, value)
    series = {}
    counts = {k: 0 for k in IDS}

    for f in parse_file(path):
        aid = f.arbitration_id
        if aid not in IDS:
            continue
        if t0 is None:
            t0 = f.timestamp
        t = f.timestamp - t0
        if tmax is not None and t > tmax:
            break
        counts[aid] += 1
        d = decode(aid, f.data)
        if d is None:
            continue

        if aid == BINV_STATUS:
            mux = d.get("BELINV_statusMultiplexer")
            if mux == 0:
                st = d.get("BELINV_state")
                if st != prev_state:
                    lines.append(fmt_change(
                        t, "state",
                        "%s (src=%s, before=%s)" % (prev_state, prev_src, prev_before)
                        if prev_state is not None else "None",
                        "%s (src=%s, before=%s)" % (
                            st, d.get("BELINV_shutdownSource"),
                            d.get("BELINV_stateBeforeLastShutdown"))))
                    prev_state = st
                prev_src = d.get("BELINV_shutdownSource")
                prev_before = d.get("BELINV_stateBeforeLastShutdown")
                for b in MUX0_BITS:
                    key = "BELINV_" + b
                    v = d.get(key)
                    if b in prev0 and prev0[b] != v:
                        lines.append(fmt_change(t, "bit " + b, prev0[b], v))
                    prev0[b] = v
            elif mux == 1:
                v = d.get("BELINV_buckBoostState")
                if v != prev_bb:
                    lines.append(fmt_change(
                        t, "buckBoostState", prev_bb,
                        "%s (before=%s)" % (
                            v, d.get("BELINV_buckBoostStateBeforeLastShutdown"))))
                    prev_bb = v
            elif mux == 2:
                v = d.get("BELINV_inverterState")
                if v != prev_inv:
                    lines.append(fmt_change(
                        t, "inverterState", prev_inv,
                        "%s (before=%s)" % (
                            v, d.get("BELINV_inverterStateBeforeLastShutdown"))))
                    prev_inv = v
            elif mux == 3:
                for b in MUX3_BITS:
                    v = d.get("BELINV_" + b)
                    if b in prev3 and prev3[b] != v:
                        lines.append(fmt_change(t, "FAULT " + b, prev3[b], v))
                    prev3[b] = v
        else:
            for k, v in d.items():
                series.setdefault(k, []).append((t, v))

    print("\nMessage counts:")
    for aid, name in IDS.items():
        print("  0x%08X %-22s %6d" % (aid, name, counts[aid]))

    print("\nEvent timeline (%d events):" % len(lines))
    for ln in lines:
        print(ln)

    print("\nInitial mux0 bits SET:", sorted(k for k, v in prev0.items() if v))
    print("Final mux3 faults SET:", sorted(k for k, v in prev3.items() if v))

    print("\nNumeric signal ranges:")
    for k in sorted(series):
        vals = [v for _, v in series[k]]
        nz = [v for v in vals if v]
        print("  %-38s n=%5d  min=%12.3f  max=%12.3f  nonzero=%d"
              % (k, len(vals), min(vals), max(vals), len(nz)))
    print()
    return series


if 1 in PHASES:
    extract("projects/vtrux/logs/truck3-logs/candump-2026-08-05_134035.log",
            "truck3-LOG 1 - charge attempt (13:40)")
    extract("projects/vtrux/logs/truck3-logs/candump-2026-08-05_135122.log",
            "truck3-LOG 2 - export attempt (13:51)")

if 2 in PHASES:
    extract("projects/vtrux/logs/after-battery-swap-charges/charge_M0_T0.log",
            "REFERENCE - good charge start (2026-01-16)", tmax=300)
    extract("projects/vtrux/logs/vtruxexportafterucsc.log",
            "REFERENCE - good export (2026-03-01)", tmax=300)


# ---------------------------------------------------------------------------
# Phase 3 - VCU->Bel proprietary command (0x18EFC000) and J1939 DM1 fault
# messages from the Bel charger (SA=0xC0) and the Bel DCDC (SA=0xB3).
# Raw byte-change timelines; these IDs are not in any DBC.
# ---------------------------------------------------------------------------
RAW_IDS = {
    0x18EFC000: "VCU->BelChg cmd (EF00 DA=C0 SA=00)",
    0x19EF00C0: "BelChg->VCU     (EF00 DA=00 SA=C0)",
    0x18EFB3FE: "->BelDCDC cmd   (EF00 DA=B3 SA=FE)",
    0x18FECAC0: "DM1 BelChg (SA=C0)",
    0x18FECAB3: "DM1 BelDCDC (SA=B3)",
    0x18FFD4B3: "BelDCDC status",
    0x18FFD6B3: "BelDCDC HV/telemetry",
}


def raw_timeline(path, label, tmax=None):
    print("=" * 78)
    print("RAW  " + label)
    print("=" * 78)
    t0 = None
    prev = {}
    uniq = {}
    for f in parse_file(path):
        aid = f.arbitration_id
        if aid not in RAW_IDS:
            continue
        if t0 is None:
            t0 = f.timestamp
        t = f.timestamp - t0
        if tmax is not None and t > tmax:
            break
        h = f.data.hex().upper()
        uniq.setdefault(aid, {})
        uniq[aid][h] = uniq[aid].get(h, 0) + 1
        if prev.get(aid) != h:
            if aid in prev:
                print("  t=%8.3f  %-34s %s -> %s" % (t, RAW_IDS[aid], prev[aid], h))
            else:
                print("  t=%8.3f  %-34s first: %s" % (t, RAW_IDS[aid], h))
            prev[aid] = h
    print("\n  Unique payloads per ID:")
    for aid in RAW_IDS:
        if aid not in uniq:
            print("    %-34s ABSENT" % RAW_IDS[aid])
            continue
        top = sorted(uniq[aid].items(), key=lambda kv: -kv[1])[:6]
        print("    %-34s %d unique" % (RAW_IDS[aid], len(uniq[aid])))
        for h, n in top:
            print("        %s  x%d" % (h, n))
    print()


if 3 in PHASES:
    raw_timeline("projects/vtrux/logs/truck3-logs/candump-2026-08-05_134035.log",
                 "truck3-LOG 1 - charge attempt")
    raw_timeline("projects/vtrux/logs/truck3-logs/candump-2026-08-05_135122.log",
                 "truck3-LOG 2 - export attempt")
    raw_timeline("projects/vtrux/logs/after-battery-swap-charges/charge_M0_T0.log",
                 "REFERENCE - good charge start", tmax=60)
    raw_timeline("projects/vtrux/logs/vtruxexportafterucsc.log",
                 "REFERENCE - good export", tmax=60)
