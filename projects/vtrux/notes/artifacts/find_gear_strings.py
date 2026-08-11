"""
Scan all cfstrings in the binary and find gear/drive-position-related strings,
then print each with its VMA so we can locate the correct array start.

Also prints full context (adjacent cfstrings) around any hits so we can see
whether the entries before/after are consistent with a gear enum.
"""
import struct, sys

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
CFSTRING_VMA  = 0x000F3D28
CFSTRING_SIZE = 0x71B0

def vma_off(vma):
    return vma - 0x4000

def read_cstring(f, ptr):
    try:
        f.seek(vma_off(ptr))
        buf = b''
        while True:
            ch = f.read(1)
            if not ch or ch == b'\x00':
                break
            buf += ch
        return buf.decode('utf-8', errors='replace')
    except Exception:
        return None

# Load all cfstrings into a list: (vma, string)
all_cf = []
with open(BINARY, 'rb') as f:
    n = CFSTRING_SIZE // 16
    for i in range(n):
        vma = CFSTRING_VMA + i * 16
        f.seek(vma_off(vma))
        raw = f.read(16)
        if len(raw) < 16:
            break
        _isa, _flags, ptr, length = struct.unpack('<IIII', raw)
        if ptr == 0:
            all_cf.append((vma, None))
            continue
        s = read_cstring(f, ptr)
        all_cf.append((vma, s))

KEYWORDS = ['drive', 'gear', 'park', 'reverse', 'neutral', 'low', 'invalid',
            'forward', 'prnd', 'position', 'dnrp', 'sport', 'manual', 'transmission']

hit_indices = set()
for idx, (vma, s) in enumerate(all_cf):
    if s and any(k in s.lower() for k in KEYWORDS):
        hit_indices.add(idx)

# Print hits with ±3 context entries
printed = set()
for idx in sorted(hit_indices):
    block_start = max(0, idx - 3)
    block_end   = min(len(all_cf) - 1, idx + 3)
    if block_start in printed:
        block_start = max(printed) + 1
    if block_start > block_end:
        continue
    print(f'--- hit at index {idx} (VMA 0x{all_cf[idx][0]:08X}) ---')
    for j in range(block_start, block_end + 1):
        vma, s = all_cf[j]
        marker = ' >>>' if j == idx else '    '
        line = f'{marker} [{j:4d}] VMA 0x{vma:08X}  {s!r}'
        sys.stdout.buffer.write((line + '\n').encode('utf-8', errors='replace'))
    print()
    for j in range(block_start, block_end + 1):
        printed.add(j)
