# canre.uds -- UDS/KWP2000 Diagnostic Scanner API Reference

> **Source last modified:** 2026-03-15

The `canre.uds` package provides a full UDS (ISO 14229) and KWP2000 diagnostic
scanner built on top of `python-isotp` and `python-can`.  It is used by
`tools/uds_interrogator.py`.

---

## Package layout

```
canre/uds/
    __init__.py    -- re-exports all public classes
    isotp.py       -- ISOTPChannel: synchronous ISO 15765-2 transport
    client.py      -- UDSClient: UDS + KWP2000 service layer
    scanner.py     -- UDSScanner + result dataclasses
    uds.md         -- this file
```

---

## ISOTPChannel (`canre.uds.isotp`)

Wraps `python-isotp` TransportLayer in a synchronous polling model.
Supports python-isotp v1 and v2 API signatures.

### Constructor

```python
ISOTPChannel(bus, tx_id, rx_id, timeout=0.1, padding=True, extended_id=False)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `bus` | `can.BusABC` | Open python-can bus |
| `tx_id` | `int` | CAN arbitration ID for outgoing frames |
| `rx_id` | `int` | CAN arbitration ID for incoming frames |
| `timeout` | `float` | Default timeout in seconds |
| `padding` | `bool` | Pad outgoing frames to 8 bytes with 0xCC |
| `extended_id` | `bool` | Use 29-bit extended IDs |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `request(data, timeout=None)` | `bytes\|None` | Send and receive; None on timeout |
| `send(data)` | `None` | Enqueue payload for transmission |
| `receive(timeout=None)` | `bytes\|None` | Poll for incoming payload |
| `pump(duration=0.0)` | `list[bytes]` | Drain all payloads for `duration` seconds |
| `close()` | `None` | Release layer resources (does not close bus) |

### Raw tap

`channel._raw_tap` is a `list` of `(arbitration_id: int, data: bytes)` tuples
for every CAN frame seen by the rxfn callback.  It is cleared at the start of
each `request()` call.  `UDSScanner` reads this after each probe to detect
ECUs responding on non-standard IDs.

---

## UDSClient (`canre.uds.client`)

UDS and KWP2000 service layer.  Handles NRC 0x78 (ResponsePending) retries
automatically (up to 3 retries with 1 s extended timeout each).

### Constants

```python
SVC_SESSION_CTRL   = 0x10    SESSION_DEFAULT  = 0x01
SVC_SEC_ACCESS     = 0x27    SESSION_EXTENDED = 0x03
SVC_TESTER_PRESENT = 0x3E
SVC_READ_DATA      = 0x22
SVC_READ_DTC       = 0x19
SVC_KWP_READ_DTC   = 0x18
SVC_READ_ECU_ID    = 0x1A    # KWP2000

F1XX_DIDS          # dict of DID -> name for standard ECU identity DIDs
SAFE_PROBE_SERVICES # frozenset of service IDs safe to probe
```

### Exceptions

| Exception | When raised |
|-----------|-------------|
| `UDSNegativeResponse(service_id, nrc)` | ECU replied 0x7F |
| `UDSTimeout` | No response within timeout |
| `ISOTPError` | Malformed response frame |

`UDSNegativeResponse` has `.service_id`, `.nrc`, `.nrc_name` attributes.

### Constructor

```python
UDSClient(channel, timeout=0.2)
```

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `raw_request(data, timeout=None)` | `bytes` | Send bytes, return positive response; raises on error |
| `session_control(session_type=SESSION_DEFAULT)` | `dict` | 0x10 service |
| `tester_present(suppress_response=True)` | `None` | 0x3E keep-alive (0x80 subfunction) |
| `read_data_by_id(did)` | `dict` | 0x22 service; returns `{responded, nrc, nrc_name, raw, value}` |
| `read_dtc_subfunction(subfunction, extra=b'')` | `dict` | Generic 0x19 dispatcher; returns `{responded, nrc, nrc_name, dtc_count, dtcs, raw}` |
| `read_kwp_dtc(group=0xFF00, status_mask=0xFF)` | `dict` | 0x18 service; returns same shape |
| `probe_service(service_id)` | `dict` | Returns `{supported, nrc, nrc_name}`; raises `ValueError` for unsafe IDs |

**Safe services to probe:** 0x10, 0x22, 0x19, 0x27, 0x3E, 0x1A, 0x18, 0x21

**Never probed:** 0x11 (reset), 0x14 (clear DTC), 0x28, 0x2E (write),
0x31 (routine), 0x34-0x37 (transfer), 0x85 (DTC setting control)

---

## UDSScanner (`canre.uds.scanner`)

Full scan + interrogation pipeline.

### Constructor

```python
UDSScanner(bus, scan_timeout=0.05, request_timeout=0.2, verbose=False,
           skip_kwp=False, skip_dtc=False,
           hardware_description="unknown", bitrate=500000)
```

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `scan_and_interrogate(start=0x600, end=0x7EF)` | `ScanResult` | Full pipeline |

### Scan logic

1. Sniff 0.2 s baseline to seed known-active IDs.
2. For each address in `[start, end]`: send `[0x10, 0x01]` (DiagSessionCtrl default).
3. Record responses; check `_raw_tap` for non-standard response IDs.
4. For each responding module: run full interrogation pipeline.

Scan throughput: ~50 ms/address worst case = ~25 s for 0x600-0x7EF.

### Interrogation pipeline (per module)

1. Extended session (0x10 0x03)
2. All F1XX_DIDS via 0x22 (TesterPresent every 5 requests)
3. Probe all safe services
4. All 0x19 DTC subfunctions (TesterPresent every 5)
5. All 0x18 KWP DTC groups (TesterPresent every 5)
6. Return to default session (0x10 0x01)

### DTC subfunctions attempted

| Subfunction | Name |
|-------------|------|
| 0x01 | reportNumberOfDTCByStatusMask |
| 0x02 | reportDTCByStatusMask |
| 0x0A | reportSupportedDTC |
| 0x0B | reportFirstTestFailedDTC |
| 0x0C | reportFirstConfirmedDTC |
| 0x0D | reportMostRecentTestFailedDTC |
| 0x0E | reportMostRecentConfirmedDTC |
| 0x0F | reportMirrorMemoryDTCByStatusMask |
| 0x13 | reportEmissionsOBDDTCByStatusMask |
| 0x19 | reportDTCWithPermanentStatus |

### KWP2000 DTC groups

| Group | Name |
|-------|------|
| 0xFF00 | all |
| 0x0000 | powertrain |
| 0x4000 | chassis |
| 0x8000 | body |
| 0xC000 | network |

---

## Result dataclasses

### DIDResult

```python
@dataclass
class DIDResult:
    did: int
    did_name: str
    responded: bool
    nrc: int | None
    nrc_name: str | None
    raw: str | None      # hex string of data bytes
    value: str | None    # ASCII if printable, else hex
```

### DTCSubfunctionResult

```python
@dataclass
class DTCSubfunctionResult:
    subfunction: int
    subfunction_name: str
    responded: bool
    nrc: int | None
    nrc_name: str | None
    dtc_count: int
    dtcs: list[str]      # ["XXXXXX:SS", ...] where SS is status byte hex
```

### KWPDTCResult

```python
@dataclass
class KWPDTCResult:
    group: int
    group_name: str
    responded: bool
    nrc: int | None
    nrc_name: str | None
    dtc_count: int
    dtcs: list[str]      # ["XXXX:SS", ...] (2-byte KWP DTC codes)
```

### ServiceProbeResult

```python
@dataclass
class ServiceProbeResult:
    service_id: int
    service_name: str
    supported: bool
    nrc: int | None
    nrc_name: str | None
```

### ModuleInfo

```python
@dataclass
class ModuleInfo:
    request_id: int
    response_id: int
    is_nonstandard_response: bool
    session_extended: bool
    dids: dict             # {"0xF190": DIDResult, ...}
    service_probes: dict   # {"0x10": ServiceProbeResult, ...}
    dtc_results: dict      # {"0x02_reportDTCByStatusMask": DTCSubfunctionResult, ...}
    kwp_dtc_results: dict  # {"0xFF00_all": KWPDTCResult, ...}
    interrogation_start: float
    interrogation_end: float
```

### ScanResult

```python
@dataclass
class ScanResult:
    scan_start: float
    scan_end: float
    bitrate: int
    hardware_description: str
    scan_range_start: int
    scan_range_end: int
    modules: list[ModuleInfo]
    nonstandard_rx_ids: dict    # {observed_rx_id: request_id}
```

---

## Dependencies

- `isotp` (`pip install can-isotp`) -- ISO 15765-2 transport (package is `can-isotp`, module imports as `isotp`)
- `can` (`pip install python-can`) -- CAN hardware abstraction
- `canbench.live.receiver` -- interface detection (`detect_all_can_interfaces`); migrated to the can-tools repo, mirrored at the reverse-it root as `canbench/`
