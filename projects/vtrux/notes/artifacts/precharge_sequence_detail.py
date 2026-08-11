"""
Zoom in on the CLOSE_MAINN failure vs. success in vtrux_partstruck_chargeagain2.log.
Pulls vbus_pos, vbus_neg, mainc_stat, alarm, epo, hvil, ibat, vbat, and iso_r
in a window around each CLOSE_MAINR start event.
Also dumps 0x440 raw bytes and 0x410 raw bytes in those windows.
"""
import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file as parse_log
import cantools

LOG = "projects/vtrux/logs/vtrux_partstruck_chargeagain2.log"
DBC = "projects/vtrux/epri-pt-bus.dbc"

db = cantools.db.load_file(DBC)

MAINC_STAT_STATES = [
    "ALL_OPEN",
    "FAILED_MAINP_OR_R_WELD",
    "CLOSE_MAINR",
    "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD",
    "CLOSE_MAINN",
    "FAILED_MAINN_OPEN",
    "WAIT_PRECHARGE",
    "CLOSE_MAINP",
    "OPEN_MAINR",
    "FAILED_MAINP_OPEN",
    "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE",
    "SHUTDOWN_REQUEST",
    "ALL_OPEN_SHUTDOWN",
    "(idx15)",
]

frames = list(parse_log(LOG))
print(f"Loaded {len(frames)} frames, t_start={frames[0].timestamp:.3f}s, t_end={frames[-1].timestamp:.3f}s")

t0 = frames[0].timestamp

def rel(f):
    return f.timestamp - t0

WINDOW = 2.5

def decode_0x440(data):
    try:
        d = db.decode_message(0x440, bytes(data), decode_choices=False)
        raw_stat = d.get("bcm_mainc_stat", None)
        idx = int(raw_stat) if raw_stat is not None else None
        stat_name = MAINC_STAT_STATES[idx] if idx is not None and idx < len(MAINC_STAT_STATES) else (f"idx{idx}" if idx is not None else "?")
        vbus_pos = d.get("bcm_vbus_pos", None)
        vbus_neg = d.get("bcm_vbus_neg", None)
        fault_mon = d.get("bcm_fault_mon", None)
        return stat_name, vbus_pos, vbus_neg, fault_mon
    except Exception:
        return "ERR", None, None, None

def decode_0x410(data):
    try:
        d = db.decode_message(0x410, bytes(data), decode_choices=False)
        hvil = d.get("bcm_hvil_mon", None)
        alarm = d.get("bcm_alarm", None)
        epo = d.get("bcm_epo", None)
        ibat = d.get("bcm_ibat", None)
        vbat = d.get("bcm_vbat", None)
        cpwr = d.get("bcm_cpwr_cmd", None)
        on_plug = d.get("bcm_on_plug", None)
        return hvil, alarm, epo, ibat, vbat, cpwr, on_plug
    except Exception:
        return (None,)*7

def decode_0x420(data):
    try:
        d = db.decode_message(0x420, bytes(data), decode_choices=False)
        chg_max = d.get("bcm_chg_max", None)
        dis_max = d.get("bcm_dis_max", None)
        return chg_max, dis_max
    except Exception:
        return None, None

def decode_0x430(data):
    try:
        d = db.decode_message(0x430, bytes(data), decode_choices=False)
        lvbat = d.get("bcm_lvbat", None)
        return lvbat
    except Exception:
        return None

CLOSE_MAINR_TIMES = []
prev_stat = None
for f in frames:
    if f.arbitration_id == 0x440:
        stat, vp, vn, fm = decode_0x440(f.data)
        if prev_stat != "CLOSE_MAINR" and stat == "CLOSE_MAINR":
            CLOSE_MAINR_TIMES.append(rel(f))
        prev_stat = stat

print(f"\nFound {len(CLOSE_MAINR_TIMES)} CLOSE_MAINR transitions at: {[f'{t:.3f}s' for t in CLOSE_MAINR_TIMES]}")

for seq_idx, t_start in enumerate(CLOSE_MAINR_TIMES):
    t_lo = t_start - 0.5
    t_hi = t_start + WINDOW
    print(f"\n{'='*70}")
    print(f"SEQUENCE {seq_idx+1}: CLOSE_MAINR at t={t_start:.3f}s  (window {t_lo:.2f}s - {t_hi:.2f}s)")
    print(f"{'='*70}")
    print(f"{'t(s)':>8}  {'ID':>6}  {'mainc_stat':<26}  {'vbus_pos':>9}  {'vbus_neg':>9}  {'hvil':>4}  {'alarm':>5}  {'epo':>3}  {'ibat':>7}  {'vbat':>7}  {'lvbat':>6}  {'chg_max':>8}  {'dis_max':>8}")
    print("-"*128)

    last_stat = "?"
    last_vp = last_vn = last_hvil = last_alarm = last_epo = last_ibat = last_vbat = last_chg = last_dis = last_lv = None

    for f in frames:
        t = rel(f)
        if t < t_lo or t > t_hi:
            continue
        if f.arbitration_id == 0x440:
            stat, vp, vn, fm = decode_0x440(f.data)
            if stat != last_stat or (vp is not None and vp != last_vp) or (vn is not None and vn != last_vn):
                print(f"{t:8.3f}  {'0x440':>6}  {stat:<26}  {str(round(vp,1)) if vp is not None else 'n/a':>9}  {str(round(vn,1)) if vn is not None else 'n/a':>9}  {str(last_hvil) if last_hvil is not None else 'n/a':>4}  {str(last_alarm) if last_alarm is not None else 'n/a':>5}  {str(last_epo) if last_epo is not None else 'n/a':>3}  {str(round(last_ibat,1)) if last_ibat is not None else 'n/a':>7}  {str(round(last_vbat,1)) if last_vbat is not None else 'n/a':>7}  {str(round(last_lv,1)) if last_lv is not None else 'n/a':>6}  {'':>8}  {'':>8}")
            last_stat = stat
            last_vp = vp
            last_vn = vn
        elif f.arbitration_id == 0x410:
            hvil, alarm, epo, ibat, vbat, cpwr, on_plug = decode_0x410(f.data)
            if hvil != last_hvil or alarm != last_alarm or epo != last_epo:
                print(f"{t:8.3f}  {'0x410':>6}  {'':26}  {'':>9}  {'':>9}  {str(hvil) if hvil is not None else 'n/a':>4}  {str(alarm) if alarm is not None else 'n/a':>5}  {str(epo) if epo is not None else 'n/a':>3}  {str(round(ibat,1)) if ibat is not None else 'n/a':>7}  {str(round(vbat,1)) if vbat is not None else 'n/a':>7}  {str(round(last_lv,1)) if last_lv is not None else 'n/a':>6}  {'':>8}  {'':>8}")
            last_hvil = hvil
            last_alarm = alarm
            last_epo = epo
            if ibat is not None:
                last_ibat = ibat
            if vbat is not None:
                last_vbat = vbat
        elif f.arbitration_id == 0x430:
            lv = decode_0x430(f.data)
            if lv != last_lv:
                print(f"{t:8.3f}  {'0x430':>6}  {'':26}  {'':>9}  {'':>9}  {'':>4}  {'':>5}  {'':>3}  {'':>7}  {'':>7}  {str(round(lv,1)) if lv is not None else 'n/a':>6}  {'':>8}  {'':>8}")
            last_lv = lv
        elif f.arbitration_id == 0x420:
            chg_max, dis_max = decode_0x420(f.data)
            if chg_max != last_chg or dis_max != last_dis:
                print(f"{t:8.3f}  {'0x420':>6}  {'':26}  {'':>9}  {'':>9}  {'':>4}  {'':>5}  {'':>3}  {'':>7}  {'':>7}  {'':>6}  {str(round(chg_max,1)) if chg_max is not None else 'n/a':>8}  {str(round(dis_max,1)) if dis_max is not None else 'n/a':>8}")
            last_chg = chg_max
            last_dis = dis_max

print("\nDone.")
