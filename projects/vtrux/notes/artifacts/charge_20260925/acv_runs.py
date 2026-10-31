"""Run-length listing of BELINV_chargerInputVoltage / Current (0x18FFD7C0) over a
window: each run of identical (V, I) values with start, end, frame count, plus
the Bel state (mux0) at the run start. PT channels folded. A live AC measurement
wobbles by 0.05-0.3 V frame to frame; a long run of one exact value is held.
Usage: python3.13 <this> LOG T_START T_END
"""
import sys
sys.path.insert(0, ".")
import cantools
from canre.parsers import parse_file

PT_ANCHORS = {0x051, 0x410, 0x18FFD4C0}
db = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc", strict=False)
vi, st = db.get_message_by_name("BELINV_hvBatteryAndCharger"), db.get_message_by_name("BINV_status")
path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
chans, state, runs = set(), None, []
for fr in parse_file(path):
    if fr.arbitration_id in PT_ANCHORS:
        chans.add(fr.bus)
    if fr.timestamp > t1:
        break
    if fr.timestamp < t0 or fr.bus not in chans:
        continue
    if fr.arbitration_id == 0x18FFD4C0:
        d = st.decode(bytes(fr.data), decode_choices=False, allow_truncated=True)
        if d.get("BELINV_statusMultiplexer") == 0:
            state = d["BELINV_state"]
    elif fr.arbitration_id == 0x18FFD7C0:
        d = vi.decode(bytes(fr.data))
        k = (round(d["BELINV_chargerInputVoltage"], 2), round(d["BELINV_chargerInputCurrent"], 2))
        if runs and runs[-1][0] == k:
            runs[-1][2] = fr.timestamp
            runs[-1][3] += 1
        else:
            runs.append([k, fr.timestamp, fr.timestamp, 1, state])
for (v, i), a, b, n, s in runs:
    if n >= 5 or v < 150:
        print(f"t={a:8.3f}..{b:8.3f}  n={n:5d}  acV={v:7.2f}  acI={i:5.2f}  bel_state={s}")
print(f"({len(runs)} runs; runs shorter than 5 frames at >= 150 V not listed)")
