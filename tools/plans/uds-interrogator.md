# UDS Interrogator Tool — Implementation Plan

> **NOTE:** This file lives in `tools/plans/uds-interrogator.md` per CLAUDE.md policy.

## Context

We need a tool that can plug a CAN dongle into a vehicle, scan all possible UDS module
addresses with no prior knowledge, and fully interrogate each one: ECU identity, service
support, and every possible DTC query (including subfunctions the module may not declare
as supported, and both UDS 0x19 and KWP2000 0x18 for older ECUs like those on the Coda).

Primary test vehicle: Coda (known modules, good for validation). Second target: Vtrux
(unknown, but SavvyCAN got a positive reply at the default address).

---

## Architecture Decision: Use `python-isotp`, write own service layer

- `python-isotp` handles ISO 15765-2 transport (SF/FF/CF/FC state machine) correctly.
  Writing this from scratch is error-prone. Reuse it.
- Do NOT use `python-udsoncan` — it lacks KWP2000 0x18 support and would require
  awkward subclassing for the scan loop.
- Write our own `canre/uds/client.py` on top of `python-isotp`. This gives full
  control over 0x18 service, NRC handling, and the aggressive DTC scan.
- Required pip dep: `python-isotp` (package name `isotp`).

---

## File Layout

```
canre/uds/
    __init__.py       # package exports
    isotp.py          # ISOTPChannel -- synchronous ISO 15765-2 transport
    client.py         # UDSClient -- UDS + KWP2000 service layer
    scanner.py        # UDSScanner + data classes (ModuleInfo, ScanResult, etc.)
    uds.md            # API reference doc

tools/
    uds_interrogator.py   # CLI entry point
    plans/
        uds-interrogator.md   # THIS PLAN
```

---

## Critical Files to Reuse

| What | File | Reuse specifically |
|------|------|-------------------|
| Hardware detection | `canre/live/receiver.py` | `detect_all_can_interfaces(bitrate, brands)` |
| Bus open pattern | `tools/can_logger.py` lines 238-248 | ixxat dict-unpack vs int channel |
| CLI arg conventions | `tools/can_logger.py` | `--bitrate`, `--brands` arg names/defaults |
| canre API names | `memory/MEMORY.md` | `parse_file` not `parse_log`; `arbitration_id` |

---

## Component: `canre/uds/isotp.py` -- `ISOTPChannel`

Wraps `python-isotp` TransportLayer in a synchronous polling model (no extra threads).

```python
class ISOTPChannel:
    def __init__(self, bus, tx_id, rx_id, timeout=0.1, padding=True): ...
    def request(self, data: bytes, timeout=None) -> bytes | None: ...
    def send(self, data: bytes) -> None: ...
    def receive(self, timeout=None) -> bytes | None: ...
    def pump(self, duration=0.0) -> list[bytes]: ...
    def close(self) -> None: ...
    # Internal: _raw_tap list -- all CAN frames seen via rxfn callback
    #           (used by scanner to detect non-standard response IDs)
```

**rxfn tap pattern** (key design): the isotp rxfn callback logs ALL received frames to
`self._raw_tap` before filtering to `rx_id`. Scanner reads `_raw_tap` after each probe
to detect ECUs that respond on an ID other than `tx_id + 8`.

**python-isotp v1 vs v2 API**: check `isotp.__version__` at init time and branch to the
correct `TransportLayer` constructor signature.

**Pump loop** (in `receive()`):
```python
deadline = time.monotonic() + timeout
while time.monotonic() < deadline:
    layer.process()
    payload = layer.recv()
    if payload is not None:
        return payload
    time.sleep(0.001)
return None
```

---

## Component: `canre/uds/client.py` -- `UDSClient`

### Key constants

```python
SVC_SESSION_CTRL  = 0x10   SVC_TESTER_PRESENT = 0x3E
SVC_READ_DATA     = 0x22   SVC_READ_DTC       = 0x19
SVC_KWP_READ_DTC  = 0x18   SVC_SEC_ACCESS     = 0x27
SVC_READ_ECU_ID   = 0x1A   # KWP2000 ECU identification

SESSION_DEFAULT   = 0x01   SESSION_EXTENDED   = 0x03

# F1xx DIDs to query (all read via 0x22):
F1XX_DIDS = {
    0xF186: 'active_diagnostic_session',
    0xF187: 'spare_part_number',
    0xF188: 'ecu_sw_number',
    0xF189: 'ecu_sw_version',
    0xF18A: 'system_supplier_id',
    0xF18B: 'ecu_mfg_date',
    0xF18C: 'ecu_serial_number',
    0xF190: 'vin',
    0xF191: 'ecu_hw_number',
    0xF192: 'supplier_hw_number',
    0xF193: 'supplier_hw_version',
    0xF194: 'supplier_sw_number',
    0xF195: 'supplier_sw_version',
    0xF197: 'system_name_or_engine_type',
}
```

### Exceptions

```python
class UDSNegativeResponse(Exception):
    service_id: int; nrc: int; nrc_name: str
class UDSTimeout(Exception): ...
class ISOTPError(Exception): ...
```

NRC 0x78 (ResponsePending) handling: in `raw_request()`, loop and re-receive up to 3
times with 1 s extended timeout when NRC 0x78 is returned.

### Key methods

```python
class UDSClient:
    def raw_request(self, data: bytes, timeout=None) -> bytes:
        # Raises UDSTimeout, UDSNegativeResponse, ISOTPError
    def session_control(self, session_type=SESSION_DEFAULT) -> dict: ...
    def tester_present(self, suppress_response=True) -> None: ...
    def read_data_by_id(self, did: int) -> dict: ...
    def read_dtc_subfunction(self, subfunction: int, extra: bytes = b'') -> dict:
        # Generic 0x19 dispatcher -- returns {'responded', 'nrc', 'dtcs', 'raw'}
    def read_kwp_dtc(self, group: int = 0xFF00, status_mask: int = 0xFF) -> dict:
        # 0x18 service -- request: [0x18, status_mask, group_HB, group_LB]
        # Positive response ID: 0x58
    def probe_service(self, service_id: int) -> dict:
        # Returns {'supported': bool, 'nrc': int|None}
        # Never probes write/clear/reset services
```

**Safe services to probe**: 0x10, 0x22, 0x19, 0x27 (seed only), 0x3E, 0x1A, 0x18, 0x21.
**Never probe**: 0x11 (reset), 0x14 (clear DTC), 0x28 (comms control), 0x2E (write),
0x31 (routine), 0x34-0x37 (transfer), 0x85 (DTC setting control).

---

## Component: `canre/uds/scanner.py` -- `UDSScanner`

### Data classes

```python
@dataclass class DIDResult: ...
@dataclass class DTCSubfunctionResult: ...
@dataclass class KWPDTCResult: ...
@dataclass class ServiceProbeResult: ...
@dataclass class ModuleInfo: ...
@dataclass class ScanResult: ...
```

### DTC subfunctions to attempt (all of them)

```python
DTC_SUBFUNCTIONS = [
    (0x01, b'\xFF', 'reportNumberOfDTCByStatusMask'),
    (0x02, b'\xFF', 'reportDTCByStatusMask'),
    (0x0A, b'',     'reportSupportedDTC'),
    (0x0B, b'',     'reportFirstTestFailedDTC'),
    (0x0C, b'',     'reportFirstConfirmedDTC'),
    (0x0D, b'',     'reportMostRecentTestFailedDTC'),
    (0x0E, b'',     'reportMostRecentConfirmedDTC'),
    (0x0F, b'\xFF', 'reportMirrorMemoryDTCByStatusMask'),
    (0x13, b'\xFF', 'reportEmissionsOBDDTCByStatusMask'),
    (0x19, b'',     'reportDTCWithPermanentStatus'),
]

KWP_DTC_GROUPS = [
    (0xFF00, 'all'),
    (0x0000, 'powertrain'),
    (0x4000, 'chassis'),
    (0x8000, 'body'),
    (0xC000, 'network'),
]
```

### Scan logic

Sequential scan. At 50 ms timeout x 496 addresses = ~25 s worst case.

### Interrogation pipeline (per module)

1. Extended session (0x10 0x03)
2. Query all F1XX_DIDS via 0x22 (send TesterPresent every 5 requests)
3. Probe safe services
4. All 0x19 DTC subfunctions (TesterPresent every 5)
5. All 0x18 KWP groups (TesterPresent every 5)
6. Return to default session (0x10 0x01)

---

## Component: `tools/uds_interrogator.py` -- CLI

Arguments: `--bitrate`, `--brands`, `--scan-range`, `--scan-timeout`, `--request-timeout`,
`--module`, `--output`, `--output-dir`, `--no-kwp`, `--no-dtc`, `--verbose/-v`, `--debug`

---

## Implementation Sequence

1. [x] Step 0: Copy plan to `tools/plans/uds-interrogator.md`
2. [x] `canre/uds/__init__.py`
3. [x] `canre/uds/isotp.py`
4. [x] `canre/uds/client.py`
5. [x] `canre/uds/scanner.py`
6. [x] `tools/uds_interrogator.py`
7. [x] `canre/uds/uds.md`
8. [x] Update `tools/tools.md`

---

## Verification Plan

1. **Unit smoke test** (no hardware): instantiate `ISOTPChannel` with a `can.interface.Bus`
   using `interface='virtual'`. Send a known ISOTP frame and verify loopback decode.

2. **Coda test** (known ground truth): run `uds_interrogator.py` on Coda Diag CAN.
   Verify: modules found at known addresses, ECU info matches known part numbers,
   DTCs match those visible in other diagnostic tools.

3. **Vtrux test**: run on Vtrux (address unknown). Tool should find the module that
   SavvyCAN found, report its capabilities and any DTCs present.

4. **KWP2000 path**: on Coda, verify that known 0x18-only modules show "responded"
   in `kwp_dtc_results` and "NOT SUPPORTED" (NRC 0x11) in `dtc_results` for 0x19.
