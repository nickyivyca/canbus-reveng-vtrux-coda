"""HVAC RAM and registers, keyed by S12X global address (rules 1, 2, 4).

Same contract as codasim's `ram.py`: blocks take handles by symbol name, stores narrow
to the declared type, two names for one address share storage, and `unsourced()`
lists variables read but never written (each is an input the model consumed as a
silent zero). Big-endian: a u16 at A is bytes A, A+1, as on the chip.

    ram = Ram(Symbols())
    v = ram.var("SomeVariable")
    v.set(v.get() + 1)
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
        return "<%s 0x%06X %s = %d>" % (self.name, self.address, self.type, self.get())


class Ram:
    def __init__(self, symbols):
        self.sym = symbols
        self.mem, self.vars, self.span = {}, {}, {}
        self.read, self.written = set(), set()

    def var(self, name):
        if name in self.vars:
            return self.vars[name]
        addr, typ = self.sym.var(name)
        n = _SIZE[typ]
        for a in range(addr, addr + n):
            other = self.span.get(a)
            if other is not None and other != name:
                raise ValueError("%s overlaps %s at 0x%06X" % (name, other, a))
        for a in range(addr, addr + n):
            self.span[a] = name
        v = self.vars[name] = Var(self, name, addr, typ)
        return v

    def assume(self, name, value):
        """Declare an input's value explicitly (it then no longer counts as unsourced)."""
        return self.var(name).set(value)

    def unsourced(self):
        return sorted(v.name for v in self.vars.values()
                      if v.address in self.read and v.address not in self.written)

    def reset(self, keep=()):
        kept = {self.vars[n].address: self.mem.get(self.vars[n].address, 0) for n in keep}
        self.mem = dict(kept)
        self.read, self.written = set(), set(kept)
