"""Bus-load governor: keep a laptop-driven flash from saturating D CAN.

WHY THIS IS NEEDED. The Omitec's reflash runs at 4.6 TransferData blocks/s and
uses about 8 % of a 500 kbps bus. Measured on the real capture, 92 % of that
cadence is the Omitec idling -- 160.7 ms between blocks and a further 1.10 ms
between consecutive frames although the ECU's flow control asks for STmin=0. Our
own tester has no reason to idle, and at the protocol's true floor (~17.3 ms per
block) it would transmit nearly back-to-back and take essentially the whole bus.

That is fine on a bench and NOT fine in the car. Ordinary D CAN traffic measured
on this vehicle runs **32-39 % utilisation** (2026-06-24 drive, per channel,
identified by the presence of 0x212 rather than by channel number). The flash
shares that segment: the gateway passes the UDS exchange through to D CAN and
the DLCM terminates it. Adding a ~95 % offered load on top of 35 % of real
vehicle traffic oversubscribes the bus; lower-priority broadcast frames lose
arbitration, get delayed behind our bursts, and modules that expect a cadence
can time out. During a CAL-only flash the application is still running -- it is
the PROG erase that kills it -- so that traffic is live and mattering.

WHAT THIS DOES. A sliding-window token budget over *bits on the wire*:

  ceiling      the total bus utilisation we refuse to exceed, ours + everyone
               else's. Default 0.70.
  max_own      a hard cap on our own share regardless of how quiet the bus is,
               so a silent bus does not license a 100 % flood. Default 0.45.

Our instantaneous budget is min(max_own, ceiling - observed_foreign), and
reserve() sleeps until sending the next frame would stay inside it. Foreign
traffic is whatever we did not transmit, the ECU's own replies included: we
cannot throttle those, but they do occupy the bus, so they count against the
ceiling rather than against our share.

FRAME COST. Classic CAN, 11-bit identifier:
    47 + 8n bits of frame, + up to (34 + 8n - 1)//4 stuffing bits, + 3 bit IFS
For n=8 that is 111 + 24 + 3 = 138 bits worst case, 114 nominal. Worst case is
the default: under-estimating our own cost is the failure that matters, since it
makes the governor permit more than it promised.
"""

import collections
import time


def frame_bits(dlc, stuffing="worst"):
    """Bits a classic-CAN standard-ID frame occupies, including the gap after."""
    base = 47 + 8 * dlc
    if stuffing == "worst":
        base += (34 + 8 * dlc - 1) // 4
    return base + 3


class BusLoadGovernor:
    def __init__(self, bitrate=500000, ceiling=0.70, max_own=0.45,
                 window_s=0.5, stuffing="worst", sleeper=time.sleep,
                 clock=time.monotonic):
        if not 0 < ceiling <= 1.0:
            raise ValueError("ceiling must be in (0, 1]")
        if not 0 < max_own <= 1.0:
            raise ValueError("max_own must be in (0, 1]")
        self.bitrate = bitrate
        self.ceiling = ceiling
        self.max_own = max_own
        self.window_s = window_s
        self.stuffing = stuffing
        self._sleep = sleeper
        self._clock = clock
        self._own = collections.deque()       # (t, bits) we transmitted
        self._foreign = collections.deque()   # (t, bits) everyone else
        self._own_bits = 0                    # running sums, kept exact by _trim
        self._foreign_bits = 0
        self.slept_s = 0.0
        self.frames_sent = 0
        self.frames_foreign = 0

    # -- bookkeeping ------------------------------------------------------

    def _trim(self, now):
        """Drop samples older than the window, keeping the running sums exact.

        The sums are maintained incrementally rather than recomputed. An earlier
        version summed both deques on every query, which is O(n) in the number of
        frames in the window -- fine on a quiet bench, quadratic-ish under load.
        At a realistic 35 % D CAN foreign load (~1400 frames/s) the window holds
        ~700 samples and reserve() re-summed them several times per frame, which
        consumed enough CPU to starve this process's own receive loop: the
        symptom was an ISO-TP flow-control timeout mid-flash, i.e. the throttle
        appearing to break the protocol it was meant to protect.
        """
        cut = now - self.window_s
        own, foreign = self._own, self._foreign
        while own and own[0][0] < cut:
            self._own_bits -= own.popleft()[1]
        while foreign and foreign[0][0] < cut:
            self._foreign_bits -= foreign.popleft()[1]

    def note_foreign(self, dlc):
        """Account a frame we did not send (vehicle traffic, or the ECU's reply)."""
        now = self._clock()
        self._trim(now)
        bits = frame_bits(dlc, self.stuffing)
        self._foreign.append((now, bits))
        self._foreign_bits += bits
        self.frames_foreign += 1

    # -- the throttle -----------------------------------------------------

    def budget(self, now=None):
        """Our currently permitted share of the bus, as a fraction."""
        now = self._clock() if now is None else now
        self._trim(now)
        foreign = self._foreign_bits / (self.window_s * self.bitrate)
        return max(0.0, min(self.max_own, self.ceiling - foreign)), foreign

    def reserve(self, dlc):
        """Block until sending a frame of this size stays inside the budget.

        Accounts the frame as sent. Returns the seconds spent waiting.
        """
        bits = frame_bits(dlc, self.stuffing)
        waited = 0.0
        while True:
            now = self._clock()
            share, _foreign = self.budget(now)
            capacity = share * self.window_s * self.bitrate
            used = self._own_bits
            if used + bits <= capacity or capacity <= 0 and not self._own:
                break
            # How long until enough of our own history ages out of the window?
            need = used + bits - capacity
            shed = 0.0
            delay = None
            for t, b in self._own:
                shed += b
                if shed >= need:
                    delay = (t + self.window_s) - now
                    break
            if delay is None or delay <= 0:
                delay = 0.001
            delay = min(delay, self.window_s)
            self._sleep(delay)
            waited += delay
            self.slept_s += delay
        now = self._clock()
        self._trim(now)
        self._own.append((now, bits))
        self._own_bits += bits
        self.frames_sent += 1
        return waited

    # -- reporting --------------------------------------------------------

    def utilisation(self):
        """(own, foreign, total) as fractions over the current window."""
        now = self._clock()
        self._trim(now)
        cap = self.window_s * self.bitrate
        own = self._own_bits / cap
        foreign = self._foreign_bits / cap
        return own, foreign, own + foreign

    def describe(self):
        own, foreign, total = self.utilisation()
        return ("bus %.1f %% (ours %.1f %%, other %.1f %%), ceiling %.0f %%, "
                "own cap %.0f %%, throttled %.1f s over %d frames"
                % (100 * total, 100 * own, 100 * foreign, 100 * self.ceiling,
                   100 * self.max_own, self.slept_s, self.frames_sent))


class NullGovernor:
    """No throttling. Explicit, so 'unthrottled' is a choice and not an oversight."""

    slept_s = 0.0
    frames_sent = 0
    frames_foreign = 0

    def note_foreign(self, dlc):
        pass

    def reserve(self, dlc):
        return 0.0

    def utilisation(self):
        return (0.0, 0.0, 0.0)

    def describe(self):
        return "bus load governor DISABLED (no throttling)"


def add_busload_args(parser):
    parser.add_argument("--bus-ceiling", type=float, default=0.70,
                        help="max TOTAL bus utilisation, ours + other traffic "
                             "(default 0.70; 0 disables throttling entirely)")
    parser.add_argument("--bus-max-own", type=float, default=0.45,
                        help="hard cap on OUR share even on a silent bus "
                             "(default 0.45)")
    parser.add_argument("--bus-window", type=float, default=0.5,
                        help="averaging window in seconds (default 0.5)")


def governor_from_args(args, bitrate=500000):
    if getattr(args, "bus_ceiling", 0) <= 0:
        return NullGovernor()
    return BusLoadGovernor(bitrate=bitrate, ceiling=args.bus_ceiling,
                           max_own=args.bus_max_own, window_s=args.bus_window)
