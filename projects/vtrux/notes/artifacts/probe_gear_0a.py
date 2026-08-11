"""
Investigate MOVT #0x000A cfstrings and map cfstring section locations.
"""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

def foff(vma):
    return vma - 0x4000

def read_cstring(data, foff_ptr):
    """Read null-terminated string at file offset."""
    end = data.index(b'\x00', foff_ptr)
    return data[foff_ptr:end].decode('utf-8', errors='replace')

with open(BINARY, 'rb') as f:
    data = f.read()

print(f'Binary size: 0x{len(data):X} bytes')

# Check what's at VMA 0x000A57B8 (cfstring struct?)
vma_a = 0x000A57B8
off_a = foff(vma_a)
print(f'\n=== VMA 0x{vma_a:08X} (foff 0x{off_a:06X}) ===')
if off_a + 16 <= len(data):
    raw = data[off_a:off_a+16]
    isa, flags, ptr, length = struct.unpack_from('<IIII', data, off_a)
    print(f'  raw: {" ".join(f"{b:02x}" for b in raw)}')
    print(f'  isa=0x{isa:08X}  flags=0x{flags:08X}  ptr=0x{ptr:08X}  len={length}')
    if flags in (0x7C8, 0x7D0, 0xC8, 0x3E8, 0x7C8):
        ptr_foff = ptr - 0x4000
        if 0 <= ptr_foff < len(data):
            try:
                s = read_cstring(data, ptr_foff)
                print(f'  string: {s!r}')
            except Exception as e:
                print(f'  string read error: {e}')
else:
    print('  Out of range!')

# Scan for __cfstring section start by looking for isa pointer patterns
# The __cfstring section entries have flags=0x000007C8 (typically)
# Let's find the section by scanning for 4-tuples where flags=0x7C8 and length matches ptr string
print()
print('=== Scanning for cfstring section start (first entry with flags=0x7C8) ===')
found = 0
for off in range(0, len(data) - 16, 16):
    isa, flags, ptr, length = struct.unpack_from('<IIII', data, off)
    if flags == 0x000007C8 and length > 0 and length < 100:
        ptr_off = ptr - 0x4000
        if 0 <= ptr_off < len(data) - length:
            # Try to read the string
            try:
                s = data[ptr_off:ptr_off+length+1]
                if s[-1] == 0 and all(32 <= b < 128 or b >= 128 for b in s[:-1]):
                    vma = off + 0x4000
                    print(f'  foff=0x{off:06X}  VMA=0x{vma:08X}  isa=0x{isa:08X}  -> {s[:-1].decode("utf-8","replace")!r}')
                    found += 1
                    if found >= 20:
                        print('  (stopping after 20 hits)')
                        break
            except Exception:
                pass

# Also check what cfstring section is at 0x000A3D28 or nearby
print()
print('=== Checking cfstring structs in 0x000A range ===')
for vma_start in [0x000A0000, 0x000A3D28, 0x000A57B0]:
    off = foff(vma_start)
    if off < 0 or off + 16 > len(data):
        print(f'  VMA 0x{vma_start:08X} out of range (foff=0x{off:06X})')
        continue
    isa, flags, ptr, length = struct.unpack_from('<IIII', data, off)
    print(f'  VMA 0x{vma_start:08X}: isa=0x{isa:08X}  flags=0x{flags:08X}  ptr=0x{ptr:08X}  len={length}')
