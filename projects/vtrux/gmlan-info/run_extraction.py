#!/usr/bin/env python3
"""
run_extraction.py

Full extraction pipeline for this spec PDF -> DBC.

Usage:
    py -3.12 run_extraction.py
    py -3.12 run_extraction.py --pdf path/to/other_copy.pdf
    py -3.12 run_extraction.py --skip-extract   (re-run distill+generate only)

Outputs:
    gmw8762_tables_extracted.json   raw signal table
    gmw8762_intermediate.json       human-editable signal database
    GMW8762_PPEI_GMLAN_v2.dbc       staged DBC (copy to project root when ready)
"""

import argparse
import os
import sys
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Spec-specific constants -- the only place these need to be known
# --------------------------------------------------------------------------
START_PAGE      = 228
END_PAGE        = 269
NAME_PREFIX     = "PPEI|PTEI"
EXTRACTED_JSON  = os.path.join(HERE, "gmw8762_tables_extracted.json")
INTERMEDIATE    = os.path.join(HERE, "gmw8762_intermediate.json")
STAGED_DBC      = os.path.join(HERE, "GMW8762_PPEI_GMLAN_v2.dbc")
CANONICAL_DBC   = os.path.join(HERE, "..", "GMW8762_PPEI_GMLAN.dbc")
# --------------------------------------------------------------------------


def _find_pdf():
    """Return the single PDF in this directory, or None if ambiguous/absent."""
    pdfs = [f for f in os.listdir(HERE) if f.lower().endswith('.pdf')]
    return os.path.join(HERE, pdfs[0]) if len(pdfs) == 1 else None


def run_extract(pdf_path):
    from extract_tables_local import extract_gmlan_frames, group_signals_by_message
    import json

    signals  = extract_gmlan_frames(
        pdf_path    = pdf_path,
        start_page  = START_PAGE,
        end_page    = END_PAGE,
        name_prefix = NAME_PREFIX,
    )
    messages = group_signals_by_message(signals)

    output = {
        "total_signals":  len(signals),
        "total_messages": len(messages),
        "messages":       messages,
        "raw_signals":    signals,
    }
    with open(EXTRACTED_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved: {EXTRACTED_JSON}")
    print(f"  {len(messages)} messages, {len(signals)} signals")


def run_distill():
    sys.path.insert(0, HERE)
    from distill_intermediate import distill
    distill(EXTRACTED_JSON, INTERMEDIATE)


def run_generate():
    sys.path.insert(0, HERE)
    from generate_dbc_v2 import generate_dbc
    generate_dbc(INTERMEDIATE, STAGED_DBC)


def copy_to_canonical():
    canonical = os.path.normpath(CANONICAL_DBC)
    shutil.copy2(STAGED_DBC, canonical)
    print(f"Copied to canonical: {canonical}")


def main():
    p = argparse.ArgumentParser(description="Extract spec PDF -> DBC pipeline.")
    p.add_argument("--pdf", default=None,
                   help="Path to spec PDF. If omitted, the single PDF in this "
                        "directory is used automatically.")
    p.add_argument("--skip-extract", action="store_true",
                   help="Skip PDF extraction; re-run distill+generate only.")
    p.add_argument("--no-copy", action="store_true",
                   help="Don't copy staged DBC to project root.")
    args = p.parse_args()

    if not args.skip_extract:
        pdf_path = args.pdf
        if pdf_path is None:
            pdf_path = _find_pdf()
            if pdf_path is None:
                print("ERROR: No PDF found in this directory. Use --pdf to specify the path.")
                sys.exit(1)
            print(f"Using PDF: {os.path.basename(pdf_path)}")
        if not os.path.isfile(pdf_path):
            print(f"ERROR: PDF not found: {pdf_path}")
            sys.exit(1)
        print("=== Step 1: Extract tables from PDF ===")
        run_extract(pdf_path)

    print("\n=== Step 2: Distill intermediate JSON ===")
    run_distill()

    print("\n=== Step 3: Generate DBC ===")
    run_generate()

    if not args.no_copy:
        print("\n=== Step 4: Copy to canonical DBC ===")
        copy_to_canonical()

    print("\nDone.")


if __name__ == "__main__":
    main()
