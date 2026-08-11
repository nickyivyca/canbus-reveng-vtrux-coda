#!/usr/bin/env python3
"""
Debug pdfplumber extraction for specific message IDs.
Prints raw table rows for pages where any of the target IDs appear.

Usage:
    python probe_pdfplumber.py --pdf spec.pdf --start-page 228 --end-page 269 \\
        --ids 3C9 3D1 77F
"""
import argparse
import sys
sys.path.insert(0, '.')
from extract_tables_local import clean_cell_text, detect_column_layout
import pdfplumber


def main():
    p = argparse.ArgumentParser(description="Probe pdfplumber table extraction for specific IDs.")
    p.add_argument("--pdf", required=True, help="Path to the PDF file.")
    p.add_argument("--start-page", type=int, required=True,
                   help="First page to scan (1-indexed).")
    p.add_argument("--end-page", type=int, required=True,
                   help="Last page to scan (1-indexed, inclusive).")
    p.add_argument("--ids", nargs="+", required=True,
                   help="Hex message IDs to search for (without $ or 0x prefix, e.g. 3C9 3D1).")
    args = p.parse_args()

    search_ids = {'$' + id_.upper() for id_ in args.ids}

    with pdfplumber.open(args.pdf) as pdf:
        for page_num in range(args.start_page - 1, args.end_page):
            if page_num >= len(pdf.pages):
                break
            page = pdf.pages[page_num]
            tables = page.extract_tables()
            for tbl in tables:
                flat = ' '.join(clean_cell_text(c) for row in tbl for c in row if c)
                if any(sid in flat for sid in search_ids):
                    found = [sid for sid in search_ids if sid in flat]
                    layout = detect_column_layout(tbl)
                    print(f'\n=== Page {page_num + 1} contains {found} ===')
                    print(f'Layout: {layout}')
                    print(f'Rows: {len(tbl)}')
                    for i, row in enumerate(tbl):
                        cells = [clean_cell_text(c) for c in row]
                        print(f'  Row {i:2d}: {cells}')


if __name__ == '__main__':
    main()
