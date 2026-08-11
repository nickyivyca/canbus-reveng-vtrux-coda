"""Three probes on loop->pack passive heating:
 Q1 spread: if heat enters from one corner (loop cold-plate), tmax leads tmin ->
    tmax-tmin SPREAD should widen while heating, narrow as it equilibrates.
 Q2 summer: is the same passive heating present in summer (pre-cooling charge)?
 Q3 ambient: what real ambient do we actually have?  Winter logs are PT-bus only
    (no ECM OutsideAirTemp); the Bel 0x18FFD5C0 B4-B5 is a BDC *component* temp, not
    true ambient. Summer session has real ECM_OutsideAirTemp (0x4C1).
"""
import sys
sys.path.insert(0, ".")

import glob
import struct
import subprocess
import statistics as st

import cantools

from battery_fan_signature import parse_header_time, decode_line

pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
M410 = pt.get_message_by_frame_id(0x410)
M430 = pt.get_message_by_frame_id(0x430)
bel = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc")
try:
    MBEL = bel.get_message_by_frame_id(0x18FFD5C0)
    BELSIG = [s.name for s in MBEL.signals]
except Exception:
    MBEL, BELSIG = None, []


def parse_winter(glob_pat, label):
    files = sorted(glob.glob(glob_pat),
                   key=lambda f: int(f.rsplit("_T", 1)[1].split(".")[0]))
    rows = []
    last = dict(ibat=None, pe=None, belamb=None)
    last_emit = None
    for path in files:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(["grep", "-hE", " 0x(410|430|18FFD5C0|18FFD6B3) ", path],
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
            elif arb == 0x18FFD6B3 and len(data) >= 8:
                last["pe"] = struct.unpack("<h", bytes(data[6:8]))[0] * 0.1
            elif arb == 0x18FFD5C0 and MBEL and len(data) >= 6:
                try:
                    d = MBEL.decode(data, allow_truncated=True)
                    for k in ("BELINV_ambientTemperature", "ambientTemperature"):
                        if k in d:
                            last["belamb"] = d[k]; break
                except Exception:
                    pass
            elif arb == 0x430:
                try:
                    s = M430.decode(data, allow_truncated=True)
                    tmax = s.get("bcm_cell_tmax"); tmin = s.get("bcm_cell_tmin")
                except Exception:
                    continue
                if tmax is None or tmin is None or tmax < -30 or tmax > 80:
                    continue
                ep = t.timestamp()
                if last_emit is not None and ep - last_emit < 10:
                    continue
                last_emit = ep
                rows.append((ep, tmax, tmin, last["ibat"], last["pe"], last["belamb"]))

    t0 = rows[0][0]
    print(f"\n===== {label} =====")
    print(f"Bel 0x18FFD5C0 signals: {BELSIG}")
    belv = [r[5] for r in rows if r[5] is not None]
    if belv:
        print(f"Bel B4-B5 temp (BDC/'ambient' field): {min(belv):.1f}..{max(belv):.1f} C "
              f"(coldest {min(belv):.1f} = rough ambient floor; NOTE component temp, not true ambient)")
    print("Q1 SPREAD during heating -- (h, tmax, tmin, spread, PEloop, ibat):")
    step = max(1, len(rows) // 16)
    for i in range(0, len(rows), step):
        t, tmax, tmin, ib, pe, ba = rows[i]
        pes = f"{pe:5.1f}" if pe is not None else "  ?  "
        ibs = f"{ib:5.0f}" if ib is not None else "  ?  "
        print(f"   {(t-t0)/3600:4.1f}h  tmax={tmax:5.1f} tmin={tmin:5.1f}  "
              f"spread={tmax-tmin:4.1f}  PE={pes}  ib={ibs}")
    heating = [r for r in rows if r[3] is not None and r[3] > 5]
    if heating:
        sp = [r[1] - r[2] for r in heating]
        print(f"  spread during charging: {min(sp):.1f}..{max(sp):.1f} C "
              f"(start-of-session spread {rows[0][1]-rows[0][2]:.1f})")


def summer_from_cache():
    import csv
    rows = []
    with open("projects/vtrux/notes/artifacts/thermal_model_samples.csv") as f:
        for r in csv.DictReader(f):
            if r["session"] != "vtrux_20260714_161319":
                continue
            def fn(x): return float(x) if x not in ("", "None", None) else None
            rows.append((fn(r["t"]), fn(r["tmax"]), fn(r["tmin"]), fn(r["ibat"]),
                         int(r["cool"]), fn(r["oat"]), fn(r["pe"])))
    rows = [r for r in rows if r[1] is not None]
    rows.sort()
    t0 = rows[0][0]
    print("\n===== SUMMER 20260714 (has REAL ECM OutsideAirTemp) =====")
    oats = [r[5] for r in rows if r[5] is not None]
    print(f"REAL ambient (ECM OutsideAirTemp): {min(oats):.1f}..{max(oats):.1f} C")
    # pre-cooling charge window: charging, cooling OFF, before cooling first engages
    chg_off = [r for r in rows if r[3] is not None and r[3] > 5 and r[4] == 0]
    if chg_off:
        print(f"Q2 pre-cooling charge (ibat>5, cooling OFF): {len(chg_off)} samples")
        print(f"  pack tmax {chg_off[0][1]:.1f}->{chg_off[-1][1]:.1f} C, "
              f"loop {chg_off[0][6]:.1f}->{chg_off[-1][6]:.1f} C")
        gaps = [r[6] - (r[1] + r[2]) / 2 for r in chg_off if r[6] is not None]
        print(f"  loop-pack gap: mean {st.mean(gaps):+.1f} C  -> passive heating gradient present in summer too")
        sp = [r[1] - r[2] for r in chg_off]
        print(f"  spread over this window: {sp[0]:.1f} -> {max(sp):.1f} C (widens as pack heats from loop side)")
    print("  sampled (h, tmax, tmin, spread, loop, OAT, cool):")
    step = max(1, len(rows) // 16)
    for i in range(0, len(rows), step):
        t, tmax, tmin, ib, cool, oat, pe = rows[i]
        pes = f"{pe:5.1f}" if pe is not None else "  ?  "
        oa = f"{oat:5.1f}" if oat is not None else "  ?  "
        print(f"   {(t-t0)/3600:4.1f}h tmax={tmax:5.1f} tmin={tmin:5.1f} spread={tmax-tmin:4.1f} "
              f"loop={pes} OAT={oa} cool={cool}")


if __name__ == "__main__":
    base = "projects/vtrux/logs/after-battery-swap-charges"
    parse_winter(f"{base}/another_M0_T*.log", "another_M0 (Jan 23, cold start 12C)")
    summer_from_cache()
