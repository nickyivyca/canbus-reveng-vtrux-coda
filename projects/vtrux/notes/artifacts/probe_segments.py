"""
Parse Mach-O segment/section layout to understand VMA->fileoff deltas.
Then verify where parseEPRIMessage (VMA 0x25D00) is, and check bytes there.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

MH_MAGIC = 0xFEEDFACE
LC_SEGMENT = 0x1

def read32(f):
    return struct.unpack('<I', f.read(4))[0]

def read_macho_sections(path):
    sections = []
    segments = []
    with open(path, 'rb') as f:
        magic = read32(f)
        if magic != MH_MAGIC:
            print(f'Unexpected magic: 0x{magic:08X}')
            return [], []
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
                segname  = f.read(16).rstrip(b'\x00').decode('ascii', errors='replace')
                vmaddr   = read32(f)
                vmsize   = read32(f)
                fileoff  = read32(f)
                filesize = read32(f)
                maxprot  = read32(f)
                initprot = read32(f)
                nsects   = read32(f)
                f.read(4)  # flags
                delta = vmaddr - fileoff if fileoff != 0 else None
                segments.append((segname, vmaddr, vmsize, fileoff, filesize, delta))
                for _ in range(nsects):
                    sname     = f.read(16).rstrip(b'\x00').decode('ascii', errors='replace')
                    f.read(16)  # segment name (skip)
                    s_vmaddr  = read32(f)
                    s_vmsize  = read32(f)
                    s_fileoff = read32(f)
                    f.read(24)  # remaining section fields
                    s_delta = s_vmaddr - s_fileoff if s_fileoff != 0 else None
                    sections.append((segname, sname, s_vmaddr, s_vmsize, s_fileoff, s_delta))
            f.seek(cmd_start + size)
    return segments, sections

segments, sections = read_macho_sections(BINARY)

print('=== Segments ===')
for seg, vmaddr, vmsize, fileoff, filesize, delta in segments:
    d = f'delta=0x{delta:X}' if delta is not None else 'fileoff=0 (no delta)'
    print(f'  {seg:16s}  vmaddr=0x{vmaddr:08X}  fileoff=0x{fileoff:08X}  {d}')

print()
print('=== All sections ===')
for seg, sec, vmaddr, vmsize, fileoff, delta in sections:
    d = f'delta=0x{delta:X}' if delta is not None else 'fileoff=0'
    name = f'{seg},{sec}'
    print(f'  {name:32s}  vmaddr=0x{vmaddr:08X}  foff=0x{fileoff:08X}  {d}')

# Verify parseEPRIMessage start
parse_vma = 0x00025D00
for seg, sec, vmaddr, vmsize, fileoff, delta in sections:
    if vmaddr <= parse_vma < vmaddr + vmsize:
        foff = parse_vma - delta if delta is not None else parse_vma - 0x4000
        print(f'\nparseEPRIMessage VMA 0x{parse_vma:08X} is in {seg},{sec}  foff=0x{foff:06X}')
        with open(BINARY, 'rb') as f:
            f.seek(foff)
            raw = f.read(16)
        print(f'  bytes: {" ".join(f"{b:02x}" for b in raw)}')
        break

# Check where VMA 0x66834 (MOVW Park site) falls
park_vma = 0x00066834
for seg, sec, vmaddr, vmsize, fileoff, delta in sections:
    if vmaddr <= park_vma < vmaddr + vmsize:
        foff = park_vma - delta if delta is not None else park_vma - 0x4000
        print(f'\nMOVW Park site VMA 0x{park_vma:08X} is in {seg},{sec}  foff=0x{foff:06X}')
        with open(BINARY, 'rb') as f:
            f.seek(foff)
            raw = f.read(8)
        print(f'  bytes: {" ".join(f"{b:02x}" for b in raw)}')
        break
