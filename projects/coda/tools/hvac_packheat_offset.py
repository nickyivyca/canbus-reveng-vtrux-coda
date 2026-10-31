#!/usr/bin/env python3
"""Read or set the Coda HVAC pack-heat offset live over UDS (HVAC decompile notes section 8).

    py -3.12 projects/coda/tools/hvac_packheat_offset.py --read
    py -3.12 projects/coda/tools/hvac_packheat_offset.py --offset-c 5
    py -3.12 projects/coda/tools/hvac_packheat_offset.py --restore
    py -3.12 projects/coda/tools/hvac_packheat_offset.py --offset-c 5 --dry-run

What it changes (notes/hvac/coda-hvac-decompile-notes.md section 7.6): the HVAC heats the pack
until the coldest cell reaches AllowedCellTempMin (0x390 B5, 8 degC from the BMS) + 2 degC, and
the calibration byte 0x24C9 adds value/4 degC to AllowedCellTempMin. That byte is RAM,
initialised from flash at start-up, and is byte 1 of DID E1AD (RAM 0x24C8-0x24CB). A write is
lost when the HVAC resets or sleeps, which is intended: this is a test, not a flash.

The exchange, physical tester 0x750 -> HVAC 0x758, single-frame ISO-TP, no session and no
SecurityAccess (the firmware's 2E handler checks neither, notes 6.2; not yet tried on the car):

    22 E1 AC                    fingerprint: must read 9C 09 0A 01, the flash image's value
    22 E1 AD                    current value: bytes 0, 2, 3 must read 00 .. 14 14
    2E E1 AD b0 NEW b2 b3       only byte 1 changes; expect 6E E1 AD
    22 E1 AD                    read back; must equal what was written

Anything else stops the script before a write, or reports the failure after one. The two
fingerprint reads guard against a different firmware, whose E1xx layout would not be this
one. The firmware copies exactly 4 bytes for any E1xx write, whatever the request length
(0x7E4E20 reads the count from 0x2A5A, a copy-down constant 4 that nothing writes; the
dispatcher at 0x7F8AF0 checks only the physical ID), so the write always carries all four.

Only 0x22 and 0x2E to E1AC/E1AD can leave this script; anything else is refused before the
bus (Tester._guard). --dry-run prints every frame and opens no bus. Before a write the script
shows old and new and asks you to type "write" (skip with --yes).

The dongle is found as flash_cal.py does (--transport auto): exactly one CAN interface must be
present. Plug it into the OBD port; the gateway routes 0x750/0x758 to the HVAC on B CAN, as for
the 2026-10-25 reflash. The HVAC has to be awake (ignition on); no answer means it is not.

Test against the fake HVAC in test_hvac_packheat_offset.py:
    python3.13 projects/coda/tools/test_hvac_packheat_offset.py
"""

import argparse
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

from flash_sim import uds                                # noqa: E402
from flash_sim.bus import REAL_BRANDS, VIRTUAL_DEFAULT_PORT, open_bus  # noqa: E402
from flash_sim.isotp import IsoTpEndpoint, IsoTpError    # noqa: E402

logger = logging.getLogger("hvac_packheat_offset")

TX_ID = 0x750          # physical tester request
RX_ID = 0x758          # HVAC response
PAD = 0xAA             # IsoTpEndpoint's default padding

DID_FINGERPRINT = 0xE1AC
DID_OFFSET = 0xE1AD
# Values the 2026-10-25 flash image copies into RAM at start-up (hvacsim.startup.copy_down;
# test_hvac_packheat_offset.py checks these against the image).
FINGERPRINT = bytes([0x9C, 0x09, 0x0A, 0x01])          # RAM 0x24C4-0x24C7
STOCK = bytes([0x00, 0x00, 0x14, 0x14])                # RAM 0x24C8-0x24CB
OFFSET_BYTE = 1                                        # 0x24C9
KEEP = (0, 2, 3)                                       # bytes that must read stock

ALLOWED = {
    0x22: {DID_FINGERPRINT, DID_OFFSET},
    0x2E: {DID_OFFSET},
}


class Refused(Exception):
    """The ECU's answer was not the one this script requires; nothing further is sent."""


# -- encoding -------------------------------------------------------------------

def raw_from_c(degc):
    """degC -> signed quarter-degree raw byte value. Must be a whole number of quarters."""
    q = degc * 4
    if abs(q - round(q)) > 1e-9:
        raise ValueError("%g degC is not a multiple of 0.25 degC" % degc)
    raw = int(round(q))
    if not -128 <= raw <= 127:
        raise ValueError("%g degC is outside -32.00..+31.75 degC" % degc)
    return raw


def c_from_byte(b):
    return (b - 0x100 if b & 0x80 else b) / 4.0


def read_request(did):
    return bytes([0x22, did >> 8, did & 0xFF])


def write_request(did, data):
    if len(data) != 4:
        raise ValueError("an E1xx write must carry exactly 4 bytes")
    return bytes([0x2E, did >> 8, did & 0xFF]) + bytes(data)


def single_frame(payload, pad=PAD):
    """The 8-byte CAN frame IsoTpEndpoint sends for a payload of up to 7 bytes."""
    if len(payload) > 7:
        raise ValueError("not a single frame")
    f = bytes([len(payload)]) + bytes(payload)
    return f + bytes([pad]) * (8 - len(f))


def with_offset(current, raw):
    out = bytearray(current)
    out[OFFSET_BYTE] = raw & 0xFF
    return bytes(out)


def parse_read(did, resp):
    """Positive 22 response -> the 4 data bytes; Refused on anything else."""
    if resp is None:
        raise Refused("no response to 22 %04X: is the HVAC awake (ignition on)?" % did)
    if uds.is_negative(resp):
        raise Refused("22 %04X refused: %s" % (did, uds.describe(resp)))
    want = bytes([0x62, did >> 8, did & 0xFF])
    if resp[:3] != want or len(resp) != 7:
        raise Refused("22 %04X: unexpected response %s" % (did, resp.hex(" ")))
    return bytes(resp[3:])


def parse_write(did, resp):
    if resp is None:
        raise Refused("no response to 2E %04X; read it back before assuming anything" % did)
    if uds.is_negative(resp):
        raise Refused("2E %04X refused: %s" % (did, uds.describe(resp)))
    if bytes(resp) != bytes([0x6E, did >> 8, did & 0xFF]):
        raise Refused("2E %04X: unexpected response %s" % (did, resp.hex(" ")))


def check_layout(fingerprint, current):
    if fingerprint != FINGERPRINT:
        raise Refused("E1AC reads %s, the analysed firmware has %s: a different HVAC firmware, "
                      "whose E1xx layout is unknown. Not writing."
                      % (fingerprint.hex(" "), FINGERPRINT.hex(" ")))
    bad = [i for i in KEEP if current[i] != STOCK[i]]
    if bad:
        raise Refused("E1AD reads %s; bytes %s differ from the image's %s. Not writing."
                      % (current.hex(" "), bad, STOCK.hex(" ")))


# -- transport ------------------------------------------------------------------

class Tester:
    """One UDS request at a time over IsoTpEndpoint. bus=None means dry run (frames printed only)."""

    def __init__(self, bus, timeout=1.0):
        self.dry_run = bus is None
        self.tp = None if self.dry_run else IsoTpEndpoint(bus, TX_ID, RX_ID, padding=PAD)
        self.timeout = timeout

    @staticmethod
    def _guard(payload):
        sid = payload[0]
        did = (payload[1] << 8) | payload[2] if len(payload) >= 3 else None
        if sid not in ALLOWED or did not in ALLOWED[sid]:
            raise AssertionError("BLOCKED: %s is outside this script's scope" % payload.hex(" "))
        if sid == 0x22 and len(payload) != 3:
            raise AssertionError("BLOCKED: malformed read %s" % payload.hex(" "))
        if sid == 0x2E and len(payload) != 7:
            raise AssertionError("BLOCKED: an E1xx write must carry exactly 4 bytes")

    def request(self, payload, pending_budget=10):
        """Send one request; return the response payload (positive or 0x7F), or None on timeout."""
        payload = bytes(payload)
        self._guard(payload)
        logger.info("  TX %03X  %s", TX_ID, single_frame(payload).hex(" ").upper())
        if self.dry_run:
            return None
        self.tp.send_uds(payload)
        timeout = self.timeout
        for _ in range(pending_budget):
            try:
                resp = self.tp.recv_uds(timeout=timeout)
            except IsoTpError as e:
                logger.warning("  ISO-TP error: %s", e)
                return None
            if resp is None:
                logger.info("  RX %03X  (timeout)", RX_ID)
                return None
            logger.info("  RX %03X  %s   %s", RX_ID, resp.hex(" ").upper(), uds.describe(resp))
            if uds.is_response_pending(resp):
                timeout = max(timeout, 5.0)
                continue
            return resp
        return None


# -- sequence -------------------------------------------------------------------

def describe_value(data):
    off = c_from_byte(data[OFFSET_BYTE])
    return ("E1AD = %s: pack-heat offset %+.2f degC (heating stops at AllowedCellTempMin + 2 %+.2f "
            "degC; with the 8 degC the BMS sends, %.2f degC)" % (data.hex(" ").upper(), off, off,
                                                               8 + 2 + off))


def run(tester, raw=None, confirm=None):
    """raw=None: read only. Otherwise write byte 1 = raw. Returns the process exit code.

    confirm(old, new) -> bool is asked before the write; None means no question.
    """
    if tester.dry_run:
        return dry_run(raw)

    logger.info("== fingerprint (22 E1AC) ==")
    fp = parse_read(DID_FINGERPRINT, tester.request(read_request(DID_FINGERPRINT)))
    logger.info("== current value (22 E1AD) ==")
    current = parse_read(DID_OFFSET, tester.request(read_request(DID_OFFSET)))
    check_layout(fp, current)
    logger.info("%s", describe_value(current))
    if raw is None:
        return 0

    new = with_offset(current, raw)
    if new == current:
        logger.info("Already %s; nothing written.", new.hex(" ").upper())
        return 0
    logger.info("Write: %s -> %s", current.hex(" ").upper(), new.hex(" ").upper())
    logger.info("       %s", describe_value(new))
    if confirm is not None and not confirm(current, new):
        logger.info("Not confirmed; nothing written.")
        return 1

    logger.info("== write (2E E1AD) ==")
    parse_write(DID_OFFSET, tester.request(write_request(DID_OFFSET, new)))
    logger.info("== read back (22 E1AD) ==")
    back = parse_read(DID_OFFSET, tester.request(read_request(DID_OFFSET)))
    if back != new:
        raise Refused("read back %s, wrote %s" % (back.hex(" "), new.hex(" ")))
    logger.info("OK. %s", describe_value(back))
    logger.info("RAM only: the HVAC returns to %+.2f degC when it resets or sleeps.",
                c_from_byte(STOCK[OFFSET_BYTE]))
    return 0


def dry_run(raw):
    """Print every frame of the sequence, assuming the HVAC answers with the image's values."""
    logger.info("DRY RUN: no bus opened. Responses assumed to be the flash image's values.")
    for did in (DID_FINGERPRINT, DID_OFFSET):
        Tester._guard(read_request(did))
        logger.info("  TX %03X  %s", TX_ID, single_frame(read_request(did)).hex(" ").upper())
    logger.info("%s", describe_value(STOCK))
    if raw is None:
        return 0
    new = with_offset(STOCK, raw)
    logger.info("Write: %s -> %s", STOCK.hex(" ").upper(), new.hex(" ").upper())
    logger.info("       %s", describe_value(new))
    w = write_request(DID_OFFSET, new)
    Tester._guard(w)
    logger.info("  TX %03X  %s", TX_ID, single_frame(w).hex(" ").upper())
    logger.info("  TX %03X  %s", TX_ID, single_frame(read_request(DID_OFFSET)).hex(" ").upper())
    return 0


# -- CLI ------------------------------------------------------------------------

def pick_transport(args):
    """Resolve --transport auto to the brand of the single CAN interface present (as flash_cal.py)."""
    if args.transport != "auto":
        return
    from canbench.live.receiver import detect_all_can_interfaces
    found = detect_all_can_interfaces(args.bitrate)
    if not found:
        raise SystemExit("--transport auto found no CAN interface. Is the dongle plugged in and its "
                         "driver installed?")
    if len(found) > 1:
        lines = "".join("\n  --transport %-9s  %s" % (i[0], i[2]) for i in found)
        raise SystemExit("--transport auto found %d CAN interfaces and will not guess:%s\n"
                         "Unplug the others, or name the brand with --transport." % (len(found), lines))
    args.transport = found[0][0]
    logger.info("auto: using %s", found[0][2])


def build_argparser():
    p = argparse.ArgumentParser(
        description="Read or set the Coda HVAC pack-heat offset (DID E1AD byte 1) live over UDS.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    what = p.add_mutually_exclusive_group(required=True)
    what.add_argument("--read", action="store_true", help="read and decode only")
    what.add_argument("--offset-c", type=float, metavar="DEGC",
                      help="set the offset in degC, a multiple of 0.25, -32.00..+31.75")
    what.add_argument("--raw", type=int, metavar="N", help="set the signed raw byte, -128..127")
    what.add_argument("--restore", action="store_true",
                      help="set the offset back to the flash image's value (0)")
    p.add_argument("--dry-run", action="store_true", help="print the frames; open no bus")
    p.add_argument("--yes", action="store_true", help="do not ask before writing")
    p.add_argument("--timeout", type=float, default=1.0, help="per-request timeout, seconds")
    p.add_argument("--transport", default="auto", choices=("auto", "virtual") + REAL_BRANDS,
                   help="'auto' = the single CAN interface present; 'virtual' = localhost bus")
    p.add_argument("--channel", default=None, help="dongle channel (default: auto-detected)")
    p.add_argument("--port", type=int, default=VIRTUAL_DEFAULT_PORT, help="virtual transport port")
    p.add_argument("--bitrate", "-b", type=int, default=500000)
    p.add_argument("--debug", action="store_true")
    return p


def raw_from_args(args):
    if args.read:
        return None
    if args.restore:
        return STOCK[OFFSET_BYTE]
    if args.raw is not None:
        if not -128 <= args.raw <= 127:
            raise SystemExit("--raw must be -128..127")
        return args.raw
    try:
        return raw_from_c(args.offset_c)
    except ValueError as e:
        raise SystemExit(str(e))


def ask(old, new):
    try:
        return input('Type "write" to send it: ').strip() == "write"
    except EOFError:
        return False


def main(argv=None):
    args = build_argparser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    raw = raw_from_args(args)
    if args.dry_run:
        return run(Tester(None), raw)

    pick_transport(args)
    bus = open_bus(args, logger=logger)
    try:
        return run(Tester(bus, timeout=args.timeout), raw, confirm=None if args.yes else ask)
    except Refused as e:
        logger.error("STOPPED: %s", e)
        return 3
    finally:
        bus.shutdown()


if __name__ == "__main__":
    sys.exit(main())
