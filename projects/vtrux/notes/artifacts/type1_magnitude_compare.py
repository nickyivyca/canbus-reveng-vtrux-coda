"""Is the TYPE1 -> TYPE3 escalation delay magnitude-dependent?

Five steady-state charge escalations are known. Four cluster at 10.165-10.259 s
(94 ms spread); truklog_M2 trips at 8.810 s -- 1.36 s early, with no data loss
(0x410 at 20.1 Hz, max inter-frame gap 54 ms through the window).

If the delay is a fixed firmware debounce, nothing should distinguish M2.
If it is an integrator / magnitude-dependent countdown, M2 should sit at an extreme
of whatever the BMS is actually measuring.

This dumps every measurable BMS quantity at the TYPE1 instant for all five, plus the
trend over the preceding 5 minutes, and ranks M2 against the cluster.

All decodes taken from tools/diagnose_vtrux.py.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/type1_magnitude_compare.py
"""
import sys
import os
import re
import glob

sys.path.insert(0, ".")

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
IDS = {0x410, 0x411, 0x420, 0x430, 0x440}
MAINC_CLOSED = {11, 12}


def chunks(pattern, prefix_filter=None):
    """Largest copy of each basename, ordered by _T number."""
    cand = {}
    for p in glob.glob(pattern, recursive=True):
        n = os.path.basename(p)
        if prefix_filter and not n.startswith(prefix_filter):
            continue
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue
        if n not in cand or sz > cand[n][1]:
            cand[n] = (p, sz)
    def tnum(n):
        m = re.search(r"_T(\d+)", n)
        return int(m.group(1)) if m else 0
    return [v[0] for k, v in sorted(cand.items(), key=lambda kv: tnum(kv[0]))]


SESSIONS = {
    "truklog_M0  (10.213s)": chunks("projects/vtrux/logs/**/truklog_M0_T*.log", "truklog"),
    "truklog_M1  (10.259s)": chunks("projects/vtrux/logs/**/truklog_M1_T*.log", "truklog"),
    "truklog_M2  ( 8.810s)": chunks("projects/vtrux/logs/**/truklog_M2_T*.log", "truklog"),
    "debuglog_M3 (10.165s)": chunks("projects/vtrux/logs/**/debuglog_M3_T*.log", "debuglog"),
    "2025-08-22  (10.212s)": ["projects/vtrux/logs/full-charge-then-fail.log"],
}


def stream(paths):
    base = 0.0
    last = 0.0
    for p in paths:
        first = None
        try:
            fh = open(p, "r", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
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
                try:
                    d = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
                if first is None:
                    first = t
                    base = last
                tt = base + (t - first)
                if tt < last:
                    tt = last
                last = max(last, tt)
                yield tt, aid, d


def collect(paths):
    st = {}
    hist = []
    t1 = t3 = None
    prev_alarm = None
    charge_start = None
    for t, aid, d in stream(paths):
        if aid == 0x410 and len(d) >= 8:
            st["alarm"] = (d[1] >> 6) & 3
            raw = (d[4] << 8) | d[5]
            st["ibat"] = None if (raw & 0xFFFE) == 0xFFFE else raw * 0.025 - 1000.0
            rv = d[7] | ((d[6] & 0xF) << 8)
            st["vbat"] = None if rv >= 0xFFE else rv * 0.25
            rg = d[2] | ((d[1] & 0xF) << 8)
            st["gfd"] = None if rg >= 0xFFE else rg * 0.25
            st["soc_int"] = None if d[3] >= 0xFE else d[3] * 0.5
            a = st["alarm"]
            if prev_alarm is not None and a != prev_alarm:
                if a == 1 and prev_alarm == 0 and t1 is None:
                    t1 = t
                elif a == 3 and prev_alarm == 1 and t1 is not None and t3 is None:
                    t3 = t
            prev_alarm = a
        elif aid == 0x411 and len(d) >= 2:
            r = d[0] * 64 + (d[1] >> 2)
            st["soc"] = None if r >= 0x3FFE else r / 100.0
        elif aid == 0x420 and len(d) >= 7:
            st["iso_r"] = d[3]
            r = d[2] | ((d[1] & 0xF) << 8)
            st["chg_max"] = None if r >= 0xFFE else r * 0.25
            st["cell_ov"] = (d[6] >> 7) & 1
        elif aid == 0x430 and len(d) >= 8:
            rx = d[1] | ((d[0] & 0x1F) << 8)
            rn = d[3] | ((d[2] & 0x1F) << 8)
            st["vmax"] = None if rx >= 0x1FFE else rx
            st["vmin"] = None if rn >= 0x1FFE else rn
            if st.get("vmax") and st.get("vmin"):
                st["spread"] = st["vmax"] - st["vmin"]
            st["tmax"] = None if d[4] >= 0xFE else d[4] * 0.5 - 40.0
            st["tmin"] = None if d[5] >= 0xFE else d[5] * 0.5 - 40.0
            st["lvbat"] = None if d[7] >= 0xFE else d[7] * 0.1
        elif aid == 0x440 and len(d) >= 7:
            m2 = (d[0] >> 2) & 0xF
            st["mainc"] = m2
            if m2 in MAINC_CLOSED and charge_start is None:
                charge_start = t
            rp = (d[4] << 4) | (d[5] >> 4)
            st["vbus_p"] = None if rp >= 0xFFE else rp * 0.25
        hist.append((t, dict(st)))
        if t3 is not None and t > t3 + 2:
            break
    return hist, t1, t3, charge_start


FIELDS = ["ibat", "vbat", "soc", "soc_int", "vmax", "vmin", "spread", "tmax", "tmin",
          "lvbat", "gfd", "iso_r", "chg_max", "cell_ov", "vbus_p"]

rows = {}
for name, paths in SESSIONS.items():
    if not paths:
        print("%-22s NO FILES" % name)
        continue
    print("scanning %-22s (%d chunks)..." % (name, len(paths)), flush=True)
    hist, t1, t3, cs = collect(paths)
    if t1 is None or t3 is None:
        print("   no escalation found")
        continue

    def at(tt):
        best = None
        for h in hist:
            if h[0] <= tt:
                best = h
            else:
                break
        return best[1] if best else {}

    s_at = at(t1)
    s_5m = at(t1 - 300)
    rows[name] = {
        "gap": t3 - t1,
        "t1": t1,
        "into_charge": (t1 - cs) if cs is not None else None,
        "at": s_at,
        "prev": s_5m,
    }

print()
print("=" * 122)
print("  STATE AT THE TYPE1 INSTANT -- five escalations")
print("=" * 122)
order = sorted(rows, key=lambda k: rows[k]["gap"])
print("  %-14s " % "field" + "".join("%-21s" % k.split("(")[0].strip() for k in order))
print("  %-14s " % "gap (s)" + "".join("%-21.3f" % rows[k]["gap"] for k in order))
print("  %-14s " % "min into chg" + "".join(
    "%-21s" % (("%.1f" % (rows[k]["into_charge"] / 60)) if rows[k]["into_charge"] else "?")
    for k in order))
print("  " + "-" * 118)
for f in FIELDS:
    line = "  %-14s " % f
    for k in order:
        v = rows[k]["at"].get(f)
        line += "%-21s" % (("%.2f" % v) if isinstance(v, float) else str(v))
    print(line)

print()
print("=" * 122)
print("  CHANGE OVER THE 5 MINUTES BEFORE TYPE1  (value_at_T1 - value_5min_earlier)")
print("=" * 122)
print("  %-14s " % "field" + "".join("%-21s" % k.split("(")[0].strip() for k in order))
print("  " + "-" * 118)
for f in FIELDS:
    line = "  %-14s " % f
    for k in order:
        a = rows[k]["at"].get(f)
        b = rows[k]["prev"].get(f)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            line += "%-21s" % ("%+.2f" % (a - b))
        else:
            line += "%-21s" % "-"
    print(line)

print()
print("=" * 122)
print("  IS M2 AN OUTLIER?  (rank of truklog_M2 among the five, per field)")
print("=" * 122)
m2 = [k for k in rows if "M2" in k]
if m2:
    m2 = m2[0]
    for f in FIELDS:
        vals = [(k, rows[k]["at"].get(f)) for k in rows
                if isinstance(rows[k]["at"].get(f), (int, float))]
        if len(vals) < 3:
            continue
        vals.sort(key=lambda kv: kv[1])
        names = [k for k, _v in vals]
        if m2 not in names:
            continue
        i = names.index(m2)
        tag = ""
        if i == 0:
            tag = "  <== LOWEST of %d" % len(vals)
        elif i == len(vals) - 1:
            tag = "  <== HIGHEST of %d" % len(vals)
        print("  %-12s M2=%-10s rank %d/%d   range %.2f .. %.2f%s"
              % (f, "%.2f" % rows[m2]["at"][f], i + 1, len(vals),
                 vals[0][1], vals[-1][1], tag))
