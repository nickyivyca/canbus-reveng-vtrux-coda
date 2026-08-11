"""Read the 8-entry parkLockState array used by VIA CAN 0x055C."""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

def vma_off(vma): return vma - 0x4000

def read_cfstring(data, vma):
    off = vma_off(vma)
    if off + 16 > len(data): return None
    isa, flags, ptr, length = struct.unpack_from('<IIII', data, off)
    if length == 0 or length > 200: return None
    ptr_off = vma_off(ptr)
    if ptr_off < 0 or ptr_off + length > len(data): return None
    try:
        return data[ptr_off:ptr_off+length].decode('utf-8', errors='replace')
    except Exception:
        return None

with open(BINARY, 'rb') as f:
    data = f.read()

# 0x055C 8-entry parkLockState array (non-contiguous in cfstring section):
# Entries derived from NEON paired-load pattern in decompile.
# Each explicit MOVW VMA and its NEON-pair adjacent (VMA+0x10).
entries = [
    (0x000F57A8, 'explicit [0]'),
    (0x000F57B8, 'implicit [1] (adjacent to OFF)'),
    (0x000F59E8, 'explicit [2]'),
    (0x000F59F8, 'implicit [3] (adjacent to Parked)'),
    (0x000F5A08, 'explicit [4]'),
    (0x000F5A18, 'implicit [5] (adjacent to Unparking)'),
    (0x000F5A28, 'explicit [6]'),
    (0x000F5A38, 'implicit [7] (adjacent to UnparkStalled)'),
]

print('=== 0x055C parkLockState 8-entry array ===')
for i, (vma, note) in enumerate(entries):
    s = read_cfstring(data, vma)
    print(f'  [{i}] VMA=0x{vma:07X}  {s!r}  ({note})')
print()

# Also read a few neighbours of 0xF5A38 to see what comes after
print('=== Context around 0xF5A28-0xF5A68 ===')
for vma in range(0x000F5A18, 0x000F5A78, 0x10):
    s = read_cfstring(data, vma)
    print(f'  VMA=0x{vma:07X}: {s!r}')
