"""Sample HV bus / contactor / DCDC signals every STEP s over a window
(PT channels folded). Usage: python3.13 <this> LOG T_START T_END [STEP]
"""
import sys
sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

PT_ANCHORS = {0x410, 0x420, 0x430, 0x440, 0x18FFD4C0, 0x18FFD9C0}
db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc", strict=False)
WANT = {0x440: ["bcm_mainc_stat", "bcm_vbus_pos", "bcm_vbus_neg"],
        0x410: ["bcm_vbat", "bcm_hvil_mon", "bcm_alarm"],
        0x18FFD6B3: ["DCDC_HV_Volt", "DCDC_LV_Volt", "DCDC_LV_Curr"]}
msgs = {c: db.get_message_by_frame_id(c | (0x80000000 if c > 0x7FF else 0)) for c in WANT}

path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
step = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
chans = set()
cur = {}
nxt = t0
for fr in parse_file(path):
    if fr.arbitration_id in PT_ANCHORS:
        chans.add(fr.bus)
    if fr.timestamp > t1:
        break
    if fr.bus in chans and fr.arbitration_id in WANT:
        try:
            d = msgs[fr.arbitration_id].decode(bytes(fr.data), allow_truncated=True)
        except Exception:
            continue
        for n in WANT[fr.arbitration_id]:
            if n in d:
                cur[n] = d[n]
    if fr.timestamp >= nxt:
        print(f"t={fr.timestamp:7.2f} " + " ".join(f"{k}={v}" for k, v in cur.items()))
        nxt += step
