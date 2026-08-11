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

db = cantools.db.load_file(DBC)
msg430 = db.get_message_by_name("EPRI_BCM_Data1_0430")
TARGET = msg430.frame_id  # 1072 / 0x430

def find_soc_msg():
    for m in db.messages:
        for s in m.signals:
            if s.name.lower() in ("bcm_soc", "soc") or "soc" in s.name.lower():
                return m, s
    return None, None

soc_msg, soc_sig = find_soc_msg()
soc_id = soc_msg.frame_id if soc_msg else None
print("SOC signal:", soc_sig.name if soc_sig else None, "on", hex(soc_id) if soc_id else None)

rows = []   # (t, vmax_mV, vmin_mV)
soc_rows = []  # (t, soc)
id_seen = {}
SENT = 0x1FFE

for fn in CHUNKS:
    path = f"{LOGDIR}/{fn}"
    for fr in parse_file(path, absolute=True):
        aid = fr.arbitration_id
        id_seen[aid] = id_seen.get(aid, 0) + 1
        if aid == TARGET or (aid & 0x7FF) == (TARGET & 0x7FF):
            try:
                raw = msg430.decode(fr.data, decode_choices=False, allow_truncated=True)
            except Exception:
                continue
            vmax = raw.get("bcm_cell_vmax")
            vmin = raw.get("bcm_cell_vmin")
            if vmax is None or vmin is None:
                continue
            vmax_mv = round(vmax * 1000)
            vmin_mv = round(vmin * 1000)
            if vmax_mv >= 8000 or vmin_mv >= 8000:
                continue
            rows.append((fr.timestamp, vmax_mv, vmin_mv))
        if soc_id is not None and (aid == soc_id or (aid & 0x7FF) == (soc_id & 0x7FF)):
            try:
                rs = soc_msg.decode(fr.data, decode_choices=False, allow_truncated=True)
                soc_rows.append((fr.timestamp, rs.get(soc_sig.name)))
            except Exception:
                pass

print("total 0x430 valid frames:", len(rows))
if not rows:
    print("NO 0x430 frames. Top IDs seen:")
    for aid, c in sorted(id_seen.items(), key=lambda x: -x[1])[:20]:
        print(f"  {hex(aid)}: {c}")
    sys.exit()

t0 = rows[0][0]
tend = rows[-1][0]
print(f"duration: {tend-t0:.1f} s ({(tend-t0)/60:.1f} min), {len(rows)} samples")

vmaxs = [r[1] for r in rows]
vmins = [r[2] for r in rows]
spreads = [r[1]-r[2] for r in rows]

def stats(name, xs):
    print(f"  {name}: min={min(xs)} max={max(xs)} mean={sum(xs)/len(xs):.1f}")

print("\n=== whole log ===")
stats("vmax(mV)", vmaxs)
stats("vmin(mV)", vmins)
stats("spread(mV)", spreads)

print("\n=== first 5 samples ===")
for t, vx, vn in rows[:5]:
    print(f"  t={t-t0:7.2f}s vmax={vx} vmin={vn} spread={vx-vn}")
print("=== last 5 samples ===")
for t, vx, vn in rows[-5:]:
    print(f"  t={t-t0:7.2f}s vmax={vx} vmin={vn} spread={vx-vn}")

print("\n=== timeline (every ~30s) ===")
last = None
for t, vx, vn in rows:
    rel = t - t0
    if last is None or rel - last >= 30:
        print(f"  t={rel:7.1f}s vmax={vx} vmin={vn} spread={vx-vn}")
        last = rel

if soc_rows:
    print("\n=== SoC timeline ===")
    s0 = soc_rows[0][0]
    last = None
    for t, v in soc_rows:
        rel = t - s0
        if last is None or rel - last >= 30:
            print(f"  t={rel:7.1f}s soc={v}")
            last = rel
    print(f"  final soc={soc_rows[-1][1]}")
