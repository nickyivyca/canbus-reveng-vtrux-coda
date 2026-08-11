"""
Matched-SoC imbalance comparison: winter current-limiting test (2026-02-25)
vs today's drive (2026-06-17). Comparing resting spread at the SAME SoC removes
the OCV-slope amplification, isolating real change in cell imbalance.
"""
import sys
sys.path.insert(0, ".")
from battery_degradation_characterize import collect, median

L = "projects/vtrux/logs"
LOGDIR = "../../CANLogs/VtruxLogs"

SESSIONS = {
    "winter current-limiting (Feb25)": [f"{L}/vtruxcurrentlimitingtest.log"],
    "today drive (Jun17)": [f"{LOGDIR}/vtrux_20260617_193900_T{i}.log" for i in range(36)],
}


def settled_rest(s):
    out = []
    for i in range(len(s)):
        if abs(s[i]["ibat"]) >= 10:
            continue
        ok, j, span = True, i - 1, 0.0
        while j >= 0 and span < 2.0:
            dt = s[j + 1]["t"] - s[j]["t"]
            if dt < 0:
                break
            span += dt
            if abs(s[j]["ibat"]) >= 15:
                ok = False
                break
            j -= 1
        if ok:
            out.append(s[i])
    return out


data = {}
for label, files in SESSIONS.items():
    files = [f for f in files if __import__("os").path.exists(f)]
    s = collect(files)
    data[label] = settled_rest(s)
    print(f"{label}: {len(s)} samples, {len(data[label])} settled-rest")

print(f"\n=== resting spread (mV) by 1% SoC band, matched ===")
print(f"  {'SoC band':>10}", end="")
for label in SESSIONS:
    print(f"{label[:22]:>24}", end="")
print()
for lo in range(12, 68):
    row = {}
    for label in SESSIONS:
        band = [x["vmax"] - x["vmin"] for x in data[label] if lo <= x["soc"] < lo + 1]
        if len(band) >= 20:
            row[label] = (median(band), len(band))
    if len(row) == 2:  # only print bands present in BOTH sessions
        print(f"  {lo:>4}-{lo+1:<5}", end="")
        for label in SESSIONS:
            m, n = row[label]
            print(f"{m:>14.1f} (n={n:<4})" if False else f"{m:>16.1f}[{n}]", end="")
        print()
