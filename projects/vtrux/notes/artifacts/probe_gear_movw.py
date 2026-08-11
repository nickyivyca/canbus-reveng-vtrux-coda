"""
Scan the parseEPRIMessage function (VMA 0x00025D00) for Thumb-2 MOVW instructions
to determine which registers were loaded with 0x57C8 ('UnPark') vs 0x5D18 ('Reverse')
and 0x5D38 ('Drive').

Thumb-2 MOVW encoding (T3, 32-bit):
  HW1: 11110 i 10010 0 imm4  (bits 31..16)
  HW2: 0 imm3 Rd imm8        (bits 15..0)
  imm16 = imm4 : i : imm3 : imm8

On disk (little-endian, two 16-bit halfwords stored LE):
  byte0 = HW1[7:0]  = (i<<6) | 0x40 | imm4 (approximately)
  byte1 = HW1[15:8] = 0xF2 (if i=0) or 0xF6 (if i=1) -- specifically bits[15:11]=11110
  byte2 = HW2[7:0]  = imm8
  byte3 = HW2[15:8] = (imm3 << 4) | Rd

More precisely:
  HW1 = (0b11110 << 11) | (i << 10) | (0b10010 << 5) | imm4
      = 0xF240 | (i << 10) | imm4      -- 0b11110_0_10010_0_imm4
  Actually: 0b1111_0_i_1_0_0100_imm4
  bit15..11 = 11110, bit10 = i, bit9..4 = 100100, bit3..0 = imm4

Let me just decompose directly:
  HW1 bits: 1111 0 i 1001 00 imm4
  -> for i=0: 1111 0010 0100 imm4 = 0xF24X where X = imm4
  -> for i=1: 1111 0110 0100 imm4 = 0xF64X where X = imm4

  As LE 2 bytes on disk: [0x24X | (low_bits), 0xF2 or 0xF6]
  Actually HW1 byte0 = lower byte of HW1 = bits[7:0] of HW1
           HW1 byte1 = upper byte of HW1 = bits[15:8] of HW1

  HW1 = 1111_0_i_10_0100_imm4
  bits[15:8] = 1111_0_i_10 = 0xF2 (i=0) or 0xF6 (i=1)
  bits[7:4] = 0100, bits[3:0] = imm4

  So HW1 LE bytes = [0x40 | imm4, 0xF2 or 0xF6]

  HW2 bits: 0_imm3_Rd_imm8
  bits[15] = 0, bits[14:12] = imm3, bits[11:8] = Rd, bits[7:0] = imm8
  HW2 LE bytes = [imm8, (imm3 << 4) | Rd]
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

def vma_to_foff(vma):
    return vma - VMA_BASE

def decode_movw(hw1, hw2):
    """
    Decode a Thumb-2 MOVW (T3 encoding) from two 16-bit halfwords.
    Returns (Rd, imm16) or None if not MOVW.
    hw1 and hw2 are integers read as LE uint16.
    """
    # Check HW1 pattern: 1111 0 i 10 0100 imm4
    # bits[15:11] must be 11110 = 0x1E
    # bits[9:4] must be 100100 = 0x24 (but bits [10] = i, [9:4] = 100100)
    # Actually: bit15=1,14=1,13=1,12=1,11=0 = top 5 bits = 11110
    # bit10 = i (don't care for identification)
    # bits[9:4] = 10 0100 = 100100
    top5 = (hw1 >> 11) & 0x1F
    if top5 != 0b11110:
        return None
    bits_9_4 = (hw1 >> 4) & 0x3F
    if bits_9_4 != 0b100100:
        return None
    # Check HW2 bit15 = 0
    if (hw2 >> 15) & 1 != 0:
        return None

    i    = (hw1 >> 10) & 1
    imm4 = hw1 & 0xF
    imm3 = (hw2 >> 12) & 0x7
    Rd   = (hw2 >> 8) & 0xF
    imm8 = hw2 & 0xFF

    imm16 = (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8
    return (Rd, imm16)

# Scan parseEPRIMessage (VMA 0x00025D00) for MOVW instructions with gear-related immediates
FUNC_VMA_START = 0x00025D00
FUNC_VMA_END   = 0x00027C00  # generous upper bound (it's a big function)

TARGETS = {
    0x57B8: 'Park',
    0x57C8: 'UnPark',
    0x57D8: 'Park Request (fmt)',
    0x5D08: '%08X (fmt)',
    0x5D18: 'Reverse',
    0x5D28: 'Neutral',
    0x5D38: 'Drive',
    0x5D48: 'Low',
    0x5D58: 'GearlevFmt',
    0x52F8: 'Invalid',
}

ARM_REG_NAMES = {0:'r0',1:'r1',2:'r2',3:'r3',4:'r4',5:'r5',6:'r6',7:'r7',
                 8:'r8',9:'r9',10:'r10',11:'r11',12:'r12',13:'sp',14:'lr',15:'pc'}

print('=== MOVW instructions with gear-related immediates in parseEPRIMessage ===')
with open(BINARY, 'rb') as f:
    f.seek(vma_to_foff(FUNC_VMA_START))
    count = (FUNC_VMA_END - FUNC_VMA_START) // 2
    for i in range(count - 1):
        vma = FUNC_VMA_START + i * 2
        f.seek(vma_to_foff(vma))
        raw = f.read(4)
        if len(raw) < 4:
            break
        hw1, hw2 = struct.unpack('<HH', raw)
        result = decode_movw(hw1, hw2)
        if result is not None:
            Rd, imm16 = result
            if imm16 in TARGETS:
                reg = ARM_REG_NAMES.get(Rd, f'r{Rd}')
                label = TARGETS[imm16]
                print(f'  VMA 0x{vma:08X}: MOVW {reg}, #0x{imm16:04X}  -> {label!r}')
