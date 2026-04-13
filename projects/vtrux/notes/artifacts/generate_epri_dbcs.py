"""
Generate EPRI-sourced DBC files for the Vtrux from the CANbusLogger2 app plists
and signal metadata extracted from the app binary (format strings).

Sources:
  Via_CANid_List.plist  -> PT bus (GENE MCU, BCM, Bel charger, ESS, etc.)
  Via_OBD_List.plist    -> OBD bus (TRAC MCU + GMLAN engine/chassis signals)
  CANbusLogger2 binary  -> format strings reveal signal units, types, and precision

Output:
  projects/vtrux/epri-pt-bus.dbc
  projects/vtrux/epri-obd-bus.dbc

Byte-level encoding (bit positions, scale, offset) is not available from the
plists or binary strings -- those are compiled into the parser methods.
Each message gets a BO_ stub with a CM_ comment listing all EPRI signals,
their units (from binary format strings), and sampling intervals.
No SG_ entries are added until byte positions are confirmed from logs.
"""

import plistlib
import re
from pathlib import Path

APP_DIR = Path("projects/vtrux/notes/artifacts/epri-app/CANbusLogger2.app")
OUT_DIR = Path("projects/vtrux")

PLIST_PT      = APP_DIR / "Via_CANid_List.plist"
PLIST_OBD = APP_DIR / "Via_OBD_List.plist"

OUT_PT      = OUT_DIR / "epri-pt-bus.dbc"
OUT_OBD = OUT_DIR / "epri-obd-bus.dbc"

# Extended-ID threshold: 11-bit standard IDs are <= 0x7FF
EXT_THRESHOLD = 0x800
DBC_EXT_FLAG  = 0x80000000

# Sampling interval key names as they appear in the plist
INTERVAL_KEYS = ["Parked_Interval", "Operating_Interval", "Driving_Interval", "Charging_Interval"]


def parse_plist(path: Path) -> dict:
    with open(path, "rb") as f:
        return plistlib.load(f)


def parse_key(key: str):
    """
    Parse a plist key like '0054.2' or '18FFD6B3.1' into (can_id_int, signal_index_int_or_None).
    Leading '0x' is optional in the source; the binary plist drops it.
    """
    parts = key.split(".")
    id_str  = parts[0].lstrip("0") or "0"   # strip leading zeros for int parse
    sig_idx = int(parts[1]) if len(parts) > 1 else None
    can_id  = int(id_str, 16)
    return can_id, sig_idx


def dbc_id(can_id: int) -> int:
    """Return the DBC message ID field (set bit 31 for 29-bit extended frames)."""
    if can_id >= EXT_THRESHOLD:
        return can_id | DBC_EXT_FLAG
    return can_id


def id_label(can_id: int) -> str:
    if can_id >= EXT_THRESHOLD:
        return f"0x{can_id:08X}"
    return f"0x{can_id:04X}"


def safe_name(raw: str) -> str:
    """Convert an EPRI description string into a valid DBC signal name."""
    # Take everything after the last colon as the name fragment
    # e.g. "1040: BCM_Status : bcm_gfd" -> "bcm_gfd"
    #      "1072: BCM_Data1: bcm_cell_tmax" -> "bcm_cell_tmax"
    parts = [p.strip() for p in raw.split(":")]
    name = parts[-1]
    # Strip leading numeric prefix (e.g. "B419420096 (2566903744) ...")
    name = re.sub(r"^[B0-9\s()\-\.]+", "", name).strip()
    # Replace spaces and special chars with underscore
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "Unknown"


# -----------------------------------------------------------------------
# Signal metadata extracted from format strings in the CANbusLogger2 binary.
# Each entry: plist_key_prefix -> {name, unit, fmt, notes, also_has (extra
# signals visible in format strings but not individually listed in the plist)}
# -----------------------------------------------------------------------
SIGNAL_META = {
    # 0x0054 -- GENE MCU rotation speed
    "0054":    {"also_has": [
                    ("GENE_RotSpd",         "rpm",   "%d",    "integer RPM; from format: 'GENE_RotSpd = %d rpm'"),
                    ("GENE_EmergcyStp_flg", "",      "bool",  "emergency stop flag; boolean (%@)"),
               ]},

    # 0x0471 -- GENE MCU motor torque
    "0471":    {"also_has": [
                    ("GENE_Mot_Trq",        "Nm",    "%.3f",  "motor torque; 3 decimal places"),
               ]},

    # 0x0479 -- GENE MCU thermal
    "0479":    {"also_has": [
                    ("GENE_DrvCoolFlowReq_pct",  "%",  "%.1f", "driver coolant flow request"),
                    ("GENE_MotCoolFlowReq_pct",  "%",  "%.1f", "motor coolant flow request"),
                    ("GENE_ThermInd_pct",         "%",  "%.1f", "thermal indicator"),
               ]},

    # 0x0482 -- GENE MCU high-power bus
    "0482":    {"also_has": [
                    ("GENE_HighPwr_Curr",   "A",   "%.2f",  "HV DC bus current"),
                    ("GENE_HighPwr_Volt",   "V",   "%.1f",  "HV DC bus voltage"),
               ]},

    # 0x0410 -- BCM status (VCU-relayed BMS data)
    "0410":    {"also_has": [
                    ("bcm_gfd",         "",    "%.2f",  "ground fault detection value"),
                    ("bcm_ibat",        "A",   "%.2f",  "battery current"),
                    ("bcm_soc",         "%",   "%.2f",  "state of charge"),
                    ("bcm_vbat",        "V",   "%.2f",  "battery voltage"),
                    # boolean flags present in format string but not individually in plist:
                    ("bcm_alarm",       "",    "bool",  "alarm flag"),
                    ("bcm_chg_done",    "",    "bool",  "charge done flag"),
                    ("bcm_chgc_stat",   "",    "bool",  "charger contactor status"),
                    ("bcm_cool_req",    "",    "bool",  "cooling request flag"),
                    ("bcm_cpwr_cmd",    "",    "bool",  "charge power command"),
                    ("bcm_epo",         "",    "bool",  "emergency power off"),
                    ("bcm_hvil_mon",    "",    "bool",  "HV interlock monitor"),
                    ("bcm_mainc_stat",  "",    "bool",  "main contactor status"),
                    ("bcm_on_plug",     "",    "bool",  "plug connected flag"),
                    ("bcm_ready",       "",    "bool",  "BMS ready flag"),
               ]},

    # 0x0420 -- BCM limits
    "0420":    {"also_has": [
                    ("bcm_chg_max",          "A",  "%.2f",  "max charge current limit"),
                    ("bcm_dis_max",          "A",  "%.2f",  "max discharge current limit"),
                    ("bcm_cell_overvolt",    "",   "bool",  "cell overvoltage flag"),
                    ("bcm_cell_undervolt",   "",   "bool",  "cell undervoltage flag"),
               ]},

    # 0x0430 -- BCM cell extremes
    "0430":    {"also_has": [
                    ("bcm_cell_tmax",  "degC",  "%.2f",  "hottest cell temperature"),
                    ("bcm_cell_tmin",  "degC",  "%.2f",  "coolest cell temperature"),
                    ("bcm_cell_vmax",  "V",     "%.3f",  "highest cell voltage (3 dp -> mV resolution)"),
                    ("bcm_cell_vmin",  "V",     "%.3f",  "lowest cell voltage"),
                    ("bcm_lvbat",      "V",     "%.2f",  "12V (LV) battery voltage"),
                    # boolean flags in format string:
                    ("bcm_chga_ena",   "",      "bool",  "charger A enable"),
                    ("bcm_chga_mon",   "",      "bool",  "charger A monitor"),
                    ("bcm_mod_ena",    "",      "bool",  "module enable"),
                    ("bcm_veh_mon",    "",      "bool",  "vehicle monitor flag"),
               ]},

    # 0x0440 -- BCM data 2
    "0440":    {"also_has": [
                    ("bcm_balancing_cnt",  "",   "%d",    "cell balancing count (integer)"),
                    ("bcm_fgd",           "%",   "%.2f",  "role unconfirmed (plist label only)"),
                    ("bcm_vbus_neg",       "V",  "%.2f",  "negative HV bus voltage (plist only, not in fmt str)"),
                    ("bcm_vbus_pos",       "V",  "%.2f",  "positive HV bus voltage (plist only, not in fmt str)"),
                    ("bcm_balancing",      "",   "bool",  "cell balancing active"),
                    ("bcm_fault_mon",      "",   "bool",  "fault monitor flag"),
               ]},

    # 0x0592 -- HCU pedal/switch inputs
    "0592":    {"also_has": [
                    ("Veh_BrakePdl_Pos",        "%",   "%.2f",  "brake pedal position (%)"),
                    ("EVSE_Switch_State",        "",    "bool",  "EVSE connected switch"),
                    ("Export_Power_State",       "",    "bool",  "export power switch"),
                    ("Ignition_Key_State",       "",    "bool",  "ignition key state"),
               ]},

    # 0x0598 -- power averages
    "0598":    {"also_has": [
                    ("DBL_ESSPwrAvg",   "W",  "%.2f",  "ESS (battery) average power"),
                    ("DBL_TracPwrAvg",  "W",  "%.2f",  "traction average power"),
               ]},

    # 0x0599 -- oil pressures
    "0599":    {"also_has": [
                    ("TracOilPress",   "?",  "%.2f",  "traction motor oil pressure (units TBD)"),
                    ("GeneOilPress",   "?",  "%.2f",  "generator oil pressure (units TBD)"),
               ]},

    # 0x18FFD5C0 -- Bel charger temperature
    "18FFD5C0": {"also_has": [
                    ("INVCH_Bdc_Temperature_Int",  "degC",  "%.2f",  "Bel charger internal temperature"),
                    ("INVCH_Bdc_TempPercent",       "%",     "%d",    "Bel charger temperature % (integer)"),
               ]},

    # 0x18FFD6B3 -- Bel DCDC feedback
    "18FFD6B3": {"also_has": [
                    ("DCDC_HV_Volt",   "V",    "%.2f",  "DCDC HV input voltage"),
                    ("DCDC_HW_Temp",   "degC", "%.2f",  "DCDC internal temperature"),
                    ("DCDC_LV_Curr",   "A",    "%.2f",  "DCDC LV output current"),
                    ("DCDC_LV_Volt",   "V",    "%.2f",  "DCDC LV output voltage"),
               ]},

    # 0x18FFD6C0 -- Bel inverter AC output
    "18FFD6C0": {"also_has": [
                    ("INVCH_Inv_Iout1_RMS",  "A",  "%.2f",  "inverter output current phase 1 RMS"),
                    ("INVCH_Inv_Iout2_RMS",  "A",  "%.2f",  "inverter output current phase 2 RMS"),
                    ("INVCH_Inv_Vout1_RMS",  "V",  "%.2f",  "inverter output voltage phase 1 RMS"),
                    ("INVCH_Inv_Vout2_RMS",  "V",  "%.2f",  "inverter output voltage phase 2 RMS"),
               ]},

    # 0x18FFD7C0 -- Bel charger battery charging input
    "18FFD7C0": {"also_has": [
                    ("INVCH_Bdc_Ibat",      "A",  "%.2f",  "battery charge current"),
                    ("INVCH_Bdc_Vbat",      "V",  "%.2f",  "battery charge voltage"),
                    ("INVCH_Chg_Iin_RMS",   "A",  "%.2f",  "AC input current RMS"),
                    ("INVCH_Chg_Vin_RMS",   "V",  "%.2f",  "AC input voltage RMS"),
               ]},

    # 0x18FFD8C0 -- Bel J1772 state
    "18FFD8C0": {"also_has": [
                    ("INVCH_Bdc_J1772",      "",   "%d",    "J1772 state (integer enum)"),
                    ("INVCH_Bdc_12Vbat",     "V",  "%.1f",  "12V battery measured by Bel unit"),
               ]},

    # 0x0868A047 / 0x0870A047 -- A/C compressor (EAC) -- J1939-style extended IDs
    "868A047":  {"also_has": [
                    ("EAC_Elec_Curr",    "A",   "%.2f",  "A/C compressor electrical current"),
                    ("EAC_Elec_Pwr",     "W",   "%d",    "A/C compressor electrical power (integer Watts)"),
                    ("EAC_CompFltStat",  "",    "bool",  "A/C compressor fault status"),
                    ("AC_status",        "",    "bool",  "A/C compressor on/off status"),
               ]},
    "870A047":  {"also_has": [
                    ("EAC_CompHVInput",  "V",   "%d",    "A/C compressor HV input voltage (integer VDC)"),
               ]},

    # 0x06000001 -- EPT HMI (likely GoPoint internal, wraps EPT bus data)
    "6000001":  {"also_has": [
                    ("Accel_Ped_Pos",  "%",    "%.2f",  "accelerator pedal position (%)"),
                    ("Veh_Speed",      "km/h", "%.3f",  "vehicle speed"),
               ]},

    # --- Vehicle bus (OBD) signals ---
    "0044":    {"also_has": [
                    ("TRAC_RotSpd",         "rpm",  "%d",    "traction motor RPM (integer); 'TRAC_RotSpd = %d rpm'"),
                    ("TRAC_EmergcyStp_flg", "",     "bool",  "traction emergency stop flag"),
               ]},

    "0451":    {"also_has": [
                    ("TRAC_Mot_Trq",  "Nm",  "%.3f",  "traction motor torque; 3 decimal places"),
               ]},

    "0459":    {"also_has": [
                    ("TRAC_DrvCoolFlowReq_pct",  "%",  "%.1f",  "traction driver coolant flow request"),
                    ("TRAC_MotCoolFlowReq_pct",  "%",  "%.1f",  "traction motor coolant flow request"),
                    ("TRAC_ThermInd_pct",         "%",  "%.1f",  "traction thermal indicator"),
               ]},

    "0462":    {"also_has": [
                    ("TRAC_HighPwr_Curr",  "A",  "%.2f",  "traction HV DC bus current"),
                    ("TRAC_HighPwr_Volt",  "V",  "%.1f",  "traction HV DC bus voltage"),
               ]},

    # GMLAN signals on vehicle bus -- units from format strings
    "00C9":    {"also_has": [
                    ("Engine_Speed",  "rpm",  "%.1f",  "engine RPM; 'Engine speed = %.1f rpm'"),
               ]},

    "01C3":    {"also_has": [
                    ("Engine_Torque_Actual",     "Nm",  "%.1f",  "engine actual torque"),
                    ("Engine_Torque_Requested",  "Nm",  "%.1f",  "engine requested torque"),
               ]},

    "03D1":    {"also_has": [
                    ("Throttle_Position",  "%",  "%.0f",  "throttle position %; 'Throttle position = %3.0f%%'"),
               ]},

    "03E9":    {"also_has": [
                    ("VehSpdAvgDrvn_linspd",       "km/h",  "%.3f",  "vehicle speed"),
                    ("DistRollCntAvgDrvn_dist",    "km",    "%.2f",  "distance traveled"),
               ]},

    "04C1":    {"also_has": [
                    ("Engine_Coolant_Temp",      "degC",  "%d",    "engine coolant temperature (integer)"),
                    ("Engine_Air_Intake_Temp",   "degC",  "%d",    "engine air intake temperature (integer)"),
                    ("Outside_Air_Temp",         "degC",  "%.1f",  "outside air temperature estimate"),
               ]},
}


def build_message_map(plist_data: dict) -> dict:
    """
    Returns {can_id: {"signals": [(sig_idx, epri_key, desc, intervals)], "dlc": int}}
    Intervals dict: {key: value_seconds}
    """
    messages = {}
    for key, entry in plist_data.items():
        can_id, sig_idx = parse_key(key)
        desc = entry.get("Description", "")
        intervals = {k: entry.get(k, 0) for k in INTERVAL_KEYS}

        if can_id not in messages:
            messages[can_id] = {"signals": []}
        messages[can_id]["signals"].append((sig_idx, key, desc, intervals))

    # Sort signals within each message by index (None = whole-message entry, sort first)
    for mid in messages:
        messages[mid]["signals"].sort(key=lambda x: (x[0] is None, x[0] or 0))

    return messages


def intervals_str(intervals: dict) -> str:
    parts = []
    for k, v in intervals.items():
        label = k.replace("_Interval", "")
        parts.append(f"{label}={v}s")
    return ", ".join(parts)


DBC_HEADER = """\
VERSION ""


NS_ :
\tNS_DESC_
\tCM_
\tBA_DEF_
\tBA_
\tVAL_
\tCAT_DEF_
\tCAT_
\tFILTER
\tBA_DEF_DEF_
\tEV_DATA_
\tENVVAR_DATA_
\tSGTYPE_
\tSGTYPE_VAL_
\tBA_DEF_SGTYPE_
\tBA_SGTYPE_
\tSIG_TYPE_REF_
\tVAL_TABLE_
\tSIG_GROUP_
\tSIG_VALTYPE_
\tSIGTYPE_VALTYPE_
\tBO_TX_BU_
\tBA_DEF_REL_
\tBA_REL_
\tBA_DEF_DEF_REL_
\tBU_SG_REL_
\tBU_EV_REL_
\tBU_BO_REL_
\tSG_MUL_VAL_

BS_:

BU_:

"""


def _meta_key(can_id: int) -> str:
    """Return the SIGNAL_META lookup key for a CAN ID.
    Try exact hex, then with leading zeros stripped, then with 4-digit zero-padded."""
    raw = f"{can_id:X}"
    if raw in SIGNAL_META:
        return raw
    stripped = raw.lstrip("0") or "0"
    if stripped in SIGNAL_META:
        return stripped
    padded = f"{can_id:04X}"
    return padded


def write_dbc(path: Path, bus_label: str, source_plist: str, messages: dict):
    lines = [DBC_HEADER]

    # Sort messages by CAN ID for readability
    for can_id in sorted(messages):
        entry   = messages[can_id]
        signals = entry["signals"]
        db_id   = dbc_id(can_id)
        id_str  = id_label(can_id)

        # Build message name from first signal description class
        first_desc = signals[0][2] if signals else ""
        msg_class  = ""
        m = re.search(r":\s*([A-Za-z][A-Za-z0-9_]+)", first_desc)
        if m:
            msg_class = m.group(1)
        if not msg_class:
            msg_class = f"MSG_{id_str.replace('0x', '')}"
        msg_name = f"EPRI_{msg_class}_{id_str.replace('0x', '')}"

        dlc = 8  # placeholder
        lines.append(f"BO_ {db_id} {msg_name}: {dlc} Vector__XXX\n\n")

    lines.append("\n")

    # CM_ blocks for each message
    for can_id in sorted(messages):
        entry   = messages[can_id]
        signals = entry["signals"]
        db_id   = dbc_id(can_id)
        id_str  = id_label(can_id)

        # Plist signal list
        plist_lines = []
        for sig_idx, pkey, desc, intervals in signals:
            iv_str = intervals_str(intervals)
            plist_lines.append(f"  plist[{pkey}] {desc} -- sampled: {iv_str}")

        # Binary-derived signal metadata
        meta = SIGNAL_META.get(_meta_key(can_id), {})
        bin_lines = []
        for name, unit, fmt, note in meta.get("also_has", []):
            unit_str = f" [{unit}]" if unit else ""
            bin_lines.append(f"  binary: {name}{unit_str} fmt={fmt} -- {note}")

        cm_body = (
            f"EPRI source: {source_plist}, bus: {bus_label}. "
            f"DLC=8 placeholder -- verify against log. "
            f"Byte positions/scales not available; derived from log analysis only.\\n"
            f"--- Plist signals ({len(plist_lines)}) ---\\n"
            + "\\n".join(plist_lines)
        )
        if bin_lines:
            cm_body += (
                f"\\n--- Binary format-string signals ({len(bin_lines)}) ---\\n"
                + "\\n".join(bin_lines)
            )

        cm_body = cm_body.replace('"', "'")
        lines.append(f'CM_ BO_ {db_id} "{cm_body}";\n\n')

    with open(path, "w", encoding="ascii", errors="replace") as f:
        f.write("".join(lines))

    print(f"Written: {path}  ({len(messages)} messages)")


def main():
    print("Parsing plists...")
    pt_data  = parse_plist(PLIST_PT)
    obd_data = parse_plist(PLIST_OBD)

    print(f"  PT bus:      {len(pt_data)} entries")
    print(f"  OBD bus:  {len(obd_data)} entries")

    pt_messages  = build_message_map(pt_data)
    obd_messages = build_message_map(obd_data)

    print(f"  PT bus:      {len(pt_messages)} unique CAN IDs")
    print(f"  OBD bus:  {len(obd_messages)} unique CAN IDs")

    # Print a summary of what's in each
    print("\n--- PT bus messages ---")
    for can_id in sorted(pt_messages):
        sigs = pt_messages[can_id]["signals"]
        names = [s[2][:60] for s in sigs]
        print(f"  {id_label(can_id):18s}  {len(sigs)} signal(s)  eg: {names[0]}")

    print("\n--- OBD bus messages ---")
    for can_id in sorted(obd_messages):
        sigs = obd_messages[can_id]["signals"]
        names = [s[2][:60] for s in sigs]
        print(f"  {id_label(can_id):18s}  {len(sigs)} signal(s)  eg: {names[0]}")

    print("\nWriting DBC files...")
    write_dbc(OUT_PT,  "PT bus",     "Via_CANid_List.plist", pt_messages)
    write_dbc(OUT_OBD, "OBD bus", "Via_OBD_List.plist",   obd_messages)

    print("\nDone.")


if __name__ == "__main__":
    main()
