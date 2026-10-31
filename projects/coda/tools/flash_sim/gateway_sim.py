#!/usr/bin/env python3
"""Coda Gateway/DLCM reflash simulator (the ECU side).

Pretends to be the vehicle Gateway/DLCM during a UDS reflash: reassembles the
tester's ISO-TP requests on 0x7E0, answers on 0x7E8 exactly as the real DLCM did
in coda_dlcm_flash6.log, and imposes the real ECU delays (fast ~8 ms block
accepts, slow multi-second erase/verify routines with 0x78 responsePending
frames). Run it against omitec_sim.py over the localhost virtual bus, or later
against a real Omitec through a dongle.

Usage:
    py -3.12 gateway_sim.py                     # virtual bus, realistic timing
    py -3.12 gateway_sim.py --time-scale 0.02   # compress delays for a smoke test
    py -3.12 gateway_sim.py --verify-bins       # check received data vs real bins
    py -3.12 gateway_sim.py --transport kvaser  # drive a real Omitec via a dongle

Responses and delays are grounded in the real capture; error/negative paths
(bad key, wrong block counter, out-of-range) are designed from the UDS spec and
were NOT observed in the passive capture.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uds
import timing as T
from bus import add_bus_args, open_bus
from isotp import IsoTpEndpoint, IsoTpError
from oob import OutOfBandResponder

# UDS services that carry a sub-function byte (bit 7 = suppressPositiveResponse).
SUBFUNCTION_SERVICES = {0x10, 0x11, 0x27, 0x28, 0x31, 0x3E, 0x85}

# RoutineControl responsePending cadence. UDS P2 requires the FIRST response to
# a request within ~100 ms; after a 0x78, subsequent responses within P2* (30 s
# here). So send the first 0x78 immediately, then keep them well under P2*.
ROUTINE_FIRST_PENDING_S = 0.02   # first 0x78 within P2 (real DLCM did ~9 ms)
ROUTINE_PENDING_PERIOD_S = 2.0   # subsequent 0x78 cadence, well under P2* = 30 s

# Post-flash ignition power-cycle the real Omitec drives during finalization
# (observed 2026-07-20): after the last segment verify it wants the ignition DID
# 0x6401 (read from the gateway module on 0x710/0x718, NOT the DLCM) cycled
# OFF -> ON -> OFF -> ON, then sends a final default-session request, then shows
# "re-flash complete". Nothing else is sent during finalization -- only ignition
# polls, which are identical whether it wants OFF or ON, so the gateway is blind
# to the current step and must play this as a timed sequence once flashing goes
# idle. Dwell is held longer than the Omitec's observed ~10 s per-step wait;
# over-holding only makes it wait (safe), under-holding makes it miss a step.
FINALIZATION_SEQUENCE = (0x00, 0x03, 0x00, 0x03)  # ends ON
FINALIZATION_GRACE_S = 5.0    # flash-idle time before the cycle starts
FINALIZATION_DWELL_S = 15.0   # hold each state (> the Omitec's ~10 s step wait)

logger = logging.getLogger("gateway_sim")

HERE = Path(__file__).resolve().parent
DLCM_DIR = HERE.parents[1] / "notes" / "dlcm"  # projects/coda/notes/dlcm

# Fixed seed the real DLCM returned. Returning the same seed means a real Omitec
# recomputes the same key it produced in the capture, which we then accept.
FIXED_SEED = bytes.fromhex("7c876e19")
EXPECTED_KEY = bytes.fromhex("2726966f")  # observed; informational only

# ReadDataByIdentifier values observed in the capture.
RDBI_VALUES = {
    0xF194: bytes.fromhex("35323730"),
    0xF1A1: bytes.fromhex("44303033"),
    0xF18B: bytes.fromhex("00000000"),
    0xF18C: bytes.fromhex("00000000"),
}

# Segments we can verify received data against (addr -> real bin file).
KNOWN_SEGMENTS = {
    0x80040000: DLCM_DIR / "coda_dlcm_prog.bin",
    0xA0020000: DLCM_DIR / "coda_dlcm_cal.bin",
}


class GatewaySim:
    def __init__(self, endpoint, time_scale=1.0, verify_bins=False, oob=None,
                 base_ignition=0x03, ignition_file=None, auto_finalize=True,
                 finalize_grace_s=FINALIZATION_GRACE_S,
                 finalize_dwell_s=FINALIZATION_DWELL_S, seed=FIXED_SEED):
        self.ep = endpoint
        self.time_scale = time_scale
        self.verify_bins = verify_bins
        self.oob = oob
        self.seed = seed

        # ignition finalization
        self.base_ignition = base_ignition & 0xFF
        self.ignition_file = ignition_file
        self.auto_finalize = auto_finalize
        self.finalize_grace_s = finalize_grace_s
        self.finalize_dwell_s = finalize_dwell_s
        self.last_flash_activity = None   # monotonic time of last DLCM send
        self.download_happened = False    # a real flash occurred (>=1 TransferExit)
        self._finalization_done = False
        self._last_final_val = None

        self.session = 0x01
        self.security_unlocked = False
        self.seed_issued = False

        # active download state
        self.dl_active = False
        self.dl_addr = None
        self.dl_len = None
        self.dl_expected_bsc = 1
        self.dl_buf = bytearray()
        self.dl_blocks = 0

        self.total_blocks = 0
        self._last_progress = 0.0
        self._suppress_positive = False

    # -- timing --------------------------------------------------------------

    def _sleep(self, seconds):
        s = seconds * self.time_scale
        if s > 0:
            time.sleep(s)

    def _send(self, payload):
        # suppressPositiveResponse: drop positive responses, still send negatives.
        if self._suppress_positive and payload and payload[0] != uds.NEGATIVE_RESPONSE_SID:
            return
        # Any DLCM send counts as flash activity (incl. routine pendings and
        # TransferData responses), so a long erase never looks idle and the
        # finalization ignition cycle only starts once real flashing has stopped.
        self.last_flash_activity = time.monotonic()
        self.ep.send_uds(payload)

    def current_ignition(self):
        """Ignition DID 0x6401 value for the out-of-band poll responder.

        Base state (ON) through pre-flash and flashing; once flashing has been
        idle for the grace period, play the observed post-flash power-cycle
        (OFF -> ON -> OFF -> ON), then latch ON. A populated --ignition-file
        overrides everything (manual control for debugging/recovery).
        """
        if self._finalization_done:
            return 0x03
        fv = self._read_ignition_file()
        if fv is not None:
            return fv
        if (not self.auto_finalize or not self.download_happened
                or self.last_flash_activity is None):
            return self.base_ignition
        idle = time.monotonic() - self.last_flash_activity
        if idle < self.finalize_grace_s:
            return self.base_ignition
        idx = int((idle - self.finalize_grace_s) / self.finalize_dwell_s)
        seq = FINALIZATION_SEQUENCE
        if idx >= len(seq):
            self._finalization_done = True
            logger.info("post-flash ignition finalization complete -> latched ON")
            return 0x03
        val = seq[idx]
        if val != self._last_final_val:
            logger.info("finalization ignition step %d/%d -> 0x%02X (hold ~%.0fs each)",
                        idx + 1, len(seq), val, self.finalize_dwell_s)
            self._last_final_val = val
        return val

    def _read_ignition_file(self):
        if not self.ignition_file:
            return None
        try:
            with open(self.ignition_file) as f:
                txt = f.read().strip()
        except OSError:
            return None
        if not txt:
            return None
        try:
            return int(txt, 0) & 0xFF
        except ValueError:
            return None

    # -- main loop -----------------------------------------------------------

    def run(self):
        oob_note = ""
        if self.oob is not None:
            oob_note = ", ignition=0x%02X, out-of-band polls answered" % self.oob.ignition_state
        logger.info("Gateway/DLCM simulator ready (rx=0x%03X tx=0x%03X, time_scale=%.3g%s)",
                    self.ep.rx_id, self.ep.tx_id, self.time_scale, oob_note)
        while True:
            try:
                req = self.ep.recv_uds(timeout=None)
            except IsoTpError as e:
                logger.warning("ISO-TP error: %s", e)
                continue
            if req is None:
                continue
            try:
                self.dispatch(req)
            except Exception as e:  # keep the ECU alive on unexpected input
                logger.exception("dispatch error on %s: %s", req[:8].hex(), e)

    def dispatch(self, req):
        sid = req[0]
        # sub-function services: honor the suppressPositiveResponse bit and strip
        # it before interpreting the sub-function.
        self._suppress_positive = False
        if sid in SUBFUNCTION_SERVICES and len(req) > 1 and (req[1] & 0x80):
            self._suppress_positive = True
            req = bytes([sid, req[1] & 0x7F]) + req[2:]
        if sid == uds.SVC_DIAGNOSTIC_SESSION_CONTROL:
            self._diag_session(req)
        elif sid == uds.SVC_READ_DATA_BY_ID:
            self._read_data_by_id(req)
        elif sid == uds.SVC_SECURITY_ACCESS:
            self._security_access(req)
        elif sid == uds.SVC_ROUTINE_CONTROL:
            self._routine_control(req)
        elif sid == uds.SVC_REQUEST_DOWNLOAD:
            self._request_download(req)
        elif sid == uds.SVC_TRANSFER_DATA:
            self._transfer_data(req)
        elif sid == uds.SVC_REQUEST_TRANSFER_EXIT:
            self._transfer_exit(req)
        elif sid == uds.SVC_ECU_RESET:
            self._sleep(T.GENERIC_LATENCY_S)
            sub = req[1] if len(req) > 1 else 0x01
            logger.info("ECUReset sub=0x%02X", sub)
            self._send(bytes([uds.positive_response(sid), sub]))
        elif sid == uds.SVC_TESTER_PRESENT:
            sub = req[1] if len(req) > 1 else 0x00
            self._send(bytes([uds.positive_response(sid), sub]))
        elif sid == uds.SVC_COMMUNICATION_CONTROL:
            self._sleep(T.GENERIC_LATENCY_S)
            sub = req[1] if len(req) > 1 else 0x00
            self._send(bytes([uds.positive_response(sid), sub]))
        elif sid == uds.SVC_CONTROL_DTC_SETTING:
            self._sleep(T.GENERIC_LATENCY_S)
            sub = req[1] if len(req) > 1 else 0x00
            self._send(bytes([uds.positive_response(sid), sub]))
        else:
            logger.info("unsupported service 0x%02X -> NRC serviceNotSupported", sid)
            self._send(uds.negative_response(sid, uds.NRC_SERVICE_NOT_SUPPORTED))

    # -- services ------------------------------------------------------------

    def _diag_session(self, req):
        sub = req[1] if len(req) > 1 else 0x01
        self._sleep(T.DIAG_SESSION_LATENCY_S)
        self.session = sub
        if sub == 0x02:
            # A programming session means a new flash attempt is starting: disarm
            # any finalization left armed by a previous (possibly aborted) flash,
            # so a retry never trips over the ignition cycle mid-attempt.
            if self.download_happened or self._finalization_done:
                logger.info("programming session -> disarming previous flash finalization")
            self.download_happened = False
            self._finalization_done = False
            self._last_final_val = None
            params = bytes.fromhex("00640bb8")  # P2=100ms P2*=3000ms
        else:
            params = bytes.fromhex("00321388")  # P2=50ms  P2*=5000ms
        logger.info("DiagnosticSessionControl -> session 0x%02X", sub)
        self._send(bytes([uds.positive_response(req[0]), sub]) + params)

    def _read_data_by_id(self, req):
        if len(req) < 3:
            self._send(uds.negative_response(req[0], uds.NRC_INCORRECT_LENGTH))
            return
        did = (req[1] << 8) | req[2]
        self._sleep(T.GENERIC_LATENCY_S)
        val = RDBI_VALUES.get(did)
        if val is None:
            logger.info("ReadDataByIdentifier DID=0x%04X (unknown) -> requestOutOfRange", did)
            self._send(uds.negative_response(req[0], uds.NRC_REQUEST_OUT_OF_RANGE))
            return
        logger.info("ReadDataByIdentifier DID=0x%04X -> %s", did, val.hex())
        self._send(bytes([uds.positive_response(req[0]), req[1], req[2]]) + val)

    def _security_access(self, req):
        sub = req[1] if len(req) > 1 else 0x00
        self._sleep(T.SECURITY_ACCESS_LATENCY_S)
        if sub == 0x01:  # requestSeed
            self.seed_issued = True
            logger.info("SecurityAccess requestSeed -> seed=%s", self.seed.hex())
            self._send(bytes([uds.positive_response(req[0]), sub]) + self.seed)
        elif sub == 0x02:  # sendKey
            key = bytes(req[2:])
            self.security_unlocked = True
            match = "matches capture" if key == EXPECTED_KEY else "differs from capture"
            logger.info("SecurityAccess sendKey=%s (%s) -> access granted", key.hex(), match)
            self._send(bytes([uds.positive_response(req[0]), sub]))
        else:
            self._send(uds.negative_response(req[0], uds.NRC_SUBFUNCTION_NOT_SUPPORTED))

    def _routine_control(self, req):
        if len(req) < 4:
            self._send(uds.negative_response(req[0], uds.NRC_INCORRECT_LENGTH))
            return
        sub = req[1]
        routine = (req[2] << 8) | req[3]
        data = req[4:].hex()
        prof = T.ROUTINE_PROFILE.get((routine, data), T.ROUTINE_DEFAULT)
        walltime = prof["walltime_s"]
        resp_data = prof["response_data"]
        logger.info("RoutineControl start routine=0x%04X data=%s (walltime~%.1fs)",
                    routine, data or "-", walltime)

        # Send the first responsePending immediately (within P2), then keep
        # emitting 0x78 every ROUTINE_PENDING_PERIOD_S until the simulated
        # routine walltime elapses, then the positive response. A delayed first
        # pending makes the tester abort (this is what failed the first real run).
        deadline = time.monotonic() + walltime * self.time_scale
        self._sleep(ROUTINE_FIRST_PENDING_S)
        self._send(uds.negative_response(req[0], uds.NRC_RESPONSE_PENDING))
        pendings = 1
        next_pending = time.monotonic() + ROUTINE_PENDING_PERIOD_S
        while time.monotonic() < deadline:
            time.sleep(0.02)
            if time.monotonic() >= next_pending:
                self._send(uds.negative_response(req[0], uds.NRC_RESPONSE_PENDING))
                pendings += 1
                next_pending += ROUTINE_PENDING_PERIOD_S
        # final positive: 71 <sub> <routine+tail>
        self._send(bytes([uds.positive_response(req[0]), sub]) + resp_data)
        logger.info("RoutineControl routine=0x%04X complete (%d pending frames)",
                    routine, pendings)

    def _request_download(self, req):
        # 34 <dataFormatId> <ALFID> <addr...> <len...>
        if len(req) < 5:
            self._send(uds.negative_response(req[0], uds.NRC_INCORRECT_LENGTH))
            return
        alfid = req[2]
        addr_len = alfid & 0x0F
        len_len = (alfid >> 4) & 0x0F
        need = 3 + addr_len + len_len
        if len(req) < need:
            self._send(uds.negative_response(req[0], uds.NRC_INCORRECT_LENGTH))
            return
        addr = int.from_bytes(req[3:3 + addr_len], "big")
        length = int.from_bytes(req[3 + addr_len:3 + addr_len + len_len], "big")
        self._sleep(T.REQUEST_DOWNLOAD_LATENCY_S)

        self.dl_active = True
        self.dl_addr = addr
        self.dl_len = length
        self.dl_expected_bsc = 1
        self.dl_buf = bytearray()
        self.dl_blocks = 0
        self._last_progress = time.monotonic()
        logger.info("RequestDownload addr=0x%08X len=0x%X (%d) end=0x%08X",
                    addr, length, length, addr + length)
        # 74 <lengthFormatId=0x20> <maxNumberOfBlockLength=0x00FF>
        self._send(bytes([uds.positive_response(req[0]), 0x20, 0x00, 0xFF]))

    def _transfer_data(self, req):
        if not self.dl_active:
            self._send(uds.negative_response(req[0], uds.NRC_REQUEST_SEQUENCE_ERROR))
            return
        if len(req) < 2:
            self._send(uds.negative_response(req[0], uds.NRC_INCORRECT_LENGTH))
            return
        bsc = req[1]
        if bsc != (self.dl_expected_bsc & 0xFF):
            logger.warning("TransferData bad BSC: got 0x%02X expected 0x%02X",
                           bsc, self.dl_expected_bsc & 0xFF)
            self._send(uds.negative_response(req[0], uds.NRC_WRONG_BLOCK_SEQUENCE_COUNTER))
            return
        self.dl_buf.extend(req[2:])
        self.dl_blocks += 1
        self.total_blocks += 1
        self.dl_expected_bsc = (self.dl_expected_bsc + 1) & 0xFF
        self._sleep(T.TRANSFER_DATA_LATENCY_S)
        self._send(bytes([uds.positive_response(req[0]), bsc]))

        now = time.monotonic()
        if now - self._last_progress >= 2.0:
            self._last_progress = now
            logger.info("  ... download 0x%08X: %d blocks, %d bytes",
                        self.dl_addr, self.dl_blocks, len(self.dl_buf))

    def _transfer_exit(self, req):
        self._sleep(T.TRANSFER_EXIT_LATENCY_S)
        addr = self.dl_addr
        got = bytes(self.dl_buf)
        logger.info("RequestTransferExit: segment 0x%08X received %d blocks, %d bytes",
                    addr if addr is not None else 0, self.dl_blocks, len(got))
        if self.verify_bins and addr in KNOWN_SEGMENTS:
            self._verify_segment(addr, got)
        self.dl_active = False
        self.download_happened = True  # arms post-flash ignition finalization
        self._send(bytes([uds.positive_response(req[0])]))

    def _verify_segment(self, addr, got):
        path = KNOWN_SEGMENTS[addr]
        try:
            ref = path.read_bytes()
        except OSError as e:
            logger.warning("verify: cannot read %s: %s", path.name, e)
            return
        if got == ref:
            logger.info("VERIFY OK: segment 0x%08X byte-exact vs %s (%d bytes)",
                        addr, path.name, len(ref))
        else:
            n = min(len(got), len(ref))
            diffs = [i for i in range(n) if got[i] != ref[i]]
            logger.warning("VERIFY DIFF: segment 0x%08X vs %s: %d/%d differing "
                           "bytes, len delta=%d",
                           addr, path.name, len(diffs), n, len(got) - len(ref))
            # list each differing byte so an intentional patch can be confirmed
            # exact (ref->got at each flash address) and no other byte changed.
            for i in diffs[:32]:
                logger.warning("    flash 0x%08X: ref 0x%02X -> got 0x%02X",
                               addr + i, ref[i], got[i])
            if len(diffs) > 32:
                logger.warning("    ... and %d more differing bytes", len(diffs) - 32)


def build_argparser():
    p = argparse.ArgumentParser(
        description="Coda Gateway/DLCM reflash simulator (ECU side).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_bus_args(p)
    p.add_argument("--request-id", type=lambda s: int(s, 0), default=uds.DEFAULT_REQUEST_ID,
                   help="arbitration ID the tester sends on (we receive)")
    p.add_argument("--response-id", type=lambda s: int(s, 0), default=uds.DEFAULT_RESPONSE_ID,
                   help="arbitration ID we respond on")
    p.add_argument("--time-scale", type=float, default=1.0,
                   help="multiply all ECU delays (1.0=realistic; 0.02=fast smoke test)")
    p.add_argument("--verify-bins", action="store_true",
                   help="on TransferExit, verify received segment vs the real .bin files")
    p.add_argument("--ignition", type=lambda s: int(s, 0), default=0x03,
                   help="ignition state returned for DID 0x6401 poll (0x03=running, 0x00=off)")
    p.add_argument("--ignition-file", default=None,
                   help="path to a text file holding the ignition state, re-read each poll "
                        "so it can be changed live (write '0x00'/'0x03'); OVERRIDES the "
                        "auto finalization sequence -- for manual control/debugging")
    p.add_argument("--no-auto-finalize", action="store_true",
                   help="disable the automatic post-flash ignition power-cycle "
                        "(OFF->ON->OFF->ON) the Omitec expects after flashing")
    p.add_argument("--finalize-dwell", type=float, default=FINALIZATION_DWELL_S,
                   help="seconds to hold each ignition state during finalization")
    p.add_argument("--finalize-grace", type=float, default=FINALIZATION_GRACE_S,
                   help="flash-idle seconds before the finalization cycle starts")
    p.add_argument("--no-oob", action="store_true",
                   help="disable out-of-band responder (ignition/keepalive polls)")
    p.add_argument("--seed", type=lambda s: bytes.fromhex(s), default=FIXED_SEED,
                   help="security-access seed to return (hex); default is the captured seed")
    p.add_argument("--log-ignition-polls", action="store_true",
                   help="log every ignition poll (noisy); default only counts them")
    p.add_argument("--debug", action="store_true", help="debug logging")
    return p


def main():
    args = build_argparser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] gw: %(message)s",
        datefmt="%H:%M:%S",
    )
    bus = open_bus(args, receive_own_messages=False, logger=logger)
    oob = None
    if not args.no_oob:
        oob = OutOfBandResponder(bus, ignition_state=args.ignition,
                                 log_polls=args.log_ignition_polls, logger_=logger)
    endpoint = IsoTpEndpoint(bus, tx_id=args.response_id, rx_id=args.request_id,
                             padding=0xAA, logger=logger,
                             oob_handler=(oob.handle if oob else None))
    sim = GatewaySim(endpoint, time_scale=args.time_scale, verify_bins=args.verify_bins,
                     oob=oob, base_ignition=args.ignition, ignition_file=args.ignition_file,
                     auto_finalize=(not args.no_auto_finalize),
                     finalize_grace_s=args.finalize_grace,
                     finalize_dwell_s=args.finalize_dwell, seed=args.seed)
    # the gateway owns ignition logic (base state + post-flash finalization);
    # the OOB responder asks it for the value on each poll.
    if oob is not None:
        oob.ignition_provider = sim.current_ignition
    try:
        sim.run()
    except KeyboardInterrupt:
        polls = oob.ignition_polls if oob else 0
        logger.info("shutdown (blocks=%d, ignition polls answered=%d)",
                    sim.total_blocks, polls)
    finally:
        try:
            bus.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
