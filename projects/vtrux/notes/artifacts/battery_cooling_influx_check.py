"""Cross-session battery-cooling threshold check via InfluxDB.

Cooling-active proxy: DCDC_LV_Curr (12V load) steps from ~6A baseline to ~100A when
the cooling package engages. During CHARGING the 12V baseline is low, so
LV_Curr > 40A cleanly means cooling-on (removes the driving confound where 12V is
high from other loads regardless of pack temp).

Test: among charging samples (bcm_ibat > +5A) across all vtrux sessions in Influx,
bin by bcm_cell_tmax and compute P(cooling-on | tmax). Expect a sharp step ~38C.

Also reports, per charge session, the tmax at which cooling first engaged (LV_Curr
crossing 40A while charging) and the max tmax reached while cooling stayed off.

Read-only against InfluxDB (localhost). Run again after the gap upload to include
new sessions.
"""
import sys
sys.path.insert(0, ".")

import json
import urllib.parse
import urllib.request
from collections import defaultdict

INFLUX = "http://localhost:8086"
DB = "canbus-data"
USER = "<influx-user>"
PW = "claude"
BUCKET = "10s"
COOL_A = 40.0     # LV_Curr threshold for "cooling on"
CHG_A = 5.0       # ibat threshold for "charging"


def q(query):
    params = urllib.parse.urlencode({"db": DB, "u": USER, "p": PW, "q": query})
    url = f"{INFLUX}/query?{params}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def sessions():
    res = q("SHOW TAG VALUES FROM signals WITH KEY=\"session\" WHERE vehicle='vtrux'")
    out = []
    for s in res["results"][0].get("series", []):
        out += [v[1] for v in s["values"]]
    return out


def series_for(session, signal):
    """mean(value) grouped by time(BUCKET) -> dict{epoch_ns: value}."""
    query = (f"SELECT mean(value) FROM signals WHERE vehicle='vtrux' "
             f"AND session='{session}' AND \"signal\"='{signal}' "
             f"GROUP BY time({BUCKET}) fill(none)")
    res = q(query)
    out = {}
    for s in res["results"][0].get("series", []):
        for t, v in s["values"]:
            if v is not None:
                out[t] = v
    return out


if __name__ == "__main__":
    sess = sessions()
    print(f"{len(sess)} vtrux sessions in Influx")

    bins = defaultdict(lambda: [0, 0])   # tmax_rounded -> [cooling_on, total] (charging only)
    per_session = []
    used = 0
    for i, s in enumerate(sess):
        lv = series_for(s, "DCDC_LV_Curr")
        tm = series_for(s, "bcm_cell_tmax")
        ib = series_for(s, "bcm_ibat")
        if not lv or not tm or not ib:
            continue
        used += 1
        first_on_tmax = None
        max_off_tmax = None
        common = sorted(set(lv) & set(tm) & set(ib))
        for t in common:
            if ib[t] <= CHG_A:      # charging only
                continue
            tmax = round(tm[t] * 2) / 2   # 0.5C resolution
            on = lv[t] > COOL_A
            b = bins[tmax]
            b[1] += 1
            if on:
                b[0] += 1
                if first_on_tmax is None:
                    first_on_tmax = tm[t]
            else:
                if max_off_tmax is None or tm[t] > max_off_tmax:
                    max_off_tmax = tm[t]
        if first_on_tmax is not None or max_off_tmax is not None:
            per_session.append((s, first_on_tmax, max_off_tmax))

    print(f"{used} sessions had LV_Curr+tmax+ibat; "
          f"{len(per_session)} had charging samples\n")

    print("=== P(cooling-on | cell tmax), CHARGING samples only ===")
    print(f"{'tmax':>6} {'on':>7} {'total':>7} {'P(on)':>7}")
    for tmax in sorted(bins):
        on, tot = bins[tmax]
        if tot < 5:
            continue
        print(f"{tmax:6.1f} {on:7d} {tot:7d} {100*on/tot:6.0f}%")

    print("\n=== per charge session: tmax at first cooling-on vs max tmax while off ===")
    print(f"{'session':45} {'first_on':>9} {'max_off':>8}")
    for s, on_t, off_t in sorted(per_session, key=lambda x: (x[1] is None, x[1] or 0)):
        on_s = f"{on_t:.1f}" if on_t is not None else "-"
        off_s = f"{off_t:.1f}" if off_t is not None else "-"
        print(f"{s[:45]:45} {on_s:>9} {off_s:>8}")
