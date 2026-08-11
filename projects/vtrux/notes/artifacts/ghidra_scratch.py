"""
Scratchpad for Ghidra binary analysis tasks.
Modify the TASK variable to select what to run.
"""
import struct, sys

BINARY_ARM = 'projects/vtrux/notes/artifacts/CANbusLogger2_ARM'
# TEXT segment: VMA base = 0x4000, so file_offset = VMA - 0x4000

def vma_to_offset(vma):
    return vma - 0x4000

def read_double(f, vma):
    f.seek(vma_to_offset(vma))
    return struct.unpack('<d', f.read(8))[0]

def read_float(f, vma):
    f.seek(vma_to_offset(vma))
    return struct.unpack('<f', f.read(4))[0]

def read_bytes(f, vma, n):
    f.seek(vma_to_offset(vma))
    return f.read(n)

def arm_vfp_imm8(imm8):
    """Decode ARM VMOV.F32 8-bit immediate to float.
    VFPExpandImm: sign=bit7, exp=NOT(b),b,b,b,b,b,c,d, mantissa=e,f,g,h,0..."""
    a = (imm8 >> 7) & 1
    b = (imm8 >> 6) & 1
    c = (imm8 >> 5) & 1
    d = (imm8 >> 4) & 1
    e = (imm8 >> 3) & 1
    f_ = (imm8 >> 2) & 1
    g = (imm8 >> 1) & 1
    h = imm8 & 1
    exp_bits = ((1-b) << 7) | (b << 6) | (b << 5) | (b << 4) | (b << 3) | (b << 2) | (c << 1) | d
    mant_bits = (e << 22) | (f_ << 21) | (g << 20) | (h << 19)
    bits32 = (a << 31) | (exp_bits << 23) | mant_bits
    return struct.unpack('<f', struct.pack('<I', bits32))[0]

with open(BINARY_ARM, 'rb') as f:

    # ---- TASK 1: Decode SIMDImm VFP immediates ----
    print("=== ARM VFP Immediate Decoding ===")
    for name, imm8 in [("SIMDImm(0xF,0x50)", 0x50),
                       ("SIMDImm(0xF,0x60)", 0x60),
                       ("SIMDImm(0xF,0x69)", 0x69)]:
        val = arm_vfp_imm8(imm8)
        print(f"  {name} = {val} ({val!r})")

    # ---- TASK 2: Read DAT constants ----
    print("\n=== DAT Constants ===")
    # DAT_0002bab8: confirmed -500.0 last run
    print(f"  DAT_0002bab8 (bcm_vbus_neg offset): {read_float(f, 0x2bab8)}")
    # DAT_00029590 for INVCH_Bdc_Temperature_Int: try double too
    f.seek(vma_to_offset(0x29590))
    raw4 = f.read(4)
    f.seek(vma_to_offset(0x29590))
    raw8 = f.read(8)
    print(f"  DAT_00029590 bytes: {raw4.hex()}")
    print(f"  DAT_00029590 as float32 LE: {struct.unpack('<f', raw4)[0]}")
    print(f"  DAT_00029590 as double LE:  {struct.unpack('<d', raw8)[0]}")
    # Check nearby constants
    for offset_vma in [0x29590, 0x29594, 0x29598, 0x2959c]:
        f.seek(vma_to_offset(offset_vma))
        r = f.read(4)
        print(f"  VMA 0x{offset_vma:05x}: bytes={r.hex()}  f32={struct.unpack('<f',r)[0]:.6g}")

    # ---- TASK 3: Read 0x0308 ParkRequest string VMAs and 0x0462 DAT constant ----
    print("\n=== 0x0308 ParkRequest string array VMAs ===")
    # 4 entries at 0xF57A8, 0xF57B8, 0xF57C8, 0xF57D8 (cfstring structs, 16 bytes each)
    # Each cfstring: [flags 4B][encoding 4B][ptr 4B][len 4B]
    # char pointer is at offset +8, but points to __cstring section
    for vma in [0xF57A8, 0xF57B8, 0xF57C8, 0xF57D8]:
        foff = vma_to_offset(vma)
        f.seek(foff + 8)
        char_ptr = struct.unpack('<I', f.read(4))[0]
        f.seek(foff + 12)
        length = struct.unpack('<I', f.read(4))[0]
        char_foff = vma_to_offset(char_ptr)
        f.seek(char_foff)
        text = f.read(length + 1)
        print(f"  VMA 0x{vma:05x}: char_ptr=0x{char_ptr:05x} len={length} -> {text[:40]!r}")

    print("\n=== DAT_00044fa0 (0x0462 TRAC_HighPwr offset) ===")
    f.seek(vma_to_offset(0x44fa0))
    r8 = f.read(8)
    print(f"  bytes={r8.hex()}  f64={struct.unpack('<d',r8)[0]:.6g}")

    # ---- TASK 5: 0x18EFC000 string arrays ----
    # 4-entry LED/SetpointMode array: element[0]=low 0x57A8, element[2]=low 0x5E38
    # 5-entry cmd_Mode array: element[0]=low 0x5E68, element[2]=low 0x5E88, element[4]=cf_Invalid
    # Unknown entries [1],[3] in both arrays have upper bits only (MOVT resolved, MOVW lost by Ghidra)
    # Strategy: scan cfstring section broadly around each anchor to read all nearby strings
    print("\n=== 0x18EFC000 cfstring scan ===")
    print("-- Anchor region 1: around 0xF57A8 (known=OFF) --")
    for vma in range(0xF5758, 0xF5878, 0x10):
        try:
            foff = vma_to_offset(vma)
            f.seek(foff + 8)
            char_ptr = struct.unpack('<I', f.read(4))[0]
            f.seek(foff + 12)
            length = struct.unpack('<I', f.read(4))[0]
            if 1 <= length <= 64 and (char_ptr & 0xffff0000) != 0:
                char_foff = vma_to_offset(char_ptr)
                f.seek(char_foff)
                text = f.read(length + 1)
                if text[-1:] == b'\x00' and all(32 <= c < 127 for c in text[:-1]):
                    print(f"  0x{vma:05x}: char_ptr=0x{char_ptr:05x} len={length} -> {text[:-1].decode()!r}")
        except Exception:
            pass
    print("-- Gap region: 0xF5858 to 0xF5E28 (bcm_chgc_stat LOW -> SOLID) --")
    for vma in range(0xF5858, 0xF5E28, 0x10):
        try:
            foff = vma_to_offset(vma)
            f.seek(foff + 8)
            char_ptr = struct.unpack('<I', f.read(4))[0]
            f.seek(foff + 12)
            length = struct.unpack('<I', f.read(4))[0]
            if 1 <= length <= 64 and (char_ptr & 0xffff0000) != 0:
                char_foff = vma_to_offset(char_ptr)
                f.seek(char_foff)
                text = f.read(length + 1)
                if text[-1:] == b'\x00' and all(32 <= c < 127 for c in text[:-1]):
                    print(f"  0x{vma:05x}: char_ptr=0x{char_ptr:05x} len={length} -> {text[:-1].decode()!r}")
        except Exception:
            pass
    print("-- Anchor region 2: around 0xF5E28-0xF5EF8 (0x5E38, 0x5E68, 0x5E88) --")
    for vma in range(0xF5E28, 0xF5EF8, 0x10):
        try:
            foff = vma_to_offset(vma)
            f.seek(foff + 8)
            char_ptr = struct.unpack('<I', f.read(4))[0]
            f.seek(foff + 12)
            length = struct.unpack('<I', f.read(4))[0]
            if 1 <= length <= 64 and (char_ptr & 0xffff0000) != 0:
                char_foff = vma_to_offset(char_ptr)
                f.seek(char_foff)
                text = f.read(length + 1)
                if text[-1:] == b'\x00' and all(32 <= c < 127 for c in text[:-1]):
                    print(f"  0x{vma:05x}: char_ptr=0x{char_ptr:05x} len={length} -> {text[:-1].decode()!r}")
        except Exception:
            pass

    # ---- TASK 6: Capstone search for MOVT 0x000F + adjacent MOVW in function body ----
    # ViaCANbusParser::parseEPRIMessage starts at VMA 0x25d00, runs to ~0x43d90
    # We need MOVT r*, #0x000F instructions (upper16=0x000F makes 0xF5xxx cfstring VMAs)
    # followed by using the register as a cfstring pointer.
    # Strategy: scan for Thumb-2 MOVT encoding with imm16=0x000F and record nearby MOVWs.
    print("\n=== Capstone MOVT 0x000F scan in parseEPRIMessage ===")
    try:
        import capstone
        cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        cs.detail = True
        FUNC_START_VMA = 0x25d00
        FUNC_END_VMA   = 0x43d90
        foff_start = vma_to_offset(FUNC_START_VMA)
        size = FUNC_END_VMA - FUNC_START_VMA
        f.seek(foff_start)
        code = f.read(size)
        # Collect all MOVW and MOVT with imm16 in range 0x5800..0x5FFF (LED/cmd_Mode region)
        # and their partner MOVT 0x000F
        targets_low = set()
        movw_log = []  # (vma, reg, imm16)
        movt_log = []  # (vma, reg, imm16)
        for ins in cs.disasm(code, FUNC_START_VMA):
            if ins.mnemonic in ('movw', 'movt'):
                # imm16 is the last operand
                imm = ins.operands[-1].imm if ins.operands else None
                if imm is None:
                    continue
                reg = ins.reg_name(ins.operands[0].reg)
                if ins.mnemonic == 'movt' and imm == 0x000f:
                    movt_log.append((ins.address, reg))
                if ins.mnemonic == 'movw' and 0x5800 <= imm <= 0x6000:
                    movw_log.append((ins.address, reg, imm))
        # Report MOVW in range paired with nearby MOVT 0x000F on same register
        movt_by_reg = {}
        for addr, reg in movt_log:
            movt_by_reg.setdefault(reg, []).append(addr)
        for addr, reg, imm in movw_log:
            print(f"  MOVW {reg}, #0x{imm:04x}  @ VMA 0x{addr:05x}  -> VMA 0x000F{imm:04x} = ?")
            # Check if MOVT 0x000F for same reg is nearby (within 32 bytes)
            for movt_addr in movt_by_reg.get(reg, []):
                if abs(movt_addr - addr) <= 32:
                    print(f"    paired with MOVT {reg}, #0x000F @ VMA 0x{movt_addr:05x}")
        # Try different upper-16 bases for the known lower-16 values 0x57a8 and 0x5e38
        # to find the actual runtime VMA where these cfstrings live
        print("\n  -- Try different upper-16 bases for 0x57a8 / 0x5e38 / 0x5e68 / 0x5e88 --")
        for low16, label in [(0x57a8, "elem[0] OFF?"), (0x5e38, "elem[2] FLASH?"),
                             (0x5e68, "cmd[0] Export?"), (0x5e88, "cmd[2] StandBy?")]:
            for upper in [0x000c, 0x000d, 0x000e, 0x000f]:
                vma = (upper << 16) | low16
                foff = vma_to_offset(vma)
                try:
                    f.seek(foff + 8)
                    char_ptr = struct.unpack('<I', f.read(4))[0]
                    f.seek(foff + 12)
                    length = struct.unpack('<I', f.read(4))[0]
                    if 1 <= length <= 64 and (char_ptr >> 16) in (0x000c, 0x000d, 0x000e, 0x000f):
                        f.seek(vma_to_offset(char_ptr))
                        text = f.read(min(length + 1, 32))
                        if all(32 <= c < 127 for c in text[:length]):
                            print(f"  0x{vma:08x} ({label}): char_ptr=0x{char_ptr:07x} len={length} -> {text[:length].decode()!r}")
                except Exception:
                    pass

        # Sanity check: what does dereferencing a known DATA address give?
        # PTR_s_sharedManager_0010bf9c from Ghidra → VMA 0x0010bf9c
        print("\n  -- Sanity check: read known DATA addresses from function literal pools --")
        # Sample: pick the first 5 unique 0x000Cxxxx and 0x000Dxxxx values and dereference
        for prefix in (0x000c, 0x000d):
            sample = []
            seen = set()
            for i in range(0, len(code) - 3, 4):
                val = struct.unpack_from('<I', code, i)[0]
                if (val >> 16) == prefix and val not in seen:
                    seen.add(val)
                    sample.append(val)
                    if len(sample) >= 3:
                        break
            for val in sample:
                foff = vma_to_offset(val)
                try:
                    f.seek(foff)
                    deref = struct.unpack('<I', f.read(4))[0]
                    print(f"  DATA[0x{val:08x}] (foff=0x{foff:07x}) -> 0x{deref:08x}")
                except Exception as e:
                    print(f"  DATA[0x{val:08x}] -> ERROR: {e}")

        # Dereference all 0x000Dxxxx pointer-table entries in the function body
        # -> read the DATA value at each, check if it resolves to 0xF5E28-0xF5E98 cfstrings
        print("\n  -- Dereferencing 0x000Dxxxx pointers -> check for LED/cmd_Mode cfstrings --")
        seen_d_vals = set()
        for i in range(0, len(code) - 3, 4):
            val = struct.unpack_from('<I', code, i)[0]
            if (val >> 16) == 0x000d and val not in seen_d_vals:
                seen_d_vals.add(val)
                try:
                    f.seek(vma_to_offset(val))
                    deref = struct.unpack('<I', f.read(4))[0]
                    if 0x000F5E00 <= deref <= 0x000F5F00:
                        pool_vma = FUNC_START_VMA + i
                        print(f"  pool[0x{pool_vma:05x}]: DATA[0x{val:07x}] -> cfstring 0x{deref:07x}")
                        # read the cfstring string
                        foff = vma_to_offset(deref)
                        f.seek(foff + 8)
                        char_ptr = struct.unpack('<I', f.read(4))[0]
                        f.seek(foff + 12)
                        length = struct.unpack('<I', f.read(4))[0]
                        if 1 <= length <= 80:
                            f.seek(vma_to_offset(char_ptr))
                            text = f.read(length + 1)
                            print(f"    -> cfstring = {text[:-1].decode(errors='replace')!r}")
                except Exception:
                    pass
        # Also do same for 0x000Cxxxx
        print("\n  -- Dereferencing 0x000Cxxxx pointers -> check for LED/cmd_Mode cfstrings --")
        seen_c_vals = set()
        for i in range(0, len(code) - 3, 4):
            val = struct.unpack_from('<I', code, i)[0]
            if (val >> 16) == 0x000c and val not in seen_c_vals:
                seen_c_vals.add(val)
                try:
                    f.seek(vma_to_offset(val))
                    deref = struct.unpack('<I', f.read(4))[0]
                    if 0x000F5E00 <= deref <= 0x000F5F00:
                        pool_vma = FUNC_START_VMA + i
                        print(f"  pool[0x{pool_vma:05x}]: DATA[0x{val:07x}] -> cfstring 0x{deref:07x}")
                        foff = vma_to_offset(deref)
                        f.seek(foff + 8)
                        char_ptr = struct.unpack('<I', f.read(4))[0]
                        f.seek(foff + 12)
                        length = struct.unpack('<I', f.read(4))[0]
                        if 1 <= length <= 80:
                            f.seek(vma_to_offset(char_ptr))
                            text = f.read(length + 1)
                            print(f"    -> cfstring = {text[:-1].decode(errors='replace')!r}")
                except Exception:
                    pass
    except ImportError:
        print("  capstone not installed")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ---- TASK 7: Full TEXT segment scan for 0x000F5xxx cfstring pointer values ----
    # Goal: find which cfstring VMAs are actually referenced by literal pools anywhere in
    # the TEXT segment (covers pools outside the main function body range 0x1E090-0x3E120).
    # This resolves the missing LED mode [1],[3] and cmd_Mode [1],[3] string values.
    print("\n=== Task 7: Full TEXT segment scan for 0x000F5xxx cfstring VMAs ===")
    TEXT_SCAN_SIZE = 0x80000
    f.seek(0)
    text_blob = f.read(TEXT_SCAN_SIZE)
    hits = {}  # vma -> [file_offsets where this VMA appears as a 4-byte LE value]
    for i in range(0, len(text_blob) - 3, 4):
        val = struct.unpack_from('<I', text_blob, i)[0]
        if 0x000F5700 <= val <= 0x000F5F00:
            hits.setdefault(val, []).append(i)
    print(f"  Found {len(hits)} distinct VMAs in 0x000F5700-0x000F5F00 range")
    for val in sorted(hits):
        try:
            foff = vma_to_offset(val)
            f.seek(foff + 8)
            char_ptr = struct.unpack('<I', f.read(4))[0]
            f.seek(foff + 12)
            length = struct.unpack('<I', f.read(4))[0]
            f.seek(vma_to_offset(char_ptr))
            text = f.read(length).decode(errors='replace')
        except Exception:
            text = '???'
        locs = ', '.join(f'0x{(x + 0x4000):05x}' for x in hits[val][:6])
        print(f"  0x{val:08x}  {text!r:30s}  ref'd at: {locs}")

    # ---- TASK 8: Enumerate ALL cfstrings in 0xF5000-0xF6000 at 16-byte stride ----
    # The Task 7 scan found 0 references (VMAs are encoded via MOVW/MOVT, not literal pools).
    # Instead, directly read every possible cfstring slot in the region to get a full inventory.
    # cfstring struct: [isa 4B][flags 4B][char_ptr 4B][length 4B]
    # A valid cfstring has: char_ptr in TEXT (.cstring) range 0xD0000-0xF0000, length 1-200
    print("\n=== Task 8: cfstring inventory 0xF5000-0xF6000 (16-byte stride) ===")
    for slot_vma in range(0xF5008, 0xF6000, 16):
        try:
            foff = vma_to_offset(slot_vma)
            f.seek(foff + 8)
            char_ptr = struct.unpack('<I', f.read(4))[0]
            f.seek(foff + 12)
            length = struct.unpack('<I', f.read(4))[0]
            if not (0x000C0000 <= char_ptr <= 0x000F0000):
                continue
            if not (1 <= length <= 200):
                continue
            f.seek(vma_to_offset(char_ptr))
            text = f.read(length).decode(errors='replace')
            print(f"  0x{slot_vma:05x}  len={length:3d}  {text!r}")
        except Exception:
            pass

    # ---- TASK 9: Disassemble first 512 bytes of parseEPRIMessage (VMA 0x25D00) ----
    # Goal: find MOVW/MOVT instructions that set in_register_00000384 and in_register_0000038c.
    # Function starts at file offset 0x25D00 - 0x4000 = 0x21D00.
    print("\n=== Task 9: Disassemble parseEPRIMessage prologue for MOVT 0x000F ===")
    try:
        import capstone
        cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        cs.detail = True
        FUNC_START_FOFF = 0x21D00
        SCAN_BYTES = 2048
        f.seek(FUNC_START_FOFF)
        code = f.read(SCAN_BYTES)
        FUNC_VMA = 0x25D00
        found_movw = {}  # reg -> imm16
        for insn in cs.disasm(code, FUNC_VMA):
            mn = insn.mnemonic.lower()
            if mn in ('movw', 'movt'):
                ops = insn.operands
                if len(ops) == 2:
                    reg = ops[0].reg
                    imm = ops[1].imm & 0xffff
                    if mn == 'movt' and imm == 0x000f:
                        low = found_movw.get(reg, None)
                        vma = 0x000f0000 | (low if low is not None else 0)
                        # read cfstring at that VMA
                        if low is not None:
                            try:
                                f.seek(vma_to_offset(vma) + 8)
                                cptr = struct.unpack('<I', f.read(4))[0]
                                f.seek(vma_to_offset(vma) + 12)
                                clen = struct.unpack('<I', f.read(4))[0]
                                f.seek(vma_to_offset(cptr))
                                cstr = f.read(clen).decode(errors='replace')
                            except Exception:
                                cstr = '???'
                        else:
                            cstr = '(MOVW not yet seen)'
                        print(f"  0x{insn.address:05x}  {mn} r{reg}, #{imm:#06x}  -> VMA 0x{vma:08x} = {cstr!r}")
                    elif mn == 'movw':
                        found_movw[reg] = imm
                    elif mn == 'movt' and 0x000c <= imm <= 0x0010:
                        print(f"  0x{insn.address:05x}  {mn} r{reg}, #{imm:#06x}  (upper={imm:#06x})")
        print("  (done scanning first 2048 bytes)")
    except ImportError:
        print("  capstone not installed")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ---- TASK 10: Scan binary for 8-byte VFP literal pool entries ----
    # in_register_00000384 = s33 = upper 32 bits of d16 (loaded by VLDR.64)
    # in_register_0000038c = s35 = upper 32 bits of d17
    # A VLDR.64 literal pool entry: [lower_32bit, upper_32bit] in LE
    # We want entries where BOTH halves are in the cfstring range 0x000F5000-0x000F6000
    print("\n=== Task 10: Scan for 8-byte VFP literals with both halves in 0x000F5xxx ===")
    SCAN_END = 0x200000  # scan entire typical binary
    f.seek(0)
    blob = f.read(SCAN_END)
    for i in range(0, len(blob) - 7, 4):
        lo = struct.unpack_from('<I', blob, i)[0]
        hi = struct.unpack_from('<I', blob, i+4)[0]
        if (0x000F0000 <= lo <= 0x000F6000) and (0x000F5000 <= hi <= 0x000F6000):
            vma_lo = lo
            vma_hi = hi
            def read_cf(vma):
                try:
                    f.seek(vma_to_offset(vma) + 8)
                    cp = struct.unpack('<I', f.read(4))[0]
                    f.seek(vma_to_offset(vma) + 12)
                    cl = struct.unpack('<I', f.read(4))[0]
                    f.seek(vma_to_offset(cp))
                    return f.read(cl).decode(errors='replace')
                except Exception:
                    return '???'
            s_lo = read_cf(vma_lo)
            s_hi = read_cf(vma_hi)
            loc_vma = i + 0x4000
            print(f"  @ file 0x{i:05x} (VMA 0x{loc_vma:05x}):")
            print(f"    lo=0x{lo:08x} ({s_lo!r}), hi=0x{hi:08x} ({s_hi!r})")

    # ---- TASK 11: Search binary for specific candidate 8-byte VFP literal patterns ----
    # Candidates from OperationState alternating pattern:
    #   in_register_00000384 = 0x000F5708 = "STBY"
    #   in_register_0000038c = 0x000F5728 = "DEACTIVATION"
    # Search for these as 4-byte LE values anywhere in binary (they might be
    # in DATA segment or separate literal pools, not paired with another 0x000Fxxxx)
    print("\n=== Task 11: Search for candidate register values as standalone 4-byte refs ===")
    candidates = {
        0x000F5708: 'STBY',
        0x000F5728: 'DEACTIVATION',
        0x000F5748: 'FAILURE',
        0x000F5768: 'WAIT4COOLING',
        0x000F56C8: 'Invalid (1)',
        0x000F56E8: 'Invalid (%d)',
    }
    f.seek(0)
    full_blob = f.read(0x200000)
    for val, name in sorted(candidates.items()):
        hits = []
        for i in range(0, len(full_blob) - 3, 4):
            if struct.unpack_from('<I', full_blob, i)[0] == val:
                hits.append(i)
        if hits:
            locs = ', '.join(f'0x{(x+0x4000):06x}' for x in hits[:8])
            print(f"  0x{val:08x} ({name!r}): {len(hits)} hits at {locs}")
        else:
            print(f"  0x{val:08x} ({name!r}): NOT FOUND")

    # Task 12 completed separately (standalone script). Key findings:
    # __DATA.__cfstring: VMA 0xF3D28, size 0x71B0, foff 0xEFD28 (formula: foff = VMA - 0x4000)
    # __TEXT.__text: VMA 0xB3F0, foff 0x73F0
    # __TEXT.__cstring: VMA 0xD57F0, foff 0xD17F0
    # __DATA: vma=0xF0000, foff=0xEC000 (same offset formula VMA-0x4000)
    pass

    # ---- TASK 13: Scan ENTIRE binary for MOVT #0x000F (loads cfstring page base) ----
    # We need to find where in_register_00000384/38c are set.
    # These must be set by the CALLER of parseEPRIMessage (at VMA 0x25D00).
    # MOVT #0x000F encoding: first halfword is 0xF2CF or similar; let's use Capstone.
    print("\n=== Task 13: Whole-binary Capstone scan for MOVT #0x000F ===")
    try:
        import capstone
        cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        cs.detail = True
        BINARY_SIZE = 0xEC000
        f.seek(0)
        all_code = f.read(BINARY_SIZE)
        TEXT_VMA_BASE = 0x4000
        found_movw = {}  # reg -> (imm16, vma_of_insn)
        movt_000f_count = 0
        for insn in cs.disasm(all_code, TEXT_VMA_BASE):
            mn = insn.mnemonic.lower()
            if mn not in ('movw', 'movt'):
                continue
            ops = insn.operands
            if len(ops) != 2:
                continue
            reg = ops[0].reg
            imm = ops[1].imm & 0xffff
            if mn == 'movw':
                found_movw[reg] = (imm, insn.address)
            elif mn == 'movt' and imm == 0x000f:
                movt_000f_count += 1
                low_info = found_movw.get(reg)
                if low_info:
                    low, movw_vma = low_info
                    vma = 0x000f0000 | low
                    try:
                        f.seek(vma_to_offset(vma) + 8)
                        cptr = struct.unpack('<I', f.read(4))[0]
                        f.seek(vma_to_offset(vma) + 12)
                        clen = struct.unpack('<I', f.read(4))[0]
                        f.seek(vma_to_offset(cptr))
                        cstr = f.read(clen).decode(errors='replace')
                    except Exception:
                        cstr = '???'
                    print(f"  MOVT 0x000F at 0x{insn.address:05x} r{reg}: VMA=0x{vma:08x} ({cstr!r}) [MOVW at 0x{movw_vma:05x}]")
                else:
                    print(f"  MOVT 0x000F at 0x{insn.address:05x} r{reg}: low16 unknown (no preceding MOVW)")
        print(f"  Total MOVT #0x000F found: {movt_000f_count}")
    except ImportError:
        print("  capstone not installed")
    except Exception as e:
        import traceback
        print(f"  ERROR: {e}")
        traceback.print_exc()

    # ---- TASK 14: Scan binary for refs in actual __DATA.__cfstring VMA range ----
    # Confirmed from section parse: __DATA.__cfstring VMA 0xF3D28-0xFAED8
    # Scan entire binary for 4-byte LE values in that range.
    print("\n=== Task 14: Scan binary for __DATA.__cfstring VMA refs (0xF3D28-0xFAED8) ===")
    CFVMA_LO = 0x000F3D28
    CFVMA_HI = 0x000FAED8
    FULL_SIZE = 0x134000  # covers TEXT+DATA+LINKEDIT
    f.seek(0)
    blob14 = f.read(FULL_SIZE)
    hits14 = {}
    for i in range(0, len(blob14) - 3, 4):
        val = struct.unpack_from('<I', blob14, i)[0]
        if CFVMA_LO <= val <= CFVMA_HI:
            hits14.setdefault(val, []).append(i)
    print(f"  Found {len(hits14)} distinct cfstring VMA refs in binary")
    for val in sorted(hits14)[:30]:
        try:
            foff = val - 0x4000  # formula: file_offset = VMA - 0x4000
            f.seek(foff + 8)
            char_ptr = struct.unpack('<I', f.read(4))[0]
            f.seek(foff + 12)
            clen = struct.unpack('<I', f.read(4))[0]
            f.seek(char_ptr - 0x4000)
            cstr = f.read(min(clen, 40)).decode(errors='replace')
        except Exception:
            cstr = '???'
        locs = ', '.join(f'0x{(x+0x4000):06x}' for x in hits14[val][:4])
        cstr_safe = cstr.encode('ascii', 'replace').decode('ascii')
        print(f"  0x{val:08x} ({cstr_safe!r:25s})  {len(hits14[val])} refs @ {locs}")

    # ---- TASK 15: Find LED array build site via PTR__OBJC_CLASS___NSArray_0010da94 ----
    # From decompile: _objc_msgSend(PTR__OBJC_CLASS___NSArray_0010da94, ...) right after
    # building the LED array. PTR... is a DATA pointer at VMA 0x10DA94.
    # Find all refs to 0x10DA94 in binary, then disassemble nearby code to find
    # VLDR/LDR instructions that load cfstring addresses.
    print("\n=== Task 15: Find LED array via NSArray class ref 0x10DA94 ===")
    # First find where 0x10DA94 appears as a 4-byte LE value (literal pool for LDR)
    TARGET = 0x0010DA94
    f.seek(0)
    blob15 = f.read(0x134000)
    nsarray_refs = [i for i in range(0, len(blob15)-3, 4)
                    if struct.unpack_from('<I', blob15, i)[0] == TARGET]
    print(f"  0x10DA94 (NSArray class ptr) appears {len(nsarray_refs)} times")
    for foff in nsarray_refs[:10]:
        print(f"    file 0x{foff:05x} (VMA 0x{foff+0x4000:06x})")

    # Also search for selector ref 0x10C2A4 (arrayWithObjects:count:)
    SEL = 0x0010C2A4
    sel_refs = [i for i in range(0, len(blob15)-3, 4)
                if struct.unpack_from('<I', blob15, i)[0] == SEL]
    print(f"  0x10C2A4 (arrayWithObjects:count: sel) appears {len(sel_refs)} times")
    for foff in sel_refs[:10]:
        print(f"    file 0x{foff:05x} (VMA 0x{foff+0x4000:06x})")

    # ---- TASK 16: Disassemble code near the LED array build in parseEPRIMessage ----
    # The 0x18EFC000 handler's LED array build is at approximately VMA 0x3E000+ based
    # on context (it's late in the huge function). Use capstone to scan the region
    # VMA 0x3DA00-0x3E200 (file 0x399A00 - but wait, function is 0x25D00-0x43D90).
    # Actually scan from function end backward for the known cfstring 0xF5EC8 log string.
    # Instead: look for the specific VLDR that loads d16/d17 before the LED array call.
    # Approach: in the function body, scan for LDR instructions that target addresses
    # in the DATA __objc_classrefs range (0x10D9BC-0x10DCB4) or __objc_selrefs range.
    # Specifically look for patterns: LDR r0/r2 with target values 0x10DA94 or nearby.
    print("\n=== Task 16: Disassemble parseEPRIMessage for LED array build area ===")
    try:
        import capstone
        cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        cs.detail = True
        # function body: VMA 0x25D00 to 0x43D90, file offset 0x21D00 to 0x3FD90
        FUNC_FSTART = 0x21D00
        FUNC_FEND   = 0x3FD90
        f.seek(FUNC_FSTART)
        func_code = f.read(FUNC_FEND - FUNC_FSTART)
        FUNC_VMA = 0x25D00
        # Scan for LDR instructions that load a literal pool containing 0x10DA94
        # When PC-relative LDR is decoded, we need to resolve the target address
        last_n = {}  # reg -> (imm, vma) for recent LDR
        for insn in cs.disasm(func_code, FUNC_VMA):
            mn = insn.mnemonic.lower()
            # Look for VLDR instructions (load VFP register from memory)
            if mn in ('vldr', 'vldmia'):
                ops = insn.operands
                print(f"  0x{insn.address:05x}: {insn.mnemonic} {insn.op_str}")
            # Look for BL to _objc_msgSend (indirect through DATA)
            # Track PC-relative LDR that loads 0x10DA94
            if mn == 'ldr' and len(insn.operands) >= 2:
                ops = insn.operands
                if ops[1].type == 3:  # MEM type
                    base = ops[1].mem.base
                    disp = ops[1].mem.disp
                    # PC-relative
                    if base == capstone.arm.ARM_REG_PC:
                        pc_val = (insn.address + 4) & ~3
                        target_addr = pc_val + disp
                        target_foff = target_addr - 0x4000
                        if 0 <= target_foff < len(blob15):
                            ldr_val = struct.unpack_from('<I', blob15, target_foff)[0]
                            if ldr_val == 0x0010DA94:
                                print(f"  0x{insn.address:05x}: LDR r{ops[0].reg} from [0x{target_addr:08x}]=0x{ldr_val:08x} (NSArray class)")
    except ImportError:
        print("  capstone not installed")
    except Exception as e:
        import traceback; traceback.print_exc()

    # ---- TASK 17: Read literal pool values for all vldr d16/d17 in function ----
    # For each vldr dN, [pc, #disp]: target = (insn_vma + 4) & ~3 + disp
    # Read the 8 bytes there and decode as two 32-bit cfstring VMAs.
    print("\n=== Task 17: Resolve vldr d16/d17 literal pool targets in parseEPRIMessage ===")
    vldr_d16_d17 = [
        # (vma, reg, disp) from Task 16 output
        (0x2ef82, 'd16', 0xfc),
        (0x3eb8c, 'd16', 0x98),
        (0x26bd8, 'd17', 0x114),
        (0x2775a, 'd17', 0x3b4),
        (0x27b96, 'd17', -0x78),
        (0x28960, 'd17', -0x14),
        (0x28d6e, 'd17', -0x20),
        (0x29cc2, 'd17', 0x1dc),
        (0x2a152, 'd17', -0x2ac),
        (0x2a796, 'd17', 0x390),
        (0x2ab4c, 'd17', -0x20),
        (0x2b2f4, 'd17', 0x2f8),
        (0x2c594, 'd17', -0x30),
        (0x2cec8, 'd17', -0x30),  # actually d8, skip
    ]
    def read_cf17(vma):
        foff = vma - 0x4000
        if foff < 0 or foff + 16 > len(blob15):
            return '(out of range)'
        try:
            char_ptr = struct.unpack_from('<I', blob15, foff + 8)[0]
            clen = struct.unpack_from('<I', blob15, foff + 12)[0]
            if not (1 <= clen <= 80):
                return f'(bad len {clen})'
            cp_foff = char_ptr - 0x4000
            if cp_foff < 0 or cp_foff + clen > len(blob15):
                return '(bad ptr)'
            return blob15[cp_foff:cp_foff+clen].decode(errors='replace')
        except Exception as e:
            return f'({e})'
    for vma, reg, disp in vldr_d16_d17:
        pc = (vma + 4) & ~3
        target = pc + disp
        target_foff = target - 0x4000
        if target_foff < 0 or target_foff + 8 > len(blob15):
            print(f"  0x{vma:05x} vldr {reg} [pc+{disp:#x}] -> target 0x{target:06x}: out of range")
            continue
        lo, hi = struct.unpack_from('<II', blob15, target_foff)
        s_lo = read_cf17(lo) if 0xF0000 <= lo <= 0x115000 else f'(not cfstring: 0x{lo:08x})'
        s_hi = read_cf17(hi) if 0xF0000 <= hi <= 0x115000 else f'(not cfstring: 0x{hi:08x})'
        print(f"  0x{vma:05x} vldr {reg} -> pool 0x{target:06x}: lo=0x{lo:08x}({s_lo!r}) hi=0x{hi:08x}({s_hi!r})")

    # ---- TASK 18: Check MH_PIE flag and scan for lower-16-only cfstring refs ----
    # If binary is PIE, literal pools may store unslid VMAs. Check flags.
    # Also: scan for lower-16 values of known cfstring VMAs (e.g. 0x57A8 as 0x000057A8)
    print("\n=== Task 18: Mach-O PIE check and lower-16 cfstring ref scan ===")
    f.seek(24)  # flags field of mach_header
    mh_flags = struct.unpack('<I', f.read(4))[0]
    MH_PIE = 0x00200000
    print(f"  mach_header flags = 0x{mh_flags:08x}, MH_PIE={'YES' if mh_flags & MH_PIE else 'NO'}")
    # scan for lower-16 values as zero-extended 32-bit values
    known_low16 = {
        0x000057A8: 'OFF',
        0x00005E38: 'FLASH',
        0x00005E68: 'Export Power Mode',
        0x00005E88: 'Stand-By',
        0x00005E28: 'SOLID',
        0x00005E78: 'Charger Mode',
        0x00005E98: 'Charger Low Power Mode',
        0x00005708: 'STBY',
        0x00005728: 'DEACTIVATION',
    }
    f.seek(0)
    blob18 = f.read(0x134000)
    for val, name in sorted(known_low16.items(), key=lambda x: x[0]):
        hits = [i for i in range(0, len(blob18)-3, 4)
                if struct.unpack_from('<I', blob18, i)[0] == val]
        if hits:
            locs = ', '.join(f'0x{(x+0x4000):06x}' for x in hits[:5])
            print(f"  0x{val:08x} ({name!r}): {len(hits)} hits @ {locs}")
        else:
            print(f"  0x{val:08x} ({name!r}): NOT FOUND")

    # ---- TASK 19: Confirm OperationState 9-entry alternating pattern ----
    # Shows in_register_00000384 = 0xF5708 = "STBY", in_register_0000038c = 0xF5728 = "DEACTIVATION"
    # Pattern: even slots loaded via in_dN | 0x5xxx, odd slots = upper-half of same dN register
    # Even slots:  [0]=INIT(0xF56F8), [2]=ACTIVATION(0xF5718), [4]=OPERATIONAL(0xF5738), [6]=SHTDWN(0xF5758), [8]=PWR_OFF_RDY(0xF5778)
    # Odd slots interleaved at exactly cfstring_VMA+0x10 between each pair of even slots:
    print("\n=== Task 19: OperationState cfstring alternating pattern verification ===")
    opstate_cfstrings = [
        (0xF56F8, "INIT",        "even [0]: in_d16 | 0x56F8"),
        (0xF5708, "STBY",        "odd  [1]: in_register_00000384 (upper d16)"),
        (0xF5718, "ACTIVATION",  "even [2]: in_d17 | 0x5718"),
        (0xF5728, "DEACTIVATION","odd  [3]: in_register_0000038c (upper d17)"),
        (0xF5738, "OPERATIONAL", "even [4]: in_d18_lo | 0x5738"),
        (0xF5748, "FAILURE",     "odd  [5]: in_d18_hi (upper d18)"),
        (0xF5758, "SHTDWN",      "even [6]: in_d19_lo | 0x5758"),
        (0xF5768, "WAIT4COOLING","odd  [7]: in_d19_hi (upper d19)"),
        (0xF5778, "PWR_OFF_RDY", "even [8]: direct &cf_PWR_OFF_RDY"),
    ]
    for vma, expected, role in opstate_cfstrings:
        foff = vma - 0x4000
        f.seek(foff + 8); char_ptr = struct.unpack('<I', f.read(4))[0]
        f.seek(foff + 12); clen = struct.unpack('<I', f.read(4))[0]
        f.seek(char_ptr - 0x4000); actual = f.read(clen).decode(errors='replace')
        status = "OK" if actual == expected else f"MISMATCH: got {actual!r}"
        print(f"  0x{vma:05x} [{status}] {actual!r:15s}  <- {role}")
    print("\n  => in_register_00000384 = 0xF5708 = 'STBY'")
    print(  "  => in_register_0000038c = 0xF5728 = 'DEACTIVATION'")
    print("\n  0x18EFC000 arrays:")
    print("    LED mode [0..3]: OFF / STBY / FLASH / DEACTIVATION")
    print("    cmd_Mode [0..4]: Export Power Mode / STBY / Stand-By / DEACTIVATION / Invalid")

    # ---- TASK 20: Find callers of parseEPRIMessage (VMA 0x25D00) ----
    # Scan entire binary for BL/BLX instructions targeting VMA 0x25D00.
    # Then for each call site, look back ~200 bytes for vldr d16/d17 instructions
    # and resolve their literal pool targets to find what cfstrings they load.
    print("\n=== Task 20: Find callers of parseEPRIMessage (VMA 0x25D00) ===")
    try:
        import capstone
        cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        cs.detail = True
        TARGET_VMA = 0x25D00
        f.seek(0)
        full_code = f.read(0xEC000)  # TEXT segment only
        # Raw scan for Thumb-2 BL/BLX instructions targeting TARGET_VMA.
        # Capstone streaming fails on mixed code/data; this avoids that problem.
        callers = []
        for i in range(0, len(full_code) - 3, 2):
            hw1, hw2 = struct.unpack_from('<HH', full_code, i)
            is_bl  = (hw1 & 0xF800) == 0xF000 and (hw2 & 0xD000) == 0xD000
            is_blx = (hw1 & 0xF800) == 0xF000 and (hw2 & 0xD001) == 0xC000
            if not (is_bl or is_blx):
                continue
            insn_vma = i + 0x4000
            S    = (hw1 >> 10) & 1
            imm10 = hw1 & 0x3FF
            J1   = (hw2 >> 13) & 1
            J2   = (hw2 >> 11) & 1
            imm11 = hw2 & 0x7FF
            I1   = 1 ^ (J1 ^ S)
            I2   = 1 ^ (J2 ^ S)
            offset = (S << 24) | (I1 << 23) | (I2 << 22) | (imm10 << 12) | (imm11 << 1)
            if S:
                offset -= (1 << 25)
            pc = insn_vma + 4
            if is_blx:
                pc = pc & ~3
            if pc + offset == TARGET_VMA:
                callers.append(insn_vma)
        print(f"  Found {len(callers)} callers: {[hex(a) for a in callers]}")

        # Sanity check: count ALL BL/BLX instructions found in the binary
        bl_count = 0
        sample_targets = {}
        for i in range(0, len(full_code) - 3, 2):
            hw1, hw2 = struct.unpack_from('<HH', full_code, i)
            is_bl  = (hw1 & 0xF800) == 0xF000 and (hw2 & 0xD000) == 0xD000
            is_blx = (hw1 & 0xF800) == 0xF000 and (hw2 & 0xD001) == 0xC000
            if not (is_bl or is_blx):
                continue
            insn_vma = i + 0x4000
            S    = (hw1 >> 10) & 1
            imm10 = hw1 & 0x3FF
            J1   = (hw2 >> 13) & 1
            J2   = (hw2 >> 11) & 1
            imm11 = hw2 & 0x7FF
            I1   = 1 ^ (J1 ^ S)
            I2   = 1 ^ (J2 ^ S)
            offset = (S << 24) | (I1 << 23) | (I2 << 22) | (imm10 << 12) | (imm11 << 1)
            if S:
                offset -= (1 << 25)
            pc = insn_vma + 4
            if is_blx:
                pc = pc & ~3
            tgt = pc + offset
            bl_count += 1
            sample_targets[tgt] = sample_targets.get(tgt, 0) + 1
        print(f"  Total BL/BLX found in TEXT: {bl_count}")
        # Show most frequent targets (top 10)
        top = sorted(sample_targets.items(), key=lambda x: -x[1])[:10]
        print("  Top-10 most-called targets:")
        for tgt, cnt in top:
            print(f"    0x{tgt:06x}  called {cnt}x")
        # Show any call near 0x25D00 +/- 0x200
        near = [(t, c) for t, c in sample_targets.items() if abs(t - 0x25D00) < 0x200]
        print(f"  Calls within +/-0x200 of 0x25D00: {near}")

        # Verify: show raw bytes at VMA 0x25D00 (first 16 bytes = 8 Thumb-2 halfwords)
        foff_fn = 0x25D00 - 0x4000
        fn_bytes = full_code[foff_fn:foff_fn+16]
        print(f"  Bytes at VMA 0x25D00 (foff 0x{foff_fn:05x}): {fn_bytes.hex()}")
        # Disassemble those bytes to confirm it looks like function entry
        for insn in cs.disasm(fn_bytes, 0x25D00):
            print(f"    0x{insn.address:05x}: {insn.mnemonic} {insn.op_str}")

        # Also check if there are indirect CALLs via BLX Rn (Thumb: 0x47_8/0xFFxx pattern)
        # BLX Rn = 0100 0111 1xxx 1000 family - but check raw pattern
        # In Thumb-2, indirect BLX Rn is a 16-bit: 0100 0111 1 Rm 000 → 0x47C0 | (Rm << 3)
        # To find them, scan for 0x47Cx / 0x47Dx / 0x47Ex / 0x47Fx halfwords
        # But these can't have a fixed target — they're register-indirect.
        # Instead let's find if parseEPRIMessage is an ObjC method by checking
        # the __objc_methnames section for the selector name.
        # __objc_methnames is in __TEXT; scan cfstrings for "parse" or "EPRI"
        text_bytes = full_code
        for probe in [b'parseEPRIMessage', b'parseEPRI', b'EPRI']:
            idx = text_bytes.find(probe)
            if idx >= 0:
                print(f"  Found {probe!r} at foff 0x{idx:06x} (VMA 0x{idx+0x4000:06x})")

        # For each caller, disassemble the 300 bytes before the call site
        # looking for vldr d16/d17 and their literal pool values
        for caller_vma in callers:
            print(f"\n  --- Caller at 0x{caller_vma:05x} ---")
            window_start = max(0x4000, caller_vma - 300)
            window_foff = window_start - 0x4000
            window_size = caller_vma - window_start + 4
            f.seek(window_foff)
            window = f.read(window_size)
            for insn in cs.disasm(window, window_start):
                mn = insn.mnemonic.lower()
                if mn == 'vldr':
                    ops = insn.operands
                    # Check if it's loading d16, d17, d18, or d19
                    reg = ops[0].reg if ops else 0
                    # capstone ARM reg IDs for d16-d19 vary; check op_str
                    op_str = insn.op_str
                    if any(f'd{n}' in op_str for n in [16,17,18,19]):
                        # resolve PC-relative target
                        if len(ops) >= 2 and ops[1].type == 3:  # MEM
                            base = ops[1].mem.base
                            disp = ops[1].mem.disp
                            if base == capstone.arm.ARM_REG_PC:
                                pc_aligned = (insn.address + 4) & ~3
                                target = pc_aligned + disp
                                target_foff = target - 0x4000
                                if 0 <= target_foff + 8 <= len(full_code):
                                    lo, hi = struct.unpack_from('<II', full_code, target_foff)
                                    def rcf(vma):
                                        fo = vma - 0x4000
                                        if fo < 0 or fo + 16 > len(full_code): return f'0x{vma:08x}'
                                        try:
                                            cp = struct.unpack_from('<I', full_code, fo+8)[0]
                                            cl = struct.unpack_from('<I', full_code, fo+12)[0]
                                            if not (1 <= cl <= 60): return f'0x{vma:08x}'
                                            cfo = cp - 0x4000
                                            if cfo < 0: return f'0x{vma:08x}'
                                            return full_code[cfo:cfo+cl].decode(errors='replace')
                                        except: return f'0x{vma:08x}'
                                    s_lo = rcf(lo) if 0xF0000 <= lo <= 0x115000 else f'float/0x{lo:08x}'
                                    s_hi = rcf(hi) if 0xF0000 <= hi <= 0x115000 else f'float/0x{hi:08x}'
                                    print(f"    0x{insn.address:05x}: vldr {op_str} -> pool 0x{target:06x}: "
                                          f"lo=0x{lo:08x}({s_lo!r}) hi=0x{hi:08x}({s_hi!r})")
                                else:
                                    print(f"    0x{insn.address:05x}: vldr {op_str} -> pool 0x{target:06x}: out of range")
                            elif base != 0:
                                print(f"    0x{insn.address:05x}: vldr {op_str} (indirect, not PC-rel)")
    except ImportError:
        print("  capstone not installed")
    except Exception as e:
        import traceback; traceback.print_exc()

    # ---- TASK 23: cfstring names for 0x65B DTC dictionary ----
    # DTC codes and their cfstring names from the 0x65B handler dictionary
    print("\n=== Task 23: 0x65B DTC cfstring names ===")
    dtc_cfstring_names = [
        "aChgr_p0d67ChgrPfrm_dtc", "sEss_p1a20BecmAFlt", "sEss_p0a7bBecmMilOnReq",
        "sEss_p1a21BecmACritFlt", "sEss_p1a81HvilPrfmGene", "sEss_p1a82HvilPrfmTrac",
        "sEss_p1a80HvilPrfmDcdc", "sEss_p0aa6HvIso", "sChgr_p1aa0ChgrShtdwn",
        "cEss_p0a0bHvilPrfm", "cEss_p0a1fEss",
        "diagHcu_u1300AppIntrptTsk", "diagHcu_u1301LowMemTsk2", "diagHcu_u1302LowMemTsk1",
        "diagHcu_u1303LowMemIdleTsk", "diagHcu_u1304LowMemIntrpt", "diagHcu_u1305LowMemKernel",
        "diagHcu_u1306ShtdwnTsk", "diagHcu_u1307LowMemHeap",
        "diagHcu_u1311HighCpuTsk2", "diagHcu_u1310HighCpuAppIntrptTsk",
        "diagHcu_u1312HighCpuTsk1", "diagHcu_u1313HighCpuShtdwnTsk", "diagHcu_u1314CpuIdleApp",
        "inAbstrCanEbcm_u0129LostRx", "inAbstrCanEcm_u0100LostRx",
        "inAbstrCanAccm_u016BLostRx", "inAbstrCanBecm_u0111LostRx", "inAbstrCanBdc_u0296LostRx",
    ]
    dtc_codes = [
        0x0D67, 0x1A20, 0x0A7B, 0x1A21, 0x1A81, 0x1A82, 0x1A80, 0x0AA6, 0x1AA0,
        0x0A0B, 0x0A1F,
        0xD300, 0xD301, 0xD302, 0xD303, 0xD304, 0xD305, 0xD306, 0xD307,
        0xD311, 0xD310, 0xD312, 0xD313, 0xD314,
        0xC129, 0xC100, 0xC16B, 0xC111, 0xC296,
    ]
    f.seek(0)
    full_bin = f.read(0x110000)
    def find_cfstring_by_cstring_name(name, binary):
        nb = name.encode('ascii') + b'\x00'
        idx = binary.find(nb)
        if idx < 0: return None, None
        cstr_vma = idx + 0x4000
        # scan cfstring section for a struct with char_ptr == cstr_vma
        # cfstring section: VMA 0xF3D28, size 0x71B0, stride 16
        for cf_foff in range(0xEFD28, 0xEFD28 + 0x71B0, 16):
            cp = struct.unpack_from('<I', binary, cf_foff + 8)[0]
            if cp == cstr_vma:
                return cf_foff + 0x4000, name
        return None, name
    for code, cname in zip(dtc_codes, dtc_cfstring_names):
        cf_vma, _ = find_cfstring_by_cstring_name(cname, full_bin)
        status = f"cfstr@0x{cf_vma:06x}" if cf_vma else "NOT FOUND in cfstring"
        print(f"  0x{code:04X}: {cname}  [{status}]")

    # ---- TASK 22: DAT constants for OBD bus messages ----
    print("\n=== Task 22: OBD bus DAT constants ===")
    for name, vma in [
        ("DAT_00044f88 (0x0120 odo factor 1)",  0x44f88),
        ("DAT_00044f90 (0x0120 odo factor 2)",  0x44f90),
        ("DAT_00044f98 (0x01C3 torque offset)", 0x44f98),
        ("DAT_000447a0 (0x03D1 fuel rate scale)",0x447a0),
        ("DAT_000447a8 (0x03E9 speed scale)",   0x447a8),
    ]:
        foff = vma - 0x4000
        f.seek(foff)
        raw8 = f.read(8)
        val_d = struct.unpack('<d', raw8)[0]
        val_f = struct.unpack('<f', raw8[:4])[0]
        print(f"  {name}: double={val_d!r}  float32={val_f!r}")

    # ---- TASK 21: DAT constants for 0x0592 and 0x0599 ----
    print("\n=== Task 21: DAT constants for 0x0592/0x0599 ===")
    for name, vma in [("DAT_00029ea0 (0x0592 BrakePdl scale)", 0x29ea0),
                      ("DAT_0002ab30 (0x0599 OilPressure scale)", 0x2ab30)]:
        foff = vma - 0x4000
        f.seek(foff)
        raw8 = f.read(8)
        val_d = struct.unpack('<d', raw8)[0]
        val_f = struct.unpack('<f', raw8[:4])[0]
        print(f"  {name}: foff=0x{foff:05x} -> double={val_d!r} float32={val_f!r}")

    # ---- TASK 4: Read bcm_chgc_stat / bcm_mainc_stat string arrays (0x0410) ----
    # Entries [0]="OPEN", [2]="FAILURE" confirmed; [1] and [3] have MOVT halves lost by Ghidra
    # cfstring structs are 16 bytes each: [flags 4B][encoding 4B][char_ptr 4B][len 4B]
    # Array base VMAs (by analogy with confirmed 0x0308 entries):
    #   bcm_chgc_stat: 0xF5828, 0xF5838, 0xF5848, 0xF5858
    #   bcm_mainc_stat: same 4 entries (both arrays share string labels in the app)
    print("\n=== 0x0410 bcm_chgc_stat/mainc_stat string cfstrings ===")
    for label, vma in [("entry[0] (expect OPEN)",    0xF5828),
                       ("entry[1] (unknown)",         0xF5838),
                       ("entry[2] (expect FAILURE)",  0xF5848),
                       ("entry[3] (unknown)",         0xF5858)]:
        foff = vma_to_offset(vma)
        f.seek(foff + 8)
        char_ptr = struct.unpack('<I', f.read(4))[0]
        f.seek(foff + 12)
        length = struct.unpack('<I', f.read(4))[0]
        try:
            char_foff = vma_to_offset(char_ptr)
            f.seek(char_foff)
            text = f.read(length + 1)
            print(f"  {label}: char_ptr=0x{char_ptr:05x} len={length} -> {text[:40]!r}")
        except Exception as e:
            print(f"  {label}: char_ptr=0x{char_ptr:05x} len={length} -> ERROR: {e}")

    # ---- TASK 24: GoPoint SDK recon -- find VMAs to target in Ghidra session 2 ----
    # Goal: locate the GoPoint SDK class methods that parse EPT (0x06000001) and
    # EAC (0x0868A047, 0x0870A047) messages. None of these IDs appear in the 12
    # already-decompiled functions. They are handled by GoPoint SDK ObjC classes.
    #
    # Strategy:
    #   A) Scan __TEXT.__cstring for GoPoint-related strings and plist signal names.
    #      These will tell us what cfstrings exist and reveal the strings the SDK uses.
    #   B) Scan __TEXT.__objc_methnames for relevant method selectors.
    #      GoPoint SDK methods like "parseEPTMessage:", "parseEACMessage:", etc.
    #   C) MOVW/MOVT constant search: find code that loads the three GoPoint IDs.
    #      0x06000001: MOVT upper = 0x0600, MOVW lower = 0x0001
    #      0x0868A047: MOVT upper = 0x0868, MOVW lower = 0xA047
    #      0x0870A047: MOVT upper = 0x0870, MOVW lower = 0xA047
    #   D) Scan ObjC classnames section for non-Via class names (GoPoint SDK classes).
    #
    # Output: a list of function VMAs and class/method names to load in Ghidra.

    print("\n=== Task 24: GoPoint SDK recon ===")

    FULL_BINARY_SIZE = 0x134000
    f.seek(0)
    full_bin24 = f.read(FULL_BINARY_SIZE)

    # --- 24A: Search __TEXT.__cstring for GoPoint-related and plist signal name strings ---
    print("\n-- 24A: cstring search for GoPoint/EPT/EAC signal names --")
    search_terms = [
        b'GoPoint', b'EPT_Stat', b'EAC_STATUS', b'EAC_Elec',
        b'Accel_Ped_Pos', b'EAC_CompHV', b'parseEPT', b'parseEAC',
        b'eptParser', b'eacParser', b'EPTParser', b'EACParser',
        b'GoPointModule', b'GoPointBT', b'goPoint',
    ]
    for term in search_terms:
        idx = 0
        found = []
        while True:
            idx = full_bin24.find(term, idx)
            if idx < 0:
                break
            found.append(idx + 0x4000)
            idx += len(term)
        if found:
            locs = ', '.join(f'0x{v:06x}' for v in found[:6])
            extra = f' (+{len(found)-6} more)' if len(found) > 6 else ''
            print(f"  {term.decode()!r}: {len(found)} hit(s) at {locs}{extra}")
        else:
            print(f"  {term.decode()!r}: NOT FOUND")

    # --- 24B: Scan __TEXT.__objc_methnames for relevant selectors ---
    # __objc_methnames lives in __TEXT between __text and __cstring.
    # Scan the TEXT segment (0x4000..0xD57F0) for the signal name bytes as method names.
    print("\n-- 24B: objc_methnames scan for GoPoint/EPT/EAC selectors --")
    text_seg = full_bin24[0:0xD57F0]  # VMA 0x4000..0xD57F0 -> foff 0x0..0xD17F0
    method_terms = [b'parseEPT', b'parseEAC', b'EPT', b'EAC', b'GoPoint',
                    b'handleEPT', b'handleEAC', b'eptMessage', b'eacMessage']
    for term in method_terms:
        idx = 0
        found = []
        while True:
            idx = text_seg.find(term, idx)
            if idx < 0:
                break
            # read the null-terminated string around this hit
            start = max(0, idx - 40)
            end_search = min(len(text_seg), idx + len(term) + 60)
            chunk = text_seg[idx:end_search]
            null = chunk.find(b'\x00')
            name = chunk[:null].decode(errors='replace') if null >= 0 else chunk.decode(errors='replace')
            found.append((idx + 0x4000, name[:80]))
            idx += len(term)
        if found:
            for vma, name in found[:5]:
                print(f"  {term.decode()!r} at VMA 0x{vma:06x}: {name!r}")
            if len(found) > 5:
                print(f"    ... and {len(found)-5} more")
        else:
            print(f"  {term.decode()!r}: NOT FOUND in text segment")

    # --- 24C: MOVW/MOVT search for GoPoint ID constants ---
    # Thumb-2 MOVW: 1111 0x10 0 imm4 | 0 imm3 Rd imm8
    #   hw1 = 0xF240 | (i << 10) | imm4_hi, hw2 = dest_reg | (imm3 << 12) | imm8
    #   Simpler: just scan for MOVT hw patterns with the right upper-16 values.
    # MOVT encoding: hw1 = 0xF2C0 | (S << 10) | imm4, hw2 = (imm3 << 12) | Rd | imm8
    # where the 16-bit immediate = imm4:i:imm3:imm8 (but bit arrangements vary).
    # Easiest: use the raw BL scan approach -- stride by 2, check halfword patterns.
    print("\n-- 24C: MOVT constant search for GoPoint ID upper halves --")
    # GoPoint IDs and their upper-16 values (used in MOVT):
    gp_targets = {
        0x0600: '0x06000001 (EPT_Stat_HMI_1)',
        0x0868: '0x0868A047 (EAC_STATUS1)',
        0x0870: '0x0870A047 (EAC_STATUS2)',
    }
    # Thumb-2 MOVT: hw1 bits [31:27]=11110, [26]=i, [25:24]=10, [23:20]=0xC (movt),
    #   [19:16]=imm4_hi. hw2: [15]=0, [14:12]=imm3, [11:8]=Rd, [7:0]=imm8.
    # imm16 = imm4_hi:i:imm3:imm8
    # For upper=0x0600: imm4_hi=0x0, i=6>>?, actually:
    # imm16 bits: [15:12]=imm4, [11]=i, [10:8]=imm3, [7:0]=imm8
    # Let's just do a pattern-based scan: look for hw1 with top bits = MOVT pattern,
    # then reconstruct the immediate and check.
    code_seg = full_bin24  # scan whole binary
    movt_hits = {upper: [] for upper in gp_targets}
    for i in range(0, len(code_seg) - 3, 2):
        hw1, hw2 = struct.unpack_from('<HH', code_seg, i)
        # MOVT: hw1 = 1111 0x11 0 imm4 | 0 xxx  -> top 5 bits of hw1 = 11110 = 0xF800 masked
        # hw1[15:11] = 11110 -> hw1 & 0xFBEF ... simpler: check standard MOVT encoding
        # Thumb32 MOVT: hw1 = 0xF2C0..0xF2CF (imm4 in bits [3:0], i in bit[10])
        # More precisely: hw1[15:11]=11110, hw1[9:8]=10 (data processing imm), hw1[7:4]=1100 (movt opcode)
        if (hw1 & 0xFBF0) == 0xF2C0:  # MOVT pattern: hw1[15:11]=11110, hw1[9]=1, hw1[8]=0, hw1[7:4]=1100
            # extract imm16: imm4=hw1[3:0], i=hw1[10], imm3=hw2[14:12], imm8=hw2[7:0]
            imm4 = hw1 & 0x000F
            i_bit = (hw1 >> 10) & 1
            imm3 = (hw2 >> 12) & 0x7
            imm8 = hw2 & 0xFF
            imm16 = (imm4 << 12) | (i_bit << 11) | (imm3 << 8) | imm8
            if imm16 in movt_hits:
                vma = i + 0x4000
                movt_hits[imm16].append(vma)
    for upper, label in gp_targets.items():
        hits = movt_hits[upper]
        if hits:
            locs = ', '.join(f'0x{v:06x}' for v in hits[:8])
            print(f"  MOVT #{upper:#06x} ({label}): {len(hits)} hit(s) at {locs}")
        else:
            print(f"  MOVT #{upper:#06x} ({label}): NOT FOUND")

    # --- 24D: ObjC classnames scan -- enumerate all class names in binary ---
    # __objc_classnames is in __TEXT; scan the methnames region for class-name-shaped strings.
    # Class names are null-terminated ASCII, typically start with uppercase, no spaces.
    # Scan the whole text segment for null-terminated strings starting after 0xB000 (post-code).
    print("\n-- 24D: ObjC classnames scan (0xB000..0xD57F0 region) --")
    CLASSNAMES_START_FOFF = 0xB000 - 0x4000  # approximate start of ObjC metadata strings
    CLASSNAMES_END_FOFF   = 0xD17F0           # up to start of __cstring
    region = full_bin24[CLASSNAMES_START_FOFF:CLASSNAMES_END_FOFF]
    # Parse null-terminated strings, filter for plausible class/selector names
    pos = 0
    class_names = []
    while pos < len(region):
        end = region.find(b'\x00', pos)
        if end < 0:
            break
        s = region[pos:end]
        pos = end + 1
        if len(s) < 3 or len(s) > 80:
            continue
        try:
            name = s.decode('ascii')
        except Exception:
            continue
        # filter: all printable, no spaces, starts with uppercase (class name heuristic)
        if name[0].isupper() and ' ' not in name and all(32 < ord(c) < 127 for c in name):
            class_names.append(name)
    # Print only names that look GoPoint/EPT/EAC related, plus a sample of all unique names
    gp_related = [n for n in class_names if any(
        kw in n for kw in ('GoPoint', 'EPT', 'EAC', 'Volt', 'Leaf', 'Prius', 'Odyne',
                           'Via', 'EPRI', 'J1939', 'OBD', 'CAN', 'Bus', 'Parser',
                           'Module', 'Logger', 'File', 'Source'))]
    seen = set()
    print(f"  Total class-name-shaped strings found: {len(class_names)}")
    print("  GoPoint/vehicle/parser related names:")
    for n in gp_related:
        if n not in seen:
            seen.add(n)
            print(f"    {n!r}")
