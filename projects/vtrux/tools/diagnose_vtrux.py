#!/usr/bin/env python3
"""Vtrux general diagnostic tool.

Decodes all known fault/status signals from a Vtrux PT-bus log and produces a
timeline of state changes with fault tagging, plus initial/final state snapshots
and a fault summary.

Not focused on charging -- covers any log type: battery reconnect, drive, idle,
fault investigation, etc.

Usage:
  py -3.12 projects/vtrux/tools/diagnose_vtrux.py FILE [FILE ...]
  py -3.12 projects/vtrux/tools/diagnose_vtrux.py FILE --output report.txt
"""
import argparse
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from canre.utils.merge import merge_files

# ---------------------------------------------------------------------------
# Bus identification
# ---------------------------------------------------------------------------

PT_BUS_ANCHOR  = 0x051   # exclusive to PT bus; identifies channel
OBD_BUS_ANCHOR = 0x044   # exclusive to OBD bus (TRAC MCU speed)
VEH_BUS_ANCHOR = 0x1E5   # exclusive to Vehicle bus (GMLAN)

# ---------------------------------------------------------------------------
# Signal target IDs to accumulate (PT bus unless noted)
# ---------------------------------------------------------------------------

PT_TARGETS = {
    0x053,   # HCU: OperationMode + OperationState
    0x054,   # GENE MCU: RotSpd + EmergencyStop flag
    0x400,   # HSC_BCM_Ctrl: contactor/EPO control bits
    0x410,   # A123 BMS status: hvil, alarm, ibat, soc, vbat, gfd, etc.
    0x420,   # A123 BMS limits: chg_max, dis_max, cell OV/UV, iso_r
    0x430,   # A123 BMS data1: cell voltages, temps, 12V battery
    0x440,   # A123 BMS data2: contactor state sequence, vbus rails
    0x411,   # BMS SoC hi-res
    0x592,   # HCU sensor inputs: ignition, EVSE switch, export
    0x065B,  # HCU DTC code dispatcher
}

OBD_TARGETS = {
    0x044,   # TRAC MCU: RotSpd + EmergencyStop flag (OBD bus only)
}

ALL_TARGETS = PT_TARGETS | OBD_TARGETS

SEP = "=" * 72

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

ALARM_STRS = ["NONE", "TYPE1", "TYPE2", "TYPE3"]
CHGC_STRS  = ["OPEN", "CLOSED", "HIGH", "LOW"]

OP_MODE_STRS  = {0: "NTRL", 1: "Invalid(1)", 2: "Invalid(2)", 3: "Invalid(3)"}
OP_STATE_STRS = {
    0: "INIT", 1: "STBY", 2: "ACTIVATION", 3: "DEACTIVATION",
    4: "OPERATIONAL", 5: "FAILURE", 6: "SHTDWN",
    7: "WAIT4COOLING", 8: "PWR_OFF_RDY",
}

# 4-bit contactor sequence state machine (bcm_mainc_stat in 0x440)
MAINC_STAT_16 = [
    "ALL_OPEN",               # 0  normal idle
    "FAILED_MAINP_OR_R_WELD", # 1  fault
    "CLOSE_MAINR",            # 2  precharge resistor closing
    "FAILED_MAINR_OPEN",      # 3  fault
    "FAILED_MAINN_WELD",      # 4  fault
    "CLOSE_MAINN",            # 5  negative main closing
    "FAILED_MAINN_OPEN",      # 6  fault
    "WAIT_PRECHARGE",         # 7  precharging
    "CLOSE_MAINP",            # 8  positive main closing
    "OPEN_MAINR",             # 9  precharge resistor opening (normal end)
    "FAILED_MAINP_OPEN",      # 10 fault
    "MAIN_PN_CLOSED_DRIVE",   # 11 drive (P+N closed)
    "MAIN_P_CLOSED_CHARGE",   # 12 charge (P closed)
    "SHUTDOWN_REQUEST",       # 13
    "ALL_OPEN_SHUTDOWN",      # 14
    "(idx15)",                # 15
]

MAINC_STAT_FAULT_IDX = {1, 3, 4, 6, 10}

BMS_B1_NAMES = {0xBF: "NORMAL", 0xCF: "FAULT_LATCHED", 0xFF: "EPO_TRANSITION"}
BMS_B2_NAMES = {0xA0: "normal", 0xFE: "settled_fault", 0x00: "isolation_shutdown"}

DTC_TABLE = {
    0x0D67: "aChgr_p0d67ChgrPfrm",
    0x1A20: "sEss_p1a20BecmAFlt",
    0x0A7B: "sEss_p0a7bBecmMilOnReq",
    0x1A21: "sEss_p1a21BecmACritFlt",
    0x1A81: "sEss_p1a81HvilPrfmGene",
    0x1A82: "sEss_p1a82HvilPrfmTrac",
    0x1A80: "sEss_p1a80HvilPrfmDcdc",
    0x0AA6: "sEss_p0aa6HvIso",
    0x1AA0: "sChgr_p1aa0ChgrShtdwn",
    0x0A0B: "cEss_p0a0bHvilPrfm",
    0x0A1F: "cEss_p0a1fEss",
    0xD300: "diagHcu_u1300AppIntrptTsk",
    0xD301: "diagHcu_u1301LowMemTsk2",
    0xD302: "diagHcu_u1302LowMemTsk1",
    0xD303: "diagHcu_u1303LowMemIdleTsk",
    0xD304: "diagHcu_u1304LowMemIntrpt",
    0xD305: "diagHcu_u1305LowMemKernel",
    0xD306: "diagHcu_u1306ShtdwnTsk",
    0xD307: "diagHcu_u1307LowMemHeap",
    0xD311: "diagHcu_u1311HighCpuTsk2",
    0xD310: "diagHcu_u1310HighCpuAppIntrptTsk",
    0xD312: "diagHcu_u1312HighCpuTsk1",
    0xD313: "diagHcu_u1313HighCpuShtdwnTsk",
    0xD314: "diagHcu_u1314CpuIdleApp",
    0xC129: "inAbstrCanEbcm_u0129LostRx",
    0xC100: "inAbstrCanEcm_u0100LostRx",
    0xC16B: "inAbstrCanAccm_u016BLostRx",
    0xC111: "inAbstrCanBecm_u0111LostRx",
    0xC296: "inAbstrCanBdc_u0296LostRx",
}

# ---------------------------------------------------------------------------
# Frame collection -- single pass
# ---------------------------------------------------------------------------

def collect_frames(paths):
    """Single pass: identify buses, accumulate target frames.

    Returns:
        pt_bus (int|None)
        obd_bus (int|None)
        accumulated (dict[int, list[(t, bytes)]])  -- all buses merged by ID
        duration (float)
        frame_count (int)
    """
    # Bel Inverter extended IDs -- presence indicates a charging log
    BEL_IDS = {0x18FFD4C0, 0x18FFD5C0, 0x18FFD7C0, 0x18FFD8C0, 0x18FFD9C0}

    pt_bus = obd_bus = None
    accumulated = {aid: [] for aid in ALL_TARGETS}
    duration = 0.0
    frame_count = 0
    bel_seen = False

    for frame in merge_files(paths):
        frame_count += 1
        duration = frame.timestamp
        if frame_count % 5000 == 0:
            print(f"\r  reading... {frame_count:,} frames  t={duration:.1f}s",
                  end='', flush=True, file=sys.stderr)

        if pt_bus is None and frame.arbitration_id == PT_BUS_ANCHOR:
            pt_bus = frame.bus
        if obd_bus is None and frame.arbitration_id == OBD_BUS_ANCHOR:
            obd_bus = frame.bus
        if not bel_seen and frame.arbitration_id in BEL_IDS:
            bel_seen = True

        if frame.arbitration_id in ALL_TARGETS:
            is_pt_target  = (pt_bus is not None  and frame.bus == pt_bus  and frame.arbitration_id in PT_TARGETS)
            is_obd_target = (obd_bus is not None and frame.bus == obd_bus and frame.arbitration_id in OBD_TARGETS)
            if is_pt_target or is_obd_target:
                accumulated[frame.arbitration_id].append((frame.timestamp, frame.data))

    if frame_count >= 5000:
        print(f"\r  {frame_count:,} frames read ({duration:.1f}s)          ", file=sys.stderr)
    return pt_bus, obd_bus, accumulated, duration, frame_count, bel_seen


# ---------------------------------------------------------------------------
# Decoders -- return dict of named values, or None on bad DLC
# ---------------------------------------------------------------------------

def _b(data, byte_idx, bit):
    return (data[byte_idx] >> bit) & 1 if byte_idx < len(data) else None


def decode_0x053(data):
    if len(data) < 1:
        return None
    b = data[0]
    mode_idx  = (b >> 4) & 0x7
    state_idx = b & 0xF
    return {
        'op_mode':  OP_MODE_STRS.get(mode_idx,  f"mode({mode_idx})"),
        'op_state': OP_STATE_STRS.get(state_idx, f"state({state_idx})"),
        'raw': b,
    }


def decode_0x054_or_0x044(data):
    """GENE MCU (0x054, PT bus) or TRAC MCU (0x044, OBD bus) -- same layout."""
    if len(data) < 5:
        return None
    rot_raw = data[0] | (data[1] << 8)
    rpm = rot_raw - 32767
    return {
        'rpm':       rpm,
        'emerstop':  _b(data, 4, 3),
    }


def decode_0x400(data):
    if len(data) < 1:
        return None
    b = data[0]
    return {
        'hsc_enable':      b & 1,
        'hsc_epo':         (b >> 1) & 1,
        'hsc_mainc_close': (b >> 2) & 1,
        'hsc_leakage_ena': (b >> 3) & 1,
    }


def decode_0x410(data):
    if len(data) < 8:
        return None
    B0, B1, B2, B3, B4, B5, B6, B7 = data[:8]
    alarm_idx    = (B1 >> 6) & 3
    chgc_idx     = (B0 >> 6) & 3
    raw_gfd      = B2 | ((B1 & 0xF) << 8)
    raw_vbat     = B7 | ((B6 & 0xF) << 8)
    raw_ibat     = (B4 << 8) | B5
    b1_name      = BMS_B1_NAMES.get(B1, f"0x{B1:02X}")
    b2_name      = BMS_B2_NAMES.get(B2, f"0x{B2:02X}")
    return {
        'hvil_mon':   (B0 >> 3) & 1,
        'epo':        (B0 >> 1) & 1,
        'on_plug':    (B0 >> 2) & 1,
        'ready':      B0 & 1,
        'cpwr_cmd':   (B1 >> 4) & 1,
        'chg_done':   (B6 >> 4) & 1,
        'cool_req':   (B6 >> 5) & 1,
        'alarm':      ALARM_STRS[alarm_idx],
        'chgc_stat':  CHGC_STRS[chgc_idx],
        'bms_b1':     b1_name,
        'bms_b2':     b2_name,
        'bms_b1_raw': B1,
        'bms_b2_raw': B2,
        'gfd':        None if raw_gfd >= 0xFFE else round(raw_gfd * 0.25, 2),
        'soc':        None if B3 >= 0xFE        else round(B3 * 0.5, 1),
        'vbat':       None if raw_vbat >= 0xFFE else round(raw_vbat * 0.25, 1),
        'ibat':       None if (raw_ibat & 0xFFFE) == 0xFFFE
                           else round(raw_ibat * 0.025 - 1000.0, 1),
    }


def decode_0x420(data):
    if len(data) < 7:
        return None
    B0, B1, B2 = data[0], data[1], data[2]
    B3 = data[3]
    B6 = data[6]
    raw_chg = B2 | ((B1 & 0xF) << 8)
    raw_dis = (B0 << 4) | (B1 >> 4)
    iso_label = {
        0xFE: "sentinel/not-ready", 0xFF: "sentinel/not-ready",
        200:  "init/no-result", 0: "fault/powerdown",
        192:  "nominal",
    }.get(B3, f"{B3}")
    return {
        'cell_overvolt':  (B6 >> 7) & 1,
        'cell_undervolt': (B6 >> 6) & 1,
        'iso_r':          B3,
        'iso_label':      iso_label,
        'chg_max':        None if raw_chg >= 0xFFE else round(raw_chg * 0.25, 1),
        'dis_max':        None if raw_dis >= 0xFFE else round(raw_dis * 0.25, 1),
    }


def decode_0x430(data):
    if len(data) < 8:
        return None
    B0, B1, B2, B3, B4, B5, B7 = data[0], data[1], data[2], data[3], data[4], data[5], data[7]
    raw_vmax = B1 | ((B0 & 0x1F) << 8)
    raw_vmin = B3 | ((B2 & 0x1F) << 8)
    validity = (B7 >> 5) & 3   # 0x00=normal, 0x03=offline
    return {
        'chga_ena':  (B0 >> 7) & 1,
        'veh_mon':   (B2 >> 5) & 1,
        'chga_mon':  (B2 >> 6) & 1,
        'mod_ena':   (B2 >> 7) & 1,
        'validity':  validity,
        'cell_tmax': None if B4 >= 0xFE    else round(B4 * 0.5 - 40.0, 1),
        'cell_tmin': None if B5 >= 0xFE    else round(B5 * 0.5 - 40.0, 1),
        'cell_vmax': None if raw_vmax >= 0x1FFE else round(raw_vmax * 0.001, 3),
        'cell_vmin': None if raw_vmin >= 0x1FFE else round(raw_vmin * 0.001, 3),
        'lvbat':     None if B7 >= 0xFE    else round(B7 * 0.1, 1),
    }


def decode_0x440(data):
    if len(data) < 7:
        return None
    B0, B1 = data[0], data[1]
    B4, B5, B6 = data[4], data[5], data[6]
    raw_pos = (B4 << 4) | (B5 >> 4)
    raw_neg = B6 | ((B5 & 0xF) << 8)
    stat_idx = (B0 >> 2) & 0xF
    return {
        'mainc_stat':  MAINC_STAT_16[stat_idx],
        'mainc_idx':   stat_idx,
        'fault_mon':   (B0 >> 6) & 1,
        'balancing':   (B0 >> 7) & 1,
        'fgd':         None if B1 >= 0xFE else round(B1 * 0.5, 1),
        'vbus_pos':    None if raw_pos >= 0xFFE else round(raw_pos * 0.25, 1),
        'vbus_neg':    None if raw_neg >= 0xFFE else round(raw_neg * 0.25 - 500.0, 1),
    }


def decode_0x411(data):
    if len(data) < 2:
        return None
    raw_soc = data[0] * 64 + (data[1] >> 2)
    return {
        'soc_hires': None if raw_soc >= 0x3FFE else round(raw_soc / 100.0, 2),
    }


def decode_0x592(data):
    if len(data) < 1:
        return None
    b = data[0]
    return {
        'evse_switch':  (b >> 1) & 1,
        'export_power': (b >> 2) & 1,
        'ignition':     (b >> 4) & 1,
    }


def decode_0x065B(data):
    if len(data) < 8:
        return None
    code = (data[6] << 8) | data[7]
    return {
        'dtc_code': code,
        'dtc_name': DTC_TABLE.get(code, f"0x{code:04X}"),
    }


DECODERS = {
    0x053:  decode_0x053,
    0x054:  decode_0x054_or_0x044,
    0x044:  decode_0x054_or_0x044,
    0x400:  decode_0x400,
    0x410:  decode_0x410,
    0x420:  decode_0x420,
    0x430:  decode_0x430,
    0x440:  decode_0x440,
    0x411:  decode_0x411,
    0x592:  decode_0x592,
    0x065B: decode_0x065B,
}

# Fields tracked in the event timeline (discrete/enum signals whose changes matter).
# Analog snapshot-only fields (voltages, currents, temps) are excluded here.
TIMELINE_FIELDS = {
    0x053:  ['op_mode', 'op_state'],
    0x054:  ['emerstop'],
    0x044:  ['emerstop'],
    0x400:  ['hsc_enable', 'hsc_epo', 'hsc_mainc_close', 'hsc_leakage_ena'],
    0x410:  ['hvil_mon', 'epo', 'on_plug', 'ready', 'cpwr_cmd', 'chg_done',
             'cool_req', 'alarm', 'chgc_stat', 'bms_b1', 'bms_b2', 'gfd'],
    0x420:  ['cell_overvolt', 'cell_undervolt', 'iso_r'],
    0x430:  ['chga_ena', 'veh_mon', 'chga_mon', 'mod_ena', 'validity'],
    0x440:  ['mainc_stat', 'balancing'],
    # fault_mon intentionally excluded: pulses HIGH 100ms/s as a BMS health signal;
    # not a fault indicator, just noise in the timeline.
    0x592:  ['evse_switch', 'export_power', 'ignition'],
    0x065B: ['dtc_name'],
}

MSG_LABELS = {
    0x053:  'HCU_OP     ',
    0x054:  'GENE_MCU   ',
    0x044:  'TRAC_MCU   ',
    0x400:  'HSC_BCM    ',
    0x410:  'BMS_STATUS ',
    0x420:  'BMS_LIMITS ',
    0x430:  'BMS_DATA1  ',
    0x440:  'BMS_DATA2  ',
    0x592:  'HCU_SENSOR ',
    0x065B: 'HCU_DTC    ',
}


# ---------------------------------------------------------------------------
# Fault tagging
# ---------------------------------------------------------------------------

def fault_tag(aid, field, old_val, new_val):
    """Return fault string if this transition is a known fault indicator, else ''."""
    if aid == 0x400:
        if field == 'hsc_epo' and new_val == 1:
            return '  *** EPO ASSERTED ***'
    if aid == 0x410:
        if field == 'hvil_mon' and new_val == 0 and old_val == 1:
            return '  *** HVIL INTERLOCK OPENED ***'
        if field == 'hvil_mon' and new_val == 1 and old_val == 0:
            return ''
        if field == 'alarm' and new_val not in ('NONE', 'TYPE2'):
            # TYPE2 is observed in healthy logs (normal charging/operation) -- not a fault indicator
            return f'  *** BMS ALARM {new_val} ***'
        if field == 'epo' and new_val == 1:
            return '  *** BMS EPO FLAG SET ***'
        if field == 'bms_b1' and new_val == 'FAULT_LATCHED':
            return '  *** BMS FAULT LATCHED ***'
        if field == 'bms_b2' and new_val == 'settled_fault':
            return '  *** BMS IN FAULT STATE ***'
        if field == 'bms_b2' and new_val == 'isolation_shutdown':
            return '  *** ISOLATION FAULT SHUTDOWN ***'
        if field == 'gfd' and isinstance(new_val, float) and new_val < 800:
            return f'  *** ISOLATION LOW gfd={new_val} ***'
    if aid == 0x420:
        if field == 'cell_overvolt' and new_val == 1:
            return '  *** CELL OVERVOLTAGE ***'
        if field == 'cell_undervolt' and new_val == 1:
            return '  *** CELL UNDERVOLTAGE ***'
        # iso_r=0 is NOT a reliable fault indicator on its own -- it also drops to 0
        # on any normal BMS shutdown. Real isolation faults are caught by
        # gfd < 800 (which fires ~150ms before EPO) and/or bms_b2 -> isolation_shutdown.
    if aid in (0x054, 0x044):
        if field == 'emerstop' and new_val == 1:
            lbl = 'GENERATOR' if aid == 0x054 else 'TRACTION'
            return f'  *** {lbl} MCU EMERGENCY STOP ***'
    if aid == 0x053:
        if field == 'op_state' and new_val == 'FAILURE':
            return '  *** HCU FAILURE STATE ***'
        if field == 'op_state' and new_val == 'SHTDWN':
            return '  *** HCU SHUTDOWN ***'
    if aid == 0x440:
        if field == 'mainc_idx' and new_val in MAINC_STAT_FAULT_IDX:
            return f'  *** CONTACTOR FAULT STATE ({MAINC_STAT_16[new_val]}) ***'
    return ''


# ---------------------------------------------------------------------------
# Event timeline builder
# ---------------------------------------------------------------------------

def build_events(accumulated):
    """Merge all tracked frames into a single time-sorted event list.

    Returns list of (t, aid, field, old_val, new_val, tag) for every
    discrete field change across all messages.
    """
    events = []
    prev_decoded = {}

    all_entries = []
    for aid, frames in accumulated.items():
        for t, data in frames:
            all_entries.append((t, aid, data))
    all_entries.sort(key=lambda x: x[0])

    for t, aid, data in all_entries:
        decoder = DECODERS.get(aid)
        if decoder is None:
            continue
        dec = decoder(data)
        if dec is None:
            continue

        fields = TIMELINE_FIELDS.get(aid, [])
        prev = prev_decoded.get(aid)

        for field in fields:
            new_val = dec.get(field)
            if new_val is None:
                continue
            if prev is None:
                continue   # first frame: captured in initial state, not timeline
            old_val = prev.get(field)
            if old_val is None or new_val == old_val:
                continue
            # Suppress TYPE2 alarm transitions entirely -- TYPE2 is seen in healthy logs
            if field == 'alarm' and new_val == 'TYPE2':
                continue
            # Only report iso_r when it drops below 180 (normal range is 180-200+)
            if field == 'iso_r' and isinstance(new_val, (int, float)) and new_val >= 180:
                continue
            # Only report gfd when it drops below 900 (normal = 1000.0 exactly)
            if field == 'gfd' and isinstance(new_val, (int, float)) and new_val >= 900:
                continue
            tag = fault_tag(aid, field, old_val, new_val)
            # For mainc_stat, also emit using the idx field internally for fault tagging
            if field == 'mainc_stat':
                idx_tag = fault_tag(aid, 'mainc_idx', prev.get('mainc_idx'), dec.get('mainc_idx'))
                tag = tag or idx_tag
            events.append((t, aid, field, old_val, new_val, tag))

        prev_decoded[aid] = dec

    return events, prev_decoded


# ---------------------------------------------------------------------------
# Initial state from first valid frame of each message
# ---------------------------------------------------------------------------

def first_decoded(accumulated):
    """Return best initial snapshot for each message ID.

    For each field, uses the first frame that produces a non-None value for that
    field. This avoids showing n/a for analogs that start as sentinels (e.g. BMS
    in fault state at log start broadcasting 0xFE fill bytes) while still picking
    up real values a few frames in.
    """
    result = {}
    for aid, frames in accumulated.items():
        decoder = DECODERS.get(aid)
        if decoder is None or not frames:
            continue
        merged = {}
        for _t, data in frames:
            dec = decoder(data)
            if dec is None:
                continue
            if not merged:
                merged = dict(dec)   # seed with first valid decode (preserves discrete fields)
            else:
                for k, v in dec.items():
                    if merged.get(k) is None and v is not None:
                        merged[k] = v
            if all(v is not None for v in merged.values()):
                break
        if merged:
            result[aid] = merged
    return result


def last_decoded(accumulated):
    result = {}
    for aid, frames in accumulated.items():
        decoder = DECODERS.get(aid)
        if decoder is None or not frames:
            continue
        for _t, data in reversed(frames):
            dec = decoder(data)
            if dec is not None:
                result[aid] = dec
                break
    return result


# ---------------------------------------------------------------------------
# State snapshot formatter
# ---------------------------------------------------------------------------

def _fv(val, unit=''):
    """Format a value that may be None."""
    if val is None:
        return 'n/a'
    return f"{val}{unit}"


def format_state(snap):
    lines = []

    def row(label, *parts):
        lines.append(f"  {label:<14s}  {'  '.join(str(p) for p in parts)}")

    d = snap.get(0x053)
    if d:
        row("HCU_OP", f"mode={d['op_mode']}", f"state={d['op_state']}")

    d = snap.get(0x592)
    if d:
        row("HCU_SENSOR", f"ignition={d['ignition']}",
            f"evse_sw={d['evse_switch']}", f"export={d['export_power']}")

    d = snap.get(0x400)
    if d:
        row("HSC_BCM",
            f"enable={d['hsc_enable']}", f"epo={d['hsc_epo']}",
            f"mainc_close={d['hsc_mainc_close']}", f"leakage_ena={d['hsc_leakage_ena']}")

    d = snap.get(0x410)
    if d:
        hvil_str = f"{d['hvil_mon']}({'CLOSED' if d['hvil_mon'] else 'OPEN'})"
        row("BMS_STATUS",
            f"hvil={hvil_str}", f"alarm={d['alarm']}",
            f"epo={d['epo']}", f"ready={d['ready']}")
        row("",
            f"bms_b1={d['bms_b1']}", f"bms_b2={d['bms_b2']}")
        row("",
            f"vbat={_fv(d['vbat'],'V')}", f"soc={_fv(d['soc'],'%')}",
            f"ibat={_fv(d['ibat'],'A')}", f"gfd={_fv(d['gfd'])}")
        row("",
            f"chgc={d['chgc_stat']}", f"cpwr={d['cpwr_cmd']}",
            f"on_plug={d['on_plug']}", f"cool_req={d['cool_req']}",
            f"chg_done={d['chg_done']}")

    d = snap.get(0x420)
    if d:
        row("BMS_LIMITS",
            f"OV={d['cell_overvolt']}", f"UV={d['cell_undervolt']}",
            f"iso_r={d['iso_r']}({d['iso_label']})",
            f"chg_max={_fv(d['chg_max'],'A')}", f"dis_max={_fv(d['dis_max'],'A')}")

    d410, d430 = snap.get(0x410), snap.get(0x430)
    if d430:
        vmax = d430.get('cell_vmax')
        vmin = d430.get('cell_vmin')
        spread = (round((vmax - vmin) * 1000) if vmax and vmin else None)
        row("BMS_DATA1",
            f"vmax={_fv(d430['cell_vmax'],'V')}", f"vmin={_fv(d430['cell_vmin'],'V')}",
            f"spread={_fv(spread,'mV')}")
        row("",
            f"tmax={_fv(d430['cell_tmax'],'C')}", f"tmin={_fv(d430['cell_tmin'],'C')}",
            f"lvbat={_fv(d430['lvbat'],'V')}",
            f"mod_ena={d430['mod_ena']}", f"veh_mon={d430['veh_mon']}")

    d = snap.get(0x440)
    if d:
        row("BMS_DATA2",
            f"mainc_stat={d['mainc_stat']}",
            f"vbus_pos={_fv(d['vbus_pos'],'V')}", f"vbus_neg={_fv(d['vbus_neg'],'V')}")
        row("",
            f"fault_mon={d['fault_mon']}", f"balancing={d['balancing']}",
            f"fgd={_fv(d['fgd'],'%')}")

    d_hires = snap.get(0x411)
    if d_hires and d_hires.get('soc_hires') is not None:
        row("BMS_SOC_HIRES", f"soc={d_hires['soc_hires']}%")

    d = snap.get(0x054)
    if d:
        row("GENE_MCU", f"emerstop={d['emerstop']}", f"rpm={d['rpm']}")

    d = snap.get(0x044)
    if d:
        row("TRAC_MCU", f"emerstop={d['emerstop']}", f"rpm={d['rpm']}")

    return lines


# ---------------------------------------------------------------------------
# Fault summary
# ---------------------------------------------------------------------------

def build_fault_summary(first_snap, events):
    faults = []

    # Check initial state for persistent faults
    d = first_snap.get(0x410)
    if d:
        # Note: HVIL open at log start is NOT reported here -- it is normal for logs that begin
        # during truck power-up before the interlock loop closes. The hvil_ever_closed NOTE at
        # the bottom of the report catches the case where HVIL is never closed in the entire log.
        if d.get('alarm') not in ('NONE', 'TYPE2'):
            faults.append(f"BMS alarm already set at t=0: {d['alarm']}")
        if d.get('bms_b1') == 'FAULT_LATCHED':
            faults.append("BMS already FAULT_LATCHED at t=0")
        # Note: bms_b2=settled_fault (0xFE) at t=0 is NOT reported here -- it is the normal
        # BMS startup state before the BMS completes initialization, seen in healthy logs too.
        # A transition TO settled_fault mid-log is still caught by the timeline fault tag.
        if d.get('bms_b2') == 'isolation_shutdown':
            faults.append("BMS in isolation_shutdown state at t=0 (bms_b2=0x00)")
        gfd0 = d.get('gfd')
        if gfd0 is not None and gfd0 < 800:
            faults.append(f"ISOLATION LOW at t=0 (gfd={gfd0}) -- isolation fault active or BMS cold-start")

    d = first_snap.get(0x420)
    if d:
        if d.get('cell_overvolt') == 1:
            faults.append("Cell OVERVOLTAGE flag set at t=0")
        if d.get('cell_undervolt') == 1:
            faults.append("Cell UNDERVOLTAGE flag set at t=0")

    d = first_snap.get(0x400)
    if d:
        if d.get('hsc_epo') == 1:
            faults.append("HSC EPO already asserted at t=0")

    d = first_snap.get(0x054)
    if d and d.get('emerstop') == 1:
        faults.append("GENE MCU emergency stop already set at t=0")

    d = first_snap.get(0x044)
    if d and d.get('emerstop') == 1:
        faults.append("TRAC MCU emergency stop already set at t=0")

    # Check timeline events for fault transitions
    for t, aid, field, old_val, new_val, tag in events:
        if tag:
            faults.append(f"t={t:.3f}s  {tag.strip()}")

    # Check if contactors ever progressed
    d440 = first_snap.get(0x440)
    mainc_seen = set()
    for _t, data in []:  # populated below via caller if needed
        pass

    return faults


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def print_report(paths, pt_bus, obd_bus, accumulated, duration, frame_count, bel_seen, out):
    def w(line=''):
        out.write(line + '\n')

    w(SEP)
    w("VTRUX DIAGNOSTIC REPORT")
    w(SEP)
    files_str = ', '.join(str(p.name) for p in paths[:3])
    if len(paths) > 3:
        files_str += f" (+{len(paths)-3} more)"
    w(f"  Files   : {files_str}")
    w(f"  Duration: {duration:.1f}s   Frames: {frame_count:,}")
    w(f"  PT bus  : {'Bus' + str(pt_bus) if pt_bus is not None else 'NOT IDENTIFIED'}")
    w(f"  OBD bus : {'Bus' + str(obd_bus) if obd_bus is not None else 'not found in log'}")
    if bel_seen:
        w()
        w("  *** WARNING: Bel Inverter (charger) messages detected in this log. ***")
        w("  This tool does not decode charger state or fault registers.")
        w("  A charge failure may appear here as an HVIL or BMS fault when the")
        w("  charger initiated the failure. For charging logs, use:")
        w("    projects/vtrux/tools/vtrux_charge_failure_analysis.py")
    w()

    first_snap = first_decoded(accumulated)
    last_snap  = last_decoded(accumulated)

    # Check HVIL at start -- used for summary
    d410_first = first_snap.get(0x410, {})
    hvil_ever_closed = d410_first.get('hvil_mon') == 1
    # HVIL ever closed check
    for _t, data in accumulated.get(0x410, []):
        dec = decode_0x410(data)
        if dec and dec.get('hvil_mon') == 1:
            hvil_ever_closed = True
            break

    w(SEP)
    w("INITIAL STATE")
    w(SEP)
    t0_str = f"t={accumulated[0x410][0][0]:.3f}s" if accumulated.get(0x410) else "t=0.000s"
    w(f"  (first frame of each signal, log starts at {t0_str})")
    w()
    for line in format_state(first_snap):
        w(line)
    w()

    # -----------------------------------------------------------------------
    # Build event timeline
    # -----------------------------------------------------------------------
    events, _ = build_events(accumulated)

    w(SEP)
    w(f"SYSTEM EVENTS TIMELINE  ({len(events)} state changes)")
    w(SEP)
    if not events:
        w("  (no state changes detected)")
    else:
        # Collapse oscillating runs: if the same (aid, field) alternates A<->B
        # for 3+ consecutive pairs, replace with a single summary line.
        OSCILLATION_MIN_CYCLES = 3   # pairs before collapsing

        def _emit_collapsed(run):
            t_first, aid, field, a_val, b_val, first_tag = run[0]
            t_last  = run[-1][0]
            n_cycles = len(run) // 2
            label = MSG_LABELS.get(aid, f"0x{aid:03X}      ")
            period = (t_last - t_first) / max(len(run) - 1, 1)
            w(f"  t={t_first:8.3f}s  {label}  {field:<20s}  "
              f"{str(a_val)}<->{str(b_val)}  "
              f"[oscillating {n_cycles} cycles, ~{period:.2f}s period, "
              f"last t={t_last:.3f}s]{first_tag}")

        i = 0
        while i < len(events):
            t, aid, field, old_val, new_val, tag = events[i]
            # Look ahead for oscillation: same (aid, field) alternating old/new
            j = i + 1
            while j < len(events):
                tj, aidj, fj, oj, nj, _ = events[j]
                if aidj != aid or fj != field:
                    break
                # Must alternate: new_val of prev == old_val of next
                expected_old = events[j-1][4]   # new_val of previous
                if oj != expected_old:
                    break
                j += 1
            run_len = j - i
            if run_len >= OSCILLATION_MIN_CYCLES * 2:
                _emit_collapsed(events[i:j])
                i = j
            else:
                label = MSG_LABELS.get(aid, f"0x{aid:03X}      ")
                w(f"  t={t:8.3f}s  {label}  {field:<20s}  {str(old_val):<20s}-> {new_val}{tag}")
                i += 1
    w()

    w(SEP)
    w("FINAL STATE")
    w(SEP)
    w()
    for line in format_state(last_snap):
        w(line)
    w()

    # -----------------------------------------------------------------------
    # Fault summary
    # -----------------------------------------------------------------------
    w(SEP)
    w("FAULT SUMMARY")
    w(SEP)

    faults = build_fault_summary(first_snap, events)

    if not faults:
        w("  No fault indicators detected.")
    else:
        # Deduplicate repeated identical fault strings (e.g. recurring HCU SHUTDOWN cycles)
        deduped = []
        i = 0
        while i < len(faults):
            entry = faults[i]
            # Extract tag (part after first timestamp) for grouping
            tag = entry.split('  ', 1)[-1] if entry.startswith('t=') else entry
            j = i + 1
            while j < len(faults):
                other_tag = faults[j].split('  ', 1)[-1] if faults[j].startswith('t=') else faults[j]
                if other_tag == tag:
                    j += 1
                else:
                    break
            if j - i > 1:
                last_t = faults[j-1].split('s')[0].lstrip('t=') if faults[j-1].startswith('t=') else '?'
                deduped.append(f"  {entry}  (repeated {j-i}x through t={last_t}s)")
            else:
                deduped.append(f"  {entry}")
            i = j
        for line in deduped:
            w(line)
    w()

    if not hvil_ever_closed:
        w()
        w("  NOTE: HVIL interlock bit (0x410 B0 bit3) was NEVER 1 in this log.")
        w("        Contactors cannot close with HVIL open.")
        w("        Check: MSD seating, HV connector locks, interlock wiring.")
    w()
    w(SEP)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Vtrux general diagnostic tool")
    parser.add_argument('files', nargs='+', help="Log file(s)")
    parser.add_argument('--output', '-o', help="Write report to file (default: stdout)")
    args = parser.parse_args()

    expanded = []
    for f in args.files:
        matches = glob.glob(f)
        if matches:
            expanded.extend(matches)
        else:
            expanded.append(f)  # let the existence check below produce the error
    paths = sorted(Path(f) for f in expanded)
    for p in paths:
        if not p.exists():
            sys.exit(f"File not found: {p}")

    pt_bus, obd_bus, accumulated, duration, frame_count, bel_seen = collect_frames(paths)

    if pt_bus is None:
        print("WARNING: PT bus not identified (0x051 not seen). Output may be empty.",
              file=sys.stderr)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            print_report(paths, pt_bus, obd_bus, accumulated, duration, frame_count, bel_seen, f)
        print(f"Report written to {args.output}")
    else:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        print_report(paths, pt_bus, obd_bus, accumulated, duration, frame_count, bel_seen, sys.stdout)


if __name__ == '__main__':
    main()
