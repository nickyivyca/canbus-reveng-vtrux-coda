"""vcu_top_of_charge.py -- what the VCU's page-01 current setpoint does at the
top of a charge, joined to the BMS, on the main truck's genuine tops of charge
and vtrux_charge_M1 (reviewer fork, 2026-10-10). The parts-truck version is
phase 3 of partstruck_top_of_charge.py.

Inputs:
  vcu_top_of_charge_raw_<session>.txt -- from vcu_top_of_charge_raw.py (run on
      the Linux box), every change of page 00 (flow, mode) and page 01
      (Ilim, Vlim) of 0x18EFC000, absolute epoch seconds on Influx's time base.
  InfluxDB canbus-data `signals`, powertrain, bounded by the session's
      upload_manifest window (tools/tools.md, the 2026-09-27 outage rule).

Alignment check: the raw log's page-00 mode 1 -> 3 and Influx's chgcmd_mode
1 -> 3 must coincide; every such transition is listed from both sources.

Output: vcu_top_of_charge_<session>.txt, 20 s bins from LP-2400 s to LP+300 s
(LP = the last Low Power at bms_soc_hires >= 95), plus event lines.
"""
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "projects/vtrux/notes/artifacts")
import bisect

from partstruck_top_of_charge import influx

ART = "projects/vtrux/notes/artifacts/"
SESSIONS = {"charge_M0": "charge_M0", "full-charge-then-fail": "fctf",
            "vtrux_20260503_192242": "s0503", "vtrux_charge_M1": "m1"}
F = ["bcm_chg_max", "bcm_ibat", "bcm_cell_vmax", "bcm_cell_vmin",
     "bms_soc_hires", "chgcmd_mode", "BELINV_hvBatteryCurrent",
     "DCDC_LV_Curr", "DCDC_LV_Volt", "bcm_epo", "bcm_alarm",
     "bcm_cell_overvolt", "bcm_fault_mon", "bcm_chg_done", "bcm_ready"]
FLAGS = ["bcm_epo", "bcm_alarm", "bcm_cell_overvolt", "bcm_fault_mon",
         "bcm_chg_done", "bcm_ready"]


def manifest(session):
    cols, rows = influx("SELECT uploaded_at, file, t_start_ns, t_end_ns FROM "
                        "upload_manifest WHERE \"vehicle\"='vtrux' AND "
                        "\"session\"='%s'" % session)
    newest = {}
    for v in rows:
        r = dict(zip(cols, v))
        f, ua = r.get("file"), r.get("uploaded_at") or 0
        if f not in newest or ua > newest[f][0]:
            newest[f] = (ua, r)
    return (min(r["t_start_ns"] for _u, r in newest.values()) // 10**6,
            max(r["t_end_ns"] for _u, r in newest.values()) // 10**6)


def grid(session):
    m0, m1 = manifest(session)
    sel = ", ".join('"%s"' % f for f in F)
    cols, rows = influx("SELECT %s FROM signals WHERE vehicle='vtrux' AND "
                        "session='%s' AND bus='powertrain' AND time >= %dms "
                        "AND time < %dms" % (sel, session, m0, m1 + 1000))
    rows.sort(key=lambda r: r[0])
    idx = {c: i for i, c in enumerate(cols)}
    cur = dict.fromkeys(F)
    g = []
    k = 0
    t0 = m0 // 1000
    modes = []
    for s in range(t0, m1 // 1000 + 1):
        while k < len(rows) and rows[k][0] <= s * 1000:
            r = rows[k]
            for f in F:
                v = r[idx[f]]
                if v is not None:
                    if f == "chgcmd_mode" and v != cur[f]:
                        modes.append((r[0] / 1000.0, cur[f], v))
                    cur[f] = v
            k += 1
        g.append(dict(cur))
    return t0, g, modes


def load_raw(tag):
    p00, p01 = [], []
    with open(ART + "vcu_top_of_charge_raw_%s.txt" % tag) as f:
        for line in f:
            if line.startswith("#"):
                continue
            q = line.split()
            t = float(q[0])
            kv = dict(x.split("=") for x in q[2:4])
            if q[1] == "p00":
                p00.append((t, int(kv["flow"]), int(kv["mode"])))
            else:
                p01.append((t, float(kv["ilim"]), float(kv["vlim"])))
    return p00, p01


def run(session, tag):
    t0, g, modes = grid(session)
    p00, p01 = load_raw(tag)
    out = ["%s: %d s stored from epoch %d" % (session, len(g), t0)]
    # alignment: raw mode transitions vs Influx chgcmd_mode transitions
    raw_tr = []
    for i in range(1, len(p00)):
        if p00[i][2] != p00[i - 1][2]:
            raw_tr.append((p00[i][0], p00[i - 1][2], p00[i][2]))
    out.append("mode transitions, raw (epoch, from->to) vs Influx:")
    for t, a, b in raw_tr:
        near = min(modes, key=lambda m: abs(m[0] - t)) if modes else None
        out.append("  raw %.2f %s->%s | influx %s" % (
            t, a, b, "%.2f %s->%s (d=%+.2f s)" % (near[0], near[1], near[2],
                                                  near[0] - t)
            if near else "-"))
    lp = None
    for s in range(1, len(g)):
        if g[s]["chgcmd_mode"] == 3 and g[s - 1]["chgcmd_mode"] != 3 \
                and (g[s]["bms_soc_hires"] or 0) >= 95:
            lp = s
    if lp is None:
        out.append("no Low Power at SoC >= 95")
        lp = len(g) - 1
    out.append("LP at t=%d (epoch %d)" % (lp, t0 + lp))
    pt = [x[0] for x in p01]

    def setpt(ep):
        i = bisect.bisect_right(pt, ep) - 1
        return p01[i][1] if i >= 0 else None

    # flags during setpoint > chg_max
    above = [s for s in range(0, lp)
             if g[s]["bcm_chg_max"] is not None and setpt(t0 + s) is not None
             and setpt(t0 + s) > g[s]["bcm_chg_max"] + 0.5
             and g[s]["chgcmd_mode"] == 1]
    if above:
        out.append("setpoint > chg_max + 0.5 A in mode 1: %d s (first t=%d)"
                   % (len(above), above[0]))
        for fl in FLAGS:
            vals = sorted(set(g[s][fl] for s in above))
            out.append("  %s values while above: %s" % (fl, vals))
    out.append(" t_rel  t-LP  setpt (min-max)   vlim   chgmax  soc     vmax  "
               "vmin   ibat   Idc   P12  mode")
    for b0 in range(max(0, lp - 2400), min(len(g), lp + 300), 20):
        sp = []
        vl = None
        for s in range(b0, min(len(g), b0 + 20)):
            v = setpt(t0 + s)
            if v is not None:
                sp.append(v)
            i = bisect.bisect_right(pt, t0 + s) - 1
            if i >= 0:
                vl = p01[i][2]
        rows = g[b0:b0 + 20]
        m = lambda f: sum(r[f] for r in rows if r[f] is not None) / max(
            1, sum(1 for r in rows if r[f] is not None))
        out.append("%6d %5d  %5.2f (%5.2f-%5.2f) %6.1f  %6.2f  %6.2f  %.3f  "
                   "%.3f  %5.2f  %5.2f  %4.0f  %s" % (
                       b0, b0 - lp, sum(sp) / len(sp) if sp else -1,
                       min(sp) if sp else -1, max(sp) if sp else -1,
                       vl or -1, m("bcm_chg_max"), m("bms_soc_hires"),
                       m("bcm_cell_vmax"), m("bcm_cell_vmin"), m("bcm_ibat"),
                       -m("BELINV_hvBatteryCurrent"),
                       m("DCDC_LV_Curr") * m("DCDC_LV_Volt"),
                       rows[-1]["chgcmd_mode"]))
    text = "\n".join(out) + "\n"
    with open(ART + "vcu_top_of_charge_%s.txt" % tag, "w") as f:
        f.write(text)
    return text


if __name__ == "__main__" and not (len(sys.argv) > 1 and sys.argv[1] == "summary"):
    for s in (sys.argv[1:] or SESSIONS):
        print(run(s, SESSIONS[s]))


# ---------------------------------------------------------------------------
# Summary phase: per session, 1 s resolution.
#  - cap: first second the setpoint leaves its CC value for ~12.5 A or lower
#  - taper: mean setpoint per 5 mV bin of bcm_cell_vmax, mode 1, chg_max
#    <= 12 A, setpoint between 6.4 and 12.4 A (the proportional part)
#  - floor: median setpoint over the 120 s before the cut
#  - cut: first second after the floor where the setpoint < floor - 0.3 A;
#    vmax there; Low Power delay from the cut, values at the Low Power
OUT_S = ART + "vcu_top_of_charge_summary.txt"


def summary(session, tag):
    t0, g, _m = grid(session)
    _p00, p01 = load_raw(tag)
    pt = [x[0] for x in p01]

    def sp(s):
        i = bisect.bisect_right(pt, t0 + s) - 1
        return p01[i][1] if i >= 0 else None

    lp = None
    for s in range(1, len(g)):
        if g[s]["chgcmd_mode"] == 3 and g[s - 1]["chgcmd_mode"] != 3 \
                and (g[s]["bms_soc_hires"] or 0) >= 95:
            lp = s
    out = ["", "== %s  LP t=%s" % (session, lp)]
    if lp is None:
        return out
    # CC value: median setpoint over LP-6000..LP-3000 in mode 1
    cc = sorted(sp(s) for s in range(max(0, lp - 6000), max(1, lp - 3000))
                if sp(s) is not None and g[s]["chgcmd_mode"] == 1)
    ccv = cc[len(cc) // 2] if cc else None
    cap = next((s for s in range(max(0, lp - 6000), lp)
                if sp(s) is not None and ccv and sp(s) <= 12.65
                and ccv > 13 and all(sp(x) <= 12.65 for x in range(s, s + 30))),
               None)
    out.append("CC setpoint (median LP-6000..-3000) %s" % ccv)
    if cap is not None:
        r = g[cap]
        out.append("left CC for <=12.65 A at t=%d (LP%+d): setpt %.2f soc %.2f "
                   "chgmax %.2f vmax %.3f ibat %.2f Idc %.2f" % (
                       cap, cap - lp, sp(cap), r["bms_soc_hires"],
                       r["bcm_chg_max"], r["bcm_cell_vmax"], r["bcm_ibat"],
                       -r["BELINV_hvBatteryCurrent"]))
    bins = {}
    for s in range(max(0, lp - 6000), lp):
        v, r = sp(s), g[s]
        if v is None or r["chgcmd_mode"] != 1 or r["bcm_chg_max"] is None:
            continue
        if r["bcm_chg_max"] <= 12 and 6.4 <= v <= 12.4:
            b = int(r["bcm_cell_vmax"] * 200) / 200.0
            bins.setdefault(b, []).append(v)
    out.append("taper: vmax bin -> mean setpoint (n s)")
    for b in sorted(bins):
        out.append("  %.3f  %5.2f  (%d)" % (b, sum(bins[b]) / len(bins[b]),
                                            len(bins[b])))
    # floor and cut
    fl_s = next((s for s in range(lp - 1500, lp)
                 if sp(s) is not None and all(sp(x) < 6.8 for x in
                                              range(s, s + 20))), None)
    if fl_s is not None:
        cut = next((s for s in range(fl_s, lp)
                    if sp(s) < min(sp(x) for x in range(fl_s, fl_s + 20)) - 0.3),
                   None)
        fv = sorted(sp(x) for x in range(max(fl_s, (cut or lp) - 120),
                                         (cut or lp)))
        out.append("floor from t=%d (LP%+d): median %.2f A, vmax at start %.3f, "
                   "P12 %.0f W" % (fl_s, fl_s - lp, fv[len(fv) // 2],
                                   g[fl_s]["bcm_cell_vmax"],
                                   g[fl_s]["DCDC_LV_Curr"]
                                   * g[fl_s]["DCDC_LV_Volt"]))
        if cut is not None:
            vpre = max(g[x]["bcm_cell_vmax"] for x in range(cut - 5, cut + 1))
            out.append("cut at t=%d (LP%+d): vmax %.3f (max of prior 5 s "
                       "%.3f), setpt %.2f" % (cut, cut - lp,
                                              g[cut]["bcm_cell_vmax"], vpre,
                                              sp(cut)))
            out.append("  1 s trace from cut-10 to LP+5 (t, setpt, vmax, ibat, "
                       "Idc, mode):")
            for s in range(cut - 10, lp + 6, 5):
                r = g[s]
                out.append("   %6d %5.2f %.3f %5.2f %5.2f %s" % (
                    s - lp, sp(s), r["bcm_cell_vmax"], r["bcm_ibat"],
                    -r["BELINV_hvBatteryCurrent"], r["chgcmd_mode"]))
    # flags over the whole mode-1 charge vs while above chg_max
    for fl in FLAGS:
        allv = sorted(set(g[s][fl] for s in range(0, lp)
                          if g[s]["chgcmd_mode"] == 1))
        out.append("  %s values over the mode-1 charge: %s" % (fl, allv))
    return out


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "summary":
    lines = []
    for s, tag in SESSIONS.items():
        lines += summary(s, tag)
    with open(OUT_S, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
