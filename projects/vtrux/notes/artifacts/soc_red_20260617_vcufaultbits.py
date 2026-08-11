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

RAW_IDS = {0x410, 0x411, 0x600, 0x644, 0x440}

soc_track = []
first_t = None
gap_check = []  # timestamps of 0x410 frames to find log gaps
raw_last = {}   # (id, byte_index) -> value
raw_trans = []  # (t, id, byte_index, old, new)

for fn in CHUNKS:
    for fr in parse_file(f"{LOGDIR}/{fn}", absolute=True):
        aid = fr.arbitration_id & 0x7FF
        if first_t is None:
            first_t = fr.timestamp
        if aid == 0x410:
            gap_check.append(fr.timestamp)
            try:
                dec = soc_msg.decode(fr.data, decode_choices=False, allow_truncated=True)
                soc_track.append((fr.timestamp, dec.get("bcm_soc")))
            except Exception:
                pass
        if aid in RAW_IDS:
            for i, b in enumerate(fr.data):
                k = (aid, i)
                if k in raw_last and raw_last[k] != b:
                    raw_trans.append((fr.timestamp, aid, i, raw_last[k], b))
                raw_last[k] = b

t0 = first_t

def soc_at(t):
    v = soc_track[0][1] if soc_track else None
    for tt, s in soc_track:
        if tt > t:
            break
        v = s
    return v

# --- 1. log gap detection ---
print("=== LOG GAP CHECK (0x410 inter-frame gaps > 2s) ===")
gaps = []
for i in range(1, len(gap_check)):
    g = gap_check[i] - gap_check[i-1]
    if g > 2.0:
        gaps.append((gap_check[i-1]-t0, gap_check[i]-t0, g))
print(f"  0x410 frames: {len(gap_check)}, span {gap_check[-1]-t0:.1f}s")
for a, b, g in gaps:
    print(f"  GAP {g:.1f}s : t={a:.1f}s (soc={soc_at(t0+a)}) -> t={b:.1f}s (soc={soc_at(t0+b)})")
if not gaps:
    print("  no gaps > 2s")

# --- 2. raw fault-bit byte transitions ---
print("\n=== RAW BYTE TRANSITIONS on fault-bit IDs (excluding continuous/counter bytes) ===")
from collections import defaultdict
by_byte = defaultdict(list)
for t, aid, i, old, new in raw_trans:
    by_byte[(aid, i)].append((t, old, new))

for (aid, i) in sorted(by_byte):
    evs = by_byte[(aid, i)]
    uniq = sorted(set([e[1] for e in evs] + [e[2] for e in evs]))
    if len(uniq) > 16:
        print(f"  0x{aid:03X} B{i}: {len(evs)} changes, {len(uniq)} values (CONTINUOUS/COUNTER - skipped)  range 0x{min(uniq):02X}-0x{max(uniq):02X}")
        continue
    print(f"  0x{aid:03X} B{i}: {len(evs)} changes, values {[hex(u) for u in uniq]}")
    last_print = None
    for t, old, new in evs:
        rel = t - t0
        if last_print is None or rel - last_print >= 1.0 or len(evs) <= 30:
            print(f"      t={rel:7.1f}s soc={soc_at(t)}  0x{old:02X}({old:08b}) -> 0x{new:02X}({new:08b})")
            last_print = rel
