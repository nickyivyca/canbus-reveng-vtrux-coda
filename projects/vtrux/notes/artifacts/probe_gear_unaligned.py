"""
Scan entire binary for gear-related cfstring struct VMAs, byte-aligned search.
Also check if the cfstring section VMAs are referenced anywhere in the binary.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

TARGETS = {
    0x000F57B8: 'cfstr_Park',
    0x000F57C8: 'cfstr_UnPark',
    0x000F5D18: 'cfstr_Reverse',
    0x000F5D28: 'cfstr_Neutral',
    0x000F5D38: 'cfstr_Drive',
    0x000F5D48: 'cfstr_Low',
    0x000F52F8: 'cfstr_Invalid',
}

with open(BINARY, 'rb') as f:
    data = f.read()

print(f'Binary size: {len(data)} bytes')
print()

# Byte-aligned scan
hits = {}
for offset in range(len(data) - 3):
    word = struct.unpack_from('<I', data, offset)[0]
    if word in TARGETS:
        hits.setdefault(TARGETS[word], []).append(offset)

if hits:
    for label, offsets in sorted(hits.items()):
        for off in offsets:
            print(f'  foff=0x{off:06X}: {label}')
else:
    print('No matches found anywhere in binary.')

# Verify: check if cfstring section start appears
cfstart = 0x000F3D28
print()
for offset in range(len(data) - 3):
    word = struct.unpack_from('<I', data, offset)[0]
    if word == cfstart:
        print(f'  cfstring section start 0x{cfstart:08X} found at foff=0x{offset:06X}')
        break
else:
    print(f'  cfstring section start 0x{cfstart:08X} NOT found anywhere')

# What does the binary actually contain near the expected Park cfstring VMA?
expected_foff = 0x000F57B8 - 0x4000  # = 0x000F17B8
print()
print(f'Checking bytes at expected Park cfstr foff=0x{expected_foff:06X}:')
if expected_foff + 16 <= len(data):
    raw = data[expected_foff:expected_foff+16]
    print(' '.join(f'{b:02x}' for b in raw))
    isa, flags, ptr, length = struct.unpack_from('<IIII', data, expected_foff)
    print(f'  isa=0x{isa:08X} flags=0x{flags:08X} ptr=0x{ptr:08X} len={length}')
else:
    print('  Out of range!')
