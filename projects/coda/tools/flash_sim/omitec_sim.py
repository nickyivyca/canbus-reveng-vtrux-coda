#!/usr/bin/env python3
"""Omitec reflash simulator (the tester side).

Drives the Coda DLCM UDS reflash the way the Omitec scanner does: default
session, identification reads, programming session, security unlock, then for
each firmware segment an erase routine, RequestDownload, a TransferData loop
over the real binary, TransferExit, and a verify routine. Reads the real
coda_dlcm_prog.bin / coda_dlcm_cal.bin so the bytes on the wire are authentic.

Run it against gateway_sim.py over the localhost virtual bus:
    py -3.12 gateway_sim.py --time-scale 0.02      # in one terminal
    py -3.12 omitec_sim.py  --max-blocks 20        # in another

Later this same script can drive a real DLCM (via a dongle) and can apply CAL
byte patches in flight (--patch), which is the on-ramp to flashing the DLCM
directly from a laptop instead of the Omitec.

    py -3.12 omitec_sim.py --patch 0xA0021532=05,00 --patch 0xA0021B6E=05,00

A human-facing flash of a named CAL image is projects/coda/tools/flash_cal.py, which drives
OmitecSim with the real-flash defaults.

Block-to-block pacing is a knob (--block-delay-ms). The real Omitec idles ~217
ms per block; the DLCM itself accepts a block in ~8 ms, so 0 (default) flashes
as fast as the ECU allows -- the whole point of getting off the Omitec.
"""

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import can

import uds
import timing as T
from bus import add_bus_args, open_bus
from isotp import IsoTpEndpoint, IsoTpError
from busload import add_busload_args, governor_from_args
import seedkey

logger = logging.getLogger("omitec_sim")

HERE = Path(__file__).resolve().parent
DLCM_DIR = HERE.parents[1] / "notes" / "dlcm"   # the images and artifacts (flash_sim moved to tools/ 2026-10-17)

# Firmware segments in flash order, matching the real capture.
#
# NOTE THE BASE IMAGE. "cal" is the STOCK dump, not whatever is currently on the
# car. A flash writes base + patches, so every byte where the base differs from
# the car and the patch set does not cover it is SILENTLY REVERTED, while the
# flash reports success and 0xFF01 returns its usual 00 00 00 0C (which is a
# readability check, not a content CRC -- see coda-dlcm-decompile-notes.md
# lines 296 and 320). This nearly bit on 2026-09-20: the car was on FLOOR5,
# the base here is stock, and the two differ at exactly 0xA0021532 and
# 0xA0021B6E (01 -> 05). It was harmless only because the vcurve-floor-20
# preset happens to overwrite both. A preset that did not would have quietly
# undone FLOOR5. check_base_covers_car() below makes that a hard error instead
# of a coincidence.
SEGMENTS = {
    "prog": dict(addr=0x80040000, bin=DLCM_DIR / "coda_dlcm_prog.bin",
                 erase_data=bytes([0x02])),
    "cal":  dict(addr=0xA0020000, bin=DLCM_DIR / "coda_dlcm_cal.bin",
                 erase_data=bytes([0x03])),
}

# What is believed to be on the car right now, per segment. Used only by the
# coverage check. Set to None to skip the check for a segment (and say why).
# Updated 2026-09-23 23:38 after the negTrqLast scale-3 flash (456 blocks via the
# OBD/Diag-CAN gateway, verify 7101ff010000000c). Previously the floor-40 image;
# before that FLOOR20. Leaving this pointing at a superseded image would make the
# coverage check compare against a calibration the car no longer holds -- and it
# would PASS while doing so, which is the exact silent-revert failure the check
# exists to prevent.
#
# Update this on EVERY flash, together with the cumulative preset. The two are a
# pair: the preset carries every deviation from stock that must survive, and this
# file is what proves nothing was left out.
CAL_ON_CAR = DLCM_DIR / "artifacts" / "cal_as_flashed_20261025_regen13_brakeblend.bin"
ON_CAR = {"cal": CAL_ON_CAR, "prog": None}

# Retained as regression data, NOT as a gate. The seed/key algorithm is now
# implemented in seedkey.py, so any seed the ECU offers can be answered; this
# pair comes from the flash6 capture and seedkey.compute_key reproduces it.
CAPTURED_SEED = bytes.fromhex("7c876e19")
CAPTURED_KEY = bytes.fromhex("2726966f")
BLOCK_DATA_LEN = 252  # data bytes per TransferData block (2+252 = 254 <= maxBlockLen 255)

# Named CAL patch presets -- the "DLCM flash script's modifications" folded in
# from ../dlcm_flash_proxy.py (DEFAULT_PATCHES). vcurve-lash-5 raises the V-curve
# lash minimum from 1 to 5 (LE int16, 01 00 -> 05 00) at the two CAL flash
# addresses. Supporting evidence is in the DLCM notes (search the addresses).
DLCM_PATCH_PRESETS = {
    "vcurve-lash-5": [
        (0xA0021532, bytes([0x05, 0x00])),
        (0xA0021B6E, bytes([0x05, 0x00])),
    ],
    # Raise the near-zero gradient-limiter V-curve floor to 20 (both copies).
    # Stock curve idx0-9 = [62,35,15,10,10,1,20,40,70,70]; idx2..idx5 (15,10,10,1)
    # are all below 20, so all four are raised on each copy to make 20 the true
    # minimum. Matches dlcm_flash_proxy.py PATCH_PRESETS["vcurve-floor-20"].
    "vcurve-floor-20": [
        (0xA002152C, bytes([0x14, 0x00])),
        (0xA002152E, bytes([0x14, 0x00])),
        (0xA0021530, bytes([0x14, 0x00])),
        (0xA0021532, bytes([0x14, 0x00])),
        (0xA0021B68, bytes([0x14, 0x00])),
        (0xA0021B6A, bytes([0x14, 0x00])),
        (0xA0021B6C, bytes([0x14, 0x00])),
        (0xA0021B6E, bytes([0x14, 0x00])),
    ],
    # Floor 40 on BOTH rising-side limbs, both copies. Base is the FLOOR20
    # image on the car, not stock: every "from" here reads 20 (0x14).
    #
    # Two tables, because the rising step is min(speed limb, V-curve) and
    # raising only one leaves the other binding:
    #   - V-curve   (gradientLimiterPositive_TrqLast) idx2..idx6 -> 40.
    #     idx6 IS included here; vcurve-floor-20 above did not need it because
    #     stock idx6 was already 20. idx7 is already 40, so 40 is the ceiling
    #     for a monotone curve -- above it the floor overtakes idx7 and notches.
    #   - speed limb (gradientLimiterPositive_VehSpd) low end -> 40. Below the
    #     knee (~116 CAN rpm) this reads 20 and pins min() at 20 no matter how
    #     high the V-curve floor goes, so a launch from a standstill would not
    #     change at all without it.
    #
    # The two copies use DIFFERENT speed axes: the live table is unsigned and
    # its 20s sit at idx0/idx1; the monitor copy is signed ([-256,-128,128,256,
    # 14720]) and its 20s sit at idx1/idx2. That is why the addresses below are
    # not symmetric between copies. Generated and verified by
    # artifacts/zero_crossing_change_list.py; independently rebuilt from the
    # table descriptors by the DLCM Ghidra session, byte-identical, candidate
    # image md5 baf6061d96c1c5a57740241bba613c24.
    "vcurve-floor-40-speedlimb-40": [
        (0xA0021508, bytes([0x28, 0x00])),   # speed limb, live,    idx0
        (0xA002150A, bytes([0x28, 0x00])),   # speed limb, live,    idx1
        (0xA002152C, bytes([0x28, 0x00])),   # V-curve,    live,    idx2
        (0xA002152E, bytes([0x28, 0x00])),   # V-curve,    live,    idx3
        (0xA0021530, bytes([0x28, 0x00])),   # V-curve,    live,    idx4
        (0xA0021532, bytes([0x28, 0x00])),   # V-curve,    live,    idx5
        (0xA0021534, bytes([0x28, 0x00])),   # V-curve,    live,    idx6
        (0xA0021B4E, bytes([0x28, 0x00])),   # speed limb, monitor, idx1
        (0xA0021B50, bytes([0x28, 0x00])),   # speed limb, monitor, idx2
        (0xA0021B68, bytes([0x28, 0x00])),   # V-curve,    monitor, idx2
        (0xA0021B6A, bytes([0x28, 0x00])),   # V-curve,    monitor, idx3
        (0xA0021B6C, bytes([0x28, 0x00])),   # V-curve,    monitor, idx4
        (0xA0021B6E, bytes([0x28, 0x00])),   # V-curve,    monitor, idx5
        (0xA0021B70, bytes([0x28, 0x00])),   # V-curve,    monitor, idx6
    ],
    # ARM 1, the falling side. Scales gradientLimiterNegative_TrqLast idx0..idx3
    # by 3.0 on the FLOOR40 base: -10,-10,-7,-4 -> -30,-30,-21,-12, both copies.
    #
    # SCALED, NOT FLATTENED, AND THAT IS THE POINT. The table mirrors the V-curve
    # including its notch -- the -4 at x=0 is a deliberate soft spot at the zero
    # crossing. Setting a block of rungs to one value deletes it and makes the
    # hand-off abrupt. Scaling holds |y[idx3]|/|y[idx0]| at 0.40, the ratio the
    # car already has, so the crossing keeps its give and just happens faster.
    #
    # 3.0 is the CEILING, not a preference: at 4.0 |y[idx3]| = 16 exceeds
    # |y[idx4]| = 15 and the notch inverts -- the crossing stops being the
    # softest point. Same kind of constraint as idx7 = 40 capping the rising side.
    #
    # idx4..idx9 untouched: idx4/idx5 are already -15, faster than the notch, and
    # scaling them would push them past idx6 (-20) and dip the curve. The descent
    # above +80 is only ~170 ms of ~1010 ms, so there is little there to win.
    #
    # Predicted: lift-off to the -276 raw coast plateau, 1010 -> 490 ms, with time
    # spent inside +/-80 counts of zero falling 230 -> 110 ms.
    # Generated and guarded by artifacts/negative_path_change_list.py; mechanism
    # in artifacts/negative_path_mechanism.py. Candidate image
    # cal_candidate_negtrq_scale3_on_floor40.bin md5 1224c0c1647b127c11397df10ebdd263.
    "negtrq-scale-3": [
        (0xA00214E8, bytes([0xE2, 0xFF])),   # negTrqLast, live,    idx0  x=-3000
        (0xA00214EA, bytes([0xE2, 0xFF])),   # negTrqLast, live,    idx1  x=-80
        (0xA00214EC, bytes([0xEB, 0xFF])),   # negTrqLast, live,    idx2  x=-70
        (0xA00214EE, bytes([0xF4, 0xFF])),   # negTrqLast, live,    idx3  x=0
        (0xA0021BB4, bytes([0xE2, 0xFF])),   # negTrqLast, monitor, idx0
        (0xA0021BB6, bytes([0xE2, 0xFF])),   # negTrqLast, monitor, idx1
        (0xA0021BB8, bytes([0xEB, 0xFF])),   # negTrqLast, monitor, idx2
        (0xA0021BBA, bytes([0xF4, 0xFF])),   # negTrqLast, monitor, idx3
    ],
}

# CUMULATIVE PRESETS -- READ THIS BEFORE ADDING A PRESET OR PICKING ONE.
#
# A CAL flash rebuilds the WHOLE segment from the stock image plus patches. It
# does not read the car and edit in place. So a preset must carry EVERY
# deviation from stock that should survive, not just the new ones: flashing
# "negtrq-scale-3" on its own would write stock V-curve and stock speed-limb
# bytes and silently undo FLOOR40.
#
# check_base_covers_car() turns that into a hard error rather than a surprise --
# it refuses any flash where a byte differs between stock and the on-car
# reference and is not in the patch set. It would have caught this. The preset
# below exists so the right thing is also the easy thing.
#
# Built by concatenation rather than by copying addresses, so the FLOOR40 half
# can never drift from the preset that was actually flashed on 2026-09-23.
DLCM_PATCH_PRESETS["floor40-negtrq-scale-3"] = (
    DLCM_PATCH_PRESETS["vcurve-floor-40-speedlimb-40"]
    + DLCM_PATCH_PRESETS["negtrq-scale-3"])

IGNITION_REQ_ID = 0x710
IGNITION_RESP_ID = 0x718
IGNITION_POLL = bytes([0x03, 0x22, 0x64, 0x01, 0x00, 0x00, 0x00, 0x00])  # 22 64 01


class IgnitionPoller(threading.Thread):
    """Reproduce the Omitec's continuous ignition/keepalive poll.

    Runs on its OWN bus socket (so it never contends with the flash dialog's
    recv) and, exactly like the real Omitec on 0x710, sends ReadDataByIdentifier
    DID 0x6401 every `interval` seconds and reads the 0x718 response. A missing
    response is how the real Omitec detects ignition-off / comms-loss.
    """

    def __init__(self, bus, interval=3.0):
        super().__init__(daemon=True)
        self.bus = bus
        self.interval = interval
        self._abort = threading.Event()
        self.polls = 0
        self.responses = 0
        self.last_state = None
        self.state_history = []   # ordered distinct ignition states observed

    def stop(self):
        self._abort.set()

    def run(self):
        next_poll = 0.0
        while not self._abort.is_set():
            now = time.monotonic()
            if now >= next_poll:
                self._poll_once()
                next_poll = now + self.interval
            self._drain(timeout=0.1)

    def _poll_once(self):
        try:
            self.bus.send(can.Message(arbitration_id=IGNITION_REQ_ID,
                                      data=IGNITION_POLL, is_extended_id=False))
            self.polls += 1
        except Exception as e:
            logger.debug("ignition poll send error: %s", e)

    def _drain(self, timeout):
        try:
            msg = self.bus.recv(timeout=timeout)
        except Exception:
            return
        if msg is None or msg.arbitration_id != IGNITION_RESP_ID:
            return
        d = bytes(msg.data)
        if len(d) >= 5 and d[1] == 0x62 and d[2] == 0x64 and d[3] == 0x01:
            self.responses += 1
            state = d[4]
            if state != self.last_state:
                logger.info("ignition poll: ECU reports state 0x%02X", state)
                self.last_state = state
                self.state_history.append(state)


class UdsRejected(Exception):
    def __init__(self, request_sid, nrc):
        super().__init__("service 0x%02X rejected: %s" % (request_sid, uds.nrc_name(nrc)))
        self.request_sid = request_sid
        self.nrc = nrc


class SafetyAbort(Exception):
    """Abort the flash BEFORE any erase/download when a precondition fails
    (e.g. the ECU returns a security seed we don't have the key for)."""


def patches_from_target(target_path, seg_name="cal"):
    """Derive the patch set as the diff from the stock base to a target image.

    WHY THIS EXISTS. A flash writes base + patches, so a preset must carry EVERY
    deviation from stock that should survive -- not just the new edits. As the
    stack of accepted changes grows (floor 40, then negTrqLast, then C1) the
    hand-maintained cumulative preset grows with it, and every entry is a chance
    to fat-finger an address. Pointing at the image you actually want removes
    that class of error entirely: the patch set IS the diff, by construction, so
    it cannot omit an earlier change or mistype one.

    Emits one patch per contiguous run of differing bytes, so the flash log
    stays readable instead of listing hundreds of single bytes.
    """
    seg = SEGMENTS[seg_name]
    base = seg["bin"].read_bytes()
    target = Path(target_path).read_bytes()
    if len(target) != len(base):
        raise SystemExit("target image is %d bytes, segment %s base is %d"
                         % (len(target), seg_name, len(base)))
    out = []
    i = 0
    while i < len(base):
        if base[i] == target[i]:
            i += 1
            continue
        j = i
        while j < len(base) and base[j] != target[j]:
            j += 1
        out.append((seg["addr"] + i, target[i:j]))
        i = j
    return out


def parse_patch_arg(s):
    """Parse 'ADDR=BB,BB[,BB...]' patch spec (flash address, hex bytes)."""
    if "=" not in s:
        raise argparse.ArgumentTypeError("invalid patch '%s', expected ADDR=BB,BB" % s)
    addr_s, bytes_s = s.split("=", 1)
    addr = int(addr_s, 16)
    parts = [p for p in bytes_s.replace(" ", ",").split(",") if p]
    if not parts:
        raise argparse.ArgumentTypeError("invalid patch '%s', no bytes" % s)
    return (addr, bytes(int(p, 16) for p in parts))


class OmitecSim:
    def __init__(self, endpoint, patches=None, block_delay_ms=0.0, max_blocks=0,
                 security_level=0x01, whole_image=None, image_bytes=None):
        self.ep = endpoint
        self.patches = patches or []
        # Name of the complete CAL image being flashed (flash_cal.py), or None for a patch flash.
        self.whole_image = whole_image
        # The complete segment image to write, when the caller already holds it
        # (flash_cal.py). The CAL is then written from these bytes directly rather
        # than rebuilt as stock + patches: patches_from_target() derived the patch
        # set as the diff OF this image, so re-applying it at flash time is a
        # round-trip back to the same bytes. It bought nothing and it ran inside
        # the programming session, which is what broke the 2026-10-25 attempt.
        self.image_bytes = image_bytes
        self.block_delay_s = block_delay_ms / 1000.0
        self.max_blocks = max_blocks
        self.security_level = security_level
        self.governor = None
        self.total_blocks = 0

    # -- UDS request/response with responsePending handling ------------------

    def request(self, payload, expect_sid=None, allow_nrc=()):
        """Send a UDS request; wait through 0x78 pendings for the final response.

        Returns the response payload. Raises UdsRejected on an unexpected NRC.
        """
        self.ep.send_uds(payload)
        req_sid = payload[0]
        while True:
            resp = self.ep.recv_uds(timeout=T.RESPONSE_PENDING_TESTER_TIMEOUT_S)
            if resp is None:
                raise IsoTpError("no response to service 0x%02X" % req_sid)
            if uds.is_response_pending(resp):
                logger.debug("  responsePending for 0x%02X ...", req_sid)
                continue
            if uds.is_negative(resp):
                nrc = resp[2] if len(resp) > 2 else 0
                if nrc in allow_nrc:
                    return resp
                raise UdsRejected(req_sid, nrc)
            if expect_sid is not None and resp[0] != expect_sid:
                logger.warning("unexpected response 0x%02X to service 0x%02X",
                               resp[0], req_sid)
            return resp

    # -- flash phases --------------------------------------------------------

    def preamble(self):
        logger.info("--- session setup + identification ---")
        r = self.request(bytes([0x10, 0x01]))
        logger.info("DiagSession default -> %s", r.hex())
        for did in (0xF194, 0xF1A1, 0xF18B, 0xF18C):
            try:
                r = self.request(bytes([0x22, did >> 8, did & 0xFF]))
                logger.info("ReadDataById 0x%04X -> %s", did, r[3:].hex())
            except UdsRejected as e:
                logger.info("ReadDataById 0x%04X rejected (%s)", did, uds.nrc_name(e.nrc))
        r = self.request(bytes([0x10, 0x02]))
        logger.info("DiagSession programming -> %s", r.hex())

    def security_unlock(self, level=0x01):
        """SecurityAccess requestSeed/sendKey, computing the key ourselves.

        Replaces the old behaviour, which held one captured (seed, key) pair and
        aborted on any other seed -- the DLCM's algorithm was unknown at the
        time. It is now implemented in seedkey.py: a 48-round LFSR with taps at
        4/11/20/29 keyed by a per-level constant, reproducing all 13 captured
        pairs including the three from genuine level-01/02 flash sessions.

        An all-zero seed means the ECU considers itself already unlocked and
        ISO 14229 says to skip sendKey; sending a key anyway earns NRC 0x24
        (requestSequenceError).
        """
        logger.info("--- security access (level 0x%02X) ---", level)
        r = self.request(bytes([0x27, level]))
        seed = bytes(r[2:])
        logger.info("SecurityAccess seed -> %s", seed.hex())
        if len(seed) != 4:
            raise SafetyAbort(
                "ECU returned a %d-byte seed, expected 4 (%s). The key routine "
                "is only known for a 32-bit seed; aborting before any "
                "erase/download." % (len(seed), seed.hex()))
        if not any(seed):
            logger.info("seed is all zero -- already unlocked, skipping sendKey")
            return
        key = seedkey.key_for_level(seed, level)
        if seed == CAPTURED_SEED and key != CAPTURED_KEY:
            # The one seed we have independent ground truth for. If the computed
            # key disagrees there, the implementation is broken and every other
            # key it produces is worthless -- stop before touching flash.
            raise SafetyAbort(
                "seedkey regression: for the captured seed %s we computed %s but "
                "the real Omitec sent %s. Aborting before any erase/download."
                % (seed.hex(), key.hex(), CAPTURED_KEY.hex()))
        logger.info("computed key -> %s", key.hex())
        self.request(bytes([0x27, level + 1]) + key)
        logger.info("SecurityAccess granted (level 0x%02X)", level)

    def check_base_covers_car(self, name, seg_addr, base):
        """Refuse to flash if this write would silently revert the car.

        Compares the base image against what is believed to be on the car and
        requires every differing byte to be covered by the patch set. A byte
        that differs and is not patched will be written back to its base value
        with no error anywhere in the protocol.
        """
        ref = ON_CAR.get(name)
        if ref is None:
            logger.warning("segment %s: no on-car reference, base-coverage "
                           "check SKIPPED -- a silent revert cannot be "
                           "detected for this segment", name)
            return
        if not ref.exists():
            raise SystemExit(
                "refusing to flash %s: the on-car reference %s does not "
                "exist, so it cannot be shown that this write will not "
                "silently revert part of the calibration. Create it, or set "
                "ON_CAR[%r] = None with a written reason." % (name, ref, name))
        car = ref.read_bytes()
        if len(car) != len(base):
            raise SystemExit(
                "refusing to flash %s: on-car reference is %d bytes, base is "
                "%d" % (name, len(car), len(base)))
        if self.whole_image and name == "cal":
            # A named image is the complete calibration wanted on the car, so a byte the car has
            # and the image does not is meant to go back to the image's value. Report it, don't refuse.
            target = (self.image_bytes if self.image_bytes is not None
                      else self._apply_patches(seg_addr, base, log=False))
            n = sum(1 for o in range(len(base)) if target[o] != car[o])
            logger.info("whole image '%s': %d byte(s) change against the on-car reference %s",
                        self.whole_image, n, ref.name)
            return
        covered = set()
        for paddr, pbytes in self.patches:
            for i in range(len(pbytes)):
                off = paddr + i - seg_addr
                if 0 <= off < len(base):
                    covered.add(off)
        naked = [o for o in range(len(base))
                 if base[o] != car[o] and o not in covered]
        if naked:
            show = ", ".join("0x%08X (base %02X, car %02X)"
                             % (seg_addr + o, base[o], car[o])
                             for o in naked[:12])
            raise SystemExit(
                "refusing to flash %s: %d byte(s) differ between the base "
                "image and the car and are NOT in the patch set, so this "
                "flash would silently revert them: %s%s"
                % (name, len(naked), show,
                   " ..." if len(naked) > 12 else ""))
        diffs = sum(1 for o in covered if base[o] != car[o])
        logger.info("base-coverage check OK for %s: %d differing byte(s), all "
                    "inside the patch set", name, diffs)

    def _apply_patches(self, seg_addr, data, log=True):
        """Return a patched copy of data with any in-range patches applied."""
        buf = bytearray(data)
        end = seg_addr + len(buf)
        applied = 0
        for paddr, pbytes in self.patches:
            for i, b in enumerate(pbytes):
                tgt = paddr + i
                if seg_addr <= tgt < end:
                    off = tgt - seg_addr
                    old = buf[off]
                    buf[off] = b
                    applied += 1
                    if log:
                        # DEBUG, not INFO. One line PER BYTE, so a full CAL image emits
                        # hundreds. On 2026-10-25, 845 of them to a PowerShell console took
                        # ~8 s, which overran the 5 s S3 timer between SecurityAccess and the
                        # erase: RoutineControl 0xFF00 came back 7F 31 7F
                        # (serviceNotSupportedInActiveSession) with 0 blocks sent.
                        #
                        # The VOLUME was not the change. Four earlier real flashes printed
                        # 730 / 746 / 746 / 456 of these lines between the grant and the
                        # erase and the gap was 0-1 s every time
                        # (artifacts/flash_*_obd.log). So per-line cost varies by ~10-50x
                        # across setups (~1 ms then, ~10 ms that day) and the slowdown is
                        # UNEXPLAINED -- candidates, none verified and none ranked:
                        # redirected vs live-console stdout, a log file flushing to
                        # SeaDrive, the host, the transport.
                        #
                        # Those four logs are NOT a clean control, so do not reason from
                        # the per-line figure as if one variable moved. They carry an "om:"
                        # prefix the current code does not emit (a different logger config),
                        # they ran omitec_sim rather than flash_cal, and they state
                        # gs_usb (Innomaker) where 2026-10-25 used ixxat HW630227. Their
                        # stdout destination is not recoverable from them either: the files
                        # hold no tee header or echoed command, and a redirected run and a
                        # saved console run leave identical content, so their existence
                        # cannot distinguish the two (checked 2026-10-25).
                        #
                        # Do not record "the patch set outgrew the window": that is refuted
                        # (746 lines in <=1 s against 845 in ~8 s).
                        #
                        # The general trap: anything slow between SecurityAccess and the
                        # erase overruns S3, because nothing here sends TesterPresent.
                        # Use --debug to see these lines.
                        logger.debug("PATCH flash 0x%08X: 0x%02X -> 0x%02X", tgt, old, b)
        if applied and log:
            logger.info("applied %d patch byte(s) to segment 0x%08X", applied, seg_addr)
        return bytes(buf)

    def _whole_image_data(self, seg_addr, base):
        """The caller's complete image, cross-checked against its own patch set.

        Writing the image bytes directly and rebuilding stock + patches are two
        expressions of the same thing, because patches_from_target() derived the
        patch set as the diff from `base` to this image. Comparing them keeps the
        guarantee the patch path gave -- that what goes on the car is exactly the
        reviewed image -- while costing one pass over the segment instead of a
        patch log inside the session window. A disagreement means
        patches_from_target() and the image have diverged, so stop before erasing.
        """
        if len(self.image_bytes) != len(base):
            raise SafetyAbort("whole image '%s' is %d bytes, segment base is %d"
                              % (self.whole_image, len(self.image_bytes), len(base)))
        derived = self._apply_patches(seg_addr, base, log=False)
        if derived != self.image_bytes:
            n = sum(1 for a, b in zip(derived, self.image_bytes) if a != b)
            raise SafetyAbort(
                "whole image '%s' and its own derived patch set disagree on %d "
                "byte(s); aborting before any erase" % (self.whole_image, n))
        logger.info("whole image '%s': %d patch byte(s) vs stock, verified against "
                    "the image; writing the image bytes directly",
                    self.whole_image, sum(len(b) for _a, b in self.patches))
        return bytes(self.image_bytes)

    def flash_segment(self, name):
        seg = SEGMENTS[name]
        addr = seg["addr"]
        data = seg["bin"].read_bytes()
        self.check_base_covers_car(name, addr, data)
        if self.image_bytes is not None and name == "cal":
            data = self._whole_image_data(addr, data)
        else:
            data = self._apply_patches(addr, data)
        length = len(data)
        logger.info("=== segment %s: addr=0x%08X len=0x%X (%d bytes) ===",
                    name, addr, length, length)

        # erase routine (RoutineControl 0xFF00 with segment-specific data)
        logger.info("erase routine (0xFF00 data=%s) ...", seg["erase_data"].hex())
        t0 = time.monotonic()
        self.request(bytes([0x31, 0x01, 0xFF, 0x00]) + seg["erase_data"])
        logger.info("erase complete (%.1fs)", time.monotonic() - t0)

        # RequestDownload: 34 00 44 <addr:4> <len:4>
        req = bytes([0x34, 0x00, 0x44]) + addr.to_bytes(4, "big") + length.to_bytes(4, "big")
        r = self.request(req, expect_sid=0x74)
        logger.info("RequestDownload accepted -> %s", r.hex())

        # TransferData loop
        t0 = time.monotonic()
        blocks = 0
        offset = 0
        bsc = 1
        last_log = t0
        while offset < length:
            chunk = data[offset:offset + BLOCK_DATA_LEN]
            self.request(bytes([0x36, bsc & 0xFF]) + chunk, expect_sid=0x76)
            offset += len(chunk)
            blocks += 1
            self.total_blocks += 1
            bsc = (bsc + 1) & 0xFF
            if self.block_delay_s:
                time.sleep(self.block_delay_s)
            now = time.monotonic()
            if now - last_log >= 2.0:
                last_log = now
                rate = blocks / (now - t0) if now > t0 else 0
                logger.info("  ... %d blocks, %d/%d bytes (%.1f blk/s)",
                            blocks, offset, length, rate)
            if self.max_blocks and blocks >= self.max_blocks:
                logger.info("  (stopping segment early at --max-blocks=%d)", self.max_blocks)
                break
        dt = time.monotonic() - t0
        rate = blocks / dt if dt > 0 else 0
        logger.info("transfer done: %d blocks, %d bytes in %.1fs (%.1f blk/s, %.1f KiB/s)",
                    blocks, offset, dt, rate, (offset / 1024.0) / dt if dt > 0 else 0)

        # TransferExit
        self.request(bytes([0x37]), expect_sid=0x77)
        logger.info("TransferExit ok")

        # verify routine (0xFF01)
        logger.info("verify routine (0xFF01) ...")
        r = self.request(bytes([0x31, 0x01, 0xFF, 0x01]), expect_sid=0x71)
        logger.info("verify complete -> %s", r.hex())

    def run(self, segments):
        t0 = time.monotonic()
        self.preamble()
        self.security_unlock(self.security_level)
        for name in segments:
            self.flash_segment(name)
        # return to default session, as the real Omitec does
        self.request(bytes([0x10, 0x01]))
        dt = time.monotonic() - t0
        logger.info("=== FLASH COMPLETE: %d segment(s), %d blocks, %.1fs total ===",
                    len(segments), self.total_blocks, dt)


def build_argparser():
    p = argparse.ArgumentParser(
        description="Omitec reflash simulator (tester side) for the Coda DLCM.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_bus_args(p)
    p.add_argument("--request-id", type=lambda s: int(s, 0), default=uds.DEFAULT_REQUEST_ID,
                   help="arbitration ID we send on")
    p.add_argument("--response-id", type=lambda s: int(s, 0), default=uds.DEFAULT_RESPONSE_ID,
                   help="arbitration ID the ECU responds on (we receive)")
    p.add_argument("--segments", default="prog,cal",
                   help="comma list of segments to flash, in order (prog,cal)")
    p.add_argument("--patch", action="append", type=parse_patch_arg, default=None,
                   metavar="ADDR=BB,BB",
                   help="flash-address byte patch, repeatable (e.g. 0xA0021532=05,00)")
    p.add_argument("--preset", choices=sorted(DLCM_PATCH_PRESETS),
                   help="apply a named DLCM patch preset (composes with --patch)")
    p.add_argument("--security-level", type=lambda v: int(v, 0), default=0x01,
                   help="SecurityAccess requestSeed subfunction (default 0x01, the "
                        "programming-session level; 0x03 is the extended-session "
                        "'backdoor' level)")
    add_busload_args(p)
    p.add_argument("--block-delay-ms", type=float, default=0.0,
                   help="idle time between TransferData blocks (0=as fast as the ECU allows; "
                        "~217 reproduces the real Omitec's slow pacing)")
    p.add_argument("--target-image", default=None,
                   help="CAL image to make the car match. The patch set is "
                        "derived as the diff from the stock base to this file, "
                        "so it carries every accepted change by construction "
                        "and cannot silently omit an earlier one. Preferred "
                        "over a hand-maintained cumulative --preset once more "
                        "than one change has been accepted.")
    p.add_argument("--tx-stmin-ms", type=float, default=0.0,
                   help="minimum gap between consecutive frames WE transmit, in "
                        "ms (default 0 = honour the ECU's STmin, which the DLCM "
                        "reports as 0, giving ~37 back-to-back frames per "
                        "TransferData block). --block-delay-ms paces the gap "
                        "BETWEEN blocks and cannot soften the burst inside one. "
                        "Use ~1.1 to reproduce the real Omitec's frame spacing "
                        "when flashing through the GWM gateway.")
    p.add_argument("--max-blocks", type=int, default=0,
                   help="cap blocks per segment (0=whole binary; small value = quick smoke test)")
    p.add_argument("--startup-delay", type=float, default=1.0,
                   help="seconds to wait before starting (let the gateway sim come up)")
    p.add_argument("--ignition-poll-interval", type=float, default=3.0,
                   help="seconds between ignition/keepalive polls on 0x710 (0=disable)")
    p.add_argument("--hold-after-flash", type=float, default=0.0,
                   help="after the flash, keep polling ignition for N seconds to observe "
                        "the ECU's post-flash power-cycle finalization")
    p.add_argument("--debug", action="store_true", help="debug logging")
    return p


def main():
    args = build_argparser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] om: %(message)s",
        datefmt="%H:%M:%S",
    )
    segments = [s.strip() for s in args.segments.split(",") if s.strip()]
    for s in segments:
        if s not in SEGMENTS:
            raise SystemExit("unknown segment '%s' (choose from %s)"
                             % (s, ", ".join(SEGMENTS)))

    patches = []
    if args.target_image:
        patches.extend(patches_from_target(args.target_image))
        logger.info("target image '%s': %d patch run(s), %d byte(s) differ from "
                    "the stock base", Path(args.target_image).name, len(patches),
                    sum(len(b) for _a, b in patches))
    if args.preset:
        patches.extend(DLCM_PATCH_PRESETS[args.preset])
        logger.info("preset '%s': %d patch(es)", args.preset, len(DLCM_PATCH_PRESETS[args.preset]))
    if args.patch:
        patches.extend(args.patch)

    bus = open_bus(args, receive_own_messages=False, logger=logger)
    gov = governor_from_args(args, bitrate=args.bitrate)
    logger.info("%s", gov.describe())
    endpoint = IsoTpEndpoint(bus, tx_id=args.request_id, rx_id=args.response_id,
                             padding=0xAA, logger=logger, governor=gov,
                             tx_stmin_floor=args.tx_stmin_ms / 1000.0)
    if args.tx_stmin_ms > 0:
        logger.info("inter-frame floor %.2f ms (DLCM asks for STmin=0; the real "
                    "Omitec spaced frames ~1.1 ms)", args.tx_stmin_ms)
    sim = OmitecSim(endpoint, patches=(patches or None), block_delay_ms=args.block_delay_ms,
                    max_blocks=args.max_blocks, security_level=args.security_level)
    sim.governor = gov
    if args.startup_delay > 0:
        logger.info("waiting %.1fs for gateway sim...", args.startup_delay)
        time.sleep(args.startup_delay)

    poller = None
    poll_bus = None
    if args.ignition_poll_interval > 0:
        poll_bus = open_bus(args, receive_own_messages=False)
        poller = IgnitionPoller(poll_bus, interval=args.ignition_poll_interval)
        poller.start()
        logger.info("ignition poller started (every %.1fs on 0x%03X)",
                    args.ignition_poll_interval, IGNITION_REQ_ID)

    try:
        sim.run(segments)
        if args.hold_after_flash > 0 and poller is not None:
            logger.info("holding %.0fs to observe post-flash ignition finalization...",
                        args.hold_after_flash)
            time.sleep(args.hold_after_flash)
            logger.info("finalization observed ignition states: %s",
                        " -> ".join("0x%02X" % s for s in poller.state_history) or "none")
    except SafetyAbort as e:
        logger.error("SAFETY ABORT (ECU untouched): %s", e)
        sys.exit(2)
    except (IsoTpError, UdsRejected) as e:
        logger.error("flash aborted: %s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("interrupted (blocks=%d)", sim.total_blocks)
    finally:
        if poller is not None:
            poller.stop()
            logger.info("ignition polls sent=%d, responses=%d, last state=%s",
                        poller.polls, poller.responses,
                        ("0x%02X" % poller.last_state) if poller.last_state is not None else "none")
        for b in (bus, poll_bus):
            if b is not None:
                try:
                    b.shutdown()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
