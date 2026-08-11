"""Analyze DFCO + TPS + RPM: wind-down profile and DFCO behavior during high-RPM coasts."""
import csv, os, bisect
OUT = "projects/vtrux/notes/artifacts/smog-test"

def load(name, cols):
    rows = []
    with open(os.path.join(OUT, name)) as f:
        r = csv.reader(f); next(r)
        for row in r:
            try: rows.append(tuple(float(row[c]) if row[c] != "" else None for c in cols))
            except (ValueError, IndexError): pass
    return rows

d = load("s3D1_dfco.csv", [0,1,2])     # t, tps, dfco
rpm = load("s0C9.csv", [0,1])          # t, eng_rpm
T0 = min(d[0][0], rpm[0][0])
rt = [r[0] for r in rpm]
def rpm_at(ta):
    i = bisect.bisect_left(rt, ta)
    best=None
    for j in (i-1,i):
        if 0<=j<len(rpm):
            if best is None or abs(rpm[j][0]-ta)<abs(best[0]-ta): best=rpm[j]
    return best[1] if best else None

# overall DFCO
ndf = sum(1 for _,_,f in d if f==1)
print(f"DFCO active frames: {ndf}/{len(d)} ({100*ndf/len(d):.1f}%)")
# DFCO activation episodes (rising edges) and their RPM/TPS context
print("\nDFCO activation episodes (rising edges), with RPM at onset:")
prev=0; eps=[]
for t,tps,f in d:
    if f==1 and prev==0:
        eps.append((t,tps))
    prev=f
print(f"  {len(eps)} DFCO onsets total")
# cluster onsets within 10s, report representative with peak rpm in +-5s
shown=[]
for t,tps in eps:
    if any(abs(t-s)<8 for s in shown): continue
    shown.append(t)
    window=[r[1] for r in rpm if abs(r[0]-t)<5]
    pk=max(window) if window else None
    print(f"  t={t-T0:8.1f}s  TPS_onset={tps:5.1f}%  peakRPM(+-5s)={pk if pk is None else f'{pk:.0f}'}")
    if len(shown)>=25: print("  ..."); break

# wind-down end of session
print("\n=== END-OF-SESSION wind-down (30s bins): TPS max, RPM max, DFCO frac ===")
from collections import defaultdict
b_tps=defaultdict(list); b_dfco=defaultdict(list)
for t,tps,f in d:
    b=int((t-T0)//30); b_tps[b].append(tps); b_dfco[b].append(f)
b_rpm=defaultdict(list)
for t,r in rpm: b_rpm[int((t-T0)//30)].append(r)
print(f"{'t_s':>6}{'TPSmax':>7}{'TPSmed':>7}{'RPMmax':>7}{'DFCO%':>6}")
for b in range(245,262):
    if b not in b_tps: continue
    tp=b_tps[b]; df=b_dfco[b]; rp=b_rpm.get(b,[])
    tp_s=sorted(tp)
    print(f"{b*30:>6}{max(tp):>7.0f}{tp_s[len(tp_s)//2]:>7.0f}{(max(rp) if rp else 0):>7.0f}{100*sum(df)/len(df):>6.0f}")

# spike window
print("\n=== SPIKE window 5722-5745: TPS, RPM, DFCO (0.5s) ===")
import bisect as bs
dt=[x[0] for x in d]
t=5722.0
print(f"{'t_rel':>7}{'TPS%':>6}{'DFCO':>5}{'RPM':>7}")
while t<=5745:
    ta=T0+t; i=bs.bisect_left(dt,ta)
    row=min(d[max(0,i-1):i+2], key=lambda r:abs(r[0]-ta)) if d[max(0,i-1):i+2] else None
    if row:
        print(f"{t:7.1f}{row[1]:6.1f}{int(row[2]):5d}{(rpm_at(ta) or 0):7.0f}")
    t+=0.5
