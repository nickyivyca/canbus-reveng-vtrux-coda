"""Corpus-wide range and distribution of the Vtrux throttle/pedal signals in InfluxDB.

Answers: what range does Accelerator_Actual_Position actually cover across the
entire upload history, and how is it distributed -- in particular, is the
~65-66% per-session ceiling seen in sample sessions a real ceiling, or do some
sessions reach full scale?

Caveat (per data-sources.md): InfluxDB point counts are NOT frame counts. The
write policy is on-change plus a 1 s heartbeat, so these distributions are
biased toward values that persist, not toward values that occur often. Good for
"what range is reached"; not valid for "what fraction of driving time".
"""
import json
import subprocess
import urllib.parse

INFLUX = "http://localhost:8086/query"
AUTH = "claude:claude"
DB = "canbus-data"

SIGNALS = [
    "Accelerator_Actual_Position",
    "Accelerator_Effective_Position",
    "Throttle_Position",
]


def q(query):
    args = [
        "curl", "-s", "-G", INFLUX, "-u", AUTH,
        "--data-urlencode", "db=" + DB,
        "--data-urlencode", "q=" + query,
    ]
    out = subprocess.run(args, capture_output=True, text=True).stdout
    return json.loads(out)


def series(res):
    r = res.get("results", [{}])[0]
    return r.get("series", [])


print("=" * 76)
print("PHASE 1 -- overall range per signal (all buses, all time)")
print("=" * 76)
for sig in SIGNALS:
    res = q('SELECT count("%s"), min("%s"), max("%s"), mean("%s") '
            'FROM signals WHERE vehicle=\'vtrux\'' % (sig, sig, sig, sig))
    for s in series(res):
        _, n, lo, hi, mu = s["values"][0]
        print("%-32s n=%-8d min=%-6.2f max=%-6.2f mean=%.2f" % (sig, n, lo, hi, mu))

print()
print("=" * 76)
print("PHASE 2 -- corpus time span (OBD bus, APP present)")
print("=" * 76)
for order, label in (("ASC", "first"), ("DESC", "last")):
    res = q('SELECT "Accelerator_Actual_Position" FROM signals '
            'WHERE vehicle=\'vtrux\' AND bus=\'obd\' '
            'ORDER BY time %s LIMIT 1' % order)
    for s in series(res):
        print("  %-6s point: %s" % (label, s["values"][0][0]))

print()
print("=" * 76)
print("PHASE 3 -- distribution of Accelerator_Actual_Position (OBD bus)")
print("=" * 76)
SIG = "Accelerator_Actual_Position"
total = None
res = q('SELECT count("%s") FROM signals WHERE vehicle=\'vtrux\' AND bus=\'obd\'' % SIG)
for s in series(res):
    total = s["values"][0][1]
print("  total points: %d" % total)
print()
print("  %-14s %10s %8s" % ("band", "points", "share"))
edges = [0, 1, 5, 10, 20, 30, 40, 50, 60, 65, 70, 80, 90, 95, 100]
for lo, hi in zip(edges, edges[1:]):
    res = q('SELECT count("%s") FROM signals WHERE vehicle=\'vtrux\' AND bus=\'obd\' '
            'AND "%s" >= %d AND "%s" < %d' % (SIG, SIG, lo, SIG, hi))
    n = 0
    for s in series(res):
        n = s["values"][0][1]
    print("  %-14s %10d %7.2f%%" % ("%d-%d%%" % (lo, hi), n, 100.0 * n / total))

for thr in (66, 70, 80, 90, 95, 99):
    res = q('SELECT count("%s") FROM signals WHERE vehicle=\'vtrux\' AND bus=\'obd\' '
            'AND "%s" > %d' % (SIG, SIG, thr))
    n = 0
    for s in series(res):
        n = s["values"][0][1]
    print("  > %-2d%%          %10d %7.3f%%" % (thr, n, 100.0 * n / total))

print()
print("=" * 76)
print("PHASE 4 -- sessions reaching the top of scale")
print("=" * 76)
res = q('SELECT max("%s") FROM signals WHERE vehicle=\'vtrux\' AND bus=\'obd\' '
        'GROUP BY session' % SIG)
rows = []
for s in series(res):
    v = s["values"][0][1]
    if v is not None:
        rows.append((s["tags"]["session"], v))
rows.sort(key=lambda r: -r[1])
print("  %d sessions with APP data" % len(rows))
over = [r for r in rows if r[1] > 66]
print("  %d sessions peak above 66%%  (%.0f%% of sessions)"
      % (len(over), 100.0 * len(over) / len(rows)))
print()
print("  highest-peaking sessions:")
for name, v in rows[:12]:
    print("    %-42s %6.1f%%" % (name, v))
print("  lowest-peaking sessions:")
for name, v in rows[-8:]:
    print("    %-42s %6.1f%%" % (name, v))
