"""Lumped pack thermal model + Peltier-liveness test. See battery-thermals.md spec.

Model:  C dT/dt = a*ibat^2 + P0 - UA*(T - T_amb) - Q_active
Fit {a/C, P0/C, UA/C} on cooling-OFF bins (Q_active=0), then on cooling-ON bins
measure the residual dT/dt vs the passive prediction. Residual is in physical
degC/min and is C-independent:
  cooling-ON cools FASTER than passive predicts (residual < 0) -> active heat
  removal -> Peltier working.  residual ~ 0 -> fan-only / dead Peltier.

T = pack mean = (tmax+tmin)/2 (primary); spread S = tmax-tmin tracked separately.
Ambient = ECM_OutsideAirTemp (0x4C1); sink = PE-loop/DCDC HW temp (0x18FFD6B3 B6-B7).

Phase A parses gap sessions (grep-prefiltered) -> cache. Phase B bins to 60s, fits,
tests. All 30 gap sessions are the post-swap (new) pack.
"""
import sys
sys.path.insert(0, ".")

import os
import csv
import glob
import struct
import subprocess
from collections import defaultdict

import cantools

from battery_fan_signature import parse_header_time, decode_line
from battery_cooling_xsession_raw import gap_sessions

ART = "projects/vtrux/notes/artifacts"
CACHE = os.path.join(ART, "thermal_model_samples.csv")
RUN_PARSE = False
BIN = 60.0  # seconds

pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
M410 = pt.get_message_by_frame_id(0x410)
M430 = pt.get_message_by_frame_id(0x430)
try:
    obd = cantools.database.load_file("projects/vtrux/epri-obd-bus.dbc")
    M4C1 = obd.get_message_by_frame_id(0x4C1)
except Exception:
    M4C1 = None


def parse_session(files):
    last = dict(ibat=None, cool=0, oat=None, pe=None)
    samples = []
    last_emit = None
    for path in files:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(
            ["grep", "-hE", " 0x(410|430|506|4C1|18FFD6B3) ", path],
            capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if arb == 0x410:
                try:
                    last["ibat"] = M410.decode(data, allow_truncated=True).get("bcm_ibat")
                except Exception:
                    pass
            elif arb == 0x506 and data:
                last["cool"] = (data[0] >> 5) & 1
            elif arb == 0x4C1 and M4C1:
                try:
                    last["oat"] = M4C1.decode(data, allow_truncated=True).get("ECM_OutsideAirTemp")
                except Exception:
                    pass
            elif arb == 0x18FFD6B3 and len(data) >= 8:
                last["pe"] = struct.unpack("<h", bytes(data[6:8]))[0] * 0.1
            elif arb == 0x430:
                try:
                    s = M430.decode(data, allow_truncated=True)
                    tmax = s.get("bcm_cell_tmax"); tmin = s.get("bcm_cell_tmin")
                except Exception:
                    continue
                if tmax is None or tmin is None or tmax < -30 or tmax > 80:
                    continue
                ep = t.timestamp()
                if last_emit is not None and ep - last_emit < 1.0:
                    continue
                last_emit = ep
                samples.append((round(ep, 1), tmax, tmin, last["ibat"],
                                last["cool"], last["oat"], last["pe"]))
    return samples


def phase_parse():
    sess = gap_sessions()
    print(f"Phase A: {len(sess)} sessions")
    with open(CACHE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["session", "t", "tmax", "tmin", "ibat", "cool", "oat", "pe"])
        for i, (name, files) in enumerate(sess):
            for s in parse_session(files):
                w.writerow([name, *s])
            print(f"  [{i+1}/{len(sess)}] {name}")
    print("cached ->", CACHE)


def load():
    rows = defaultdict(list)
    with open(CACHE) as f:
        for r in csv.DictReader(f):
            rows[r["session"]].append(r)
    return rows


def fnum(x):
    return float(x) if x not in (None, "", "None") else None


def bin_session(rows):
    """Return 60s bins: list of dict(t, T, S, ibat, cool_frac, oat, pe)."""
    buckets = defaultdict(list)
    for r in rows:
        tmax = fnum(r["tmax"]); tmin = fnum(r["tmin"]); ib = fnum(r["ibat"])
        oat = fnum(r["oat"]); pe = fnum(r["pe"]); t = fnum(r["t"])
        if None in (tmax, tmin, ib, t):
            continue
        b = int(t // BIN)
        buckets[b].append((tmax, tmin, ib, int(r["cool"]), oat, pe))
    out = []
    for b in sorted(buckets):
        v = buckets[b]
        n = len(v)
        tmax = sum(x[0] for x in v) / n
        tmin = sum(x[1] for x in v) / n
        ib = sum(x[2] for x in v) / n
        cool = sum(x[3] for x in v) / n
        oats = [x[4] for x in v if x[4] is not None]
        pes = [x[5] for x in v if x[5] is not None]
        out.append(dict(b=b, t=b * BIN, T=(tmax + tmin) / 2, S=tmax - tmin,
                        tmax=tmax, ib=ib, cool=cool,
                        oat=(sum(oats) / len(oats) if oats else None),
                        pe=(sum(pes) / len(pes) if pes else None)))
    return out


def build_dataset(rows_by_session, require_oat=True):
    """Yield (dTdt, ibat2, T_minus_Tamb, cool_flag, dSdt, ctx) over consecutive bins."""
    data = []
    for sess, rows in rows_by_session.items():
        bins = bin_session(rows)
        for i in range(len(bins) - 1):
            a, c = bins[i], bins[i + 1]
            if c["b"] - a["b"] != 1:      # require adjacent 60s bins
                continue
            tamb = a["oat"]
            if require_oat and tamb is None:
                continue
            if tamb is None:
                tamb = 25.0
            dTdt = (c["T"] - a["T"]) / BIN * 60.0   # degC/min
            dSdt = (c["S"] - a["S"]) / BIN * 60.0
            cool = 1 if a["cool"] > 0.5 else 0
            data.append(dict(sess=sess, dTdt=dTdt, ib2=(a["ib"] / 100.0) ** 2,
                             dT=a["T"] - tamb, cool=cool, dSdt=dSdt,
                             T=a["T"], ib=a["ib"], pe=a["pe"], tamb=tamb))
    return data


def lstsq(X, y):
    n = len(X[0])
    A = [[0.0] * n for _ in range(n)]
    bvec = [0.0] * n
    for xi, yi in zip(X, y):
        for r in range(n):
            bvec[r] += xi[r] * yi
            for cc in range(n):
                A[r][cc] += xi[r] * xi[cc]
    for i in range(n):
        A[i].append(bvec[i])
    for i in range(n):
        p = A[i][i] or 1e-9
        for cc in range(i, n + 1):
            A[i][cc] /= p
        for k in range(n):
            if k != i:
                f = A[k][i]
                for cc in range(i, n + 1):
                    A[k][cc] -= f * A[i][cc]
    return [A[i][n] for i in range(n)]


if __name__ == "__main__":
    if RUN_PARSE:
        phase_parse()
    rows_by_session = load()
    data = build_dataset(rows_by_session, require_oat=True)
    print(f"\nBins with ambient: {len(data)} (from "
          f"{sum(1 for r in rows_by_session)} sessions)")
    off = [d for d in data if d["cool"] == 0]
    on = [d for d in data if d["cool"] == 1]
    print(f"cooling-OFF bins: {len(off)}   cooling-ON bins: {len(on)}")

    X = [[d["ib2"], d["dT"], 1.0] for d in off]
    y = [d["dTdt"] for d in off]
    coef = lstsq(X, y)
    a_C, negUA_C, P0_C = coef
    print(f"\nPassive fit (degC/min):  dT/dt = {a_C:.4f}*ibat2 "
          f"{negUA_C:+.4f}*(T-Tamb) {P0_C:+.4f}")
    print(f"  implied passive time const ~ {-1/negUA_C:.1f} min" if negUA_C < 0 else "")

    def predict(d):
        return a_C * d["ib2"] + negUA_C * d["dT"] + P0_C

    import statistics as st
    res_on = [d["dTdt"] - predict(d) for d in on]
    res_off = [d["dTdt"] - predict(d) for d in off]
    print(f"\n=== Peltier test: residual dT/dt (actual - passive prediction) ===")
    print(f"  cooling-OFF residual: mean {st.mean(res_off):+.3f} degC/min "
          f"(should be ~0; n={len(res_off)})")
    print(f"  cooling-ON  residual: mean {st.mean(res_on):+.3f} +/- "
          f"{st.pstdev(res_on)/len(res_on)**0.5:.3f} degC/min (n={len(res_on)})")
    print(f"  -> negative = active heat removal beyond passive (Peltier working)")

    print(f"\n=== Spread dS/dt (fan-mixing signature) ===")
    print(f"  cooling-OFF dS/dt: {st.mean([d['dSdt'] for d in off]):+.3f} degC/min")
    print(f"  cooling-ON  dS/dt: {st.mean([d['dSdt'] for d in on]):+.3f} degC/min "
          f"(negative = spread shrinking = fan mixing)")

    print(f"\n=== cooling-ON bins: is pack above or below ambient & PE sink? ===")
    dT_amb = [d["T"] - d["tamb"] for d in on]
    peon = [d["T"] - d["pe"] for d in on if d["pe"] is not None]
    print(f"  pack T - ambient: mean {st.mean(dT_amb):+.1f} C (pack is this far above OAT)")
    if peon:
        print(f"  pack T - PE loop: mean {st.mean(peon):+.1f} C "
              f"(negative = pack colder than sink)")
