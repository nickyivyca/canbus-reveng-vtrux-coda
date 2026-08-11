"""Query Mode 01 engine PIDs and GM-specific RDBI ranges on the OBD bus module at 0x7E0.

If this is the GM ECM it will respond to engine PIDs (RPM, coolant temp, MAF, etc.).
If it is the Woodward HCU it won't know those values.
Also scans GM-specific RDBI DID ranges that might carry manufacturer identification.
"""

import sys
import time
from pathlib import Path
from queue import Empty, Queue
import threading

import can

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canbench.live.receiver import detect_all_can_interfaces

BITRATE = 500_000
OBD_BUS_ANCHORS = frozenset({0x040, 0x041, 0x042, 0x043, 0x044, 0x441, 0x44A})
HCU_PHYS = 0x7E0
HCU_RESP = 0x7E8


def make_sf(payload):
    assert len(payload) <= 7
    return bytes([len(payload)] + list(payload) + [0x00] * (7 - len(payload)))


def recv_one(bus, resp_id, timeout=1.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = bus.recv(timeout=0.05)
        if msg and not msg.is_extended_id and msg.arbitration_id == resp_id:
            d = list(msg.data)
            pt = (d[0] >> 4) & 0x0F
            if pt == 1:
                total = ((d[0] & 0x0F) << 8) | d[1]
                payload = bytearray(d[2:])
                fc = can.Message(arbitration_id=HCU_PHYS,
                                 data=bytes([0x30,0,0,0,0,0,0,0]),
                                 is_extended_id=False)
                bus.send(fc)
                while len(payload) < total:
                    cf = bus.recv(timeout=0.5)
                    if cf and not cf.is_extended_id and cf.arbitration_id == resp_id:
                        cd = list(cf.data)
                        if (cd[0] >> 4) == 2:
                            payload.extend(cd[1:])
                return bytes(payload[:total])
            elif pt == 0:
                length = d[0] & 0x0F
                return bytes(d[1:1 + length])
    return None


def query(bus, payload, label):
    req = can.Message(arbitration_id=HCU_PHYS, data=make_sf(payload), is_extended_id=False)
    bus.send(req)
    resp = recv_one(bus, HCU_RESP)
    if resp is None:
        print(f"  ----  {label:<40}  no response")
        return None
    if resp[0] == 0x7F:
        nrc = resp[2] if len(resp) > 2 else 0
        nrc_names = {0x11: "serviceNotSupported", 0x12: "subFunctionNotSupported",
                     0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange",
                     0x33: "securityAccessDenied"}
        print(f"  NRC   {label:<40}  {nrc_names.get(nrc, f'0x{nrc:02X}')}")
        return None
    hex_str = " ".join(f"{b:02X}" for b in resp)
    try:
        asc = resp.decode("ascii")
        if all(0x20 <= ord(c) < 0x7F for c in asc):
            print(f"  OK    {label:<40}  {repr(asc)}  [{hex_str}]")
            return resp
    except Exception:
        pass
    print(f"  OK    {label:<40}  [{hex_str}]")
    return resp


def find_obd_bus():
    interfaces = detect_all_can_interfaces(BITRATE, brands=None)
    for iface, ch_spec, desc in interfaces:
        try:
            if isinstance(ch_spec, dict):
                b = can.interface.Bus(interface=iface, bitrate=BITRATE, **ch_spec)
            else:
                b = can.interface.Bus(interface=iface, channel=ch_spec, bitrate=BITRATE)
        except Exception:
            continue
        seen = set()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            msg = b.recv(timeout=0.05)
            if msg and not msg.is_extended_id:
                seen.add(msg.arbitration_id)
        hits = len(seen & OBD_BUS_ANCHORS)
        print(f"  {desc}: {len(seen)} IDs, {hits} OBD anchors")
        if hits >= 2:
            print(f"  -> Using {desc} as OBD bus")
            return b
        b.shutdown()
    return None


print("Detecting OBD bus (2s)...")
bus = find_obd_bus()
if bus is None:
    print("ERROR: OBD bus not found.")
    sys.exit(1)

print()
print("--- Mode 01 engine PIDs ---")
print("(If this is the engine ECM these will return live engine values)")

MODE01_PIDS = [
    (0x00, "Mode01/0x00 supported PIDs 01-20"),
    (0x01, "Mode01/0x01 MIL status + DTC count"),
    (0x05, "Mode01/0x05 coolant temp (C)"),
    (0x0C, "Mode01/0x0C engine RPM"),
    (0x0D, "Mode01/0x0D vehicle speed (km/h)"),
    (0x0F, "Mode01/0x0F intake air temp (C)"),
    (0x10, "Mode01/0x10 MAF air flow rate"),
    (0x11, "Mode01/0x11 throttle position"),
]

for pid, label in MODE01_PIDS:
    resp = query(bus, bytes([0x01, pid]), label)
    if resp and resp[0] == 0x41 and len(resp) >= 3:
        pid_val = resp[1]
        data = resp[2:]
        if pid_val == 0x00:
            mask = int.from_bytes(data[:4], "big") if len(data) >= 4 else 0
            supported = [i+1 for i in range(32) if mask & (1 << (31 - i))]
            print(f"        Supported PIDs: {[hex(p) for p in supported]}")
        elif pid_val == 0x0C and len(data) >= 2:
            rpm = ((data[0] << 8) | data[1]) / 4.0
            print(f"        RPM = {rpm:.1f}")
        elif pid_val == 0x05 and len(data) >= 1:
            print(f"        Coolant = {data[0] - 40}C")
        elif pid_val == 0x0D and len(data) >= 1:
            print(f"        Speed = {data[0]} km/h")
        elif pid_val == 0x11 and len(data) >= 1:
            print(f"        Throttle = {data[0] * 100 / 255:.1f}%")
    time.sleep(0.1)

print()
print("--- Mode 09 full subfunction sweep (find any others that respond) ---")
for subfn in range(0x01, 0x10):
    time.sleep(0.05)
    resp = query(bus, bytes([0x09, subfn]), f"Mode09/0x{subfn:02X}")

print()
print("--- RDBI GM-specific DID ranges ---")
print("(Scanning 0x0100-0x011F and 0xF100-0xF10F for manufacturer info)")

for did in list(range(0x0100, 0x0120)) + list(range(0xF100, 0xF110)):
    time.sleep(0.04)
    resp = query(bus, bytes([0x22, (did >> 8) & 0xFF, did & 0xFF]),
                 f"RDBI 0x{did:04X}")

bus.shutdown()
print()
print("Done.")
