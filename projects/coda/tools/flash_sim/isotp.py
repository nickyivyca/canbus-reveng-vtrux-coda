"""Minimal ISO-TP (ISO 15765-2) transport over a python-can Bus.

Just enough of ISO-TP to carry the Coda DLCM UDS reflash on classic CAN
(8-byte frames): single frame, first frame + consecutive frames, and flow
control. One IsoTpEndpoint object owns a (tx_id, rx_id) pair and can both send
and receive full UDS payloads over the shared bus.

Real capture parameters this models (flash6.log):
  - ECU flow control is always "30 00 00": FS=ClearToSend, BlockSize=0
    (send everything), STmin=0 (no inter-frame separation required).
  - Frames are padded to 8 bytes (padding byte is cosmetic; receivers ignore it).

The endpoint is deliberately single-threaded and half-duplex, matching the
request/response nature of a UDS flash: send_uds() fully completes (including
waiting for the peer's flow control) before returning, and recv_uds() fully
reassembles one message (including emitting our own flow control) before
returning.
"""

import time

import can

# PCI type nibbles (high nibble of byte 0)
PCI_SF = 0x0  # single frame
PCI_FF = 0x1  # first frame
PCI_CF = 0x2  # consecutive frame
PCI_FC = 0x3  # flow control

# Flow-control status (low nibble of FC byte 0)
FC_CTS = 0x0       # clear to send
FC_WAIT = 0x1      # wait
FC_OVERFLOW = 0x2  # overflow / abort


class IsoTpError(Exception):
    pass


class IsoTpTimeout(IsoTpError):
    pass


def _stmin_seconds(stmin):
    """Decode an ISO-TP STmin byte to seconds."""
    if stmin <= 0x7F:
        return stmin / 1000.0            # 0..127 ms
    if 0xF1 <= stmin <= 0xF9:
        return (stmin - 0xF0) / 10000.0  # 100..900 us
    return 0.0                            # reserved -> treat as 0


class IsoTpEndpoint:
    def __init__(self, bus, tx_id, rx_id, *, padding=0xAA, extended_id=False,
                 fc_block_size=0, fc_stmin=0, logger=None, oob_handler=None,
                 governor=None, tx_stmin_floor=0.0):
        """
        bus            : an open python-can Bus (any interface).
        tx_id / rx_id  : arbitration IDs we transmit on / receive on.
        padding        : byte used to pad frames to 8 bytes.
        fc_block_size  : BlockSize we advertise when WE receive a multi-frame
                         message (0 = send all, matches the real DLCM).
        fc_stmin       : STmin byte we advertise as a receiver (0 = no gap).
        tx_stmin_floor : MINIMUM gap, in seconds, between consecutive frames we
                         TRANSMIT -- a floor under whatever STmin the receiver
                         asks for, not a replacement for it (we take the max).
                         0.0 = honour the receiver exactly, the old behaviour.
                         The DLCM advertises STmin=0, so without a floor a
                         TransferData block goes out as ~37 back-to-back frames.
                         That is ~4x the instantaneous rate the real Omitec ever
                         put through the GWM gateway (it spaced frames ~1.1 ms),
                         and block-level pacing cannot soften it: --block-delay
                         changes the gap BETWEEN bursts, not the burst itself.
                         Set this when flashing through the gateway.
        oob_handler    : optional callable(can.Message). Invoked for every
                         received frame that is NOT addressed to rx_id (e.g. the
                         Omitec's ignition/keepalive polls on other IDs), so the
                         endpoint can answer out-of-band traffic while it waits
                         for the next flash frame. Must not block.
        """
        self.bus = bus
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.padding = padding
        self.extended_id = extended_id
        self.fc_block_size = fc_block_size
        self.fc_stmin = fc_stmin
        self.tx_stmin_floor = tx_stmin_floor
        self.log = logger
        self.oob_handler = oob_handler
        # Bus-load governor (busload.py). Every frame we transmit is metered
        # through it, and every frame we observe that we did not send is
        # accounted as foreign traffic. None = no throttling.
        self.governor = governor

    # -- low-level frame I/O -------------------------------------------------

    def _send_frame(self, data):
        payload = bytes(data)
        if len(payload) < 8:
            payload = payload + bytes([self.padding]) * (8 - len(payload))
        # Throttle BEFORE handing the frame to the driver. Metering after the
        # send would let a burst reach the wire and only then slow down, which
        # is exactly the transient that disturbs other modules.
        if self.governor is not None:
            self.governor.reserve(len(payload))
        msg = can.Message(
            arbitration_id=self.tx_id,
            data=payload,
            is_extended_id=self.extended_id,
        )
        self.bus.send(msg)

    def _recv_frame(self, timeout):
        """Return the next CAN frame addressed to rx_id, or None on timeout."""
        deadline = None
        remaining = timeout
        while True:
            msg = self.bus.recv(timeout=remaining if remaining is not None else 0.2)
            if msg is not None and self.governor is not None \
                    and msg.arbitration_id != self.tx_id:
                # Anything we did not transmit occupies the bus too -- the ECU's
                # own replies included. We cannot throttle those, so they count
                # against the total ceiling rather than against our own share.
                self.governor.note_foreign(len(msg.data))
            if msg is not None and msg.arbitration_id == self.rx_id \
                    and bool(msg.is_extended_id) == bool(self.extended_id):
                return msg
            if msg is not None and self.oob_handler is not None:
                # frame not addressed to us (e.g. ignition/keepalive poll on
                # another ID) -- let the out-of-band handler answer it.
                self.oob_handler(msg)
            if timeout is None:
                continue
            # decrement remaining against a monotonic deadline
            if deadline is None:
                deadline = time.monotonic() + timeout
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None

    # -- receive a full UDS message -----------------------------------------

    def recv_uds(self, timeout=2.0):
        """Reassemble one UDS payload. Emits our flow control for multi-frame.

        Returns bytes, or None on timeout with nothing received.
        Non-addressed frames and stray flow-control frames are ignored.
        """
        msg = self._recv_frame(timeout)
        if msg is None:
            return None
        d = msg.data
        if not d:
            return None
        pci = d[0] >> 4

        if pci == PCI_SF:
            length = d[0] & 0x0F
            return bytes(d[1:1 + length])

        if pci == PCI_FF:
            total = ((d[0] & 0x0F) << 8) | d[1]
            buf = bytearray(d[2:8])
            # send flow control: clear to send
            self._send_frame(bytes([0x30 | FC_CTS, self.fc_block_size, self.fc_stmin]))
            expected_seq = 1
            since_fc = 0
            while len(buf) < total:
                cf = self._recv_frame(timeout)
                if cf is None:
                    raise IsoTpTimeout("timeout waiting for consecutive frame "
                                       "(%d/%d bytes)" % (len(buf), total))
                cd = cf.data
                if (cd[0] >> 4) != PCI_CF:
                    # unexpected non-CF mid-transfer; ignore FC, else abort
                    if (cd[0] >> 4) == PCI_FC:
                        continue
                    raise IsoTpError("expected CF, got PCI 0x%X" % (cd[0] >> 4))
                seq = cd[0] & 0x0F
                if seq != (expected_seq & 0x0F):
                    raise IsoTpError("bad CF sequence: got %d expected %d"
                                     % (seq, expected_seq & 0x0F))
                buf.extend(cd[1:8])
                expected_seq += 1
                since_fc += 1
                if self.fc_block_size and since_fc >= self.fc_block_size \
                        and len(buf) < total:
                    self._send_frame(bytes([0x30 | FC_CTS,
                                            self.fc_block_size, self.fc_stmin]))
                    since_fc = 0
            return bytes(buf[:total])

        if pci == PCI_FC:
            # stray flow control with no send in progress; ignore, try again
            return self.recv_uds(timeout)

        raise IsoTpError("unexpected PCI 0x%X" % pci)

    # -- send a full UDS message --------------------------------------------

    def send_uds(self, payload, fc_timeout=2.0):
        """Transmit a UDS payload, doing FF/CF + flow-control handshake."""
        payload = bytes(payload)
        n = len(payload)
        if n <= 7:
            self._send_frame(bytes([(PCI_SF << 4) | n]) + payload)
            return

        # first frame carries 6 data bytes
        ff = bytes([(PCI_FF << 4) | ((n >> 8) & 0x0F), n & 0xFF]) + payload[0:6]
        self._send_frame(ff)

        bs, stmin = self._await_fc(fc_timeout)
        idx = 6
        seq = 1
        sent_in_block = 0
        st = max(_stmin_seconds(stmin), self.tx_stmin_floor)
        while idx < n:
            chunk = payload[idx:idx + 7]
            self._send_frame(bytes([(PCI_CF << 4) | (seq & 0x0F)]) + chunk)
            idx += 7
            seq += 1
            sent_in_block += 1
            if idx >= n:
                break
            if bs and sent_in_block >= bs:
                bs, stmin = self._await_fc(fc_timeout)
                st = max(_stmin_seconds(stmin), self.tx_stmin_floor)
                sent_in_block = 0
            elif st > 0:
                self._pace(st)

    def _pace(self, seconds):
        """Wait `seconds` accurately, including sub-millisecond values.

        time.sleep() rounds UP to the OS timer granularity, which on Windows can
        be ~15 ms -- 14x the ~1.1 ms inter-frame gap we are trying to reproduce.
        Using it here would silently turn a 1.1 ms request into a 15 ms one and
        stretch a 456-block flash by minutes. Spin on perf_counter() for short
        waits instead: it burns a core, but it is the only way to pace frames at
        sub-millisecond accuracy on this platform, and it only runs during the
        transfer itself.
        """
        if seconds <= 0:
            return
        if seconds >= 0.005:
            time.sleep(seconds)
            return
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            pass

    def _await_fc(self, timeout):
        """Wait for a ClearToSend flow-control frame; return (block_size, stmin)."""
        while True:
            msg = self._recv_frame(timeout)
            if msg is None:
                raise IsoTpTimeout("timeout waiting for flow control")
            d = msg.data
            if (d[0] >> 4) != PCI_FC:
                # ignore anything that is not flow control while awaiting FC
                continue
            fs = d[0] & 0x0F
            if fs == FC_CTS:
                return d[1], d[2]
            if fs == FC_WAIT:
                continue
            raise IsoTpError("flow control overflow/abort (FS=0x%X)" % fs)
