"""`dlcm_symbols.csv` as a programmatic lookup table (user, 2026-10-09).

The CSV stays where it is and stays the source of truth for names: the Ghidra
database is derived from it (`ghidra/scripts/DlcmApplySymbols.java`), and codasim
resolves addresses through it (plan R1) -- so a block names `TrqUpperBoundSlewed`,
not 0xD000514E, and a renamed or retyped row is seen by both at once.

    S = Symbols()
    S["MotorSpeedSignedX2"].address    -> 0xD0005114
    S.var("MotorSpeedSignedX2")        -> (0xD0005114, "s16"); raises if untyped
    S.at(0x80052370)                   -> the row at that address, or None
    S.containing(0x800523F0)           -> the function/fragment whose span holds it

`var()` refuses a row with no `type`: R2 says every state variable has a declared
width and sign, and the refusal is what makes the CSV get completed as the model
grows rather than the model guessing. Edit the CSV with a hand-check by
`dlcm_symbols_validate.py` (the Java reader cannot report a malformed row).
"""

import csv
import os
from typing import NamedTuple

from .image import DLCM

CSV_PATH = os.path.join(DLCM, "artifacts", "dlcm_symbols.csv")


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
                    raise ValueError("duplicate symbol %s / 0x%08X in %s"
                                     % (s.name, s.address, path))
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
            raise ValueError("%s has no type in %s; R2 needs width and sign"
                             % (name, self.path))
        return s.address, s.type

    def at(self, address):
        return self.by_addr.get(address)

    def containing(self, address):
        best = None
        for s in self.by_addr.values():
            if s.kind in ("function", "fragment") and s.end and s.address <= address <= s.end:
                if best is None or s.address > best.address:
                    best = s
        return best
