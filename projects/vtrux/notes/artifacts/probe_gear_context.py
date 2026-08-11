"""
Look at the ARM instructions around the MOVW Park/UnPark occurrences
to determine what the adjacent entries in the gear array are.
Disassemble ~80 bytes around each MOVW hit.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

ARM_REGS = {0:'r0',1:'r1',2:'r2',3:'r3',4:'r4',5:'r5',6:'r6',7:'r7',
            8:'r8',9:'r9',10:'r10',11:'r11',12:'r12',13:'sp',14:'lr',15:'pc'}

# Gear-related MOVW immediates
GEAR_IMMS = {
    0x57B8: 'Park',    0x57C8: 'UnPark',
    0x5D08: '%08X',    0x5D18: 'Reverse',
    0x5D28: 'Neutral', 0x5D38: 'Drive',
    0x5D48: 'Low',     0x52F8: 'Invalid',
}

def decode_t2_mov(data, offset):
    """Try to decode any known Thumb-2 32-bit instruction at offset.
    Returns a description string or None."""
    if offset + 4 > len(data):
        return None
    hw1, hw2 = struct.unpack_from('<HH', data, offset)
    top5 = (hw1 >> 11) & 0x1F
    if top5 != 0b11110:
        return None
    bits_9_4 = (hw1 >> 4) & 0x3F
    if bits_9_4 in (0b100100, 0b101100):
        op = 'MOVW' if bits_9_4 == 0b100100 else 'MOVT'
        if (hw2 >> 15) & 1 != 0:
            return None
        i    = (hw1 >> 10) & 1
        imm4 = hw1 & 0xF
        imm3 = (hw2 >> 12) & 0x7
        Rd   = (hw2 >> 8) & 0xF
        imm8 = hw2 & 0xFF
        imm16 = (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8
        reg = ARM_REGS.get(Rd, f'r{Rd}')
        label = GEAR_IMMS.get(imm16, '')
        if label:
            label = f'  <- {label!r}'
        return f'{op:4s} {reg}, #0x{imm16:04X}{label}'
    return None

def decode_vmov(data, offset):
    """Try to decode VMOV.32 dN[x], Rt or LDR Rt, [pc, #imm].
    Returns description or None."""
    if offset + 4 > len(data):
        return None
    hw1, hw2 = struct.unpack_from('<HH', data, offset)
    # Check for T2 encoding of LDR Rt, [PC, #imm12]
    # HW1: 11111 000 1101 1111 = 0xF89F (check bits)
    # Actually LDR literal T3: 1111 1000 U 101 1111 = 0xF85F (subtract) or 0xF89F (add)
    # No, let me check if hw1 encodes something useful
    return None

def show_context(data, center_vma, window=60):
    """Print Thumb-2 instructions around center_vma."""
    start = center_vma - window
    end   = center_vma + window
    start = max(start, VMA_BASE)
    print(f'  --- context around VMA 0x{center_vma:08X} ---')
    offset = start - VMA_BASE
    while offset < end - VMA_BASE:
        vma = offset + VMA_BASE
        result = decode_t2_mov(data, offset)
        if result:
            marker = '>>>' if vma == center_vma else '   '
            print(f'  {marker} VMA 0x{vma:08X}: {result}')
            offset += 4
        else:
            offset += 2

with open(BINARY, 'rb') as f:
    data = f.read()

# Hits from earlier scan:
MOVW_PARK_VMAS = [0x00066834, 0x00068C00]

for vma in MOVW_PARK_VMAS:
    print()
    show_context(data, vma, window=120)
