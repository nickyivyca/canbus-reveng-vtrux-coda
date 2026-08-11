"""Find the range of all MOVT #0x000F instructions and adjacent MOVW values."""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

def decode_mov(hw1, hw2):
    top5 = (hw1 >> 11) & 0x1F
    if top5 != 0b11110: return None
    bits_9_4 = (hw1 >> 4) & 0x3F
    if bits_9_4 == 0b100100: op = 'MOVW'
    elif bits_9_4 == 0b101100: op = 'MOVT'
    else: return None
    if (hw2 >> 15) & 1 != 0: return None
    i    = (hw1 >> 10) & 1
    imm4 = hw1 & 0xF
    imm3 = (hw2 >> 12) & 0x7
    Rd   = (hw2 >> 8) & 0xF
    imm8 = hw2 & 0xFF
    imm16 = (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8
    return (op, Rd, imm16)

with open(BINARY, 'rb') as f:
    data = f.read()

# Find first and last MOVT #0x000F
first_vma = None
last_vma = None
for vma in range(VMA_BASE, VMA_BASE + len(data) - 4, 2):
    off = vma - VMA_BASE
    hw1, hw2 = struct.unpack_from('<HH', data, off)
    r = decode_mov(hw1, hw2)
    if r and r[0] == 'MOVT' and r[2] == 0x000F:
        if first_vma is None: first_vma = vma
        last_vma = vma

print(f'First MOVT #0x000F: VMA 0x{first_vma:08X}')
print(f'Last  MOVT #0x000F: VMA 0x{last_vma:08X}')

# Now find MOVT #0x000F with MOVW for gear cfstrings in the FULL binary range
GEAR_CFSTR = {
    0x57B8: 'Park',   0x57C8: 'UnPark',   0x5D18: 'Reverse',
    0x5D28: 'Neutral',0x5D38: 'Drive',    0x5D48: 'Low',
    0x52F8: 'Invalid',0x5D08: '%08X',
}

print()
print('=== MOVW(gear) + MOVT(#0x000F) pairs anywhere in binary ===')
prev = None
for vma in range(VMA_BASE, VMA_BASE + len(data) - 4, 2):
    off = vma - VMA_BASE
    hw1, hw2 = struct.unpack_from('<HH', data, off)
    r = decode_mov(hw1, hw2)
    if r is None:
        prev = None
        continue
    op, Rd, imm16 = r
    if op == 'MOVT' and imm16 == 0x000F:
        if prev and prev[0] == 'MOVW' and prev[1] == Rd and prev[2] in GEAR_CFSTR:
            label = GEAR_CFSTR[prev[2]]
            print(f'  VMA 0x{prev[3]:08X}: MOVW r{Rd}, #0x{prev[2]:04X}  [{label}]')
            print(f'  VMA 0x{vma:08X}: MOVT r{Rd}, #0x000F')
            print()
    prev = (op, Rd, imm16, vma)
