#!/usr/bin/env python3
"""Vtrux charge failure analysis tool.

Analyzes one or more CAN log files from the Vtrux powertrain bus and produces
a structured plain-text failure report covering the Bel charger state machine,
J1772 health, VCU charge command, BMS cluster signals, and failure classification.

Usage:
  py -3.12 vtrux_charge_failure_analysis.py FILE [FILE ...]
  py -3.12 vtrux_charge_failure_analysis.py --dir DIR [--session SFX]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from canre.utils.merge import detect_capture_groups, merge_files

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PT_BUS_ANCHOR_ID         = 0x051       # Always on PT bus; used to identify PT channel
PT_BUS_ANCHOR_FALLBACK   = 0x18FFD4C0  # Charger-only logs lack 0x051; use charger ID instead

# Standard 11-bit target IDs (PT bus only)
TARGET_STD = {
    0x053,  # HCU OperatingMode / OperatingState
    0x054,  # GENE_RotSpd (generator RPM) + emergency stop flag
    0x0400, # HSC_BCM_Ctrl: hsc_bcm_enable/epo/mainc_close/leakage_ena (B0 bits 0-3)
    0x410,  # BMS interlock/mode/fault register
    0x411,  # BMS SoC hi-res + contactor bytes
    0x412,  # BMS charge current limit (Tier 2)
    0x420,  # BCM_Limits: chg_max, dis_max, cell OV/UV
    0x430,  # BCM_Data1: cell temps, cell voltages, 12V battery
    0x440,  # BCM_Data2: contactor sequence (mainc_stat), vbus, fault_mon
    0x592,  # HCU_Sensor: EVSE switch, ignition, export, brake pedal
    0x598,  # HCU power averages: DBL_ESSPwrAvg, DBL_TracPwrAvg
    0x63A,  # Cell extremes / delta (Tier 2)
    0x63D,  # Fault flags OV/UV/OT (Tier 2)
    0x065B, # HCU DTC code dispatcher (29-entry lookup table)
}

# Extended 29-bit target IDs (PT bus only)
TARGET_EXT = {
    0x18FFD4C0,  # Bel charger status (mux=0 + mux=3)
    0x18FFD7C0,  # Bel charger V/I telemetry
    0x18FFD8C0,  # Bel J1772 pilot info
    0x18FFD6B3,  # DCDC HV input voltage
    0x18FFD9C0,  # Vehicle charge command (VCU->charger)
}

ALL_TARGETS = TARGET_STD | TARGET_EXT

SEP = "=" * 68

# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def resolve_input_files(args):
    """Return a list of Path objects to pass to merge_files()."""
    if args.dir:
        dir_path = Path(args.dir)
        if not dir_path.is_dir():
            sys.exit(f"Not a directory: {dir_path}")
        groups = detect_capture_groups(dir_path)
        if not groups:
            sys.exit(f"No capture groups found in {dir_path}")
        if args.session:
            sfx = args.session
            groups = {k: v for k, v in groups.items() if sfx in k}
            if not groups:
                sys.exit(f"No capture groups matching --session '{sfx}' in {dir_path}")
        if len(groups) > 1:
            names = ", ".join(sorted(groups.keys()))
            sys.exit(
                f"--dir matched multiple capture groups ({names}). "
                f"Use --session to select one."
            )
        return next(iter(groups.values()))
    else:
        paths = [Path(f) for f in args.files]
        for p in paths:
            if not p.exists():
                sys.exit(f"File not found: {p}")
        return paths


# ---------------------------------------------------------------------------
# Single streaming pass: PT bus identification + frame accumulation
# ---------------------------------------------------------------------------

def collect_frames(paths):
    """Stream all files once.

    Identifies PT bus from the first 0x051 frame, then accumulates
    (timestamp, data) tuples for each target ID on that bus only.

    Returns:
        pt_bus (int|None): PT bus channel number; None if 0x051 never seen.
        accumulated (dict[int, list[tuple[float, bytes]]]): per-ID frame lists.
        duration (float): timestamp of last frame seen.
        frame_count (int): total frames across all buses.
    """
    pt_bus = None
    accumulated = {aid: [] for aid in ALL_TARGETS}
    duration = 0.0
    frame_count = 0

    for frame in merge_files(paths):
        frame_count += 1
        duration = frame.timestamp

        if pt_bus is None:
            if frame.arbitration_id == PT_BUS_ANCHOR_ID:
                pt_bus = frame.bus
            elif frame.arbitration_id == PT_BUS_ANCHOR_FALLBACK:
                pt_bus = frame.bus  # charger-only log: no 0x051, use charger ID

        if (pt_bus is not None
                and frame.bus == pt_bus
                and frame.arbitration_id in ALL_TARGETS):
            accumulated[frame.arbitration_id].append((frame.timestamp, frame.data))

    return pt_bus, accumulated, duration, frame_count


# ---------------------------------------------------------------------------
# Charger decode tables (0x18FFD4C0, per BelInverter.dbc)
# Each entry: (name, byte_index, bit_index_within_byte)
# ---------------------------------------------------------------------------

MUX0_STATUS_BITS = [
    ('keySwitch',               1, 0),
    ('pilotControlSignal',      1, 1),
    ('proxEnabled',             1, 2),
    ('evseConnected',           1, 3),
    ('vehicleConnected',        1, 4),
    ('auxPowerSupply',          1, 5),
    ('chargerEFE',              1, 6),
    ('s2Switch',                1, 7),
    ('chargingInProgress',      2, 0),
    ('powerChargingInProgress', 2, 1),
    ('inverterAlive',           3, 1),
    ('inverterReady',           3, 2),
    ('buckBoostAlive',          3, 3),
    ('buckBoostReady',          3, 4),
    ('evseDisconnected',        4, 1),
    ('standby',                 4, 6),
    ('unitReady',               4, 7),
]

# Bits in the mux=3 fault register where the ACTIVE (fault) state is 0, not 1.
# acOk = 1 means "AC input is OK" (healthy); acOk = 0 means AC fault/dropout.
INVERTED_FAULT_BITS = {'acOk'}

MUX3_FAULT_BITS = [
    ('acOk',                    1, 0),
    ('acOverVoltage',           1, 1),
    ('acUnderVoltage',          1, 2),
    ('sysLVUV',                 1, 3),
    ('hvBattOV',                1, 4),
    ('hvBattUV',                1, 5),
    ('overTemperature',         1, 6),
    ('exportOverLoad',          1, 7),
    ('inverterFault',           2, 0),
    ('buckBoostFault',          2, 1),
    ('wakeOutputError',         2, 3),
    ('underFrequency',          2, 5),
    ('overFrequency',           2, 6),
]

# Subset of MUX0_STATUS_BITS used for J1772 flag change tracking
J1772_FLAG_DEFS = [e for e in MUX0_STATUS_BITS
                   if e[0] in {'pilotControlSignal', 'proxEnabled',
                               'evseConnected', 'vehicleConnected'}]

# ---------------------------------------------------------------------------
# BMS / HCU signal tables (EPRI CANbusLogger2 Ghidra analysis, 2026-03-26)
# Source: original-datalogging-investigation.md Part 5
# ---------------------------------------------------------------------------

ALARM_STRS = ["NONE", "TYPE1", "TYPE2", "TYPE3"]
CHGC_STRS  = ["OPEN", "CLOSED", "HIGH", "LOW"]

# 0x440 bcm_mainc_stat: 4-bit index (B0 bits[5:2]), 16 entries
MAINC_STAT_16 = [
    "ALL_OPEN",               # 0
    "FAILED_MAINP_OR_R_WELD", # 1 -- weld fault
    "CLOSE_MAINR",            # 2 -- precharge resistor closing
    "FAILED_MAINR_OPEN",      # 3 -- fault
    "FAILED_MAINN_WELD",      # 4 -- fault
    "CLOSE_MAINN",            # 5 -- negative main closing
    "FAILED_MAINN_OPEN",      # 6 -- fault
    "WAIT_PRECHARGE",         # 7 -- precharging
    "CLOSE_MAINP",            # 8 -- positive main closing
    "OPEN_MAINR",             # 9 -- precharge resistor opening (normal)
    "FAILED_MAINP_OPEN",      # 10 -- fault
    "MAIN_PN_CLOSED_DRIVE",   # 11 -- drive mode (P+N closed)
    "MAIN_P_CLOSED_CHARGE",   # 12 -- charge mode (P closed)
    "SHUTDOWN_REQUEST",       # 13
    "ALL_OPEN_SHUTDOWN",      # 14
    "(idx15)",                # 15
]

# 0x053 OperatingMode (B0[6:4]) and OperatingState (B0[3:0])
OP_MODE_STRS  = ["NTRL", "Invalid(1)", "Invalid(2)", "Invalid(3)"]
OP_STATE_STRS = [
    "INIT", "STBY", "ACTIVATION", "DEACTIVATION", "OPERATIONAL",
    "FAILURE", "SHTDWN", "WAIT4COOLING", "PWR_OFF_RDY",
]

# 0x065B HCU DTC dispatcher: B6:B7 big-endian uint16 -> name string
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


def _bit(data, byte_idx, bit_idx):
    return (data[byte_idx] >> bit_idx) & 1 if byte_idx < len(data) else None


def _snapshot(data, defs):
    return {name: _bit(data, b, bi) for name, b, bi in defs}


def _bit_changes(frames, defs, min_len=8):
    """Yield (t, name, old_val, new_val) for every bit change in sequence."""
    prev = None
    for t, data in frames:
        if len(data) < min_len:
            continue
        cur = _snapshot(data, defs)
        if prev is not None:
            for name, _, _ in defs:
                if cur[name] != prev[name]:
                    yield t, name, prev[name], cur[name]
        prev = cur


def _fault_tag(name, new_val):
    """Return fault label for a bit change, respecting inverted-polarity bits."""
    fault = (new_val == 0) if name in INVERTED_FAULT_BITS else (new_val == 1)
    return "  FAULT SET" if fault else "  fault cleared"


def _find_charger_events(mux0):
    """Parse mux=0 frames; return state timeline, intermittency, failures, final.

    failures entries are (t, src, end_state).  Terminal failures are detected by
    shutdownSource==14 on any transition out of state 12, regardless of destination
    state (handles both 12->15 src=14 and 12->33 src=14 firmware variants).
    """
    state_timeline = []   # (t, old_state, new_state, src)
    to_15 = []            # (t, src) each 12->15 transition
    to_12 = []            # t of each 15->12 transition
    src14_exits = []      # (t, src, new_state) any 12->X with src=14

    prev_state = prev_src = None
    for t, data in mux0:
        if len(data) < 8:
            continue
        state, src = data[5], data[6]
        if prev_state is None:
            prev_state, prev_src = state, src
            continue
        if state != prev_state:
            state_timeline.append((t, prev_state, state, src))
            if prev_state == 12 and state == 15:
                to_15.append((t, src))
            elif prev_state == 15 and state == 12:
                to_12.append(t)
            if prev_state == 12 and src == 14:
                src14_exits.append((t, src, state))
            prev_state, prev_src = state, src

    intermittency, failures = [], []
    for t_f, src in to_15:
        if src == 14:
            continue  # captured via src14_exits; skip to avoid double-counting
        rec = next((r for r in to_12 if t_f < r <= t_f + 3.0), None)
        if rec is not None:
            intermittency.append((t_f, rec - t_f, src))
        else:
            failures.append((t_f, src, 15))  # unexpected unrecovered 12->15

    for t_f, src, end_s in src14_exits:
        failures.append((t_f, src, end_s))

    failures.sort()
    final = failures[-1] if failures else None
    return state_timeline, intermittency, failures, final


def _health_baseline(mux0, state_timeline):
    """Return bit snapshot from first stable state=12 frame (>=5s from any transition)."""
    trans_times = {t for t, *_ in state_timeline}
    for t, data in mux0:
        if len(data) < 8 or data[5] != 12:
            continue
        if not any(abs(t - tt) < 5.0 for tt in trans_times):
            return _snapshot(data, MUX0_STATUS_BITS)
    # Fallback: first state=12 frame regardless of proximity to transitions
    for t, data in mux0:
        if len(data) >= 8 and data[5] == 12:
            return _snapshot(data, MUX0_STATUS_BITS)
    return None


def _find_charging_pauses(mux0, startup_grace=60.0, min_duration=5.0):
    """Find episodes within state=12 where powerChargingInProgress=0.

    Excludes the first startup_grace seconds after the initial state=12 entry
    (normal ramp period).  Returns list of (t_start, duration) for episodes
    lasting >= min_duration seconds.
    """
    first_12 = next((t for t, d in mux0 if len(d) >= 8 and d[5] == 12), None)
    if first_12 is None:
        return []

    pauses, in_pause, t_p0 = [], False, None
    prev_state = None

    for t, d in mux0:
        if len(d) < 8:
            continue
        state = d[5]
        pcip = (d[2] >> 1) & 1   # B2 bit1 = powerChargingInProgress

        if state != 12:
            if in_pause:
                in_pause, t_p0 = False, None
            prev_state = state
            continue

        if t - first_12 < startup_grace:
            prev_state = state
            continue

        if pcip == 0 and not in_pause:
            in_pause, t_p0 = True, t
        elif pcip == 1 and in_pause:
            dur = t - t_p0
            if dur >= min_duration:
                pauses.append((t_p0, dur))
            in_pause = False

        prev_state = state

    if in_pause and t_p0 is not None and mux0:
        dur = mux0[-1][0] - t_p0
        if dur >= min_duration:
            pauses.append((t_p0, dur))

    return pauses


def _detail_window(mux0, mux3, t_f, window):
    """Return list of formatted lines for +/-window around t_f."""
    lo, hi = t_f - window, t_f + window
    w0 = [(t, d) for t, d in mux0 if lo <= t <= hi and len(d) >= 8]
    w3 = [(t, d) for t, d in mux3 if lo <= t <= hi and len(d) >= 3]

    lines = []

    lines.append("    mux=0 changes:")
    found = False
    prev_extra = prev_bits = None
    for t, data in w0:
        dt = t - t_f
        extra = (data[5], data[6], data[7])
        cur = _snapshot(data, MUX0_STATUS_BITS)
        if prev_extra is None:
            prev_extra, prev_bits = extra, cur
            continue
        changes = []
        for lbl, ov, nv in zip(
            ('state', 'shutdownSource', 'stateBeforeLastShutdown'),
            prev_extra, extra
        ):
            if ov != nv:
                changes.append(f"{lbl} {ov} -> {nv}")
        for name, _, _ in MUX0_STATUS_BITS:
            if cur[name] != prev_bits[name]:
                changes.append(f"{name} {prev_bits[name]} -> {cur[name]}")
        for ch in changes:
            lines.append(f"      dt={dt:+8.2f}s  {ch}")
            found = True
        prev_extra, prev_bits = extra, cur
    if not found:
        lines.append("      (none)")

    lines.append("    mux=3 fault changes:")
    found = False
    for t, name, old, new in _bit_changes(w3, MUX3_FAULT_BITS, min_len=3):
        dt = t - t_f
        tag = _fault_tag(name, new)
        lines.append(f"      dt={dt:+8.2f}s  {name} {old} -> {new}{tag}")
        found = True
    if not found:
        lines.append("      (none)")

    return lines


# ---------------------------------------------------------------------------
# BMS / HCU decode helpers
# ---------------------------------------------------------------------------

def _decode_0x410(data):
    """BCM_Status: discrete flags + ibat/soc/vbat/gfd. Returns dict or None."""
    if len(data) < 8:
        return None
    B0, B1, B2, B3, B4, B5, B6, B7 = data[:8]
    raw_ibat = B2 | ((B1 & 0xF) << 8)
    raw_vbat = B7 | ((B6 & 0xF) << 8)
    raw_gfd  = (B4 << 8) | B5
    return {
        'alarm':     ALARM_STRS[(B1 >> 6) & 3],
        'chgc_stat': CHGC_STRS[(B0 >> 6) & 3],
        'hvil_mon':  (B0 >> 3) & 1,
        'on_plug':   (B0 >> 2) & 1,
        'epo':       (B0 >> 1) & 1,
        'ready':     B0 & 1,
        'cpwr_cmd':  (B1 >> 4) & 1,
        'chg_done':  (B6 >> 4) & 1,
        'cool_req':  (B6 >> 5) & 1,
        'ibat': None if raw_ibat == 0xFFE else round(raw_ibat * 0.25, 2),
        'soc':  None if B3 >= 0xFE       else round(B3 * 0.5, 1),
        'vbat': None if raw_vbat == 0xFFE else round(raw_vbat * 0.25, 1),
        'gfd':  None if (raw_gfd & 0xFFFE) == 0xFFFE
                     else round(raw_gfd * 0.025 - 1000.0, 2),
    }


def _decode_0x420(data):
    """BCM_Limits: chg_max, dis_max, cell OV/UV flags. Returns dict or None."""
    if len(data) < 7:
        return None
    B0, B1, B2 = data[0], data[1], data[2]
    B6 = data[6]
    raw_chg = B2 | ((B1 & 0xF) << 8)
    raw_dis = (B0 << 4) | (B1 >> 4)
    return {
        'chg_max':        None if raw_chg == 0xFFE else round(raw_chg * 0.25, 2),
        'dis_max':        None if raw_dis == 0xFFE else round(raw_dis * 0.25, 2),
        'cell_overvolt':  (B6 >> 7) & 1,
        'cell_undervolt': (B6 >> 6) & 1,
    }


def _decode_0x430(data):
    """BCM_Data1: cell temps, cell voltages, 12V battery, charge adapter flags."""
    if len(data) < 8:
        return None
    B0, B1, B2, B3, B4, B5, B7 = data[0], data[1], data[2], data[3], data[4], data[5], data[7]
    raw_vmax = B1 | ((B0 & 0x1F) << 8)
    raw_vmin = B3 | ((B2 & 0x1F) << 8)
    return {
        'chga_ena':  (B0 >> 7) & 1,
        'chga_mon':  (B2 >> 6) & 1,
        'mod_ena':   (B2 >> 7) & 1,
        'veh_mon':   (B2 >> 5) & 1,
        'cell_tmax': None if B4 >= 0xFE    else round(B4 * 0.5 - 40.0, 1),
        'cell_tmin': None if B5 >= 0xFE    else round(B5 * 0.5 - 40.0, 1),
        'cell_vmax': None if raw_vmax == 0x1FFE else round(raw_vmax * 0.001, 3),
        'cell_vmin': None if raw_vmin == 0x1FFE else round(raw_vmin * 0.001, 3),
        'lvbat':     None if B7 >= 0xFE    else round(B7 * 0.1, 1),
    }


def _decode_0x440(data):
    """BCM_Data2: contactor sequence (mainc_stat 16-state), fault_mon, vbus."""
    if len(data) < 7:
        return None
    B0, B1 = data[0], data[1]
    B4, B5, B6 = data[4], data[5], data[6]
    raw_vbus_pos = (B4 << 4) | (B5 >> 4)
    raw_vbus_neg = B6 | ((B5 & 0xF) << 8)
    return {
        'mainc_stat':  MAINC_STAT_16[(B0 >> 2) & 0xF],
        'balancing':   (B0 >> 7) & 1,
        'fault_mon':   (B0 >> 6) & 1,
        'fgd':         None if B1 >= 0xFE else round(B1 * 0.5, 1),
        'vbus_pos':    None if raw_vbus_pos == 0xFFE else round(raw_vbus_pos * 0.25, 1),
        'vbus_neg':    None if raw_vbus_neg == 0xFFE
                            else round(raw_vbus_neg * 0.25 - 500.0, 1),
    }


def _decode_0x0400(data):
    """HSC_BCM_Ctrl: four control bits in B0. Returns dict or None."""
    if not data:
        return None
    B0 = data[0]
    return {
        'hsc_bcm_enable':      B0 & 1,
        'hsc_bcm_epo':         (B0 >> 1) & 1,
        'hsc_bcm_mainc_close': (B0 >> 2) & 1,
        'hsc_bcm_leakage_ena': (B0 >> 3) & 1,
    }


# ---------------------------------------------------------------------------
# Analysis stubs (Steps 4-8 -- not yet implemented)
# ---------------------------------------------------------------------------

def analyze_charger_state(frames_4C0, window):
    """Step 3: Bel charger state machine + fault register."""
    if not frames_4C0:
        return "  No 0x18FFD4C0 frames -- PT bus not captured or charger absent."

    mux0 = [(t, d) for t, d in frames_4C0 if d and d[0] == 0x00]
    mux3 = [(t, d) for t, d in frames_4C0 if d and d[0] == 0x03]

    out = []
    out.append(f"  mux=0 frames: {len(mux0):,}   mux=3 frames: {len(mux3):,}")
    out.append("")

    state_timeline, intermittency, failures, final = _find_charger_events(mux0)
    ft = final[0] if final else None

    # --- State transition timeline ---
    out.append("  State Transition Timeline:")
    if not state_timeline:
        out.append("    (no state changes observed)")
    else:
        intermit_times = {t_i for t_i, _, _ in intermittency}
        for t, old_s, new_s, src in state_timeline:
            tag = ""
            if old_s == 12 and new_s == 15:
                tag = "  [non-fatal]" if t in intermit_times else "  [FAILURE]"
            elif old_s == 12 and src == 14:
                tag = "  [FAILURE]"
            out.append(f"    t={t:9.2f}s  state {old_s:3d} -> {new_s:3d}  src={src}{tag}")
    out.append("")

    # --- Intermittency catalog ---
    out.append(f"  Intermittency ({len(intermittency)} non-fatal 12->15->12 recoveries):")
    if not intermittency:
        out.append("    (none)")
    else:
        for i, (t_i, dur, src) in enumerate(intermittency, 1):
            dt_str = f"{t_i - ft:+.1f}s" if ft is not None else "n/a"
            out.append(
                f"    #{i:2d}  t={t_i:9.2f}s  src={src}"
                f"  recovered in {dur:.2f}s  dt_to_final={dt_str}"
            )
    out.append("")

    # --- Final failure ---
    out.append("  Final Failure:")
    if not final:
        out.append("    None detected (normal completion, non-charge log, or no terminal src=14 seen).")
    else:
        t_f, src_f, end_s = final
        out.append(f"    t={t_f:.2f}s  state 12 -> {end_s}  shutdownSource={src_f}")
        if len(failures) > 1:
            out.append(f"    ({len(failures)} total unrecovered transitions; reporting last above)")
    out.append("")

    # --- Health bits baseline ---
    baseline = _health_baseline(mux0, state_timeline)
    out.append("  Health Bits Baseline (stable state=12):")
    if baseline is None:
        out.append("    (no stable state=12 window found)")
    else:
        for name, _, _ in MUX0_STATUS_BITS:
            out.append(f"    {name:<30s} = {baseline[name]}")
    out.append("")

    # --- Health bit changes ---
    out.append("  Health Bit Changes (dt relative to final failure):")
    hchanges = list(_bit_changes(mux0, MUX0_STATUS_BITS))
    if not hchanges:
        out.append("    (none)")
    elif ft is None:
        out.append("    (no final failure identified -- dt not computable)")
    else:
        for t, name, old, new in hchanges:
            out.append(f"    dt={t - ft:+8.2f}s  {name:<30s} {old} -> {new}")
    out.append("")

    # --- Fault register baseline ---
    out.append("  Fault Register Baseline (mux=3):")
    if not mux3:
        out.append("    (no mux=3 frames)")
    else:
        t0, d0 = mux3[0]
        if len(d0) >= 3:
            base3 = _snapshot(d0, MUX3_FAULT_BITS)
            for name, _, _ in MUX3_FAULT_BITS:
                out.append(f"    {name:<30s} = {base3[name]}")
    out.append("")

    # --- Fault register changes ---
    out.append("  Fault Register Changes:")
    fchanges = list(_bit_changes(mux3, MUX3_FAULT_BITS, min_len=3))
    if not fchanges:
        out.append("    (none)")
    else:
        for t, name, old, new in fchanges:
            tag = _fault_tag(name, new)
            if ft is not None:
                prefix = f"dt={t - ft:+8.2f}s"
            else:
                prefix = f"t={t:9.2f}s "
            out.append(f"    {prefix}  {name:<25s} {old} -> {new}{tag}")
    out.append("")

    # --- Charging pauses ---
    pauses = _find_charging_pauses(mux0)
    out.append(
        "  Charging Pauses (powerChargingInProgress=0 within state=12, "
        ">5s, after 60s startup grace):"
    )
    if not pauses:
        out.append("    None detected.")
    else:
        for i, (t_p, dur) in enumerate(pauses, 1):
            dt_str = (f"  dt_to_final={t_p - ft:+.1f}s" if ft is not None else "")
            out.append(f"    #{i:2d}  t={t_p:.2f}s  duration={dur:.1f}s{dt_str}")
    out.append("")

    # --- Detail window for each unrecovered failure ---
    for i, (t_f, src_f, _) in enumerate(failures, 1):
        out.append(
            f"  Detail Window: Failure #{i}"
            f" (t={t_f:.2f}s, src={src_f}, +/-{window:.0f}s):"
        )
        out.extend(_detail_window(mux0, mux3, t_f, window))
        out.append("")

    return "\n".join(out)


def analyze_j1772(frames_4C0, frames_8C0, window):
    """Step 4: J1772 connection health."""
    mux0 = [(t, d) for t, d in frames_4C0 if d and d[0] == 0x00]
    out = []

    if not frames_8C0:
        out.append("  No 0x18FFD8C0 frames -- charger pilot data absent.")
        return "\n".join(out)

    out.append(f"  0x18FFD8C0 frames: {len(frames_8C0):,}   mux=0 frames: {len(mux0):,}")
    out.append("")

    _, _, failures, final = _find_charger_events(mux0)
    ft = final[0] if final else None

    # Build state sequence for two-pointer lookup (mux0 is time-sorted from merge_files)
    state_seq = [(t, d[5]) for t, d in mux0 if len(d) >= 8]

    # Parse 8C0 frames with running state pointer (O(n+m))
    duties, freqs, online_times, freqs_charging = [], [], [], []
    state_ptr = 0
    current_state = None
    for t, data in frames_8C0:
        if len(data) < 8:
            continue
        while state_ptr < len(state_seq) and state_seq[state_ptr][0] <= t:
            current_state = state_seq[state_ptr][1]
            state_ptr += 1
        duty  = data[2]
        freq  = int.from_bytes(data[3:5], 'little')
        otime = int.from_bytes(data[5:8], 'little')
        duties.append((t, duty))
        freqs.append((t, freq))
        online_times.append((t, otime))
        if current_state == 12:
            freqs_charging.append((t, freq))

    anomalies = []

    # --- Pilot Duty ---
    # J1772 spec: valid duty for current delivery is 10-96%.
    # 10-85%: I = duty% * 0.6 A;  85-96%: I = (duty% - 64) * 2.5 A.
    # 0% = pilot not present (offline); different EVSEs use different values
    # within 10-96%, so any value in that range is normal.
    def _duty_to_amps(d):
        if d <= 85:
            return d * 0.6
        return (d - 64) * 2.5

    out.append("  Pilot Duty (0x18FFD8C0 B2, uint8, J1772 spec valid 10-96%):")
    if not duties:
        out.append("    (no data)")
    else:
        duty_vals = [d for _, d in duties]
        dmin, dmax = min(duty_vals), max(duty_vals)
        out.append(f"    min={dmin}  max={dmax}")
        unique = sorted(set(duty_vals))
        if len(unique) <= 12:
            out.append(f"    Unique values: {unique}")
        else:
            out.append(
                f"    Unique values ({len(unique)} distinct): "
                f"{unique[:6]} ... {unique[-6:]}"
            )
        active = [d for d in duty_vals if d > 0]
        if active:
            a_min, a_max = min(active), max(active)
            out.append(
                f"    Active (non-zero): {a_min}-{a_max}%  =>  "
                f"{_duty_to_amps(a_min):.1f}-{_duty_to_amps(a_max):.1f} A offered"
            )
            if a_min < 10 or a_max > 96:
                note = (f"pilotDuty outside J1772 spec (active {a_min}-{a_max}%, "
                        f"valid 10-96%)")
                out.append(f"    !! ANOMALY: {note}")
                anomalies.append(note)
            else:
                out.append("    OK (within J1772 spec 10-96%)")
    out.append("")

    # --- Pilot Frequency ---
    out.append("  Pilot Frequency (0x18FFD8C0 B3-B4 LE uint16, Hz):")
    out.append(f"    Frames used for range check: {len(freqs_charging):,} (state=12 only)")
    if not freqs:
        out.append("    (no data)")
    else:
        fv = [f for _, f in freqs]
        out.append(f"    Full session: min={min(fv)}  max={max(fv)}")
        if freqs_charging:
            cv = [f for _, f in freqs_charging]
            out.append(f"    During state=12: min={min(cv)}  max={max(cv)}")
            if min(cv) < 995 or max(cv) > 1005:
                note = (f"pilotFrequency out of range during charging "
                        f"({min(cv)}-{max(cv)} Hz, expected 995-1005)")
                out.append(f"    !! ANOMALY: {note}")
                anomalies.append(note)
            else:
                out.append("    OK (995-1005 Hz during state=12)")
        # Pilot offline (freq=0) episodes
        zero_eps, in_z, t_z = [], False, None
        for t, f in freqs:
            if f == 0 and not in_z:
                in_z, t_z = True, t
            elif f != 0 and in_z:
                zero_eps.append((t_z, t - t_z))
                in_z = False
        if in_z and t_z is not None:
            zero_eps.append((t_z, freqs[-1][0] - t_z))
        if zero_eps:
            total_zero = sum(dur for _, dur in zero_eps)
            out.append(
                f"    Pilot offline (freq=0) episodes: {len(zero_eps)}, "
                f"total {total_zero:.1f}s"
            )
            for t_ep, dur in zero_eps:
                dt_str = (f"  dt_to_final={t_ep - ft:+.1f}s"
                          if ft is not None else "")
                out.append(f"      t={t_ep:.2f}s  duration={dur:.1f}s{dt_str}")
            if total_zero > 5.0:
                note = (f"pilot offline {total_zero:.1f}s total "
                        f"({len(zero_eps)} episode(s))")
                anomalies.append(note)
    out.append("")

    # --- chargePilotOnlineTime ---
    out.append("  chargePilotOnlineTime (0x18FFD8C0 B5-B7, 24-bit LE, minutes):")
    if not online_times:
        out.append("    (no data)")
    else:
        resets = []
        prev_v = online_times[0][1]
        for t, v in online_times[1:]:
            if v < prev_v - 1 and prev_v > 1:
                resets.append((t, prev_v, v))
            prev_v = v
        first_v, last_v = online_times[0][1], online_times[-1][1]
        out.append(f"    First={first_v} min  Last={last_v} min")
        if resets:
            out.append(f"    Timer resets detected: {len(resets)}")
            for t_r, old_v, new_v in resets:
                dt_str = (f"  dt_to_final={t_r - ft:+.1f}s"
                          if ft is not None else "")
                out.append(f"      t={t_r:.2f}s  {old_v} -> {new_v} min{dt_str}")
            note = f"chargePilotOnlineTime reset {len(resets)} time(s)"
            anomalies.append(note)
        else:
            out.append("    No resets detected")
    out.append("")

    # --- J1772 flag transitions ---
    out.append("  J1772 Flag Transitions (mux=0 B1 bits):")
    flag_changes = list(_bit_changes(mux0, J1772_FLAG_DEFS))
    if not flag_changes:
        out.append("    (none)")
    else:
        for t, name, old, new in flag_changes:
            dt_str = (f"  dt_to_final={t - ft:+.1f}s"
                      if ft is not None else "")
            tag = "  CLEARED" if new == 0 else "  SET"
            out.append(f"    t={t:.2f}s  {name:<25s} {old} -> {new}{tag}{dt_str}")
        cleared_near = (
            [(t, n) for t, n, o, nv in flag_changes
             if nv == 0 and ft is not None and abs(t - ft) <= window]
        )
        if cleared_near:
            note = (f"{len(cleared_near)} J1772 flag(s) cleared within "
                    f"{window:.0f}s of failure")
            anomalies.append(note)
    out.append("")

    # --- Verdict ---
    out.append("  Verdict:")
    if not anomalies:
        out.append("    J1772 CLEAN -- no anomalies detected.")
    else:
        out.append("    J1772 ANOMALY:")
        for a in anomalies:
            out.append(f"      - {a}")

    return "\n".join(out)


def analyze_vehicle_command(frames_4C0, frames_9C0, window):
    """Step 5: Vehicle charge command (0x18FFD9C0).

    Tier 1 confirmed signals (BelInverter.dbc):
      B0-B1  maxAvailableChargingCurrent  LE signed int16 * 0.05 A
      B2     vehicleState                 uint8
    Tier 2:
      B3-B7  raw bytes, no confirmed meaning
    """
    mux0 = [(t, d) for t, d in frames_4C0 if d and d[0] == 0x00]
    out = []

    if not frames_9C0:
        out.append("  No 0x18FFD9C0 frames -- vehicle charge command absent.")
        return "\n".join(out)

    out.append(f"  0x18FFD9C0 frames: {len(frames_9C0):,}")
    out.append("")

    _, _, failures, final = _find_charger_events(mux0)
    ft = final[0] if final else None
    failure_times = [t for t, _, _ in failures]

    # Decode all frames (require at least 3 bytes for vehicleState)
    decoded = []
    for t, data in frames_9C0:
        if len(data) < 3:
            continue
        raw16 = int.from_bytes(data[0:2], 'little')
        cur_amps = (raw16 if raw16 < 0x8000 else raw16 - 0x10000) * 0.05
        vs = data[2]
        decoded.append((t, cur_amps, vs, data))

    # --- vehicleState timeline ---
    out.append("  vehicleState (B2, uint8):")
    if not decoded:
        out.append("    (no data)")
    else:
        prev_vs = decoded[0][2]
        vs_changes = []
        for t, ca, vs, data in decoded[1:]:
            if vs != prev_vs:
                vs_changes.append((t, prev_vs, vs))
                prev_vs = vs
        out.append(f"    Initial: {decoded[0][2]}   Final: {decoded[-1][2]}")
        if not vs_changes:
            out.append("    No transitions observed.")
        else:
            for t, old, new in vs_changes:
                dt_str = (f"  dt_to_final={t - ft:+.2f}s" if ft is not None else "")
                tag = ""
                if ft is not None and t < ft:
                    tag = "  [BEFORE FAILURE]"
                elif ft is not None and t < ft + 5.0:
                    tag = "  [at failure]"
                out.append(f"    t={t:.2f}s  vehicleState {old} -> {new}{dt_str}{tag}")
    out.append("")

    # --- maxAvailableChargingCurrent ---
    out.append("  maxAvailableChargingCurrent (B0-B1 LE int16 x0.05 A):")
    if not decoded:
        out.append("    (no data)")
    else:
        amps_vals = [a for _, a, _, _ in decoded]
        out.append(f"    Range: {min(amps_vals):.2f} - {max(amps_vals):.2f} A")

        # Significant changes (>=2 A) within 30s of failure only;
        # finer oscillation is normal BMS current-control, not informative
        cur_near_win = 30.0
        if failure_times:
            prev_a = None
            amps_near = []
            for t, a, vs, data in decoded:
                near = any(abs(t - t_f) <= cur_near_win for t_f in failure_times)
                if near and prev_a is not None and abs(a - prev_a) >= 2.0:
                    t_f_near = min(failure_times, key=lambda tf: abs(tf - t))
                    amps_near.append((t, prev_a, a, t - t_f_near))
                prev_a = a
            if amps_near:
                out.append(f"    Significant changes (>=2 A) within {cur_near_win:.0f}s of failure ({len(amps_near)}):")
                for t, old, new, dt in amps_near:
                    out.append(f"      t={t:.2f}s  {old:.2f} -> {new:.2f} A  dt_to_failure={dt:+.1f}s")
            else:
                out.append(f"    No significant (>=2 A) changes within {cur_near_win:.0f}s of failure")
        else:
            out.append("    (no failure events -- not checking changes)")

        # Value at each failure event
        if failure_times:
            out.append("    At failure event(s):")
            for t_f in failure_times:
                nearest = min(decoded, key=lambda x: abs(x[0] - t_f))
                out.append(
                    f"      t_f={t_f:.2f}s  "
                    f"nearest frame t={nearest[0]:.2f}s  "
                    f"current={nearest[1]:.2f} A"
                )
    out.append("")

    # --- Tier 2: bytes B3-B7 near failure ---
    out.append("  Tier 2 -- B3-B7 byte changes within +/-window of failure:")
    if not failure_times:
        out.append("    (no failure events)")
    else:
        t2_changes = []
        prev_data = None
        for t, data in frames_9C0:
            if len(data) < 8:
                prev_data = data
                continue
            if prev_data is not None and len(prev_data) >= 8:
                near = any(abs(t - t_f) <= window for t_f in failure_times)
                if near:
                    for bi in range(3, 8):
                        if data[bi] != prev_data[bi]:
                            t_f_near = min(failure_times, key=lambda tf: abs(tf - t))
                            dt = t - t_f_near
                            tag = "  [BEFORE FAILURE]" if dt < 0 else ""
                            t2_changes.append((t, bi, prev_data[bi], data[bi], dt, tag))
            prev_data = data

        if not t2_changes:
            out.append(f"    None within +/-{window:.0f}s of any failure event.")
        else:
            for t, bi, old, new, dt, tag in t2_changes:
                out.append(
                    f"    t={t:.2f}s  B{bi}: {old:02X} -> {new:02X}"
                    f"  dt_to_failure={dt:+.2f}s{tag}"
                )
    out.append("")

    # --- VCU initiative check ---
    out.append("  VCU Initiative Check (any 0x18FFD9C0 change in 5s before 12->15?):")
    if ft is None:
        out.append("    (no final failure identified)")
    else:
        pre_win = 5.0
        pre_frames = [(t, data) for t, data in frames_9C0
                      if ft - pre_win <= t < ft and len(data) >= 3]
        early_changes = []
        prev = None
        for t, data in pre_frames:
            if prev is not None:
                for bi in range(min(len(data), len(prev))):
                    if data[bi] != prev[bi]:
                        early_changes.append((t, bi, prev[bi], data[bi], ft - t))
            prev = data
        if not early_changes:
            out.append(
                f"    No changes in {pre_win:.0f}s before final failure. "
                f"Consistent with charger-initiated shutdown."
            )
        else:
            out.append(f"    Changes detected before final failure:")
            for t, bi, old, new, dt_before in early_changes:
                out.append(
                    f"      t={t:.2f}s  B{bi}: {old:02X} -> {new:02X}"
                    f"  ({dt_before:.3f}s before failure)"
                )
            out.append("    !! Possible VCU-initiated shutdown -- investigate further.")

    return "\n".join(out)


def analyze_bms_tier1(accumulated, window):
    """Step 4 Tier 1: Confirmed BMS signals.

    Decodes (EPRI CANbusLogger2 Ghidra analysis, 2026-03-26):
      0x440  BCM_Data2:  mainc_stat 16-state contactor sequence, fault_mon, vbus_pos/neg
      0x420  BCM_Limits: bcm_chg_max, bcm_dis_max, cell OV/UV flags
      0x410  BCM_Status: alarm, chgc_stat, hvil_mon, on_plug, epo, cpwr_cmd,
                         chg_done, cool_req; analog ibat/soc/vbat
      0x430  BCM_Data1:  cell_tmax/tmin, cell_vmax/vmin, lvbat, chga_ena/mon, veh_mon
      0x411  BMS SoC hi-res: (B0*64 + (B1>>2)) / 100 %
    """
    mux0 = [(t, d) for t, d in accumulated.get(0x18FFD4C0, []) if d and d[0] == 0x00]
    _, _, failures, final = _find_charger_events(mux0)
    ft = final[0] if final else None
    failure_times = [t for t, _, _ in failures]

    def _dt(t):
        return f"  dt={t - ft:+8.2f}s" if ft is not None else f"  t={t:9.2f}s"

    out = []

    # ── 0x440 Contactor Sequence ──────────────────────────────────────────
    frames_440 = accumulated.get(0x440, [])
    out.append("  Contactor Sequence (0x440 bcm_mainc_stat):")
    if not frames_440:
        out.append("    (no 0x440 frames)")
    else:
        prev_stat = prev_fm = None
        transitions = []
        # fault_mon (bit 6) oscillates ~1/s as a normal heartbeat; debounce it.
        fm_set_count = 0          # total 0->1 transitions
        fm_sustained_near = []    # (t, duration) for SET events >=0.5s near failure
        fm_set_start = None       # timestamp of current SET edge
        t_prev_fm = None

        fail_lo = min(failure_times) - window if failure_times else None
        fail_hi = max(failure_times) + window if failure_times else None

        for t, data in frames_440:
            d = _decode_0x440(data)
            if d is None:
                continue
            if prev_stat is None:
                prev_stat = d['mainc_stat']
                prev_fm = d['fault_mon']
                t_prev_fm = t
                out.append(f"    Initial (t={t:.1f}s):  {prev_stat}  fault_mon={prev_fm}")
                if prev_fm:
                    fm_set_start = t
                continue
            if d['mainc_stat'] != prev_stat:
                transitions.append((t, prev_stat, d['mainc_stat']))
                prev_stat = d['mainc_stat']
            if d['fault_mon'] != prev_fm:
                if d['fault_mon']:
                    # Rising edge
                    fm_set_count += 1
                    fm_set_start = t
                else:
                    # Falling edge — measure how long it was SET
                    if fm_set_start is not None:
                        dur = t - fm_set_start
                        if dur >= 0.5 and fail_lo is not None:
                            if fail_lo <= fm_set_start <= fail_hi:
                                fm_sustained_near.append((fm_set_start, dur))
                    fm_set_start = None
                prev_fm = d['fault_mon']
                t_prev_fm = t

        if not transitions:
            out.append("    No mainc_stat transitions")
        else:
            for t, old, new in transitions:
                warn = ("  !! CONTACTOR FAULT" if "FAILED" in new
                        else "  [shutdown]" if new in ("SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN")
                        else "")
                out.append(f"   {_dt(t)}  {old} -> {new}{warn}")

        # fault_mon summary (one line, not per-toggle)
        if fm_set_count == 0:
            out.append("    fault_mon: never SET")
        elif fm_sustained_near:
            detail = ", ".join(f"t={ts:.1f}s dur={d:.2f}s" for ts, d in fm_sustained_near)
            out.append(f"    fault_mon: {fm_set_count} SET events total; "
                       f"{len(fm_sustained_near)} sustained near failure: {detail}")
        else:
            out.append(f"    fault_mon: {fm_set_count} SET events (normal oscillation, "
                       f"none sustained near failure)")

        if failure_times and frames_440:
            out.append("    At failure event(s):")
            for t_f in failure_times:
                near_t, near_d_raw = min(frames_440, key=lambda x: abs(x[0] - t_f))
                d = _decode_0x440(near_d_raw)
                if d:
                    out.append(f"      t_f={t_f:.2f}s  {d['mainc_stat']}  "
                               f"vbus_pos={d['vbus_pos']}V  vbus_neg={d['vbus_neg']}V")
    out.append("")

    # ── 0x420 BCM Charge Limits ───────────────────────────────────────────
    frames_420 = accumulated.get(0x420, [])
    out.append("  BCM Charge/Discharge Limits (0x420):")
    if not frames_420:
        out.append("    (no 0x420 frames)")
    else:
        dec420 = [(t, _decode_0x420(d)) for t, d in frames_420]
        dec420 = [(t, d) for t, d in dec420 if d is not None]
        if dec420:
            t0, d0 = dec420[0]
            out.append(f"    First (t={t0:.1f}s):  chg_max={d0['chg_max']} A  "
                       f"dis_max={d0['dis_max']} A  "
                       f"cell_OV={d0['cell_overvolt']}  cell_UV={d0['cell_undervolt']}")
            # Significant chg_max swings (>= 5A)
            prev_chg = d0['chg_max']
            chg_swings = []
            for t, d in dec420[1:]:
                if d['chg_max'] is not None and prev_chg is not None:
                    if abs(d['chg_max'] - prev_chg) >= 5.0:
                        chg_swings.append((t, prev_chg, d['chg_max']))
                        prev_chg = d['chg_max']
            if chg_swings:
                out.append(f"    chg_max changes (>= 5 A):")
                for t, old, new in chg_swings:
                    out.append(f"     {_dt(t)}  {old:.1f} -> {new:.1f} A")
            else:
                out.append("    chg_max stable throughout (no swings >= 5 A)")
            # OV/UV flag changes
            prev_ov, prev_uv = d0['cell_overvolt'], d0['cell_undervolt']
            for t, d in dec420[1:]:
                if d['cell_overvolt'] != prev_ov:
                    out.append(f"     {_dt(t)}  cell_overvolt {prev_ov} -> {d['cell_overvolt']}")
                    prev_ov = d['cell_overvolt']
                if d['cell_undervolt'] != prev_uv:
                    out.append(f"     {_dt(t)}  cell_undervolt {prev_uv} -> {d['cell_undervolt']}")
                    prev_uv = d['cell_undervolt']
            if failure_times:
                out.append("    At failure event(s):")
                for t_f in failure_times:
                    near_t, near_d = min(dec420, key=lambda x: abs(x[0] - t_f))
                    out.append(f"      t_f={t_f:.2f}s  chg_max={near_d['chg_max']} A  "
                               f"dis_max={near_d['dis_max']} A")
    out.append("")

    # ── 0x410 BCM Status Flags + Analog ──────────────────────────────────
    frames_410 = accumulated.get(0x410, [])
    out.append("  BCM Status Flags (0x410):")
    if not frames_410:
        out.append("    (no 0x410 frames)")
    else:
        dec410 = [(t, _decode_0x410(d)) for t, d in frames_410]
        dec410 = [(t, d) for t, d in dec410 if d is not None]
        if dec410:
            t0, d0 = dec410[0]
            out.append(f"    Baseline (t={t0:.1f}s):  alarm={d0['alarm']}  "
                       f"chgc_stat={d0['chgc_stat']}  hvil_mon={d0['hvil_mon']}  "
                       f"on_plug={d0['on_plug']}  epo={d0['epo']}  ready={d0['ready']}  "
                       f"cpwr_cmd={d0['cpwr_cmd']}")
            DISC = ('alarm', 'chgc_stat', 'hvil_mon', 'on_plug', 'epo',
                    'ready', 'cpwr_cmd', 'chg_done', 'cool_req')
            prev = {k: d0[k] for k in DISC}
            for t, d in dec410[1:]:
                for k in DISC:
                    if d[k] != prev[k]:
                        out.append(f"     {_dt(t)}  {k}: {prev[k]} -> {d[k]}")
                        prev[k] = d[k]
            soc_vals  = [d['soc']  for _, d in dec410 if d['soc']  is not None]
            ibat_vals = [d['ibat'] for _, d in dec410 if d['ibat'] is not None]
            vbat_vals = [d['vbat'] for _, d in dec410 if d['vbat'] is not None]
            if soc_vals:
                out.append(f"    bcm_soc:  {min(soc_vals):.1f} - {max(soc_vals):.1f} %")
            if ibat_vals:
                out.append(f"    bcm_ibat: {min(ibat_vals):.1f} - {max(ibat_vals):.1f} A")
            if vbat_vals:
                out.append(f"    bcm_vbat: {min(vbat_vals):.1f} - {max(vbat_vals):.1f} V")
            if failure_times:
                out.append("    At failure event(s):")
                for t_f in failure_times:
                    near_t, near_d = min(dec410, key=lambda x: abs(x[0] - t_f))
                    out.append(f"      t_f={t_f:.2f}s  soc={near_d['soc']}%  "
                               f"ibat={near_d['ibat']}A  vbat={near_d['vbat']}V")
    out.append("")

    # ── 0x430 Cell Temps + Voltages ───────────────────────────────────────
    frames_430 = accumulated.get(0x430, [])
    out.append("  Cell Temps / Voltages (0x430 BCM_Data1):")
    if not frames_430:
        out.append("    (no 0x430 frames)")
    else:
        dec430 = [(t, _decode_0x430(d)) for t, d in frames_430]
        dec430 = [(t, d) for t, d in dec430 if d is not None]
        if dec430:
            t0, d0 = dec430[0]
            out.append(f"    Baseline (t={t0:.1f}s):  "
                       f"tmax={d0['cell_tmax']} degC  tmin={d0['cell_tmin']} degC  "
                       f"vmax={d0['cell_vmax']} V  vmin={d0['cell_vmin']} V  "
                       f"lvbat={d0['lvbat']} V")
            tmax_v = [d['cell_tmax'] for _, d in dec430 if d['cell_tmax'] is not None]
            tmin_v = [d['cell_tmin'] for _, d in dec430 if d['cell_tmin'] is not None]
            vmax_v = [d['cell_vmax'] for _, d in dec430 if d['cell_vmax'] is not None]
            vmin_v = [d['cell_vmin'] for _, d in dec430 if d['cell_vmin'] is not None]
            if tmax_v:
                out.append(f"    cell_tmax range: {min(tmax_v):.1f} - {max(tmax_v):.1f} degC")
            if tmin_v:
                out.append(f"    cell_tmin range: {min(tmin_v):.1f} - {max(tmin_v):.1f} degC")
            if vmax_v:
                out.append(f"    cell_vmax range: {min(vmax_v):.3f} - {max(vmax_v):.3f} V")
            if vmin_v:
                out.append(f"    cell_vmin range: {min(vmin_v):.3f} - {max(vmin_v):.3f} V")
            # Bool flag transitions
            BOOLS_430 = ('chga_ena', 'chga_mon', 'mod_ena', 'veh_mon')
            prev_b = {k: d0[k] for k in BOOLS_430}
            for t, d in dec430[1:]:
                for k in BOOLS_430:
                    if d[k] != prev_b[k]:
                        out.append(f"     {_dt(t)}  {k}: {prev_b[k]} -> {d[k]}")
                        prev_b[k] = d[k]
            if failure_times:
                out.append("    At failure event(s):")
                for t_f in failure_times:
                    near_t, near_d = min(dec430, key=lambda x: abs(x[0] - t_f))
                    out.append(f"      t_f={t_f:.2f}s  "
                               f"tmax={near_d['cell_tmax']} degC  "
                               f"tmin={near_d['cell_tmin']} degC  "
                               f"vmax={near_d['cell_vmax']} V  "
                               f"vmin={near_d['cell_vmin']} V")
    out.append("")

    # ── 0x411 SoC Hi-Res ─────────────────────────────────────────────────
    frames_411 = accumulated.get(0x411, [])
    out.append("  SoC Hi-Res (0x411, formula: (B0*64 + (B1>>2)) / 100 %):")
    if not frames_411:
        out.append("    (no 0x411 frames)")
    else:
        soc_series = []
        for t, data in frames_411:
            if len(data) >= 2:
                soc_series.append((t, (data[0] * 64 + (data[1] >> 2)) / 100.0))
        if soc_series:
            soc_vals = [s for _, s in soc_series]
            out.append(f"    First: {soc_series[0][1]:.2f}%  "
                       f"Last: {soc_series[-1][1]:.2f}%  "
                       f"(delta: {soc_series[-1][1] - soc_series[0][1]:+.2f}%)")
            out.append(f"    Range: {min(soc_vals):.2f} - {max(soc_vals):.2f} %")
            if failure_times:
                out.append("    At failure event(s):")
                for t_f in failure_times:
                    near = min(soc_series, key=lambda x: abs(x[0] - t_f))
                    out.append(f"      t_f={t_f:.2f}s  SoC={near[1]:.2f}%")
    out.append("")

    # ── 0x0400 HSC_BCM_Ctrl ───────────────────────────────────────────────
    # Full timeline shown (not windowed) to capture before/after battery swap.
    frames_0400 = accumulated.get(0x0400, [])
    out.append("  HSC BCM Control Bits (0x0400 B0 bits 0-3) -- full timeline:")
    _BITS_0400 = ('hsc_bcm_enable', 'hsc_bcm_epo', 'hsc_bcm_mainc_close', 'hsc_bcm_leakage_ena')
    if not frames_0400:
        out.append("    (no 0x0400 frames)")
    else:
        dec0400 = [(t, _decode_0x0400(d)) for t, d in frames_0400]
        dec0400 = [(t, d) for t, d in dec0400 if d is not None]
        if not dec0400:
            out.append("    (no decodable frames)")
        else:
            t0, d0 = dec0400[0]
            bits_str = "  ".join(f"{k}={d0[k]}" for k in _BITS_0400)
            out.append(f"    Initial (t={t0:.1f}s):  {bits_str}")
            prev = {k: d0[k] for k in _BITS_0400}
            for t, d in dec0400[1:]:
                for k in _BITS_0400:
                    if d[k] != prev[k]:
                        out.append(f"     {_dt(t)}  {k}: {prev[k]} -> {d[k]}")
                        prev[k] = d[k]
            t_last, d_last = dec0400[-1]
            bits_last = "  ".join(f"{k}={d_last[k]}" for k in _BITS_0400)
            out.append(f"    Final   (t={t_last:.1f}s):  {bits_last}")
            if failure_times:
                out.append("    At failure event(s):")
                for t_f in failure_times:
                    near_t, near_d = min(dec0400, key=lambda x: abs(x[0] - t_f))
                    bits_f = "  ".join(f"{k}={near_d[k]}" for k in _BITS_0400)
                    out.append(f"      t_f={t_f:.2f}s  {bits_f}")
    out.append("")

    return "\n".join(out)


def analyze_bms_tier2(accumulated, window):
    """Step 5 Tier 2: Unconfirmed BMS raw observation.

    Reports raw byte changes for 0x412, 0x63A, 0x63D within the failure window.
    """
    mux0 = [(t, d) for t, d in accumulated.get(0x18FFD4C0, []) if d and d[0] == 0x00]
    _, _, failures, _ = _find_charger_events(mux0)
    failure_times = [t for t, _, _ in failures]

    out = []

    if not failure_times:
        out.append("  (no failure events -- Tier 2 raw observation skipped)")
        return "\n".join(out)

    for tid, label in [
        (0x412, "0x412 (charge current limit, unconfirmed)"),
        (0x63A, "0x63A (cell extremes / delta, unconfirmed)"),
        (0x63D, "0x63D (fault flags OV/UV/OT, unconfirmed)"),
    ]:
        frames = accumulated.get(tid, [])
        out.append(f"  {label}:")
        if not frames:
            out.append("    (no frames)")
        else:
            prev_data = None
            changes_near = []
            for t, data in frames:
                if any(abs(t - t_f) <= window for t_f in failure_times):
                    if prev_data is not None and data != prev_data:
                        diffs = [f"B{bi}:{prev_data[bi]:02X}->{data[bi]:02X}"
                                 for bi in range(min(len(data), len(prev_data)))
                                 if data[bi] != prev_data[bi]]
                        if diffs:
                            t_f_near = min(failure_times, key=lambda tf: abs(tf - t))
                            changes_near.append((t, t - t_f_near, diffs))
                prev_data = data
            if not changes_near:
                out.append(f"    No changes within +/-{window:.0f}s of any failure event")
            else:
                for t, dt, diffs in changes_near:
                    out.append(f"    t={t:.2f}s  dt={dt:+.2f}s  " + "  ".join(diffs))
        out.append("")

    return "\n".join(out)


def analyze_vi_profile(frames_4C0, frames_7C0, window):
    """Step 7: V/I profile (0x18FFD7C0 BELINV_hvBatteryAndCharger).

    Signals (all LE int16 * 0.05):
      B0-B1  hvBatteryVoltage    V
      B2-B3  hvBatteryCurrent    A  (negative = charging into pack)
      B4-B5  chargerInputVoltage V  (AC input)
      B6-B7  chargerInputCurrent A  (AC input)
    """
    mux0 = [(t, d) for t, d in frames_4C0 if d and d[0] == 0x00]
    out = []

    if not frames_7C0:
        out.append("  No 0x18FFD7C0 frames -- V/I telemetry absent.")
        return "\n".join(out)

    out.append(f"  0x18FFD7C0 frames: {len(frames_7C0):,}")
    out.append("")

    _, _, failures, final = _find_charger_events(mux0)
    ft = final[0] if final else None
    failure_times = [t for t, _, _ in failures]

    def _s16(data, byte_idx):
        raw = int.from_bytes(data[byte_idx:byte_idx + 2], 'little')
        return (raw if raw < 0x8000 else raw - 0x10000) * 0.05

    # Decode all frames; require 8 bytes
    decoded = []
    for t, data in frames_7C0:
        if len(data) < 8:
            continue
        decoded.append((t, _s16(data, 0), _s16(data, 2), _s16(data, 4), _s16(data, 6)))
        # (t, hvV, hvI, acV, acI)

    if not decoded:
        out.append("  No valid 8-byte frames.")
        return "\n".join(out)

    # Build state lookup for state=12 filtering
    state_seq = [(t, d[5]) for t, d in mux0 if len(d) >= 8]
    state_ptr, current_state = 0, None
    decoded_charging = []
    for t, hvV, hvI, acV, acI in decoded:
        while state_ptr < len(state_seq) and state_seq[state_ptr][0] <= t:
            current_state = state_seq[state_ptr][1]
            state_ptr += 1
        if current_state == 12:
            decoded_charging.append((t, hvV, hvI, acV, acI))

    # --- Range summary ---
    out.append("  Session range (all state=12 frames):")
    if not decoded_charging:
        out.append("    (no state=12 frames with V/I data)")
    else:
        hvV_vals = [r[1] for r in decoded_charging]
        hvI_vals = [r[2] for r in decoded_charging]
        acV_vals = [r[3] for r in decoded_charging]
        acI_vals = [r[4] for r in decoded_charging]
        out.append(f"    hvBatteryVoltage:    {min(hvV_vals):.1f} - {max(hvV_vals):.1f} V")
        out.append(f"    hvBatteryCurrent:    {min(hvI_vals):.1f} - {max(hvI_vals):.1f} A  (neg=charging)")
        out.append(f"    chargerInputVoltage: {min(acV_vals):.1f} - {max(acV_vals):.1f} V")
        out.append(f"    chargerInputCurrent: {min(acI_vals):.1f} - {max(acI_vals):.1f} A")
    out.append("")

    # --- Sampled trend (every ~60s) ---
    out.append("  Sampled trend during state=12 (~60s intervals):")
    if decoded_charging:
        last_sample_t = decoded_charging[0][0] - 999
        for t, hvV, hvI, acV, acI in decoded_charging:
            if t - last_sample_t >= 60.0:
                dt_str = (f"  dt_to_final={t - ft:+.0f}s" if ft is not None else "")
                out.append(
                    f"    t={t:8.1f}s  hvV={hvV:6.1f}V  hvI={hvI:7.2f}A"
                    f"  acV={acV:6.1f}V  acI={acI:6.2f}A{dt_str}"
                )
                last_sample_t = t
    out.append("")

    # --- Mid-session zero-current episodes ---
    # A "power drop" is when |hvBatteryCurrent| < 0.5 A for >= 5s during
    # state=12, occurring >60s after first state=12 entry.
    first_12_t = decoded_charging[0][0] if decoded_charging else None
    out.append("  Mid-session power drops (|hvBatteryCurrent| < 0.5 A, >5s, after 60s grace):")
    if not decoded_charging or first_12_t is None:
        out.append("    (no data)")
    else:
        drops, in_drop, t_d0 = [], False, None
        for t, hvV, hvI, acV, acI in decoded_charging:
            if t - first_12_t < 60.0:
                continue
            if abs(hvI) < 0.5 and not in_drop:
                in_drop, t_d0 = True, t
            elif abs(hvI) >= 0.5 and in_drop:
                dur = t - t_d0
                if dur >= 5.0:
                    drops.append((t_d0, dur))
                in_drop = False
        if in_drop and t_d0 is not None and decoded_charging:
            dur = decoded_charging[-1][0] - t_d0
            if dur >= 5.0:
                drops.append((t_d0, dur))

        if not drops:
            out.append("    None detected.")
        else:
            for i, (t_d, dur) in enumerate(drops, 1):
                dt_str = (f"  dt_to_final={t_d - ft:+.0f}s" if ft is not None else "")
                # Sample V/I just before and at the drop
                pre = [(t, hvI) for t, hvV, hvI, acV, acI in decoded
                       if t_d - 5 <= t < t_d]
                pre_i = pre[-1][1] if pre else None
                out.append(
                    f"    #{i:2d}  t={t_d:.1f}s  duration={dur:.1f}s"
                    f"  pre-drop hvI={pre_i:.2f}A" if pre_i is not None else
                    f"    #{i:2d}  t={t_d:.1f}s  duration={dur:.1f}s"
                )
                out[-1] += dt_str
    out.append("")

    # --- V/I at each failure event ---
    out.append(f"  V/I at failure event(s) (+/-5s window):")
    if not failure_times:
        out.append("    (no failure events)")
    else:
        for t_f in failure_times:
            window_frames = [(t, hvV, hvI, acV, acI) for t, hvV, hvI, acV, acI in decoded
                             if abs(t - t_f) <= 5.0]
            if not window_frames:
                out.append(f"    t_f={t_f:.2f}s  (no V/I frames within 5s)")
                continue
            out.append(f"    t_f={t_f:.2f}s:")
            for t, hvV, hvI, acV, acI in window_frames:
                out.append(
                    f"      dt={t - t_f:+6.2f}s  hvV={hvV:.1f}V  hvI={hvI:.2f}A"
                    f"  acV={acV:.1f}V  acI={acI:.2f}A"
                )

    return "\n".join(out)


def analyze_hcu_vehicle(accumulated, window):
    """Step 6: HCU and vehicle-side signals.

    Decodes (EPRI CANbusLogger2 Ghidra analysis, 2026-03-26):
      0x053  HCU OperatingMode (B0[6:4]) / OperatingState (B0[3:0])
      0x065B HCU DTC codes: B6:B7 big-endian uint16, 29-entry lookup table
      0x592  HCU_Sensor: EVSESwitchState (B0[1]), ExportPowerState (B0[2]),
                          IgnitionKeyState (B0[4])
      0x054  GENE_RotSpd: int16_LE(B0:B1) - 32767 rpm; EmergcyStp_flg B4[3]
      0x598  Power averages: DBL_ESSPwrAvg (int16_LE B0:B1 * 0.01 kW),
                              DBL_TracPwrAvg ((B5<<8|B4) signed * 0.01 kW)
    """
    mux0 = [(t, d) for t, d in accumulated.get(0x18FFD4C0, []) if d and d[0] == 0x00]
    _, _, failures, final = _find_charger_events(mux0)
    ft = final[0] if final else None
    failure_times = [t for t, _, _ in failures]

    def _dt(t):
        return f"  dt={t - ft:+8.2f}s" if ft is not None else f"  t={t:9.2f}s"

    out = []

    # ── 0x053 HCU Operating Mode / State ─────────────────────────────────
    frames_053 = accumulated.get(0x053, [])
    out.append("  HCU Operating Mode/State (0x053):")
    if not frames_053:
        out.append("    (no 0x053 frames)")
    else:
        prev_mode = prev_state = None
        t0, d0 = frames_053[0]
        if d0:
            m0  = OP_MODE_STRS[min((d0[0] >> 4) & 0x7, 3)]
            i0  = d0[0] & 0xF
            s0  = OP_STATE_STRS[i0] if i0 < len(OP_STATE_STRS) else f"Unknown({i0})"
            out.append(f"    Initial (t={t0:.1f}s):  mode={m0}  state={s0}")
            prev_mode, prev_state = m0, s0
        for t, data in frames_053[1:]:
            if not data:
                continue
            mode  = OP_MODE_STRS[min((data[0] >> 4) & 0x7, 3)]
            idx   = data[0] & 0xF
            state = OP_STATE_STRS[idx] if idx < len(OP_STATE_STRS) else f"Unknown({idx})"
            if mode != prev_mode or state != prev_state:
                warn = (f"  !! {state}" if state in ("FAILURE", "SHTDWN", "WAIT4COOLING")
                        else "")
                out.append(f"    {_dt(t)}  mode={mode}  state={state}{warn}")
                prev_mode, prev_state = mode, state
    out.append("")

    # ── 0x065B HCU DTC Codes ─────────────────────────────────────────────
    frames_65B = accumulated.get(0x065B, [])
    out.append("  HCU DTC Codes (0x065B B6:B7 BE uint16):")
    if not frames_65B:
        out.append("    (no 0x065B frames)")
    else:
        dtcs_seen = {}  # code -> first timestamp
        for t, data in frames_65B:
            if len(data) < 8:
                continue
            code = (data[6] << 8) | data[7]
            if code != 0x0000 and code not in dtcs_seen:
                dtcs_seen[code] = t
        if not dtcs_seen:
            out.append(f"    {len(frames_65B):,} frames -- all DTC=0x0000 (no active faults)")
        else:
            out.append(f"    Active DTC codes ({len(dtcs_seen)} unique):")
            for code, first_t in sorted(dtcs_seen.items()):
                name   = DTC_TABLE.get(code, f"Unknown(0x{code:04X})")
                out.append(f"     {_dt(first_t)}  0x{code:04X}  {name}")
    out.append("")

    # ── 0x592 EVSE Switch / Ignition / Export ────────────────────────────
    frames_592 = accumulated.get(0x592, [])
    out.append("  HCU Sensor Flags (0x592 B0):")
    if not frames_592:
        out.append("    (no 0x592 frames)")
    else:
        def _dec592(data):
            if not data:
                return None
            return {
                'evse_sw':  (data[0] >> 1) & 1,
                'export':   (data[0] >> 2) & 1,
                'ignition': (data[0] >> 4) & 1,
            }
        t0, d0 = frames_592[0]
        s0 = _dec592(d0)
        if s0:
            out.append(f"    Initial (t={t0:.1f}s):  ignition={s0['ignition']}  "
                       f"evse_sw={s0['evse_sw']}  export={s0['export']}")
            prev_s = s0
            for t, data in frames_592[1:]:
                s = _dec592(data)
                if s is None:
                    continue
                for k in ('evse_sw', 'export', 'ignition'):
                    if s[k] != prev_s[k]:
                        out.append(f"    {_dt(t)}  {k}: {prev_s[k]} -> {s[k]}")
                prev_s = s
    out.append("")

    # ── 0x054 Generator RPM ───────────────────────────────────────────────
    frames_054 = accumulated.get(0x054, [])
    out.append("  Generator RPM (0x054 GENE_RotSpd = int16_LE(B0:B1) - 32767):")
    if not frames_054:
        out.append("    (no 0x054 frames)")
    else:
        rpms = []
        emg_changes = []
        prev_emg = None
        for t, data in frames_054:
            if len(data) < 2:
                continue
            rpm = int.from_bytes(data[0:2], 'little', signed=False) - 32767
            rpms.append((t, rpm))
            if len(data) >= 5:
                emg = (data[4] >> 3) & 1
                if prev_emg is not None and emg != prev_emg:
                    emg_changes.append((t, prev_emg, emg))
                prev_emg = emg
        if rpms:
            rpm_vals = [r for _, r in rpms]
            out.append(f"    Range: {min(rpm_vals)} - {max(rpm_vals)} rpm")
            nonzero = [r for r in rpm_vals if r != 0]
            if nonzero:
                out.append(f"    Non-zero: {min(nonzero)} - {max(nonzero)} rpm"
                           "  (generator spinning -- unexpected during charge)")
            else:
                out.append("    All 0 rpm (generator idle -- expected during charge)")
            if emg_changes:
                for t, old, new in emg_changes:
                    out.append(f"    {_dt(t)}  EmergcyStp_flg: {old} -> {new}"
                               + ("  !! EMERGENCY STOP" if new else ""))
            if failure_times:
                out.append("    RPM at failure event(s):")
                for t_f in failure_times:
                    near = min(rpms, key=lambda x: abs(x[0] - t_f))
                    out.append(f"      t_f={t_f:.2f}s  RPM={near[1]}")
    out.append("")

    # ── 0x598 HCU Power Averages ─────────────────────────────────────────
    frames_598 = accumulated.get(0x598, [])
    out.append("  HCU Power Averages (0x598):")
    if not frames_598:
        out.append("    (no 0x598 frames)")
    else:
        pwr = []
        for t, data in frames_598:
            if len(data) < 6:
                continue
            ess_raw  = int.from_bytes(data[0:2], 'little', signed=True)
            trac_raw = (data[5] << 8) | data[4]
            if trac_raw >= 0x8000:
                trac_raw -= 0x10000
            pwr.append((t, ess_raw * 0.01, trac_raw * 0.01))
        if pwr:
            ess_v  = [e for _, e, _ in pwr]
            trac_v = [tr for _, _, tr in pwr]
            out.append(f"    DBL_ESSPwrAvg:  {min(ess_v):.1f} - {max(ess_v):.1f} kW")
            out.append(f"    DBL_TracPwrAvg: {min(trac_v):.1f} - {max(trac_v):.1f} kW")
            if failure_times:
                out.append("    At failure event(s):")
                for t_f in failure_times:
                    near = min(pwr, key=lambda x: abs(x[0] - t_f))
                    out.append(f"      t_f={t_f:.2f}s  ESS={near[1]:.2f} kW  "
                               f"Trac={near[2]:.2f} kW")
    out.append("")

    return "\n".join(out)


def classify_failure(results):
    """Step 8: Failure pattern classification."""
    return "[Step 8: Failure classification -- NOT YET IMPLEMENTED]"


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(paths, pt_bus, accumulated, duration, frame_count, window):
    label = ", ".join(p.name for p in paths)
    lines = []

    lines.append(SEP)
    lines.append("VTRUX CHARGE FAILURE ANALYSIS")
    lines.append(SEP)
    lines.append(f"Log:      {label}")
    lines.append(f"Duration: {duration:.1f}s ({duration / 60:.1f} min)")
    lines.append(f"Frames:   {frame_count:,} total")
    if pt_bus is not None:
        lines.append(f"PT bus:   channel {pt_bus} (anchor: 0x{PT_BUS_ANCHOR_ID:03X})")
    else:
        lines.append(
            f"PT bus:   NOT IDENTIFIED -- neither 0x{PT_BUS_ANCHOR_ID:03X} nor "
            f"0x{PT_BUS_ANCHOR_FALLBACK:08X} seen. Wrong log or non-PT capture?"
        )
    lines.append("")

    lines.append(classify_failure({}))
    lines.append("")

    lines.append(SEP)
    lines.append("1. CHARGER STATE MACHINE (0x18FFD4C0)")
    lines.append(SEP)
    lines.append(analyze_charger_state(accumulated[0x18FFD4C0], window))
    lines.append("")

    lines.append(SEP)
    lines.append("2. J1772 CONNECTION HEALTH")
    lines.append(SEP)
    lines.append(analyze_j1772(accumulated[0x18FFD4C0], accumulated[0x18FFD8C0], window))
    lines.append("")

    lines.append(SEP)
    lines.append("3. VEHICLE CHARGE COMMAND (0x18FFD9C0)")
    lines.append(SEP)
    lines.append(analyze_vehicle_command(accumulated[0x18FFD4C0], accumulated[0x18FFD9C0], window))
    lines.append("")

    lines.append(SEP)
    lines.append("4. BMS CLUSTER -- TIER 1 (CONFIRMED)")
    lines.append(SEP)
    lines.append(analyze_bms_tier1(accumulated, window))
    lines.append("")

    lines.append(SEP)
    lines.append("5. BMS CLUSTER -- TIER 2 (UNCONFIRMED RAW OBSERVATION)")
    lines.append(SEP)
    lines.append(analyze_bms_tier2(accumulated, window))
    lines.append("")

    lines.append(SEP)
    lines.append("6. HCU / VEHICLE SIGNALS")
    lines.append(SEP)
    lines.append(analyze_hcu_vehicle(accumulated, window))
    lines.append("")

    lines.append(SEP)
    lines.append("7. V/I PROFILE AT FAILURE EVENT(S)")
    lines.append(SEP)
    lines.append(analyze_vi_profile(accumulated[0x18FFD4C0], accumulated[0x18FFD7C0], window))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Vtrux charge failure analysis tool."
    )
    parser.add_argument(
        "files", nargs="*", metavar="FILE",
        help="One or more log files (merged by timestamp)."
    )
    parser.add_argument(
        "--dir", metavar="DIR",
        help="Scan directory for capture groups."
    )
    parser.add_argument(
        "--session", metavar="SFX",
        help="With --dir: restrict to sessions whose prefix contains SFX."
    )
    parser.add_argument(
        "--output", "-o", metavar="FILE",
        help="Write report to this file (default: stdout)."
    )
    parser.add_argument(
        "--window", "-w", type=float, default=120.0, metavar="SEC",
        help="Analysis window in seconds around each failure event (default: 120)."
    )
    args = parser.parse_args()

    if args.dir and args.files:
        parser.error("--dir and FILE arguments are mutually exclusive.")
    if not args.dir and not args.files:
        parser.error("Provide FILE argument(s) or use --dir.")

    paths = resolve_input_files(args)
    pt_bus, accumulated, duration, frame_count = collect_frames(paths)
    report = build_report(paths, pt_bus, accumulated, duration, frame_count, args.window)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(report, encoding="utf-8")
        print(f"Report written to {out_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
