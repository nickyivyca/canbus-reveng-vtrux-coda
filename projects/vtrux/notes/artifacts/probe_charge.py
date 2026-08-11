"""
Probe candidate recent sessions for: is it a charge? does it reach high SoC
(balancing region)? is it the MAIN truck (TYPE2 alarm present)? and what is the
high-SoC resting spread (post-balance imbalance metric).
"""
import sys, os
sys.path.insert(0, ".")
import cantools
from canre.parsers import parse_file
from battery_degradation_characterize import collect, median

DBC = "projects/vtrux/epri-pt-bus.dbc"
db = cantools.database.load_file(DBC)
M410 = db.get_message_by_name("EPRI_BCM_Status_0410")

L = "projects/vtrux/logs"
LOGDIR = "../../CANLogs/VtruxLogs"

CL = "projects/vtrux/logs/after-battery-swap-charges"
CANDS = [
    ("winter charge_M0 Jan16", [f"{CL}/charge_M0_T{i}.log" for i in range(60)]),
    ("winter another_M0 Jan23", [f"{CL}/another_M0_T{i}.log" for i in range(1, 56)]),
    ("vtrux_newcharger 2026-05-03", [f"{L}/vtrux_newcharger.log", f"{L}/vtrux_newcharger_part2.log"]),
    ("android 2026-06-14", [f"{LOGDIR}/vtrux_20260614_165314_T{i}.log" for i in range(8)]),
]


def type2_fraction(files):
    """Sample bcm_alarm over the session start; TYPE2 (=2) => main truck swapped battery."""
    counts = {0: 0, 1: 0, 2: 0, 3: 0}
    seen = 0
    for f in files:
        if not os.path.exists(f):
            continue
        for fr in parse_file(f):
            if (fr.arbitration_id & 0x7FF) == 0x410:
                try:
                    a = M410.decode(fr.data, decode_choices=False, allow_truncated=True).get("bcm_alarm")
                    counts[int(a)] = counts.get(int(a), 0) + 1
                    seen += 1
                except Exception:
                    pass
            if seen >= 4000:
                break
        if seen >= 4000:
            break
    return counts, seen


for label, files in CANDS:
    files = [f for f in files if os.path.exists(f)]
    if not files:
        print(f"\n### {label}: NO FILES")
        continue
    s = collect(files)
    if len(s) < 50:
        print(f"\n### {label}: only {len(s)} samples")
        continue
    soc = [x["soc"] for x in s]
    cur = [x["ibat"] for x in s]
    tmax = [x["tmax"] for x in s if x["tmax"] is not None]
    role = "CHARGE" if sum(cur)/len(cur) > 5 else ("DRIVE" if min(cur) < -50 else "mixed/idle")
    counts, seen = type2_fraction(files)
    t2 = counts.get(2, 0) / seen * 100 if seen else 0

    print(f"\n### {label}")
    print(f"  samples={len(s)} dur={s[-1]['t']-s[0]['t']:.0f}s  role~{role}")
    print(f"  SoC {min(soc):.1f}-{max(soc):.1f}%  current {min(cur):.0f}/{max(cur):.0f}/{sum(cur)/len(cur):+.0f} (min/max/mean)A")
    print(f"  cell temp {min(tmax):.0f}-{max(tmax):.0f}C")
    print(f"  bcm_alarm over first {seen}: {counts}  -> TYPE2={t2:.0f}%  ({'MAIN truck' if t2>50 else 'NOT main (parts?)'})")
    # high-SoC resting spread
    for band_lo in (90, 85, 80):
        rest = [x["vmax"]-x["vmin"] for x in s if x["soc"] >= band_lo and abs(x["ibat"]) < 10]
        if len(rest) >= 30:
            print(f"  resting spread at SoC>={band_lo}%: median={median(rest):.1f} mV (n={len(rest)})")
            break
    else:
        print(f"  (no high-SoC rest samples; max SoC {max(soc):.1f}%)")
