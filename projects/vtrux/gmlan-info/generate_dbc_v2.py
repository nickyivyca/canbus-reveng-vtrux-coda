#!/usr/bin/env python
"""
generate_dbc_v2.py

Generates a DBC file from an intermediate JSON produced by distill_intermediate.py.

Usage:
    python generate_dbc_v2.py --input intermediate.json --output out.dbc
    python generate_dbc_v2.py --input intermediate.json --output out.dbc --version "My Spec v1"

Signal naming rules applied during generation:
  1. PKT (packet) signals are dropped. The GMLAN spec defines both a named
     32-bit composite signal and its constituent sub-fields occupying the same
     bits. Emitting both causes cantools to reject the file with an overlap
     error. The sub-fields are more useful, so the PKT wrapper is discarded.
  2. For messages with left/right wheel-half structure (two PKT signals whose
     names contain 'left' and 'right'), non-PKT sub-signals are prefixed with
     'L_' or 'R_' based on which byte half they occupy. This replaces the
     previous blind '_2' suffix deduplication for these messages.
  3. Signals with empty names (blanked-out rows in the PDF) are skipped entirely.
  4. Any remaining name collisions within a message (rare after the above) are
     resolved with a '_2', '_3', ... suffix counter as a safety net.
"""

import json
import re
import os

# Map non-ASCII characters to ASCII stand-ins for DBC string fields.
_NON_ASCII_REPLACEMENTS = [
    ('\xbd', '1/2'),  # U+00BD VULGAR FRACTION ONE HALF (e.g. "Flashing 1/2 Hertz")
]


def ascii_safe(text):
    """Replace known non-ASCII characters with ASCII equivalents."""
    for char, replacement in _NON_ASCII_REPLACEMENTS:
        text = text.replace(char, replacement)
    return text


def sanitize_name(name):
    """Sanitize a signal/message name for DBC format."""
    if not name:
        return ''
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')
    if name and name[0].isdigit():
        name = 'SG_' + name
    return name


def get_wheel_side_prefixes(signals):
    """
    If a message has exactly two PKT signals whose names contain 'left' and
    'right', return a dict mapping signal index -> 'L_' or 'R_' for every
    non-PKT signal, based on which byte half it falls in.
    Otherwise return an empty dict.
    """
    pkt_sigs = [(i, s) for i, s in enumerate(signals) if s.get('data_type') == 'PKT']
    if len(pkt_sigs) < 2:
        return {}

    left_pkts = [(i, s) for i, s in pkt_sigs if 'left' in s['signal_name'].lower()]
    right_pkts = [(i, s) for i, s in pkt_sigs if 'right' in s['signal_name'].lower()]
    if not left_pkts or not right_pkts:
        return {}

    left_byte = left_pkts[0][1]['start_byte']
    right_byte = right_pkts[0][1]['start_byte']
    boundary = (left_byte + right_byte) // 2 + 1  # e.g. 4 when halves start at 0 and 4

    result = {}
    for i, s in enumerate(signals):
        if s.get('data_type') != 'PKT':
            result[i] = 'L_' if s['start_byte'] < boundary else 'R_'
    return result


def generate_dbc(intermediate_path, output_path, version=""):
    print(f"Reading: {intermediate_path}")
    with open(intermediate_path, encoding='utf-8') as f:
        data = json.load(f)

    messages = data['messages']
    print(f"Generating DBC for {len(messages)} messages...")

    lines = []

    # --- Header ---
    lines.append(f'VERSION "{version}"')
    lines.append('')
    lines.append('NS_ :')
    for ns in ('NS_DESC_', 'CM_', 'BA_DEF_', 'BA_', 'VAL_', 'CAT_DEF_', 'CAT_',
               'FILTER', 'BA_DEF_DEF_', 'EV_DATA_', 'ENVVAR_DATA_', 'SGTYPE_',
               'SGTYPE_VAL_', 'BA_DEF_SGTYPE_', 'BA_SGTYPE_', 'SIG_TYPE_REF_',
               'VAL_TABLE_', 'SIG_GROUP_', 'SIG_VALTYPE_', 'SIGTYPE_VALTYPE_',
               'BO_TX_BU_', 'BA_DEF_REL_', 'BA_REL_', 'BA_SGTYPE_REL_',
               'SG_MUL_VAL_'):
        lines.append(f'\t{ns}')
    lines.append('')
    lines.append('BS_:')
    lines.append('')

    # --- Node list ---
    transmitters = set()
    for msg in messages.values():
        tx = msg.get('transmitter', '').strip()
        if tx:
            for t in tx.split(','):
                t = t.strip()
                if t:
                    transmitters.add(sanitize_name(t))
    transmitters.discard('')
    lines.append('BU_: ' + ' '.join(sorted(transmitters)))
    lines.append('')

    # --- Messages and signals ---
    value_tables = {}   # (msg_id_int, sig_name) -> {int: str}
    total_pkt_dropped = 0
    total_signals_written = 0

    for msg_id in sorted(messages.keys(), key=lambda x: int(x, 16)):
        msg = messages[msg_id]
        msg_id_int = int(msg_id, 16)
        msg_name = sanitize_name(msg['message_name']) or 'MSG_{:03X}'.format(msg_id_int)

        tx = msg.get('transmitter', '').strip()
        transmitter = sanitize_name(tx.split(',')[0].strip()) if tx else 'XXX'
        transmitter = transmitter or 'XXX'

        lines.append(f'BO_ {msg_id_int} {msg_name}: 8 {transmitter}')

        wheel_prefixes = get_wheel_side_prefixes(msg['signals'])
        used_names = set()

        def fmt(v):
            if v == int(v):
                return str(int(v))
            return f'{v:.6g}'

        for idx, sig in enumerate(msg['signals']):
            # Fix 1: drop PKT composite signals -- they overlap their own sub-fields
            if sig.get('data_type') == 'PKT':
                total_pkt_dropped += 1
                continue

            raw_name = sig['signal_name']

            # Fix 3: skip blanked-out rows (no name = no signal)
            if not raw_name.strip():
                continue
            sig_name = sanitize_name(raw_name)

            # Fix 2: apply L_/R_ prefix for left/right wheel-half messages
            if idx in wheel_prefixes:
                sig_name = wheel_prefixes[idx] + sig_name

            # Safety-net dedup for any remaining collisions
            if sig_name in used_names:
                counter = 2
                while f'{sig_name}_{counter}' in used_names:
                    counter += 1
                sig_name = f'{sig_name}_{counter}'
            used_names.add(sig_name)

            # DBC Motorola start bit = byte * 8 + bit_within_byte
            # (start_bit in intermediate is the MSB position, 7=MSB of byte)
            start_bit_dbc = sig['start_byte'] * 8 + sig['start_bit']
            length = sig['length']
            factor = sig['factor']
            offset = sig['offset']
            unit = sig.get('unit', '')

            min_phys = sig['min_raw'] * factor + offset
            max_phys = sig['max_raw'] * factor + offset

            line = (
                f' SG_ {sig_name} : {start_bit_dbc}|{length}@0+ '
                f'({fmt(factor)},{fmt(offset)}) '
                f'[{fmt(min_phys)}|{fmt(max_phys)}] '
                f'"{unit}" Vector__XXX'
            )
            lines.append(line)
            total_signals_written += 1

            if sig.get('enum_values'):
                value_tables[(msg_id_int, sig_name)] = sig['enum_values']

        lines.append('')

    # --- Message comments ---
    lines.append('')
    for msg_id in sorted(messages.keys(), key=lambda x: int(x, 16)):
        msg = messages[msg_id]
        msg_id_int = int(msg_id, 16)
        comment = msg['message_name'].replace('"', '\\"')
        lines.append(f'CM_ BO_ {msg_id_int} "{comment}";')

    lines.append('')

    # --- Value tables ---
    for (msg_id_int, sig_name), vt in sorted(value_tables.items()):
        entries = ' '.join(f'{k} "{ascii_safe(v)}"' for k, v in sorted(vt.items()))
        lines.append(f'VAL_ {msg_id_int} {sig_name} {entries} ;')

    lines.append('')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    total_signals_in = sum(len(m['signals']) for m in messages.values())
    print(f"Written: {output_path}")
    print(f"  Messages:       {len(messages)}")
    print(f"  Signals in JSON:{total_signals_in}")
    print(f"  PKT dropped:    {total_pkt_dropped}")
    print(f"  Signals written:{total_signals_written}")
    print(f"  Value tables:   {len(value_tables)}")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description="Generate a DBC file from an intermediate JSON.")
    p.add_argument("--input",   required=True, help="Path to intermediate JSON.")
    p.add_argument("--output",  required=True, help="Output DBC file path.")
    p.add_argument("--version", default="",   help="VERSION string to embed in the DBC (default: empty).")
    args = p.parse_args()
    generate_dbc(args.input, args.output, version=args.version)
