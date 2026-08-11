"""
Scan the parseEPRIMessage function's byte range for 32-bit words matching
the gear-related cfstring VMAs. These would be in the literal pool (LDR PC-relative).
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

def vma_to_foff(vma):
    return vma - VMA_BASE

FUNC_VMA_START = 0x00025D00
FUNC_VMA_END   = 0x00028000  # generous upper bound

TARGETS = {
    0x000F57B8: 'Park',
    0x000F57C8: 'UnPark',
    0x000F5D18: 'Reverse',
    0x000F5D28: 'Neutral',
    0x000F5D38: 'Drive',
    0x000F5D48: 'Low',
    0x000F52F8: 'Invalid',
}

print('=== Literal pool words matching gear cfstring VMAs in parseEPRIMessage range ===')
with open(BINARY, 'rb') as f:
    f.seek(vma_to_foff(FUNC_VMA_START))
    nbytes = FUNC_VMA_END - FUNC_VMA_START
    data = f.read(nbytes)

for offset in range(0, len(data) - 3, 4):
    word = struct.unpack_from('<I', data, offset)[0]
    if word in TARGETS:
        vma = FUNC_VMA_START + offset
        print(f'  file_off=0x{vma_to_foff(vma):06X}  VMA 0x{vma:08X}: 0x{word:08X}  -> {TARGETS[word]!r}')
