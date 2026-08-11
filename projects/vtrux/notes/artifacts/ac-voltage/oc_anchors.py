"""Per-EVSE-bucket open-circuit anchors for the Vtrux.

For each outlet (capture event x J1772 pilot-advertised current) find the LOWEST
current at which the charger reported a valid AC voltage, and the voltage there.
That reading is the best empirical stand-in for the supply's open-circuit
voltage: no extrapolation, no fitted intercept.

This matters because assuming a nominal open-circuit voltage (e.g. "the EVSE is
about 200 V") and back-computing resistance from a loaded reading gives a wrong
and current-dependent answer. Measuring near 0 A removes the assumption.

Charge shutdowns ("load dumps") are the ideal case: current falls to 0 A while
the charger is still reporting, giving a directly measured open circuit.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/ac-voltage/oc_anchors.py
"""
import os, re, sys
from collections import defaultdict, Counter
sys.path.insert(0, ".")

ART = "projects/vtrux/notes/artifacts/ac-voltage"
AC = [os.path.join(ART, "raw_primary.txt"), os.path.join(ART, "raw_android.txt")]
PILOT = os.path.join(ART, "raw_pilot.txt")

AC_RE = re.compile(r"^(?P<path>.+?):\d{2}:\d{2}:\d{2}:\d{4}\s+\S+\s+\d+\s+"
                   r"0x18FFD7C0\s+x\s+8\s+(?P<d>(?:[0-9A-Fa-f]{2}\s+){7}[0-9A-Fa-f]{2})")
PI_RE = re.compile(r"^(?P<path>.+?):\d{2}:\d{2}:\d{2}:\d{4}\s+\S+\s+\d+\s+"
                   r"0x18FFD8C0\s+x\s+8\s+(?P<d>(?:[0-9A-Fa-f]{2}\s+){7}[0-9A-Fa-f]{2})")
CHUNK = re.compile(r"_T\d+\.log$", re.IGNORECASE)


def pct(v, p):
    if not v:
        return float("nan")
    k = (len(v) - 1) * p
    lo = int(k); hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def cap(path):
    b = os.path.basename(path)
    return CHUNK.sub("", b) or b


def main():
    pilot = defaultdict(Counter)
    for line in open(PILOT, errors="replace"):
        m = PI_RE.match(line)
        if not m:
            continue
        duty = [int(x, 16) for x in m.group("d").split()][2]
        if 10 <= duty <= 85:
            pilot[cap(m.group("path"))][duty] += 1
    adv = {k: c.most_common(1)[0][0] * 0.6 for k, c in pilot.items()}

    # outlet -> list of (I, V); keep everything, including near-zero current
    out = defaultdict(list)
    for p in AC:
        for line in open(p, errors="replace"):
            m = AC_RE.match(line)
            if not m:
                continue
            b = [int(x, 16) for x in m.group("d").split()]
            v = (b[4] | (b[5] << 8)) * 0.05
            i = (b[6] | (b[7] << 8)) * 0.05
            if not (60.0 <= v <= 300.0 and 0.0 <= i <= 60.0):
                continue
            c = cap(m.group("path"))
            out[(c, round(adv.get(c, 0.0), 1))].append((i, v))

    rows = []
    for (c, a), pts in out.items():
        if len(pts) < 20:
            continue
        bins = defaultdict(list)
        for i, v in pts:
            bins[round(i / 0.5)].append(v)
        lo = None
        for b in sorted(bins):
            if len(bins[b]) >= 3:
                lo = (b * 0.5, sorted(bins[b]))
                break
        if lo is None:
            continue
        i_lo, vs = lo
        v_anchor = pct(vs, 0.95)
        hi_i = max(p[0] for p in pts)
        hi_v = pct(sorted(v for i, v in pts if i >= hi_i - 1.0), 0.5)
        r = (v_anchor - hi_v) / (hi_i - i_lo) if hi_i - i_lo > 3 else None
        rows.append({"cap": c, "adv": a, "i_lo": i_lo, "v_anchor": v_anchor,
                     "n_lo": len(vs), "i_hi": hi_i, "v_hi": hi_v, "r": r,
                     "n": len(pts)})

    def cls(v):
        return 240 if v >= 228 else (208 if v >= 196 else 190)

    bkt = defaultdict(list)
    for r in rows:
        bkt[(cls(r["v_anchor"]), r["adv"])].append(r)

    print("=" * 112)
    print("OPEN-CIRCUIT ANCHORS PER EVSE BUCKET")
    print("min I = lowest current with >=3 valid samples; V@minI = p95 voltage there")
    print("=" * 112)
    print("%-9s %-9s %8s %8s %10s %9s %9s %9s %9s"
          % ("supply", "EVSE adv", "outlets", "min I A", "V @ minI", "max I A",
             "V @ maxI", "drop V", "R ohm"))
    for k in sorted(bkt, key=lambda x: (-x[0], x[1])):
        g = bkt[k]
        i_lo = min(r["i_lo"] for r in g)
        best = [r for r in g if r["i_lo"] == i_lo]
        v_at = max(r["v_anchor"] for r in best)
        i_hi = max(r["i_hi"] for r in g)
        v_hi = pct(sorted(r["v_hi"] for r in g if r["i_hi"] >= i_hi - 1.5), 0.5)
        rs = sorted(r["r"] for r in g if r["r"])
        print("%-9s %-9s %8d %8.1f %10.1f %9.1f %9.1f %9.2f %9s"
              % ("%d V" % k[0], "%.0f A" % k[1] if k[1] else "unknown", len(g),
                 i_lo, v_at, i_hi, v_hi, v_at - v_hi,
                 "%.3f" % pct(rs, 0.5) if rs else "-"))

    print("\nOutlets with a near-zero-current reading (best anchors):")
    for r in sorted(rows, key=lambda x: x["i_lo"])[:12]:
        print("  %-34s adv %5.1f A | %4.1f A -> %6.1f V (n=%d) | %5.1f A -> %6.1f V | R %s"
              % (r["cap"][:34], r["adv"], r["i_lo"], r["v_anchor"], r["n_lo"],
                 r["i_hi"], r["v_hi"], "%.3f" % r["r"] if r["r"] else "-"))


if __name__ == "__main__":
    main()
