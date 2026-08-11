"""Re-apply the Continental variant-opcode NOP stubs to a stock SuperH4.sinc.

Normal restore does not need this script -- `restore-ghidra.ps1` copies the
already-patched `SuperH4.sinc` straight into the Ghidra install.

This script exists for the case where Ghidra is *upgraded* and the stock
`SuperH4.sinc` has changed upstream: rather than clobbering the new stock file
with our 12.0.4-era copy, re-apply just our insertion block onto the new stock
file.

The block is inserted immediately after the stock SH-4 `nop` constructor:

    :nop                        is OP_3=0x9 {  } # Empty on purpose

Usage (from the project root):

    py -3.12 ghidra/sleigh/apply_continental_stubs.py \
        "<GHIDRA_HOME>/Ghidra/Processors/SuperH4/data/languages/SuperH4.sinc"

    py -3.12 ghidra/sleigh/apply_continental_stubs.py <stock.sinc> -o <out.sinc>

By default the target file is patched in place and a `.stock` backup is written
next to it. After patching, delete `SuperH4_be.sla` in the same directory so
Ghidra recompiles the language.
"""

import argparse
import pathlib
import shutil
import sys

ANCHOR = ":nop "  # start of the stock SH-4 nop constructor line
STUBS = pathlib.Path(__file__).with_name("continental-stubs.sinc")


def apply_stubs(stock_text: str, stub_text: str) -> str:
    lines = stock_text.splitlines(keepends=True)

    if ":nop_x" in stock_text:
        raise SystemExit("ERROR: target already contains Continental stubs (:nop_x found).")

    anchor_idx = None
    for i, line in enumerate(lines):
        if line.startswith(ANCHOR) and "OP_3=0x9" in line:
            anchor_idx = i
            break
    if anchor_idx is None:
        raise SystemExit(
            "ERROR: could not find the stock ':nop ... is OP_3=0x9' anchor line. "
            "Upstream SuperH4.sinc may have changed -- insert the block by hand."
        )

    block = stub_text
    if not block.endswith("\n"):
        block += "\n"
    return "".join(lines[: anchor_idx + 1]) + block + "".join(lines[anchor_idx + 1 :])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", type=pathlib.Path, help="stock SuperH4.sinc to patch")
    ap.add_argument("-o", "--output", type=pathlib.Path,
                    help="write here instead of patching in place")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip writing the .stock backup when patching in place")
    args = ap.parse_args()

    if not args.target.is_file():
        raise SystemExit("ERROR: target not found: %s" % args.target)
    if not STUBS.is_file():
        raise SystemExit("ERROR: stub block not found: %s" % STUBS)

    stock = args.target.read_text(encoding="utf-8", errors="replace")
    stubs = STUBS.read_text(encoding="utf-8", errors="replace")
    patched = apply_stubs(stock, stubs)

    dest = args.output
    if dest is None:
        dest = args.target
        if not args.no_backup:
            backup = args.target.with_suffix(args.target.suffix + ".stock")
            if not backup.exists():
                shutil.copy2(args.target, backup)
                print("backup  : %s" % backup)

    dest.write_text(patched, encoding="utf-8", newline="")
    added = sum(1 for ln in stubs.splitlines() if ln.startswith(":nop_"))
    print("patched : %s" % dest)
    print("stubs   : %d NOP constructors inserted" % added)
    print("NOTE    : delete SuperH4_be.sla next to the .sinc so Ghidra recompiles it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
