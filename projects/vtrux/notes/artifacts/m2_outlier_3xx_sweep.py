"""Extend the M2-outlier byte sweep DOWN into 0x300-0x3FF.

m2_outlier_bytewise.py covered 0x400-0x5FF and concluded "the trigger is not in the
broadcast set". That conclusion had a hole: it excluded 0x370-0x375, the pack SECTION
boards, which can-disconnect.md T2 confirms are pack-sourced (they drop when the HV
battery LV connector is pulled). Those are precisely where a pack-internal condition
would be telemetered, if it is telemetered at all.

Same three passes as the 0x400-0x5FF sweep, over 0x300-0x3FF:
  presence / value at TYPE1 / bytes moving during the TYPE1->TYPE3 countdown.

Note truklog_M2_T8 is excluded -- it is a 2025-05-20 capture, 36 days before
T14..T21 (2025-06-25), and is not part of this session. See detect_capture_sessions().

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/m2_outlier_3xx_sweep.py
"""
import sys
import os
import re
import glob

sys.path.insert(0, ".")

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
LO, HI = 0x300, 0x3FF


def chunks(pattern, prefix, only=None):
    c = {}
    for p in glob.glob(pattern, recursive=True):
        n = os.path.basename(p)
        if not n.startswith(prefix):
            continue
        if only is not None and not any(("_T%d." % t) in n for t in only):
            continue
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue
        if n not in c or sz > c[n][1]:
            c[n] = (p, sz)
    return [v[0] for k, v in sorted(c.items(),
            key=lambda kv: int(re.search(r"_T(\d+)", kv[0]).group(1)))]


SESSIONS = {
    "M2": chunks("projects/vtrux/logs/other-logs/truklog_M2_T*.log", "truklog", range(14, 22)),
    "M0": chunks("projects/vtrux/logs/**/truklog_M0_T*.log", "truklog"),
    "M1": chunks("projects/vtrux/logs/**/truklog_M1_T*.log", "truklog"),
    "M3": chunks("projects/vtrux/logs/**/debuglog_M3_T*.log", "debuglog"),
    "0822": ["projects/vtrux/logs/full-charge-then-fail.log"],
}
CLUSTER = ["M0", "M1", "M3", "0822"]


def run(paths):
    base = last = 0.0
    latest = {}
    prev = None
    t1 = t3 = None
    snap = None
    win = {}
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
                hh, mi, ss, tk, idh, _d, rest = m.groups()
                aid = int(idh, 16)
                if not ((LO <= aid <= HI) or aid == 0x410):
                    continue
                t = int(hh) * 3600 + int(mi) * 60 + int(ss) + int(tk) / 10000.0
                if first is None:
                    first = t
                    base = last
                tt = base + (t - first)
                if tt < last:
                    tt = last
                last = max(last, tt)
                try:
                    d = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
                if LO <= aid <= HI:
                    latest[aid] = d
                    if t1 is not None and t3 is None:
                        win.setdefault(aid, set()).add(d)
                elif len(d) >= 2:
                    a = (d[1] >> 6) & 3
                    if prev is not None and a != prev:
                        if a == 1 and prev == 0 and t1 is None:
                            t1 = tt
                            snap = dict(latest)
                        elif a == 3 and prev == 1 and t1 is not None and t3 is None:
                            t3 = tt
                    prev = a
                if t3 is not None:
                    return snap or {}, win, t1, t3
    return snap or {}, win, t1, t3


R = {}
for k, v in SESSIONS.items():
    print("scanning %-5s (%d chunks)..." % (k, len(v)), flush=True)
    R[k] = run(v)

print()
print("=" * 104)
print("  0x300-0x3FF AT TYPE1  (range EXCLUDED from the earlier 0x400-0x5FF sweep)")
print("=" * 104)
ids = sorted(set(R["M2"][0]) | set().union(*[set(R[c][0]) for c in CLUSTER]))
print("  IDs present anywhere: %s" % " ".join("0x%03X" % i for i in ids))
print()
n_uni = n_out = 0
for aid in ids:
    missing = [c for c in ["M2"] + CLUSTER if aid not in R[c][0]]
    if missing:
        print("  0x%03X  PRESENCE DIFFERS -- absent in: %s" % (aid, ", ".join(missing)))
        continue
    pm = R["M2"][0][aid]
    ln = min([len(pm)] + [len(R[c][0][aid]) for c in CLUSTER])
    for b in range(ln):
        v = pm[b]
        o = [R[c][0][aid][b] for c in CLUSTER]
        if len(set(o)) == 1 and v == o[0]:
            continue
        uni = all(v != x for x in o)
        out = v < min(o) or v > max(o)
        if uni:
            n_uni += 1
        if uni and out:
            n_out += 1
        tag = "M2 UNIQUE + OUTSIDE" if (uni and out) else ("M2 unique, inside" if uni else "")
        print("  0x%03X.B%-4d M2=%-4s cluster=%-24s %s"
              % (aid, b, "%02X" % v, " ".join("%02X" % x for x in o), tag))
print()
print("  --> %d M2-unique bytes, %d of them outside the cluster range" % (n_uni, n_out))

print()
print("=" * 104)
print("  DYNAMICS in 0x300-0x3FF during the TYPE1->TYPE3 countdown")
print("=" * 104)
for k in ["M2"] + CLUSTER:
    snap, win, t1, t3 = R[k]
    mv = []
    for aid, ps in sorted(win.items()):
        if len(ps) < 2:
            continue
        ln = min(len(p) for p in ps)
        for b in range(ln):
            nv = len(set(p[b] for p in ps))
            if nv > 1:
                mv.append("0x%03X.B%d(%d)" % (aid, b, nv))
    print("  %-5s gap=%.3fs  %d moving bytes: %s"
          % (k, (t3 - t1) if (t1 and t3) else -1, len(mv), ", ".join(mv) if mv else "(none)"))
