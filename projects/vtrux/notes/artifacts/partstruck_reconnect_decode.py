"""
Decode key BMS/contactor signals from vtrux__partstruck_reconnect.log
to diagnose why battery reconnect is failing.

Focus signals (all Bus2 = PT bus, anchor 0x051):
  0x400 B0: hsc_bcm_enable(bit0), hsc_bcm_epo(bit1), hsc_bcm_mainc_close(bit2), hsc_bcm_leakage_ena(bit3)
  0x410 B0: interlock loop state (bit3=1 closed); B1: BMS state machine (0xBF=normal, 0xCF=fault)
            B2: 0xA0=normal, 0xFE=settled fault state, 0x00=isolation-fault ordered shutdown
  0x420 B3: isolation resistance (0xC8=init, 192=nominal, 0=fault/powerdown)
  0x440: bcm_mainc_stat (B2[7:4] 4-bit contactor seq), bcm_vbus_pos (B0-B1 12-bit Motorola *0.25V)
         bcm_vbus_neg (B3-B4 12-bit Motorola *0.25-500V), bcm_fault_mon (B6 bit7)
  0x470 B0-B1: HV bus voltage (11-bit LE, 1 V/count)
"""

import sys
sys.path.insert(0, ".")
from canre.parsers.autodetect import parse_file

LOG = "projects/vtrux/logs/vtrux__partstruck_reconnect.log"

frames = list(parse_file(LOG))

PT_ANCHOR = 0x051
pt_bus = None
bus_anchors = {}
for f in frames:
    if f.arbitration_id == PT_ANCHOR:
        bus_anchors[f.bus] = bus_anchors.get(f.bus, 0) + 1
for b, cnt in bus_anchors.items():
    if cnt > 10:
        pt_bus = b
        break

print(f"PT bus identified as: Bus{pt_bus}")
print()

TARGET_IDS = {0x400, 0x410, 0x420, 0x430, 0x440, 0x470}

pt_frames = [f for f in frames if f.bus == pt_bus and f.arbitration_id in TARGET_IDS]
pt_frames.sort(key=lambda f: f.timestamp)

if not pt_frames:
    print("ERROR: No target frames found on PT bus")
    sys.exit(1)

t0 = pt_frames[0].timestamp

def decode_440(data):
    if len(data) < 7:
        return {}
    b0, b1, b2, b3, b4, b5, b6 = data[0], data[1], data[2], data[3], data[4], data[5], data[6]
    vbus_pos_raw = ((b0 & 0xFF) << 4) | (b1 >> 4)
    vbus_pos = vbus_pos_raw * 0.25
    vbus_neg_raw = ((b3 & 0xFF) << 4) | (b4 >> 4)
    vbus_neg = vbus_neg_raw * 0.25 - 500.0
    mainc_stat = (b2 >> 4) & 0x0F
    fault_mon = (b6 >> 7) & 0x01
    return {"vbus_pos": vbus_pos, "vbus_neg": vbus_neg, "mainc_stat": mainc_stat, "fault_mon": fault_mon}

def decode_470(data):
    if len(data) < 2:
        return {}
    raw = data[0] | ((data[1] & 0x07) << 8)
    return {"hv_volt": raw}

def decode_400(data):
    if len(data) < 1:
        return {}
    b = data[0]
    return {
        "enable": (b >> 0) & 1,
        "epo": (b >> 1) & 1,
        "mainc_close": (b >> 2) & 1,
        "leakage_ena": (b >> 3) & 1,
    }

def decode_410(data):
    if len(data) < 3:
        return {}
    b0, b1, b2 = data[0], data[1], data[2]
    interlock = (b0 >> 3) & 1
    state_label = {0xBF: "NORMAL", 0xCF: "FAULT_LATCHED"}.get(b1, f"0x{b1:02X}")
    b2_label = {0xA0: "normal", 0xFE: "settled_fault", 0x00: "isolation_shutdown"}.get(b2, f"0x{b2:02X}")
    return {"interlock_closed": interlock, "bms_state": state_label, "b1_raw": b1, "b2_label": b2_label, "b2_raw": b2}

def decode_420(data):
    if len(data) < 4:
        return {}
    b3 = data[3]
    iso_label = {200: "init/no_result", 0: "fault_or_powerdown"}.get(b3, str(b3))
    return {"iso_r": b3, "iso_label": iso_label}

last = {}
prev = {}

PRINT_IDS = TARGET_IDS

for f in pt_frames:
    t = f.timestamp - t0
    d = f.data
    aid = f.arbitration_id

    if aid == 0x400:
        dec = decode_400(d)
    elif aid == 0x410:
        dec = decode_410(d)
    elif aid == 0x420:
        dec = decode_420(d)
    elif aid == 0x440:
        dec = decode_440(d)
    elif aid == 0x470:
        dec = decode_470(d)
    else:
        dec = {}

    key = (aid,)
    if last.get(key) != dec:
        raw_hex = " ".join(f"{b:02X}" for b in d)
        print(f"t={t:7.3f}s  ID=0x{aid:03X}  raw=[{raw_hex}]")
        if dec:
            for k, v in dec.items():
                print(f"             {k} = {v}")
        last[key] = dec
        print()
