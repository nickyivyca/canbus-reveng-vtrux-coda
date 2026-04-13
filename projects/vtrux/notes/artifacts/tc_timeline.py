"""
Transfer case timeline analysis.
Sequence (from sidecar): 4H -> 2H -> N -> 4L -> N -> rev motor -> 2H
Find which IDs show state transitions at TC shift times, and what happens during motor rev.
"""
import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file

LOG = "projects/vtrux/logs/vtrux_transfer_case_test.log"

frames = list(parse_file(LOG))
print(f"Total frames: {len(frames):,}  span: {frames[0].timestamp:.2f}-{frames[-1].timestamp:.2f}s")

BUS1 = 1
BUS2 = 2
BUS3 = 3

def bus_label(bus):
    anchor = {1: "OBD", 2: "PT", 3: "VEH"}
    return anchor.get(bus, str(bus))

def get_frames(arb_id, bus=None):
    if bus is None:
        return [f for f in frames if f.arbitration_id == arb_id]
    return [f for f in frames if f.arbitration_id == arb_id and f.bus == bus]

def show_transitions(arb_id, bus, label="", byte_indices=None):
    frms = get_frames(arb_id, bus)
    if not frms:
        print(f"  0x{arb_id:03X} bus={bus}: no frames")
        return
    if byte_indices is None:
        byte_indices = list(range(len(frms[0].data)))
    prev = None
    changes = []
    for f in frms:
        key = tuple(f.data[i] for i in byte_indices if i < len(f.data))
        if key != prev:
            changes.append((f.timestamp, prev, key))
            prev = key
    print(f"\n  0x{arb_id:03X} bus={bus_label(bus)} ({label}): {len(frms)} frames, {len(changes)} transitions")
    for t, old, new in changes:
        old_s = " ".join(f"{b:02X}" for b in old) if old else "START"
        new_s = " ".join(f"{b:02X}" for b in new)
        print(f"    t={t:7.3f}s  {old_s:20s} -> {new_s}")

print("\n=== TRANSFER CASE CANDIDATES ===")

show_transitions(0x1CF, BUS3, "Secondary_Axle_General_Info (TCCM_RDCM)")
show_transitions(0x1CF, BUS1, "Secondary_Axle_General_Info (OBD mirror)")

show_transitions(0x17D, BUS3, "Antilock_Brake_and_TC_Status (EBCM)", byte_indices=[0])

show_transitions(0x135, BUS3, "0x135 Bus3")

show_transitions(0x140, BUS3, "0x140 Bus3 (low-rate)")

show_transitions(0x233, BUS3, "0x233 Bus3 (very low rate)")

show_transitions(0x1F3, BUS3, "0x1F3 Bus3")

show_transitions(0x1A3, BUS3, "0x1A3 Bus3")

print("\n=== SHIFTER POSITION / INVALIDITY ===")

show_transitions(0x1F5, BUS3, "Transmission_General_Status_2 (VEH)")
show_transitions(0x4C9, BUS3, "Transmission_General_Status_3 (VEH)")

print("\n=== MOTOR REV INDICATORS (PT bus) ===")
show_transitions(0x308, BUS2, "BorgWarner park pin (PT)", byte_indices=[0])
show_transitions(0x55C, BUS2, "BorgWarner TCM state (PT)", byte_indices=[0])

print("\n=== WHAT CHANGES DURING MOTOR REV WINDOW ===")
print("(Looking for events that start/end in the rev window)")

import cantools
try:
    gmlan_db = cantools.db.load_file("projects/vtrux/GMW8762_PPEI_GMLAN.dbc", strict=False)
    has_cantools = True
except Exception as e:
    print(f"  cantools load failed: {e}")
    has_cantools = False

if has_cantools:
    print("\n  Decoding 0x1CF (Secondary_Axle_General_Info) transitions:")
    msg_1cf = gmlan_db.get_message_by_frame_id(0x1CF)
    frms_1cf = get_frames(0x1CF, BUS3)
    prev_dec = None
    for f in frms_1cf:
        try:
            dec = gmlan_db.decode_message(0x1CF, bytes(f.data))
        except Exception:
            continue
        if dec != prev_dec:
            print(f"    t={f.timestamp:7.3f}s  {dec}")
            prev_dec = dec

    print("\n  Decoding 0x17D (Antilock_Brake_TC) transitions:")
    try:
        msg_17d = gmlan_db.get_message_by_frame_id(0x17D)
        frms_17d = get_frames(0x17D, BUS3)
        prev_dec = None
        for f in frms_17d:
            try:
                dec = gmlan_db.decode_message(0x17D, bytes(f.data[:msg_17d.length]))
            except Exception:
                continue
            if dec != prev_dec:
                print(f"    t={f.timestamp:7.3f}s  {dec}")
                prev_dec = dec
    except Exception as e:
        print(f"  failed: {e}")

print("\n=== ALL IDS THAT CHANGE VALUE DURING LOG (sorted by number of unique values) ===")
from collections import defaultdict
id_states = defaultdict(set)
for f in frames:
    id_states[(f.arbitration_id, f.bus)].add(bytes(f.data))

changing = [(aid, bus, len(vals)) for (aid, bus), vals in id_states.items() if len(vals) > 1]
changing.sort(key=lambda x: -x[2])

print(f"  {'ID':8s}  {'Bus':4s}  {'#unique':8s}")
for aid, bus, n in changing[:40]:
    print(f"  0x{aid:06X}  {bus_label(bus):4s}  {n}")
