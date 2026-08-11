"""Winter (Jan 2026, post-swap pack) loop-heat availability analysis.

Quantifies, for cold-weather charge sessions:
  - how cold the pack is (tmax/tmin; coldest tmin ~ ambient proxy)
  - PE-loop temp (DCDC HW temp, 0x18FFD6B3 B6-B7 signed x0.1 C) during charging
  - loop - pack delta (the driving force for a raw water/air heat-exchanger heating mod)
  - whether cooling (0x506 bit5) ever engages (expected: never, pack too cold)
  - pack self-heating over the charge

Context: the Bel charger has ~500 W fixed loss dumped into the PE loop during
charging regardless of season, so the loop should sit a fixed increment above
ambient even in winter -> usable heating gradient into a cold pack.
"""
import sys
sys.path.insert(0, ".")

import glob
import struct
import subprocess

import cantools

from battery_fan_signature import parse_header_time, decode_line

pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
M410 = pt.get_message_by_frame_id(0x410)
M430 = pt.get_message_by_frame_id(0x430)
MDCDC = pt.get_message_by_frame_id(0x18FFD6B3)


def analyze(glob_pat, label):
    files = sorted(glob.glob(glob_pat),
                   key=lambda f: int(f.rsplit("_T", 1)[1].split(".")[0]))
    rows = []   # (t, tmax, tmin, ibat, cool, pe, lv)
    last = dict(ibat=None, cool=0, pe=None, lv=None)
    last_emit = None
    for path in files:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(["grep", "-hE", " 0x(410|430|506|18FFD6B3) ", path],
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
            elif arb == 0x18FFD6B3 and len(data) >= 8:
                last["pe"] = struct.unpack("<h", bytes(data[6:8]))[0] * 0.1
                try:
                    last["lv"] = MDCDC.decode(data, allow_truncated=True).get("DCDC_LV_Curr")
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
                if last_emit is not None and ep - last_emit < 5.0:
                    continue
                last_emit = ep
                rows.append((ep, tmax, tmin, last["ibat"], last["cool"],
                             last["pe"], last["lv"]))
    if not rows:
        print(f"{label}: no data"); return
    t0 = rows[0][0]
    dur = (rows[-1][0] - t0) / 3600
    tmaxs = [r[1] for r in rows]; tmins = [r[2] for r in rows]
    pes = [r[5] for r in rows if r[5] is not None]
    cools = [r[4] for r in rows]
    chg = [r for r in rows if r[3] is not None and r[3] > 5]
    print(f"\n===== {label} =====")
    print(f"duration {dur:.1f} h, {len(rows)} samples")
    print(f"pack tmax {min(tmaxs):.1f}->{max(tmaxs):.1f} C  (start {rows[0][1]:.1f}, end {rows[-1][1]:.1f})")
    print(f"pack tmin {min(tmins):.1f}->{max(tmins):.1f} C  (coldest {min(tmins):.1f} ~ ambient proxy)")
    print(f"PE loop temp {min(pes):.1f}..{max(pes):.1f} C" if pes else "no PE temp")
    print(f"cooling (0x506 bit5) on-fraction: {100*sum(cools)/len(cools):.1f}%")
    import statistics as st
    lvs = [r[6] for r in rows if r[6] is not None]
    if lvs:
        hi = [v for v in lvs if v > 30]
        print(f"12V load DCDC_LV_Curr: median {st.median(lvs):.1f} A, "
              f"max {max(lvs):.1f} A, fraction >30A: {100*len(hi)/len(lvs):.1f}% "
              f"(summer cooling-ON baseline was ~100A vs ~6A off)")
    if chg:
        loopdt = [r[5] - (r[1] + r[2]) / 2 for r in chg if r[5] is not None]
        print(f"during CHARGING (ibat>5): {len(chg)} samples")
        if loopdt:
            print(f"  loop - pack(mean) delta: mean {st.mean(loopdt):+.1f} C  "
                  f"(min {min(loopdt):+.1f}, max {max(loopdt):+.1f})")
        chlv = [r[6] for r in chg if r[6] is not None]
        if chlv:
            print(f"  12V load while charging: median {st.median(chlv):.1f} A, "
                  f"max {max(chlv):.1f} A")
    print("  timeline (h, tmax, tmin, PEloop, dloop, ibat, cool, 12V-load):")
    step = max(1, len(rows) // 18)
    for i in range(0, len(rows), step):
        t, tmax, tmin, ib, cool, pe, lv = rows[i]
        pmean = (tmax + tmin) / 2
        pes_ = f"{pe:5.1f}" if pe is not None else "  ?  "
        dl = f"{pe - pmean:+5.1f}" if pe is not None else "  ?  "
        ibs = f"{ib:6.0f}" if ib is not None else "   ?  "
        lvs_ = f"{lv:5.1f}A" if lv is not None else "  ?  "
        print(f"    {(t-t0)/3600:4.1f}h  tmax={tmax:5.1f} tmin={tmin:5.1f}  "
              f"PE={pes_} dloop={dl}  ib={ibs} cool={cool}  12V={lvs_}")


if __name__ == "__main__":
    base = "projects/vtrux/logs/after-battery-swap-charges"
    analyze(f"{base}/charge_M0_T*.log", "charge_M0 (Jan 16-17, winter charge)")
    analyze(f"{base}/another_M0_T*.log", "another_M0 (Jan 23, winter charge)")
