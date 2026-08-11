"""Phase 3: zoom into specific events. Pure stdlib."""
import csv, os, bisect, sys

OUT = "projects/vtrux/notes/artifacts/smog-test"

def load(name, ncol):
    rows = []
    with open(os.path.join(OUT, name)) as f:
        r = csv.reader(f); next(r)
        for row in r:
            try:
                rows.append(tuple(float(x) if x != "" else None for x in row[:ncol]))
            except ValueError:
                pass
    return rows

s051 = load("s051.csv", 4)
s471 = load("s471.csv", 2)
s054 = load("s054.csv", 2)
s0c9 = load("s0C9.csv", 2)
s3d1 = load("s3D1.csv", 2)
T0 = min(s051[0][0], s054[0][0], s0c9[0][0])

def near(rows, t_abs, idx):
    ts = [r[0] for r in rows]
    i = bisect.bisect_left(ts, t_abs)
    best = None
    for j in (i-1, i, i+1):
        if 0 <= j < len(rows) and rows[j][idx] is not None:
            if best is None or abs(rows[j][0]-t_abs) < abs(best[0]-t_abs):
                best = rows[j]
    return best[idx] if best else None

def window(rows, t0r, t1r, idx):
    return [r for r in rows if t0r <= r[0]-T0 <= t1r and r[idx] is not None]

def dump(t0r, t1r, step=0.5):
    print(f"\n{'t_rel':>8} {'051_ti':>7} {'051_b0':>6} {'051rpmref':>9} {'471_Nm':>8} {'054rpm':>7} {'engRPM':>7} {'TPS%':>6}")
    t = t0r
    while t <= t1r:
        ta = T0 + t
        ti = near(s051, ta, 2); b0 = near(s051, ta, 1); rr = near(s051, ta, 3)
        nm = near(s471, ta, 1); gr = near(s054, ta, 1); er = near(s0c9, ta, 1); tp = near(s3d1, ta, 1)
        def f(v, fmt): return (fmt % v) if v is not None else "-"
        print(f"{t:8.1f} {f(ti,'%7.0f')} {f(b0,'%6.0f')} {f(rr,'%9.0f')} {f(nm,'%8.1f')} {f(gr,'%7.0f')} {f(er,'%7.0f')} {f(tp,'%6.1f')}")
        t += step

mode = sys.argv[1] if len(sys.argv) > 1 else "spike"
if mode == "spike":
    print("=== SPIKE window (engine RPM peak ~t=5732.6s) ===")
    dump(5722, 5745, 0.5)
    print("\nmax torque_input overall and its time:")
    mx = max(s051, key=lambda r: r[2])
    print(f"  ti_max={mx[2]:.0f} at t={mx[0]-T0:.1f}s (b0={mx[1]:.0f}, rpmref={mx[3]:.0f})")
elif mode == "osc":
    print("=== Oscillation burst window ===")
    a, b = float(sys.argv[2]), float(sys.argv[3])
    dump(a, b, float(sys.argv[4]) if len(sys.argv) > 4 else 0.5)
