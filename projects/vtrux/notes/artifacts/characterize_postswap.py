"""
Characterize battery state in the earliest post-swap logs (Jan 2026, winter).
Sessions live in projects/vtrux/logs/after-battery-swap-charges/ with M/T naming.
These are charge/balancing sessions -> R_step sparse, R_reg polarization-inflated;
the resting-imbalance metric is the clean comparison vs today.
"""
import sys, os, re, glob
sys.path.insert(0, ".")
from battery_degradation_characterize import characterize

LOGDIR = "projects/vtrux/logs/after-battery-swap-charges"


def chunks_for(prefix):
    pat = re.compile(re.escape(prefix) + r"_T(\d+)\.log$")
    found = []
    for p in glob.glob(os.path.join(LOGDIR, prefix + "_T*.log")):
        m = pat.search(os.path.basename(p))
        if m:
            found.append((int(m.group(1)), p))
    return [p for _, p in sorted(found)]


SESSIONS = [
    ("charge_M0 (Jan16-17)", chunks_for("charge_M0")),
    ("another_M0 (Jan23 marathon)", chunks_for("another_M0")),
]

for label, files in SESSIONS:
    tot = sum(os.path.getsize(f) for f in files)
    print(f"{label}: {len(files)} chunks, {tot/1e6:.0f} MB")

results = []
for label, files in SESSIONS:
    r = characterize(label, files)
    if r:
        results.append(r)

print(f"\n{'='*78}\n### POST-SWAP SUMMARY (Jan 2026) -- per-cell R_reg (mOhm)")
print(f"  {'session':<30}{'n':>8}{'SoC%':>12}{'I(A)':>13}{'spread':>8}"
      f"{'Rmax':>7}{'Rmin':>7}{'Ravg':>7}")
for r in results:
    R = r["R"]
    print(f"  {r['label']:<30}{r['n']:>8}"
          f"{r['soc'][0]:>6.1f}-{r['soc'][1]:<5.1f}"
          f"{r['cur'][0]:>6.0f}-{r['cur'][1]:<6.0f}{r['spread_mean']:>8.1f}"
          f"{R.get('max',{}).get('R_reg',float('nan')):>7.2f}"
          f"{R.get('min',{}).get('R_reg',float('nan')):>7.2f}"
          f"{R.get('avg',{}).get('R_reg',float('nan')):>7.2f}")
