"""Pre-battery-swap (main-orig pack) charge failure signature.

Scope note: post-swap charge failures are a KNOWN separate fault (Bel charger
inverterFault / shutdownSource=3) and are deliberately excluded. This script looks
only at the pre-swap sessions on the main-orig pack, which are the ones carrying the
fault of interest.

Sessions:
  M0_b  truklog_M0_T0..T10   (chunked, merge by order)
  M1_b  truklog_M1_T10..T14
  2025-08-22  full-charge-then-fail.log

For every alarm NONE->TYPE1->TYPE3 escalation it reports:
  - the TYPE1 -> TYPE3 gap
  - what else changed at TYPE1 onset (the key question: is there a trigger?)
  - HVIL / chgc / contactor / rails behaviour through the event
  - whether an operator unplug preceded it (the confound from
    fault-signature-comparison.md section 4)

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/preswap_failure_signature.py
"""
import sys
import os
import re
import glob

sys.path.insert(0, ".")

MAINC = ["ALL_OPEN", "F_MAINP_R_WELD", "CLOSE_MAINR", "F_MAINR_OPEN", "F_MAINN_WELD",
         "CLOSE_MAINN", "F_MAINN_OPEN", "WAIT_PRECHARGE", "CLOSE_MAINP", "OPEN_MAINR",
         "F_MAINP_OPEN", "PN_CLOSED_DRIVE", "P_CLOSED_CHARGE", "SHUTDOWN_REQ",
         "ALL_OPEN_SHUTDOWN", "(15)"]
ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}
CHGC = {0: "OPEN", 1: "?1", 2: "?2", 3: "CLOSED"}
IDS = {0x410, 0x420, 0x430, 0x440, 0x592}

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")


def frames(paths):
    """Merge chunked BUSMASTER files in order, continuing the time base."""
    base = 0.0
    last = 0.0
    for p in paths:
        first = None
        for line in open(p, "r", encoding="utf-8", errors="ignore"):
            if line[:1] == "*":
                continue
            m = BM.match(line)
            if not m:
                continue
            hh, mm, ss, tk, idh, _x, rest = m.groups()
            aid = int(idh, 16)
            if aid not in IDS:
                continue
            t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
            if first is None:
                first = t
                base = last
            try:
                d = bytes(int(b, 16) for b in rest.split())
            except ValueError:
                continue
            tt = base + (t - first)
            last = max(last, tt)
            yield tt, aid, d, os.path.basename(p)


def decode(aid, d):
    o = {}
    if aid == 0x410 and len(d) >= 8:
        o["alarm"] = (d[1] >> 6) & 3
        o["epo"] = (d[0] >> 1) & 1
        o["hvil"] = (d[0] >> 3) & 1
        o["on_plug"] = (d[0] >> 2) & 1
        o["chgc"] = (d[0] >> 6) & 3
        raw = (d[4] << 8) | d[5]
        o["ibat"] = None if (raw & 0xFFFE) == 0xFFFE else raw * 0.025 - 1000.0
        rv = d[7] | ((d[6] & 0xF) << 8)
        o["vbat"] = None if rv >= 0xFFE else rv * 0.25
    elif aid == 0x420 and len(d) >= 7:
        o["iso_r"] = d[3]
        o["cell_ov"] = (d[6] >> 7) & 1
        o["cell_uv"] = (d[6] >> 6) & 1
        raw = d[2] | ((d[1] & 0xF) << 8)
        o["chg_max"] = None if raw >= 0xFFE else raw * 0.25
    elif aid == 0x430 and len(d) >= 8:
        rvx = d[1] | ((d[0] & 0x1F) << 8)
        rvn = d[3] | ((d[2] & 0x1F) << 8)
        o["vmax"] = None if rvx >= 0x1FFE else rvx
        o["vmin"] = None if rvn >= 0x1FFE else rvn
        o["tmax"] = None if d[4] >= 0xFE else d[4] * 0.5 - 40.0
        o["lvbat"] = None if d[7] >= 0xFE else d[7] * 0.1
    elif aid == 0x440 and len(d) >= 7:
        o["mainc"] = (d[0] >> 2) & 0xF
        rp = (d[4] << 4) | (d[5] >> 4)
        rn = d[6] | ((d[5] & 0xF) << 8)
        o["vbus_p"] = None if rp >= 0xFFE else rp * 0.25
        o["vbus_n"] = None if rn >= 0xFFE else rn * 0.25 - 500.0
    elif aid == 0x592 and len(d) >= 1:
        o["ign"] = (d[0] >> 4) & 1
        o["evse_sw"] = (d[0] >> 1) & 1
    return o


SESSIONS = {
    "M0_b (pre-swap)": sorted(glob.glob("projects/vtrux/logs/actual-failed-charges/truklog_M0_T*.log"),
                              key=lambda p: int(re.search(r"_T(\d+)", p).group(1))),
    "M1_b (pre-swap)": sorted(glob.glob("projects/vtrux/logs/actual-failed-charges/truklog_M1_T*.log"),
                              key=lambda p: int(re.search(r"_T(\d+)", p).group(1))),
    "2025-08-22 full-charge-then-fail": ["projects/vtrux/logs/full-charge-then-fail.log"],
}

for name, paths in SESSIONS.items():
    print("=" * 112)
    print("  %s   (%d file%s)" % (name, len(paths), "s" if len(paths) > 1 else ""))
    print("=" * 112)
    if not paths:
        print("  no files found\n")
        continue

    st = {}
    hist = []
    escal = []
    prev_alarm = None
    t1_t = None
    for t, aid, d, fn in frames(paths):
        f = decode(aid, d)
        if not f:
            continue
        st.update({k: v for k, v in f.items() if v is not None})
        hist.append((t, dict(st), fn))
        if "alarm" in f:
            a = f["alarm"]
            if prev_alarm is not None and a != prev_alarm:
                if a == 1 and prev_alarm == 0:
                    t1_t = t
                elif a == 3 and prev_alarm == 1 and t1_t is not None:
                    escal.append((t1_t, t, fn))
                    t1_t = None
            prev_alarm = a

    print("  duration %.0fs   samples %d" % (hist[-1][0] if hist else 0, len(hist)))
    print("  NONE->TYPE1->TYPE3 escalations found: %d" % len(escal))
    print()
    for t1, t3, fn in escal:
        print("  " + "-" * 108)
        print("  ESCALATION   TYPE1 at t=%.3f  ->  TYPE3+EPO at t=%.3f   GAP = %.3f s   [%s]"
              % (t1, t3, t3 - t1, fn))
        print("  " + "-" * 108)
        # state at TYPE1 onset vs 30s before
        def near(tt):
            best = None
            for h in hist:
                if h[0] <= tt:
                    best = h
                else:
                    break
            return best
        a = near(t1 - 30.0)
        b = near(t1 + 0.5)
        c = near(t3 + 0.5)
        print("     %-14s %-16s %-16s %-16s" % ("signal", "T1-30s", "at TYPE1", "at TYPE3"))
        for k in ("mainc", "alarm", "epo", "hvil", "on_plug", "chgc", "evse_sw",
                  "ibat", "vbat", "vbus_p", "vbus_n", "iso_r", "cell_ov", "cell_uv",
                  "chg_max", "vmax", "vmin", "tmax", "lvbat"):
            def fmt(h):
                if not h or k not in h[1]:
                    return "-"
                v = h[1][k]
                if k == "mainc":
                    return MAINC[v]
                if k == "alarm":
                    return ALARM[v]
                if k == "chgc":
                    return CHGC.get(v, str(v))
                if isinstance(v, float):
                    return "%.2f" % v
                return str(v)
            va, vb, vc = fmt(a), fmt(b), fmt(c)
            flag = "  <== CHANGED at TYPE1" if va != vb else ""
            print("     %-14s %-16s %-16s %-16s%s" % (k, va, vb, vc, flag))
        print()
        # HVIL / unplug check
        print("     --- events in window T1-5s .. T3+15s ---")
        pv = {}
        for t, s, fn2 in hist:
            if not (t1 - 5 <= t <= t3 + 15):
                continue
            for k in ("mainc", "alarm", "epo", "hvil", "on_plug", "chgc", "evse_sw"):
                if k in s and pv.get(k) != s[k]:
                    if pv.get(k) is not None:
                        v = s[k]
                        vs = MAINC[v] if k == "mainc" else (ALARM[v] if k == "alarm" else
                                                            (CHGC.get(v, v) if k == "chgc" else v))
                        print("        t=%9.3f  %-9s -> %s   (T1%+.2f, T3%+.2f)"
                              % (t, k, vs, t - t1, t - t3))
                    pv[k] = s[k]
        print()
