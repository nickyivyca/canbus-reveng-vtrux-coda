"""
Probe the binary to understand actual cfstring struct layout
and locate the __cfstring section.

Strategy:
1. Parse Mach-O load commands to find __cfstring section vmaddr/fileoff
2. Dump raw bytes at the candidate VMAs to see what's actually there
3. Try reading cfstring structs with the correct file-offset formula
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

MH_MAGIC = 0xFEEDFACE  # 32-bit LE Mach-O (bytes CE FA ED FE on disk, read as LE)
LC_SEGMENT = 0x1

def read32(f):
    return struct.unpack('<I', f.read(4))[0]

def read_macho_sections(path):
    """Return list of (segname, sectname, vmaddr, fileoff, size)."""
    sections = []
    with open(path, 'rb') as f:
        magic = read32(f)
        assert magic == MH_MAGIC, f'unexpected magic 0x{magic:08X}'
        f.read(4)   # cputype
        f.read(4)   # cpusubtype
        f.read(4)   # filetype
        ncmds = read32(f)
        sizeofcmds = read32(f)
        f.read(4)   # flags

        for _ in range(ncmds):
            cmd_start = f.tell()
            cmd  = read32(f)
            size = read32(f)
            if cmd == LC_SEGMENT:
                segname = f.read(16).rstrip(b'\x00').decode('ascii', errors='replace')
                vmaddr  = read32(f)
                vmsize  = read32(f)
                fileoff = read32(f)
                filesize= read32(f)
                maxprot = read32(f)
                initprot= read32(f)
                nsects  = read32(f)
                f.read(4)  # flags
                for _ in range(nsects):
                    sname   = f.read(16).rstrip(b'\x00').decode('ascii', errors='replace')
                    _seg    = f.read(16)
                    s_vmaddr  = read32(f)
                    s_vmsize  = read32(f)
                    s_fileoff = read32(f)
                    # section struct tail: align,reloff,nreloc,flags,reserved1,reserved2 = 6*4=24 bytes
                    f.read(24)
                    sections.append((segname, sname, s_vmaddr, s_fileoff, s_vmsize))
            f.seek(cmd_start + size)
    return sections

sections = read_macho_sections(BINARY)
print('=== Mach-O sections ===')
for seg, sec, vmaddr, fileoff, size in sections:
    line = f'  {seg:12s} {sec:20s}  vmaddr=0x{vmaddr:08X}  fileoff=0x{fileoff:08X}  size=0x{size:X}'
    print(line.encode('ascii', errors='replace').decode('ascii'))

# Find __cfstring and __cstring sections
cfstring_sec = None
cstring_sec  = None
for seg, sec, vmaddr, fileoff, size in sections:
    if sec == '__cfstring':
        cfstring_sec = (seg, sec, vmaddr, fileoff, size)
    if sec == '__cstring':
        cstring_sec  = (seg, sec, vmaddr, fileoff, size)

print()
if cfstring_sec:
    print(f'__cfstring: vmaddr=0x{cfstring_sec[2]:08X}  fileoff=0x{cfstring_sec[3]:08X}  size=0x{cfstring_sec[4]:X}')
    print(f'  vma->fileoff delta: 0x{cfstring_sec[2]-cfstring_sec[3]:X}')
if cstring_sec:
    print(f'__cstring:  vmaddr=0x{cstring_sec[2]:08X}  fileoff=0x{cstring_sec[3]:08X}  size=0x{cstring_sec[4]:X}')
    print(f'  vma->fileoff delta: 0x{cstring_sec[2]-cstring_sec[3]:X}')

# Dump raw bytes at VMA 0x56B8 using simple formula vma-0x4000
print()
print('=== Raw bytes at VMA 0x56B8 (file offset 0x12B8, formula vma-0x4000) ===')
with open(BINARY, 'rb') as f:
    f.seek(0x56B8 - 0x4000)
    raw = f.read(64)
    for i in range(0, 64, 16):
        chunk = raw[i:i+16]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        print(f'  +{i:02X}: {hex_str}')

# Also dump using cfstring section's actual fileoff formula
if cfstring_sec:
    cf_delta = cfstring_sec[2] - cfstring_sec[3]  # vmaddr - fileoff
    vma_target = 0x56B8
    fo = vma_target - cf_delta
    print()
    print(f'=== Raw bytes at VMA 0x56B8 using cfstring delta (file offset 0x{fo:X}) ===')
    with open(BINARY, 'rb') as f:
        f.seek(fo)
        raw = f.read(64)
        for i in range(0, 64, 16):
            chunk = raw[i:i+16]
            hex_str = ' '.join(f'{b:02x}' for b in chunk)
            print(f'  +{i:02X}: {hex_str}')
