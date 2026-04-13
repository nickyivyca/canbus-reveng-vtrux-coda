"""
make_graph.py -- Generate SavvyCAN Graph Definition (.gdf) files from DBC signals.

Usage:
    py -3.12 tools/make_graph.py --dbc PATH [PATH ...] --signal MSG.signal [MSG.signal ...]
                                  [--output PATH] [--append] [--stride N] [--line-width N]

Multiple DBCs are searched in order; first match wins. Use --append to add signals to
an existing .gdf file across multiple tool runs (color cycling continues from the last
signal already in the file).

Examples:
    # Create a new .gdf with signals from the main DBC
    py -3.12 tools/make_graph.py \\
        --dbc projects/vtrux/vtrux.dbc \\
        --signal BELINV_hvBatteryAndCharger.BELINV_hvBatteryVoltage \\
                 BELINV_hvBatteryAndCharger.BELINV_hvBatteryCurrent \\
        --output projects/vtrux/notes/artifacts/bel_voltage_current.gdf

    # Append a signal from a second DBC (e.g. GMLAN or provisional)
    py -3.12 tools/make_graph.py \\
        --dbc projects/vtrux/gmlan.dbc projects/vtrux/provisional.dbc \\
        --signal SomeMsg.SomeSignal \\
        --output projects/vtrux/notes/artifacts/bel_voltage_current.gdf --append
"""

import argparse
import contextlib
import io
import os
import re
import sys

try:
    import cantools
except ImportError:
    print("ERROR: cantools not installed. Run: pip install cantools")
    sys.exit(1)

_EXTENDED_BIT = 0x80000000
_BO_RE = re.compile(r'^(BO_ )(\d+)( )', re.MULTILINE)


def _fix_extended_ids(dbc_text):
    """
    Some DBC files store 29-bit extended CAN IDs without the 0x80000000 marker
    that cantools requires. Detect IDs > 0x7FF in BO_ lines and OR in the bit.
    """
    def _fix(m):
        raw_id = int(m.group(2))
        if raw_id > 0x7FF and not (raw_id & _EXTENDED_BIT):
            raw_id |= _EXTENDED_BIT
        return m.group(1) + str(raw_id) + m.group(3)
    return _BO_RE.sub(_fix, dbc_text)

# 8-color palette cycled per signal across all runs (append-aware)
COLORS = [
    (31, 119, 180),    # blue
    (255, 127, 14),    # orange
    (44, 160, 44),     # green
    (214, 39, 40),     # red
    (148, 103, 189),   # purple
    (140, 86, 75),     # brown
    (227, 119, 194),   # pink
    (127, 127, 127),   # gray
]


def fmt_value(v):
    """Format scale/offset: int if whole number, float otherwise."""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def make_gdf_line(msg, signal, color, stride=1, line_width=1):
    """Return one .gdf line for the given signal."""
    r, g, b = color

    # Field 5: Y = signed, N = unsigned.
    # Endianness is encoded in the sign of the start bit:
    #   positive start -> LE (Intel): start = cantools start (LSB bit position)
    #   negative start -> BE (Motorola): start = -(cantools Motorola MSB position)
    # Verified against SavvyCAN-exported GDFs and cell graph (1).gdf BE examples.
    signed = 'Y' if signal.is_signed else 'N'

    if signal.byte_order == 'little_endian':
        start = signal.start           # positive: Intel LSB position
    else:
        start = -signal.start          # negative: -(Motorola MSB position)

    bias = fmt_value(signal.offset)
    scale = fmt_value(signal.scale)
    id_hex = '{:x}'.format(msg.frame_id)
    label = signal.name
    msg_name = msg.name

    fields = [
        'Z',
        id_hex,
        'ffffffff',
        str(start),
        str(signal.length),
        signed,
        bias,
        scale,
        str(stride),
        '-1',
        str(r),
        str(g),
        str(b),
        label,
        '128',
        '128',
        '128',
        '0',
        'N',
        '0',
        str(line_width),
        msg_name,
        label,
    ]
    return ','.join(fields)


def count_existing_signals(gdf_path):
    """Return the number of signal lines already in the .gdf file (for color offset)."""
    if not os.path.exists(gdf_path):
        return 0
    count = 0
    with open(gdf_path, 'r', encoding='ascii', errors='replace') as f:
        for line in f:
            line = line.strip()
            if line.startswith('Z,'):
                count += 1
    return count


def load_dbcs(dbc_paths):
    """Load one or more DBC files. Returns list of (path, db) tuples."""
    dbs = []
    for path in dbc_paths:
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
            text = _fix_extended_ids(text)
            # Suppress cantools "Overwriting message" chatter on noisy DBCs
            _sink = io.StringIO()
            with contextlib.redirect_stdout(_sink), contextlib.redirect_stderr(_sink):
                db = cantools.database.load_string(text, database_format='dbc', strict=False)
            dbs.append((path, db))
        except Exception as e:
            print('ERROR loading DBC "{}": {}'.format(path, e))
    return dbs


def find_signal(dbs, msg_name, sig_name):
    """
    Search dbs in order for msg_name.sig_name.
    msg_name may be a message name (e.g. 'Engine_General_Status_1') or a hex frame ID
    prefixed with '0x' (e.g. '0x3E9') for disambiguation when a name is duplicated.
    Returns (dbc_path, msg, signal) for the first match, or (None, None, None).
    """
    for dbc_path, db in dbs:
        # Support hex ID lookup: 0x3E9.Signal_Name
        if msg_name.lower().startswith('0x'):
            try:
                frame_id = int(msg_name, 16)
                msg = db.get_message_by_frame_id(frame_id)
            except (ValueError, KeyError):
                continue
        else:
            try:
                msg = db.get_message_by_name(msg_name)
            except KeyError:
                continue
        for s in msg.signals:
            if s.name == sig_name:
                return dbc_path, msg, s
    return None, None, None


def main():
    parser = argparse.ArgumentParser(
        description='Generate a SavvyCAN .gdf graph definition file from DBC signals.'
    )
    parser.add_argument('--dbc', required=True, nargs='+', metavar='PATH',
                        help='DBC file(s) to search for signals (searched in order, first match wins)')
    parser.add_argument('--signal', required=True, nargs='+', metavar='MSG.signal',
                        help='Signal(s) as MessageName.signal_name')
    parser.add_argument('--output', metavar='PATH', default='graph_output.gdf',
                        help='Output .gdf file (default: graph_output.gdf)')
    parser.add_argument('--append', action='store_true',
                        help='Append to existing .gdf instead of overwriting; '
                             'color cycling continues from the last signal already in the file')
    parser.add_argument('--stride', type=int, default=1, metavar='N',
                        help='Plot every Nth point (default: 1)')
    parser.add_argument('--line-width', type=int, default=1, metavar='N',
                        help='Line width in pixels (default: 1)')
    args = parser.parse_args()

    # Load all DBCs
    dbs = load_dbcs(args.dbc)
    if not dbs:
        print('ERROR: no DBC files could be loaded.')
        sys.exit(1)

    if len(dbs) < len(args.dbc):
        print('WARNING: {}/{} DBC(s) failed to load and will be skipped.'.format(
            len(args.dbc) - len(dbs), len(args.dbc)))

    # Color offset: if appending, count signals already in the file
    color_offset = count_existing_signals(args.output) if args.append else 0
    if args.append and color_offset:
        print('Appending to {} ({} existing signal(s), color offset {})'.format(
            args.output, color_offset, color_offset))

    lines = []
    errors = 0

    for idx, spec in enumerate(args.signal):
        if '.' not in spec:
            print('ERROR: signal spec must be MessageName.signal_name, got: {}'.format(spec))
            errors += 1
            continue

        msg_name, sig_name = spec.split('.', 1)

        dbc_path, msg, signal = find_signal(dbs, msg_name, sig_name)
        if signal is None:
            searched = ', '.join(p for p, _ in dbs)
            print('ERROR: "{}" not found in any loaded DBC ({})'.format(spec, searched))
            errors += 1
            continue

        color = COLORS[(color_offset + idx) % len(COLORS)]
        line = make_gdf_line(msg, signal, color, stride=args.stride, line_width=args.line_width)
        lines.append(line)
        gdf_start = signal.start if signal.byte_order == 'little_endian' else -signal.start
        print('  + {} [from {}] (ID {:x}, gdf_start={}, len={}, {}, {}, bias={}, scale={})'.format(
            spec,
            os.path.basename(dbc_path),
            msg.frame_id,
            gdf_start,
            signal.length,
            'LE' if signal.byte_order == 'little_endian' else 'BE',
            'signed' if signal.is_signed else 'unsigned',
            signal.offset,
            signal.scale,
        ))

    if errors and not lines:
        sys.exit(1)

    mode = 'a' if args.append else 'w'
    with open(args.output, mode, encoding='ascii') as f:
        for line in lines:
            f.write(line + '\n')

    action = 'Appended' if args.append else 'Wrote'
    print('{} {} signal(s) to {}'.format(action, len(lines), args.output))
    if errors:
        print('WARNING: {} signal(s) had errors and were skipped.'.format(errors))


if __name__ == '__main__':
    main()
