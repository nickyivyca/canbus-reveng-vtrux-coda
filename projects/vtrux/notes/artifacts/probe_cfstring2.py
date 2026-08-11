"""
Probe the __cfstring section directly to determine struct layout and flags.
Also dump a range of cfstrings to understand what's where.
"""
import struct, sys

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
CFSTRING_VMA  = 0x000F3D28  # from Mach-O parse
CFSTRING_SIZE = 0x71B0
CSTRING_VMA   = 0x000D57F0  # __cstring section

def vma_off(vma):
    return vma - 0x4000

def read_cstring(f, ptr):
    """Read null-terminated C string at VMA ptr."""
    try:
        f.seek(vma_off(ptr))
        buf = b''
        while True:
            ch = f.read(1)
            if not ch or ch == b'\x00':
                break
            buf += ch
        return buf.decode('utf-8', errors='replace')
    except Exception as e:
        return f'<ERR:{e}>'

with open(BINARY, 'rb') as f:
    # Dump the first 10 cfstring structs (16 bytes each) from section start
    print('=== First 10 cfstring structs at VMA 0xF3D28 ===')
    for i in range(10):
        vma = CFSTRING_VMA + i * 16
        f.seek(vma_off(vma))
        raw = f.read(16)
        isa, flags, ptr, length = struct.unpack('<IIII', raw)
        s = read_cstring(f, ptr) if ptr else '(null)'
        print(f'  VMA 0x{vma:08X}  isa=0x{isa:08X}  flags=0x{flags:08X}  ptr=0x{ptr:08X}  len={length}  -> {s!r}')

    # Now dump all cfstrings in the section, printing vma + string
    print()
    print('=== All cfstrings in __cfstring section ===')
    n = CFSTRING_SIZE // 16
    for i in range(n):
        vma = CFSTRING_VMA + i * 16
        f.seek(vma_off(vma))
        raw = f.read(16)
        if len(raw) < 16:
            break
        isa, flags, ptr, length = struct.unpack('<IIII', raw)
        if ptr == 0:
            continue
        s = read_cstring(f, ptr)
        line = f'  VMA 0x{vma:08X}  {s!r}'
        sys.stdout.buffer.write((line + '\n').encode('utf-8', errors='replace'))
