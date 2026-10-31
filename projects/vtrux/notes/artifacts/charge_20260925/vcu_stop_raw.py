"""Raw frames of the charger status (0x18FFD4C0, every mux page), the VCU
command (0x18EFC000), the VCM warn lamp (0x646) and the Bel chargeInfo
(0x18FFD9C0) in a window, in file order, with DBC decode of the fields that
bear on who moved first. PT channels folded.
Usage: python3.13 <this> LOG T_START T_END
"""
import sys
sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

PT_ANCHORS = {0x051, 0x410, 0x18FFD4C0}
bel = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc", strict=False)
exp = cantools.database.load_file("projects/vtrux/vtrux-powertrain-experimental.dbc", strict=False)
st = bel.get_message_by_name("BINV_status")
path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
chans, rows = set(), []
for fr in parse_file(path):
    if fr.arbitration_id in PT_ANCHORS:
        chans.add(fr.bus)
    if t0 <= fr.timestamp <= t1:
        rows.append(fr)
    if fr.timestamp > t1:
        break
for fr in rows:
    if fr.bus not in chans:
        continue
    cid, d, h = fr.arbitration_id, bytes(fr.data), bytes(fr.data).hex(" ")
    if cid == 0x18FFD4C0:
        x = st.decode(d, decode_choices=False, allow_truncated=True)
        mux = x.get("BELINV_statusMultiplexer")
        keys = {0: ["BELINV_state", "BELINV_shutdownSource", "BELINV_chargingInProgress",
                    "BELINV_chargerEnergyFlowEnable", "BELINV_standby"],
                1: ["BELINV_buckBoostState"], 2: ["BELINV_inverterState"],
                3: ["BELINV_acOk"]}.get(mux, [])
        info = " ".join(f"{k.replace('BELINV_', '')}={x[k]}" for k in keys if k in x)
        print(f"t={fr.timestamp:8.3f} BEL  mux{mux} {h}  {info}")
    elif cid == 0x18EFC000:
        print(f"t={fr.timestamp:8.3f} VCU  {h}")
    elif cid == 0x646:
        m = exp.get_message_by_frame_id(0x646)
        print(f"t={fr.timestamp:8.3f} 646  {h}  {m.decode(d, allow_truncated=True)}")
    elif cid == 0x18FFD9C0:
        print(f"t={fr.timestamp:8.3f} D9C0 {h}")
