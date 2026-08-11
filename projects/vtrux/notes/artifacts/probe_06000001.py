"""
Find the 0x06000001 compare in the binary, then look at surrounding code
to determine the gear array construction.

Also try VLD1/VLDR instructions which may load cfstring addresses into NEON registers.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

with open(BINARY, 'rb') as f:
    data = f.read()

ARM_REGS = {i: f'r{i}' for i in range(16)}
ARM_REGS[13]='sp'; ARM_REGS[14]='lr'; ARM_REGS[15]='pc'

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

# Strategy 1: find MOVW #0x0001 followed by MOVT #0x0600 (constructing 0x06000001)
print('=== Strategy 1: MOVW #0x0001 + MOVT #0x0600 (GoPoint ID 0x06000001) ===')
prev = None
for vma in range(VMA_BASE, VMA_BASE + len(data) - 4, 2):
    off = vma - VMA_BASE
    hw1, hw2 = struct.unpack_from('<HH', data, off)
    r = decode_mov(hw1, hw2)
    if r is None:
        prev = None
        continue
    op, Rd, imm16 = r
    if op == 'MOVT' and imm16 == 0x0600:
        if prev and prev[0] == 'MOVW' and prev[2] == 0x0001:
            print(f'  MOVW VMA 0x{prev[3]:08X}: MOVW r{Rd}, #0x0001')
            print(f'  MOVT VMA 0x{vma:08X}: MOVT r{Rd}, #0x0600  -> 0x06000001')
            # Show next 128 bytes decoded
            print(f'  Context after MOVT:')
            ctx_off = vma - VMA_BASE + 4
            ctx_prev = None
            for i in range(0, 80, 2):
                cvma = vma + 4 + i
                coff = cvma - VMA_BASE
                if coff + 4 > len(data): break
                ch1, ch2 = struct.unpack_from('<HH', data, coff)
                cr = decode_mov(ch1, ch2)
                if cr:
                    cop, cRd, cimm = cr
                    # If this is a MOVT #0x000F, show it
                    if cop == 'MOVT' and cimm == 0x000F:
                        print(f'    VMA 0x{cvma:08X}: MOVT r{cRd}, #0x000F  <- cfstring MOVT!')
                    elif cop == 'MOVW':
                        print(f'    VMA 0x{cvma:08X}: MOVW r{cRd}, #0x{cimm:04X}')
            print()
    prev = (op, Rd, imm16, vma)

# Strategy 2: search for the 32-bit literal 0x06000001 in data
print('=== Strategy 2: raw 0x06000001 in binary data ===')
target = struct.pack('<I', 0x06000001)
pos = 0
found = 0
while True:
    pos = data.find(target, pos)
    if pos < 0: break
    vma = pos + VMA_BASE
    print(f'  foff=0x{pos:06X}  VMA=0x{vma:08X}')
    found += 1
    pos += 1
if not found:
    print('  Not found as raw 32-bit LE word')
