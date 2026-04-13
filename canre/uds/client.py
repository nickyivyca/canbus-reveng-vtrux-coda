"""canre.uds.client -- UDS + KWP2000 service layer.

Sits on top of ISOTPChannel and provides typed methods for the diagnostic
services used by UDSScanner.  Handles NRC 0x78 (ResponsePending) retries
automatically.

Exceptions
----------
UDSNegativeResponse  -- ECU replied with a 0x7F negative response
UDSTimeout           -- no response within timeout
ISOTPError           -- ISO-TP layer error

Public API
----------
UDSClient(channel, timeout=0.2)
    .raw_request(data, timeout=None) -> bytes
    .session_control(session_type=SESSION_DEFAULT) -> dict
    .tester_present(suppress_response=True) -> None
    .read_data_by_id(did) -> dict
    .read_dtc_subfunction(subfunction, extra=b'') -> dict
    .read_kwp_dtc(group=0xFF00, status_mask=0xFF) -> dict
    .probe_service(service_id) -> dict
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service IDs
# ---------------------------------------------------------------------------
SVC_SESSION_CTRL   = 0x10
SVC_SEC_ACCESS     = 0x27
SVC_TESTER_PRESENT = 0x3E
SVC_READ_DATA      = 0x22
SVC_READ_DTC       = 0x19
SVC_KWP_READ_DTC   = 0x18
SVC_READ_ECU_ID    = 0x1A   # KWP2000 ECU identification

SESSION_DEFAULT    = 0x01
SESSION_EXTENDED   = 0x03

# F1xx DIDs to query via ReadDataByIdentifier (0x22)
F1XX_DIDS = {
    0xF186: "active_diagnostic_session",
    0xF187: "spare_part_number",
    0xF188: "ecu_sw_number",
    0xF189: "ecu_sw_version",
    0xF18A: "system_supplier_id",
    0xF18B: "ecu_mfg_date",
    0xF18C: "ecu_serial_number",
    0xF190: "vin",
    0xF191: "ecu_hw_number",
    0xF192: "supplier_hw_number",
    0xF193: "supplier_hw_version",
    0xF194: "supplier_sw_number",
    0xF195: "supplier_sw_version",
    0xF197: "system_name_or_engine_type",
}

# Positive response offset
_POS_OFFSET = 0x40

# ---------------------------------------------------------------------------
# Services that are SAFE to probe (read-only / no side-effects)
# ---------------------------------------------------------------------------
SAFE_PROBE_SERVICES = frozenset([
    0x10,  # DiagnosticSessionControl
    0x22,  # ReadDataByIdentifier
    0x19,  # ReadDTCInformation
    0x27,  # SecurityAccess (seed request only -- we never send key)
    0x3E,  # TesterPresent
    0x1A,  # ReadECUIdentification (KWP2000)
    0x18,  # ReadDTCByStatus (KWP2000)
    0x21,  # ReadDataByLocalIdentifier (KWP2000)
])

# Services that MUST NEVER be probed
UNSAFE_PROBE_SERVICES = frozenset([
    0x11,  # ECUReset
    0x14,  # ClearDiagnosticInformation
    0x28,  # CommunicationControl
    0x2E,  # WriteDataByIdentifier
    0x31,  # RoutineControl
    0x34,  # RequestDownload
    0x35,  # RequestUpload
    0x36,  # TransferData
    0x37,  # RequestTransferExit
    0x85,  # ControlDTCSetting
])

# ---------------------------------------------------------------------------
# NRC table
# ---------------------------------------------------------------------------
_NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x25: "noResponseFromSubnetComponent",
    0x26: "failurePreventsExecutionOfRequestedAction",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


def _nrc_name(nrc: int) -> str:
    return _NRC_NAMES.get(nrc, f"unknown_0x{nrc:02X}")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UDSNegativeResponse(Exception):
    """ECU replied with a 0x7F negative response frame."""

    def __init__(self, service_id: int, nrc: int):
        self.service_id = service_id
        self.nrc = nrc
        self.nrc_name = _nrc_name(nrc)
        super().__init__(
            f"NegativeResponse for service 0x{service_id:02X}: "
            f"NRC 0x{nrc:02X} ({self.nrc_name})"
        )


class UDSTimeout(Exception):
    """No response received within the timeout period."""


class ISOTPError(Exception):
    """ISO-TP layer error (malformed frame, overflow, etc.)."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

# Maximum ResponsePending retries before giving up
_MAX_PENDING_RETRIES = 3
_PENDING_EXTENDED_TIMEOUT = 1.0   # seconds


class UDSClient:
    """UDS + KWP2000 service layer on top of ISOTPChannel.

    Parameters
    ----------
    channel : ISOTPChannel
        Open, addressed ISOTP channel.
    timeout : float
        Default request timeout in seconds.
    """

    def __init__(self, channel, timeout: float = 0.2):
        self._ch = channel
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------

    def raw_request(self, data: bytes, timeout=None) -> bytes:
        """Send raw UDS/KWP bytes and return the positive response payload.

        Handles NRC 0x78 (ResponsePending) by re-waiting up to
        _MAX_PENDING_RETRIES times with an extended timeout.

        Raises
        ------
        UDSTimeout            no response
        UDSNegativeResponse   ECU sent 0x7F NRC
        ISOTPError            malformed response
        """
        if timeout is None:
            timeout = self._timeout

        resp = self._ch.request(data, timeout=timeout)
        if resp is None:
            raise UDSTimeout(
                f"No response to service 0x{data[0]:02X} "
                f"(tx_id=0x{self._ch.tx_id:03X})"
            )

        for _retry in range(_MAX_PENDING_RETRIES):
            resp = self._check_response(data[0], resp)
            if resp is not None:
                return resp
            # NRC 0x78 -- re-receive with extended timeout
            resp = self._ch.receive(timeout=_PENDING_EXTENDED_TIMEOUT)
            if resp is None:
                raise UDSTimeout(
                    f"No response after ResponsePending for service "
                    f"0x{data[0]:02X}"
                )

        # Exhausted retries -- final check
        result = self._check_response(data[0], resp)
        if result is not None:
            return result
        raise UDSTimeout("Exhausted ResponsePending retries")

    def _check_response(self, service_id: int, resp: bytes):
        """Parse one response frame.

        Returns:
            bytes  -- positive response payload (stripped of SID byte)
            None   -- NRC 0x78 (ResponsePending), caller should retry

        Raises:
            UDSNegativeResponse  -- other NRC
            ISOTPError           -- malformed frame
        """
        if len(resp) < 1:
            raise ISOTPError("Empty response frame")

        if resp[0] == 0x7F:
            # Negative response: [0x7F, echo_sid, nrc]
            if len(resp) < 3:
                raise ISOTPError(
                    f"Malformed NRC frame (len={len(resp)}): {resp.hex()}"
                )
            nrc = resp[2]
            if nrc == 0x78:
                logger.debug(
                    "NRC 0x78 (ResponsePending) for service 0x%02X -- waiting",
                    service_id,
                )
                return None   # signal caller to retry
            raise UDSNegativeResponse(service_id, nrc)

        expected = service_id + _POS_OFFSET
        if resp[0] != expected:
            # KWP2000 positive SIDs may differ -- accept any non-0x7F frame
            logger.debug(
                "Unexpected SID in response: got 0x%02X, expected 0x%02X",
                resp[0], expected,
            )
        return resp   # return full frame including SID byte

    # ------------------------------------------------------------------
    # Service methods
    # ------------------------------------------------------------------

    def session_control(self, session_type: int = SESSION_DEFAULT) -> dict:
        """Send DiagnosticSessionControl (0x10).

        Returns dict with 'raw' and 'session_type'.
        """
        resp = self.raw_request(bytes([SVC_SESSION_CTRL, session_type]))
        return {"session_type": session_type, "raw": resp.hex()}

    def tester_present(self, suppress_response: bool = True) -> None:
        """Send TesterPresent (0x3E) to keep the session alive.

        With suppress_response=True (subfunction 0x80), the ECU sends no reply;
        this is the recommended keep-alive pattern.
        """
        subfn = 0x80 if suppress_response else 0x00
        try:
            if suppress_response:
                self._ch.send(bytes([SVC_TESTER_PRESENT, subfn]))
                # No response expected -- pump briefly to drain any stray frames
                self._ch.pump(duration=0.005)
            else:
                self.raw_request(bytes([SVC_TESTER_PRESENT, subfn]))
        except (UDSTimeout, UDSNegativeResponse):
            pass   # keep-alive failures are non-fatal

    def read_data_by_id(self, did: int) -> dict:
        """Send ReadDataByIdentifier (0x22) for a single DID.

        Returns dict:
            {'responded': bool, 'nrc': int|None, 'nrc_name': str|None,
             'raw': str|None, 'value': str|None}

        The 'value' field is an ASCII decode of the data bytes if all
        characters are printable, else a hex string.
        """
        result = {
            "responded": False,
            "nrc": None,
            "nrc_name": None,
            "raw": None,
            "value": None,
        }
        try:
            resp = self.raw_request(
                bytes([SVC_READ_DATA, (did >> 8) & 0xFF, did & 0xFF])
            )
            result["responded"] = True
            # Response: [0x62, DID_HB, DID_LB, data...]
            if len(resp) >= 3:
                data_bytes = resp[3:]
                result["raw"] = data_bytes.hex()
                result["value"] = _try_ascii(data_bytes)
            else:
                result["raw"] = resp.hex()
        except UDSNegativeResponse as e:
            result["nrc"] = e.nrc
            result["nrc_name"] = e.nrc_name
        except UDSTimeout:
            pass
        return result

    def read_dtc_subfunction(
        self,
        subfunction: int,
        extra: bytes = b"",
    ) -> dict:
        """Send ReadDTCInformation (0x19) with given subfunction + extra bytes.

        Returns dict:
            {'responded': bool, 'nrc': int|None, 'nrc_name': str|None,
             'dtc_count': int, 'dtcs': list[str], 'raw': str|None}
        """
        result = {
            "responded": False,
            "nrc": None,
            "nrc_name": None,
            "dtc_count": 0,
            "dtcs": [],
            "raw": None,
        }
        try:
            req = bytes([SVC_READ_DTC, subfunction]) + extra
            resp = self.raw_request(req)
            result["responded"] = True
            result["raw"] = resp.hex()
            # Parse DTCs from 0x59 response
            dtcs, count = _parse_dtc_response(subfunction, resp)
            result["dtc_count"] = count
            result["dtcs"] = dtcs
        except UDSNegativeResponse as e:
            result["nrc"] = e.nrc
            result["nrc_name"] = e.nrc_name
        except UDSTimeout:
            pass
        return result

    def read_kwp_dtc(
        self,
        group: int = 0xFF00,
        status_mask: int = 0xFF,
    ) -> dict:
        """Send KWP2000 ReadDTCByStatus (0x18).

        Request layout: [0x18, status_mask, group_HB, group_LB]
        Positive response SID: 0x58

        Returns dict:
            {'responded': bool, 'nrc': int|None, 'nrc_name': str|None,
             'dtc_count': int, 'dtcs': list[str], 'raw': str|None}
        """
        result = {
            "responded": False,
            "nrc": None,
            "nrc_name": None,
            "dtc_count": 0,
            "dtcs": [],
            "raw": None,
        }
        try:
            req = bytes([
                SVC_KWP_READ_DTC,
                status_mask,
                (group >> 8) & 0xFF,
                group & 0xFF,
            ])
            resp = self.raw_request(req)
            result["responded"] = True
            result["raw"] = resp.hex()
            dtcs, count = _parse_kwp_dtc_response(resp)
            result["dtc_count"] = count
            result["dtcs"] = dtcs
        except UDSNegativeResponse as e:
            result["nrc"] = e.nrc
            result["nrc_name"] = e.nrc_name
        except UDSTimeout:
            pass
        return result

    def probe_service(self, service_id: int) -> dict:
        """Probe whether a service is supported without triggering side effects.

        Only safe services (SAFE_PROBE_SERVICES) may be probed.  Unsafe
        service IDs are rejected immediately.

        Returns dict:
            {'supported': bool, 'nrc': int|None, 'nrc_name': str|None}
        """
        if service_id in UNSAFE_PROBE_SERVICES:
            raise ValueError(
                f"Service 0x{service_id:02X} is unsafe to probe and will not "
                f"be sent to the bus."
            )

        result = {"supported": False, "nrc": None, "nrc_name": None}

        # Build a minimal (deliberately incomplete) request to elicit a
        # meaningful NRC without actually executing the service.
        probe_bytes = _build_probe_request(service_id)

        try:
            self.raw_request(probe_bytes)
            result["supported"] = True
        except UDSNegativeResponse as e:
            # NRC 0x11 (serviceNotSupported) or 0x7F (serviceNotSupportedInSession)
            # = not supported.  Any other NRC means the service exists but
            # rejected our minimal request -- it IS supported.
            if e.nrc in (0x11, 0x7F):
                result["supported"] = False
            else:
                result["supported"] = True
            result["nrc"] = e.nrc
            result["nrc_name"] = e.nrc_name
        except UDSTimeout:
            # Timeout on a probe is ambiguous -- treat as not supported
            result["supported"] = False

        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_ascii(data: bytes) -> str:
    """Return ASCII string if all bytes are printable ASCII, else hex string."""
    try:
        text = data.decode("ascii")
        if all(c.isprintable() for c in text):
            return text.strip("\x00 ")
    except (UnicodeDecodeError, AttributeError):
        pass
    return data.hex()


def _build_probe_request(service_id: int) -> bytes:
    """Build a minimal safe probe request for a given service ID.

    The request is intentionally incomplete so the ECU will either:
    - Return NRC 0x11/0x7F (not supported), or
    - Return NRC 0x12/0x13 (wrong subfunction/length -- service IS supported).
    """
    probes = {
        0x10: bytes([0x10, 0x01]),          # Default session (safe)
        0x22: bytes([0x22, 0xF1, 0x90]),    # Read VIN DID
        0x19: bytes([0x19, 0x02, 0xFF]),    # reportDTCByStatusMask all
        0x27: bytes([0x27, 0x01]),          # SecurityAccess seed request
        0x3E: bytes([0x3E, 0x80]),          # TesterPresent suppress
        0x1A: bytes([0x1A, 0x86]),          # KWP ECU identification
        0x18: bytes([0x18, 0xFF, 0xFF, 0x00]),  # KWP ReadDTCByStatus all
        0x21: bytes([0x21, 0x01]),          # KWP ReadDataByLocalIdentifier
    }
    return probes.get(service_id, bytes([service_id]))


def _parse_dtc_response(subfunction: int, resp: bytes):
    """Parse 0x59 ReadDTCInformation response.

    Returns (dtcs: list[str], count: int).
    DTC bytes are encoded as 3-byte groups (B0 B1 B2=status).
    For subfunction 0x01 (reportNumberOfDTCByStatusMask) the count is in B2-B3.
    """
    dtcs = []
    count = 0

    if len(resp) < 1:
        return dtcs, count

    # Subfunction 0x01: response = [0x59, 0x01, status_avail, count_HB, count_LB]
    if subfunction == 0x01:
        if len(resp) >= 5:
            count = (resp[3] << 8) | resp[4]
        return dtcs, count

    # General: [0x59, subfunction, status_avail, {DTC_HB, DTC_MB, DTC_LB, status}...]
    # Each DTC is 4 bytes (3 byte DTC + 1 byte status)
    if len(resp) < 3:
        return dtcs, count

    payload = resp[3:]   # skip SID + subfunction + status_avail_mask
    i = 0
    while i + 3 <= len(payload):
        dtc_bytes = payload[i:i+3]
        status = payload[i+3] if i + 3 < len(payload) else 0
        dtc_code = (dtc_bytes[0] << 16) | (dtc_bytes[1] << 8) | dtc_bytes[2]
        dtcs.append(f"{dtc_code:06X}:{status:02X}")
        i += 4
        count += 1

    return dtcs, count


def _parse_kwp_dtc_response(resp: bytes):
    """Parse KWP2000 0x58 ReadDTCByStatus response.

    Response layout: [0x58, dtc_count, {DTC_HB, DTC_LB, status}...]
    Returns (dtcs: list[str], count: int).
    """
    dtcs = []
    count = 0
    if len(resp) < 2:
        return dtcs, count

    count = resp[1]
    payload = resp[2:]
    i = 0
    while i + 2 <= len(payload):
        dtc_bytes = payload[i:i+2]
        status = payload[i+2] if i + 2 < len(payload) else 0
        dtc_code = (dtc_bytes[0] << 8) | dtc_bytes[1]
        dtcs.append(f"{dtc_code:04X}:{status:02X}")
        i += 3

    return dtcs, count
