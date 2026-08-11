"""Read all enum cfstring arrays needed for notes update."""
import struct

BINARY = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'

def vma_off(vma): return vma - 0x4000

def read_cfstring(data, vma):
    off = vma_off(vma)
    if off + 16 > len(data): return None
    isa, flags, ptr, length = struct.unpack_from('<IIII', data, off)
    if length == 0 or length > 200: return None
    ptr_off = vma_off(ptr)
    if ptr_off < 0 or ptr_off + length > len(data): return None
    try:
        return data[ptr_off:ptr_off+length].decode('utf-8', errors='replace')
    except Exception:
        return None

with open(BINARY, 'rb') as f:
    data = f.read()

def read_array(label, start_vma, count):
    print(f'=== {label} ({count} entries @ 0x{start_vma:07X}) ===')
    for i in range(count):
        s = read_cfstring(data, start_vma + i * 16)
        print(f'  [{i}] {s!r}')
    print()

# All enum arrays
read_array('0x06000001 gear position', 0x000F57B8, 1)  # Park
read_array('0x06000001 - UnPark candidate', 0x000F57C8, 1)
read_array('0x06000001 - Reverse (adjacent to Neutral)', 0x000F5D18, 1)
read_array('0x06000001 - Neutral+Drive', 0x000F5D28, 2)

read_array('0x0868A047 AC compressor status', 0x000F5D68, 4)
read_array('0x0868A047 EAC_CompFltStat', 0x000F5D98, 8)

read_array('0x0580 TCM park lock state', 0x000F59D8, 6)

read_array('0x0053 OperationMode', 0x000F56B8, 4)
read_array('0x0053 OperationState', 0x000F56F8, 9)
