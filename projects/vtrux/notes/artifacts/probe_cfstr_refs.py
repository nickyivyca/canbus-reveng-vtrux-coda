"""
Search for cfstring struct addresses in the code/data sections.
The binary may store these as 32-bit LE values in literal pools.
Scan byte-by-byte to avoid alignment issues.
Also check the Mach-O rebase info to understand what addresses are fixed up.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
VMA_BASE = 0x4000

with open(BINARY, 'rb') as f:
    data = f.read()

# These are the cfstring struct VMAs we're looking for
TARGETS = {
    0x000F57B8: 'cfstr_Park',
    0x000F57C8: 'cfstr_UnPark',
    0x000F5D18: 'cfstr_Reverse',
    0x000F5D28: 'cfstr_Neutral',
    0x000F5D38: 'cfstr_Drive',
    0x000F5D48: 'cfstr_Low',
    0x000F52F8: 'cfstr_Invalid',
}

print('=== Byte-by-byte search for cfstring VMAs ===')
found_any = False
for off in range(len(data) - 3):
    word = struct.unpack_from('<I', data, off)[0]
    if word in TARGETS:
        found_any = True
        vma = off + VMA_BASE
        print(f'  foff=0x{off:06X} VMA=0x{vma:08X}: {TARGETS[word]}')
if not found_any:
    print('  None found.')

# Check Mach-O dyld_chained_fixups or rebase opcodes
# These are in __LINKEDIT and explain why addresses aren't literal in the binary
# For now, just check what the __LINKEDIT section contains near rebase info

# Parse LC_DYSYMTAB and LC_DYLD_INFO to find rebase info location
MH_MAGIC = 0xFEEDFACE
LC_DYSYMTAB = 0xB
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022

def read32(f): return struct.unpack('<I', f.read(4))[0]

print()
print('=== Mach-O load commands for dyld info ===')
with open(BINARY, 'rb') as f:
    magic = read32(f)
    f.read(16)  # skip cputype,cpusubtype,filetype,ncmds
    f.seek(16)
    ncmds = read32(f)
    _ = read32(f)  # sizeofcmds
    _ = read32(f)  # flags
    for _ in range(ncmds):
        cmd_start = f.tell()
        cmd  = read32(f)
        size = read32(f)
        if cmd in (LC_DYSYMTAB,):
            print(f'  LC_DYSYMTAB at 0x{cmd_start:06X}')
            indirectsymoff = struct.unpack('<I', f.read(4))[0] if False else 0  # skip
        elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            rebase_off  = read32(f); rebase_size  = read32(f)
            bind_off    = read32(f); bind_size    = read32(f)
            weak_off    = read32(f); weak_size    = read32(f)
            lazy_off    = read32(f); lazy_size    = read32(f)
            export_off  = read32(f); export_size  = read32(f)
            print(f'  LC_DYLD_INFO_ONLY: rebase_off=0x{rebase_off:06X} size=0x{rebase_size:04X}')
            print(f'                     bind_off=0x{bind_off:06X} size=0x{bind_size:04X}')
            # Read first 64 bytes of rebase info to understand encoding
            print()
            print('  First 48 bytes of rebase opcodes:')
            rb = data[rebase_off:rebase_off+48]
            print(' '.join(f'{b:02x}' for b in rb))
            # Decode rebase opcodes
            print()
            print('  Decoded rebase opcodes (first 20):')
            i = 0; n = 0
            while i < len(rb) and n < 20:
                b = rb[i]; i += 1
                opcode = b & 0xF0; imm = b & 0x0F
                if opcode == 0x00: print('    DONE'); break
                elif opcode == 0x10: print(f'    SET_TYPE_IMM {imm}')
                elif opcode == 0x20: print(f'    SET_SEG_AND_OFFSET_ULEB seg={imm}')
                elif opcode == 0x30:
                    # read ULEB128
                    val = 0; shift = 0
                    while True:
                        bb = rb[i]; i += 1
                        val |= (bb & 0x7F) << shift; shift += 7
                        if not (bb & 0x80): break
                    print(f'    ADD_ADDR_ULEB 0x{val:X}')
                elif opcode == 0x40: print(f'    ADD_ADDR_IMM_SCALED {imm}')
                elif opcode == 0x50: print(f'    DO_REBASE_IMM_TIMES {imm}')
                elif opcode == 0x60: print(f'    DO_REBASE_ULEB_TIMES')
                elif opcode == 0x70: print(f'    DO_REBASE_ADD_ADDR_ULEB')
                elif opcode == 0x80: print(f'    DO_REBASE_ULEB_TIMES_SKIPPING_ULEB')
                else: print(f'    UNKNOWN 0x{b:02X}')
                n += 1
        f.seek(cmd_start + size)
