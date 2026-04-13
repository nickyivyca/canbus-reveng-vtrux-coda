"""Read CFString objects at specific VMAs from CANbusLogger2_ARM Mach-O slice.

For each VMA we want to decode:
  - find which segment/section it falls in
  - read the 16-byte CFString struct: [isa(4)][flags(4)][charsPtr(4)][len(4)]
  - follow charsPtr to read the actual string bytes

Also dumps all strings near those addresses for context.

file_offset = VMA - seg_vmaddr + seg_fileoff for the containing segment.
"""
import struct
import sys

BINARY = r"projects\vtrux\notes\artifacts\CANbusLogger2_ARM"

# VMAs of interest - from Ghidra decompiled code for bcm_alarm, bcm_chgc_stat,
# bcm_mainc_stat string arrays in 0x0410 parseEPRIMessage dispatch
TARGET_VMAS = [0x4fd8, 0x5748, 0x5808, 0x5828]

# Also find all cfstrings in the range around 0x4000-0x7000
SCAN_MIN = 0x4000
SCAN_MAX = 0x8000

def read32le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

with open(BINARY, 'rb') as f:
    raw = f.read()

# Parse Mach-O fat header - check if this is already an extracted slice or still fat
magic = struct.unpack_from('>I', raw, 0)[0]
print(f"Magic: 0x{magic:08X}")

if magic == 0xCEFAEDFE:  # ARM LE: 0xFEEDFACE in BE
    base = 0
    print("Single Mach-O slice (LE 32-bit)")
elif magic == 0xCAFEBABE:
    print("Fat binary - need to find ARM slice")
    narch = read32le(raw, 4)
    base = None
    for i in range(narch):
        off = 8 + i * 20
        cputype = struct.unpack_from('>I', raw, off)[0]
        offset = struct.unpack_from('>I', raw, off + 8)[0]
        size   = struct.unpack_from('>I', raw, off + 12)[0]
        print(f"  arch[{i}]: cputype=0x{cputype:08X} offset=0x{offset:X} size=0x{size:X}")
        if cputype == 12:  # ARM
            base = offset
    if base is None:
        print("ARM slice not found")
        sys.exit(1)
else:
    # Maybe already a raw slice starting with ARM LE magic
    le_magic = struct.unpack_from('<I', raw, 0)[0]
    if le_magic == 0xFEEDFACE:
        base = 0
        print("Single Mach-O slice (LE 32-bit, correct endian)")
    else:
        print(f"Unknown magic: 0x{magic:08X} / 0x{le_magic:08X}")
        sys.exit(1)

# Parse load commands to build VMA->file-offset map
ncmds = struct.unpack_from('<I', raw, base + 16)[0]
sizeofcmds = struct.unpack_from('<I', raw, base + 20)[0]

segments = []  # list of (segname, vmaddr, vmsize, fileoff, filesize, sections)

pos = base + 28  # skip mach_header (28 bytes for 32-bit)
for _ in range(ncmds):
    cmd     = struct.unpack_from('<I', raw, pos)[0]
    cmdsize = struct.unpack_from('<I', raw, pos + 4)[0]
    if cmd == 1:  # LC_SEGMENT
        segname  = raw[pos+8:pos+24].rstrip(b'\x00').decode('ascii', errors='replace')
        vmaddr   = struct.unpack_from('<I', raw, pos + 24)[0]
        vmsize   = struct.unpack_from('<I', raw, pos + 28)[0]
        fileoff  = struct.unpack_from('<I', raw, pos + 32)[0]
        filesize = struct.unpack_from('<I', raw, pos + 36)[0]
        nsects   = struct.unpack_from('<I', raw, pos + 48)[0]
        sections = []
        spos = pos + 56
        for s in range(nsects):
            secname  = raw[spos:spos+16].rstrip(b'\x00').decode('ascii', errors='replace')
            s_vmaddr = struct.unpack_from('<I', raw, spos + 32)[0]
            s_size   = struct.unpack_from('<I', raw, spos + 36)[0]
            s_off    = struct.unpack_from('<I', raw, spos + 40)[0]
            sections.append((secname, s_vmaddr, s_size, s_off))
            spos += 68
        segments.append((segname, vmaddr, vmsize, fileoff, filesize, sections))
        print(f"Segment {segname}: vmaddr=0x{vmaddr:X} vmsize=0x{vmsize:X} fileoff=0x{fileoff:X}")
        for s in sections:
            print(f"  Section {s[0]}: vmaddr=0x{s[1]:X} size=0x{s[2]:X} fileoff=0x{s[3]:X}")
    pos += cmdsize

def vma_to_fileoff(vma):
    for segname, vmaddr, vmsize, fileoff, filesize, sections in segments:
        if vmaddr <= vma < vmaddr + vmsize:
            return base + fileoff + (vma - vmaddr)
    return None

def read_cstring(vma):
    fo = vma_to_fileoff(vma)
    if fo is None:
        return f"<VMA 0x{vma:X} not mapped>"
    end = raw.index(b'\x00', fo)
    return raw[fo:end].decode('latin-1')

def read_cfstring(vma):
    fo = vma_to_fileoff(vma)
    if fo is None:
        return None, f"<not mapped>"
    # CFString struct: isa(4), flags(4), charsPtr(4), length(4)
    isa      = read32le(raw, fo)
    flags    = read32le(raw, fo + 4)
    charsPte = read32le(raw, fo + 8)
    length   = read32le(raw, fo + 12)
    s = read_cstring(charsPte)
    return length, s

print("\n=== Target VMAs ===")
for vma in TARGET_VMAS:
    length, s = read_cfstring(vma)
    print(f"  0x{vma:04X}: len={length}  \"{s}\"")

# Find and dump ALL cfstrings in the scan range
print(f"\n=== All CFStrings with VMA in [{SCAN_MIN:#x}, {SCAN_MAX:#x}) ===")
# Find __cfstring section
for segname, vmaddr, vmsize, fileoff, filesize, sections in segments:
    for secname, s_vmaddr, s_size, s_off in sections:
        if 'cfstring' in secname.lower():
            print(f"\nSection {secname} @ vmaddr=0x{s_vmaddr:X}, size=0x{s_size:X}")
            for i in range(0, s_size, 16):
                entry_vma = s_vmaddr + i
                fo = base + s_off + i
                if fo + 16 > len(raw):
                    break
                charsPte = read32le(raw, fo + 8)
                length   = read32le(raw, fo + 12)
                try:
                    s = read_cstring(charsPte)
                except Exception:
                    s = "<read error>"
                print(f"  VMA 0x{entry_vma:05X}: len={length:3d}  \"{s}\"")
