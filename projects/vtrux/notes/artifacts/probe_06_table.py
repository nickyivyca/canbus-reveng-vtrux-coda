"""
Examine the GoPoint ID lookup table near foff 0x118BCC.
Read 32-bit values to understand the table structure.
The parseEPRIMessage switch likely has a GoPoint ID lookup table here.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

with open(BINARY, 'rb') as f:
    data = f.read()

# Look at 200 bytes around the first 0x06000001 occurrence
foff_start = 0x118B80
foff_end   = 0x118D00

print('=== Data around foff 0x118BCC (raw 32-bit words) ===')
for off in range(foff_start, foff_end, 4):
    if off + 4 > len(data): break
    word = struct.unpack_from('<I', data, off)[0]
    vma = off + VMA_BASE
    known = ''
    if word == 0x06000001: known = '  <- 0x06000001 (gear)'
    elif word == 0x0868A047: known = '  <- 0x0868A047 (AC)'
    elif word == 0x0870A047: known = '  <- 0x0870A047 (HV)'
    elif word == 0x18FFD4C0: known = '  <- VIA CAN extended'
    elif 0x0001 <= word <= 0xFFFF: known = f'  (small: {word})'
    print(f'  foff=0x{off:06X}  VMA=0x{vma:08X}:  0x{word:08X}{known}')

# Also check foff 0x118E00 area (second cluster)
print()
print('=== Data around foff 0x118E00 ===')
for off in range(0x118DC0, 0x118F00, 4):
    if off + 4 > len(data): break
    word = struct.unpack_from('<I', data, off)[0]
    vma = off + VMA_BASE
    known = ''
    if word == 0x06000001: known = '  <- 0x06000001'
    elif word == 0x0868A047: known = '  <- 0x0868A047'
    elif word == 0x0870A047: known = '  <- 0x0870A047'
    print(f'  foff=0x{off:06X}:  0x{word:08X}{known}')
