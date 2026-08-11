"""Cross-session battery-cooling threshold check, directly on the RAW android logs.

Unlike the InfluxDB check, the raw logs carry the actual cooling signal
(0x506 B0 bit5 == 0x508 presence), so we test the trigger directly instead of via
the 12V-current proxy.

Model under test: cooling engages when HV path is active (charging OR driving,
|ibat|>3A) AND cell tmax crosses ~38C on / ~36.5C off (thermostat + hysteresis).

Signals (epri-pt-bus.dbc): 0x410 bcm_ibat/bcm_soc, 0x430 bcm_cell_tmax/tmin,
0x506 B0 bit5 (cooling state), 0x508 presence (corroborates), 0x18FFD6B3
DCDC_LV_Curr (12V load, corroborates).

Phase A: parse each gap session (grep-prefiltered), sample at ~1 Hz on the 0x430
clock, cache to CSV.  Phase B: aggregate P(cooling | tmax) by HV state; per-session
first-cooling-on tmax vs max tmax while cooling off.
"""
import sys
sys.path.insert(0, ".")

import os
import glob
import csv
import subprocess

import cantools

from battery_fan_signature import parse_header_time, decode_line

LOG_DIR = "<home>/Seafile/CANLogs/VtruxLogs"
ART = "projects/vtrux/notes/artifacts"
CACHE = os.path.join(ART, "cooling_xsession_samples.csv")

RUN_PARSE = False   # set False to re-analyze from cache
MIN_MB = 20        # skip sessions smaller than this

GAP_DATES = ["20260425", "20260503", "20260504", "20260509", "20260512",
             "20260513", "20260514", "20260606", "20260609", "20260610",
             "20260611", "20260614", "20260617", "20260618", "20260627",
             "20260714"]

db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
M410 = db.get_message_by_frame_id(0x410)
M430 = db.get_message_by_frame_id(0x430)
MDCDC = db.get_message_by_frame_id(0x18FFD6B3)


def gap_sessions():
    out = []
    for d in GAP_DATES:
        prefixes = sorted(set(
            f.rsplit("_T", 1)[0]
            for f in glob.glob(os.path.join(LOG_DIR, f"vtrux_{d}_*_T*.log"))))
        for pfx in prefixes:
            files = sorted(glob.glob(pfx + "_T*.log"),
                           key=lambda f: int(f.rsplit("_T", 1)[1].split(".")[0]))
            size = sum(os.path.getsize(f) for f in files)
            if size >= MIN_MB * 1024 * 1024:
                out.append((os.path.basename(pfx), files))
    return out


def parse_session(name, files):
    """Return list of ~1Hz samples: (t_epoch, tmax, tmin, ibat, soc, cool, lv)."""
    last_ibat = last_soc = last_lv = None
    last_cool = 0
    last_508 = None
    samples = []
    last_emit = None
    for path in files:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(["grep", "-hE", " 0x(410|430|506|508|18FFD6B3) ", path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if arb == 0x410:
                try:
                    s = M410.decode(data, allow_truncated=True)
                    last_ibat = s.get("bcm_ibat"); last_soc = s.get("bcm_soc")
                except Exception:
                    pass
            elif arb == 0x506 and len(data) >= 1:
                last_cool = (data[0] >> 5) & 1
            elif arb == 0x508:
                last_508 = t
            elif arb == 0x18FFD6B3:
                try:
                    last_lv = MDCDC.decode(data, allow_truncated=True).get("DCDC_LV_Curr")
                except Exception:
                    pass
            elif arb == 0x430:
                try:
                    s = M430.decode(data, allow_truncated=True)
                    tmax = s.get("bcm_cell_tmax"); tmin = s.get("bcm_cell_tmin")
                except Exception:
                    continue
                if tmax is None or tmax < -30 or tmax > 80:
                    continue
                ep = t.timestamp()
                if last_emit is not None and ep - last_emit < 1.0:
                    continue
                last_emit = ep
                p508 = 1 if (last_508 is not None and (t - last_508).total_seconds() < 3) else 0
                samples.append((round(ep, 1), tmax, tmin, last_ibat, last_soc,
                                last_cool, p508, last_lv))
    return samples


def phase_parse():
    sess = gap_sessions()
    print(f"Phase A: {len(sess)} gap sessions >= {MIN_MB}MB")
    with open(CACHE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["session", "t", "tmax", "tmin", "ibat", "soc", "cool", "p508", "lv"])
        for i, (name, files) in enumerate(sess):
            samples = parse_session(name, files)
            for s in samples:
                w.writerow([name, *s])
            nblank = sum(1 for s in samples if s[3] is None)
            print(f"  [{i+1}/{len(sess)}] {name}: {len(samples)} samples "
                  f"({nblank} w/o ibat)")
    print("Phase A done ->", CACHE)


def phase_analyze():
    from collections import defaultdict
    rows = []
    with open(CACHE) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    print(f"\nPhase B: {len(rows)} cached samples")

    def fnum(x):
        return float(x) if x not in (None, "", "None") else None

    bins = defaultdict(lambda: [0, 0])       # tmax -> [cool, total], HV-active
    bins_chg = defaultdict(lambda: [0, 0])
    bins_drv = defaultdict(lambda: [0, 0])
    per = defaultdict(lambda: [None, None])  # session -> [first_on_tmax, max_off_tmax]
    p508_agree = [0, 0]

    for r in rows:
        tmax = fnum(r["tmax"]); ibat = fnum(r["ibat"])
        if tmax is None or ibat is None:
            continue
        cool = int(r["cool"]); p508 = int(r["p508"])
        p508_agree[0] += 1 if cool == p508 else 0
        p508_agree[1] += 1
        if abs(ibat) <= 3:          # HV idle -> cooling gated off; skip
            continue
        tb = round(tmax * 2) / 2
        b = bins[tb]; b[1] += 1; b[0] += cool
        if ibat > 3:
            c = bins_chg[tb]; c[1] += 1; c[0] += cool
        else:
            dv = bins_drv[tb]; dv[1] += 1; dv[0] += cool
        s = r["session"]
        if cool and per[s][0] is None:
            per[s][0] = tmax
        if not cool and ibat > 3:   # max tmax seen while cooling OFF during charge
            if per[s][1] is None or tmax > per[s][1]:
                per[s][1] = tmax

    print(f"0x506-bit5 vs 0x508-presence agreement: "
          f"{100*p508_agree[0]/max(1,p508_agree[1]):.1f}%")

    def show(title, b):
        print(f"\n=== P(cooling | tmax) — {title} ===")
        print(f"{'tmax':>6} {'cool':>6} {'total':>6} {'P':>6}")
        for tb in sorted(b):
            c, t = b[tb]
            if t < 10:
                continue
            print(f"{tb:6.1f} {c:6d} {t:6d} {100*c/t:5.0f}%")

    show("HV-active (charge or drive)", bins)
    show("CHARGING only (ibat>3)", bins_chg)
    show("DRIVING only (ibat<-3)", bins_drv)

    print("\n=== per session: tmax at first cooling-ON vs max tmax while OFF(charging) ===")
    print(f"{'session':32} {'first_on':>9} {'max_off':>8}")
    for s in sorted(per):
        on, off = per[s]
        print(f"{s:32} {('%.1f'%on) if on else '-':>9} {('%.1f'%off) if off else '-':>8}")


if __name__ == "__main__":
    if RUN_PARSE:
        phase_parse()
    phase_analyze()
