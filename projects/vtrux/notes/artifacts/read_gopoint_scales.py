"""
Read two float scale constants from the CANbusLogger2 ARMv7 binary.

DAT_00027b10 -- EAC_Elec_Curr scale (Amps/LSB), used as a double in:
    (float)((double)(float)bVar67 * DAT_00027b10)

DAT_00029588 -- Veh_Speed scale (km/h/LSB), used in a SIMD float multiply:
    FloatVectorMult(speed_raw_float, CONCAT44(extraout_s1_05, DAT_00029588), 2, 0x20)

VMA base = 0x4000, so file_offset = VMA - 0x4000.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

def vma_to_offset(vma):
    return vma - 0x4000

with open(BINARY, 'rb') as f:
    # --- DAT_00027b10 (AC current scale) ---
    # The multiply is (double)(float)x * DAT_00027b10, so try double first,
    # then float as fallback.
    f.seek(vma_to_offset(0x27b10))
    raw8 = f.read(8)
    as_f64 = struct.unpack('<d', raw8)[0]
    as_f32 = struct.unpack('<f', raw8[:4])[0]
    print(f'DAT_00027b10  raw: {raw8.hex()}')
    print(f'  float32: {as_f32}')
    print(f'  float64: {as_f64}')

    # --- DAT_00029588 (vehicle speed scale) ---
    # SIMD float (32-bit), packed with an adjacent float in a 64-bit register pair.
    f.seek(vma_to_offset(0x29588))
    raw8b = f.read(8)
    as_f32b = struct.unpack('<f', raw8b[:4])[0]
    as_f64b = struct.unpack('<d', raw8b)[0]
    print()
    print(f'DAT_00029588  raw: {raw8b.hex()}')
    print(f'  float32: {as_f32b}')
    print(f'  float64: {as_f64b}')

    # Also read the adjacent float (the other lane of the SIMD pair)
    # extraout_s1_05 is loaded alongside DAT_00029588 in the CONCAT44 call;
    # it occupies the upper 32 bits of the 64-bit SIMD register.
    print(f'  adjacent float32 (upper lane): {struct.unpack("<f", raw8b[4:])[0]}')
