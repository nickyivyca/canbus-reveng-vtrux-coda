"""
Search for Thumb-2 MOVW byte patterns for gear-related immediates.

Thumb-2 MOVW (T3) 32-bit encoding, little-endian stored as two LE 16-bit halfwords:
  HW1 bytes: [0x40|imm4, 0xF2 if i=0 else 0xF6]
  HW2 bytes: [imm8, (imm3<<4)|Rd]
  imm16 = (imm4<<12)|(i<<11)|(imm3<<8)|imm8

Also search for MOVT (T1):
  HW1 bytes: [0xC0|imm4, 0xF2 if i=0 else 0xF6]
  HW2: same as MOVW
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

GEAR_IMMS = {
    0x57B8: 'Park',
    0x57C8: 'UnPark',
    0x5D18: 'Reverse',
    0x5D28: 'Neutral',
    0x5D38: 'Drive',
    0x5D48: 'Low',
    0x52F8: 'Invalid',
    0x000F: 'MOVT #0x000F (cfstring MOVT)',
}

# Also interesting: MOVT #0x000F to find where cfstring section MOVT is
MOVT_IMMS = {
    0x000F: 'high 0x000F -> cfstring base',
}

with open(BINARY, 'rb') as f:
    data = f.read()

def decode_movw_movt(data, offset):
    """Return (op, Rd, imm16) for MOVW or MOVT at byte offset, or None."""
    if offset + 4 > len(data):
        return None
    hw1, hw2 = struct.unpack_from('<HH', data, offset)
    # HW1: bits[15:11] = 11110, bits[10]=i, bits[9:4]=10 0100 (MOVW) or 10 1100 (MOVT)
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

ARM_REGS = {0:'r0',1:'r1',2:'r2',3:'r3',4:'r4',5:'r5',6:'r6',7:'r7',
            8:'r8',9:'r9',10:'r10',11:'r11',12:'r12',13:'sp',14:'lr',15:'pc'}

print('=== MOVW/MOVT instructions for gear-related values ===')
for offset in range(0, len(data) - 4, 2):
    result = decode_movw_movt(data, offset)
    if result is None:
        continue
    op, Rd, imm16 = result
    vma = offset + VMA_BASE
    if imm16 in GEAR_IMMS:
        reg = ARM_REGS.get(Rd, f'r{Rd}')
        print(f'  VMA 0x{vma:08X}: {op:4s} {reg}, #0x{imm16:04X}  -> {GEAR_IMMS[imm16]!r}')
    elif op == 'MOVT' and imm16 in MOVT_IMMS:
        reg = ARM_REGS.get(Rd, f'r{Rd}')
        print(f'  VMA 0x{vma:08X}: {op:4s} {reg}, #0x{imm16:04X}  -> {MOVT_IMMS[imm16]}')
