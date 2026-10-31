"""`hvac_symbols.csv` as the lookup table (rule 1: addresses by symbol name).

Same contract as codasim's `symbols.py`: the CSV in
`notes/hvac/artifacts/hvac_symbols.csv` is the source of truth, the Ghidra database
is derived from it (`ghidra/scripts/DlcmApplySymbols.java`, program-agnostic), and
hvacsim resolves addresses through it. Addresses are S12X global.

    S = Symbols()
    S.addr("SomeFunction")     -> global address
    S.var("SomeVariable")      -> (address, "u16"); raises if untyped
"""

import csv
import os
from typing import NamedTuple

from .image import HVAC

CSV_PATH = os.path.join(HVAC, "artifacts", "hvac_symbols.csv")


class Symbol(NamedTuple):
    address: int
    name: str
    kind: str
    end: int
    type: str
    confidence: str
    source: str
    role: str


class Symbols:
    def __init__(self, path=CSV_PATH):
        self.path = path
        self.by_name, self.by_addr = {}, {}
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r = {k: (v or "").strip() for k, v in r.items()}
                s = Symbol(int(r["address"], 16), r["name"], r["kind"],
                           int(r["end"], 16) if r["end"] else 0, r.get("type", ""),
                           r["confidence"], r["source"], r["role"])
                if s.name in self.by_name or s.address in self.by_addr:
                    raise ValueError("duplicate symbol %s / 0x%06X in %s" % (s.name, s.address, path))
                self.by_name[s.name] = s
                self.by_addr[s.address] = s

    def __getitem__(self, name):
        try:
            return self.by_name[name]
        except KeyError:
            raise KeyError("%r is not in %s -- add the row (with its source) "
                           "rather than using a literal address" % (name, self.path))

    def __contains__(self, name):
        return name in self.by_name

    def addr(self, name):
        return self[name].address

    def var(self, name):
        s = self[name]
        if s.kind not in ("data", "cal"):
            raise ValueError("%s is kind=%s, not a variable" % (name, s.kind))
        if not s.type:
            raise ValueError("%s has no type in %s; rule 2 needs width and sign" % (name, self.path))
        return s.address, s.type

    def at(self, address):
        return self.by_addr.get(address)
