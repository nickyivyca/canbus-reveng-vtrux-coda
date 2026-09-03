#!/usr/bin/env python3
"""Generate parity test cases for cancore's SlcanParityTest.

Runs a reference SLCAN reader over the 914 VCU capture fixtures, copies the
fixtures into cancore's test resources, and writes a flat TSV of expected
results the Kotlin test consumes from the classpath.

The Kotlin SlcanReader must agree with this reader on every counter and on a
digest taken over every delivered frame in order. Parity between two
implementations is not proof on its own -- a misreading shared by both would
survive it -- but the block CRCs are an independent oracle: they were computed
by the firmware over the bytes it actually wrote, so a tokenizer that splits
the stream wrongly cannot make them verify.

TSV columns (tab-separated):
    fixture_basename
    key
    value

Keys per fixture:
    frames          data frames delivered (integrity frames excluded)
    integrity       integrity frames seen
    csv             CSV records (dual-emit builds interleave them)
    acks            bare-CR acknowledgements
    malformed       tokens rejected as not-a-frame and not-CSV
    oversize        tokens discarded for exceeding MAX_TOKEN
    blocksChecked   blocks closed by an integrity frame, after sync
    blocksCrcBad    of those, CRC mismatches
    blocksCountBad  of those, frame-count mismatches
    digest          FNV-1a 64 over every delivered frame, hex
    sample.<n>      id:ext:dlc:datahex for the first and last frames

Run from project root:
    py -3.12 tools/slcan_parity_generate.py
"""
from __future__ import annotations

import argparse
import gzip
import re
import shutil
from pathlib import Path

# The VCU's integrity frame. Excluded from both the CRC and the frame count --
# it reports the block before it and its own bytes are never part of any block.
SEQ_ID = 0x1FFFFFFF

# Longest legal token. A frame is at most 26 characters (T + 8 id + 1 dlc +
# 16 data). CSV records in the dual-emit fixtures reach 1260. 4096 leaves room
# without letting a stream that never terminates grow without bound.
MAX_TOKEN = 4096

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK64 = 0xFFFFFFFFFFFFFFFF

# (basename, expect_clean)
#
# Every fixture's counters are asserted exactly, which is the real test: the
# reader must both refrain from inventing damage and actually detect the damage
# that is there.
#
# expect_clean=True additionally demands zero block failures. Only
# serial-full-slcan.log.gz qualifies -- it is the one capture recorded as having
# no link damage at all. Its 1381 checked blocks are an INDEPENDENT oracle, not
# parity: those CRCs were computed by the VCU over the bytes it actually wrote,
# so a reader that tokenizes the stream wrongly cannot make them verify.
#
# serial-dualemit-verify.log.gz carries two real corruption events, both of
# documented kinds, each costing its block one frame (15 counted vs 16
# declared):
#   - Mode 1, single-byte insertion: token "8t001800003F0100000000" -- a stray
#     '8' ahead of an otherwise valid frame, which is correctly rejected.
#   - Mode 2, whole-frame loss: a block short by one frame with no malformed
#     token anywhere near it, so the frame left no trace at all.
#
# serial-slcan-realistic.log.gz (2026-08-09) predates the integrity frame's
# switch to little-endian and carries BIG-endian integrity frames from the first
# prototype, so every one of its blocks reads as corrupt and its block counters
# say nothing about link health. It is kept for volume and damage coverage: 226k
# frames, a capture that begins mid-frame, and five real corruption events at
# token indices 0, 23300, 90851, 101758 and 135801. This is also why
# slcan_analyze.py decodes big-endian -- it was written the same day, against
# this capture. See outstanding-changes.md item 2.
DEFAULT_FIXTURES = [
    ("serial-full-slcan.log.gz", True),
    ("serial-dualemit-verify.log.gz", False),
    ("serial-slcan-realistic.log.gz", False),
]
# The 914 notes hub is a sibling of this workspace. Both live under the same
# SeaDrive root, so the relative path holds across machines even though the
# root itself does not.
DEFAULT_FIXTURE_DIR = Path("../914/notes/artifacts")
DEFAULT_OUT_DIR = Path("android-app/CanLoggerApps/cancore/src/test/resources")

_HEX = re.compile(r"^[0-9A-Fa-f]+$")


def crc16_ccitt(crc: int, data: bytes) -> int:
    """CCITT-FALSE, polynomial 0x1021, MSB first. Matches crc_byte() in Slcan.cpp."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_frame(token: str):
    """Return (id, extended, dlc, data) or None if the token is not a well-formed frame."""
    if not token:
        return None
    kind = token[0]
    if kind not in "tTrR":
        return None
    id_len = 3 if kind in "tr" else 8
    remote = kind in "rR"
    if len(token) < 1 + id_len + 1:
        return None
    id_str = token[1 : 1 + id_len]
    dlc_str = token[1 + id_len]
    body = token[2 + id_len :]
    if not _HEX.match(id_str) or not _HEX.match(dlc_str):
        return None
    dlc = int(dlc_str, 16)
    if dlc > 8:
        return None
    if remote:
        if body:
            return None
        return int(id_str, 16), not remote or id_len == 8, dlc, b""
    if len(body) != dlc * 2 or (body and not _HEX.match(body)):
        return None
    return int(id_str, 16), id_len == 8, dlc, bytes.fromhex(body)


class Reference:
    """Reference SLCAN reader. Mirrors the intended Kotlin SlcanReader exactly."""

    def __init__(self):
        self.frames = []
        self.counts = dict(
            frames=0, integrity=0, csv=0, acks=0, malformed=0, oversize=0,
            blocksChecked=0, blocksCrcBad=0, blocksCountBad=0,
        )
        self._buf = bytearray()
        self._discarding = False
        self._crc = 0xFFFF
        self._count = 0
        self._synced = False
        self._digest = FNV_OFFSET

    def feed(self, data: bytes) -> None:
        i, n = 0, len(data)
        while i < n:
            b = data[i]
            if b in (0x0D, 0x0A):
                # Absorb CRLF as one terminator. The mbed console translates the
                # CSV record's '\n' into '\r\n', so treating them separately
                # invents an empty token after every CSV record and reports it
                # as a bare-CR ack that never happened.
                step = 2 if b == 0x0D and i + 1 < n and data[i + 1] == 0x0A else 1
                if self._discarding:
                    self._discarding = False
                    self._buf.clear()
                else:
                    self._token(bytes(self._buf), step)
                    self._buf.clear()
                i += step
                continue
            if not self._discarding:
                self._buf.append(b)
                if len(self._buf) > MAX_TOKEN:
                    self.counts["oversize"] += 1
                    self._discarding = True
                    self._buf.clear()
            i += 1

    def _token(self, raw: bytes, term_len: int) -> None:
        if not raw:
            # Only a lone CR produces an empty token once CRLF is absorbed.
            if term_len == 1:
                self.counts["acks"] += 1
            return
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            self.counts["malformed"] += 1
            return
        parsed = parse_frame(text)
        if parsed is None:
            if b"," in raw:
                self.counts["csv"] += 1
            else:
                self.counts["malformed"] += 1
            return
        ident, extended, dlc, data = parsed
        if extended and ident == SEQ_ID:
            self._integrity(data)
            return
        # The firmware CRCs the exact bytes it wrote, terminator included.
        self._crc = crc16_ccitt(self._crc, raw + b"\r")
        self._count += 1
        self.counts["frames"] += 1
        self.frames.append((ident, extended, dlc, data))
        self._mix(ident, extended, dlc, data)

    def _integrity(self, payload: bytes) -> None:
        self.counts["integrity"] += 1
        declared_count = payload[2] | (payload[3] << 8)
        declared_crc = payload[4] | (payload[5] << 8)
        if self._synced:
            self.counts["blocksChecked"] += 1
            if declared_crc != self._crc:
                self.counts["blocksCrcBad"] += 1
            if declared_count != self._count:
                self.counts["blocksCountBad"] += 1
        # The first block is not checked: a capture may start mid-block, so its
        # frame count and CRC are incomplete through no fault of the reader.
        self._synced = True
        self._crc = 0xFFFF
        self._count = 0

    def _mix(self, ident: int, extended: bool, dlc: int, data: bytes) -> None:
        enc = bytes(
            [(ident >> 24) & 0xFF, (ident >> 16) & 0xFF, (ident >> 8) & 0xFF, ident & 0xFF,
             1 if extended else 0, dlc]
        ) + data
        d = self._digest
        for b in enc:
            d = ((d ^ b) * FNV_PRIME) & MASK64
        self._digest = d

    @property
    def digest(self) -> int:
        return self._digest


def read_fixture(path: Path) -> bytes:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as fh:
            return fh.read()
    return path.read_bytes()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--fixtures", nargs="*", default=DEFAULT_FIXTURES)
    ap.add_argument("--samples", type=int, default=20,
                    help="frames sampled from each end, for diagnosable failures")
    args = ap.parse_args()

    out_dir = args.output_dir
    fixture_out = out_dir / "slcan"
    fixture_out.mkdir(parents=True, exist_ok=True)

    rows = []
    for name, expect_clean in args.fixtures:
        src = args.fixture_dir / name
        if not src.exists():
            raise SystemExit("fixture not found: %s" % src)
        # Ship the fixtures compressed and whole. The corruption events in
        # serial-slcan-realistic sit at token indices 0, 23300, 90851, 101758
        # and 135801 -- spread across the file, so any trimmed slice would drop
        # coverage of exactly the cases this test exists for.
        shutil.copy2(src, fixture_out / name)

        data = read_fixture(src)
        ref = Reference()
        ref.feed(data)

        print("%-32s %s" % (name, "  ".join(
            "%s=%d" % (k, v) for k, v in ref.counts.items())))
        print("%-32s digest=%016x  bytes=%d" % ("", ref.digest, len(data)))

        if expect_clean and (ref.counts["blocksCrcBad"] or ref.counts["blocksCountBad"]):
            raise SystemExit(
                "%s is declared clean but %d of %d blocks failed. Either the "
                "reference reader is wrong or the capture is not what it claims "
                "to be -- do not ship these expectations."
                % (name, ref.counts["blocksCrcBad"] + ref.counts["blocksCountBad"],
                   ref.counts["blocksChecked"]))

        for key, value in ref.counts.items():
            rows.append((name, key, str(value)))
        rows.append((name, "digest", "%016x" % ref.digest))
        rows.append((name, "expectClean", "1" if expect_clean else "0"))

        n = args.samples
        picks = list(range(min(n, len(ref.frames))))
        picks += [i for i in range(max(0, len(ref.frames) - n), len(ref.frames))
                  if i not in picks]
        for idx in picks:
            ident, extended, dlc, payload = ref.frames[idx]
            rows.append((name, "sample.%d" % idx,
                         "%08X:%d:%d:%s" % (ident, 1 if extended else 0, dlc,
                                            payload.hex().upper())))

    tsv = out_dir / "slcan_parity_cases.tsv"
    with open(tsv, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# generated by tools/slcan_parity_generate.py -- do not edit\n")
        for fixture, key, value in rows:
            fh.write("%s\t%s\t%s\n" % (fixture, key, value))
    print("\nwrote %s (%d rows)" % (tsv, len(rows)))
    print("wrote fixtures to %s" % fixture_out)


if __name__ == "__main__":
    main()
