#!/usr/bin/env python3
"""
extract_tables_docling.py

Extracts tabular signal data from a CAN specification PDF using Docling and
writes a structured JSON file compatible with distill_intermediate.py.

This is a generalized extractor designed to work on any CAN specification PDF
that uses a tabular format with columns for message ID, signal name, byte/bit
position, data type, range, and conversion formula.

Usage:
    python extract_tables_docling.py --pdf spec.pdf --start-page 228 --end-page 269
    python extract_tables_docling.py --pdf spec.pdf --start-page 228 --end-page 269 \\
        --output my_extracted.json \\
        --id-pattern "\\$([0-9A-Fa-f]{2,4})" \\
        --name-prefix "PPEI|PTEI" \\
        --debug

Output JSON schema (same as legacy pdfplumber extractor):
    {
        "total_signals": int,
        "total_messages": int,
        "messages": {
            "0x0C1": {
                "id": "0x0C1",
                "name": "...",
                "transmitter": "...",
                "signals": [{"name": ..., "start_byte": ..., "start_bit": ...,
                             "length": ..., "data_type": ..., "range": ...,
                             "conversion": ...}]
            }
        },
        "raw_signals": [...]
    }

Dependencies:
    pip install docling

"""

import argparse
import json
import os
import re
import sys


def parse_args():
    p = argparse.ArgumentParser(
        description="Extract CAN signal tables from a spec PDF using Docling."
    )
    p.add_argument("--pdf", required=True, help="Path to the input PDF.")
    p.add_argument("--start-page", type=int, required=True,
                   help="First page to extract (1-indexed).")
    p.add_argument("--end-page", type=int, required=True,
                   help="Last page to extract (1-indexed, inclusive).")
    p.add_argument("--output", default="tables_extracted.json",
                   help="Output JSON file (default: tables_extracted.json).")
    p.add_argument("--id-pattern", default=r"\$([0-9A-Fa-f]{2,4})",
                   help="Regex to extract message hex IDs from the ID column. "
                        "Must have one capture group that returns the hex digits. "
                        r"Default: \$([0-9A-Fa-f]{2,4})")
    p.add_argument("--name-prefix", default="",
                   help="Regex for spec-specific prefixes to strip from message names "
                        "(e.g. 'PPEI|PTEI'). Empty string means no stripping.")
    p.add_argument("--chunk-size", type=int, default=1,
                   help="Pages per Docling call; lower values reduce peak memory. "
                        "Default 1 (one page at a time) is safest for large specs. "
                        "Increase to 5+ if memory is not a concern.")
    p.add_argument("--debug", action="store_true",
                   help="Print per-table column mapping debug info.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

# Keywords used to identify columns by substring matching on the column header.
# Each entry: (internal key, list of substrings to try in priority order)
_COL_KEYWORDS = [
    ("message",    ["message"]),
    ("id",         ["id"]),
    ("signal",     ["signal"]),
    ("start_byte", ["start byte", "byte"]),
    ("start_bit",  ["start bit", "bit"]),
    ("length",     ["length"]),
    ("data_type",  ["data type", "type"]),
    ("range",      ["range"]),
    ("conversion", ["conversion"]),
    ("transmitter",["transmitter"]),
]


def detect_columns(df_columns, debug=False):
    """
    Map internal field names to DataFrame column indices by looking for
    keyword substrings in the column headers.

    Returns a dict {field_name: column_index} for fields that were found,
    or an empty dict if no columns could be mapped.
    """
    cols_lower = [c.lower() for c in df_columns]
    mapping = {}
    for field, keywords in _COL_KEYWORDS:
        for kw in keywords:
            for i, col in enumerate(cols_lower):
                if kw in col:
                    mapping[field] = i
                    break
            if field in mapping:
                break

    if debug:
        print(f"    Column mapping: {mapping}")

    return mapping


# ---------------------------------------------------------------------------
# Message ID parsing
# ---------------------------------------------------------------------------

def make_id_parser(pattern):
    """Return a function that extracts a 0x-prefixed hex ID from a cell string."""
    compiled = re.compile(pattern, re.IGNORECASE)
    def parse(text):
        m = compiled.search(text or "")
        if m:
            return "0x" + m.group(1).upper()
        return None
    return parse


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def make_name_normalizer(prefix_pattern):
    """
    Return a function that strips a spec-specific prefix from a message name
    and normalizes underscore-space artifacts (e.g. 'Some_ Name' -> 'Some_Name').
    """
    compiled = re.compile(
        r"(?:" + prefix_pattern + r")[:\s]+(.+)",
        re.IGNORECASE
    ) if prefix_pattern else None

    def normalize(raw):
        text = (raw or "").strip().replace("\n", " ")
        text = re.sub(r"_\s+", "_", text)
        if compiled:
            m = compiled.search(text)
            if m:
                return m.group(1).strip()
        return text

    return normalize


# ---------------------------------------------------------------------------
# Row processing
# ---------------------------------------------------------------------------

def process_rows(df, col_map, parse_id, normalize_name,
                 current_msg_id, current_msg_name, current_transmitter):
    """
    Iterate over DataFrame rows and extract signal records.

    current_transmitter is carried as state across rows (and across table
    chunks) because the transmitter cell in the PDF is a merged cell that
    spans all signal rows for a message.  Docling places the value only in
    the row where the message ID appears; if that row has no byte/bit/length
    data (a header-only row) the per-row value would be lost before any
    signal is emitted.  Tracking it as state ensures it is applied to all
    subsequent signal rows for that message.

    Returns (signals, current_msg_id, current_msg_name, current_transmitter).
    """
    signals = []

    def cell(row, field):
        idx = col_map.get(field)
        if idx is None:
            return ""
        val = row.iloc[idx]
        if val is None:
            return ""
        return str(val).strip()

    for _, row in df.iterrows():
        id_text = cell(row, "id")
        msg_id = parse_id(id_text)
        if msg_id:
            current_msg_id = msg_id
            msg_text = cell(row, "message")
            if msg_text:
                current_msg_name = normalize_name(msg_text)
            tx = cell(row, "transmitter")
            if tx:
                current_transmitter = tx

        # A signal row must have parseable integer values for byte, bit, length
        byte_str = cell(row, "start_byte")
        bit_str  = cell(row, "start_bit")
        len_str  = cell(row, "length")

        if not (byte_str and bit_str and len_str):
            continue

        try:
            byte_val = int(byte_str)
            bit_val  = int(bit_str)
            len_val  = int(len_str)
        except ValueError:
            continue

        sig_name = cell(row, "signal").replace("\n", " ")

        # Skip rows that look like table header artifacts (all-digit signal names)
        if not sig_name or sig_name.replace(".", "").isdigit():
            continue

        signals.append({
            "message_id":   current_msg_id,
            "message_name": current_msg_name,
            "signal_name":  sig_name,
            "start_byte":   byte_val,
            "start_bit":    bit_val,
            "length":       len_val,
            "data_type":    cell(row, "data_type") or "UNK",
            "range":        cell(row, "range"),
            "conversion":   cell(row, "conversion"),
            "transmitter":  current_transmitter,
        })

    return signals, current_msg_id, current_msg_name, current_transmitter


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract(pdf_path, start_page, end_page, id_pattern, name_prefix, debug,
            chunk_size=1):
    """
    Run Docling on the specified page range and extract all signal rows.

    Pages are processed in chunks to avoid memory exhaustion when the table
    structure recognition model is applied to many pages at once. Each chunk
    is converted independently; message state (current ID and name) is
    preserved across chunks so that signals that span a chunk boundary are
    attributed correctly.

    Args:
        chunk_size: Number of pages per Docling conversion call. Lower values
                    use less peak memory. Default 5 works well in practice.

    Returns a list of raw signal dicts.
    """
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions, TableStructureOptions, TableFormerMode
    )

    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.do_ocr = False
    pipeline_opts.do_table_structure = True
    pipeline_opts.table_structure_options = TableStructureOptions(
        mode=TableFormerMode.ACCURATE,
        do_cell_matching=True,
    )
    # Batch sizes of 1 minimize per-call peak memory; combined with chunk_size=1
    # this keeps memory bounded to approximately one page at a time.
    pipeline_opts.table_batch_size = 1
    pipeline_opts.layout_batch_size = 1

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)
        }
    )

    parse_id  = make_id_parser(id_pattern)
    normalize = make_name_normalizer(name_prefix)

    all_signals         = []
    current_msg_id      = None
    current_msg_name    = None
    current_transmitter = None
    tables_with_no_col_map = 0
    total_tables = 0

    print(f"Converting pages {start_page}-{end_page} of: {pdf_path}")
    print(f"(Processing in chunks of {chunk_size} pages)")

    chunk_start = start_page
    while chunk_start <= end_page:
        chunk_end = min(chunk_start + chunk_size - 1, end_page)
        print(f"  Pages {chunk_start}-{chunk_end}...", end=" ", flush=True)

        result = converter.convert(
            pdf_path,
            page_range=(chunk_start, chunk_end),
            raises_on_error=False,
        )
        doc = result.document
        print(f"{len(doc.tables)} tables")
        total_tables += len(doc.tables)

        for tbl in doc.tables:
            df = tbl.export_to_dataframe(doc=doc)

            if debug:
                print(f"\n    Table shape={df.shape}")

            col_map = detect_columns(list(df.columns), debug=debug)
            if not col_map.get("signal") or not col_map.get("start_byte"):
                if debug:
                    print(f"    Skipping: missing 'signal' or 'start_byte' column.")
                tables_with_no_col_map += 1
                continue

            sigs, current_msg_id, current_msg_name, current_transmitter = process_rows(
                df, col_map, parse_id, normalize,
                current_msg_id, current_msg_name, current_transmitter
            )
            all_signals.extend(sigs)

        chunk_start = chunk_end + 1

    print(f"\nTotal tables processed: {total_tables}")
    if tables_with_no_col_map:
        print(f"Skipped {tables_with_no_col_map} table(s) with no recognizable column layout.")

    return all_signals


def group_by_message(signals):
    """Group raw signal list into a message dict keyed by message ID."""
    messages = {}
    for sig in signals:
        msg_id = sig["message_id"]
        if not msg_id:
            continue
        if msg_id not in messages:
            messages[msg_id] = {
                "id":          msg_id,
                "name":        sig["message_name"],
                "transmitter": sig["transmitter"],  # updated below if empty
                "signals":     [],
            }
        # If a later signal in the same message has a non-empty transmitter
        # (shouldn't normally happen, but handles edge cases), keep the first one.
        if not messages[msg_id]["transmitter"] and sig["transmitter"]:
            messages[msg_id]["transmitter"] = sig["transmitter"]
        messages[msg_id]["signals"].append({
            "name":       sig["signal_name"],
            "start_byte": sig["start_byte"],
            "start_bit":  sig["start_bit"],
            "length":     sig["length"],
            "data_type":  sig["data_type"],
            "range":      sig["range"],
            "conversion": sig["conversion"],
        })
    return messages


def main():
    args = parse_args()

    if not os.path.isfile(args.pdf):
        print(f"ERROR: PDF not found: {args.pdf}")
        sys.exit(1)

    signals = extract(
        pdf_path=args.pdf,
        start_page=args.start_page,
        end_page=args.end_page,
        id_pattern=args.id_pattern,
        name_prefix=args.name_prefix,
        debug=args.debug,
        chunk_size=args.chunk_size,
    )

    messages = group_by_message(signals)

    print(f"\nTotal signals extracted: {len(signals)}")
    print(f"Messages grouped: {len(messages)}")

    output = {
        "total_signals":  len(signals),
        "total_messages": len(messages),
        "messages":       messages,
        "raw_signals":    signals,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved to: {args.output}")

    print("\nSample messages:")
    for msg_id in sorted(messages.keys(), key=lambda x: int(x, 16))[:5]:
        msg = messages[msg_id]
        print(f"  {msg_id}: {msg['name']} ({len(msg['signals'])} signals)")


if __name__ == "__main__":
    main()
