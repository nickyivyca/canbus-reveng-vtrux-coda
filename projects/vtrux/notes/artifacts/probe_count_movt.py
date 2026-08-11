"""Count MOVT #0x000F instructions in various ranges."""
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

# First: verify we see MOVT #0x000F anywhere in the binary
print('=== MOVT #0x000F hits across whole binary (first 20) ===')
count = 0
for vma in range(VMA_BASE, 0xC0000, 2):
    off = vma - VMA_BASE
    if off + 4 > len(data): break
    hw1, hw2 = struct.unpack_from('<HH', data, off)
    r = decode_mov(hw1, hw2)
    if r and r[0] == 'MOVT' and r[2] == 0x000F:
        print(f'  VMA 0x{vma:08X}: MOVT r{r[1]}, #0x000F')
        count += 1
        if count >= 20:
            print('  ...')
            break

# Count all MOVT #0x000F in full binary
full_count = 0
for vma in range(VMA_BASE, VMA_BASE + len(data) - 4, 2):
    off = vma - VMA_BASE
    hw1, hw2 = struct.unpack_from('<HH', data, off)
    r = decode_mov(hw1, hw2)
    if r and r[0] == 'MOVT' and r[2] == 0x000F:
        full_count += 1
print(f'\nTotal MOVT #0x000F in full binary: {full_count}')

# Also: verify the 0xBE04 MOVT that was found by earlier scan
test_vma = 0x0000BE04
test_off = test_vma - VMA_BASE
print(f'\n=== Verify MOVT at VMA 0x{test_vma:08X} (foff 0x{test_off:06X}) ===')
hw1, hw2 = struct.unpack_from('<HH', data, test_off)
print(f'  bytes: {data[test_off]:02x} {data[test_off+1]:02x} {data[test_off+2]:02x} {data[test_off+3]:02x}')
r = decode_mov(hw1, hw2)
print(f'  decode: {r}')

# Check what precedes it
for prev_off in [test_off - 4, test_off - 2]:
    hw1p, hw2p = struct.unpack_from('<HH', data, prev_off)
    rp = decode_mov(hw1p, hw2p)
    if rp:
        print(f'  preceding at foff 0x{prev_off:06X}: {rp}')
