"""canre.uds.scanner -- Address scanner and full UDS/KWP2000 interrogation pipeline.

Scans a range of CAN request IDs for responding ECUs, then fully interrogates
each one: extended session, all F1xx DIDs, service probes, all 0x19 DTC
subfunctions, and KWP2000 0x18 DTC groups.

Public API
----------
UDSScanner(bus, scan_timeout=0.05, request_timeout=0.2, verbose=False,
           skip_kwp=False, skip_dtc=False)
    .scan_and_interrogate(start=0x600, end=0x7EF) -> ScanResult

Data classes
------------
DIDResult, DTCSubfunctionResult, KWPDTCResult, ServiceProbeResult,
ModuleInfo, ScanResult
"""

import logging
import time
from dataclasses import dataclass, field

from canre.uds.isotp import ISOTPChannel
from canre.uds.client import (
    UDSClient,
    UDSNegativeResponse,
    UDSTimeout,
    SESSION_DEFAULT,
    SESSION_EXTENDED,
    SAFE_PROBE_SERVICES,
    F1XX_DIDS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DTC subfunction table -- attempt ALL of these
# ---------------------------------------------------------------------------
DTC_SUBFUNCTIONS = [
    (0x01, b"\xFF",         "reportNumberOfDTCByStatusMask"),
    (0x02, b"\xFF",         "reportDTCByStatusMask"),
    (0x0A, b"",             "reportSupportedDTC"),
    (0x0B, b"",             "reportFirstTestFailedDTC"),
    (0x0C, b"",             "reportFirstConfirmedDTC"),
    (0x0D, b"",             "reportMostRecentTestFailedDTC"),
    (0x0E, b"",             "reportMostRecentConfirmedDTC"),
    (0x0F, b"\xFF",         "reportMirrorMemoryDTCByStatusMask"),
    (0x13, b"\xFF",         "reportEmissionsOBDDTCByStatusMask"),
    (0x19, b"",             "reportDTCWithPermanentStatus"),
]

# ---------------------------------------------------------------------------
# KWP2000 DTC group table
# ---------------------------------------------------------------------------
KWP_DTC_GROUPS = [
    (0xFF00, "all"),
    (0x0000, "powertrain"),
    (0x4000, "chassis"),
    (0x8000, "body"),
    (0xC000, "network"),
]

# TesterPresent interval (send every N requests)
_TP_INTERVAL = 5

# Service ID -> human-readable name (for probing)
_SVC_NAMES = {
    0x10: "DiagnosticSessionControl",
    0x22: "ReadDataByIdentifier",
    0x19: "ReadDTCInformation",
    0x27: "SecurityAccess",
    0x3E: "TesterPresent",
    0x1A: "ReadECUIdentification_KWP",
    0x18: "ReadDTCByStatus_KWP",
    0x21: "ReadDataByLocalIdentifier_KWP",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DIDResult:
    did: int
    did_name: str
    responded: bool
    nrc: "int | None"
    nrc_name: "str | None"
    raw: "str | None"          # hex string of raw data bytes
    value: "str | None"        # ASCII decode if printable, else hex


@dataclass
class DTCSubfunctionResult:
    subfunction: int
    subfunction_name: str
    responded: bool
    nrc: "int | None"
    nrc_name: "str | None"
    dtc_count: int
    dtcs: "list[str]"


@dataclass
class KWPDTCResult:
    group: int
    group_name: str
    responded: bool
    nrc: "int | None"
    nrc_name: "str | None"
    dtc_count: int
    dtcs: "list[str]"


@dataclass
class ServiceProbeResult:
    service_id: int
    service_name: str
    supported: bool
    nrc: "int | None"
    nrc_name: "str | None"


@dataclass
class ModuleInfo:
    request_id: int
    response_id: int
    is_nonstandard_response: bool   # True if response_id != request_id + 8
    session_extended: bool
    dids: "dict"                    # keyed by DID hex string e.g. "0xF190"
    service_probes: "dict"          # keyed by "0x10" etc.
    dtc_results: "dict"             # keyed by "0x02_reportDTCByStatusMask"
    kwp_dtc_results: "dict"         # keyed by "0xFF00_all"
    interrogation_start: float
    interrogation_end: float


@dataclass
class ScanResult:
    scan_start: float
    scan_end: float
    bitrate: int
    hardware_description: str
    scan_range_start: int
    scan_range_end: int
    modules: "list"
    nonstandard_rx_ids: "dict"      # {observed_rx_id: request_id}


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class UDSScanner:
    """Address scanner and full UDS/KWP2000 interrogation pipeline.

    Parameters
    ----------
    bus : can.BusABC
        Open python-can bus.
    scan_timeout : float
        Per-address timeout during address scan (seconds).  Default 0.05.
    request_timeout : float
        Per-request timeout during interrogation (seconds).  Default 0.2.
    verbose : bool
        Print per-module progress to stdout.
    skip_kwp : bool
        Skip KWP2000 0x18 DTC queries.
    skip_dtc : bool
        Skip all DTC queries (both 0x19 and 0x18).
    hardware_description : str
        Human-readable hardware label for the report.
    bitrate : int
        CAN bitrate (for the report only).
    """

    def __init__(
        self,
        bus,
        scan_timeout=0.05,
        request_timeout=0.2,
        verbose=False,
        skip_kwp=False,
        skip_dtc=False,
        hardware_description="unknown",
        bitrate=500000,
    ):
        self._bus = bus
        self._scan_timeout = scan_timeout
        self._request_timeout = request_timeout
        self._verbose = verbose
        self._skip_kwp = skip_kwp
        self._skip_dtc = skip_dtc
        self._hw_desc = hardware_description
        self._bitrate = bitrate

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def scan_and_interrogate(self, start=0x600, end=0x7EF):
        """Run the full scan + interrogation pipeline.

        1. Sniff baseline traffic to seed known-active IDs.
        2. Probe each address in [start, end] with DiagSessionCtrl default.
        3. Fully interrogate each responding module.

        Returns ScanResult.
        """
        scan_start = time.time()
        self._log(
            "Scanning 0x%03X..0x%03X (timeout=%d ms/addr)" % (
                start, end, int(self._scan_timeout * 1000)
            )
        )

        baseline = self._sniff_baseline(duration=0.2)
        self._log("Baseline: %d active IDs seen in 0.2 s" % len(baseline))

        found_modules = []           # list of (request_id, response_id, nonstandard)
        nonstandard_rx_ids = {}      # {observed_rx_id: request_id}

        total = end - start + 1
        for idx, req_id in enumerate(range(start, end + 1)):
            if self._verbose:
                print(
                    "\rScanning 0x%03X (%d/%d)..." % (req_id, idx + 1, total),
                    end="",
                    flush=True,
                )

            ch = ISOTPChannel(
                self._bus,
                tx_id=req_id,
                rx_id=req_id + 8,
                timeout=self._scan_timeout,
            )
            resp = ch.request(
                bytes([0x10, SESSION_DEFAULT]),
                timeout=self._scan_timeout,
            )

            # Check raw tap for non-standard response IDs
            extra = self._check_raw_tap(ch._raw_tap, req_id, req_id + 8, baseline)
            ch.close()

            if resp is not None:
                found_modules.append((req_id, req_id + 8, False))
                logger.debug("Found module at 0x%03X -> 0x%03X", req_id, req_id + 8)

            for obs_rx_id in extra:
                nonstandard_rx_ids[obs_rx_id] = req_id
                # Record as found module with nonstandard flag if not already found
                if not any(m[0] == req_id for m in found_modules):
                    found_modules.append((req_id, obs_rx_id, True))
                logger.debug(
                    "Non-standard response at 0x%03X for request 0x%03X",
                    obs_rx_id, req_id,
                )

        if self._verbose:
            print()  # newline after scan progress

        self._log("Scan complete: %d module(s) found" % len(found_modules))

        # Interrogate each found module
        modules = []
        for req_id, rx_id, nonstandard in found_modules:
            self._log(
                "Interrogating 0x%03X -> 0x%03X%s" % (
                    req_id, rx_id,
                    " (non-standard rx)" if nonstandard else "",
                )
            )
            info = self._interrogate(req_id, rx_id, nonstandard)
            modules.append(info)

        scan_end = time.time()
        return ScanResult(
            scan_start=scan_start,
            scan_end=scan_end,
            bitrate=self._bitrate,
            hardware_description=self._hw_desc,
            scan_range_start=start,
            scan_range_end=end,
            modules=modules,
            nonstandard_rx_ids=nonstandard_rx_ids,
        )

    # ------------------------------------------------------------------
    # Interrogation pipeline
    # ------------------------------------------------------------------

    def _interrogate(self, req_id, rx_id, nonstandard):
        """Fully interrogate one module and return a ModuleInfo."""
        t_start = time.time()
        ch = ISOTPChannel(
            self._bus,
            tx_id=req_id,
            rx_id=rx_id,
            timeout=self._request_timeout,
        )
        client = UDSClient(ch, timeout=self._request_timeout)

        # --- 1. Extended session ---
        extended_ok = False
        try:
            client.session_control(SESSION_EXTENDED)
            extended_ok = True
            self._log("  0x%03X: extended session OK" % req_id)
        except (UDSTimeout, UDSNegativeResponse) as e:
            self._log("  0x%03X: extended session failed (%s)" % (req_id, e))

        # --- 2. F1xx DID queries ---
        dids = {}
        for idx, (did, did_name) in enumerate(F1XX_DIDS.items()):
            if idx > 0 and idx % _TP_INTERVAL == 0:
                client.tester_present()
            result = client.read_data_by_id(did)
            dids["0x%04X" % did] = DIDResult(
                did=did,
                did_name=did_name,
                responded=result["responded"],
                nrc=result["nrc"],
                nrc_name=result["nrc_name"],
                raw=result["raw"],
                value=result["value"],
            )

        # --- 3. Service probes ---
        service_probes = {}
        for svc_id in sorted(SAFE_PROBE_SERVICES):
            try:
                result = client.probe_service(svc_id)
                service_probes["0x%02X" % svc_id] = ServiceProbeResult(
                    service_id=svc_id,
                    service_name=_SVC_NAMES.get(svc_id, "0x%02X" % svc_id),
                    supported=result["supported"],
                    nrc=result["nrc"],
                    nrc_name=result["nrc_name"],
                )
            except ValueError:
                pass   # unsafe service -- should not happen given SAFE_PROBE_SERVICES

        # --- 4. UDS 0x19 DTC subfunctions ---
        dtc_results = {}
        if not self._skip_dtc:
            client.tester_present()
            for idx, (subfn, extra_bytes, name) in enumerate(DTC_SUBFUNCTIONS):
                if idx > 0 and idx % _TP_INTERVAL == 0:
                    client.tester_present()
                result = client.read_dtc_subfunction(subfn, extra_bytes)
                key = "0x%02X_%s" % (subfn, name)
                dtc_results[key] = DTCSubfunctionResult(
                    subfunction=subfn,
                    subfunction_name=name,
                    responded=result["responded"],
                    nrc=result["nrc"],
                    nrc_name=result["nrc_name"],
                    dtc_count=result["dtc_count"],
                    dtcs=result["dtcs"],
                )

        # --- 5. KWP2000 0x18 DTC groups ---
        kwp_dtc_results = {}
        if not self._skip_dtc and not self._skip_kwp:
            client.tester_present()
            for idx, (group, group_name) in enumerate(KWP_DTC_GROUPS):
                if idx > 0 and idx % _TP_INTERVAL == 0:
                    client.tester_present()
                result = client.read_kwp_dtc(group=group)
                key = "0x%04X_%s" % (group, group_name)
                kwp_dtc_results[key] = KWPDTCResult(
                    group=group,
                    group_name=group_name,
                    responded=result["responded"],
                    nrc=result["nrc"],
                    nrc_name=result["nrc_name"],
                    dtc_count=result["dtc_count"],
                    dtcs=result["dtcs"],
                )

        # --- 6. Return to default session ---
        try:
            client.session_control(SESSION_DEFAULT)
        except (UDSTimeout, UDSNegativeResponse):
            pass

        ch.close()
        t_end = time.time()

        return ModuleInfo(
            request_id=req_id,
            response_id=rx_id,
            is_nonstandard_response=nonstandard,
            session_extended=extended_ok,
            dids=dids,
            service_probes=service_probes,
            dtc_results=dtc_results,
            kwp_dtc_results=kwp_dtc_results,
            interrogation_start=t_start,
            interrogation_end=t_end,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sniff_baseline(self, duration):
        """Passively sniff for `duration` seconds and return set of active IDs."""
        active = set()
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            msg = self._bus.recv(timeout=max(remaining, 0))
            if msg is not None:
                active.add(msg.arbitration_id)
        return active

    def _check_raw_tap(self, raw_tap, req_id, expected_rx_id, baseline):
        """Return set of unexpected response IDs seen in raw_tap.

        Filters out:
        - The expected rx_id (normal response)
        - IDs in the baseline (pre-existing traffic)
        - The req_id itself (echo)
        """
        unexpected = set()
        for arb_id, _ in raw_tap:
            if arb_id == expected_rx_id:
                continue
            if arb_id == req_id:
                continue
            if arb_id in baseline:
                continue
            unexpected.add(arb_id)
        return unexpected

    def _log(self, msg):
        logger.info(msg)
        if self._verbose:
            print(msg)
