import sys
sys.path.insert(0, ".")
import cantools
from canre.parsers import parse_file

DBC = "projects/vtrux/epri-pt-bus.dbc"
LOGDIR = "../../CANLogs/VtruxLogs"
CHUNKS = [
    "vtrux_20260617_193900_T0.log",
    "vtrux_20260617_193900_T1.log",
    "vtrux_20260617_193900_T2.log",
]
db = cantools.database.load_file(DBC)
soc_msg = db.get_message_by_name("EPRI_BCM_Status_0410")

WATCH = {0x410, 0x411, 0x600, 0x644, 0x412, 0x592 & 0x7FF}
soc_track = []
first_t = None
present = {}
const_vals = {}   # (id,byte)->set of values
focus_trans = []  # 0x600 B0, 0x410 B6, 0x410 B1, 0x410 B0
FOCUS = {(0x600,0): None, (0x410,6): None, (0x410,1): None, (0x410,0): None, (0x600,1): None}

for fn in CHUNKS:
    for fr in parse_file(f"{LOGDIR}/{fn}", absolute=True):
        aid = fr.arbitration_id & 0x7FF
        if first_t is None:
            first_t = fr.timestamp
        present[aid] = present.get(aid, 0) + 1
        if aid == 0x410:
            try:
                soc_track.append((fr.timestamp, soc_msg.decode(fr.data, allow_truncated=True).get("bcm_soc")))
            except Exception:
                pass
        if aid in WATCH:
            for i, b in enumerate(fr.data):
                const_vals.setdefault((aid,i), set()).add(b)
                if (aid,i) in FOCUS:
                    prev = FOCUS[(aid,i)]
                    if prev is not None and prev != b:
                        focus_trans.append((fr.timestamp, aid, i, prev, b))
                    FOCUS[(aid,i)] = b

t0 = first_t
def soc_at(t):
    v = soc_track[0][1] if soc_track else None
    for tt, s in soc_track:
        if tt > t: break
        v = s
    return v

print("=== presence of fault-relevant IDs ===")
for x in [0x410,0x411,0x412,0x440,0x600,0x644,0x592]:
    print(f"  0x{x:03X}: {present.get(x,0)} frames")

print("\n=== 0x410 B0 / B1 constant check (the confirmed fault register) ===")
for i in [0,1]:
    vals = sorted(const_vals.get((0x410,i), set()))
    print(f"  0x410 B{i}: values={[f'0x{v:02X}({v:08b})' for v in vals]}")

print("\n=== focus transitions (0x600 B0/B1, 0x410 B0/B1/B6) ===")
for t, aid, i, old, new in focus_trans:
    print(f"  t={t-t0:7.1f}s soc={soc_at(t)}  0x{aid:03X} B{i}: 0x{old:02X}({old:08b}) -> 0x{new:02X}({new:08b})")

print("\n=== 0x410 B6 values seen ===")
print("  ", sorted(const_vals.get((0x410,6), set())))
