"""
Compare OBD-bus ECM messages between:
  - reference log (VCM present, all 3 buses)
  - T3 log (VCM B-connector disconnected)

For each ID that appears on the OBD bus in the reference, report whether it
appears on the Vehicle bus in T3 (ECM-native on Vehicle) or is absent from
Vehicle bus in T3 (was VCM-bridged).

Also flags IDs that appear on Vehicle bus in reference but drop in T3 (VCM-bridged).
"""

import re
import collections
from pathlib import Path

LOGS = Path(r"<repo>\projects\vtrux\logs")

REF_LOG = LOGS / "generator-on-then-off.log"
T3_LOG  = LOGS / "vtruxwoodwardbconnectordisconnected.log"

FRAME_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2}:\d{4})\s+\w+\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[se]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)"
)

VEHICLE_ANCHORS = {"1E5", "500", "514", "52A", "52B", "52C", "778", "780", "785", "788"}
OBD_ANCHORS     = {"40", "41", "42", "43", "44", "C9", "3D1", "3E9"}
PT_ANCHORS      = {"51", "52", "639", "63A", "63B", "64B"}


def load_log(fpath):
    """Return {channel: set_of_ids} and identify OBD/Vehicle/PT channels."""
    ch_ids = collections.defaultdict(set)
    with open(fpath, encoding="latin-1", errors="replace") as f:
        for line in f:
            m = FRAME_RE.match(line.strip())
            if not m:
                continue
            _, ch, arb, dlc, data = m.groups()
            ch_ids[ch].add(arb.upper())
    return ch_ids


def identify_buses(ch_ids):
    buses = {}
    for ch, ids in ch_ids.items():
        if ids & VEHICLE_ANCHORS:
            buses["vehicle"] = ch
        if ids & OBD_ANCHORS and "C9" in ids:
            buses["obd"] = ch
        if ids & PT_ANCHORS:
            buses["pt"] = ch
    return buses


def main():
    print("Loading reference log...")
    ref_ch  = load_log(REF_LOG)
    ref_bus = identify_buses(ref_ch)
    print(f"  Reference buses: {ref_bus}")

    print("Loading T3 disconnect log...")
    t3_ch  = load_log(T3_LOG)
    t3_bus = identify_buses(t3_ch)
    print(f"  T3 buses: {t3_bus}")
    print()

    if "obd" not in ref_bus or "vehicle" not in ref_bus:
        print("ERROR: could not identify OBD or Vehicle bus in reference log")
        return
    if "vehicle" not in t3_bus:
        print("ERROR: could not identify Vehicle bus in T3 log")
        return

    ref_obd     = ref_ch[ref_bus["obd"]]
    ref_vehicle = ref_ch[ref_bus["vehicle"]]
    t3_vehicle  = t3_ch[t3_bus["vehicle"]]
    t3_obd      = t3_ch.get(t3_bus.get("obd", ""), set())

    print(f"Reference OBD bus (ch{ref_bus['obd']}):      {len(ref_obd)} unique IDs")
    print(f"Reference Vehicle bus (ch{ref_bus['vehicle']}):  {len(ref_vehicle)} unique IDs")
    print(f"T3 Vehicle bus (ch{t3_bus['vehicle']}):           {len(t3_vehicle)} unique IDs")
    if t3_obd:
        print(f"T3 OBD bus (ch{t3_bus.get('obd','?')}):              {len(t3_obd)} unique IDs")
    print()

    obd_only_ref    = ref_obd - ref_vehicle
    both_buses_ref  = ref_obd & ref_vehicle
    vehicle_only_ref = ref_vehicle - ref_obd

    print("=== IDs on OBD bus in reference: breakdown by Vehicle bus presence in T3 ===")
    print()

    print("--- In reference on BOTH OBD and Vehicle bus ---")
    survived  = sorted(x for x in both_buses_ref if x in t3_vehicle)
    dropped   = sorted(x for x in both_buses_ref if x not in t3_vehicle)
    print(f"  Survived on Vehicle bus in T3 ({len(survived)}) -- ECM-native on Vehicle bus:")
    for x in survived:
        print(f"    0x{x}")
    print(f"  Dropped from Vehicle bus in T3 ({len(dropped)}) -- was VCM-bridged OBD->Vehicle:")
    for x in dropped:
        print(f"    0x{x}")
    print()

    print("--- In reference on OBD bus ONLY (not on Vehicle bus in reference) ---")
    now_on_veh  = sorted(x for x in obd_only_ref if x in t3_vehicle)
    still_absent = sorted(x for x in obd_only_ref if x not in t3_vehicle)
    print(f"  Appear on Vehicle bus in T3 ({len(now_on_veh)}) -- unexpected:")
    for x in now_on_veh:
        print(f"    0x{x}")
    print(f"  Still absent from Vehicle bus in T3 ({len(still_absent)}) -- OBD-only:")
    for x in still_absent[:20]:
        print(f"    0x{x}")
    if len(still_absent) > 20:
        print(f"    ... and {len(still_absent)-20} more")
    print()

    print("--- Vehicle bus IDs in reference NOT on OBD bus (non-ECM origin) ---")
    veh_only_survived = sorted(x for x in vehicle_only_ref if x in t3_vehicle)
    veh_only_dropped  = sorted(x for x in vehicle_only_ref if x not in t3_vehicle)
    print(f"  Survived in T3 ({len(veh_only_survived)}) -- native Vehicle bus module:")
    for x in veh_only_survived:
        print(f"    0x{x}")
    print(f"  Dropped in T3 ({len(veh_only_dropped)}) -- VCM-generated or VCM-bridged PT->Vehicle:")
    for x in veh_only_dropped:
        print(f"    0x{x}")


if __name__ == "__main__":
    main()
