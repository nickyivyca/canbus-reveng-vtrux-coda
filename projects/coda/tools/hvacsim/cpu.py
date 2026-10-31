"""S12X (CPU12X) instruction emulator for running HVAC firmware functions as they are.

Added 2026-10-26 (plan step 4) to execute the generated thermal-model code, whose
32-bit fixed-point arithmetic and stack temporaries the decompiler reads badly, and
whose BRSET branches stock Ghidra decodes inverted (notes section 6 / step 4). The
emulator decodes the bytes itself; it never uses Ghidra's listing or p-code.

Scope: the opcodes the HVAC application uses. An opcode or addressing form outside
that set raises `Unimplemented`, never guesses. Global (G-prefixed) instructions, the
RPAGE/EPAGE windows, interrupts, STOP/WAI and the BDM are not modelled.

Memory: `Mem` gives flash from the packed image (read-only; a write raises), RAM
0x0FE000-0x0FFFFF from a bytearray (initialised by the start-up copy-down unless told
otherwise), and the register block 0x0000-0x07FF from a dict whose reads default to 0.
Every register read is logged in `Mem.reg_reads` so a caller can see which hardware the
function consulted.

    from hvacsim.cpu import Cpu
    cpu = Cpu()
    cpu.call(0x7E5853, args=...)      # far CALL, runs until the matching RTC

Condition codes follow the CPU12/CPU12X reference manual. The extended-precision
ops ADED/ADEX/ADEY/SBED/SBEX/SBEY/CPED/CPEX/CPEY/CPES set Z only if the result is 0
AND Z was already set (multi-word compare chains).
"""

from .image import Image, to_global
from .startup import copy_down

RAM_LO, RAM_HI = 0x0FE000, 0x0FFFFF


class Unimplemented(Exception):
    pass


class Mem:
    def __init__(self, img=None, init_ram=True):
        self.img = img or Image()
        self.ram = bytearray(RAM_HI - RAM_LO + 1)
        if init_ram:
            for g, b in copy_down(self.img).items():
                self.ram[g - RAM_LO] = b
        self.regs = {}
        self.reg_reads = []
        self.ram_writes = set()

    def glob(self, local, ppage):
        return to_global(local & 0xFFFF, ppage)

    def rd(self, local, ppage):
        local &= 0xFFFF
        if local < 0x0800:
            self.reg_reads.append(local)
            return self.regs.get(local, 0)
        g = self.glob(local, ppage)
        if RAM_LO <= g <= RAM_HI:
            return self.ram[g - RAM_LO]
        return self.img.u8(g)

    def wr(self, local, ppage, v):
        local &= 0xFFFF
        if local < 0x0800:
            if local == 0x0030:
                raise Unimplemented("PPAGE write through memory at 0x0030")
            self.regs[local] = v & 0xFF
            return
        g = self.glob(local, ppage)
        if RAM_LO <= g <= RAM_HI:
            self.ram[g - RAM_LO] = v & 0xFF
            self.ram_writes.add(g)
            return
        raise Unimplemented("write to flash 0x%06X" % g)

    def g8(self, g):
        return self.ram[g - RAM_LO]

    def s8g(self, g, v):
        self.ram[g - RAM_LO] = v & 0xFF

    def g16(self, g):
        return (self.ram[g - RAM_LO] << 8) | self.ram[g - RAM_LO + 1]

    def s16g(self, g, v):
        self.ram[g - RAM_LO] = (v >> 8) & 0xFF
        self.ram[g - RAM_LO + 1] = v & 0xFF


def _s8(v):
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


def _s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


# register codes for TFR/EXG and the loop primitives
R_A, R_B, R_CCR, R_TMP, R_D, R_X, R_Y, R_SP = range(8)

SENTINEL_PC = 0x0000
SENTINEL_PAGE = 0x00


class Cpu:
    def __init__(self, mem=None, sp=0x2200):
        self.m = mem or Mem()
        self.a = self.b = 0
        self.x = self.y = 0
        self.sp = sp
        self.pc = 0
        self.ppage = 0xFE
        self.n = self.z = self.v = self.c = 0
        self.h = 0
        self.i = 1
        self.steps = 0
        self.trace = None
        self.hooks = {}          # {(ppage or None, local pc): fn(cpu)} run before the instruction

    # ---- registers ----
    @property
    def d(self):
        return (self.a << 8) | self.b

    @d.setter
    def d(self, v):
        v &= 0xFFFF
        self.a, self.b = v >> 8, v & 0xFF

    @property
    def ccr(self):
        return (0x80 | 0x40 | (self.h << 5) | (self.i << 4) | (self.n << 3) |
                (self.z << 2) | (self.v << 1) | self.c)

    @ccr.setter
    def ccr(self, v):
        self.h = (v >> 5) & 1
        self.i = (v >> 4) & 1
        self.n = (v >> 3) & 1
        self.z = (v >> 2) & 1
        self.v = (v >> 1) & 1
        self.c = v & 1

    def getr(self, r):
        return [self.a, self.b, self.ccr & 0xFF, 0, self.d, self.x, self.y, self.sp][r]

    def setr(self, r, v):
        if r == R_A:
            self.a = v & 0xFF
        elif r == R_B:
            self.b = v & 0xFF
        elif r == R_CCR:
            self.ccr = v & 0xFF
        elif r == R_D:
            self.d = v
        elif r == R_X:
            self.x = v & 0xFFFF
        elif r == R_Y:
            self.y = v & 0xFFFF
        elif r == R_SP:
            self.sp = v & 0xFFFF
        else:
            raise Unimplemented("register code %d" % r)

    # ---- memory ----
    def r8(self, a):
        return self.m.rd(a, self.ppage)

    def w8(self, a, v):
        self.m.wr(a, self.ppage, v)

    def r16(self, a):
        return (self.r8(a) << 8) | self.r8((a + 1) & 0xFFFF)

    def w16(self, a, v):
        self.w8(a, (v >> 8) & 0xFF)
        self.w8((a + 1) & 0xFFFF, v & 0xFF)

    def fetch(self):
        v = self.r8(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        hi = self.fetch()
        return (hi << 8) | self.fetch()

    def push8(self, v):
        self.sp = (self.sp - 1) & 0xFFFF
        self.w8(self.sp, v)

    def push16(self, v):
        self.sp = (self.sp - 2) & 0xFFFF
        self.w16(self.sp, v)

    def pull8(self):
        v = self.r8(self.sp)
        self.sp = (self.sp + 1) & 0xFFFF
        return v

    def pull16(self):
        v = self.r16(self.sp)
        self.sp = (self.sp + 2) & 0xFFFF
        return v

    # ---- indexed addressing ----
    def _ireg(self, rr):
        return [self.x, self.y, self.sp, None][rr]

    def _setireg(self, rr, v):
        v &= 0xFFFF
        if rr == 0:
            self.x = v
        elif rr == 1:
            self.y = v
        elif rr == 2:
            self.sp = v
        else:
            raise Unimplemented("auto inc/dec on PC")

    def ea_idx(self, extra_after=0):
        """Decode an indexed postbyte (+ extension bytes) and return the effective
        address. `extra_after` = operand bytes that follow the index bytes (for the
        PC-relative base, which is the address of the next instruction)."""
        xb = self.fetch()
        if (xb & 0x20) == 0:                       # rr0nnnnn: 5-bit constant offset
            rr = (xb >> 6) & 3
            off = xb & 0x1F
            if off & 0x10:
                off -= 0x20
            base = self._ireg(rr) if rr != 3 else (self.pc + extra_after) & 0xFFFF
            return (base + off) & 0xFFFF
        if (xb & 0xE0) != 0xE0:                    # rr1pnnnn: auto pre/post inc/dec
            rr = (xb >> 6) & 3
            post = xb & 0x10
            n = xb & 0x0F
            n = n + 1 if n < 8 else n - 16
            r = self._ireg(rr)
            if post:
                self._setireg(rr, r + n)
                return r
            r = (r + n) & 0xFFFF
            self._setireg(rr, r)
            return r
        rr = (xb >> 3) & 3
        low = xb & 7
        if low in (0, 1):                          # 9-bit offset
            off = self.fetch()
            if low & 1:
                off -= 0x100
            base = self._ireg(rr) if rr != 3 else (self.pc + extra_after) & 0xFFFF
            return (base + off) & 0xFFFF
        if low == 2:                               # 16-bit offset
            off = self.fetch16()
            base = self._ireg(rr) if rr != 3 else (self.pc + extra_after) & 0xFFFF
            return (base + off) & 0xFFFF
        if low == 3:                               # [16-bit offset, r]
            off = self.fetch16()
            base = self._ireg(rr) if rr != 3 else (self.pc + extra_after) & 0xFFFF
            return self.r16((base + off) & 0xFFFF)
        if low == 7:                               # [D, r]
            base = self._ireg(rr) if rr != 3 else (self.pc + extra_after) & 0xFFFF
            return self.r16((base + self.d) & 0xFFFF)
        acc = [self.a, self.b, self.d][low - 4]    # A,r / B,r / D,r (unsigned)
        base = self._ireg(rr) if rr != 3 else (self.pc + extra_after) & 0xFFFF
        return (base + acc) & 0xFFFF

    # ---- flag helpers ----
    def nz8(self, r):
        r &= 0xFF
        self.n = r >> 7
        self.z = int(r == 0)
        return r

    def nz16(self, r):
        r &= 0xFFFF
        self.n = r >> 15
        self.z = int(r == 0)
        return r

    def add8(self, a, b, c=0):
        r = a + b + c
        self.h = int(((a & 0xF) + (b & 0xF) + c) > 0xF)
        self.c = int(r > 0xFF)
        self.v = int(((a ^ r) & (b ^ r) & 0x80) != 0)
        return self.nz8(r)

    def sub8(self, a, b, c=0):
        r = a - b - c
        self.c = int(r < 0)
        self.v = int(((a ^ b) & (a ^ r) & 0x80) != 0)
        return self.nz8(r)

    def add16(self, a, b, c=0, ext=False):
        r = a + b + c
        self.c = int(r > 0xFFFF)
        self.v = int(((a ^ r) & (b ^ r) & 0x8000) != 0)
        z = self.z
        r = self.nz16(r)
        if ext:
            self.z = int(z and r == 0)
        return r

    def sub16(self, a, b, c=0, ext=False):
        r = a - b - c
        self.c = int(r < 0)
        self.v = int(((a ^ b) & (a ^ r) & 0x8000) != 0)
        z = self.z
        r = self.nz16(r)
        if ext:
            self.z = int(z and r == 0)
        return r

    def logic8(self, r):
        self.v = 0
        return self.nz8(r)

    def logic16(self, r):
        self.v = 0
        return self.nz16(r)

    def branch_cond(self, k):
        n, z, v, c = self.n, self.z, self.v, self.c
        return [True, False, not (c or z), bool(c or z), not c, bool(c), not z, bool(z),
                not v, bool(v), not n, bool(n), not (n ^ v), bool(n ^ v),
                not (z or (n ^ v)), bool(z or (n ^ v))][k]

    # ---- read-modify-write unary ops on a value of width w (8 or 16) ----
    def unary(self, op, val, w):
        top = 1 << (w - 1)
        mask = (1 << w) - 1
        nz = self.nz8 if w == 8 else self.nz16
        if op == 0:            # NEG
            r = (-val) & mask
            self.c = int(r != 0)
            self.v = int(r == top)
            return nz(r)
        if op == 1:            # COM
            r = (~val) & mask
            self.c = 1
            self.v = 0
            return nz(r)
        if op == 2:            # INC
            r = (val + 1) & mask
            self.v = int(val == top - 1)
            return nz(r)
        if op == 3:            # DEC
            r = (val - 1) & mask
            self.v = int(val == top)
            return nz(r)
        if op == 4:            # LSR
            self.c = val & 1
            r = nz(val >> 1)
            self.v = self.n ^ self.c
            return r
        if op == 5:            # ROL
            cin = self.c
            self.c = (val >> (w - 1)) & 1
            r = nz(((val << 1) | cin) & mask)
            self.v = self.n ^ self.c
            return r
        if op == 6:            # ROR
            cin = self.c
            self.c = val & 1
            r = nz((val >> 1) | (cin << (w - 1)))
            self.v = self.n ^ self.c
            return r
        if op == 7:            # ASR
            self.c = val & 1
            r = nz((val >> 1) | (val & top))
            self.v = self.n ^ self.c
            return r
        if op == 8:            # ASL
            self.c = (val >> (w - 1)) & 1
            r = nz((val << 1) & mask)
            self.v = self.n ^ self.c
            return r
        if op == 9:            # CLR
            self.n, self.z, self.v, self.c = 0, 1, 0, 0
            return 0
        if op == 0xA:          # TST (handled by caller as no write)
            self.v = 0
            self.c = 0
            return nz(val)
        raise Unimplemented("unary op %d" % op)

    # ---- operand fetch for the 8x-Fx groups ----
    def operand_addr(self, mode):
        """mode: 1 dir, 2 idx, 3 ext. Returns a local address."""
        if mode == 1:
            return self.fetch()
        if mode == 2:
            return self.ea_idx()
        return self.fetch16()

    # ---- run control ----
    def call(self, entry_global, sp=None, max_steps=5_000_000):
        """Far-call a function at a global address and run to its RTC (or RTS for a
        near function in the fixed page). The caller sets registers and pushes
        arguments before calling."""
        if sp is not None:
            self.sp = sp
        if 0x7FC000 <= entry_global <= 0x7FFFFF:
            page, local = 0xFF, 0xC000 | (entry_global & 0x3FFF)
        elif 0x7F4000 <= entry_global <= 0x7F7FFF:
            page, local = 0xFD, 0x4000 | (entry_global & 0x3FFF)
        else:
            page = (entry_global >> 14) & 0xFF
            local = 0x8000 | (entry_global & 0x3FFF)
        # CALL frame: return PC then PPAGE
        self.push16(SENTINEL_PC)
        self.push8(self.ppage if self.ppage else SENTINEL_PAGE)
        self.ret_sp = self.sp
        self.pc, self.ppage = local, page
        self._near_ret = False
        start = self.steps
        while True:
            if self.pc == SENTINEL_PC and self.steps > start:
                return
            self.step()
            if self.steps - start > max_steps:
                raise RuntimeError("step limit at PC %04X page %02X" % (self.pc, self.ppage))

    def jsr_call(self, entry_global, max_steps=5_000_000):
        """Near-call (JSR) a function in the fixed pages; runs to RTS."""
        self.push16(SENTINEL_PC)
        if 0x7FC000 <= entry_global <= 0x7FFFFF:
            self.pc = 0xC000 | (entry_global & 0x3FFF)
        elif 0x7F4000 <= entry_global <= 0x7F7FFF:
            self.pc = 0x4000 | (entry_global & 0x3FFF)
        else:
            self.ppage = (entry_global >> 14) & 0xFF
            self.pc = 0x8000 | (entry_global & 0x3FFF)
        start = self.steps
        while True:
            if self.pc == SENTINEL_PC and self.steps > start:
                return
            self.step()
            if self.steps - start > max_steps:
                raise RuntimeError("step limit at PC %04X" % self.pc)

    # ---- one instruction ----
    def step(self):
        self.steps += 1
        at = self.pc
        if self.trace is not None:
            self.trace(self, at)
        if self.hooks:
            fn = self.hooks.get((self.ppage, at)) or self.hooks.get((None, at))
            if fn is not None:
                fn(self)
        op = self.fetch()
        if op == 0x18:
            return self.page2(at)
        hi, lo = op >> 4, op & 0xF

        # 8x-Fx: accumulator / index register ops in imm, dir, idx, ext
        if op >= 0x80:
            mode = (op >> 4) & 3          # 0 imm, 1 dir, 2 idx, 3 ext
            accb = op >= 0xC0
            k = lo
            # special single-byte entries
            if op == 0x87:
                self.a = self.unary(9, 0, 8)
                return
            if op == 0xC7:
                self.b = self.unary(9, 0, 8)
                return
            if op == 0x97:
                self.unary(0xA, self.a, 8)
                return
            if op == 0xD7:
                self.unary(0xA, self.b, 8)
                return
            if op == 0xA7:          # NOP
                return
            if op == 0xB7:
                return self.tfr_exg(self.fetch())
            if op in (0xE7, 0xF7):  # TST idx/ext
                addr = self.operand_addr(2 if op == 0xE7 else 3)
                self.unary(0xA, self.r8(addr), 8)
                return
            wide = k in (3, 0xC, 0xD, 0xE, 0xF)
            if mode == 0:
                val = self.fetch16() if wide else self.fetch()
                addr = None
            else:
                addr = self.operand_addr(mode)
                if accb and k in (0xA, 0xB) or (not accb and k in (0xA, 0xB)):
                    pass
            if k in (0xA, 0xB) and False:
                pass
            # stores live in 5A-5F, 6A-6F, 7A-7F: not here. Here: SUB CMP SBC SUBD/ADDD
            # AND BIT LDA (CLR) EOR ADC ORA ADD CPD/LDD CPY/LDY CPX/LDX CPS/LDS
            if mode != 0:
                val = self.r16(addr) if wide else self.r8(addr)
            acc = self.b if accb else self.a
            if k == 0:
                r = self.sub8(acc, val)
            elif k == 1:
                self.sub8(acc, val)
                return
            elif k == 2:
                r = self.sub8(acc, val, self.c)
            elif k == 3:
                if accb:
                    self.d = self.add16(self.d, val)
                else:
                    self.d = self.sub16(self.d, val)
                return
            elif k == 4:
                r = self.logic8(acc & val)
            elif k == 5:
                self.logic8(acc & val)
                return
            elif k == 6:
                r = self.logic8(val)
            elif k == 8:
                r = self.logic8(acc ^ val)
            elif k == 9:
                r = self.add8(acc, val, self.c)
            elif k == 0xA:
                r = self.logic8(acc | val)
            elif k == 0xB:
                r = self.add8(acc, val)
            elif k == 0xC:
                if accb:
                    self.d = self.logic16(val)
                else:
                    self.sub16(self.d, val)
                return
            elif k == 0xD:
                if accb:
                    self.y = self.logic16(val)
                else:
                    self.sub16(self.y, val)
                return
            elif k == 0xE:
                if accb:
                    self.x = self.logic16(val)
                else:
                    self.sub16(self.x, val)
                return
            elif k == 0xF:
                if accb:
                    self.sp = self.logic16(val)
                else:
                    self.sub16(self.sp, val)
                return
            else:
                raise Unimplemented("op %02X at %04X" % (op, at))
            if accb:
                self.b = r
            else:
                self.a = r
            return

        # 60-7F: memory unary ops and stores (idx / ext)
        if 0x60 <= op <= 0x7F:
            mode = 2 if op < 0x70 else 3
            if lo <= 9:
                addr = self.operand_addr(mode)
                if lo == 9:
                    self.w8(addr, self.unary(9, 0, 8))
                else:
                    self.w8(addr, self.unary(lo, self.r8(addr), 8))
                return
            addr = self.operand_addr(mode)
            return self.store(lo, addr)
        if 0x5A <= op <= 0x5F:
            return self.store(lo, self.fetch())

        # 40-59 inherent accumulator ops
        if 0x40 <= op <= 0x48:
            self.a = self.unary(lo, self.a, 8)
            return
        if 0x50 <= op <= 0x58:
            self.b = self.unary(lo, self.b, 8)
            return
        if op == 0x49:                     # LSRD
            self.d = self.unary(4, self.d, 16)
            return
        if op == 0x59:                     # ASLD
            self.d = self.unary(8, self.d, 16)
            return

        # 20-2F short branches
        if 0x20 <= op <= 0x2F:
            rel = _s8(self.fetch())
            if self.branch_cond(lo):
                self.pc = (self.pc + rel) & 0xFFFF
            return

        if op == 0x4A:                     # CALL ext
            dest = self.fetch16()
            pg = self.fetch()
            self.push16(self.pc)
            self.push8(self.ppage)
            self.pc, self.ppage = dest, pg
            return
        if op == 0x4B:                     # CALL idx (non-indirect: page byte follows)
            xb = self.r8(self.pc)
            indirect = (xb & 0xE7) in (0xE3, 0xE7)
            if indirect:
                ptr_ea = self._ea_ptr()
                dest = self.r16(ptr_ea)
                pg = self.r8((ptr_ea + 2) & 0xFFFF)
            else:
                dest = self.ea_idx(extra_after=1)
                pg = self.fetch()
            self.push16(self.pc)
            self.push8(self.ppage)
            self.pc, self.ppage = dest, pg
            return
        if op == 0x0A:                     # RTC
            self.ppage = self.pull8()
            self.pc = self.pull16()
            return
        if op == 0x3D:                     # RTS
            self.pc = self.pull16()
            return
        if op == 0x16:                     # JSR ext
            dest = self.fetch16()
            self.push16(self.pc)
            self.pc = dest
            return
        if op == 0x15:                     # JSR idx
            dest = self.ea_idx()
            self.push16(self.pc)
            self.pc = dest
            return
        if op == 0x17:                     # JSR dir
            dest = self.fetch()
            self.push16(self.pc)
            self.pc = dest
            return
        if op == 0x06:                     # JMP ext
            self.pc = self.fetch16()
            return
        if op == 0x05:                     # JMP idx
            self.pc = self.ea_idx()
            return
        if op == 0x07:                     # BSR
            rel = _s8(self.fetch())
            self.push16(self.pc)
            self.pc = (self.pc + rel) & 0xFFFF
            return

        if op in (0x4C, 0x4D, 0x1C, 0x1D, 0x0C, 0x0D):   # BSET/BCLR
            addr = self.fetch() if op in (0x4C, 0x4D) else (
                self.fetch16() if op in (0x1C, 0x1D) else self.ea_idx(extra_after=1))
            mask = self.fetch()
            v = self.r8(addr)
            v = (v | mask) if op in (0x4C, 0x1C, 0x0C) else (v & ~mask)
            self.w8(addr, self.logic8(v))
            return
        if op in (0x4E, 0x4F, 0x1E, 0x1F, 0x0E, 0x0F):   # BRSET/BRCLR
            addr = self.fetch() if op in (0x4E, 0x4F) else (
                self.fetch16() if op in (0x1E, 0x1F) else self.ea_idx(extra_after=2))
            mask = self.fetch()
            rel = _s8(self.fetch())
            v = self.r8(addr)
            if op in (0x4E, 0x1E, 0x0E):
                take = (~v & mask) == 0          # BRSET: all mask bits set
            else:
                take = (v & mask) == 0           # BRCLR: all mask bits clear
            if take:
                self.pc = (self.pc + rel) & 0xFFFF
            return

        if op == 0x04:                     # loop primitives
            pb = self.fetch()
            off = self.fetch()
            if pb & 0x10:
                off -= 0x100
            kind = pb >> 5
            r = pb & 7
            wide = r >= 4
            val = self.getr(r)
            mask = 0xFFFF if wide else 0xFF
            if kind in (0, 1):
                val = (val - 1) & mask
                self.setr(r, val)
            elif kind in (4, 5):
                val = (val + 1) & mask
                self.setr(r, val)
            elif kind not in (2, 3):
                raise Unimplemented("loop primitive %02X" % pb)
            eq = val == 0
            if (kind in (0, 2, 4) and eq) or (kind in (1, 3, 5) and not eq):
                self.pc = (self.pc + off) & 0xFFFF
            return

        if op == 0x19:
            self.y = self.ea_idx()
            return
        if op == 0x1A:
            self.x = self.ea_idx()
            return
        if op == 0x1B:
            self.sp = self.ea_idx()
            return
        if op == 0x02:
            self.y = (self.y + 1) & 0xFFFF
            self.z = int(self.y == 0)
            return
        if op == 0x03:
            self.y = (self.y - 1) & 0xFFFF
            self.z = int(self.y == 0)
            return
        if op == 0x08:
            self.x = (self.x + 1) & 0xFFFF
            self.z = int(self.x == 0)
            return
        if op == 0x09:
            self.x = (self.x - 1) & 0xFFFF
            self.z = int(self.x == 0)
            return
        if op == 0x10:
            self.ccr = self.ccr & self.fetch()
            return
        if op == 0x14:
            self.ccr = self.ccr | self.fetch()
            return
        if op == 0x12:                     # MUL
            r = self.a * self.b
            self.d = r
            self.c = (r >> 7) & 1
            return
        if op == 0x13:                     # EMUL
            r = self.d * self.y
            self.y = (r >> 16) & 0xFFFF
            self.d = r & 0xFFFF
            self.n = (r >> 31) & 1
            self.z = int((r & 0xFFFFFFFF) == 0)
            self.c = (r >> 15) & 1
            return
        if op == 0x11:                     # EDIV
            if self.x == 0:
                raise Unimplemented("EDIV by zero at %04X" % at)
            dividend = (self.y << 16) | self.d
            q, rem = divmod(dividend, self.x)
            self.v = int(q > 0xFFFF)
            self.c = 0
            if not self.v:
                self.y = q
                self.d = rem
            self.n = (q >> 15) & 1
            self.z = int((q & 0xFFFF) == 0)
            return
        if op == 0x30:
            self.x = self.pull16()
            return
        if op == 0x31:
            self.y = self.pull16()
            return
        if op == 0x32:
            self.a = self.pull8()
            return
        if op == 0x33:
            self.b = self.pull8()
            return
        if op == 0x34:
            self.push16(self.x)
            return
        if op == 0x35:
            self.push16(self.y)
            return
        if op == 0x36:
            self.push8(self.a)
            return
        if op == 0x37:
            self.push8(self.b)
            return
        if op == 0x38:
            self.ccr = self.pull8()
            return
        if op == 0x39:
            self.push8(self.ccr)
            return
        if op == 0x3A:
            self.d = self.pull16()
            return
        if op == 0x3B:
            self.push16(self.d)
            return
        raise Unimplemented("op %02X at %04X page %02X" % (op, at, self.ppage))

    def _ea_ptr(self):
        """For indirect indexed CALL: return the address holding the pointer."""
        xb = self.fetch()
        rr = (xb >> 3) & 3
        base = self._ireg(rr)
        if (xb & 7) == 3:
            return (base + self.fetch16()) & 0xFFFF
        return (base + self.d) & 0xFFFF

    def store(self, k, addr):
        if k == 0xA:
            self.w8(addr, self.logic8(self.a))
        elif k == 0xB:
            self.w8(addr, self.logic8(self.b))
        elif k == 0xC:
            self.w16(addr, self.logic16(self.d))
        elif k == 0xD:
            self.w16(addr, self.logic16(self.y))
        elif k == 0xE:
            self.w16(addr, self.logic16(self.x))
        elif k == 0xF:
            self.w16(addr, self.logic16(self.sp))
        else:
            raise Unimplemented("store %X" % k)

    def tfr_exg(self, pb):
        src, dst = (pb >> 4) & 0xF, pb & 0xF
        exg = src & 8
        src &= 7
        if pb in (0x4D, 0x4E):             # SEX D,X / SEX D,Y (CPU12X): sign of D into X/Y
            v = 0xFFFF if self.d & 0x8000 else 0
            if pb == 0x4D:
                self.x = v
            else:
                self.y = v
            return
        if dst & 8:
            raise Unimplemented("TFR/EXG postbyte %02X" % pb)
        sv = self.getr(src)
        swide = src >= 4
        dwide = dst >= 4
        if not exg:
            if not swide and dwide:        # 8 -> 16: sign extend
                v = sv | 0xFF00 if sv & 0x80 else sv
            else:
                v = sv & (0xFFFF if dwide else 0xFF)
            self.setr(dst, v)
            return
        dv = self.getr(dst)
        if swide == dwide:
            self.setr(src, dv)
            self.setr(dst, sv)
        elif not swide and dwide:          # EXG 8,16: 16 <- $00:8, 8 <- low(16)
            self.setr(dst, sv & 0xFF)
            self.setr(src, dv & 0xFF)
        else:                               # EXG 16,8
            self.setr(src, dv & 0xFF)
            self.setr(dst, sv & 0xFF)

    # ---- page 2 (0x18 prefix) ----
    def page2(self, at):
        op = self.fetch()
        hi, lo = op >> 4, op & 0xF
        if 0x20 <= op <= 0x2F:             # long branches
            rel = _s16(self.fetch16())
            if self.branch_cond(lo):
                self.pc = (self.pc + rel) & 0xFFFF
            return
        if op == 0x10:                     # IDIV
            if self.x == 0:
                raise Unimplemented("IDIV by zero at %04X" % at)
            q, r = divmod(self.d, self.x)
            self.x, self.d = q, r
            self.v = 0
            self.c = 0
            self.z = int(q == 0)
            return
        if op == 0x15:                     # IDIVS
            if self.x == 0:
                raise Unimplemented("IDIVS by zero at %04X" % at)
            a, b = _s16(self.d), _s16(self.x)
            q = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                q = -q
            r = a - q * b
            self.v = int(q > 32767 or q < -32768)
            self.x = q & 0xFFFF
            self.d = r & 0xFFFF
            self.c = 0
            self.n = (self.x >> 15) & 1
            self.z = int(self.x == 0)
            return
        if op == 0x13:                     # EMULS
            r = _s16(self.d) * _s16(self.y)
            r &= 0xFFFFFFFF
            self.y = r >> 16
            self.d = r & 0xFFFF
            self.n = (r >> 31) & 1
            self.z = int(r == 0)
            self.c = (r >> 15) & 1
            return
        if op == 0x14:                     # EDIVS
            if self.x == 0:
                raise Unimplemented("EDIVS by zero at %04X" % at)
            a = (self.y << 16) | self.d
            if a & 0x80000000:
                a -= 1 << 32
            b = _s16(self.x)
            q = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                q = -q
            r = a - q * b
            self.v = int(q > 32767 or q < -32768)
            self.c = 0
            if not self.v:
                self.y = q & 0xFFFF
                self.d = r & 0xFFFF
            self.n = (q < 0)
            self.z = int(q == 0)
            return
        if op == 0x11:                     # FDIV
            if self.x == 0 or self.x <= self.d:
                raise Unimplemented("FDIV overflow at %04X" % at)
            q = (self.d << 16) // self.x
            r = (self.d << 16) % self.x
            self.x, self.d = q & 0xFFFF, r & 0xFFFF
            self.z = int(self.x == 0)
            self.v = 0
            self.c = 0
            return
        if op == 0x17:                     # CBA
            self.sub8(self.a, self.b)
            return
        if op == 0x16:                     # SBA
            self.a = self.sub8(self.a, self.b)
            return
        if op == 0x06:                     # ABA
            self.a = self.add8(self.a, self.b)
            return
        if op == 0x0E:                     # TAB
            self.b = self.logic8(self.a)
            return
        if op == 0x0F:                     # TBA
            self.a = self.logic8(self.b)
            return
        if op in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D):   # MOVB
            return self.movb(op)
        if op in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05):   # MOVW
            return self.movw(op)
        # CPU12X X/Y mirror of 4x/5x inherent ops
        if 0x40 <= op <= 0x48:
            self.x = self.unary(lo, self.x, 16)
            return
        if 0x50 <= op <= 0x58:
            self.y = self.unary(lo, self.y, 16)
            return
        if op == 0x87:
            self.x = self.unary(9, 0, 16)
            return
        if op == 0xC7:
            self.y = self.unary(9, 0, 16)
            return
        if op == 0x97:
            self.unary(0xA, self.x, 16)
            return
        if op == 0xD7:
            self.unary(0xA, self.y, 16)
            return
        if op in (0xE7, 0xF7):             # TSTW idx/ext
            addr = self.operand_addr(2 if op == 0xE7 else 3)
            self.unary(0xA, self.r16(addr), 16)
            return
        # word memory unary ops 18 60-69 / 70-79
        if 0x60 <= op <= 0x79 and lo <= 9:
            addr = self.operand_addr(2 if op < 0x70 else 3)
            if lo == 9:
                self.w16(addr, self.unary(9, 0, 16))
            else:
                self.w16(addr, self.unary(lo, self.r16(addr), 16))
            return
        # 18 8x-Fx: X (8x-Bx) / Y (Cx-Fx) arithmetic, 16-bit operands
        if op >= 0x80:
            mode = (op >> 4) & 3
            isy = op >= 0xC0
            k = lo
            if k in (0x6, 0xA, 0xB) and False:
                pass
            if mode == 0:
                val = self.fetch16()
            else:
                val = self.r16(self.operand_addr(mode))
            reg = self.y if isy else self.x
            if k == 0x0:
                r = self.sub16(reg, val)
            elif k == 0x2:
                r = self.sub16(reg, val, self.c, ext=True)
            elif k == 0x3:
                if isy:
                    self.d = self.add16(self.d, val, self.c, ext=True)     # ADED
                else:
                    self.d = self.sub16(self.d, val, self.c, ext=True)     # SBED
                return
            elif k == 0x4:
                r = self.logic16(reg & val)
            elif k == 0x5:
                self.logic16(reg & val)
                return
            elif k == 0x8:
                r = self.logic16(reg ^ val)
            elif k == 0x9:
                r = self.add16(reg, val, self.c, ext=True)
            elif k == 0xA:
                r = self.logic16(reg | val)
            elif k == 0xB:
                r = self.add16(reg, val)
            elif k == 0xC and not isy:
                self.sub16(self.d, val, self.c, ext=True)                  # CPED
                return
            elif k == 0xD and not isy:
                self.sub16(self.y, val, self.c, ext=True)                  # CPEY
                return
            elif k == 0xE and not isy:
                self.sub16(self.x, val, self.c, ext=True)                  # CPEX
                return
            elif k == 0xF and not isy:
                self.sub16(self.sp, val, self.c, ext=True)                 # CPES
                return
            else:
                raise Unimplemented("18 %02X at %04X" % (op, at))
            if isy:
                self.y = r
            else:
                self.x = r
            return
        raise Unimplemented("18 %02X at %04X page %02X" % (op, at, self.ppage))

    def movb(self, op):
        if op == 0x08:     # #,idx : 18 08 xb ii
            dst = self.ea_idx(extra_after=1)
            v = self.fetch()
        elif op == 0x09:   # ext,idx : 18 09 xb hh ll
            dst = self.ea_idx(extra_after=2)
            v = self.r8(self.fetch16())
        elif op == 0x0A:   # idx,idx
            src = self.ea_idx(extra_after=1)
            v = self.r8(src)
            dst = self.ea_idx()
        elif op == 0x0B:   # #,ext : 18 0B ii hh ll
            v = self.fetch()
            dst = self.fetch16()
        elif op == 0x0C:   # ext,ext
            v = self.r8(self.fetch16())
            dst = self.fetch16()
        else:              # idx,ext : 18 0D xb hh ll
            src = self.ea_idx(extra_after=2)
            v = self.r8(src)
            dst = self.fetch16()
        self.w8(dst, v)

    def movw(self, op):
        if op == 0x00:     # #,idx : 18 00 xb jj kk
            dst = self.ea_idx(extra_after=2)
            v = self.fetch16()
        elif op == 0x01:   # ext,idx
            dst = self.ea_idx(extra_after=2)
            v = self.r16(self.fetch16())
        elif op == 0x02:   # idx,idx
            src = self.ea_idx(extra_after=1)
            v = self.r16(src)
            dst = self.ea_idx()
        elif op == 0x03:   # #,ext
            v = self.fetch16()
            dst = self.fetch16()
        elif op == 0x04:   # ext,ext
            v = self.r16(self.fetch16())
            dst = self.fetch16()
        else:              # idx,ext
            src = self.ea_idx(extra_after=2)
            v = self.r16(src)
            dst = self.fetch16()
        self.w16(dst, v)
