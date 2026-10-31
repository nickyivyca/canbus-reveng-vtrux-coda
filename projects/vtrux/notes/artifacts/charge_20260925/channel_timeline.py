"""Per-channel frame count, time span and anchor-ID hits for one log.
Usage: python3.13 <this> LOG
"""
import sys
sys.path.insert(0, ".")
from collections import defaultdict
from canre.parsers import parse_file

ANCH = {"pt_051": {0x051}, "bms_410": {0x410}, "bel_d4c0": {0x18FFD4C0},
        "veh": {0x1E5, 0x500}, "obd": {0x040, 0x041, 0x042, 0x043, 0x044}}
st = defaultdict(lambda: [0, None, None, defaultdict(int)])
for fr in parse_file(sys.argv[1]):
    s = st[fr.bus]
    s[0] += 1
    s[1] = fr.timestamp if s[1] is None else s[1]
    s[2] = fr.timestamp
    for k, ids in ANCH.items():
        if fr.arbitration_id in ids:
            s[3][k] += 1
for ch, (n, a, b, h) in sorted(st.items()):
    print(f"ch {ch:3d} n={n:8d} t={a:8.2f}..{b:8.2f} " + " ".join(f"{k}={v}" for k, v in sorted(h.items())))
