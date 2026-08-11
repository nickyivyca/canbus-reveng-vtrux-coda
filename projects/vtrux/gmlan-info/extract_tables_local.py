#!/usr/bin/env python3
"""
Extract CAN signal tables from a spec PDF using pdfplumber.
100% local processing, no API calls needed.

Usage:
    python extract_tables_local.py --pdf spec.pdf --start-page 228 --end-page 269
    python extract_tables_local.py --pdf spec.pdf --start-page 228 --end-page 269 \\
        --output my_extracted.json \\
        --name-prefix "PPEI|PTEI" \\
        --debug
"""

import pdfplumber
import json
import re

def clean_cell_text(text):
    """Clean up text from table cells."""
    if text is None:
        return ""
    # Remove extra whitespace
    text = ' '.join(text.split())
    return text.strip()

def parse_message_id(text):
    """Extract message ID from text (e.g., '$1F5' -> '0x1F5')."""
    match = re.search(r'\$([0-9A-Fa-f]{2,4})', text)
    if match:
        return f'0x{match.group(1).upper()}'
    return None

# Default column layout (most pages)
_DEFAULT_LAYOUT = {
    'id_col':           1,
    'signal_col':       5,
    'byte_col':         6,
    'bit_col':          7,
    'length_col':       8,
    'data_type_col':    9,
    'range_col':        12,
    'conversion_col':   13,
    'transmitter_col':  14,
}

def detect_column_layout(table):
    """
    Scan the first few rows of a table for the header row and detect column
    indices dynamically.

    CAN spec tables typically have a header row with cells such as 'Message', 'ID',
    'Signal', 'Range', 'Conversion', 'Transmitter'.  pdfplumber renders this
    differently across pages depending on how it splits merged cells, so the
    column indices shift.  Reading them from the header row on each page means
    we always use the right offsets regardless of the shift.

    Start Byte / Start Bit / Length / Data Type are the four columns immediately
    after 'Signal' -- that relationship is constant even when the absolute index
    shifts.

    Column positions are accumulated across all scanned rows so that headers
    split across multiple rows (e.g. page 269 first table) are still detected.

    Returns a layout dict.  Falls back to _DEFAULT_LAYOUT if detection fails.
    """
    id_col = None
    signal_col = None
    range_col = None
    conversion_col = None
    transmitter_col = None

    for row in table[:4]:
        cells = [clean_cell_text(c) for c in row]
        for i, cell in enumerate(cells):
            if cell == 'ID' and id_col is None:
                id_col = i
            elif cell == 'Signal' and signal_col is None:
                signal_col = i
            elif cell == 'Range' and range_col is None:
                range_col = i
            elif cell == 'Conversion' and conversion_col is None:
                conversion_col = i
            elif cell == 'Transmitter' and transmitter_col is None:
                transmitter_col = i

        if id_col is not None and signal_col is not None:
            break

    if id_col is not None and signal_col is not None:
        return {
            'id_col':           id_col,
            'signal_col':       signal_col,
            'byte_col':         signal_col + 1,
            'bit_col':          signal_col + 2,
            'length_col':       signal_col + 3,
            'data_type_col':    signal_col + 4,
            'range_col':        range_col        if range_col        is not None else signal_col + 7,
            'conversion_col':   conversion_col   if conversion_col   is not None else signal_col + 8,
            'transmitter_col':  transmitter_col  if transmitter_col  is not None else signal_col + 9,
        }

    return _DEFAULT_LAYOUT.copy()

def process_gmlan_table_row(row, current_message_id, current_message_name,
                            current_transmitter, layout, name_prefix_re=None):
    """
    Process a single row from a CAN spec table using the supplied column layout
    (detected per-page from the header row).

    name_prefix_re: compiled regex with one capture group that strips a
    spec-specific prefix from message names (e.g. compiled 'PPEI|PTEI').
    Pass None to use the full cell text as-is.

    current_transmitter is carried as state because the transmitter cell is a
    merged PDF cell spanning all signal rows for a message.  pdfplumber places
    the value only in the row where the message ID appears; subsequent signal
    rows for that message have an empty transmitter cell.  Tracking it as state
    ensures it is applied to all signals for the message.

    Returns: (signal_dict_or_None, new_message_id, new_message_name,
              new_current_transmitter)
    """
    cells = [clean_cell_text(cell) for cell in row]

    id_col          = layout['id_col']
    signal_col      = layout['signal_col']
    byte_col        = layout['byte_col']
    bit_col         = layout['bit_col']
    length_col      = layout['length_col']
    data_type_col   = layout['data_type_col']
    range_col       = layout['range_col']
    conversion_col  = layout['conversion_col']
    transmitter_col = layout['transmitter_col']

    def get(col):
        return cells[col] if len(cells) > col else ''

    # Check if this row defines a new message (message ID in the detected ID column)
    msg_id = parse_message_id(get(id_col)) if get(id_col) else None
    if msg_id:
        current_message_id = msg_id
        # Message name is always in column 0.
        # Some messages carry a spec-specific prefix (stripped via name_prefix_re);
        # others use a plain name.  Fall back to the raw cell text so we never
        # silently carry the previous message's name forward.
        if cells[0]:
            name_text = cells[0].strip().replace('\n', ' ')
            # Normalize pdfplumber underscore-space artifacts ("Vehicle_ Odometer_HS")
            name_text = re.sub(r'_\s+', '_', name_text)
            if name_prefix_re:
                prefix_match = name_prefix_re.search(name_text)
                if prefix_match:
                    current_message_name = prefix_match.group(1).strip()
                else:
                    current_message_name = name_text
            else:
                current_message_name = name_text
        # Capture transmitter from the message ID row (merged cell — only present here)
        tx = get(transmitter_col)
        if tx:
            current_transmitter = tx

    # Extract signal data (byte, bit, length must all be present and integer)
    signal = None
    if get(byte_col) and get(bit_col) and get(length_col):
        try:
            byte_val   = int(get(byte_col))
            bit_val    = int(get(bit_col))
            # Length cell occasionally merges with the data type column
            # (e.g. "1 UBYTE") — take just the leading integer token
            length_val = int(get(length_col).split()[0])

            sig_name = get(signal_col).replace('\n', ' ')

            # Skip rows that look like table header/period artefacts
            if not sig_name.replace('.', '').isdigit():
                signal = {
                    'message_id':   current_message_id,
                    'message_name': current_message_name,
                    'signal_name':  sig_name,
                    'start_byte':   byte_val,
                    'start_bit':    bit_val,
                    'length':       length_val,
                    'data_type':    get(data_type_col) or 'UNK',
                    'range':        get(range_col),
                    'conversion':   get(conversion_col),
                    'transmitter':  current_transmitter,
                }
        except (ValueError, IndexError):
            # byte_col may contain overflowed signal name text — detect by checking
            # whether the next column (bit_col) holds a valid integer instead
            try:
                bit_val    = int(get(bit_col))
                length_val = int(get(length_col).split()[0])

                # Columns shifted right by 1: signal name bled into byte_col
                overflow_text = get(byte_col)
                # If overflow starts lowercase it is a mid-word split at the cell
                # boundary — join without separator.  Otherwise treat as word break.
                sep = '' if (overflow_text and overflow_text[0].islower()) else ' '
                sig_name = (get(signal_col) + sep + overflow_text).strip().replace('\n', ' ')
                # pdfplumber sometimes renders a single capital letter separated from
                # the rest of its word by a space (e.g. "T hrottle" -> "Throttle").
                # This pattern never appears legitimately in spec signal names.
                sig_name = re.sub(r'([A-Z]) ([a-z])', r'\1\2', sig_name)

                # Shift the remaining columns right by 1
                shifted_byte      = int(get(bit_col))
                shifted_bit       = int(get(length_col).split()[0])
                shifted_length    = int(get(data_type_col).split()[0])
                shifted_data_type = get(range_col) or 'UNK'
                shifted_range     = get(conversion_col)
                shifted_conv      = get(transmitter_col)

                if sig_name and not sig_name.replace('.', '').isdigit():
                    signal = {
                        'message_id':   current_message_id,
                        'message_name': current_message_name,
                        'signal_name':  sig_name,
                        'start_byte':   shifted_byte,
                        'start_bit':    shifted_bit,
                        'length':       shifted_length,
                        'data_type':    shifted_data_type,
                        'range':        shifted_range,
                        'conversion':   shifted_conv,
                        'transmitter':  current_transmitter,
                    }
            except (ValueError, IndexError):
                pass

    return signal, current_message_id, current_message_name, current_transmitter

def extract_gmlan_frames(pdf_path, start_page=1, end_page=None, name_prefix='',
                         debug_output='table_extraction_debug.txt'):
    """
    Extract CAN signal tables from a spec PDF.

    Args:
        pdf_path:    Path to the PDF file.
        start_page:  First page to extract (1-indexed, default 1).
        end_page:    Last page to extract (1-indexed, inclusive).
                     Defaults to the last page of the document.
        name_prefix: Regex for spec-specific prefixes to strip from message names
                     (e.g. 'PPEI|PTEI').  Empty string means no stripping.

    Returns:
        List of extracted signal dicts.
    """
    name_prefix_re = re.compile(
        r'(?:' + name_prefix + r')[:\s]+(.+)', re.IGNORECASE
    ) if name_prefix else None

    print(f"Opening PDF: {pdf_path}")
    print(f"Extracting pages {start_page}-{end_page}...")

    all_signals = []
    current_message_id = None
    current_message_name = None
    current_transmitter = None
    debug_data = []

    with pdfplumber.open(pdf_path) as pdf:
        last_page = len(pdf.pages)
        if end_page is None:
            end_page = last_page
        for page_num in range(start_page - 1, end_page):
            if page_num >= len(pdf.pages):
                break

            page = pdf.pages[page_num]
            print(f"\nPage {page_num + 1}...")

            tables = page.extract_tables()
            print(f"  Found {len(tables)} tables")

            for table_idx, table in enumerate(tables):
                print(f"  Table {table_idx + 1}: {len(table)} rows")

                # Detect column layout from this page's header row
                layout = detect_column_layout(table)

                # Save first page's first table for debugging
                if page_num == start_page - 1 and table_idx == 0:
                    debug_data.append({'page': page_num + 1, 'table': table, 'layout': layout})

                for row in table:
                    signal, current_message_id, current_message_name, current_transmitter = \
                        process_gmlan_table_row(
                            row, current_message_id, current_message_name,
                            current_transmitter, layout, name_prefix_re
                        )
                    if signal:
                        all_signals.append(signal)
                        if len(all_signals) % 10 == 0:
                            print(f"    Extracted {len(all_signals)} signals so far...")

    print(f"\n{'='*80}")
    print(f"Total signals extracted: {len(all_signals)}")

    # Save debug data
    with open(debug_output, 'w', encoding='utf-8') as f:
        f.write("First page table data:\n")
        f.write("=" * 80 + "\n\n")
        if debug_data:
            entry = debug_data[0]
            f.write(f"Detected layout: {entry['layout']}\n\n")
            for row_idx, row in enumerate(entry['table']):
                f.write(f"Row {row_idx}:\n")
                for col_idx, cell in enumerate(row):
                    f.write(f"  Col {col_idx}: {repr(cell)}\n")
                f.write("\n")

    return all_signals

def group_signals_by_message(signals):
    """Group signals by message ID."""

    messages = {}

    for signal in signals:
        msg_id = signal['message_id']
        if not msg_id:
            continue

        if msg_id not in messages:
            messages[msg_id] = {
                'id':           msg_id,
                'name':         signal['message_name'],
                'transmitter':  signal['transmitter'],
                'signals':      []
            }
        elif not messages[msg_id]['transmitter'] and signal['transmitter']:
            messages[msg_id]['transmitter'] = signal['transmitter']

        messages[msg_id]['signals'].append({
            'name':       signal['signal_name'],
            'start_byte': signal['start_byte'],
            'start_bit':  signal['start_bit'],
            'length':     signal['length'],
            'data_type':  signal['data_type'],
            'range':      signal['range'],
            'conversion': signal['conversion'],
        })

    return messages

def main():
    import argparse
    import os
    p = argparse.ArgumentParser(
        description="Extract CAN signal tables from a spec PDF using pdfplumber."
    )
    p.add_argument("--pdf", required=True, help="Path to the input PDF.")
    p.add_argument("--start-page", type=int, required=True,
                   help="First page to extract (1-indexed).")
    p.add_argument("--end-page", type=int, required=True,
                   help="Last page to extract (1-indexed, inclusive).")
    p.add_argument("--output", default="tables_extracted.json",
                   help="Output JSON file (default: tables_extracted.json).")
    p.add_argument("--name-prefix", default="",
                   help="Regex for spec-specific prefixes to strip from message names "
                        "(e.g. 'PPEI|PTEI'). Empty string means no stripping.")
    p.add_argument("--debug", action="store_true",
                   help="Write first-page table layout to table_extraction_debug.txt.")
    args = p.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"ERROR: PDF not found: {args.pdf}")
        return

    signals = extract_gmlan_frames(
        pdf_path     = args.pdf,
        start_page   = args.start_page,
        end_page     = args.end_page,
        name_prefix  = args.name_prefix,
        debug_output = 'table_extraction_debug.txt' if args.debug else os.devnull,
    )

    messages = group_signals_by_message(signals)

    output = {
        'total_signals':  len(signals),
        'total_messages': len(messages),
        'messages':       messages,
        'raw_signals':    signals,
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved to: {args.output}")
    print(f"  {len(messages)} messages, {len(signals)} signals")

    print("\nSample messages:")
    for msg_id in sorted(messages.keys(), key=lambda x: int(x, 16))[:5]:
        msg = messages[msg_id]
        print(f"  {msg_id}: {msg['name']} ({len(msg['signals'])} signals)")

if __name__ == '__main__':
    main()
