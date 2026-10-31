"""Out-of-band (non-reflash) traffic responder for the Gateway/DLCM simulator.

During a real flash the Omitec does more than the 0x7E0/0x7E8 reprogramming
dialog: it continuously polls vehicle state and probes other modules. If the
simulator does not answer the essential polls, a real Omitec treats the vehicle
as absent / ignition-off and aborts before or during the flash.

What the real capture (coda_dlcm_flash6.log) shows outside 0x7E0/0x7E8:

  0x710 -> 0x718  IGNITION / KEEPALIVE poll, runs the ENTIRE session (t=0..3258s):
                  req  0x710: 22 64 01        (ReadDataByIdentifier DID 0x6401)
                  resp 0x718: 62 64 01 <ign>  (ign = 0x03 running, 0x00 off)
                  This is the critical one -- answer it or the Omitec aborts.
                  (Confirmed by coda-diagnostics/playback/coda_fake_car.py.)

  0x7DF           Functional broadcast: 10 82 (enter programming session) and
                  11 81 (ECUReset), both with the suppressPositiveResponse bit
                  (0x80) set -> NO response expected. We recognize and ignore.

  0x734/0x758/0x7ED   Other modules the Omitec probed pre-flash (their responses
                  landed on the shared bus). Mostly negative responses; not the
                  DLCM. Not emulated here -- see README. Add entries to
                  MODULE_RESPONDERS if a real-Omitec test shows the flash needs
                  a given module present.

The CAN controller ACKs every frame on the bus regardless of UDS content, so an
unanswered probe just times out on the Omitec side (as if that module were
absent) -- it does not cause bus-off the way transmitting to an empty bus does.
"""

import logging

import can

logger = logging.getLogger("gateway_sim.oob")

IGNITION_REQ_ID = 0x710
IGNITION_RESP_ID = 0x718
IGNITION_DID = 0x6401

FUNCTIONAL_REQ_ID = 0x7DF
SUPPRESS_POS_RSP_BIT = 0x80

# Extension point: emulate additional modules the real Omitec may require during
# a flash. Map a request arbitration ID to a callable(request_data) -> response
# payload bytes (UDS, no PCI) sent on req_id|0x8, or None to stay silent. Empty
# by default; populate only if a real-Omitec test shows the flash needs a given
# module present. The DTC vehicle sim (../../../coda-diagnostics/playback/
# coda_fake_car.py) has ready-made encoders for ABS/BMS/airbag/HVAC/AC.
MODULE_RESPONDERS = {}


class OutOfBandResponder:
    """Answers non-reflash frames the Omitec expects during a flash."""

    def __init__(self, bus, *, ignition_state=0x03, padding=0x00, log_polls=False,
                 extra_responders=None, ignition_file=None, logger_=None):
        """
        bus            : the shared python-can Bus (used to send responses).
        ignition_state : value returned for DID 0x6401 (0x03 = running/on).
        padding        : byte used to pad SF responses to 8 bytes.
        log_polls      : if True, log every ignition poll (noisy); else count.
        extra_responders : optional {req_id: callable(data)->bytes|None} to add
                         or override module responders. The callable gets the
                         raw request data and returns the response payload
                         (UDS bytes, no PCI) to send on req_id|0x8, or None.
        ignition_file  : optional path to a small text file holding the current
                         ignition state (e.g. "0x00" or "3"). Re-read on each
                         poll, so the state can be changed live (no restart, no
                         bus gap) by writing the file -- useful for following the
                         Omitec's post-flash ignition power-cycle prompts.
        """
        # Unhandled out-of-band arbitration IDs, logged once each rather
        # than once per frame -- see the handler below.
        self._seen_oob = set()
        self._oob_counts = {}
        self.bus = bus
        self.ignition_state = ignition_state & 0xFF
        self.padding = padding
        self.log_polls = log_polls
        self.ignition_file = ignition_file
        # Optional callable() -> ignition byte, asked on each poll. When set
        # (the gateway wires this to its finalization logic), it fully drives the
        # reported state and takes precedence over the fixed value / file.
        self.ignition_provider = None
        self._log = logger_ or logger
        self.ignition_polls = 0
        self.functional_seen = 0
        self.responders = dict(MODULE_RESPONDERS)
        if extra_responders:
            self.responders.update(extra_responders)

    def _refresh_ignition(self):
        """Re-read the ignition control file if configured; update state on change."""
        if not self.ignition_file:
            return
        try:
            with open(self.ignition_file) as f:
                txt = f.read().strip()
        except OSError:
            return
        if not txt:
            return
        try:
            val = int(txt, 0) & 0xFF
        except ValueError:
            return
        if val != self.ignition_state:
            self._log.info("ignition state changed %02X -> %02X (from %s)",
                           self.ignition_state, val, self.ignition_file)
            self.ignition_state = val

    def handle(self, msg):
        """Entry point for IsoTpEndpoint.oob_handler. Best-effort, never raises."""
        try:
            self._handle(msg)
        except Exception as e:  # keep the flash alive no matter what
            logger.debug("oob handler error on 0x%03X: %s", msg.arbitration_id, e)

    def _handle(self, msg):
        arb = msg.arbitration_id
        data = bytes(msg.data)

        # custom / overriding module responders first
        if arb in self.responders:
            resp = self.responders[arb](data)
            if resp is not None:
                self._send_sf(arb | 0x08, resp)
            return

        if arb == IGNITION_REQ_ID:
            self._handle_ignition(data)
            return

        if arb == FUNCTIONAL_REQ_ID:
            self._handle_functional(data)
            return

        # Any other frame on the shared bus. Worth seeing ONCE per arbitration
        # ID -- it tells us whether the tester probes anything besides ignition
        # (e.g. a DLCM version read on a different ID) -- but not once per
        # frame. Logging every one at INFO makes the simulator unusable the
        # moment the bus carries ordinary vehicle traffic: at the ~1400 frames/s
        # of a realistic 35 % D CAN load the log I/O starves this process's own
        # receive loop, the 0x7E0 request is never serviced, and the tester
        # times out with "no response to service 0x10" -- which reads as a
        # protocol or throttle bug and is neither.
        if arb not in self._seen_oob:
            self._seen_oob.add(arb)
            self._log.info("OOB rx 0x%03X %s (unhandled -- not answered; "
                           "further frames on this ID logged at DEBUG only)",
                           arb, data.hex())
        else:
            self._oob_counts[arb] = self._oob_counts.get(arb, 0) + 1
            # data.hex() is an argument expression, so it runs even when DEBUG
            # is off. On a bus carrying vehicle traffic this is thousands of
            # pointless hex conversions per second in the receive path.
            if self._log.isEnabledFor(logging.DEBUG):
                self._log.debug("OOB rx 0x%03X %s (unhandled)", arb, data.hex())

    def _handle_ignition(self, data):
        if self.ignition_provider is not None:
            self.ignition_state = self.ignition_provider() & 0xFF
        else:
            self._refresh_ignition()
        # expect SF: 03 22 64 01
        if len(data) < 4 or (data[0] >> 4) != 0:
            return
        if data[1] == 0x22 and ((data[2] << 8) | data[3]) == IGNITION_DID:
            self.ignition_polls += 1
            resp = bytes([0x62, 0x64, 0x01, self.ignition_state])
            self._send_sf(IGNITION_RESP_ID, resp)
            if self.log_polls:
                logger.info("ignition poll #%d -> 0x718 62 64 01 %02X",
                            self.ignition_polls, self.ignition_state)

    def _handle_functional(self, data):
        # functional broadcast; sub-function bit 0x80 => suppress positive resp.
        if len(data) < 2 or (data[0] >> 4) != 0:
            return
        self.functional_seen += 1
        sid = data[1]
        sub = data[2] if len(data) > 2 else 0
        if sub & SUPPRESS_POS_RSP_BIT:
            logger.debug("functional 0x7DF svc=0x%02X sub=0x%02X (suppressPosRsp) -> ignore",
                         sid, sub)
            return
        # A functional request WITHOUT suppress would expect the DLCM to answer
        # on 0x7E8. Not observed in the capture; log and leave to the reflash
        # dispatcher if it ever appears.
        logger.info("functional 0x7DF svc=0x%02X sub=0x%02X (no suppress) -- not answered",
                    sid, sub)

    def _send_sf(self, arb_id, payload):
        payload = bytes(payload)
        frame = bytes([len(payload) & 0x0F]) + payload
        if len(frame) < 8:
            frame = frame + bytes([self.padding]) * (8 - len(frame))
        self.bus.send(can.Message(arbitration_id=arb_id, data=frame, is_extended_id=False))
