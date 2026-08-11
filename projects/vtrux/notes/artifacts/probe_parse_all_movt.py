"""
Find ALL MOVT #0x000F instructions in parseEPRIMessage range,
and report what MOVW precedes each (within the last 4 instructions).
This lets us see ALL cfstring address loads and find gear-related ones.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

ARM_REGS = {0:'r0',1:'r1',2:'r2',3:'r3',4:'r4',5:'r5',6:'r6',7:'r7',
            8:'r8',9:'r9',10:'r10',11:'r11',12:'r12',13:'sp',14:'lr',15:'pc'}

KNOWN_CFSTRS = {
    0x57B8: 'Park',      0x57C8: 'UnPark',    0x57D8: 'Park Request %@',
    0x5D08: '%08X',      0x5D18: 'Reverse',   0x5D28: 'Neutral',
    0x5D38: 'Drive',     0x5D48: 'Low',       0x5D58: 'GearlevFmt',
    0x5D68: 'Normal Op', 0x5D78: 'Degraded',  0x5D88: 'Inoperative',
    0x5D98: 'No Fault',  0x5DA8: 'Under V',   0x5DB8: 'Over V',
    0x52F8: 'Invalid',   0x56B8: 'NTRL',      0x56C8: 'Invalid(1)',
    0x56D8: 'Invalid(2)',0x56E8: 'Invalid(%d)',
    0x56F8: 'INIT',      0x5708: 'STBY',
    0x59D8: 'Parking',   0x59E8: 'Parked',    0x59F8: 'ParkStalled',
    0x5A08: 'Unparking', 0x5A18: 'Unparked',  0x5A28: 'UnparkStalled',
}

def decode_mov(hw1, hw2):
    top5 = (hw1 >> 11) & 0x1F
    if top5 != 0b11110:
        return None
    bits_9_4 = (hw1 >> 4) & 0x3F
    if bits_9_4 == 0b100100:
        op = 'MOVW'
    elif bits_9_4 == 0b101100:
        op = 'MOVT'
    else:
        return None
    if (hw2 >> 15) & 1 != 0:
        return None
    i    = (hw1 >> 10) & 1
    imm4 = hw1 & 0xF
    imm3 = (hw2 >> 12) & 0x7
    Rd   = (hw2 >> 8) & 0xF
    imm8 = hw2 & 0xFF
    imm16 = (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8
    return (op, Rd, imm16)

with open(BINARY, 'rb') as f:
    data = f.read()

# Scan range: parseEPRIMessage is at 0x25D00, but the 0x06000001 case gear code
# could be anywhere. Scan wider range.
SCAN_START = 0x00025D00
SCAN_END   = 0x000C0000  # up to stub_helper start (end of __text)

print(f'Scanning VMA 0x{SCAN_START:X}..0x{SCAN_END:X} for MOVT #0x000F pairs')
print()

recent = []  # list of (op, Rd, imm16, vma)
gear_labels = set()

for vma in range(SCAN_START, SCAN_END - 4, 2):
    off = vma - VMA_BASE
    hw1, hw2 = struct.unpack_from('<HH', data, off)
    r = decode_mov(hw1, hw2)
    if r is None:
        if recent and recent[-1][0] != 'GAP':
            recent.append(('GAP', None, None, vma))
        continue
    op, Rd, imm16 = r
    recent.append((op, Rd, imm16, vma))
    if len(recent) > 8:
        recent.pop(0)

    if op == 'MOVT' and imm16 == 0x000F:
        # Find the most recent MOVW for the same Rd
        movw = None
        for item in reversed(recent[:-1]):
            if item[0] == 'GAP':
                break
            if item[0] == 'MOVW' and item[1] == Rd:
                movw = item
                break
        if movw:
            low16 = movw[2]
            label = KNOWN_CFSTRS.get(low16, f'0xF{low16:04X}')
            reg = ARM_REGS.get(Rd, f'r{Rd}')
            if label not in ('0x' + f'F{low16:04X}',):
                # Known cfstring
                print(f'  MOVW VMA 0x{movw[3]:08X}: MOVW {reg}, #0x{low16:04X}  [{label}]')
                print(f'  MOVT VMA 0x{vma:08X}: MOVT {reg}, #0x000F')
                print()
            elif any(s in hex(low16) for s in ['57b', '5d1', '5d2', '5d3', '5d4', '52f']):
                print(f'  MOVW VMA 0x{movw[3]:08X}: MOVW {reg}, #0x{low16:04X}  [gear area]')
                print(f'  MOVT VMA 0x{vma:08X}: MOVT {reg}, #0x000F')
                print()
