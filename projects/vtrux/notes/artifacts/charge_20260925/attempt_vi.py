"""Charger V/I (0x18FFD7C0) and VCU page traffic (0x18EFC000) around a
charge start, plus raw 0x065B / 0x617 / 0x460 frames. PT channels folded.

Usage: python3.13 <this> LOG T_START T_END
"""
import sys
sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

PT_ANCHORS = {0x410, 0x420, 0x430, 0x440, 0x18FFD4C0, 0x18FFD9C0}
RAW_IDS = {0x065B, 0x617, 0x460, 0x18EFC000}

db = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc", strict=False)
vi = db.get_message_by_name("BELINV_hvBatteryAndCharger")

path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
chans = set()
rows = []
for fr in parse_file(path):
    if fr.arbitration_id in PT_ANCHORS:
        chans.add(fr.bus)
    if fr.timestamp < t0:
        continue
    if fr.timestamp > t1:
        break
    rows.append(fr)
last_raw = {}
for fr in rows:
    if fr.bus not in chans:
        continue
    cid = fr.arbitration_id
    if cid == 0x18FFD7C0:
        d = vi.decode(bytes(fr.data))
        print(f"t={fr.timestamp:8.3f} VI  hvV={d['BELINV_hvBatteryVoltage']:7.2f} "
              f"hvI={d['BELINV_hvBatteryCurrent']:7.2f} acV={d['BELINV_chargerInputVoltage']:7.2f} "
              f"acI={d['BELINV_chargerInputCurrent']:7.2f}")
    elif cid in RAW_IDS:
        h = bytes(fr.data).hex(" ")
        if cid == 0x18EFC000 or last_raw.get(cid) != h:
            print(f"t={fr.timestamp:8.3f} RAW 0x{cid:X} {h}")
        last_raw[cid] = h
