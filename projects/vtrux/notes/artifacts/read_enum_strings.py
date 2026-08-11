"""
Read all cfstring enum values from the CANbusLogger2 ARMv7 binary
for the GoPoint and VIA CAN parser switch arms.

cfstring struct (16 bytes, ARM32 LE):
  offset  0: isa pointer (skip)
  offset  4: flags (0x7C8 for UTF-8 NSConstantString)
  offset  8: data pointer -> C string in __cstring section
  offset 12: length

VMA base = 0x4000: file_offset = vma - 0x4000
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

def vma_off(vma):
    return vma - 0x4000

def read_cfstring(f, vma):
    """Read one cfstring struct; return (string, length) or None."""
    f.seek(vma_off(vma))
    raw = f.read(16)
    if len(raw) < 16:
        return None
    _isa, flags, ptr, length = struct.unpack('<IIII', raw)
    if flags not in (0x7C8, 0x7D0, 0xC8, 0x3E8):   # known NSConstantString flags
        return None
    try:
        f.seek(vma_off(ptr))
        s = f.read(length + 1)
        return s[:length].decode('utf-8', errors='replace')
    except Exception:
        return None

def read_cfstring_array(f, start_vma, count):
    """Read count consecutive cfstring structs starting at start_vma."""
    results = []
    for i in range(count):
        s = read_cfstring(f, start_vma + i * 16)
        results.append(s)
    return results

with open(BINARY, 'rb') as f:

    # ------------------------------------------------------------------
    # NOTE: The __cfstring section is at VMA 0x000F3D28.
    # Decompile showed low-16-bit fragments like 0x56B8, 0x5D68 etc.
    # The MOVT high half is 0x000F, so full VMAs = 0x000F0000 | low16.
    # ------------------------------------------------------------------

    # Verify known cfstrings to calibrate VMA layout
    # From decompile: 0x0053 OperationMode = 4 entries (low bits 0x56B8)
    # and OperationState = 9 entries starting at low bits 0x56F8
    print('=== Calibration: 0x0053 OperationMode (4 entries @ 0x000F56B8) ===')
    for i, s in enumerate(read_cfstring_array(f, 0x000F56B8, 4)):
        print(f'  [{i}] {s!r}')

    print()
    print('=== Calibration: 0x0053 OperationState (9 entries @ 0x000F56F8) ===')
    for i, s in enumerate(read_cfstring_array(f, 0x000F56F8, 9)):
        print(f'  [{i}] {s!r}')

    # ------------------------------------------------------------------
    # 0x06000001: gear position (6 entries, low bits 0x57B8)
    # Known: entry[4]=Low, entry[5]=Invalid
    # ------------------------------------------------------------------
    print()
    print('=== 0x06000001 gear position (6 entries @ 0x000F57B8) ===')
    for i, s in enumerate(read_cfstring_array(f, 0x000F57B8, 6)):
        print(f'  [{i}] {s!r}')

    # ------------------------------------------------------------------
    # 0x0868A047: AC compressor status (4 entries, low bits 0x5D68)
    # ------------------------------------------------------------------
    print()
    print('=== 0x0868A047 AC compressor status (4 entries @ 0x000F5D68) ===')
    for i, s in enumerate(read_cfstring_array(f, 0x000F5D68, 4)):
        print(f'  [{i}] {s!r}')

    # ------------------------------------------------------------------
    # 0x0868A047: EAC_CompFltStat fault status
    # From decompile, array of 8 entries; visible low bits: 0x5D98, 0x5DB8, 0x5DD8, 0x5DF8
    # (every other entry; register-loaded ones are interleaved)
    # Try sequential from 0x000F5D98
    # ------------------------------------------------------------------
    print()
    print('=== 0x0868A047 EAC_CompFltStat (8 entries @ 0x000F5D98) ===')
    for i, s in enumerate(read_cfstring_array(f, 0x000F5D98, 8)):
        print(f'  [{i}] {s!r}')

    # ------------------------------------------------------------------
    # Wide scan over entire __cfstring section (0xF3D28 - 0xFAED8)
    # to see all cfstrings and verify the above
    # ------------------------------------------------------------------
    print()
    print('=== Wide scan 0x000F5500-0x000F6200 (cfstrings around enum areas) ===')
    vma = 0x000F5500
    while vma < 0x000F6200:
        s = read_cfstring(f, vma)
        if s is not None:
            print(f'  VMA 0x{vma:07X}  {s!r}')
        vma += 16
