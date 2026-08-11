"""
Compare 0x716 DID 0x0101 values against live 0x430 BMS cell temperatures.

DID 0x0101 returns 24 bytes structured as 6 groups of 4: [XX YY 00 ZZ]
XX/YY values are in the 53-59 decimal range -- unknown encoding.

0x430 bcm_cell_tmax = byte 4, scale 0.5*raw - 40 degC
0x430 bcm_cell_tmin = byte 5, scale 0.5*raw - 40 degC

Both are read simultaneously so the comparison is valid.
"""

import sys
import time
from pathlib import Path

import can
import cantools

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canbench.live.receiver import detect_all_can_interfaces

BITRATE = 500_000
PT_ANCHORS = frozenset({0x051, 0x054, 0x471, 0x479, 0x482, 0x592, 0x639})
DBC_PATH = Path(__file__).resolve().parents[4] / "projects" / "vtrux" / "epri-pt-bus.dbc"

TARGET_ADDR  = 0x716
RESP_ADDR    = 0x71E
BMS_ID       = 0x430
DID          = 0x0101

RDBI_REQ = bytes([0x03, 0x22, (DID >> 8) & 0xFF, DID & 0xFF, 0x00, 0x00, 0x00, 0x00])
FLOW_CTL = bytes([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def open_pt_bus():
    interfaces = detect_all_can_interfaces(BITRATE, brands={"kvaser"})
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
        if len(seen & PT_ANCHORS) >= 3:
            print(f"PT bus: {desc}")
            return bus
        bus.shutdown()
    return None


def collect_0430(bus, count=5):
    """Collect up to `count` 0x430 frames, return list of (tmax, tmin) tuples."""
    results = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < 3.0 and len(results) < count:
        msg = bus.recv(timeout=0.1)
        if msg and msg.arbitration_id == BMS_ID and not msg.is_extended_id and len(msg.data) >= 6:
            tmax_raw = msg.data[4]
            tmin_raw = msg.data[5]
            tmax = tmax_raw * 0.5 - 40.0
            tmin = tmin_raw * 0.5 - 40.0
            results.append((tmax, tmin, tmax_raw, tmin_raw))
    return results


def rdbi_0101(bus):
    """Send RDBI 0x0101 to 0x716, handle multi-frame response, return payload bytes."""
    req = can.Message(arbitration_id=TARGET_ADDR, data=RDBI_REQ, is_extended_id=False)
    bus.send(req)

    payload = bytearray()
    expected_len = None
    seq = 1

    t0 = time.monotonic()
    while time.monotonic() - t0 < 2.0:
        msg = bus.recv(timeout=0.05)
        if not msg or msg.arbitration_id != RESP_ADDR or msg.is_extended_id:
            continue
        pci = msg.data[0]

        if (pci & 0xF0) == 0x00:
            length = pci & 0x0F
            payload = bytearray(msg.data[1:1 + length])
            break

        elif (pci & 0xF0) == 0x10:
            expected_len = ((pci & 0x0F) << 8) | msg.data[1]
            payload = bytearray(msg.data[2:])
            fc = can.Message(arbitration_id=TARGET_ADDR, data=FLOW_CTL, is_extended_id=False)
            bus.send(fc)

        elif (pci & 0xF0) == 0x20:
            frame_seq = pci & 0x0F
            if frame_seq == seq % 16:
                payload.extend(msg.data[1:])
                seq += 1
            if expected_len and len(payload) >= expected_len - 2:
                payload = payload[:expected_len - 2]
                break

    return bytes(payload)


db = cantools.database.load_file(str(DBC_PATH))

bus = open_pt_bus()
if not bus:
    print("PT bus not found.")
    sys.exit(1)

print()
print("Collecting live 0x430 BMS frames (5 samples)...")
bms_samples = collect_0430(bus, count=5)

print(f"Sending RDBI 0x{DID:04X} to 0x{TARGET_ADDR:03X}...")
payload = rdbi_0101(bus)
bus.shutdown()

print()
print("=" * 55)
print("  0x430 BMS live samples")
print("=" * 55)
if bms_samples:
    for i, (tmax, tmin, tmax_r, tmin_r) in enumerate(bms_samples):
        print(f"  Sample {i+1}: tmax={tmax:.1f}C (raw=0x{tmax_r:02X}={tmax_r})"
              f"  tmin={tmin:.1f}C (raw=0x{tmin_r:02X}={tmin_r})")
    tmaxes = [s[0] for s in bms_samples]
    tmins  = [s[1] for s in bms_samples]
    print(f"  Mean: tmax={sum(tmaxes)/len(tmaxes):.1f}C  tmin={sum(tmins)/len(tmins):.1f}C")
else:
    print("  No 0x430 frames received.")

print()
print("=" * 55)
print(f"  0x716 DID 0x0101 response ({len(payload)} bytes)")
print("=" * 55)
if not payload:
    print("  No response.")
elif payload[0] == 0x62:
    data = payload[3:]
    print(f"  Raw: {' '.join(f'{b:02X}' for b in data)}")
    print()
    if len(data) >= 24:
        groups = [data[i:i+4] for i in range(0, 24, 4)]
        for i, g in enumerate(groups):
            xx, yy, z1, z2 = g[0], g[1], g[2], g[3]
            print(f"  Group {i+1}: XX=0x{xx:02X}({xx:3d})  YY=0x{yy:02X}({yy:3d})  "
                  f"[00]=0x{z1:02X}  flag=0x{z2:02X}")
    else:
        print(f"  (short response, {len(data)} data bytes)")
    print()
    print("  Decode attempts on XX byte (per group):")
    if len(data) >= 24:
        groups = [data[i:i+4] for i in range(0, 24, 4)]
        xx_vals = [g[0] for g in groups]
        yy_vals = [g[1] for g in groups]
        print(f"  XX as direct degC:        {[f'{v}C' for v in xx_vals]}")
        print(f"  XX as 0.5*raw-40 degC:    {[f'{v*0.5-40:.1f}C' for v in xx_vals]}")
        print(f"  YY as direct degC:        {[f'{v}C' for v in yy_vals]}")
        print(f"  YY as 0.5*raw-40 degC:    {[f'{v*0.5-40:.1f}C' for v in yy_vals]}")
        if bms_samples:
            mean_tmax = sum(s[0] for s in bms_samples) / len(bms_samples)
            mean_tmin = sum(s[1] for s in bms_samples) / len(bms_samples)
            print()
            print(f"  0x430 live: tmax={mean_tmax:.1f}C  tmin={mean_tmin:.1f}C")
            print(f"  Best XX match (direct C): min={min(xx_vals)} max={max(xx_vals)}")
            print(f"  Best XX match (0.5*r-40): min={min(xx_vals)*0.5-40:.1f} max={max(xx_vals)*0.5-40:.1f}")
else:
    print(f"  NRC or unexpected: {' '.join(f'{b:02X}' for b in payload)}")
