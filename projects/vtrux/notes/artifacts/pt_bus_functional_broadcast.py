"""Send functional broadcast (0x7DF) on PT bus with DSC and TesterPresent.
Listen for any response in 0x700-0x7FF. Any module that supports these services
will reveal its physical address in its response.
"""

import sys
import time
from pathlib import Path
from queue import Empty, Queue

import can

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canbench.live.receiver import detect_all_can_interfaces

BITRATE = 500_000
PT_BUS_ANCHORS = frozenset({0x051, 0x054, 0x471, 0x479, 0x482, 0x592, 0x639})
FUNC_ADDR = 0x7DF
LISTEN_SECS = 3.0

NRC_NAMES = {
    0x10: "generalReject", 0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported", 0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError", 0x31: "requestOutOfRange",
    0x33: "securityAccessDenied", 0x78: "responsePending",
}

PROBES = [
    ("TesterPresent 0x3E/00", bytes([0x02, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
    ("DSC default  0x10/01", bytes([0x02, 0x10, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])),
    ("DSC extended 0x10/03", bytes([0x02, 0x10, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00])),
]


def describe(data):
    if not data:
        return "(empty)"
    sid = data[0]
    if sid == 0x7F:
        req = data[1] if len(data) > 1 else 0
        nrc = data[2] if len(data) > 2 else 0
        return f"NRC 0x{req:02X}: {NRC_NAMES.get(nrc, f'0x{nrc:02X}')}"
    if sid == 0x7E:
        return "TesterPresent OK"
    if sid == 0x50:
        subfn = data[1] if len(data) > 1 else 0
        names = {0x01: "default", 0x02: "programming", 0x03: "extended"}
        return f"DSC OK: {names.get(subfn, f'0x{subfn:02X}')}"
    return " ".join(f"{b:02X}" for b in data)


def find_pt_bus():
    interfaces = detect_all_can_interfaces(BITRATE, brands={"kvaser"})
    for iface, ch_spec, desc in interfaces:
        try:
            if isinstance(ch_spec, dict):
                b = can.interface.Bus(interface=iface, bitrate=BITRATE, **ch_spec)
            else:
                b = can.interface.Bus(interface=iface, channel=ch_spec, bitrate=BITRATE)
        except Exception as e:
            print(f"  Could not open {desc}: {e}")
            continue
        seen = set()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            msg = b.recv(timeout=0.05)
            if msg and not msg.is_extended_id:
                seen.add(msg.arbitration_id)
        hits = len(seen & PT_BUS_ANCHORS)
        print(f"  {desc}: {len(seen)} IDs, {hits} PT anchors")
        if hits >= 3:
            print(f"  -> PT bus confirmed")
            return b
        b.shutdown()
    return None


print("Detecting PT bus...")
bus = find_pt_bus()
if bus is None:
    print("ERROR: PT bus not found.")
    sys.exit(1)

for probe_label, req_data in PROBES:
    print(f"\n--- Functional broadcast 0x7DF: {probe_label} ---")
    print(f"    Listening {LISTEN_SECS}s for any response in 0x700-0x7FF...")

    req = can.Message(arbitration_id=FUNC_ADDR, data=req_data, is_extended_id=False)
    bus.send(req)

    deadline = time.time() + LISTEN_SECS
    responses = {}
    while time.time() < deadline:
        msg = bus.recv(timeout=0.05)
        if msg is None or msg.is_extended_id:
            continue
        arb = msg.arbitration_id
        if 0x700 <= arb <= 0x7FF and arb != FUNC_ADDR:
            d = list(msg.data)
            pt = (d[0] >> 4) & 0x0F
            if pt == 0:
                length = d[0] & 0x0F
                payload = bytes(d[1:1 + length])
                sid = payload[0] if payload else 0
                if sid in (0x7E, 0x50, 0x7F):
                    if arb not in responses:
                        responses[arb] = payload
                        print(f"    RESPONSE 0x{arb:03X}: {describe(payload)}")

    if not responses:
        print("    No diagnostic responses.")
    time.sleep(0.5)

bus.shutdown()
print("\nDone.")
