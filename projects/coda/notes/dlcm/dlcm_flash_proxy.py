#!/usr/bin/env python3
"""DLCM flash man-in-the-middle proxy.

Sits between the Omitec scanner and the Coda Diagnostic CAN gateway,
forwarding all CAN frames bidirectionally. During a UDS RequestDownload
session whose target address range covers any of the configured patch
addresses, modifies specific bytes of the TransferData stream so the
DLCM ends up flashing the patched values.

Default patches target the V-curve lash minimum at runtime addresses
0x80021532 and 0x80021B6E (= flash-side 0xA0021532 / 0xA0021B6E),
flipping bytes 01 00 -> 05 00 (LE i16 from 1 to 5).

Usage:
    py -3.12 dlcm_flash_proxy.py --omitec-brand kvaser --gateway-brand ixxat
    py -3.12 dlcm_flash_proxy.py --omitec-brand kvaser --gateway-brand ixxat --dry-run
    py -3.12 dlcm_flash_proxy.py --omitec-brand kvaser --gateway-brand ixxat \\
        --patch 0xA0021532=05,00 --patch 0xA0021B6E=05,00

Brands are matched against canbench.live.receiver.detect_all_can_interfaces:
    ixxat, kvaser, pcan, socketcan
"""

import argparse
import logging
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import can

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from canbench.live.receiver import detect_all_can_interfaces


logger = logging.getLogger("dlcm_flash_proxy")


# Named DLCM CAL patch presets. Each raises entries of the near-zero gradient-
# limiter V-curve (rate-limit-vs-torque); stock curve idx0-9 = [62,35,15,10,10,
# 1,20,40,70,70] in two copies at flash 0xA0021528 (A) and 0xA0021B64 (B).
# Supporting evidence: notes/dlcm/dlcm-torque-limiter-code-trace.md.
#   vcurve-lash-5   : idx5 (the lash minimum) 1 -> 5 on both copies (the original
#                     real-car flash, 2026-07-21; near-zero rate cap raised a little).
#   vcurve-floor-20 : idx2..idx5 -> 20 on both copies, so the true curve minimum
#                     (the floor) becomes 20. idx2(15)/idx3(10)/idx4(10)/idx5(1)
#                     are all raised because setting only idx5 would leave the
#                     neighbors below 20 and the effective floor at 10.
#                     Result curve: [62,35,20,20,20,20,20,40,70,70].
PATCH_PRESETS = {
    "vcurve-lash-5": [
        (0xA0021532, bytes([0x05, 0x00])),
        (0xA0021B6E, bytes([0x05, 0x00])),
    ],
    "vcurve-floor-20": [
        (0xA002152C, bytes([0x14, 0x00])),  # copy A idx2  15 -> 20
        (0xA002152E, bytes([0x14, 0x00])),  # copy A idx3  10 -> 20
        (0xA0021530, bytes([0x14, 0x00])),  # copy A idx4  10 -> 20
        (0xA0021532, bytes([0x14, 0x00])),  # copy A idx5   1 -> 20
        (0xA0021B68, bytes([0x14, 0x00])),  # copy B idx2  15 -> 20
        (0xA0021B6A, bytes([0x14, 0x00])),  # copy B idx3  10 -> 20
        (0xA0021B6C, bytes([0x14, 0x00])),  # copy B idx4  10 -> 20
        (0xA0021B6E, bytes([0x14, 0x00])),  # copy B idx5   1 -> 20
    ],
}

DEFAULT_PATCHES = PATCH_PRESETS["vcurve-lash-5"]

DEFAULT_OMITEC_REQUEST_ID = 0x7E0


def parse_patch_arg(s):
    """Parse 'ADDR=BB,BB[,BB...]' patch spec; ADDR is hex, bytes are hex."""
    if "=" not in s:
        raise argparse.ArgumentTypeError(f"invalid patch spec '{s}', expected ADDR=BB,BB")
    addr_s, bytes_s = s.split("=", 1)
    addr = int(addr_s, 16)
    parts = [p.strip() for p in bytes_s.replace(" ", ",").split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError(f"invalid patch spec '{s}', no bytes given")
    new_bytes = bytes(int(p, 16) for p in parts)
    return (addr, new_bytes)


class FlashSession:
    """ISO-TP-aware modifier for the Omitec -> Gateway request stream.

    Tracks UDS RequestDownload (0x34) and TransferData (0x36) on a single
    arbitration ID. When the active download covers any patch address,
    modifies the corresponding bytes of the in-flight TransferData CAN
    frames before they get forwarded to the Gateway/DLCM.
    """

    def __init__(self, patches, request_id=DEFAULT_OMITEC_REQUEST_ID, dry_run=False):
        self.patches = patches
        self.req_id = request_id
        self.dry_run = dry_run
        self._lock = threading.Lock()

        self.dl_active = False
        self.dl_start_addr = None
        self.dl_total_length = None
        self.block_count = 0

        self.msg_total_len = 0
        self.msg_buf = bytearray()
        self.msg_cf_index = 0
        self.msg_is_xferdata = False
        self.msg_block_seq = None
        self.msg_block_addr = None
        self.msg_block_data_len = 0
        self.msg_pending_request_download = False

        self.applied_patches = 0
        self.would_apply_patches = 0
        self.blocks_seen = 0
        self.dl_sessions_active = 0
        self.dl_sessions_total = 0

    def process(self, msg):
        """Possibly mutate msg.data; always return msg for forwarding."""
        if msg.arbitration_id != self.req_id or msg.is_extended_id or not msg.data:
            return msg
        d = bytearray(msg.data)
        n = d[0] >> 4
        modified = False
        with self._lock:
            if n == 0x1:
                modified = self._handle_ff(d)
            elif n == 0x2:
                modified = self._handle_cf(d)
        if modified and not self.dry_run:
            msg.data = bytes(d)
        return msg

    def _handle_ff(self, d):
        total_len = ((d[0] & 0x0F) << 8) | d[1]
        self.msg_total_len = total_len
        self.msg_buf = bytearray(d[2:8])
        self.msg_cf_index = 0
        self.msg_is_xferdata = False
        self.msg_block_seq = None
        self.msg_block_addr = None
        self.msg_block_data_len = 0
        self.msg_pending_request_download = False

        if total_len < 1:
            return False
        svc = d[2]
        if svc == 0x34:
            self.msg_pending_request_download = True
            if len(self.msg_buf) >= total_len:
                self._handle_request_download(self.msg_buf[:total_len])
                self.msg_pending_request_download = False
            return False
        if svc == 0x36 and total_len >= 2 and self.dl_active:
            block_seq = d[3]
            self.block_count += 1
            self.blocks_seen += 1
            self.msg_is_xferdata = True
            self.msg_block_seq = block_seq
            block_idx = self.block_count - 1
            self.msg_block_data_len = total_len - 2
            self.msg_block_addr = self.dl_start_addr + block_idx * 252
            return self._maybe_patch_ff(d)
        return False

    def _handle_cf(self, d):
        self.msg_cf_index += 1
        cf_payload = d[1:8]
        room = self.msg_total_len - len(self.msg_buf)
        take = min(len(cf_payload), max(0, room))
        if take > 0:
            self.msg_buf.extend(cf_payload[:take])

        if (self.msg_pending_request_download
                and len(self.msg_buf) >= self.msg_total_len):
            self._handle_request_download(self.msg_buf[:self.msg_total_len])
            self.msg_pending_request_download = False
            return False

        if self.msg_is_xferdata and self.dl_active:
            return self._maybe_patch_cf(d)
        return False

    def _maybe_patch_ff(self, d):
        modified = False
        block_data_len = self.msg_block_data_len
        for patch_addr, patch_bytes in self.patches:
            for i, b in enumerate(patch_bytes):
                tgt = patch_addr + i
                offset = tgt - self.msg_block_addr
                if 0 <= offset < min(4, block_data_len):
                    can_pos = 4 + offset
                    self._record_patch(d, can_pos, b, location=f"FF d[{can_pos}]",
                                       block_seq=self.msg_block_seq, flash_addr=tgt)
                    modified = True
        return modified

    def _maybe_patch_cf(self, d):
        modified = False
        block_data_len = self.msg_block_data_len
        cf_idx = self.msg_cf_index
        cf_block_offset_start = 4 + (cf_idx - 1) * 7
        cf_block_offset_end = cf_block_offset_start + 7
        for patch_addr, patch_bytes in self.patches:
            for i, b in enumerate(patch_bytes):
                tgt = patch_addr + i
                offset = tgt - self.msg_block_addr
                if cf_block_offset_start <= offset < min(cf_block_offset_end, block_data_len):
                    can_pos = 1 + (offset - cf_block_offset_start)
                    self._record_patch(d, can_pos, b,
                                       location=f"CF#{cf_idx} d[{can_pos}]",
                                       block_seq=self.msg_block_seq, flash_addr=tgt)
                    modified = True
        return modified

    def _record_patch(self, d, can_pos, value, location, block_seq, flash_addr):
        old = d[can_pos]
        if self.dry_run:
            self.would_apply_patches += 1
            logger.info(
                "DRY-RUN PATCH block_seq=0x%02X flash=0x%08X %s old=0x%02X new=0x%02X",
                block_seq, flash_addr, location, old, value,
            )
            return
        d[can_pos] = value
        self.applied_patches += 1
        logger.info(
            "PATCH block_seq=0x%02X flash=0x%08X %s old=0x%02X new=0x%02X",
            block_seq, flash_addr, location, old, value,
        )

    def _handle_request_download(self, payload):
        if len(payload) < 4:
            return
        alfid = payload[2]
        addr_len = alfid & 0x0F
        len_len = (alfid >> 4) & 0x0F
        need = 3 + addr_len + len_len
        if len(payload) < need:
            return
        addr = int.from_bytes(payload[3:3 + addr_len], "big")
        length = int.from_bytes(payload[3 + addr_len:3 + addr_len + len_len], "big")
        self.dl_start_addr = addr
        self.dl_total_length = length
        self.block_count = 0
        end_addr = addr + length
        covers = any(addr <= pa < end_addr for pa, _ in self.patches)
        self.dl_active = covers
        self.dl_sessions_total += 1
        if covers:
            self.dl_sessions_active += 1
            logger.info(
                "RequestDownload covers patch region: addr=0x%08X len=0x%X end=0x%08X",
                addr, length, end_addr,
            )
        else:
            logger.info(
                "RequestDownload outside patch region: addr=0x%08X len=0x%X",
                addr, length,
            )


class EchoSuppressor:
    """Drop a bus's own transmitted frames when the transport loops them back.

    python-can's udp_multicast backend does NOT honor receive_own_messages: a
    socket always receives its own sends (multicast loopback). A transparent
    bidirectional bridge over such a transport would loop forever -- every frame
    the proxy emits on a segment echoes back on the same socket and gets
    re-forwarded to the other segment, which echoes, and so on (a broadcast
    storm; the ECU even sees its own responses come back). This suppresses that.

    Each frame the proxy sends onto a segment is recorded; when the reader for
    that same segment sees a byte-identical frame within a short window, it is
    our own echo and is dropped instead of forwarded. This is safe because the
    proxy only ever emits onto a segment frames that ORIGINATED on the other
    segment, so a recorded signature never collides with a genuine frame from
    the endpoint on this segment (request vs response IDs are disjoint by
    direction). Real dongles honor receive_own_messages, so this never engages
    there -- it is created only for the virtual transport.
    """

    def __init__(self, window_s=0.5):
        self.window_s = window_s
        self._lock = threading.Lock()
        self._sent = {}  # segment name -> deque[(signature, monotonic_ts)]
        self.suppressed = 0

    @staticmethod
    def _sig(msg):
        return (msg.arbitration_id, bytes(msg.data), bool(msg.is_extended_id))

    def note_tx(self, segment, msg):
        with self._lock:
            dq = self._sent.setdefault(segment, deque())
            dq.append((self._sig(msg), time.monotonic()))

    def is_echo(self, segment, msg):
        """True (and consumes the record) if msg is our own loopback on segment."""
        sig = self._sig(msg)
        now = time.monotonic()
        with self._lock:
            dq = self._sent.get(segment)
            if not dq:
                return False
            while dq and now - dq[0][1] > self.window_s:
                dq.popleft()
            for i, (s, _) in enumerate(dq):
                if s == sig:
                    del dq[i]
                    self.suppressed += 1
                    return True
        return False


def find_interface_for_brand(interfaces, brand):
    """Pick the first detected interface matching the requested brand."""
    matches = [iface for iface in interfaces if iface[0] == brand]
    if not matches:
        return None
    return matches[0]


def open_virtual_bus(channel, port):
    """Open a localhost udp_multicast bus (no hardware).

    Used to verify the proxy sim-to-sim: the omitec_sim and gateway_sim each
    live on a SEPARATE virtual segment (distinct multicast group/port), and the
    proxy bridges the two. Same code path as a real run -- only the two buses
    are virtual. receive_own_messages=False so a forwarded frame is never looped
    straight back into the segment it came from.
    """
    return can.interface.Bus(
        interface="udp_multicast",
        channel=channel,
        port=port,
        receive_own_messages=False,
    )


def open_bus(iface_tuple, bitrate):
    iface, ch, desc = iface_tuple
    kwargs = dict(bitrate=bitrate)
    # PCAN bus-off insurance for the ~46-min proxy session (see
    # can-tools canbench/live/pcan-busoff-recovery.md): a transient bus-off would silently
    # kill one direction of the bridge and the CAL patch would never land. The
    # patch window is only the final ~100 s, so a mid-session drop is costly.
    if iface == "pcan":
        kwargs["auto_reset"] = True
    if isinstance(ch, dict):
        bus = can.interface.Bus(interface=iface, **kwargs, **ch)
    else:
        bus = can.interface.Bus(interface=iface, channel=ch, **kwargs)
    if iface == "pcan":
        try:
            bus.reset()  # flush TX/RX queues + clear any post-error state at startup
        except Exception as e:
            logger.debug("pcan reset() at startup failed (non-fatal): %s", e)
    return bus


def forward_loop(name, src_bus, dst_bus, abort, session, stats,
                 echo=None, src_seg=None, dst_seg=None):
    """Receive on src_bus, optionally modify, send on dst_bus.

    When `echo` is set (virtual transport), frames the proxy itself transmitted
    onto src_seg are loopback echoes and are dropped rather than re-forwarded.
    """
    last_log = time.time()
    while not abort.is_set():
        try:
            msg = src_bus.recv(timeout=0.1)
        except Exception as e:
            logger.error("[%s] recv error: %s", name, e)
            time.sleep(0.1)
            continue
        if msg is None:
            now = time.time()
            if now - last_log > 5.0:
                logger.debug("[%s] idle (rx=%d tx=%d)",
                             name, stats["rx"], stats["tx"])
                last_log = now
            continue
        if echo is not None and echo.is_echo(src_seg, msg):
            stats["echo"] += 1
            continue
        stats["rx"] += 1
        if session is not None:
            try:
                msg = session.process(msg)
            except Exception as e:
                logger.error("[%s] session.process error: %s", name, e)
        try:
            tx_msg = can.Message(
                arbitration_id=msg.arbitration_id,
                data=msg.data,
                is_extended_id=msg.is_extended_id,
                is_remote_frame=msg.is_remote_frame,
                dlc=msg.dlc,
            )
            if echo is not None:
                echo.note_tx(dst_seg, tx_msg)
            dst_bus.send(tx_msg)
            stats["tx"] += 1
        except Exception as e:
            logger.error("[%s] send error on 0x%X: %s",
                         name, msg.arbitration_id, e)


def stats_printer(abort, omitec_to_gw_stats, gw_to_omitec_stats, session, interval=5.0):
    last_print = time.time()
    while not abort.is_set():
        time.sleep(0.5)
        now = time.time()
        if now - last_print < interval:
            continue
        last_print = now
        s_o2g = omitec_to_gw_stats
        s_g2o = gw_to_omitec_stats
        with session._lock:
            dl_active = session.dl_active
            dl_addr = session.dl_start_addr
            dl_len = session.dl_total_length
            blocks = session.blocks_seen
            applied = session.applied_patches
            would = session.would_apply_patches
            sessions_total = session.dl_sessions_total
            sessions_match = session.dl_sessions_active
        dl_state = "idle"
        if dl_addr is not None:
            dl_state = (f"addr=0x{dl_addr:08X} len=0x{dl_len:X} "
                        f"{'(patch-target)' if dl_active else '(other-region)'}")
        logger.info(
            "STATS  O->G rx=%d tx=%d  G->O rx=%d tx=%d  echo=%d  "
            "downloads=%d (matching=%d) blocks=%d applied=%d dryrun=%d  dl=%s",
            s_o2g["rx"], s_o2g["tx"], s_g2o["rx"], s_g2o["tx"],
            s_o2g["echo"] + s_g2o["echo"],
            sessions_total, sessions_match, blocks, applied, would, dl_state,
        )


def build_argparser():
    p = argparse.ArgumentParser(
        description="DLCM flash MITM: forward Omitec<->Gateway, patch CAL bytes in flight.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--transport", choices=["real", "virtual"], default="real",
                   help="'real' = two physical dongles (brands below); "
                        "'virtual' = two localhost udp_multicast segments, for "
                        "sim-to-sim verification with no hardware")
    p.add_argument("--omitec-brand",
                   choices=["ixxat", "kvaser", "pcan", "socketcan"],
                   help="dongle brand cabled to the Omitec scanner (real transport)")
    p.add_argument("--gateway-brand",
                   choices=["ixxat", "kvaser", "pcan", "socketcan"],
                   help="dongle brand cabled to the vehicle Gateway (real transport)")
    # The two virtual segments MUST be on different multicast GROUPS, not just
    # different ports: python-can's udp_multicast delivers by group membership,
    # and (at least on Windows) two sockets on the same group but different ports
    # still hear each other -- which turns the bridge into a frame-storm loop
    # (gateway sees its own responses echoed back). Different groups are
    # IGMP-isolated and break the loop cleanly.
    p.add_argument("--omitec-channel", default="239.0.0.1",
                   help="virtual transport: Omitec-segment multicast group IP")
    p.add_argument("--omitec-port", type=int, default=43113,
                   help="virtual transport: Omitec-segment UDP port")
    p.add_argument("--gateway-channel", default="239.0.0.2",
                   help="virtual transport: Gateway-segment multicast group IP "
                        "(MUST differ from --omitec-channel)")
    p.add_argument("--gateway-port", type=int, default=43113,
                   help="virtual transport: Gateway-segment UDP port")
    p.add_argument("--bitrate", "-b", type=int, default=500000,
                   help="CAN bitrate (bps); real transport only")
    p.add_argument("--request-id", type=lambda s: int(s, 0),
                   default=DEFAULT_OMITEC_REQUEST_ID,
                   help="Omitec request arbitration ID (UDS tester)")
    p.add_argument("--preset", choices=sorted(PATCH_PRESETS), default=None,
                   help="apply a named CAL patch preset (composes with --patch). "
                        "Presets: %s" % ", ".join(sorted(PATCH_PRESETS)))
    p.add_argument("--patch", action="append", type=parse_patch_arg, default=None,
                   metavar="ADDR=BB,BB",
                   help="patch spec (repeatable), composes with --preset. If "
                        "neither --preset nor --patch is given, defaults to the "
                        "vcurve-lash-5 preset.")
    p.add_argument("--dry-run", action="store_true",
                   help="forward unmodified; only LOG which bytes would be patched")
    p.add_argument("--debug", action="store_true",
                   help="enable debug-level logging")
    return p


def main():
    args = build_argparser().parse_args()
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    patches = []
    if args.preset:
        patches.extend(PATCH_PRESETS[args.preset])
        logger.info("preset '%s': %d patch(es)", args.preset, len(PATCH_PRESETS[args.preset]))
    if args.patch:
        patches.extend(args.patch)
    if not patches:
        patches = DEFAULT_PATCHES
        logger.info("no --preset/--patch given; using default preset vcurve-lash-5")
    logger.info("Patches:")
    for addr, bs in patches:
        logger.info("  0x%08X = %s", addr, " ".join(f"{b:02X}" for b in bs))

    if args.transport == "virtual":
        if (args.omitec_channel, args.omitec_port) == (args.gateway_channel, args.gateway_port):
            logger.error("virtual transport: Omitec and Gateway segments must differ "
                         "(same group AND port = one shared bus, nothing to proxy). "
                         "Give them different --omitec-channel/--gateway-channel or "
                         "different --omitec-port/--gateway-port.")
            sys.exit(2)
        logger.info("Virtual transport (sim-to-sim, no hardware):")
        logger.info("  Omitec  segment: udp_multicast %s:%d",
                    args.omitec_channel, args.omitec_port)
        logger.info("  Gateway segment: udp_multicast %s:%d",
                    args.gateway_channel, args.gateway_port)
        omitec_bus = open_virtual_bus(args.omitec_channel, args.omitec_port)
        gateway_bus = open_virtual_bus(args.gateway_channel, args.gateway_port)
    else:
        if not args.omitec_brand or not args.gateway_brand:
            logger.error("real transport requires --omitec-brand and --gateway-brand.")
            sys.exit(2)
        if args.omitec_brand == args.gateway_brand:
            logger.error("Omitec brand and Gateway brand must differ "
                         "(this script picks the first detected dongle of each brand).")
            sys.exit(2)

        logger.info("Detecting CAN interfaces at %d bps...", args.bitrate)
        interfaces = detect_all_can_interfaces(
            args.bitrate,
            brands={args.omitec_brand, args.gateway_brand},
        )
        if not interfaces:
            logger.error("No CAN interfaces detected. Is the dongle plugged in and driver installed?")
            sys.exit(1)
        logger.info("Detected %d interface(s):", len(interfaces))
        for iface in interfaces:
            logger.info("  %s  (channel_spec=%r)", iface[2], iface[1])

        omitec_iface = find_interface_for_brand(interfaces, args.omitec_brand)
        gateway_iface = find_interface_for_brand(interfaces, args.gateway_brand)
        if omitec_iface is None:
            logger.error("No %s dongle detected for Omitec side.", args.omitec_brand)
            sys.exit(1)
        if gateway_iface is None:
            logger.error("No %s dongle detected for Gateway side.", args.gateway_brand)
            sys.exit(1)

        logger.info("Omitec  side: %s", omitec_iface[2])
        logger.info("Gateway side: %s", gateway_iface[2])

        omitec_bus = open_bus(omitec_iface, args.bitrate)
        gateway_bus = open_bus(gateway_iface, args.bitrate)

    session = FlashSession(
        patches=patches,
        request_id=args.request_id,
        dry_run=args.dry_run,
    )

    abort = threading.Event()
    o2g_stats = {"rx": 0, "tx": 0, "echo": 0}
    g2o_stats = {"rx": 0, "tx": 0, "echo": 0}

    # The virtual (udp_multicast) transport loops a socket's own sends back to
    # it, which would turn this transparent bridge into a frame storm; suppress
    # those echoes. Real dongles honor receive_own_messages, so no suppressor is
    # needed (or wanted) there -- keeps the hardware path byte-for-byte as
    # validated.
    echo = EchoSuppressor() if args.transport == "virtual" else None

    t_o2g = threading.Thread(
        target=forward_loop,
        args=("O->G", omitec_bus, gateway_bus, abort, session, o2g_stats),
        kwargs=dict(echo=echo, src_seg="omitec", dst_seg="gateway"),
        daemon=True,
    )
    t_g2o = threading.Thread(
        target=forward_loop,
        args=("G->O", gateway_bus, omitec_bus, abort, None, g2o_stats),
        kwargs=dict(echo=echo, src_seg="gateway", dst_seg="omitec"),
        daemon=True,
    )
    t_stats = threading.Thread(
        target=stats_printer,
        args=(abort, o2g_stats, g2o_stats, session),
        daemon=True,
    )

    t_o2g.start()
    t_g2o.start()
    t_stats.start()

    mode = "DRY-RUN (no modification)" if args.dry_run else "LIVE (modifies CAL flash)"
    logger.info("=== Proxy running [%s] === Ctrl+C to stop", mode)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Shutdown requested...")
    finally:
        abort.set()
        t_o2g.join(timeout=2.0)
        t_g2o.join(timeout=2.0)
        t_stats.join(timeout=2.0)
        try:
            omitec_bus.shutdown()
        except Exception:
            pass
        try:
            gateway_bus.shutdown()
        except Exception:
            pass
        logger.info("Final: O->G rx=%d tx=%d  G->O rx=%d tx=%d  echo_suppressed=%d  "
                    "blocks=%d applied=%d dryrun=%d sessions_total=%d sessions_match=%d",
                    o2g_stats["rx"], o2g_stats["tx"],
                    g2o_stats["rx"], g2o_stats["tx"],
                    o2g_stats["echo"] + g2o_stats["echo"],
                    session.blocks_seen, session.applied_patches,
                    session.would_apply_patches,
                    session.dl_sessions_total, session.dl_sessions_active)


if __name__ == "__main__":
    main()
