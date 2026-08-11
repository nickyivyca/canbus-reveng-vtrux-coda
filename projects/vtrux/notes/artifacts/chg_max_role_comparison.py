import sys, struct
sys.path.insert(0, ".")
import cantools
from canre.parsers import parse_file

db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")

LOGS = {
    "DRIVE (currentlimitingtest)": "projects/vtrux/logs/vtruxcurrentlimitingtest.log",
    "CHARGE S3-T10 (Android newcharger)": "<home>/<drive-root>/<library>/My Libraries/CANLogs/VtruxLogs/vtrux_20260503_192242_T10.log",
    "CHARGE newcharger_part2 (laptop)": "projects/vtrux/logs/vtrux_newcharger_part2.log",
}

SAMPLE_INTERVAL = 30.0

for label, path in LOGS.items():
    print(f"\n{'='*70}")
    print(f"LOG: {label}")
    print(f"{'='*70}")

    chg_max_vals = []
    dis_max_vals = []
    b2_412_vals = []
    samples = []

    frames = list(parse_file(path))
    t0 = frames[0].timestamp

    last_chg = None
    last_dis = None
    last_b2 = None
    prev_sample_t = -SAMPLE_INTERVAL

    for frame in frames:
        t = frame.timestamp - t0
        arb = frame.arbitration_id
        data = bytes(frame.data)

        if arb == 0x420:
            try:
                dec = db.decode_message(0x420, data)
                last_chg = dec["bcm_chg_max"]
                last_dis = dec["bcm_dis_max"]
                chg_max_vals.append(last_chg)
                dis_max_vals.append(last_dis)
            except Exception:
                pass

        elif arb == 0x412:
            if len(data) >= 3:
                last_b2 = data[2]
                b2_412_vals.append(last_b2)

        if t - prev_sample_t >= SAMPLE_INTERVAL:
            samples.append((t, last_chg, last_dis, last_b2))
            prev_sample_t = t

    if chg_max_vals:
        print(f"  bcm_chg_max: min={min(chg_max_vals):.2f}A  max={max(chg_max_vals):.2f}A  mean={sum(chg_max_vals)/len(chg_max_vals):.2f}A  ({len(chg_max_vals)} samples)")
    else:
        print("  bcm_chg_max: (no 0x420 frames)")

    if dis_max_vals:
        print(f"  bcm_dis_max: min={min(dis_max_vals):.2f}A  max={max(dis_max_vals):.2f}A  mean={sum(dis_max_vals)/len(dis_max_vals):.2f}A")
    else:
        print("  bcm_dis_max: (no 0x420 frames)")

    if b2_412_vals:
        print(f"  0x412 B2:    min={min(b2_412_vals)}  max={max(b2_412_vals)}  mean={sum(b2_412_vals)/len(b2_412_vals):.1f}  ({len(b2_412_vals)} samples)")
    else:
        print("  0x412 B2:    (no 0x412 frames)")

    print(f"\n  {'t(s)':>7}  {'chg_max':>9}  {'dis_max':>9}  {'0x412_B2':>10}")
    print(f"  {'-'*7}  {'-'*9}  {'-'*9}  {'-'*10}")
    for t, chg, dis, b2 in samples[:20]:
        chg_s = f"{chg:.2f}A" if chg is not None else "  ---  "
        dis_s = f"{dis:.2f}A" if dis is not None else "  ---  "
        b2_s  = str(b2) if b2 is not None else "  ---  "
        print(f"  {t:7.1f}  {chg_s:>9}  {dis_s:>9}  {b2_s:>10}")
