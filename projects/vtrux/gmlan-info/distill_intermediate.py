#!/usr/bin/env python
"""
distill_intermediate.py

Reads a raw extraction JSON (output of extract_tables_local.py or
extract_tables_docling.py) and emits an intermediate JSON with correct
factor/offset values for all signals.  The intermediate JSON is human-editable;
edit it to correct signals then regenerate the DBC with generate_dbc_v2.py.

Fixes vs a naive approach:
  Bug A: Some signals have their formula in the 'range' field instead of
         'conversion'. This script checks both, with 'conversion' taking priority.
  Bug B: Parenthesized formulas like "E = (N x 1) - 40" were not matched by
         any regex in the original parser. This script handles them.

Usage:
    python distill_intermediate.py --input extracted.json --output intermediate.json
"""

import json
import re
import sys


# ---------------------------------------------------------------------------
# Formula parsing
# ---------------------------------------------------------------------------

def _norm(s):
    """Normalize formula string: replace Unicode multiply/minus signs with ASCII."""
    s = s.replace('\u00d7', 'x')   # Unicode multiplication sign -> x
    s = s.replace('*', 'x')        # asterisk multiply -> x
    s = s.replace('\u2212', '-')   # Unicode MINUS SIGN -> hyphen-minus
    s = s.replace('\u2013', '-')   # en-dash -> hyphen-minus
    s = s.replace('\u2014', '-')   # em-dash -> hyphen-minus
    return s


def parse_formula(s):
    """
    Parse a CAN spec conversion formula string into (factor, offset).

    Handles (in order):
      E = (N x factor) +/- offset   -- combined multiply + offset (parenthesized)
      E = N x factor +/- offset     -- combined multiply + offset (no parens)
      E = N x factor / divisor      -- ratio (e.g. N x 100/255)
      E = (N / divisor) +/- offset  -- division then offset
      E = N x factor                -- simple multiply
      E = N +/- offset              -- simple offset only

    Returns (factor, offset) as floats, or None if no formula found.
    """
    n = _norm(s)

    # Combined: E = (N x factor) +/- offset  OR  E = N x factor +/- offset
    # Factor can be a plain number or a parenthesized ratio like (1/16) or (100/255)
    m = re.search(
        r'E\s*=\s*\(?\s*N\s*x\s*\(?([0-9.]+)\s*/\s*([0-9.]+)\)?\s*\)?\s*([+-])\s*([0-9. ]+)',
        n, re.IGNORECASE
    )
    if m:
        factor = float(m.group(1)) / float(m.group(2))
        sign = m.group(3)
        offset_val = float(m.group(4).replace(' ', ''))
        offset = -offset_val if sign == '-' else offset_val
        return factor, offset

    m = re.search(
        r'E\s*=\s*\(?\s*N\s*x\s*([0-9.]+)\s*\)?\s*([+-])\s*([0-9. ]+)',
        n, re.IGNORECASE
    )
    if m:
        factor = float(m.group(1))
        sign = m.group(2)
        offset_val = float(m.group(3).replace(' ', ''))
        offset = -offset_val if sign == '-' else offset_val
        return factor, offset

    # Division then offset: E = (N / divisor) +/- offset
    m = re.search(
        r'E\s*=\s*\(?\s*N\s*/\s*([0-9.]+)\s*\)?\s*([+-])\s*([0-9. ]+)',
        n, re.IGNORECASE
    )
    if m:
        factor = 1.0 / float(m.group(1))
        sign = m.group(2)
        offset_val = float(m.group(3).replace(' ', ''))
        offset = -offset_val if sign == '-' else offset_val
        return factor, offset

    # Ratio: E = N x (numerator / denominator)  or  E = N x numerator / denominator
    m = re.search(
        r'E\s*=\s*N\s*x\s*\(?([0-9.]+)\s*/\s*([0-9.]+)\)?',
        n, re.IGNORECASE
    )
    if m:
        return float(m.group(1)) / float(m.group(2)), 0.0

    # Division only: E = N / divisor
    m = re.search(
        r'E\s*=\s*N\s*/\s*([0-9.]+)',
        n, re.IGNORECASE
    )
    if m:
        return 1.0 / float(m.group(1)), 0.0

    # Simple multiply: E = N x factor  (plain number, no offset)
    m = re.search(
        r'E\s*=\s*\(?\s*N\s*x\s*([0-9.]+)\s*\)?',
        n, re.IGNORECASE
    )
    if m:
        return float(m.group(1)), 0.0

    # Identity: E = N  (factor=1, offset=0)
    m = re.search(r'E\s*=\s*N\s*$', n, re.IGNORECASE)
    if m:
        return 1.0, 0.0

    # Simple offset: E = N +/- offset
    m = re.search(
        r'E\s*=\s*N\s*([+-])\s*([0-9. ]+)',
        n, re.IGNORECASE
    )
    if m:
        sign = m.group(1)
        offset_val = float(m.group(2).replace(' ', ''))
        return 1.0, (-offset_val if sign == '-' else offset_val)

    return None  # no formula found


def parse_enum(s):
    """
    Parse an enumeration string like '$0 = Value A; $1 = Value B' into a
    dict {int: str}.  Returns None if the string is not an enumeration.
    """
    if '$' not in s:
        return None
    result = {}
    for part in s.split('$'):
        part = part.strip().rstrip(';').strip()
        if not part:
            continue
        if '=' not in part:
            continue
        val_str, _, desc = part.partition('=')
        val_str = val_str.strip()
        desc = desc.strip()
        try:
            if len(val_str) == 1 and val_str.upper() in 'ABCDEF':
                val = int(val_str, 16)
            elif val_str.startswith('0x') or val_str.startswith('0X'):
                val = int(val_str, 16)
            else:
                val = int(val_str)
            result[val] = desc
        except ValueError:
            pass
    return result if result else None


# ---------------------------------------------------------------------------
# Unit extraction
# ---------------------------------------------------------------------------

_UNIT_PATTERNS = [
    (r'%',              '%'),
    (r'\u00b0C|degC|deg C|\u00b0 C', 'degC'),   # degree C variants
    (r'\bNm\b|N\u00b7m|N\.m',       'Nm'),
    (r'\bkPa\b',        'kPa'),
    (r'\bkPa.g\b',      'kPa_g'),
    (r'\brpm\b',        'rpm'),
    (r'\bkm/h\b',       'km/h'),
    (r'\bm/s\s*2\b',    'm/s2'),
    (r'\bdegrees/s\b',  'deg/s'),
    (r'\bdegrees\b',    'deg'),
    (r'\bg/s\b',        'g/s'),
    (r'\bkW\b',         'kW'),
    (r'\bliters\b|\bL\b', 'L'),
    (r'\bL/hr\b',       'L/hr'),
    (r'\bkm\b',         'km'),
    (r'\bm\b',          'm'),
    (r'\bminutes\b',    'min'),
    (r'\bcounts\b|\bcount\b', 'counts'),
    (r'\bkg\b',         'kg'),
    (r'\bmm\b',         'mm'),
    (r'\bpassword\b',   ''),
]


def extract_unit(range_str):
    if not range_str or range_str == 'N/A':
        return ''
    for pattern, unit in _UNIT_PATTERNS:
        if re.search(pattern, range_str, re.IGNORECASE):
            return unit
    return ''


# ---------------------------------------------------------------------------
# Main distillation
# ---------------------------------------------------------------------------

def resolve_formula(sig):
    """
    Determine factor and offset for a signal, checking both 'conversion' and
    'range' fields.  Returns (factor, offset, enum_values).
    """
    conversion = sig.get('conversion', '')
    range_str = sig.get('range', '')

    # Check for enum in conversion field first
    if conversion and '$' in conversion:
        enum = parse_enum(conversion)
        return 1.0, 0.0, enum, False

    # Check for enum in range field
    if range_str and '$' in range_str:
        enum = parse_enum(range_str)
        return 1.0, 0.0, enum, False

    # Try to find a numeric formula -- conversion field takes priority
    for candidate in (conversion, range_str):
        if not candidate or candidate == 'N/A':
            continue
        result = parse_formula(candidate)
        if result is not None:
            return result[0], result[1], None, False

    # Formula text present but nothing parsed -- genuine warning case
    has_formula_text = any(
        'E =' in s or 'E=' in s
        for s in (conversion, range_str) if s and s != 'N/A'
    )
    return 1.0, 0.0, None, has_formula_text


def distill(input_path, output_path):
    print(f"Reading: {input_path}")
    with open(input_path, encoding='utf-8') as f:
        data = json.load(f)

    raw_messages = data['messages']
    out_messages = {}

    no_formula = []   # signals where we found no formula at all (may be intentional)

    for msg_id in sorted(raw_messages.keys(), key=lambda x: int(x, 16)):
        msg = raw_messages[msg_id]
        out_signals = []

        for sig in msg.get('signals', []):
            factor, offset, enum_values, unparsed = resolve_formula(sig)

            if unparsed:
                no_formula.append({
                    'msg': msg_id,
                    'signal': sig['name'],
                    'conversion': sig.get('conversion', ''),
                    'range': sig.get('range', ''),
                })

            unit = extract_unit(sig.get('range', ''))

            max_raw = (2 ** sig['length']) - 1

            out_signals.append({
                'signal_name':  sig['name'],
                'start_byte':   sig['start_byte'],
                'start_bit':    sig['start_bit'],
                'length':       sig['length'],
                'data_type':    sig['data_type'],
                'factor':       factor,
                'offset':       offset,
                'min_raw':      0,
                'max_raw':      max_raw,
                'unit':         unit,
                'enum_values':  enum_values,
                'notes':        '',
            })

        out_messages[msg_id] = {
            'message_id':   msg_id,
            'message_name': msg['name'],
            'transmitter':  msg.get('transmitter', ''),
            'signals':      out_signals,
        }

    output = {'messages': out_messages}

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Written: {output_path}")
    print(f"  Messages: {len(out_messages)}")
    total_signals = sum(len(m['signals']) for m in out_messages.values())
    print(f"  Signals:  {total_signals}")

    # Report signals where formula text was present but unparsed
    if no_formula:
        print(f"\nWARNING: {len(no_formula)} signal(s) had formula text that could not be parsed:")
        for item in no_formula:
            print(f"  {item['msg']} {item['signal']}")
            print(f"    conversion: {repr(item['conversion'])}")
            print(f"    range:      {repr(item['range'])}")
    else:
        print("\nAll formula strings parsed successfully.")

    # Print all signals with non-trivial factor/offset for spot-check
    print("\n--- Signals with non-default factor or offset (spot-check list) ---")
    for msg_id, msg in sorted(out_messages.items(), key=lambda x: int(x[0], 16)):
        for sig in msg['signals']:
            if sig['factor'] != 1.0 or sig['offset'] != 0.0:
                f = sig['factor']
                o = sig['offset']
                print(f"  {msg_id} {msg['message_name']}: {sig['signal_name']}")
                print(f"    factor={f}, offset={o}, unit={repr(sig['unit'])}")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description="Distill raw extraction JSON to intermediate JSON.")
    p.add_argument("--input",  required=True, help="Path to raw extraction JSON.")
    p.add_argument("--output", required=True, help="Output intermediate JSON path.")
    args = p.parse_args()
    distill(args.input, args.output)
