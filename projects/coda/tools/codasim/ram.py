"""DLCM RAM, keyed by real address (plan R1/R2).

Blocks take handles by SYMBOL NAME and read/write through them:

    trq = ram.var("TrqLast")      # resolved via dlcm_symbols.csv: address + type
    trq.set(trq.get() + step)     # set() narrows to the declared width, as st.h does

Why addresses rather than Python attributes:
  - a trace of the model is directly comparable with a trace of the firmware, and
    with live RAM reads over UDS (`dlcm_ram_probe.py` reads real addresses);
  - two names for one address (a0-relative vs absolute) share storage, as they do
    on the chip, instead of silently becoming two variables;
  - a variable the CSV has no row for cannot be used, so the CSV grows with the model.

Overlap is checked: declaring a variable whose bytes overlap a different
declaration raises, rather than letting a 32-bit accumulator and a 16-bit view of
it drift apart. (Deliberate views can be added later with an explicit alias call.)

UNSOURCED INPUTS (plan R4, automatic). Every read and every write is recorded by
address. `unsourced()` lists variables that were read but never written -- by a
block, a sink or an explicit `assume()`. Each one is an input the model consumed
as a silent zero, which is the Mode-1 failure in its purest form, so every run
header prints the list.

Power-on state is all zeros (the firmware's .bss clear). `reset()` restores it;
`keep` lists names that survive a reset (NVM-mirrored counters, e.g. the ECM2
occurrence counter -- worklog 6H.55).
"""

from .fixedpoint import s8, u8, s16, u16, s32, u32

_NARROW = {"u8": u8, "s8": s8, "u16": u16, "s16": s16, "u32": u32, "s32": s32}
_SIZE = {"u8": 1, "s8": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4}


class Var:
    __slots__ = ("ram", "name", "address", "type", "_narrow")

    def __init__(self, ram, name, address, typ):
        self.ram, self.name, self.address, self.type = ram, name, address, typ
        self._narrow = _NARROW[typ]

    def get(self):
        self.ram.read.add(self.address)
        return self.ram.mem.get(self.address, 0)

    def set(self, value):
        v = self._narrow(int(value))
        self.ram.mem[self.address] = v
        self.ram.written.add(self.address)
        return v

    def __repr__(self):
        return "<%s 0x%08X %s = %d>" % (self.name, self.address, self.type, self.get())


class Ram:
    def __init__(self, symbols):
        self.sym = symbols
        self.mem = {}
        self.vars = {}
        self._extent = {}          # address -> (end_exclusive, name)
        self.read, self.written = set(), set()
        self.assumed = {}          # name -> (value, why)

    def var(self, name):
        v = self.vars.get(name)
        if v is not None:
            return v
        addr, typ = self.sym.var(name)
        if typ not in _SIZE:
            raise ValueError("%s is type %r; Ram holds scalars only" % (name, typ))
        end = addr + _SIZE[typ]
        for a, (e, other) in self._extent.items():
            if a < end and addr < e and not (a == addr and e == end):
                raise ValueError("%s [0x%08X..0x%08X) overlaps %s [0x%08X..0x%08X)"
                                 % (name, addr, end, other, a, e))
        prev = self._extent.get(addr)
        if prev and self.vars[prev[1]].type != typ:
            raise ValueError("%s and %s share 0x%08X with types %s/%s"
                             % (name, prev[1], addr, typ, self.vars[prev[1]].type))
        self._extent.setdefault(addr, (end, name))
        v = self.vars[name] = Var(self, name, addr, typ)
        return v

    def assume(self, name, value, why):
        """Hold a variable at a declared constant: an input the model does not
        source, stated rather than defaulted. Re-applied by reset()."""
        self.assumed[name] = (int(value), why)
        self.var(name).set(value)

    def reset(self, keep=()):
        saved = {n: self.mem.get(self.var(n).address, 0) for n in keep}
        self.mem.clear()
        for n, val in saved.items():
            self.var(n).set(val)
        for n, (val, _) in self.assumed.items():
            self.var(n).set(val)

    def unsourced(self):
        names = {v.address: n for n, v in self.vars.items()}
        return sorted(names.get(a, "0x%08X" % a) for a in self.read - self.written)

    def snapshot(self, names=None):
        names = names or list(self.vars)
        return {n: self.vars[n].get() for n in names}
