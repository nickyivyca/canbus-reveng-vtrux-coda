"""
Scan entire binary for gear-related cfstring VMAs as 32-bit words.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

TARGETS = {
    0x000F57B8: 'Park',
    0x000F57C8: 'UnPark',
    0x000F5D18: 'Reverse',
    0x000F5D28: 'Neutral',
    0x000F5D38: 'Drive',
    0x000F5D48: 'Low',
    0x000F52F8: 'Invalid',
}

with open(BINARY, 'rb') as f:
    data = f.read()

print(f'Binary size: {len(data)} bytes')
print()

for offset in range(0, len(data) - 3, 4):
    word = struct.unpack_from('<I', data, offset)[0]
    if word in TARGETS:
        print(f'  foff=0x{offset:06X}  VMA=0x{offset+0x4000:08X}: 0x{word:08X}  -> {TARGETS[word]!r}')
