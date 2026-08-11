"""
Search for cfstring-loading MOVT/MOVW pairs within parseEPRIMessage.

parseEPRIMessage is at VMA 0x25D00. It's a HUGE function (see decompile).
The 0x06000001 case constructs a 6-entry gear array.

Strategy:
1. Find MOVT #0x000F instructions in the range 0x25D00..0x28000
2. Print the MOVW that precedes each MOVT #0x000F
3. This will show which cfstring addresses are constructed

Also: dump the first 32 bytes of the function to confirm it's the right place.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

ARM_REGS = {0:'r0',1:'r1',2:'r2',3:'r3',4:'r4',5:'r5',6:'r6',7:'r7',
            8:'r8',9:'r9',10:'r10',11:'r11',12:'r12',13:'sp',14:'lr',15:'pc'}

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

GEAR_IMMS = {
    0x57B8: 'Park',   0x57C8: 'UnPark',
    0x5D08: '%08X',   0x5D18: 'Reverse',
    0x5D28: 'Neutral', 0x5D38: 'Drive',
    0x5D48: 'Low',    0x52F8: 'Invalid',
}

CFSTR_IMMS_MOVT = {0x000F: 'cfstring-section'}

with open(BINARY, 'rb') as f:
    data = f.read()

# Dump first 32 bytes at parseEPRIMessage to confirm
parse_foff = 0x021D00
print('=== First 32 bytes of parseEPRIMessage (foff 0x021D00) ===')
raw = data[parse_foff:parse_foff+32]
print(' '.join(f'{b:02x}' for b in raw))
print()

# Decode Thumb-2 MOV instructions in a wide range around parseEPRIMessage
# The 0x06000001 case might be far from the function start
# Scan 0x25D00 to 0x70000 (conservative upper bound)
SCAN_START_VMA = 0x00025D00
SCAN_END_VMA   = 0x00070000

print(f'=== MOVT/MOVW pairs in VMA 0x{SCAN_START_VMA:X}..0x{SCAN_END_VMA:X} ===')
print('Looking for MOVT #0x000F preceded by MOVW #gear_imm...')
print()

prev = None  # (op, Rd, imm16, vma)
for vma in range(SCAN_START_VMA, SCAN_END_VMA - 4, 2):
    off = vma - VMA_BASE
    hw1, hw2 = struct.unpack_from('<HH', data, off)
    r = decode_mov(hw1, hw2)
    if r is None:
        prev = None
        continue
    op, Rd, imm16 = r
    if op == 'MOVT' and imm16 == 0x000F:
        # Found a cfstring MOVT — look for preceding MOVW
        if prev and prev[0] == 'MOVW' and prev[1] == Rd:
            movw_imm = prev[2]
            label = GEAR_IMMS.get(movw_imm, '')
            if label:
                reg = ARM_REGS.get(Rd, f'r{Rd}')
                print(f'  VMA 0x{prev[3]:08X}: MOVW {reg}, #0x{movw_imm:04X}  -> {label!r}')
                print(f'  VMA 0x{vma:08X}: MOVT {reg}, #0x{imm16:04X}')
                print()
    prev = (op, Rd, imm16, vma)
