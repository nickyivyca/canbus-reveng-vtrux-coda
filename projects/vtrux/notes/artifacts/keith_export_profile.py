"""Export-session profiler -- compare Truck 3's log 6 export run against main-truck references.

Extracts, for any PT-bus log:
  0x592  export switch / ignition        (B0 bit2 = export, bit4 = ignition)
  0x053  HCU op_mode (B0[6:4]) / op_state (B0[3:0])
  0x054  GENE rpm (B0-B1 LE, offset -32767)
  0x411  BMS SoC hi-res  (B0*64 + B1>>2, /100 = %)
  0x410  BMS vbat (B7|(B6&0xF)<<8, 0.25V) / ibat ((B4<<8)|B5, signed-ish)
  0x482  HV DC bus volts (B1 | (B2&0x0F)<<8)
  0x598  power bundle: battery / generator / drivetrain (LE16, -32768, 0.01 kW/count)
  0x440  contactor state machine (B0 low nibble -> MAINC_STAT_16)

Prints a condensed timeline of engine start/stop events with the SoC at each one,
which is the number we need to calibrate Truck 3's "engine starts too early" complaint.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/truck3-export_profile.py <log> [<log> ...]
"""
import sys
sys.path.insert(0, ".")

from canre.parsers import parse_file

# Must match tools/diagnose_vtrux.py MAINC_STAT_16 exactly.
MAINC_STAT_16 = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]

RPM_ON = 300      # engine considered running above this
RPM_OFF = 100     # and stopped below this


def profile(path):
    print("=" * 78)
    print(path)
    print("=" * 78)

    t0 = None
    state = {"export": None, "ign": None, "mode": None, "opstate": None,
             "rpm": 0, "soc": None, "vbat": None, "mainc": None,
             "pbatt": None, "pgen": None, "pdrv": None, "hv": None, "ibat": None}
    engine_on = False
    events = []
    rpm_peak = 0
    soc_min, soc_max = 999.0, -999.0
    gen_kw_peak = 0.0
    batt_kw_min, batt_kw_max = 999.0, -999.0

    for f in parse_file(path):
        if t0 is None:
            t0 = f.timestamp
        t = f.timestamp - t0
        d = f.data
        i = f.arbitration_id

        if i == 0x592 and len(d) >= 1:
            ex = (d[0] >> 2) & 1
            ig = (d[0] >> 4) & 1
            if ex != state["export"]:
                events.append((t, "EXPORT SWITCH", "%s" % ("ON" if ex else "OFF"), dict(state)))
                state["export"] = ex
            if ig != state["ign"]:
                events.append((t, "IGNITION", "%s" % ("ON" if ig else "OFF"), dict(state)))
                state["ign"] = ig

        elif i == 0x053 and len(d) >= 1:
            m = (d[0] >> 4) & 0x7
            s = d[0] & 0xF
            if m != state["mode"]:
                events.append((t, "HCU op_mode", "%s -> %s" % (state["mode"], m), dict(state)))
                state["mode"] = m
            state["opstate"] = s

        elif i == 0x054 and len(d) >= 2:
            rpm = (d[0] | (d[1] << 8)) - 32767
            state["rpm"] = rpm
            rpm_peak = max(rpm_peak, rpm)
            if not engine_on and rpm > RPM_ON:
                events.append((t, "*** ENGINE START ***", "rpm=%d" % rpm, dict(state)))
                engine_on = True
            elif engine_on and rpm < RPM_OFF:
                events.append((t, "*** ENGINE STOP ***", "rpm=%d" % rpm, dict(state)))
                engine_on = False

        elif i == 0x411 and len(d) >= 2:
            raw = d[0] * 64 + (d[1] >> 2)
            if raw < 0x3FFE:
                state["soc"] = raw / 100.0
                soc_min = min(soc_min, state["soc"])
                soc_max = max(soc_max, state["soc"])

        elif i == 0x410 and len(d) >= 8:
            state["vbat"] = (d[7] | ((d[6] & 0xF) << 8)) * 0.25
            raw_i = (d[4] << 8) | d[5]
            state["ibat"] = None if (raw_i & 0xFFFE) == 0xFFFE else raw_i * 0.025 - 1000.0

        elif i == 0x440 and len(d) >= 1:
            m = (d[0] >> 2) & 0x0F
            if m != state["mainc"]:
                events.append((t, "CONTACTOR", "%s -> %s"
                               % (MAINC_STAT_16[state["mainc"]] if state["mainc"] is not None else "?",
                                  MAINC_STAT_16[m]), dict(state)))
                state["mainc"] = m

        elif i == 0x482 and len(d) >= 3:
            state["hv"] = d[1] | ((d[2] & 0x0F) << 8)

        elif i == 0x598 and len(d) >= 6:
            state["pbatt"] = ((d[0] | (d[1] << 8)) - 32768) * 0.01
            state["pgen"] = ((d[2] | (d[3] << 8)) - 32768) * 0.01
            state["pdrv"] = ((d[4] | (d[5] << 8)) - 32768) * 0.01
            gen_kw_peak = max(gen_kw_peak, abs(state["pgen"]))
            batt_kw_min = min(batt_kw_min, state["pbatt"])
            batt_kw_max = max(batt_kw_max, state["pbatt"])

    print("  duration=%.1fs  rpm_peak=%d  soc range=%.2f%% - %.2f%%" % (t, rpm_peak, soc_min, soc_max))
    print("  |gen power| peak = %.2f kW    battery power %.2f .. %.2f kW" % (gen_kw_peak, batt_kw_min, batt_kw_max))
    print()
    print("  %-9s %-22s %-26s %s" % ("time", "event", "detail", "state at event"))
    print("  " + "-" * 108)
    for t, ev, detail, st in events:
        ctx = "soc=%s vbat=%s hv=%s rpm=%s export=%s pgen=%s pbatt=%s" % (
            ("%.2f%%" % st["soc"]) if st["soc"] is not None else "?",
            ("%.1fV" % st["vbat"]) if st["vbat"] is not None else "?",
            ("%dV" % st["hv"]) if st["hv"] is not None else "?",
            st["rpm"],
            st["export"],
            ("%.2fkW" % st["pgen"]) if st["pgen"] is not None else "?",
            ("%.2fkW" % st["pbatt"]) if st["pbatt"] is not None else "?",
        )
        print("  t=%8.3f %-22s %-26s %s" % (t, ev, detail, ctx))
    print()


if __name__ == "__main__":
    for p in sys.argv[1:]:
        profile(p)
