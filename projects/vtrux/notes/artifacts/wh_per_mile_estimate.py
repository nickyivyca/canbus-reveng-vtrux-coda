"""
wh_per_mile_estimate.py

Rough Wh/mile (battery-out) estimate for the Vtrux, with explicit handling of
the elevation confound.

Phases:
  1  recon   -- per-log census: which buses, which key IDs, duration, odometer
                and SoC endpoints. Decides which logs are usable.
  2  extract -- single-pass extraction of the signal time series needed for
                energy + distance + a barometric altitude proxy.
  3  energy  -- integrate pack power, distance from odometer/speed, naive Wh/mi
  4  grade   -- elevation handling: baro altimetry, PE/KE correction,
                road-load regression (elevation-free)

Run:  python3.13 projects/vtrux/notes/artifacts/wh_per_mile_estimate.py <phase>
"""

import re
import sys
import json
import math
from pathlib import Path

sys.path.insert(0, ".")

ART = Path("projects/vtrux/notes/artifacts")
LOGDIR = Path("projects/vtrux/logs")

# IDs of interest, keyed by hex string exactly as it appears in the BUSMASTER
# line (the parser writes IDs as 0x%X with no zero padding, but the logger
# writes them however it likes -- so normalise by int() instead).
WANT = {
    0x051: "VCM gen torque cmd (PT)",
    0x120: "odometer 0.015625 km (OBD)",
    0x2C3: "MAP / barometric proxy (OBD)",
    0x308: "BorgWarner input shaft speed (PT)",
    0x3E9: "veh speed + rolling distance (GM)",
    0x410: "BMS ibat/vbat/soc (PT)",
    0x411: "BMS SoC hi-res (PT)",
    0x430: "BMS cell v/t (PT)",
    0x462: "TRAC HV bus V/I (OBD)",
    0x482: "GENE HV bus V/I (PT)",
    0x4C1: "engine + outside air temp (OBD)",
    0x592: "pedals (PT)",
    0x598: "power averages (PT)",
    0x599: "oil pressures + baro ref (PT)",
    0x5A2: "trac rpm / torque (PT)",
    0x625: "odometer 1 km (PT)",
    0x044: "TRAC RotSpd (OBD)",
    0x0C1: "wheel speeds (GM)",
    0x0C5: "wheel speeds (GM)",
    0x1E5: "vehicle-bus anchor",
    0x500: "vehicle-bus anchor",
}

ANCHORS = {
    "PT": [0x051, 0x592, 0x598, 0x5A2, 0x625],
    "VEH": [0x1E5, 0x500, 0x514, 0x778, 0x780],
    "OBD": [0x040, 0x041, 0x042, 0x043, 0x044],
}


ANDROID_DIR = Path("../../CANLogs/VtruxLogs")

_START_RE = re.compile(r"\*\*\*START DATE AND TIME\s+\d{2}:\d{2}:\d{4}\s+"
                       r"(\d{1,2}):(\d{2}):(\d{2}):\d+")


def log_paths(spec):
    """Resolve a spec to an ordered list of chunk paths.

    '@20260714_161319' -> every _T{n} chunk of that Android session, in T order.
    anything else      -> a single file under projects/vtrux/logs/.
    """
    if spec.startswith("@"):
        sess = spec[1:]
        pats = []
        for f in ANDROID_DIR.iterdir():
            m = re.match(r"vtrux_%s_T(\d+)\.log$" % re.escape(sess), f.name)
            if m:
                pats.append((int(m.group(1)), f))
        return [f for _, f in sorted(pats)]
    return [LOGDIR / spec]


def iter_lines(spec):
    """Yield data lines across every chunk of a capture.

    Android chunk files each restart their data-line clock at 00:00:00, so the
    per-chunk ***START DATE AND TIME*** header is the only thing tying them to
    one timeline. We rewrite each line's timestamp field to session-absolute
    seconds and hand back (t, rest_of_line_parts).
    """
    base = None          # session epoch, seconds
    prev_epoch = None
    for path in log_paths(spec):
        epoch = None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line:
                    continue
                if line[0] == "*":
                    if epoch is None:
                        m = _START_RE.match(line)
                        if m:
                            h, mn, sec = (int(x) for x in m.groups())
                            epoch = h * 3600.0 + mn * 60.0 + sec
                            if prev_epoch is not None and epoch < prev_epoch - 1:
                                epoch += 86400.0        # session crossed midnight
                            prev_epoch = epoch
                            if base is None:
                                base = epoch
                    continue
                yield line, (epoch - base) if (epoch is not None and base is not None) else 0.0


def parse_ts(tok):
    h, m, s, t = tok.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(t) * 0.0001


# --------------------------------------------------------------------------
# Phase 1 -- recon
# --------------------------------------------------------------------------

def phase_recon(logs):
    out = {}
    for name in logs:
        if not log_paths(name):
            print("MISSING", name)
            continue
        # per (bus, id) -> count ; plus bus -> all ids seen
        counts = {}
        bus_ids = {}
        t_first = None
        t_last = None
        n = 0
        for line, off in iter_lines(name):
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                arb = int(parts[3], 16)
            except ValueError:
                continue
            bus = parts[2]
            n += 1
            ids = bus_ids.get(bus)
            if ids is None:
                ids = set()
                bus_ids[bus] = ids
            ids.add(arb)
            if arb in WANT:
                k = (bus, arb)
                counts[k] = counts.get(k, 0) + 1
            tt = parse_ts(parts[0]) + off
            if t_first is None:
                t_first = tt
            t_last = tt

        dur = (t_last - t_first) if t_first is not None else 0
        if dur < 0:
            dur += 86400
        print("=" * 78)
        print("%s   %.1f min   %d frames" % (name, dur / 60.0, n))
        for bus in sorted(bus_ids):
            ids = bus_ids[bus]
            role = []
            for r, anch in ANCHORS.items():
                hits = sum(1 for a in anch if a in ids)
                if hits:
                    role.append("%s:%d/%d" % (r, hits, len(anch)))
            print("  bus %s: %d unique IDs  [%s]" % (bus, len(ids), " ".join(role)))
            present = [(a, counts[(bus, a)]) for a in sorted(WANT) if (bus, a) in counts]
            for a, c in present:
                print("      0x%03X %-40s %d" % (a, WANT[a], c))
        out[name] = {"dur_min": dur / 60.0, "frames": n,
                     "buses": {b: sorted(v) for b, v in bus_ids.items()}}
    (ART / "whpm_recon.json").write_text(json.dumps(
        {k: {"dur_min": v["dur_min"], "frames": v["frames"]} for k, v in out.items()},
        indent=1))


# --------------------------------------------------------------------------
# Phase 2 -- extract signal time series
# --------------------------------------------------------------------------

# High-rate IDs get decimated to keep the extract small; the rest are kept whole.
DECIMATE = {0x051: 10, 0x482: 10, 0x462: 10, 0x308: 10, 0x592: 10,
            0x0C1: 5, 0x0C5: 5, 0x5A2: 1, 0x410: 1, 0x054: 5, 0x0C9: 5, 0x598: 1, 0x3D1: 1, 0x3FB: 1, 0x4D1: 1, 0x644: 10,
            0x18FFD7C0: 1, 0x18FFD8C0: 1, 0x18FFD6B3: 1, 0x18FFD4C0: 1,
            0x18FFD6C0: 1}

EXTRACT_IDS = [0x410, 0x411, 0x5A2, 0x482, 0x462, 0x599, 0x625,
               0x3E9, 0x120, 0x2C3, 0x4C1, 0x051, 0x054, 0x0C9, 0x598, 0x3D1, 0x3FB, 0x4D1, 0x644,
               0x18FFD7C0, 0x18FFD8C0, 0x18FFD6B3, 0x18FFD4C0,
               0x18FFD6C0]


def _load_dbcs():
    import cantools
    dbs = {}
    for key, path in [
        ("pt", "projects/vtrux/epri-pt-bus.dbc"),
        ("obd", "projects/vtrux/epri-obd-bus.dbc"),
        ("ptx", "projects/vtrux/vtrux-powertrain-experimental.dbc"),
        ("gm", "projects/vtrux/GMW8762_PPEI_GMLAN.dbc"),
    ]:
        dbs[key] = cantools.database.load_file(path)
    return dbs


def phase_extract(logs):
    dbs = _load_dbcs()

    def dec(dbkey, arb, data):
        try:
            return dbs[dbkey].decode_message(arb, data, decode_choices=False,
                                             allow_truncated=True)
        except Exception:
            return None

    for name in logs:
        rows = {}          # (bus, arb) -> list of (t, decoded dict)
        bus_ids = {}
        seen = {}
        t0 = None
        for line, off in iter_lines(name):
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                arb = int(parts[3], 16)
            except ValueError:
                continue
            bus = int(parts[2])
            bus_ids.setdefault(bus, set()).add(arb)
            if arb not in EXTRACT_IDS:
                continue
            k = (bus, arb)
            n = seen.get(k, 0)
            seen[k] = n + 1
            step = DECIMATE.get(arb, 1)
            if n % step:
                continue
            t = parse_ts(parts[0]) + off
            if t0 is None:
                t0 = t
            t -= t0
            if t < -1:
                t += 86400
            dlc = int(parts[5])
            data = bytes(int(b, 16) for b in parts[6:6 + dlc])
            rows.setdefault(k, []).append((t, data))

        # bus roles
        role = {}
        for bus, ids in bus_ids.items():
            score = {r: sum(1 for a in anch if a in ids) for r, anch in ANCHORS.items()}
            role[bus] = max(score, key=score.get)
        print(name, "bus roles:", role)

        series = {}

        def put(sig, t, v):
            series.setdefault(sig, []).append((round(t, 3), v))

        for (bus, arb), lst in sorted(rows.items()):
            r = role[bus]
            for t, data in lst:
                if arb == 0x18FFD7C0 and len(data) >= 8:
                    u = lambda b: data[b] | (data[b + 1] << 8)
                    sgn = lambda v: v - 65536 if v >= 32768 else v
                    put("dc_v", t, u(0) * 0.05)
                    put("dc_i", t, sgn(u(2)) * 0.05)
                    put("ac_v", t, u(4) * 0.05)
                    put("ac_i", t, u(6) * 0.05)
                elif arb == 0x18FFD6C0 and len(data) >= 8:
                    u = lambda b: data[b] | (data[b + 1] << 8)
                    put("inv_v1", t, u(0) * 0.05)
                    put("inv_v2", t, u(2) * 0.05)
                    put("inv_i1", t, u(4) * 0.05)
                    put("inv_i2", t, u(6) * 0.05)
                elif arb == 0x18FFD8C0 and len(data) >= 3:
                    put("pilot_duty", t, data[2])
                elif arb == 0x18FFD6B3 and len(data) >= 6:
                    u = lambda b: data[b] | (data[b + 1] << 8)
                    put("dcdc_lv_v", t, u(0) * 0.05)
                    put("dcdc_lv_i", t, u(2) * 0.05)
                    put("dcdc_hv_v", t, u(4) * 0.05)
                elif arb == 0x18FFD4C0 and len(data) >= 6 and data[0] == 0:
                    put("bel_state", t, data[5])
                elif r == "PT" and arb == 0x410:
                    d = dec("pt", 0x410, data)
                    if d:
                        put("ibat", t, d["bcm_ibat"])
                        put("vbat", t, d["bcm_vbat"])
                        put("soc", t, d["bcm_soc"])
                elif r == "PT" and arb == 0x411:
                    d = dec("ptx", 0x411, data)
                    if d:
                        put("soc_hires", t, d["bms_soc_hires"])
                elif r == "PT" and arb == 0x5A2:
                    d = dec("ptx", 0x5A2, data)
                    if d:
                        put("trac_rpm", t, d["trac_rpm"])
                        put("trac_trq", t, d["trac_torque_fbk"])
                elif r == "PT" and arb == 0x482:
                    d = dec("pt", 0x482, data)
                    if d:
                        put("gene_v", t, d["GENE_HighPwr_Volt"])
                        put("gene_i", t, d["GENE_HighPwr_Curr"])
                elif r == "PT" and arb == 0x599 and len(data) >= 4:
                    put("baro_599", t, (data[2] | (data[3] << 8)) * 0.1)
                elif r == "PT" and arb == 0x598 and len(data) >= 6:
                    put("p598_ess", t, data[0] | (data[1] << 8))
                    put("p598_gen", t, data[2] | (data[3] << 8))
                    put("p598_trac", t, data[4] | (data[5] << 8))
                elif r == "PT" and arb == 0x644 and len(data) >= 3:
                    put("cruise_mode", t, (data[2] >> 4) & 0x0F)
                    put("cruise_set", t, (((data[2] & 0x0F) << 8) | data[3]) * 0.125)
                elif r == "PT" and arb == 0x054:
                    d = dec("pt", 0x054, data)
                    if d:
                        put("gene_rpm", t, d["GENE_RotSpd"])
                elif r == "PT" and arb == 0x625:
                    d = dec("pt", 0x625, data)
                    if d:
                        put("odo_km_625", t, d["VehicleOdometer"])
                elif r == "OBD" and arb == 0x462:
                    d = dec("obd", 0x462, data)
                    if d:
                        put("trac_v", t, d["TRAC_HighPwr_Volt"])
                        put("trac_i", t, d["TRAC_HighPwr_Curr"])
                elif r == "OBD" and arb == 0x2C3 and len(data) >= 7:
                    put("map_obd", t, data[6] * 0.5)
                elif r == "OBD" and arb == 0x4C1:
                    d = dec("obd", 0x4C1, data)
                    if d:
                        put("oat", t, d["ECM_OutsideAirTemp"])
                        put("ect", t, d["ECM_EngineCoolantTemp"])
                elif arb == 0x3D1 and r in ("OBD", "VEH"):
                    d = dec("gm", 0x3D1, data)
                    if d:
                        tag = "" if r == "OBD" else "_veh"
                        put("fuel_lph" + tag, t, d["Instantaneous_Fuel_Consumption_Rate"])
                        put("fuel_cut" + tag, t, d["Engine_Coast_Fuel_Cut_Off_Active"])
                elif arb == 0x3FB and r in ("OBD", "VEH"):
                    d = dec("gm", 0x3FB, data)
                    if d:
                        tag = "" if r == "OBD" else "_veh"
                        put("eth_pct" + tag, t, d["Fuel_Alcohol_Composition"])
                        put("eth_valid" + tag, t, d["Fuel_Alcohol_Composition_Validity"])
                        put("eth_adapt" + tag, t, d["Fuel_Alcohol_Composition_Adaptation_in_Progress"])
                elif arb == 0x4D1 and r in ("OBD", "VEH"):
                    d = dec("gm", 0x4D1, data)
                    if d:
                        tag = "" if r == "OBD" else "_veh"
                        put("fuel_pct" + tag, t, d["Fuel_Level_Percent"])
                        put("fuel_cap" + tag, t, d["Fuel_Total_Capacity"])
                        put("fuel_pct_valid" + tag, t, d["Fuel_Level_Percent_Validity"])
                elif r == "OBD" and arb == 0x0C9:
                    d = dec("obd", 0x0C9, data)
                    if d:
                        put("eng_rpm", t, d["Engine_Speed"])
                elif r == "VEH" and arb == 0x3E9:
                    d = dec("gm", 0x3E9, data)
                    if d and d["Vehicle_Speed_Average_Driven_Validity"] == 0:
                        put("veh_kph", t, d["Vehicle_Speed_Average_Driven"])
                    if d and d["Distance_Rolling_Count_Average_Driven_Validity"] == 0:
                        put("dist_roll_m", t, d["Distance_Rolling_Count_Average_Driven"])
                elif r == "VEH" and arb == 0x120:
                    d = dec("obd", 0x120, data)
                    if d:
                        put("odo_km_120", t, d["VehicleOdometer"])
                elif r == "VEH" and arb == 0x2C3 and len(data) >= 7:
                    put("map_veh", t, data[6] * 0.5)

        for k in series:
            series[k].sort(key=lambda tv: tv[0])

        outp = ART / ("whpm_%s.json" % name.replace(".log", "").replace("@", "and_"))
        outp.write_text(json.dumps(series))
        print("  wrote", outp, {k: len(v) for k, v in sorted(series.items())})


# --------------------------------------------------------------------------
# Phase 3 -- signal sanity check
# --------------------------------------------------------------------------

def load(name):
    p = ART / ("whpm_%s.json" % name.replace(".log", "").replace("@", "and_"))
    return json.loads(p.read_text())


def resample(series, dt=1.0, tmax=None):
    """Zero-order-hold resample [(t,v)] onto a uniform dt grid."""
    if not series:
        return []
    tmax = tmax if tmax is not None else series[-1][0]
    out = []
    i = 0
    t = series[0][0]
    while t <= tmax:
        while i + 1 < len(series) and series[i + 1][0] <= t:
            i += 1
        out.append((t, series[i][1]))
        t += dt
    return out


def unwrap(series, modulus):
    """Unwrap a rolling counter that wraps at `modulus`."""
    out = []
    total = 0.0
    prev = None
    for t, v in series:
        if prev is not None:
            d = v - prev
            if d < -modulus / 2:
                d += modulus
            elif d > modulus / 2:
                d -= modulus
            total += d
        prev = v
        out.append((t, total))
    return out


def integrate(series):
    """Trapezoidal integral of [(t,v)] -> value*seconds."""
    tot = 0.0
    for i in range(1, len(series)):
        dt = series[i][0] - series[i - 1][0]
        if dt <= 0 or dt > 5.0:
            continue
        tot += 0.5 * (series[i][1] + series[i - 1][1]) * dt
    return tot


def stats(name, s):
    if not s:
        return "%-14s (empty)" % name
    vals = [v for _, v in s]
    return "%-14s n=%-6d t=%.0f..%.0f  min=%.3f max=%.3f first=%.3f last=%.3f" % (
        name, len(s), s[0][0], s[-1][0], min(vals), max(vals), vals[0], vals[-1])


def phase_check(logs):
    for name in logs:
        S = load(name)
        print("=" * 78)
        print(name)
        for k in sorted(S):
            print("  " + stats(k, S[k]))

        # --- distance sources -------------------------------------------
        print("  --- distance ---")
        if "odo_km_120" in S:
            v = [x[1] for x in S["odo_km_120"]]
            print("    odo 0x120 delta:      %.3f km" % (max(v) - min(v)))
        if "odo_km_625" in S:
            v = [x[1] for x in S["odo_km_625"]]
            print("    odo 0x625 delta:      %.0f km" % (max(v) - min(v)))
        if "dist_roll_m" in S:
            u = unwrap(S["dist_roll_m"], 8192 * 0.125)
            print("    0x3E9 rolling dist:   %.3f km" % (u[-1][1] / 1000.0))
        if "veh_kph" in S:
            print("    int(veh_kph):         %.3f km" % (integrate(S["veh_kph"]) / 3600.0))
        if "trac_rpm" in S:
            rpm = [(t, abs(v)) for t, v in S["trac_rpm"]]
            print("    int(trac_rpm)/66.1:   %.3f km" % (integrate(rpm) / 66.1 / 3600.0))

        # --- energy -----------------------------------------------------
        print("  --- energy ---")
        if "ibat" in S and "vbat" in S:
            ib = dict(S["ibat"])
            pw = [(t, v * ib.get(t, 0.0)) for t, v in S["vbat"] if t in ib]
            wh = integrate(pw) / 3600.0
            pos = integrate([(t, max(p, 0)) for t, p in pw]) / 3600.0
            neg = integrate([(t, min(p, 0)) for t, p in pw]) / 3600.0
            print("    pack net energy:      %.3f kWh (charge+ %.3f / discharge %.3f)"
                  % (wh / 1000, pos / 1000, neg / 1000))
        if "gene_v" in S and "gene_i" in S:
            gi = dict(S["gene_i"])
            gp = [(t, v * gi.get(t, 0.0)) for t, v in S["gene_v"] if t in gi]
            print("    generator energy:     %.3f kWh  (peak %.1f kW)"
                  % (integrate(gp) / 3.6e6, max(abs(p) for _, p in gp) / 1000 if gp else 0))
        if "soc_hires" in S:
            v = [x[1] for x in S["soc_hires"]]
            print("    SoC hires: %.2f -> %.2f  (delta %.2f %%)" % (v[0], v[-1], v[-1] - v[0]))

        # --- elevation proxies ------------------------------------------
        print("  --- elevation proxies ---")
        for k in ("baro_599", "map_obd", "map_veh"):
            if k in S:
                v = [x[1] for x in S[k]]
                sv = sorted(v)
                print("    %-9s min=%.1f p5=%.1f med=%.1f p95=%.1f max=%.1f kPa (unique %d)"
                      % (k, sv[0], sv[len(sv) // 20], sv[len(sv) // 2],
                         sv[len(sv) * 19 // 20], sv[-1], len(set(v))))


# --------------------------------------------------------------------------
# Phase 4 -- energy accounting + elevation handling
# --------------------------------------------------------------------------

G = 9.80665
MASS_KG = 3000.0        # ASSUMPTION -- see notes; only affects grade/KE terms
KM_PER_MI = 1.609344
# Barometric scale height at ~288 K: dh = -H * dp/p
H_SCALE = 8434.0        # m


def zoh(series):
    """Return a callable f(t) doing zero-order hold lookup, plus (t0, t1)."""
    ts = [t for t, _ in series]
    vs = [v for _, v in series]
    n = len(ts)
    state = [0]

    def f(t):
        i = state[0]
        if i >= n or ts[i] > t:
            i = 0
        while i + 1 < n and ts[i + 1] <= t:
            i += 1
        state[0] = i
        return vs[i]
    return f, (ts[0], ts[-1])


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def lstsq(A, y):
    """Least squares via normal equations + Gaussian elimination. Pure stdlib."""
    n = len(A[0])
    M = [[sum(A[k][i] * A[k][j] for k in range(len(A))) for j in range(n)]
         + [sum(A[k][i] * y[k] for k in range(len(A)))] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r == c:
                continue
            f = M[r][c] / M[c][c]
            for j in range(c, n + 1):
                M[r][j] -= f * M[c][j]
    return [M[i][n] / M[i][i] for i in range(n)]


def build(name, dt=1.0):
    """Build a uniform-dt frame of everything needed for one log."""
    S = load(name)
    out = {"name": name}

    # --- power channels (native rate, paired within the same CAN frame) ---
    ib = dict(S["ibat"])
    p_pack = [(t, v * ib[t]) for t, v in S["vbat"] if t in ib]        # W, +=charging
    out["p_pack_native"] = p_pack
    p_gene = []
    if "gene_i" in S:
        gi = dict(S["gene_i"])
        p_gene = [(t, -v * gi[t]) for t, v in S["gene_v"] if t in gi]  # W, +=generating
    out["p_gene_native"] = p_gene
    p_trac = []
    if "trac_i" in S:
        ti = dict(S["trac_i"])
        p_trac = [(t, v * ti[t]) for t, v in S["trac_v"] if t in ti]   # W, +=motoring
    out["p_trac_native"] = p_trac

    t0 = p_pack[0][0]
    t1 = p_pack[-1][0]
    n = int((t1 - t0) / dt) + 1
    grid = [t0 + i * dt for i in range(n)]
    out["t"] = grid
    out["dt"] = dt

    def col(series, default=0.0):
        if not series:
            return [default] * n
        f, _ = zoh(series)
        return [f(t) for t in grid]

    out["pack"] = col(p_pack)
    out["gene"] = col(p_gene)
    out["trac"] = col(p_trac)
    out["soc"] = col(S.get("soc_hires") or S["soc"])

    # --- engine-on flag -------------------------------------------------
    rpm_src = "eng_rpm" if "eng_rpm" in S else ("gene_rpm" if "gene_rpm" in S else None)
    out["rpm_src"] = rpm_src
    if rpm_src:
        rpm = col(S[rpm_src])
        out["eng_on"] = [abs(r) > 300 for r in rpm]
    else:
        out["eng_on"] = [abs(p) > 2000 for p in out["gene"]]

    # --- speed ----------------------------------------------------------
    if "veh_kph" in S:
        out["kph"] = col(S["veh_kph"])
        out["speed_src"] = "0x3E9 GMLAN"
        # calibrate trac_rpm -> km/h on this log for the PT-only logs
        rr = col(S["trac_rpm"])
        num = sum(r * k for r, k in zip(rr, out["kph"]) if k > 5)
        den = sum(k * k for k in out["kph"] if k > 5)
        out["rpm_per_kph"] = num / den if den else None
    else:
        ratio = 62.48   # calibrated against 0x3E9 on the three 3-bus logs
        out["kph"] = [abs(r) / ratio for r in col(S["trac_rpm"])]
        out["speed_src"] = "trac_rpm / %.2f (calibrated)" % ratio
        out["rpm_per_kph"] = None

    # --- distance -------------------------------------------------------
    if "dist_roll_m" in S:
        u = unwrap(S["dist_roll_m"], 8192 * 0.125)
        out["dist_m"] = col(u)
        out["dist_src"] = "0x3E9 rolling count"
    else:
        d = 0.0
        acc = []
        for k in out["kph"]:
            d += k / 3.6 * dt
            acc.append(d)
        out["dist_m"] = acc
        out["dist_src"] = "integrated speed"

    # --- barometric altitude (engine-off MAP only) ----------------------
    alt = None
    mapk = S.get("map_obd") or S.get("map_veh")
    if mapk and rpm_src:
        mv = col(mapk)
        # engine must have been off for >= 10 s for MAP to equal ambient
        off_run = 0
        raw = []
        for i in range(n):
            off_run = off_run + 1 if not out["eng_on"][i] else 0
            raw.append(mv[i] if off_run >= 10 else None)
        # median filter over a +/-60 s window of valid samples, then hold
        alt = []
        last = None
        for i in range(n):
            w = sorted(x for x in raw[max(0, i - 60):i + 61] if x is not None)
            # Manifold pressure can never EXCEED ambient, so contamination (a
            # sample taken before the manifold equalised, or an engine-off
            # misdetection) is always low-side. Require a real body of samples
            # with low spread, then take an upper quantile. A plain median over
            # a thinly-populated window let two bad samples inject +1237 m.
            if len(w) >= 20 and (w[-1] - w[0]) <= 2.0:
                last = -H_SCALE * math.log(w[int(0.9 * (len(w) - 1))] / 101.325)
            alt.append(last)
        out["map_valid_frac"] = sum(1 for x in raw if x is not None) / n
    out["alt"] = alt
    return out


def integ(vals, dt):
    return sum(vals) * dt


def phase_energy(logs):
    allsegs = []
    for name in logs:
        F = build(name)
        dt, n = F["dt"], len(F["t"])
        dur = F["t"][-1] - F["t"][0]
        dist_m = F["dist_m"][-1] - F["dist_m"][0]
        dist_mi = dist_m / 1000.0 / KM_PER_MI

        e_pack = integ(F["pack"], dt) / 3.6e6          # kWh, + = into pack
        e_pack_dis = -integ([min(p, 0) for p in F["pack"]], dt) / 3.6e6
        e_pack_chg = integ([max(p, 0) for p in F["pack"]], dt) / 3.6e6
        e_gene = integ(F["gene"], dt) / 3.6e6
        e_trac = integ(F["trac"], dt) / 3.6e6
        e_trac_out = integ([max(p, 0) for p in F["trac"]], dt) / 3.6e6
        e_regen = -integ([min(p, 0) for p in F["trac"]], dt) / 3.6e6

        # Energy delivered onto the HV bus by sources = pack discharge + generator
        e_bus = -e_pack + e_gene
        e_aux = e_bus - e_trac

        print("=" * 78)
        print("%s" % name)
        print("  duration %.1f min   distance %.3f km (%.3f mi)  [%s]"
              % (dur / 60, dist_m / 1000, dist_mi, F["dist_src"]))
        print("  speed src %s   avg %.1f km/h   max %.1f km/h"
              % (F["speed_src"], dist_m / 1000 / (dur / 3600), max(F["kph"])))
        if F["rpm_per_kph"]:
            print("  trac_rpm/kph calibration: %.2f" % F["rpm_per_kph"])
        eng_frac = sum(1 for x in F["eng_on"] if x) / n
        print("  engine on %.0f%% of time  (src %s)" % (100 * eng_frac, F["rpm_src"]))
        print("  SoC %.2f -> %.2f" % (F["soc"][0], F["soc"][-1]))
        print("  --- energy (kWh) ---")
        print("    pack net %+.3f   discharge %.3f  charge %.3f" % (e_pack, e_pack_dis, e_pack_chg))
        print("    generator %+.3f" % e_gene)
        if F["p_trac_native"]:
            print("    traction net %+.3f  (out %.3f  regen %.3f)" % (e_trac, e_trac_out, e_regen))
            print("    aux residual (bus - traction) %+.3f" % e_aux)
        print("  --- naive Wh/mi (uncorrected for elevation) ---")
        if dist_mi > 0.5:
            print("    battery-out only        %8.0f Wh/mi" % (e_pack_dis * 1000 / dist_mi))
            print("    battery net (out-in)    %8.0f Wh/mi" % (-e_pack * 1000 / dist_mi))
            print("    HV bus total (pack+gen) %8.0f Wh/mi" % (e_bus * 1000 / dist_mi))
            if F["p_trac_native"]:
                print("    traction net            %8.0f Wh/mi" % (e_trac * 1000 / dist_mi))

        # --- elevation --------------------------------------------------
        if F["alt"] and F["alt"][0] is not None and F["alt"][-1] is not None:
            dh = F["alt"][-1] - F["alt"][0]
            valid = [a for a in F["alt"] if a is not None]
            e_grade = MASS_KG * G * dh / 3.6e6
            print("  --- elevation (MAP barometric altimeter) ---")
            print("    engine-off MAP coverage %.0f%% of samples" % (100 * F["map_valid_frac"]))
            print("    relative altitude: start %+.0f m  end %+.0f m  min %+.0f  max %+.0f"
                  % (F["alt"][0], F["alt"][-1], min(valid), max(valid)))
            print("    net dh %+.0f m  -> potential energy %+.3f kWh (m=%.0f kg)"
                  % (dh, e_grade, MASS_KG))
            if dist_mi > 0.5:
                print("    grade-corrected HV bus  %8.0f Wh/mi  (was %.0f)"
                      % ((e_bus - e_grade) * 1000 / dist_mi, e_bus * 1000 / dist_mi))
        else:
            print("  --- elevation: no usable MAP altimeter (no engine-off window) ---")

        # --- segments for the pooled road-load regression ----------------
        SEGLEN = 1000.0
        i0 = 0
        while True:
            j = i0
            while j < n - 1 and F["dist_m"][j] - F["dist_m"][i0] < SEGLEN:
                j += 1
            if j >= n - 1:
                break
            d = F["dist_m"][j] - F["dist_m"][i0]
            if d < SEGLEN * 0.9:
                break
            src = F["trac"] if F["p_trac_native"] else \
                [F["gene"][k] - F["pack"][k] for k in range(n)]
            E = integ(src[i0:j], dt)                       # J
            v = [F["kph"][k] / 3.6 for k in range(i0, j)]
            Sv = sum(vv ** 3 for vv in v) * dt             # int v^3 dt = int v^2 dx
            dke = 0.5 * (v[-1] ** 2 - v[0] ** 2) * MASS_KG
            dh = None
            if F["alt"] and F["alt"][i0] is not None and F["alt"][j] is not None:
                dh = F["alt"][j] - F["alt"][i0]
            vbar = d / ((j - i0) * dt)
            allsegs.append({"log": name, "d": d, "E": E, "Sv": Sv, "dke": dke,
                            "dh": dh, "vbar": vbar})
            i0 = j
    return allsegs


def phase_roadload(logs):
    segs = phase_energy(logs)
    print("\n" + "=" * 78)
    print("POOLED ROAD-LOAD REGRESSION  (%d segments of ~1 km)" % len(segs))
    print("Model:  E_seg = F0*d + k*int(v^2 dx) + c_up*mgdh+ + c_dn*mgdh- + c_ke*dKE")
    print("        level-road force F(v) = F0 + k*v^2   ->   Wh/mi = F(v)*1609.34/3600")

    def report(rows, cols, label):
        A = [[r[c] for c in cols] for r in rows]
        y = [r["E"] for r in rows]
        b = lstsq(A, y)
        if not b:
            print("  %s: singular" % label)
            return None
        pred = [sum(A[i][j] * b[j] for j in range(len(cols))) for i in range(len(A))]
        ssr = sum((y[i] - pred[i]) ** 2 for i in range(len(y)))
        ybar = sum(y) / len(y)
        sst = sum((v - ybar) ** 2 for v in y)
        print("\n  [%s]  n=%d  R2=%.3f" % (label, len(rows), 1 - ssr / sst))
        for c, bv in zip(cols, b):
            print("     %-8s %12.4f" % (c, bv))
        return b

    for r in segs:
        r["mgdh_up"] = max(r["dh"], 0) * MASS_KG * G if r["dh"] is not None else None
        r["mgdh_dn"] = min(r["dh"], 0) * MASS_KG * G if r["dh"] is not None else None

    b1 = report(segs, ["d", "Sv", "dke"], "no grade term (grade left in residual)")
    withdh = [r for r in segs if r["dh"] is not None]
    b2 = report(withdh, ["d", "Sv", "dke", "mgdh_up", "mgdh_dn"],
                "explicit grade term from MAP altimeter") if withdh else None

    for b, lbl in ((b1, "no-grade"), (b2, "grade-corrected")):
        if not b:
            continue
        print("\n  Level-road steady-speed consumption [%s]" % lbl)
        print("     %6s %10s %10s" % ("km/h", "mph", "Wh/mi"))
        for kph in (30, 40, 50, 60, 70, 80, 90, 100, 110):
            v = kph / 3.6
            F0 = b[0] + b[1] * v * v
            print("     %6d %10.0f %10.0f" % (kph, kph / KM_PER_MI, F0 * 1609.344 / 3600))



# --------------------------------------------------------------------------
# Phase 5 -- elevation-robust steady-cruise analysis
# --------------------------------------------------------------------------
#
# Rationale: a whole-trip Wh/mi is confounded by net elevation change and by
# how much stop-go cycling the route had.  Steady-cruise windows remove the
# cycling; grade is removed by taking the MEDIAN within each speed bin.  On a
# route that returns to its start the grade distribution is close to symmetric
# about zero, so the median cruise power at a given speed approximates the
# level-road value even though any individual window is on some slope.

WIN = 20          # s, cruise window length
V_MIN = 25.0      # km/h
V_SPREAD = 3.0    # km/h, max-min inside the window
V_DRIFT = 1.5     # km/h, |end-start|


def cruise_windows(F):
    n = len(F["t"])
    dt = F["dt"]
    W = int(WIN / dt)
    src = F["trac"] if F["p_trac_native"] else \
        [F["gene"][k] - F["pack"][k] for k in range(n)]
    out = []
    i = 0
    while i + W < n:
        v = F["kph"][i:i + W]
        if min(v) >= V_MIN and (max(v) - min(v)) <= V_SPREAD \
                and abs(v[-1] - v[0]) <= V_DRIFT:
            p = sum(src[i:i + W]) / W
            dh = None
            if F["alt"] and F["alt"][i] is not None and F["alt"][i + W] is not None:
                dh = F["alt"][i + W] - F["alt"][i]
            out.append({"v": sum(v) / W, "p": p, "dh": dh, "log": F["name"]})
            i += W
        else:
            i += 1
    return out


def phase_cruise(logs):
    allw = []
    for name in logs:
        F = build(name)
        w = cruise_windows(F)
        allw.extend(w)
        print("%-34s %4d cruise windows (%.0f s of steady cruise)"
              % (name, len(w), len(w) * WIN))

    print("\nCruise power binned by speed. Wh/mi = P/v.  Median is the")
    print("grade-robust estimator (up/down slopes cancel in the median).")
    print("%8s %5s %9s %9s %9s %9s" % ("km/h bin", "n", "P_med kW", "Wh/mi q1",
                                       "Wh/mi med", "Wh/mi q3"))
    pts = []
    for lo in range(20, 120, 10):
        b = [x for x in allw if lo <= x["v"] < lo + 10]
        if len(b) < 4:
            continue
        vm = sum(x["v"] for x in b) / len(b) / 3.6
        whs = sorted(x["p"] / (x["v"] / 3.6) * 0.44704 for x in b)
        pm = median([x["p"] for x in b])
        q1 = whs[len(whs) // 4]
        q3 = whs[len(whs) * 3 // 4]
        med = median(whs)
        print("%5d-%-3d %5d %9.2f %9.0f %9.0f %9.0f"
              % (lo, lo + 10, len(b), pm / 1000, q1, med, q3))
        pts.append((vm, med / 0.44704))     # (v m/s, force-equivalent N)

    if len(pts) >= 3:
        A = [[1.0, v * v] for v, _ in pts]
        y = [f for _, f in pts]
        b = lstsq(A, y)
        if b:
            print("\n  Fit F(v) = F0 + k*v^2  ->  F0 = %.0f N   k = %.3f kg/m" % (b[0], b[1]))
            print("  (implies Crr=%.4f at %.0f kg, and CdA=%.2f m^2 at rho=1.2,"
                  " both INCLUDING driveline+inverter losses)"
                  % (b[0] / (MASS_KG * G), MASS_KG, 2 * b[1] / 1.2))
            print("\n  Level-road steady-cruise consumption")
            print("  %6s %7s %10s" % ("km/h", "mph", "Wh/mi"))
            for kph in (40, 50, 60, 70, 80, 90, 100, 110):
                v = kph / 3.6
                print("  %6d %7.0f %10.0f" % (kph, kph / KM_PER_MI,
                                              (b[0] + b[1] * v * v) * 0.44704))

    # --- flat-only cross-check ------------------------------------------
    flat = [x for x in allw if x["dh"] == 0]
    if len(flat) > 10:
        print("\n  Cross-check: windows where the MAP altimeter shows dh=0")
        print("  %8s %5s %9s" % ("km/h bin", "n", "Wh/mi med"))
        for lo in range(20, 120, 10):
            b = [x for x in flat if lo <= x["v"] < lo + 10]
            if len(b) < 4:
                continue
            whs = [x["p"] / (x["v"] / 3.6) * 0.44704 for x in b]
            print("  %5d-%-3d %5d %9.0f" % (lo, lo + 10, len(b), median(whs)))


# --------------------------------------------------------------------------
# Phase 6 -- 0x598 power-average cross-check (settles the DBC signedness
#            conflict empirically against measured V*I)
# --------------------------------------------------------------------------

def phase_598(logs):
    for name in logs:
        S = load(name)
        if "p598_trac" not in S:
            print(name, "no 0x598"); continue
        F = build(name)
        f_pack, _ = zoh(F["p_pack_native"])
        f_trac = zoh(F["p_trac_native"])[0] if F["p_trac_native"] else None
        f_gene = zoh(F["p_gene_native"])[0] if F["p_gene_native"] else None
        print("=" * 78)
        print(name)
        for field, ref, sign in (("p598_ess", f_pack, -1.0),
                                 ("p598_trac", f_trac, 1.0),
                                 ("p598_gen", f_gene, 1.0)):
            if ref is None:
                continue
            raws = S[field]
            print("  %-10s raw min=%d max=%d" % (field, min(v for _, v in raws),
                                                 max(v for _, v in raws)))
            for label, conv in (("centered@32768", lambda r: (r - 32768) * 10.0),
                                ("signed int16", lambda r: ((r - 65536) if r >= 32768 else r) * 10.0)):
                xs, ys = [], []
                for t, r in raws:
                    xs.append(conv(r))
                    ys.append(sign * ref(t))
                nn = len(xs)
                mx = sum(xs) / nn
                my = sum(ys) / nn
                sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(nn))
                sxx = sum((x - mx) ** 2 for x in xs)
                syy = sum((y - my) ** 2 for y in ys)
                r_ = sxy / math.sqrt(sxx * syy) if sxx and syy else 0
                err = sum(abs(xs[i] - ys[i]) for i in range(nn)) / nn
                print("      %-15s r=%+.4f  mean|err|=%8.0f W  (vs V*I)"
                      % (label, r_, err))



# --------------------------------------------------------------------------
# Phase 7 -- final trip / window summary
# --------------------------------------------------------------------------
#
# Elevation strategy, after testing three options:
#
#   * 0x599 B2:B3 is a dead constant (103.0 kPa) -- NOT a live barometer.
#   * 0x2C3 MAP (B6, 0.5 kPa/count) IS a usable barometric altimeter whenever
#     the engine is off, which in an EREV is much of the time.  0.5 kPa is
#     ~42 m, i.e. ~0.34 kWh of potential energy at 3000 kg.  Spread over a
#     15-mile trip that is only ~22 Wh/mi -- negligible.  Spread over a 1 km
#     segment it is ~340 Wh/mi -- useless.  So the altimeter is trustworthy
#     at WHOLE-TRIP scale only, and per-segment grade correction is not
#     supportable with this data.
#   * Therefore: prefer trips that CLOSE (start pressure == end pressure).
#     Net grade energy is then zero by construction and no correction is
#     needed at all.

def window(F, t0=None, t1=None):
    n = len(F["t"])
    i0 = 0 if t0 is None else max(0, min(n - 1, int((t0 - F["t"][0]) / F["dt"])))
    i1 = n if t1 is None else max(i0 + 1, min(n, int((t1 - F["t"][0]) / F["dt"])))
    return i0, i1


def summarise(F, t0=None, t1=None, label=""):
    dt = F["dt"]
    i0, i1 = window(F, t0, t1)
    sl = slice(i0, i1)
    n = i1 - i0
    dur = n * dt
    dist_m = F["dist_m"][i1 - 1] - F["dist_m"][i0]
    mi = dist_m / 1000.0 / KM_PER_MI
    if mi < 0.3:
        print("  %s: too short (%.2f mi)" % (label, mi)); return

    pack = F["pack"][sl]
    gene = F["gene"][sl]
    trac = F["trac"][sl]
    kph = F["kph"][sl]

    e_bus = (-integ(pack, dt) + integ(gene, dt)) / 3.6e6
    e_trac = integ(trac, dt) / 3.6e6
    e_regen = -integ([min(p, 0) for p in trac], dt) / 3.6e6
    e_trac_out = integ([max(p, 0) for p in trac], dt) / 3.6e6
    e_aux = e_bus - e_trac
    moving = sum(1 for k in kph if k > 2.0) * dt

    dh = None
    if F["alt"] and F["alt"][i0] is not None and F["alt"][i1 - 1] is not None:
        dh = F["alt"][i1 - 1] - F["alt"][i0]

    print("  --- %s ---" % label)
    print("    %.2f mi (%.2f km) in %.1f min; moving %.0f%% of the time; avg %.1f km/h"
          % (mi, dist_m / 1000, dur / 60, 100 * moving / dur, dist_m / 1000 / (dur / 3600)))
    if dh is not None:
        print("    net elevation change %+.0f m  (grade energy %+.0f Wh/mi, +/-%.0f from"
              " 0.5 kPa quantisation)"
              % (dh, MASS_KG * G * dh / 3600 / mi, MASS_KG * G * 42.0 / 3600 / mi))
    else:
        print("    net elevation change UNKNOWN (no engine-off MAP window)")
    print("    energy from HV sources (battery net + generator): %.3f kWh" % e_bus)
    if F["p_trac_native"]:
        print("      traction inverter net %.3f kWh  (out %.3f, regen recovered %.3f = %.0f%%)"
              % (e_trac, e_trac_out, e_regen, 100 * e_regen / e_trac_out if e_trac_out else 0))
        print("      accessories (DCDC/AC/pumps) %.3f kWh = %.2f kW average"
              % (e_aux, e_aux * 3600 / dur))
    print("    >> %.0f Wh/mi  total at the HV bus (what the vehicle actually consumed)" % (e_bus * 1000 / mi))
    if F["p_trac_native"]:
        print("    >> %.0f Wh/mi  propulsion only (traction inverter, net of regen)"
              % (e_trac * 1000 / mi))


def phase_summary(specs):
    for spec in specs:
        parts = spec.split(":")
        name = parts[0]
        F = build(name)
        print("=" * 78)
        print("%s   [speed %s | distance %s | engine-rpm %s]"
              % (name, F["speed_src"], F["dist_src"], F["rpm_src"]))
        if len(parts) == 1:
            summarise(F, None, None, "whole log")
        else:
            summarise(F, None, None, "whole log")
            for w in parts[1:]:
                a, b = w.split("-")
                summarise(F, float(a), float(b), "window %s-%s s" % (a, b))



# --------------------------------------------------------------------------
# Phase 8 -- split a capture into TRIPS and summarise each
# --------------------------------------------------------------------------
#
# A logger session is not a trip.  Android sessions in particular routinely
# contain a drive followed by hours of parked wall-charging.  Charging makes
# `battery net + generator` go NEGATIVE, which scores as negative consumption
# and produces nonsense (-3069 Wh/mi on 20260503_192242).  It also shows up as
# a NEGATIVE accessory residual, which is physically impossible and is used
# below as an automatic validity check.
#
# A trip = a maximal run of movement, allowing stops of up to STOP_GAP seconds
# (traffic lights, brief errands) but cut at anything longer.

STOP_GAP = 300.0        # s of continuous standstill that ends a trip
MIN_TRIP_MI = 2.0


def find_trips(F):
    dt = F["dt"]
    n = len(F["t"])
    moving = [k > 2.0 for k in F["kph"]]
    trips = []
    i = 0
    while i < n:
        if not moving[i]:
            i += 1
            continue
        j = i
        last_move = i
        while j < n:
            if moving[j]:
                last_move = j
            elif (j - last_move) * dt > STOP_GAP:
                break
            j += 1
        trips.append((i, last_move + 1))
        i = j + 1
    return trips


def phase_trips(specs):
    rows = []
    for spec in specs:
        F = build(spec)
        trips = find_trips(F)
        print("=" * 78)
        print("%s   %d trip(s)" % (spec, len(trips)))
        for ti, (i0, i1) in enumerate(trips):
            dt = F["dt"]
            sl = slice(i0, i1)
            dur = (i1 - i0) * dt
            dist_m = F["dist_m"][i1 - 1] - F["dist_m"][i0]
            mi = dist_m / 1000.0 / KM_PER_MI
            if mi < MIN_TRIP_MI:
                continue
            e_bus = (-integ(F["pack"][sl], dt) + integ(F["gene"][sl], dt)) / 3.6e6
            e_trac = integ(F["trac"][sl], dt) / 3.6e6
            e_out = integ([max(p, 0) for p in F["trac"][sl]], dt) / 3.6e6
            e_reg = -integ([min(p, 0) for p in F["trac"][sl]], dt) / 3.6e6
            e_gen = integ(F["gene"][sl], dt) / 3.6e6
            aux = e_bus - e_trac
            dh = None
            if F["alt"] and F["alt"][i0] is not None and F["alt"][i1 - 1] is not None:
                dh = F["alt"][i1 - 1] - F["alt"][i0]
            grade_whmi = MASS_KG * G * dh / 3600 / mi if dh is not None else None
            ok = "ok" if (F["p_trac_native"] and 0 < aux < 10) else \
                 ("CHECK" if F["p_trac_native"] else "no-trac-chan")
            rows.append({"spec": spec, "trip": ti, "mi": mi, "min": dur / 60,
                         "kph": dist_m / 1000 / (dur / 3600), "e_bus": e_bus,
                         "e_trac": e_trac, "e_gen": e_gen, "aux_kw": aux * 3600 / dur,
                         "regen": e_reg / e_out if e_out else 0,
                         "whmi": e_bus * 1000 / mi,
                         "whmi_prop": e_trac * 1000 / mi if F["p_trac_native"] else None,
                         "dh": dh, "grade_whmi": grade_whmi, "ok": ok})
            print("  trip %d: %6.1f mi %6.1f min %5.1f km/h | %7.0f Wh/mi | aux %+5.2f kW"
                  " | regen %3.0f%% | gen %6.2f kWh | dh %s | %s"
                  % (ti, mi, dur / 60, rows[-1]["kph"], rows[-1]["whmi"],
                     rows[-1]["aux_kw"], 100 * rows[-1]["regen"], e_gen,
                     ("%+5.0f m" % dh) if dh is not None else "  n/a ", ok))

    good = [r for r in rows if r["ok"] == "ok"]
    print("\n" + "=" * 78)
    print("%d trips >= %.0f mi; %d with a valid power balance (0 < aux < 10 kW)"
          % (len(rows), MIN_TRIP_MI, len(good)))
    if good:
        tm = sum(r["mi"] for r in good)
        te = sum(r["e_bus"] for r in good)
        print("  AGGREGATE over valid trips: %.1f mi, %.2f kWh -> %.0f Wh/mi"
              % (tm, te, te * 1000 / tm))
        flat = [r for r in good if r["dh"] is not None and abs(r["grade_whmi"]) < 25]
        if flat:
            fm = sum(r["mi"] for r in flat)
            fe = sum(r["e_bus"] for r in flat)
            print("  ELEVATION-NEUTRAL subset (|grade| < 25 Wh/mi, %d trips):"
                  " %.1f mi, %.2f kWh -> %.0f Wh/mi" % (len(flat), fm, fe, fe * 1000 / fm))
        corr = [r for r in good if r["dh"] is not None]
        if corr:
            cm = sum(r["mi"] for r in corr)
            ce = sum(r["e_bus"] - MASS_KG * G * r["dh"] / 3.6e6 for r in corr)
            raw = sum(r["e_bus"] for r in corr)
            print("  GRADE-CORRECTED (all %d trips with an altimeter): %.1f mi,"
                  " %.2f kWh -> %.0f Wh/mi   (uncorrected %.0f)"
                  % (len(corr), cm, ce, ce * 1000 / cm, raw * 1000 / cm))
    (ART / "whpm_trips.json").write_text(json.dumps(rows, indent=1))
    print("\n  wrote projects/vtrux/notes/artifacts/whpm_trips.json")



# --------------------------------------------------------------------------
# Phase 9 -- fuel to electricity efficiency (Wh per gallon)
# --------------------------------------------------------------------------
#
# Numerator:   generator electrical energy onto the HV bus, 0x482 V*I.
# Denominator: gasoline burned, from 0x3D1 Instantaneous_Fuel_Consumption_Rate
#              (12-bit Motorola, 0.025 L/hr, OBD bus) integrated over the trip.
#
# ETHANOL NORMALISATION follows `projects/vtrux/notes/Vtrux Gas.xlsx` sheet 1
# exactly, so results are comparable with the user's own fuel tracking:
#
#     F = ( E*B*ETH_LHV + E*(1-B) ) / BASE_ENERGY
#     BASE_ENERGY = (1 - BASE_ETH) + BASE_ETH*ETH_LHV
#
# where E = gallons as pumped, B = alcohol fraction, and F = gallons expressed
# as energy-equivalent baseline-E8 gallons.  Verified against the sheet: with
# ETH_LHV=0.669 and BASE_ETH=0.08, BASE_ENERGY=0.97352, matching cell M11.
# 0.669 also matches the real ethanol/gasoline LHV ratio (76,100/114,000 BTU).

ETH_LHV = 0.669          # Vtrux Gas.xlsx M9 -- ethanol energy content vs gasoline
BASE_ETH = 0.08          # Vtrux Gas.xlsx M10 -- baseline pump-gas ethanol fraction
BASE_ENERGY = (1 - BASE_ETH) + BASE_ETH * ETH_LHV      # = M11 = 0.97352
L_PER_GAL = 3.785411784
GAL_LHV_KWH = 33.705     # E0 gasoline, EPA MPGe constant


def equiv_gallons(gal_pumped, eth_frac):
    """Vtrux Gas.xlsx column F -- normalise any blend to baseline-E8 gallons."""
    return (gal_pumped * eth_frac * ETH_LHV
            + gal_pumped * (1 - eth_frac)) / BASE_ENERGY


def phase_fuel(specs):
    rows = []
    for spec in specs:
        S = load(spec)
        if "fuel_lph" not in S:
            print("%-28s no 0x3D1 fuel rate on the OBD bus" % spec)
            continue
        F = build(spec)
        dt, n = F["dt"], len(F["t"])
        f_lph, _ = zoh(S["fuel_lph"])
        lph = [f_lph(t) for t in F["t"]]

        # ethanol content as reported by the flex-fuel sensor
        eth = None
        if "eth_pct" in S:
            vv = [v for _, v in S["eth_pct"]]
            valid = [v for _, v in S.get("eth_valid", [])]
            adapt = [v for _, v in S.get("eth_adapt", [])]
            eth = {"med": median(vv), "min": min(vv), "max": max(vv),
                   "uniq": len(set(vv)),
                   "valid_frac": (sum(1 for v in valid if v == 0) / len(valid)) if valid else None,
                   "adapt_frac": (sum(1 for v in adapt if v) / len(adapt)) if adapt else None}

        print("=" * 78)
        print(spec)
        if eth:
            print("  0x3FB Fuel_Alcohol_Composition: median %.1f%%  range %.1f-%.1f%%"
                  "  unique %d  validity-0 %s  adapting %s"
                  % (eth["med"], eth["min"], eth["max"], eth["uniq"],
                     ("%.0f%%" % (100 * eth["valid_frac"])) if eth["valid_frac"] is not None else "n/a",
                     ("%.0f%%" % (100 * eth["adapt_frac"])) if eth["adapt_frac"] is not None else "n/a"))

        # tank-level cross-check
        if "fuel_pct" in S and "fuel_cap" in S:
            pv = [v for _, v in S["fuel_pct"]]
            cap = median([v for _, v in S["fuel_cap"]])
            print("  0x4D1 tank: %.1f%% -> %.1f%% of %.1f L capacity  => %.2f L drop"
                  % (pv[0], pv[-1], cap, (pv[0] - pv[-1]) / 100.0 * cap))

        for ti, (i0, i1) in enumerate(find_trips(F)):
            dur = (i1 - i0) * dt
            mi = (F["dist_m"][i1 - 1] - F["dist_m"][i0]) / 1000.0 / KM_PER_MI
            if mi < MIN_TRIP_MI:
                continue
            litres = sum(lph[i0:i1]) * dt / 3600.0
            gal = litres / L_PER_GAL
            e_gen = integ(F["gene"][i0:i1], dt) / 3.6e6
            e_bus = (-integ(F["pack"][i0:i1], dt) + integ(F["gene"][i0:i1], dt)) / 3.6e6
            on = sum(1 for x in F["eng_on"][i0:i1] if x) * dt
            if gal < 0.05 or e_gen < 0.5:
                print("  trip %d: %.1f mi -- negligible engine use (%.2f gal, %.2f kWh gen)"
                      % (ti, mi, gal, e_gen))
                continue
            # Blend must be weighted by fuel actually burned, not by time and
            # not by a session median -- 20260724_211556 refuels mid-trip and
            # its composition steps 29% -> 68% partway through.
            if "eth_pct" in S:
                f_eth, _ = zoh(S["eth_pct"])
                num = sum(f_eth(F["t"][k]) * lph[k] for k in range(i0, i1))
                den = sum(lph[k] for k in range(i0, i1))
                ef = (num / den / 100.0) if den > 0 else BASE_ETH
            else:
                ef = BASE_ETH
            gal_e8 = equiv_gallons(gal, ef)
            whgal = e_gen * 1000 / gal
            whgal_e8 = e_gen * 1000 / gal_e8
            eff = e_gen / (gal_e8 * BASE_ENERGY * GAL_LHV_KWH)
            rows.append({"spec": spec, "trip": ti, "mi": mi, "gal": gal,
                         "gal_e8": gal_e8, "e_gen": e_gen, "e_bus": e_bus,
                         "whgal_e8": whgal_e8, "eff": eff, "eth": ef,
                         "whgal_raw": whgal,
                         "eng_min": on / 60})
            print("  trip %d: %5.1f mi | engine on %5.1f min | %6.3f gal (%6.3f E8-equiv)"
                  " | gen %6.2f kWh | %6.0f Wh/gal | %6.0f Wh/gal-E8 | eta %.1f%%"
                  % (ti, mi, on / 60, gal, gal_e8, e_gen, whgal, whgal_e8, 100 * eff))

    if rows:
        tg = sum(r["gal_e8"] for r in rows)
        te = sum(r["e_gen"] for r in rows)
        tmi = sum(r["mi"] for r in rows)
        tbus = sum(r["e_bus"] for r in rows)
        print("\n" + "=" * 78)
        print("AGGREGATE over %d engine-run trips" % len(rows))
        print("  %.1f mi | %.2f E8-equiv gal | %.2f kWh generated" % (tmi, tg, te))
        print("  >> %.0f Wh per baseline-E8 gallon" % (te * 1000 / tg))
        print("  >> tank-to-HV-bus efficiency %.1f%% (vs %.1f kWh/gal E0 LHV)"
              % (100 * te / (tg * BASE_ENERGY * GAL_LHV_KWH), GAL_LHV_KWH))
        # In charge-sustaining mode every mile is ultimately paid for with fuel,
        # so mpg = (Wh per gallon) / (Wh per mile).
        whmi = tbus * 1000 / tmi
        print("  >> these trips consumed %.0f Wh/mi at the HV bus" % whmi)
        print("  >> implied charge-sustaining economy: %.1f mpg (E8-equivalent),"
              " i.e. running purely on fuel with no grid charge"
              % ((te * 1000 / tg) / whmi))
        def cv(key):
            xs = [r[key] for r in rows]
            m = sum(xs) / len(xs)
            sd = (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
            return m, sd, 100 * sd / m
        print("\n  Does the ethanol normalisation help? (spread across the %d trips)"
              % len(rows))
        for key, lbl in (("whgal_raw", "Wh per gallon as pumped"),
                         ("whgal_e8", "Wh per baseline-E8 gallon"),
                         ("eff", "tank-to-bus efficiency")):
            m, sd, c = cv(key)
            print("    %-28s mean %9.4f  sd %8.4f  CV %5.1f%%" % (lbl, m, sd, c))
    (ART / "whpm_fuel.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "recon"
    logs = sys.argv[2:]
    if phase == "recon":
        phase_recon(logs)
    elif phase == "extract":
        phase_extract(logs)
    elif phase == "check":
        phase_check(logs)
    elif phase == "energy":
        phase_energy(logs)
    elif phase == "roadload":
        phase_roadload(logs)
    elif phase == "cruise":
        phase_cruise(logs)
    elif phase == "p598":
        phase_598(logs)
    elif phase == "summary":
        phase_summary(logs)
    elif phase == "trips":
        phase_trips(logs)
    elif phase == "fuel":
        phase_fuel(logs)
    else:
        print("unknown phase", phase)
