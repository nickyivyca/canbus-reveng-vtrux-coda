"""CAN bus factory for the flash simulators.

Two transport families:

  virtual : python-can 'udp_multicast' backend. Two processes on the same host
            join the same multicast group/port and see each other's frames
            (but not their own). No hardware, no admin rights. This is the
            localhost test bus used to run gateway_sim.py against omitec_sim.py.

  real    : a physical dongle brand (ixxat / kvaser / pcan / socketcan /
            gs_usb). The channel is auto-detected via canbench's
            detect_all_can_interfaces so the exact same simulator code can later
            drive real silicon.

Both simulators must agree on transport + channel/port to share a bus.
"""

import sys
from pathlib import Path

import can

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VIRTUAL_DEFAULT_CHANNEL = "239.0.0.1"
VIRTUAL_DEFAULT_PORT = 43113

REAL_BRANDS = ("ixxat", "kvaser", "pcan", "socketcan", "gs_usb")


def add_bus_args(parser):
    """Add the shared transport CLI options to an argparse parser."""
    parser.add_argument(
        "--transport", default="virtual",
        choices=("virtual",) + REAL_BRANDS,
        help="'virtual' = localhost udp_multicast (no hardware); "
             "otherwise a real dongle brand")
    parser.add_argument(
        "--channel", default=None,
        help="virtual: multicast group IP (default %s); "
             "real: dongle channel (default: first auto-detected)"
             % VIRTUAL_DEFAULT_CHANNEL)
    parser.add_argument(
        "--port", type=int, default=VIRTUAL_DEFAULT_PORT,
        help="virtual transport UDP port (default %d)" % VIRTUAL_DEFAULT_PORT)
    parser.add_argument(
        "--bitrate", "-b", type=int, default=500000,
        help="real transport CAN bitrate (bps); ignored for virtual")


def open_bus(args, *, receive_own_messages=False, logger=None):
    """Open a python-can Bus from parsed args (see add_bus_args)."""
    if args.transport == "virtual":
        channel = args.channel or VIRTUAL_DEFAULT_CHANNEL
        if logger:
            logger.info("Opening virtual bus (udp_multicast %s:%d)",
                        channel, args.port)
        # hop_limit=0 is NOT optional. python-can defaults it to 1, which puts
        # every frame on the wire: the kernel routes 239.0.0.0/8 out the default
        # interface, so an accelerated run floods the real LAN. Measured on this
        # network 2026-09-01 at 66,450 pps / 13.6 MB/s from the Vtrux interposer
        # bench, which disrupted the house network for ~20 minutes. Multicast is
        # flooded to every switch port unless IGMP snooping catches it, and APs
        # transmit it at the lowest basic rate, so wireless clients suffer worst
        # even when the source is wired. TTL 0 means the datagram is looped back
        # to local sockets and never transmitted on any interface.
        bus = can.interface.Bus(
            interface="udp_multicast",
            channel=channel,
            port=args.port,
            hop_limit=0,
            receive_own_messages=receive_own_messages,
        )
        _confine_to_host(bus)
        _enlarge_rx_buffer(bus)
        return bus

    # real dongle
    from canbench.live.receiver import detect_all_can_interfaces
    if logger:
        logger.info("Detecting %s interfaces at %d bps...",
                    args.transport, args.bitrate)
    interfaces = detect_all_can_interfaces(args.bitrate, brands={args.transport})
    matches = [i for i in interfaces if i[0] == args.transport]
    if not matches:
        raise RuntimeError("no %s interface detected" % args.transport)
    iface, ch, desc = matches[0]
    if args.channel is not None:
        ch = args.channel
    if logger:
        logger.info("Using real interface: %s", desc)

    kwargs = dict(bitrate=args.bitrate, receive_own_messages=receive_own_messages)
    # PCAN bus-off insurance for long live sessions (see
    # can-tools canbench/live/pcan-busoff-recovery.md): driver auto-recovers from bus-off.
    if iface == "pcan":
        kwargs["auto_reset"] = True

    if isinstance(ch, dict):
        bus = can.interface.Bus(interface=iface, **kwargs, **ch)
    else:
        bus = can.interface.Bus(interface=iface, channel=ch, **kwargs)

    if iface == "pcan":
        try:
            bus.reset()  # flush TX/RX queues + clear any post-error state
        except Exception as e:
            if logger:
                logger.debug("pcan reset() at startup failed (non-fatal): %s", e)
    return bus


def _confine_to_host(bus):
    """Re-assert TTL 0 and VERIFY it. Raises if traffic could reach the LAN.

    A hard failure on purpose: a virtual CAN bench that silently ends up on the
    wire is far worse than one that refuses to start. Do NOT also pin
    IP_MULTICAST_IF to loopback -- python-can joins the group with INADDR_ANY,
    which the kernel resolves to the default multicast interface, so sending via
    a different interface means receivers see nothing. TTL 0 alone is both
    necessary and sufficient.
    """
    import socket
    import struct

    sock = getattr(getattr(bus, "_multicast", None), "_socket", None)
    if sock is None:
        raise SystemExit(
            "refusing to start: cannot reach the multicast socket to verify "
            "IP_MULTICAST_TTL. Without that check every simulated CAN frame "
            "may be transmitted on the real network.")
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL,
                        struct.pack("@I", 0))
    except OSError as e:
        raise SystemExit(
            "refusing to start: could not set IP_MULTICAST_TTL to 0 (%s).\n"
            "Without it every simulated CAN frame goes on the real network." % e)
    ttl = sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL)
    if ttl != 0:
        raise SystemExit(
            "refusing to start: IP_MULTICAST_TTL is %d, not 0. Simulated CAN "
            "frames would be transmitted on the real network." % ttl)


def _enlarge_rx_buffer(bus, want=16 * 1024 * 1024):
    """Give the virtual bus a large receive buffer.

    The default ~200 KB overflows in bursts once the bus carries ordinary
    vehicle traffic on top of the flash, and the kernel then drops datagrams
    silently -- including the tester's own requests. Measured here 2026-09-20:
    with the default buffer and ~35 % foreign load the run dies at the very
    first request ("no response to service 0x10"); with 16 MB it gets through
    session setup, the security exchange and the erase before hitting a
    separate limit. A dropped frame reads as a protocol bug, not a full buffer,
    so this is worth having even though it does not make the simulators keep up
    with a fully loaded bus.

    The kernel caps this at net.core.rmem_max, so it raises the ceiling rather
    than removing it.
    """
    import socket

    sock = getattr(getattr(bus, "_multicast", None), "_socket", None)
    if sock is None:
        return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, want)
    except OSError:
        pass  # non-fatal: a smaller buffer still works on a quiet bus
