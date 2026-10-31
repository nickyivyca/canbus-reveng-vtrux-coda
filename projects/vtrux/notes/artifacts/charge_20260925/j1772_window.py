"""Every J1772 / plug-related signal change (plus first value) over a window,
at full frame resolution, PT channels folded:
  0x18FFD4C0 mux0 pilot/prox/evse/vehicle/s2/keySwitch/evseDisconnected flags
  0x18FFD8C0 pilotDuty, pilotFrequency
  0x18FFD7C0 chargerInputVoltage/Current (min/max per 1 s, not every change)
  0x592 EVSESwitchState, 0x410 bcm_on_plug
Also prints each message's median inter-frame period.
Usage: python3.13 <this> LOG T_START T_END
"""
import sys
sys.path.insert(0, ".")
import statistics
from collections import defaultdict
import cantools
from canre.parsers import parse_file

PT_ANCHORS = {0x051, 0x410, 0x18FFD4C0}
dbs = [cantools.database.load_file(p, strict=False) for p in
       ("projects/vtrux/BelInverter-v2.dbc", "projects/vtrux/epri-pt-bus.dbc")]
def msg(fid):
    for db in dbs:
        for f in (fid, fid | 0x80000000):
            try:
                m = db.get_message_by_frame_id(f)
                if m.signals:
                    return m
            except KeyError:
                pass
WATCH = {
    0x18FFD4C0: ["BELINV_keySwitch", "BELINV_pilotControlSignal", "BELINV_proxEnabled",
                 "BELINV_evseConnected", "BELINV_vehicleConnected", "BELINV_s2Switch",
                 "BELINV_evseDisconnected", "BELINV_state"],
    0x18FFD8C0: ["BELINV_pilotDuty", "BELINV_pilotFrequency"],
    0x592: ["EVSESwitchState"],
    0x410: ["bcm_on_plug"],
}
VI = 0x18FFD7C0
path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
M = {c: msg(c) for c in list(WATCH) + [VI]}
chans, last, times = set(), {}, defaultdict(list)
vi = defaultdict(lambda: [1e9, -1e9, 1e9, -1e9])
for fr in parse_file(path):
    if fr.arbitration_id in PT_ANCHORS:
        chans.add(fr.bus)
    if fr.timestamp > t1:
        break
    if fr.timestamp < t0 or fr.bus not in chans:
        continue
    cid = fr.arbitration_id
    if cid not in M:
        continue
    try:
        d = M[cid].decode(bytes(fr.data), decode_choices=False, allow_truncated=True)
    except Exception:
        continue
    if cid == 0x18FFD4C0 and d.get("BELINV_statusMultiplexer") != 0:
        continue
    times[cid].append(fr.timestamp)
    if cid == VI:
        s = vi[int(fr.timestamp)]
        v, i = d["BELINV_chargerInputVoltage"], d["BELINV_chargerInputCurrent"]
        s[0], s[1], s[2], s[3] = min(s[0], v), max(s[1], v), min(s[2], i), max(s[3], i)
        continue
    for n in WATCH[cid]:
        if n in d and last.get(n) != d[n]:
            print(f"t={fr.timestamp:8.3f} {n:28s} {last.get(n, '(first)')} -> {d[n]}")
            last[n] = d[n]
print("\nmedian period (s):", {hex(c): round(statistics.median(
    [b - a for a, b in zip(v, v[1:]) if b - a < 5]), 3) for c, v in times.items() if len(v) > 2})
print("\nAC per second: sec  Vmin  Vmax  Imin  Imax")
for s, (a, b, c, e) in sorted(vi.items()):
    print(f"  {s:5d} {a:7.2f} {b:7.2f} {c:6.2f} {e:6.2f}")
