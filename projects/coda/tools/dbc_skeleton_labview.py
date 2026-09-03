#!/usr/bin/env python3
"""Generate skeleton DBC files from LabVIEW XML extraction JSON.

Reads the merged signal inventory from labview_xml_extract.py and produces
skeleton DBC files for B CAN and D CAN with:
- Messages for clusters with known CAN IDs (from embedded hex in cluster names)
- Placeholder messages for clusters without CAN IDs (ID = 0x1FFF + index)
- Signal stubs with type hints from LabVIEW types in comments
- No real bit positions -- signals packed sequentially as layout hints only

Bus assignment is by originating module per vehicle architecture, NOT by which
bus the LabVIEW app captured on (the GWM rebroadcasts many messages cross-bus).

Usage:
    python tools/dbc_skeleton_labview.py <signals.json> --b-can out_b.dbc --d-can out_d.dbc
"""

import argparse
import json
import re
import sys
from pathlib import Path

# -----------------------------------------------------------------------
# Bus assignment: which clusters go on which CAN bus
#
# From projects/coda/README.md topology:
#   B CAN: GWM, TEM, HVAC, ACCM, IPK, SRS, OCS, DCDC, CHM (charger), BMS, FCHM
#   D CAN: DLCM, TCM, ESC, RCU, PSM/EPS
#   Motor CAN (private, not OBD): MCM -- relayed through DLCM, so D CAN
#
# Note: the GWM rebroadcasts many messages across buses, so the LabVIEW app
# sees messages from both buses on a single dongle. We assign to the bus
# where the message *originates* per vehicle architecture.
# -----------------------------------------------------------------------

# Clusters explicitly assigned to D CAN (originate from D CAN modules)
D_CAN_CLUSTERS = {
    # DLCM module signals
    'DLCM',
    'DLCM Globals',
    'AccurateFeedbacks',
    'EMS 3',
    'FCM 1',
    # TCM
    'TCM',
    # ESC / ABS
    'BS_208h',           # ESC brake/stability message on 0x208
    # EPS / Power steering
    'EPS SAM_1',
    # MCM (private motor CAN, relayed through DLCM to D CAN)
    'MCM',
    'MCM.Tempreature',   # note: typo is from original LabVIEW
}

# Clusters that are cross-bus global data or internal LabVIEW constructs -- skip
SKIP_CLUSTERS = {
    'global data',       # aggregate of everything, not a single CAN message
    'DCDC',              # parent TypeDef wrapping DCDCStatus1+2, not a message itself
    'DCDC globals',      # same as DCDC, global variable wrapper
    'BMS Globals',       # parent container, not a single message
    'CMM Globals',       # parent container
    'Vehicle_Mode',      # GWM-internal mode state, likely derived from multiple messages
    'Death Counter',     # heartbeat watchdog counters (internal bookkeeping)
    'Tire',              # single tire element (array element, not a message)
    'CAN Frame',         # LabVIEW CAN frame struct (infrastructure)
    'Recv Frame',        # LabVIEW receive frame (infrastructure)
    'error out',         # LabVIEW error cluster
    'error in',          # LabVIEW error cluster
    'txd',               # LabVIEW data space internal
    'ext',               # LabVIEW data space internal
    'sum',               # LabVIEW internal
    'BMSDrivingRange',   # sub-cluster of BMS Globals, not its own message
    'VehFaults',         # sub-cluster of global data
}

# Known CAN IDs from existing DBC + hardware manuals (not embedded in cluster names)
KNOWN_CAN_IDS = {
    'DCDCStatus1': 469,           # 0x1D5, from DCDC hardware manual
    'BMS_DCDCEnableSet': 471,     # 0x1D7, from DCDC hardware manual
    'HEV_PCM_Control_3': 1040,    # 0x410, AC compressor control
    'CMSInputValues': 635,        # 0x27B
    'CMSOutputValues': 636,       # 0x27C
    'CMSTempStatus': 634,         # 0x27A
    'HVACAirState': 913,          # 0x391
}

# Map LabVIEW cluster names to DBC-safe message names
NAME_OVERRIDES = {
    'DCDCStatus2 (0x48A)': 'DCDCStatus2',
    'ChrgrSysCtrlEcho (0x616)': 'ChrgrSysCtrlEcho',
    'ChrgrSysFaultsTemp (0x274)': 'ChrgrSysFaultsTemp',
    'ChrgrSysLimits (0x615)': 'ChrgrSysLimits',
    'ChrgrSysSts (0x617)': 'ChrgrSysSts',
    'CMMInputValues (0x27D)': 'CMMInputValues',
    'CMMOutputValues (0x279)': 'CMMOutputValues',
    'CMMTempStatus (0x277)': 'CMMTempStatus',
    'BS_208h': 'ESC_BS_208',
    'MCM.Tempreature': 'MCM_Temperature',
    'EPS SAM_1': 'EPS_SAM_1',
    'EMS 3': 'EMS_3',
    'FCM 1': 'FCM_1',
    'BMS DCDCEnableSet': 'BMS_DCDCEnableSet',
    'BMS Faults': 'BMS_Faults',
    'BMS Version': 'BMS_Version',
    'CMS Cmd': 'CMS_Cmd',
    'CMM Limiting Info': 'CMM_LimitingInfo',
    'CMM Node Status': 'CMM_NodeStatus',
}


def sanitize_dbc_name(name):
    """Convert a LabVIEW label to a DBC-safe identifier."""
    if name in NAME_OVERRIDES:
        return NAME_OVERRIDES[name]
    # Remove units in parens: "HVInputCurrent (A)" -> "HVInputCurrent"
    name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
    # Replace spaces and special chars with underscore
    name = re.sub(r'[^A-Za-z0-9_]', '_', name)
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    # Strip leading/trailing underscores
    name = name.strip('_')
    # DBC names can't start with a digit
    if name and name[0].isdigit():
        name = '_' + name
    return name


def lv_type_comment(sig):
    """Generate a comment string describing the LabVIEW type for a signal."""
    lv_type = sig.get('lv_type', '')
    ti = sig.get('type_info', {})
    parts = [lv_type]
    bw = ti.get('bit_width')
    if bw:
        parts.append(f'{bw}bit')
    cat = ti.get('category', '')
    if cat:
        parts.append(cat)
    if 'enum_labels' in sig:
        parts.append('enum[' + ','.join(sig['enum_labels'][:4]) + ']')
    return ' '.join(parts)


def guess_signal_width(sig):
    """Guess the raw CAN signal bit width from LabVIEW type.
    Float64 signals are likely scaled from 8 or 16 bit raw values.
    Returns (bit_length, signed_char) for DBC format."""
    ti = sig.get('type_info', {})
    cat = ti.get('category', '')
    bw = ti.get('bit_width')

    if cat == 'boolean':
        return 1, '+'
    if cat == 'unsigned' and bw:
        return bw, '+'
    if cat == 'signed' and bw:
        return bw, '-'
    if cat == 'enum' and bw:
        return bw, '+'
    # float_lv: the actual CAN encoding is unknown, guess 8 bits unsigned
    if cat == 'float_lv':
        return 8, '+'
    if cat == 'string':
        return 0, '+'
    return 8, '+'


def flatten_cluster_signals(cluster):
    """Flatten nested cluster signals into a leaf-level list."""
    results = []
    for sig in cluster.get('signals', []):
        if 'signals' in sig:
            results.extend(flatten_cluster_signals(sig))
        else:
            results.append(sig)
    return results


def write_dbc(path, bus_label, messages, node_names):
    """Write a DBC file with the given messages."""
    lines = []
    lines.append('VERSION ""')
    lines.append('')
    lines.append('')
    lines.append('NS_ :')
    lines.append('')
    lines.append('BS_:')
    lines.append('')
    lines.append('BU_: ' + ' '.join(sorted(node_names)))
    lines.append('')
    lines.append('')

    comments = []
    placeholder_id = 0x1FFF

    for msg in messages:
        msg_name = msg['dbc_name']
        can_id = msg.get('can_id')
        sender = msg.get('sender', 'Vector__XXX')
        signals = msg.get('signals', [])
        id_source = msg.get('id_source', '')

        if can_id is None:
            can_id = placeholder_id
            placeholder_id += 1
            id_source = 'placeholder -- real ID unknown'

        dlc = 8

        lines.append(f'BO_ {can_id} {msg_name}: {dlc} {sender}')

        bit_offset = 0
        for sig in signals:
            sig_name = sanitize_dbc_name(sig.get('name', 'unknown'))
            if not sig_name:
                continue
            bit_len, sign_char = guess_signal_width(sig)
            if bit_len == 0:
                continue

            start_bit = bit_offset

            unit = ''
            label = sig.get('name', '')
            unit_match = re.search(r'\(([^)]+)\)\s*$', label)
            if unit_match:
                unit = unit_match.group(1)

            lines.append(f' SG_ {sig_name} : {start_bit}|{bit_len}@1{sign_char}'
                         f' (1,0) [0|0] "{unit}" Vector__XXX')

            type_comment = lv_type_comment(sig)
            if type_comment:
                comments.append((can_id, sig_name, f'LV: {type_comment}'))

            bit_offset += bit_len

        lines.append('')

        # Message comment
        parts = []
        if msg.get('source'):
            parts.append(f'source: {msg["source"]}')
        if id_source:
            parts.append(f'id: {id_source}')
        if parts:
            comments.append((can_id, None, '; '.join(parts)))

    # Comments section
    if comments:
        lines.append('')
        for can_id, sig_name, comment in comments:
            # Escape quotes in comment
            comment = comment.replace('"', "'")
            if sig_name:
                lines.append(f'CM_ SG_ {can_id} {sig_name} "{comment}";')
            else:
                lines.append(f'CM_ BO_ {can_id} "{comment}";')

    lines.append('')

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='ascii', errors='replace', newline='\n') as f:
        f.write('\n'.join(lines))

    known_count = sum(1 for m in messages if m.get('id_source', '') != 'placeholder -- real ID unknown'
                      and m.get('can_id') is not None)
    print(f'  {path}: {len(messages)} messages ({known_count} with known CAN IDs)')


def main():
    parser = argparse.ArgumentParser(
        description='Generate skeleton DBC files from LabVIEW signal inventory JSON'
    )
    parser.add_argument('json_file', help='Path to labview-signals.json')
    parser.add_argument('--b-can', required=True, help='Output path for B CAN skeleton DBC')
    parser.add_argument('--d-can', required=True, help='Output path for D CAN skeleton DBC')
    args = parser.parse_args()

    with open(args.json_file) as f:
        data = json.load(f)

    clusters = data.get('clusters', [])
    b_messages = []
    d_messages = []

    for cluster in clusters:
        name = cluster.get('name', '')

        if name in SKIP_CLUSTERS:
            continue

        dbc_name = sanitize_dbc_name(name)
        if not dbc_name:
            continue

        can_id = cluster.get('can_id')
        id_source = 'labview_cluster_name' if can_id else None

        if can_id is None and name in KNOWN_CAN_IDS:
            can_id = KNOWN_CAN_IDS[name]
            id_source = 'hardware_manual'
        if can_id is None and dbc_name in KNOWN_CAN_IDS:
            can_id = KNOWN_CAN_IDS[dbc_name]
            id_source = 'hardware_manual'

        flat_sigs = flatten_cluster_signals(cluster)
        if not flat_sigs:
            continue

        source_str = ', '.join(cluster.get('sources', []))

        msg = {
            'dbc_name': dbc_name,
            'can_id': can_id,
            'signals': flat_sigs,
            'sender': 'Vector__XXX',
            'source': f'labview_xml ({source_str})',
            'id_source': id_source,
        }

        if name in D_CAN_CLUSTERS:
            d_messages.append(msg)
        else:
            b_messages.append(msg)

    # Sort: known IDs first (ascending), then placeholders
    b_messages.sort(key=lambda m: (m['can_id'] is None, m.get('can_id') or 99999))
    d_messages.sort(key=lambda m: (m['can_id'] is None, m.get('can_id') or 99999))

    b_nodes = {'GWM', 'BMS', 'DCDC', 'ACCM', 'HVAC', 'IPK', 'CHM', 'CHS', 'SRS', 'TEM'}
    d_nodes = {'GWM', 'DLCM', 'TCM', 'ESC', 'EPS', 'RCU'}

    print('Generating skeleton DBCs from LabVIEW signal inventory...')
    write_dbc(args.b_can, 'B CAN', b_messages, b_nodes)
    write_dbc(args.d_can, 'D CAN', d_messages, d_nodes)


if __name__ == '__main__':
    main()
