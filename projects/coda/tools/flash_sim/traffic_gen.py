"""Synthetic vehicle traffic, so the bus-load governor can be tested under load.

The virtual bus is otherwise silent, which is the one condition under which a
throttle cannot be shown to work: with no competing traffic the governor's own
cap binds and its adaptive half -- ceiling minus observed foreign load -- is
never exercised. This injects broadcast frames at a requested utilisation so a
flash can be run against a realistically busy D CAN.

Defaults reproduce what was measured on this vehicle: ordinary D CAN traffic at
32-39 % utilisation (2026-06-24 drive, per channel, buses identified by the
presence of 0x212 rather than by channel number). The IDs and cadences below are
the real periodic set from that capture.

Run from the project root:
    python3.13 projects/coda/tools/flash_sim/traffic_gen.py --load 0.35
"""

import argparse
import logging
import time

import can

from bus import add_bus_args, open_bus
from busload import frame_bits

logger = logging.getLogger("traffic")

# (arbitration id, dlc, period_s) -- the real periodic D CAN set.
PERIODIC = [
    (0x212, 6, 0.010), (0x210, 6, 0.010), (0x208, 8, 0.003),
    (0x1C0, 8, 0.003), (0x330, 8, 0.020), (0x418, 6, 0.020),
    (0x315, 8, 0.020), (0x240, 8, 0.050), (0x270, 8, 0.100),
]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_bus_args(p)
    p.add_argument("--load", type=float, default=0.35,
                   help="target bus utilisation as a fraction (default 0.35)")
    p.add_argument("--duration", type=float, default=0.0,
                   help="seconds to run (0 = until killed)")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s [%(levelname)s] tg: %(message)s",
                        datefmt="%H:%M:%S")

    bus = open_bus(args, receive_own_messages=False, logger=logger)

    # Scale the natural periods so the set adds up to the requested utilisation.
    natural = sum(frame_bits(d) / per for _, d, per in PERIODIC)
    target_bps = args.load * args.bitrate
    scale = natural / target_bps if target_bps > 0 else 1.0
    logger.info("natural load %.1f %%; scaling periods by %.2f to reach %.1f %%",
                100 * natural / args.bitrate, scale, 100 * args.load)

    msgs = [(can.Message(arbitration_id=i, data=bytes(d), is_extended_id=False),
             per * scale) for i, d, per in PERIODIC]
    nxt = [time.monotonic() + p for _, p in msgs]
    t_end = time.monotonic() + args.duration if args.duration > 0 else None
    sent = 0
    t0 = time.monotonic()
    try:
        while t_end is None or time.monotonic() < t_end:
            now = time.monotonic()
            due = min(range(len(msgs)), key=lambda k: nxt[k])
            if nxt[due] > now:
                time.sleep(min(nxt[due] - now, 0.005))
                continue
            bus.send(msgs[due][0])
            sent += 1
            nxt[due] += msgs[due][1]
            if nxt[due] < now:
                nxt[due] = now + msgs[due][1]
    except KeyboardInterrupt:
        pass
    finally:
        el = time.monotonic() - t0
        bits = sum(frame_bits(len(m.data)) for m, _ in msgs) * 0  # per-frame below
        logger.info("sent %d frames in %.1f s (%.0f fps)", sent, el, sent / (el or 1))
        bus.shutdown()


if __name__ == "__main__":
    main()
