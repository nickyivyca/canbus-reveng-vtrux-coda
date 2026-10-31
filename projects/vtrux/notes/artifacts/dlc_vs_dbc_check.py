"""Check every manifest-subscribed message for DLC < declared BO_ length.

Motivation (2026-09-06): the gs_usb path on the phone always hands the decoder
a fixed 8-byte buffer (`GsUsbFrame.fromBytes` allocates `ByteArray(8)`
regardless of DLC), so `DbcDecoder`'s `data.size < message.length` guard never
trips on the truck. The BUSMASTER parser used by the replay harness truncates
to DLC instead, so any message whose real DLC is shorter than its declared
`BO_` length decodes on the truck but is dropped in replay.

This lists which subscribed messages are affected, i.e. which signals are
missing from the replay screenshots purely as a harness artifact.
"""
import sys
sys.path.insert(0, ".")

import json
from collections import defaultdict
from pathlib import Path

import cantools

from canre.parsers import parse_file

APP = Path("android-app/CanLoggerApps/vtrux/src/main/assets/live-display")
manifest = json.loads((APP / "manifest.json").read_text())
declared = {}
for bus in ("powertrain", "obd"):
    db = cantools.database.load_file(APP / "dbcs" / f"{bus}.dbc")
    for m in db.messages:
        declared[(bus, m.frame_id)] = (m.name, m.length)

wanted = {}
for sub in manifest["subscriptions"]:
    key = (sub["bus"], sub["message_id"])
    if key in declared:
        wanted[sub["message_id"]] = (sub["bus"], *declared[key])

seen = defaultdict(set)
for path in sys.argv[1:]:
    for frame in parse_file(Path(path)):
        if frame.arbitration_id in wanted:
            seen[frame.arbitration_id].add(len(frame.data))

print(f"{'id':>10}  {'bus':<11} {'message':<38} {'BO_':>4} {'seen DLCs':<12} verdict")
for mid, (bus, name, length) in sorted(wanted.items()):
    dlcs = sorted(seen.get(mid, ()))
    if not dlcs:
        verdict = "absent from these logs"
    elif min(dlcs) < length:
        verdict = "DROPPED IN REPLAY, works on truck"
    else:
        verdict = "ok"
    print(f"{mid:#10x}  {bus:<11} {name:<38} {length:>4} "
          f"{str(dlcs):<12} {verdict}")
