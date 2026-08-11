"""
Phase 2 analysis of smog test extraction (run after smog_extract.py PHASE=1).
Loads the CSVs and answers the four questions. Pure stdlib.
"""
import csv, os, bisect

OUT = "projects/vtrux/notes/artifacts/smog-test"

def load(name, cols):
    path = os.path.join(OUT, name)
    rows = []
    with open(path) as f:
        r = csv.reader(f); next(r)
        for row in r:
            try:
                rows.append([float(row[0])] + [float(row[c]) if row[c] != "" else None for c in cols])
            except (ValueError, IndexError):
                pass
    return rows

def main():
    s051 = load("s051.csv", [1, 2, 3])   # t, b0, torque_input, rpm_ref
    s471 = load("s471.csv", [1])          # t, gene_trq_nm
    s054 = load("s054.csv", [1])          # t, gene_rpm
    s0c9 = load("s0C9.csv", [1])          # t, eng_rpm
    s3d1 = load("s3D1.csv", [1])          # t, tps_pct

    t0 = min(s051[0][0], s054[0][0], s0c9[0][0])
    def rel(t): return t - t0
    dur = max(s051[-1][0], s0c9[-1][0]) - t0
    print(f"session span: {dur:.0f} s ({dur/60:.1f} min), t0(abs)={t0:.0f}")
    print(f"counts: 0x051={len(s051)} 0x471={len(s471)} 0x054={len(s054)} 0x0C9={len(s0c9)} 0x3D1={len(s3d1)}")

    # ---- engine RPM peak (Q2) ----
    print("\n=== Q2: engine RPM peak (0x0C9) ===")
    rpm_max = max(s0c9, key=lambda r: r[1])
    print(f"peak eng_rpm = {rpm_max[1]:.0f} at t={rel(rpm_max[0]):.1f}s")
    gmax = max(s054, key=lambda r: r[1])
    print(f"peak GENE_rpm(0x054) = {gmax[1]:.0f} at t={rel(gmax[0]):.1f}s")
    # top 10 distinct-time engine rpm peaks
    top = sorted(s0c9, key=lambda r: -r[1])[:200]
    seen = []
    for r in top:
        if all(abs(r[0]-s) > 5 for s in seen):
            seen.append(r[0])
            print(f"  eng_rpm {r[1]:7.0f} @ t={rel(r[0]):8.1f}s")
        if len(seen) >= 8:
            break

    # ---- engine RPM time profile (binned) ----
    print("\n=== engine RPM / GENE rpm / TPS profile (60s bins: max) ===")
    def binmax(rows, idx, binsz=60):
        d = {}
        for r in rows:
            b = int(rel(r[0]) // binsz)
            v = r[idx]
            if v is None: continue
            if b not in d or v > d[b]: d[b] = v
        return d
    eng_b = binmax(s0c9, 1); gene_b = binmax(s054, 1); tps_b = binmax(s3d1, 1)
    nb = int(dur // 60) + 1
    print(f"{'min':>4} {'engRPMmax':>9} {'geneRPMmax':>10} {'TPSmax%':>8}")
    for b in range(nb):
        e = eng_b.get(b); g = gene_b.get(b); tp = tps_b.get(b)
        print(f"{b:>4} {(f'{e:.0f}' if e is not None else '-'):>9} {(f'{g:.0f}' if g is not None else '-'):>10} {(f'{tp:.1f}' if tp is not None else '-'):>8}")

    # ---- oscillation (Q1) ----
    print("\n=== Q1: 0x051 torque_input stats ===")
    ti = [r[2] for r in s051]
    print(f"torque_input min={min(ti):.0f} max={max(ti):.0f}")
    # script bands
    below = sum(1 for v in ti if v < 32420)
    band = sum(1 for v in ti if 32420 <= v < 32768)
    above = sum(1 for v in ti if v >= 32768)
    n = len(ti)
    print(f"  <32420 (HCU strong-gen passthrough): {below} ({100*below/n:.1f}%)")
    print(f"  32420..32768 (idle band): {band} ({100*band/n:.1f}%)")
    print(f"  >=32768 (motoring/backdrive override): {above} ({100*above/n:.1f}%)")

    # detect override ramp cycles: a cycle = crossing up into >=32768 region then drop below 32420
    # Use hysteresis state machine on torque_input
    cycles = []
    state = "low"  # low (<32420) ; ramp (>=32420)
    ramp_start = None; ramp_peak = None; ramp_peak_t = None
    for t, b0, v, rr in s051:
        if v >= 32768:
            if state == "low":
                state = "ramp"; ramp_start = t; ramp_peak = v; ramp_peak_t = t
            else:
                if v > (ramp_peak or 0): ramp_peak = v; ramp_peak_t = t
        elif v < 32420:
            if state == "ramp":
                cycles.append((ramp_start, ramp_peak_t, t, ramp_peak))
                state = "low"
    print(f"\noverride->drop cycles detected (peak>=32768 then <32420): {len(cycles)}")
    if cycles:
        periods = [cycles[i+1][0]-cycles[i][0] for i in range(len(cycles)-1)]
        durs = [c[2]-c[0] for c in cycles]
        peaks = [c[3] for c in cycles]
        import statistics as st
        print(f"  cycle period: median={st.median(periods):.2f}s mean={st.mean(periods):.2f}s min={min(periods):.2f} max={max(periods):.2f}" if periods else "  (one cycle)")
        print(f"  ramp duration (start->drop): median={st.median(durs):.2f}s")
        print(f"  ramp peak torque_input: median={st.median(peaks):.0f} max={max(peaks):.0f}")
        # where are cycles concentrated in time?
        print("  cycles per minute-bin:")
        cb = {}
        for c in cycles:
            cb[int(rel(c[0])//60)] = cb.get(int(rel(c[0])//60),0)+1
        line = " ".join(f"{b}:{cb[b]}" for b in sorted(cb))
        print("   " + line)

    # ---- OBD readiness (Q4) ----
    print("\n=== Q4: OBD readiness ===")
    obd = []
    with open(os.path.join(OUT, "obd.csv")) as f:
        r = csv.reader(f); next(r)
        for row in r:
            obd.append(row)  # t,arbid,dir,svc,pid,A,B,C,D
    reqs = [o for o in obd if o[2] == "req"]
    resps = [o for o in obd if o[2] == "resp"]
    print(f"requests: {len(reqs)}  responses(PID01/41): {len(resps)}")
    from collections import Counter
    print("  req PIDs:", dict(Counter(o[4] for o in reqs)))
    # decode readiness for PID 01 responses over time
    NONCONT = ["Catalyst","HeatedCat","EvapSys","SecAir","ACrefrig","O2sensor","O2heater","EGR/VVT"]
    def decode_pid01(A,B,C,D):
        A=int(A);B=int(B);C=int(C);D=int(D)
        mil = bool(A & 0x80); dtc = A & 0x7F
        cont = []
        names_c = ["Misfire","Fuel","Components"]
        for i in range(3):
            sup = bool(B & (1<<i)); inc = bool(B & (1<<(i+4)))
            if sup: cont.append(f"{names_c[i]}{'!' if inc else 'OK'}")
        nonc = []
        for i in range(8):
            sup = bool(C & (1<<i)); inc = bool(D & (1<<i))
            if sup: nonc.append(f"{NONCONT[i]}{'!' if inc else 'OK'}")
        return mil, dtc, cont, nonc
    print("\n  PID 01 (since DTC clear) readiness samples over time:")
    last = None
    for o in resps:
        if o[4] != "1":  # pid 0x01
            continue
        t = float(o[0]); mil,dtc,cont,nonc = decode_pid01(o[5],o[6],o[7],o[8])
        sig = (tuple(cont), tuple(nonc), mil, dtc)
        if sig != last:
            inc = sum(1 for x in cont+nonc if x.endswith("!"))
            print(f"   t={rel(t):8.1f}s MIL={mil} DTC={dtc} incomplete={inc}: " + " ".join(cont+nonc))
            last = sig
    print("\n  PID 41 (this drive cycle) readiness changes:")
    last = None
    for o in resps:
        if o[4] != "65":  # pid 0x41 = 65
            continue
        t = float(o[0]); mil,dtc,cont,nonc = decode_pid01(o[5],o[6],o[7],o[8])
        sig = (tuple(cont), tuple(nonc))
        if sig != last:
            inc = sum(1 for x in cont+nonc if x.endswith("!"))
            print(f"   t={rel(t):8.1f}s incomplete={inc}: " + " ".join(cont+nonc))
            last = sig

if __name__ == "__main__":
    main()
