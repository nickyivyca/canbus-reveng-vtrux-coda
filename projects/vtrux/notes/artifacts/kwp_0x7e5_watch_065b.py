"""
Send KWP2000 Continental-style request to 0x7E5, then watch PT bus for 0x065B.

0x7E5 previously responded: 58 01 C1 00 24  (U0100, status=0x24)

Sends the request 3 times with 5s watch windows between each send,
then a final 10s listen-only period. Prints every 0x065B frame seen.
Also prints the 0x7ED response to confirm the KWP request landed.
"""

import sys
import time
from pathlib import Path

import can

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canbench.live.receiver import detect_all_can_interfaces

BITRATE = 500_000
PT_ANCHORS = frozenset({0x051, 0x054, 0x471, 0x479, 0x482, 0x592, 0x639})
HCU_DTC_ID = 0x065B

KWP_REQUEST_ADDR = 0x7E5
KWP_RESPONSE_ADDR = 0x7ED
KWP_DATA = bytes([0x04, 0x18, 0x00, 0xFF, 0x00, 0x00, 0x00, 0x00])

NUM_SENDS = 3
WATCH_SECONDS = 8


def find_pt_bus(interfaces):
    for iface_tuple in interfaces:
        interface, channel_spec, desc = iface_tuple
        if isinstance(channel_spec, dict):
            bus = can.interface.Bus(interface=interface, bitrate=BITRATE, **channel_spec)
        else:
            bus = can.interface.Bus(interface=interface, channel=channel_spec, bitrate=BITRATE)
        seen = set()
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2.0:
            msg = bus.recv(timeout=0.05)
            if msg:
                seen.add(msg.arbitration_id)
        anchors_seen = len(seen & PT_ANCHORS)
        bus.shutdown()
        if anchors_seen >= 3:
            print(f"PT bus: {desc} ({anchors_seen} anchors)")
            return iface_tuple
    return None


def watch_for_065b(bus, duration, label):
    found = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < duration:
        msg = bus.recv(timeout=0.02)
        if msg is None:
            continue
        if msg.arbitration_id == HCU_DTC_ID and not msg.is_remote_frame:
            elapsed = time.monotonic() - t0
            data_hex = " ".join(f"{b:02X}" for b in msg.data)
            print(f"  *** 0x065B at +{elapsed:.2f}s [{label}]: {data_hex}")
            found.append((elapsed, data_hex))
        elif msg.arbitration_id == KWP_RESPONSE_ADDR and not msg.is_remote_frame:
            elapsed = time.monotonic() - t0
            data_hex = " ".join(f"{b:02X}" for b in msg.data)
            print(f"  0x7ED response at +{elapsed:.2f}s: {data_hex}")
    return found


interfaces = detect_all_can_interfaces(BITRATE, brands={"kvaser"})
if not interfaces:
    print("No kvaser interface found.")
    sys.exit(1)

pt_iface = find_pt_bus(interfaces)
if not pt_iface:
    print("Could not identify PT bus on kvaser.")
    sys.exit(1)

interface, channel_spec, desc = pt_iface
if isinstance(channel_spec, dict):
    bus = can.interface.Bus(interface=interface, bitrate=BITRATE, **channel_spec)
else:
    bus = can.interface.Bus(interface=interface, channel=channel_spec, bitrate=BITRATE)

print()
print(f"Sending KWP 0x18 subfn=0x00 to 0x{KWP_REQUEST_ADDR:03X}, watching for 0x{HCU_DTC_ID:03X}")
print(f"Request data: {' '.join(f'{b:02X}' for b in KWP_DATA)}")
print()

all_hits = []

for i in range(NUM_SENDS):
    print(f"--- Send {i+1}/{NUM_SENDS} ---")
    req = can.Message(
        arbitration_id=KWP_REQUEST_ADDR,
        data=KWP_DATA,
        is_extended_id=False,
    )
    bus.send(req)
    print(f"  Sent. Watching {WATCH_SECONDS}s for 0x{HCU_DTC_ID:03X}...")
    hits = watch_for_065b(bus, WATCH_SECONDS, f"send{i+1}")
    all_hits.extend(hits)
    if hits:
        print(f"  ** GOT {len(hits)} hit(s) **")
    else:
        print(f"  No 0x065B seen.")
    print()

print(f"--- Final listen-only 10s ---")
hits = watch_for_065b(bus, 10.0, "listen")
all_hits.extend(hits)
if not hits:
    print("  No 0x065B seen.")

bus.shutdown()

print()
print("=" * 50)
if all_hits:
    print(f"RESULT: 0x065B appeared {len(all_hits)} time(s)")
    for elapsed, data in all_hits:
        print(f"  +{elapsed:.2f}s  {data}")
else:
    print("RESULT: 0x065B never appeared.")
print("=" * 50)
