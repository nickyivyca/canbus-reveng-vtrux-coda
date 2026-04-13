#!/usr/bin/env python3
"""Disassemble LabVIEW VICD_code.bin files and trace CAN frame decode logic.

Uses capstone for x86 32-bit disassembly. Focuses on identifying:
- Byte loads from CAN frame data buffer: mov reg, [base+N]
- Bitfield extraction: and, shr, shl
- Scale/offset: fmul, fadd, fild (integer-to-float conversion)
- Jump tables / switch on CAN arbitration ID
- Writes to output data space (relocation targets)

Usage:
    python tools/vicd_disasm.py <vicd_code.bin> [--start OFFSET] [--length N]
    python tools/vicd_disasm.py <vicd_code.bin> --full
    python tools/vicd_disasm.py <vicd_code.bin> --scan-patterns
"""

import argparse
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_X86, CS_MODE_32, CS_GRP_JUMP, CS_GRP_CALL


def load_binary(path):
    with open(path, 'rb') as f:
        return f.read()


def disassemble_range(code, start, length, base=0):
    """Disassemble a range of bytes and return instruction list."""
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    chunk = code[start:start + length]
    return list(md.disasm(chunk, base + start))


def find_code_regions(code):
    """Scan for regions that look like actual code (not zero-fill or data)."""
    regions = []
    in_code = False
    start = 0
    zero_run = 0

    for i, b in enumerate(code):
        if b == 0:
            zero_run += 1
            if zero_run > 16 and in_code:
                regions.append((start, i - zero_run))
                in_code = False
        else:
            if not in_code:
                start = i
                in_code = True
            zero_run = 0

    if in_code:
        regions.append((start, len(code)))

    return regions


def scan_patterns(code):
    """Scan the entire binary for CAN decode patterns."""
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True

    regions = find_code_regions(code)
    print(f"Found {len(regions)} code regions:")
    for start, end in regions:
        print(f"  0x{start:04x} - 0x{end:04x}  ({end - start} bytes)")
    print()

    # Track patterns of interest
    byte_loads = []       # mov reg, [reg+N] where N is small (CAN data bytes 0-7)
    float_ops = []        # fmul, fadd, fild, etc.
    bitfield_ops = []     # and, shr, shl with immediate
    comparisons = []      # cmp with interesting values (CAN IDs?)
    float_constants = []  # fld with memory operands (scale factors)

    for start, end in regions:
        chunk = code[start:end]
        for insn in md.disasm(chunk, start):
            mnemonic = insn.mnemonic
            op_str = insn.op_str

            # Byte loads: movzx/mov from [reg+N]
            if mnemonic in ('movzx', 'mov', 'movsx') and '+' in op_str:
                # Look for small offsets that could be CAN frame byte indices
                parts = op_str.split(',')
                if len(parts) == 2:
                    src = parts[1].strip()
                    if 'byte ptr' in src or 'word ptr' in src:
                        byte_loads.append((insn.address, mnemonic, op_str))

            # Float operations
            if mnemonic.startswith('f') and mnemonic in (
                'fmul', 'fadd', 'fsub', 'fdiv', 'fild', 'fist', 'fistp',
                'fld', 'fstp', 'fst', 'fimul', 'fidiv'):
                float_ops.append((insn.address, mnemonic, op_str))

            # Bitfield: and/shr/shl with immediate
            if mnemonic in ('and', 'shr', 'shl', 'sar', 'ror', 'rol'):
                if '0x' in op_str or any(c.isdigit() for c in op_str.split(',')[-1]):
                    bitfield_ops.append((insn.address, mnemonic, op_str))

            # Comparisons (potential CAN ID matching)
            if mnemonic == 'cmp':
                bitfield_ops.append((insn.address, mnemonic, op_str))

            # Look for interesting immediate values that could be CAN IDs
            if mnemonic == 'cmp' and '0x' in op_str:
                comparisons.append((insn.address, mnemonic, op_str))

    print(f"=== Byte/Word Loads from memory (potential CAN frame reads) ===")
    print(f"Count: {len(byte_loads)}")
    for addr, mn, ops in byte_loads[:50]:
        print(f"  0x{addr:04x}: {mn:8s} {ops}")
    if len(byte_loads) > 50:
        print(f"  ... ({len(byte_loads) - 50} more)")

    print(f"\n=== Float Operations (scale/offset conversion) ===")
    print(f"Count: {len(float_ops)}")
    for addr, mn, ops in float_ops[:50]:
        print(f"  0x{addr:04x}: {mn:8s} {ops}")
    if len(float_ops) > 50:
        print(f"  ... ({len(float_ops) - 50} more)")

    print(f"\n=== Bitfield Operations (and/shift/cmp) ===")
    print(f"Count: {len(bitfield_ops)}")
    for addr, mn, ops in bitfield_ops[:50]:
        print(f"  0x{addr:04x}: {mn:8s} {ops}")
    if len(bitfield_ops) > 50:
        print(f"  ... ({len(bitfield_ops) - 50} more)")

    print(f"\n=== Comparisons with hex values (potential CAN ID dispatch) ===")
    print(f"Count: {len(comparisons)}")
    for addr, mn, ops in comparisons:
        print(f"  0x{addr:04x}: {mn:8s} {ops}")

    # Look for float constants in data regions (between code)
    print(f"\n=== Scanning for 64-bit float constants in data regions ===")
    # Check the relocation area (0x30-0x12C based on DCDC_Recvd)
    for offset in range(0, len(code) - 8, 4):
        try:
            val = struct.unpack_from('<d', code, offset)[0]
            # Filter for plausible scale factors (small numbers, powers of 10, etc.)
            if val != 0.0 and abs(val) < 1e6 and abs(val) > 1e-10:
                # Skip if it's in a code region
                in_code_region = any(s <= offset < e for s, e in regions)
                if not in_code_region:
                    print(f"  0x{offset:04x}: {val:.10g}")
        except:
            pass


def disasm_full(code, start_offset=None):
    """Full disassembly of all code regions."""
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True

    if start_offset is not None:
        regions = [(start_offset, len(code))]
    else:
        regions = find_code_regions(code)

    for reg_start, reg_end in regions:
        print(f"\n{'='*60}")
        print(f"Code region: 0x{reg_start:04x} - 0x{reg_end:04x}")
        print(f"{'='*60}")
        chunk = code[reg_start:reg_end]
        for insn in md.disasm(chunk, reg_start):
            # Annotate interesting instructions
            annotation = ''
            mn = insn.mnemonic
            ops = insn.op_str

            if mn in ('movzx', 'movsx') and 'byte ptr' in ops:
                annotation = '  ; << byte load'
            elif mn in ('movzx', 'movsx') and 'word ptr' in ops:
                annotation = '  ; << word load'
            elif mn in ('and',) and '0x' in ops:
                annotation = '  ; << mask'
            elif mn in ('shr', 'shl', 'sar'):
                annotation = '  ; << shift'
            elif mn.startswith('f') and mn in ('fmul', 'fadd', 'fild', 'fld', 'fstp'):
                annotation = '  ; << FLOAT'
            elif mn == 'cmp' and '0x' in ops:
                annotation = '  ; << COMPARE'
            elif mn in ('ret', 'retn'):
                annotation = '\n'

            print(f"  0x{insn.address:04x}: {insn.bytes.hex():24s} {mn:8s} {ops}{annotation}")


def main():
    parser = argparse.ArgumentParser(description='Disassemble LabVIEW VICD_code.bin')
    parser.add_argument('binary', help='Path to _VICD_code.bin file')
    parser.add_argument('--start', type=lambda x: int(x, 0), default=None,
                        help='Start offset (hex or dec)')
    parser.add_argument('--length', type=lambda x: int(x, 0), default=0x200,
                        help='Number of bytes to disassemble')
    parser.add_argument('--full', action='store_true',
                        help='Disassemble all code regions')
    parser.add_argument('--scan-patterns', action='store_true',
                        help='Scan for CAN decode patterns')
    args = parser.parse_args()

    code = load_binary(args.binary)
    print(f"Loaded {len(code)} bytes from {args.binary}")

    if args.scan_patterns:
        scan_patterns(code)
    elif args.full:
        disasm_full(code, args.start)
    else:
        start = args.start or 0
        disasm_full(code, start)


if __name__ == '__main__':
    main()
