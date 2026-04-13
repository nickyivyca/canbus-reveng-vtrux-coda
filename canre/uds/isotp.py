"""canre.uds.isotp -- Synchronous ISO 15765-2 (ISO-TP) transport channel.

Wraps python-isotp TransportLayer in a polling model so callers do not need
to manage threads.  Supports python-isotp v1 and v2 API signatures.

Key design: the rxfn callback taps ALL received CAN frames into _raw_tap
before the TransportLayer filters by rx_id.  The scanner reads _raw_tap
after each probe to detect ECUs that reply on a non-standard response ID.

Public API
----------
ISOTPChannel(bus, tx_id, rx_id, timeout=0.1, padding=True)
    .request(data, timeout=None) -> bytes | None
    .send(data) -> None
    .receive(timeout=None) -> bytes | None
    .pump(duration=0.0) -> list[bytes]
    .close() -> None
    ._raw_tap : list of (arbitration_id, data_bytes) tuples, appended by rxfn
"""

import time
import logging

try:
    import isotp
except ImportError as _e:
    raise ImportError(
        "python-isotp is required: pip install isotp"
    ) from _e

import can

logger = logging.getLogger(__name__)


def _parse_isotp_version():
    """Return (major, minor) integer tuple from isotp.__version__."""
    try:
        parts = isotp.__version__.split(".")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return 1, 0


class ISOTPChannel:
    """Synchronous ISO 15765-2 transport channel over a python-can Bus.

    Parameters
    ----------
    bus : can.BusABC
        Open python-can bus instance.
    tx_id : int
        CAN arbitration ID for outgoing (request) frames.
    rx_id : int
        CAN arbitration ID for incoming (response) frames.
    timeout : float
        Default timeout in seconds for send/receive operations.
    padding : bool
        If True, pad outgoing frames to 8 bytes with 0xCC.
    extended_id : bool
        Use 29-bit extended CAN IDs.  Default False (11-bit standard).
    """

    def __init__(self, bus, tx_id, rx_id, timeout=0.1, padding=True,
                 extended_id=False):
        self._bus = bus
        self._tx_id = tx_id
        self._rx_id = rx_id
        self._default_timeout = timeout
        self._padding = padding
        self._extended_id = extended_id

        # Raw frame tap: list of (arbitration_id, bytes) for every frame seen
        self._raw_tap = []

        self._layer = self._build_layer()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _txfn(self, frame):
        """Send a CAN frame produced by the ISO-TP layer."""
        msg = can.Message(
            arbitration_id=frame.arbitration_id,
            data=frame.data,
            is_extended_id=self._extended_id,
            is_fd=False,
        )
        self._bus.send(msg)

    def _rxfn(self, timeout=0):
        """Poll bus for one CAN frame; tap it before returning to ISO-TP layer.

        Returns an isotp.CanMessage (or the v2 equivalent) if a frame
        arrives, else None.
        """
        deadline = time.monotonic() + max(timeout, 0)
        while True:
            remaining = deadline - time.monotonic()
            msg = self._bus.recv(timeout=max(remaining, 0))
            if msg is None:
                return None
            # Tap every frame regardless of ID
            self._raw_tap.append((msg.arbitration_id, bytes(msg.data)))
            # Return only if it matches rx_id (the layer will also check,
            # but returning non-matching frames causes them to be silently
            # dropped by the layer, which is fine)
            # isotp v2 CanMessage uses 'extended_id' (not 'is_extended_id')
            return isotp.CanMessage(
                arbitration_id=msg.arbitration_id,
                data=bytes(msg.data),
                dlc=msg.dlc,
                extended_id=msg.is_extended_id,
            )

    def _build_layer(self):
        """Construct the isotp.TransportLayer, handling v1/v2 API differences."""
        major, minor = _parse_isotp_version()
        logger.debug("python-isotp version %s.%s", major, minor)

        address = isotp.Address(
            isotp.AddressingMode.Normal_11bits,
            txid=self._tx_id,
            rxid=self._rx_id,
        )

        params = {}
        if self._padding:
            params["tx_padding"] = 0xCC

        if major >= 2:
            # v2 API: TransportLayer(address=..., rxfn=..., txfn=..., params=...)
            layer = isotp.TransportLayer(
                rxfn=self._rxfn,
                txfn=self._txfn,
                address=address,
                params=params if params else None,
            )
        else:
            # v1 API: TransportLayer(rxfn=..., txfn=..., addressing_mode=...,
            #                        source_id=..., target_id=..., params=...)
            layer = isotp.TransportLayer(
                rxfn=self._rxfn,
                txfn=self._txfn,
                address=address,
                params=params if params else None,
            )
        return layer

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send(self, data: bytes) -> None:
        """Enqueue an ISO-TP payload for transmission."""
        self._layer.send(data)
        # Pump until all outgoing frames have been transmitted
        deadline = time.monotonic() + self._default_timeout
        while time.monotonic() < deadline:
            self._layer.process()
            if not self._layer.transmitting():
                return
            time.sleep(0.001)
        logger.warning("ISOTPChannel: send timed out for tx_id=0x%03X", self._tx_id)

    def receive(self, timeout=None) -> "bytes | None":
        """Poll for an ISO-TP payload until timeout.

        Returns the reassembled payload bytes, or None on timeout.
        """
        if timeout is None:
            timeout = self._default_timeout
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._layer.process()
            payload = self._layer.recv()
            if payload is not None:
                return bytes(payload)
            time.sleep(0.001)
        return None

    def request(self, data: bytes, timeout=None) -> "bytes | None":
        """Send data and wait for a response payload.

        Returns the response payload bytes, or None on timeout.
        """
        self._raw_tap.clear()
        self.send(data)
        return self.receive(timeout=timeout)

    def pump(self, duration=0.0) -> "list[bytes]":
        """Process the layer for `duration` seconds and return all payloads received.

        Useful for draining unsolicited traffic before a scan.
        """
        results = []
        deadline = time.monotonic() + duration
        while True:
            self._layer.process()
            payload = self._layer.recv()
            if payload is not None:
                results.append(bytes(payload))
            if time.monotonic() >= deadline:
                break
            time.sleep(0.001)
        return results

    def close(self) -> None:
        """Release any layer resources (does not close the underlying bus)."""
        try:
            self._layer.reset()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tx_id(self) -> int:
        return self._tx_id

    @property
    def rx_id(self) -> int:
        return self._rx_id
