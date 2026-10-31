"""Shared plumbing for the DLCM blocks."""


class Ctx:
    """What every block needs: the image (CAL + PROG), the symbol map and RAM."""

    def __init__(self, image, symbols, ram):
        self.img, self.sym, self.ram = image, symbols, ram


class Block:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ram = ctx.ram

    def v(self, name):
        return self.ctx.ram.var(name)

    def k(self, name):
        """A flash constant (CAL scalar or PROG data) by symbol name, read at its type."""
        a, t = self.ctx.sym.var(name)
        return self.ctx.img.read(a, t)

    def t1(self, name):
        return self.ctx.img.table1d(self.ctx.sym.addr(name))

    def t2(self, name):
        return self.ctx.img.table2d(self.ctx.sym.addr(name))
