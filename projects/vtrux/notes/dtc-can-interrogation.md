# CAN Interrogation and DTC Notes

> Active CAN interrogation tools and DTC analysis for the Vtrux. The DTC lookup table
> (29-entry, extracted from binary) lives in **`epri-decompile.md`** under the 0x065B
> signal decoding section. This file builds on that base: interrogation tool proposals
> (Part 4) and live-log findings for 0x065B (4e).

---

## Part 4 -- CAN Interrogation Tools

**Goal:** Write tools to actively query the Vtrux CAN buses. Scope refined by EPRI Logger
decompile findings -- rather than sweeping blind, we implement EPRI's own query list first
(documented in `epri-decompile.md`).

### 4a. OBD-II ISO 15765-4 PID sweep on Vehicle and Powertrain buses

Test whether the VCM answers 0x7E8 on the Vehicle and PT buses (confirmed on OBD bus only
so far). Highest-priority unknown -- if yes, all standard OBD-II PIDs are accessible on the
buses the GoPoints were connected to.

- Send Mode 01 supported-PID queries (0x00, 0x20, 0x40, 0x60) at 0x7DF
- Parse supported-PID bitmask response
- Sweep supported PIDs, log raw responses
- Flag any Mode 22 (manufacturer-specific) PIDs returned

### 4b. UDS / Mode 22 DID sweep

The VCM or other PT bus modules may answer UDS ReadDataByIdentifier (0x22) for Via-specific
data identifiers. The INL study captured SOC, operating mode, and fuel data not available via
standard Mode 01 -- almost certainly accessed via Mode 22 or direct CAN.

- Target DID ranges common in GM/Via telematics (0xF400-0xF4FF, 0x4000-0x40FF)
- Scope by confirmed module addresses: VCM (0x7E0 likely), Bel Fuse charger, BorgWarner controller
- GoPoint extended mode can send arbitrary CAN frames including UDS requests

### 4c. J1939 PGN sweep on Powertrain bus

The extended-ID messages already seen on the PT bus (0x18FF??B3, 0x18FF??C0) are J1939-formatted.

- Parse existing PT bus logs interpreting 29-bit IDs as J1939 PGN/SA/DA fields
- Identify which PGNs are already broadcasting unsolicited
- Send J1939 request PGN (0xEA00) for PGNs not already broadcasting to see what responds

### 4d. MPR 3 CAN output identification (charging sessions)

The MPR 3 is a confirmed J1772-to-CAN bridge on the PT bus near the charger. Its output
messages should appear only during plug-in events.

- Cross-reference existing charge-session logs for IDs that appear only during charging and
  are not part of the known Bel Fuse charger message set
- Characterize timing relative to J1772 state transitions (plug-in, charge enable, plug-out)
- Identify encoding of pilot state and available current in candidate messages

---

### 4e. DTC interrogation via 0x065B -- findings (2026-03-27)

**0x065B is never seen in any log in the corpus**, including logs from deliberate hard-fault
events (vtruxinterlocktest.log, vtruxinterlocktest2.log, vtruxisolationtest.log,
vtruxisolationtestrecovery.log). In those sessions the full BMS fault cascade is clearly
visible on 0x410/0x420/0x644 -- contactors opened, HV bus dropped -- yet 0x065B never appeared.

**The EPRI app does not request DTCs.** The decompilation found no outgoing CAN frame
construction anywhere in ViaCANbusParser or ViaOBDParser. The app is purely a passive
receiver for 0x065B. The GoPoint dongles were in standard mode (auto-poll RPM via Mode 01 only);
no DTC request frames were ever issued on the bus.

**0x065B is almost certainly a stored DTC readout, not a live fault broadcast.** The most
likely behavior: the HCU transmits 0x065B only when a diagnostic tool explicitly requests it
(scan tool request, or possibly at key-on if a stored DTC is pending). The 29 DTC entries in
the lookup table cover faults that persist as stored codes, not transient real-time events.

**Correction (2026-03-30):** An earlier version of this note speculated that "interlock/isolation
trips do not set HCU-level DTCs." This is almost certainly wrong -- the DTC table explicitly
includes four HVIL codes (P0A0B ESS HVIL, P1A80 HVIL DCDC, P1A81 HVIL generator, P1A82 HVIL
traction). Intermittent HVIL faults are exactly the kind of condition a stored DTC system exists
to track. The absence of 0x065B in the interlock test logs is about the trigger mechanism (we
were passively logging, not issuing a diagnostic request), not about HVIL events being
undiagnosable. Additionally, vtruxinterlocktest2 keyed on with the interlock already tripped --
if 0x065B fires at key-on when DTCs are stored, it should have appeared there, but it still
didn't. This points to the trigger being an explicit diagnostic request, not a key-on broadcast.

**DTC code encoding -- standard SAE J2012 / OBD-II 2-byte format.** The 16-bit codes
follow the standard encoding used in all OBD-II-compliant ECUs:

| Upper nibble | Category | Source |
|---|---|---|
| 0x0-0x3 | Powertrain (P0-P3) | 0x0xxx = SAE generic; 0x1xxx = GM manufacturer-specific |
| 0xC-0xF | Network/Comm (U0-U3) | 0xCxxx = SAE generic; 0xDxxx = GM manufacturer-specific |

The P0Axxx and P0Dxxx codes (0x0A0B, 0x0A1F, 0x0A7B, 0x0AA6, 0x0D67) are in the SAE J2012
hybrid/EV DTC range (P0A00-P0DFF), standardized across manufacturers. Some are
well-known codes: P0A7B = battery state of charge too low; P0AA6 = HV isolation fault.

The U0xxx codes (0xC100, 0xC111, 0xC129, 0xC16B, 0xC296) are SAE standard lost-communication
DTCs: U0100 = lost comm ECM/PCM, U0111 = lost comm battery energy control module, U0129 = lost
comm brake system control module. These map directly to standard GM/SAE J2012 definitions and
would be readable by any OBD-II scan tool supporting the U-code range.

The P1xxx codes (0x1A20, 0x1A21, 0x1A80-0x1A82, 0x1AA0) and U1xxx codes (0xD300-0xD314) are
GM/Via manufacturer-specific but use the same 2-byte encoding convention.

**For the full 29-entry DTC string lookup table,** see `epri-decompile.md` under
`#### 0x065B -- HCU DTC code dispatcher`.

---

## Part 5 -- Live Interrogation Session (2026-03-30)

Tools: `projects/vtrux/tools/vtrux_dtc_interrogation.py`, `vtrux_uds_probe.py`
Logs: `notes/artifacts/dtc_interrogation_20260330_*.log`

### 5a. DLC connector and bus access mapping (confirmed)

Physical access to all three buses via the OBD-II DLC and the Via-added harness:

| Access point | Bus | DLC pins |
|---|---|---|
| Standard OBD-II DLC pins | **Vehicle bus** | Pin 6 (CAN-H) / Pin 14 (CAN-L) |
| Via harness P1 connector | **OBD bus** | Pin 10 (CAN-H) / Pin 2 (CAN-L) |
| Via harness P2 connector | **Powertrain bus** | Pin 1 (CAN-H) / Pin 9 (CAN-L) |

A standard scan tool on the stock DLC sees only the Vehicle bus and talks to the VCM diagnostic
gateway -- it cannot directly reach the ECM or TRAC MCU on the OBD bus. The Via harness exposes
the other two buses on non-standard pins. This corrects a prior note in projects/vtrux/README.md that stated the
OBD DLC was wired to the OBD bus.

### 5b. OBD-II DTC query results

Sent Mode 03 (stored), Mode 07 (pending), Mode 0A (permanent) at 0x7DF and 0x7E0 on all three
buses simultaneously. Results:

| Bus | Response | DTCs |
|---|---|---|
| Vehicle bus | 0x7E8 Mode 43/47/4A | No stored DTCs (clean) |
| OBD bus | 0x7E8 Mode 43/47/4A | No stored DTCs (clean) |
| PT bus | No response | Silent -- PT bus modules do not speak ISO 15765-4 at 0x7DF/0x7E0 |

VCM responds at 0x7E8 on both GM buses. PT bus is completely silent to OBD-II functional and
physical requests. **0x065B did not appear on the PT bus in response to any request on any bus.**

VCM uses `0xAA` padding in OBD-II responses (e.g. `02 43 00 AA AA AA AA AA`) -- standard GM
convention.

### 5c. UDS 0x19 and KWP2000 0x18 results

Sent UDS ReadDTCInformation (0x19/02 and 0x19/0A) and KWP2000 ReadDTCByStatus (0x18) at 0x7DF
and 0x7E0 on all buses:

- **Vehicle bus 0x7E8**: NRC `serviceNotSupported` for both 0x19 and 0x18 -- VCM explicitly
  rejects these protocols.
- **OBD bus 0x7E8**: Same -- NRC `serviceNotSupported`.
- **PT bus**: No response at 0x7DF/0x7E0. Two modules responded during the 0x7E0-0x7EF address
  sweep (see 5d).

### 5d. PT bus address sweep -- two unknown modules found

Swept all physical addresses 0x7E0-0x7EF on the PT bus with Mode 03 and UDS 0x19. Two modules
responded:

| Request addr | Response addr | Protocol | Response |
|---|---|---|---|
| 0x7E5 | 0x7ED | UDS 0x19 | NRC `serviceNotSupported` |
| 0x7E7 | 0x7EF | UDS 0x19 | NRC `serviceNotSupported` |

These are the only modules on any bus (besides the VCM at 0x7E0) that respond in the
0x7E0-0x7EF diagnostic address range. No equivalent modules found at 0x7E1-0x7EF on the OBD
or Vehicle buses.

### 5e. UDS probe of 0x7E5 and 0x7E7

Full UDS probe (TesterPresent, DSC, RDBI F190/F18C/F189/F187/F18A/F186, ReadDTC 0x19/01/02/0A):

**0x7E5 (response at 0x7ED):**
- TesterPresent: NRC `0x80` -- non-standard response, likely an older/pre-UDS protocol stack
  echoing the suppress-response bit. Not a standard UDS NRC.
- All other services: NRC `serviceNotSupported` across the board.
- Interpretation: probably running a legacy diagnostic protocol that incidentally responds at
  a UDS-range address. The GENE MCU (Dana TM4 CO150) is a candidate -- J1939-native hardware
  with a non-standard diagnostic interface.

**0x7E7 (response at 0x7EF):**
- TesterPresent: NRC `serviceNotSupported`
- DSC default session (0x10/01): **positive response** in first run; NRC `serviceNotSupported`
  in second run -- inconsistent, possibly state-dependent
- RDBI F190 (VIN), F187 (parts number), F186 (active session): NRC `requestOutOfRange` --
  module understands RDBI (0x22) but those specific DIDs are not implemented
- RDBI F18C/F189/F18A: NRC `serviceNotSupported`
- All ReadDTC 0x19 subfunctions: NRC `serviceNotSupported`
- Interpretation: a real UDS module with a limited service set. Understands DSC and RDBI but
  does not implement standard identification DIDs or DTC services. The TRAC MCU (also Dana TM4
  CO150) is a candidate. DID scan on 0x7E7 not yet attempted -- unknown which DIDs it does
  expose. **Does not expose DTCs via 0x19.**

### 5f. Safety note -- functional DSC broadcast on Vehicle bus

During the multi-bus sweep, DiagnosticSessionControl (0x10) was sent as a functional broadcast
(0x7DF) on the Vehicle bus. This caused the power steering to stop working and a "check 4WD"
warning to appear on the dash. Both cleared after a 12V restart -- nothing was damaged. The
EPS module and TCCM both live on the Vehicle bus and responded to the 0x7DF DSC command by
entering a diagnostic session, temporarily suspending normal operation.

**Going forward: do not send functional broadcasts on the Vehicle bus.** Use physical addressing
only (0x7E0 or other specific module addresses) when sending diagnostic requests on the Vehicle
bus.

### 5g. Log scan findings (2026-03-30, post-session)

A retrospective scan of all 5 DTC interrogation logs was run against the full log corpus
(291,892 frames across 5 sessions) using `notes/artifacts/log_response_scan.py`. Key findings:

**IDs seen in 0x700-0x7FF outside expected range:** 0x772, 0x778, 0x780, 0x785, 0x788.
All are normal Vehicle bus periodic broadcasts (listed in projects/vtrux/README.md), not diagnostic
responses. No hidden modules.

**VCM OBD-II clean:** `02 43 00 AA...` / `02 47 00 AA...` / `02 4A 00 AA...` confirm
zero stored, pending, and permanent DTCs via Mode 43/47/4A. VCM rejects UDS 0x19 and
KWP 0x18 with serviceNotSupported.

**DCDC is broadcasting J1939 DM1 spontaneously.** `0x18FECAB3` (DM1 active faults,
PGN=0xFECA, SA=0xB3) was seen in logs 194134 and 203759, multiple frames each. Data:
`00 FF 00 00 00 00` = lamp byte 0x00 (no lamps lit) + flash byte 0xFF + no active SPN
entries. Interpretation: DCDC reports no current active faults, but DM1 is being broadcast
periodically. This means the DCDC speaks J1939 diagnostic protocol natively. **DM2
(PGN 0xFECB = previously active faults) should be requestable and may reveal stored fault
history from charge failures.** No DM1 from charger (SA=0xC0) seen -- likely only active
when plugged in.

**0x065B:** Still no frames, including with non-zero DTC payload.

**Coverage gap:** 0x700-0x7DE (223 addresses) never queried.

### 5h. Current status and next steps

Protocol status as of 2026-03-30 post-analysis:
- OBD-II Mode 03/07/0A: VCM clean (0 DTCs); PT bus silent
- UDS 0x19: VCM rejects; 0x7E5 and 0x7E7 reject; PT bus modules at 0x7E0-0x7EF otherwise silent
- KWP2000 0x18: VCM rejects
- PT bus physical address sweep 0x7E0-0x7EF: only 0x7E5 and 0x7E7 respond, neither exposes DTCs
- J1939 DM1: DCDC broadcasts spontaneously (no active faults); not yet actively requested
- 0x700-0x7DE: never queried

**Tools updated (2026-03-30) to cover remaining candidates:**

`vtrux_dtc_interrogation.py` changes:
- Real-time response decoder extended from 0x7E8-0x7EF to full 0x700-0x7FF range
- J1939 DM1/DM2 real-time decoding added (extended-ID frames PGN 0xFECA/0xFECB)
- PT bus now includes: broad TesterPresent sweep 0x700-0x7DF + J1939 DM1/DM2 requests
  to DCDC (SA=0xB3), charger (SA=0xC0), global broadcast
- Vehicle bus functional broadcast (0x7DF) now guarded against (caused EPS incident)
- KWP2000 now includes Continental-style subfn variants (0x18 00 FF 00, 0x18 02 FF 00)
- Default log-time extended to 30s

`vtrux_uds_probe.py` changes:
- Fixed 0x78 response-pending handling: now discards and keeps waiting (was returning
  0x78 as final answer, potentially missing real response from slow modules like 0x7E7)
- Added `--sweep-broad`: sweeps 0x700-0x7DF with TesterPresent, checks offsets +1/+8/+0x10/+0x18
- Added `--j1939`: sends J1939 DM1/DM2 requests to DCDC and charger, decodes responses
- Added KWP2000 Continental-style probes to the standard probe sequence

**Recommended next session:**

1. `py -3.12 projects/vtrux/tools/vtrux_uds_probe.py --sweep-broad --j1939`
   -- Find any new modules in 0x700-0x7DF; request DCDC/charger DM2 fault history

2. `py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py`
   -- Full protocol sweep with all new capabilities; J1939 DM1/DM2 now decoded in real-time

3. **DID scan on 0x7E7** -- module understands RDBI (0x22) but rejects standard F1xx DIDs.
   Try GM/Via-specific DID ranges: 0x0100-0x01FF, 0x4000-0x40FF, 0xF400-0xF4FF.
   Can target with: `--targets 0x7E7` and add DID sweep to probe sequence.

4. **Deliberately trigger a stored DTC** -- truck currently clean. Unplug DCDC CAN connector
   briefly to set U0296 (lost Rx: BDC), then restart and run the full scan. If 0x065B still
   doesn't appear, the trigger is proprietary.

---

### 5i. Round 1 -- PT bus uds_probe (2026-03-30, live session)

Ran `vtrux_uds_probe.py --sweep-broad --j1939 --brands kvaser` with kvaser dongle on PT bus.
Bus 0 (kvaser ch0) confirmed as PT bus (7 PT anchors, 56 unique IDs).

**Broad sweep (0x700-0x7DF) -- 4 new modules found:**

| Addr | Resp addr | Note |
|------|-----------|------|
| 0x712 | 0x71A (+8) | TesterPresent OK |
| 0x716 | 0x71E (+8) | TesterPresent OK |
| 0x717 | 0x71F (+8) | TesterPresent OK |
| 0x7B0 | 0x7B8 (+8) | NRC conditionsNotCorrect (alive, not in default diag mode) |

**J1939 DM1/DM2:**
- DCDC (SA=0xB3) DM1: 114-byte TP response (17 TP.DT frames). Decoded as `lamps=no-lamps
  SPN0/FMI0(OC=0)` -- no active faults. Confirms DCDC is J1939-native.
- DCDC DM2: no response in 2s. May need longer timeout or dedicated TP reassembly.
- Charger (SA=0xC0) DM1/DM2: no response. Charger may only respond when plugged in.

**0x7E5 (known module):**
- UDS 0x19 and 0x22: serviceNotSupported for all subservices
- KWP 0x18 subfn=0x00: positive response `58 01 C1 00 24` = **DTC 0xC100 (U0100) status=0x24**
- KWP 0x18 subfn=0x02: subFunctionNotSupported

**0x7E7 (known module):**
- DSC default session: OK. Extended session: serviceNotSupported.
- RDBI F190/F189/F186: requestOutOfRange (supports RDBI service but not standard F1xx DIDs)
- No DTCs from UDS 0x19 or KWP 0x18

**0x712 (new):**
- DSC default + extended: OK
- RDBI F18C serial: `EE00001702` (ASCII)
- RDBI F187/F18A/F186: securityAccessDenied (locked behind security access)
- ReadDTC 0x19/02: **2 pending DTCs: 0xC02987 (st=0x20), 0x0AFB17 (st=0x20)**
  - Status 0x20 = confirmed test failed (pending, not yet MIL-on)
- KWP 0x18 both variants: securityAccessDenied
- Identity (component type) unknown

**0x716 (new):**
- DSC default: OK. Extended: subFunctionNotSupported.
- All RDBI DIDs: requestOutOfRange
- No DTCs via any protocol
- Module is alive and responds to TesterPresent but yields no useful data

**0x717 (new):**
- DSC default + extended: OK
- ReadDTC 0x19/01: "256 DTCs" (statusMask response -- may be mis-parsed count)
- ReadDTC 0x19/02: **3 DTCs: 0x111100 (st=0x0E), 0x222200 (st=0x06), 0x333300 (st=0x0E)**
- ReadDTC 0x19/0A also shows 0x444400 (st=0x00) and 0x555500 (st=0x00)
- All codes are obviously sequential placeholder values. This module either has test/debug
  firmware loaded or has uninitialized DTC table entries.

**0x7B0 (new -- Bel charger):**
- DSC default + extended: OK
- RDBI F18C serial: `00 02 82 06 00 00 01 6D` (8 binary bytes, not ASCII)
- ReadDTC 0x19/02: Large DTC list. First clean segment (before parser alignment loss):
  0xAC1000, 0xAC1001, 0xAEE007/08, 0xAFC00A-0E, 0xACCA00/01, 0xACCB00/01, 0xF00000,
  0xF6C000-0xF6C002, 0xF6C100/01, 0xF6C200, 0xF6C301-07, 0xF6C401-07, 0xF6C501-07,
  0xF6C601-07, 0xF6CF00-03, 0xFC1C00, 0xFC1E00-08, 0xFC1A00-02, 0xFC16FD -- all st=0x50
  (stored+confirmed). Parser then loses alignment at 0xAA 0xAA 0xAA TP padding bytes.
- ReadDTC 0x19/0A raw bytes are reliable and confirm the same DTC list above. Full decode
  pending proper 0xAA-stripping in the parser.
- KWP 0x18 both variants: conditionsNotCorrect (same as TesterPresent)

**Safety note -- power steering warning during PT bus scan:**
Power steering disable / 4x4 warning message appeared on the dash during this PT bus probe,
same as previously observed during a Vehicle bus functional broadcast. Since this scan did NOT
send 0x7DF (Vehicle bus guard is active), the trigger must be something on the PT bus --
possibly the VCM reacting to a DSC session or TesterPresent on the PT bus side. This message
is therefore not strictly a Vehicle bus artifact; it may be VCM-driven regardless of which
bus the diagnostic traffic lands on.

### 5j. Round 1 -- PT bus dtc_interrogation (2026-03-30)

Ran `vtrux_dtc_interrogation.py --brands kvaser` with kvaser on PT bus.
Log: `artifacts/dtc_interrogation_20260330_220742.log`
Console: `artifacts/dtc_interrogation_pt_bus_20260330_console.txt`

DCDC (SA=0xB3) broadcast DM1 every ~1s throughout the session: no active faults.

Actual Rx diagnostic responses (from physical address sweep):
- **0x7ED** (response addr for 0x7E5): NRC 0x80 for TesterPresent, NRC serviceNotSupported for UDS 0x19
- **0x7EF** (response addr for 0x7E7): NRC serviceNotSupported for UDS 0x19
- **0x7B8** (response addr for 0x7B0): NRC conditionsNotCorrect for TesterPresent
- Broad sweep responses from 0x712/0x716/0x717 captured in log file (raw Rx) but not cleanly
  decoded in console due to tool bug below

No OBD-II Mode 03/07/0A or UDS 0x19 DTC data from any address.

**Tool bug identified:** The real-time decoder processed Tx frames echoed back over CAN as if
they were Rx responses, flooding the console with false "UNKNOWN SID" entries (e.g. seeing
its own TesterPresent request 02 3E 00 at sweep addresses). Tx frames need to be filtered from
the drain queue before decoding. Raw log files are unaffected and still valid.

### 5k. Round 2 -- Vehicle bus dtc_interrogation (2026-03-30)

Ran `vtrux_dtc_interrogation.py --brands kvaser` with kvaser on Vehicle bus (DLC pins 6/14).
Log: `artifacts/dtc_interrogation_20260330_221357.log`
Console: `artifacts/dtc_interrogation_vehicle_bus_20260330_console.txt`

Bus correctly identified as Vehicle (88 unique IDs). Functional broadcast (0x7DF) correctly
suppressed by Vehicle bus guard.

No diagnostic responses from any physical address (0x7E0-0x7EF). Vehicle bus modules do not
respond to standard UDS/OBD-II diagnostic requests at these addresses.

Periodic broadcasts 0x772/0x778/0x785/0x788 were flagged as UNKNOWN SID by the decoder
(false positives -- these are known periodic GM frames that happen to fall in the 0x700-0x7FF
range, not diagnostic responses). Same Tx echo bug as above contributed additional noise.

### 5l. Round 3 -- OBD bus dtc_interrogation (2026-03-30)

Ran `vtrux_dtc_interrogation.py --brands kvaser` with kvaser on OBD bus (P1 harness pins 10/2).
Log: `artifacts/dtc_interrogation_20260330_221532.log`
Console: `artifacts/dtc_interrogation_obd_bus_20260330_console.txt`

Bus correctly identified as OBD (71 unique IDs). 0x772 also present on OBD bus (bridge/gateway).

**0x7E8 (VCM) responded:**
- Mode 43 stored DTCs: none
- Mode 47 pending DTCs: empty
- Mode 4A permanent DTCs: empty
- UDS 0x19 (all subservices): serviceNotSupported
- KWP 0x18 (all variants): serviceNotSupported

VCM is OBD-II only -- no UDS or KWP DTC protocol support. Truck is clean (no stored,
pending, or permanent OBD-II DTCs).

No other modules responded on the OBD bus.

### 5m. Session summary and outstanding items (2026-03-30)

**What was confirmed across the full 2026-03-30 session:**

| Bus | Tool | Result |
|-----|------|--------|
| PT | uds_probe --sweep-broad --j1939 | 4 new modules found (0x712/0x716/0x717/0x7B0); U0100 from 0x7E5; DCDC DM1 no active faults |
| PT | dtc_interrogation | DCDC DM1 spontaneous (no faults); no DTC data from query sweep |
| Vehicle | dtc_interrogation | No responses; 0x7DF guard worked correctly |
| OBD | dtc_interrogation | VCM (0x7E8) clean via OBD-II; rejects UDS/KWP |

**Known DTCs as of 2026-03-30:**
- 0x7E5 (PT bus, addr unknown): **U0100 (0xC100)** via KWP 0x18 Continental subfn=0x00, status=0x24
- 0x712 (PT bus, module unknown): **0xC02987** and **0x0AFB17**, both status=0x20 (confirmed-pending)
- 0x7B0 (PT bus, Bel charger): large list of stored DTCs (status=0x50) -- full list in 5i; parser alignment needs fix
- VCM (OBD bus, 0x7E8): clean

**Outstanding items as of 2026-03-30** -- superseded by section 6f (2026-04-05).

---

### 5n. DTC cross-reference -- standards and EPRI data (2026-03-30)

**U0100 (0xC100) from 0x7E5 -- direct EPRI match**

This code appears verbatim in the EPRI app's 29-entry DTC lookup table extracted from the
binary (`epri-decompile.md` §0x065B): `inAbstrCanEcm_u0100LostRx` = **"CAN lost Rx: ECM"**.
The HCU's CAN abstraction layer reports it has lost receive communication with the ECM.
The ECM lives on the OBD bus; 0x7E5 is on the PT bus -- this fault is almost certainly
chronic and expected: the PT bus module at 0x7E5 is configured to expect ECM heartbeats
that never arrive across the bus boundary. Status 0x24 = confirmedDTC + pendingDTC, not
MIL-on.

The other EPRI-table network faults (U0111 lost Rx BECM, U0129 lost Rx EBCM, U016B lost Rx
ACCM, U0296 lost Rx BDC) were not present -- those modules are communicating normally.

**0xC02987 and 0x0AFB17 from 0x712 -- no EPRI match**

0x712 is unknown to the EPRI system. Both are 3-byte proprietary UDS DTCs with status=0x20
(confirmedDTC, not MIL-on):
- 0xC02987: first two bytes = **U0029** (SAE J2012 "Lost Communication With Chassis Control
  Module"; GM-specific: Steering Column Control Module). Third byte 0x87 = GM sub-type.
- 0x0AFB17: first two bytes = **P0AFB** (SAE enhanced hybrid/EV range P0A00-P0FFF).
  Third byte 0x17 = sub-type.

A U-code (lost comms) paired with a P0Axxx (hybrid powertrain) from an unknown module with
serial `EE00001702` is consistent with a hybrid drivetrain controller (e.g. BorgWarner
transfer case or similar). The security lockout on RDBI F187/F18A/F186 is consistent with a
Tier-1 supplier ECU.

**0x7B0 (Bel charger) -- all proprietary, no standards/EPRI match**

Bel proprietary DTC namespace. EPRI monitored the Bel charger via J1939 PGNs
(0x18FFD6C0/D7C0/D8C0 for currents and voltages), not UDS DTCs, so no overlap.
The code prefixes suggest a structured internal fault taxonomy (AC input, power stage
subsystems, communication/firmware) but without Bel's DTC documentation the specific
meanings cannot be confirmed.

---

### 5o. Bel charger DTC parse -- parse_bel_dtcs.py (2026-03-30)

Script parsed the manually-transcribed 0x19/0A raw bytes from uds_probe output.
**456 DTCs across 17 fault category prefixes.** Status availability mask = 0x0F (Bel
proprietary -- actual status bytes observed are 0x50/0x2F/0x00, which do not strictly
align to this mask; Bel likely uses a non-standard encoding).

**Status codes observed:**
- `0x50` -- the vast majority; Bel "supported/stored" state
- `0x00` -- supported but never triggered (or not applicable in this config)
- `0x2F` -- only 2 DTCs: **0xFBB6E4** and **0xFC16F2**; only faults with a distinct
  "previously-active, now-cleared" status

**Structural breakdown by prefix category:**

| Prefix | Count | Notable pattern |
|--------|-------|----------------|
| 0xACxx | 12 | AC10, ACCA, ACCB, AC60 sub-groups |
| 0xAExx | 9 | AEE0 00-08; first 7 have status=0x00 (never triggered) |
| 0xAFxx | 5 | AFC0 0A-0E |
| 0xCCxx | 65 | CC10-CC70 (7 groups) x sub-codes 00-08; CCF1 x 2 |
| 0xDAxx | 96 | DA10 00-17 (24 channels) x sub-codes 00-03 |
| 0xDCxx | 2 | DC00 00-01 |
| 0xDDxx | 14 | DD00 00-06 x sub-codes 00-01 (7 groups x 2) |
| 0xDExx | 60 | DE10 00-0A (11 ch) x 4 + DEE0 06 + DE3DC/DE3FE pairs x 5 |
| 0xF0xx | 5 | F000 + F0E0 00-03 |
| 0xF1xx | 6 | F111 00-02, F112 00-02 |
| 0xF6xx | 43 | F6C0-F6C6 (7 groups), F6CF, F6D1, F6D2 |
| 0xF7xx | 1 | F700 status=0x00 |
| 0xF8xx | 2 | F800 00/01; F80000 status=0x00, F80001 stored |
| 0xF9xx | 1 | F900 |
| 0xFAxx | 6 | FAC0 00-02 appears twice (repeated group in raw response) |
| 0xFBxx | 92 | FBB6C/D/E sub-groups; FBBC/FBBE/FBBD each with 24 sub-codes (01-24); FBC, FBE |
| 0xFCxx | 37 | FC1C, FC1E (9), FC1A, FC16, FC1F, FCB, FCF, FC21, FC22, FCA |

**Key structural patterns:**
- `0xCCxx`: 7 groups (CC10-CC70) x 9 sub-codes each = highly regular. Likely 7 subsystems
  or phases, each with 9 fault types.
- `0xDAxx`: 24 channels (indices 00-17) x 4 sub-codes = exhaustive channel-fault matrix.
- `0xFBBCxx / 0xFBBExx / 0xFBBDxx`: each group has exactly 24 sub-codes (01-24). Three
  parallel groups of 24.
- `0xDExx + 0xDAxx`: similar channel-indexed structures with different prefixes -- may
  represent different subsystem layers (power stage vs. input monitoring).

**Three 0x2F faults (previously active, now cleared) -- updated 2026-04-05:**
- `0xFBB6E4` -- in the FBB6E sub-group (alongside FBB6E0-3, EA, EB which are stored+confirmed)
- `0xFC16F2` -- in the FC16 sub-group (alongside FC16F1/F3/F4/F5/F6 which are stored+confirmed,
  and FC16FD which is also stored+confirmed)
- `0xF90000` -- sole entry in the 0xF9xx prefix group; this code has status=0x2F while
  0xF80000 has status=0x00 (never triggered) and 0xF80001 has status=0x50 (stored).
  Discovered in uds_probe re-run 2026-04-05; the 2026-03-30 parse missed it because the
  0x19/0A raw bytes were manually transcribed with an error at that position.

These are the only faults that have ever been active and subsequently cleared. All other
stored+confirmed (0x50) faults appear to represent the module's supported fault inventory
rather than active fault history -- the Bel appears to use 0x50 as "this DTC type is
implemented" rather than "this fault has fired."

---

## Part 6 -- Session 2026-04-05

Dongles: kvaser on PT bus (Via P2 pins 1/9), PEAK on Vehicle bus (DLC pins 6/14). OBD bus not connected.

Logs: `artifacts/dtc_interrogation_20260405_104256.log`

Tools run:
1. `vtrux_uds_probe.py --sweep-broad --j1939 --brands kvaser`
2. `vtrux_dtc_interrogation.py` (both dongles)
3. `vtrux_uds_probe.py --targets 0x7E7 0x716 --did-scan --brands kvaser` (extended 0x0100-0x01FF)
4. `vtrux_uds_probe.py --targets 0x716 --did-scan --brands kvaser` (full output capture)

### 6a. PT bus module state -- no changes from 2026-03-30

All four modules (0x712, 0x716, 0x717, 0x7B0) and both known modules (0x7E5, 0x7E7) confirmed
present with same responses. No new modules found in broad sweep. DCDC DM1 broadcasting
clean (no active faults) at ~1s cadence throughout all sessions.

DCDC DM2 (PGN 0xFECB): still no response at 5s timeout. DCDC does not implement DM2.
Charger (SA=0xC0): still silent; not plugged in.

VCM (0x7E8) on Vehicle bus: clean (Mode 43/47/4A all empty). 0x065B still absent.

0x7E5: U0100 still stored (status=0x24) via KWP Continental subfn=0x00.
0x712: 0xC02987 + 0x0AFB17 still stored (status=0x20).

### 6b. Bel charger 0x7B0 -- third previously-cleared DTC

Full 0x19/02 re-read confirms a third 0x2F fault: **0xF90000**. The 0x19/0A re-read
confirms 0xF90000 is the sole entry in the 0xF9xx prefix group with status=0x2F.
Section 5o updated accordingly.

### 6c. DID scan on 0x7E7 -- 0x0100-0x01FF (GM/Via ranges)

19 hits across two separate scan runs (run 1: 0x0100-0x013F, run 2: 0x0100-0x01FF).
A subset of DIDs responded inconsistently between the two runs -- some addresses that
returned data in run 1 were silent in run 2, and vice versa. This suggests the module
has state-dependent or dynamically-indexed DID availability, or a time-varying internal
pointer. Only DIDs that responded in BOTH runs are treated as stable.

**Stable DIDs (responded in both runs with same or close values):**

| DID | Raw bytes (run 2) | Notes |
|-----|-------------------|-------|
| 0x0116 | `03 AB` (run1: `02 9D`) | Incrementing counter: 669 -> 939 over ~15 min |
| 0x0118 | `03 9E 44 52` (run1: `03 9E 43 43`) | Bytes 0-1 fixed `03 9E`=926; bytes 2-3 vary |
| 0x011F | `00 0A CC D8` | = 707,800; stable across both runs |
| 0x0121 | `00 00 00 00` | Zero both runs |
| 0x0126 | `00 1C ED B0` | = 1,896,880; stable across both runs |
| 0x0128 | `00 00 00 00` | Zero both runs |

**Run-2-only DIDs (0x0140-0x01FF range, first time accessed):**

| DID | Raw bytes | Notes |
|-----|-----------|-------|
| 0x0141 | `00 0E 86 9C` | = 952,988 |
| 0x0144 | `02 6D 7D 5C` | = 40,009,052 (large counter) |
| 0x0146 | `00 1C 80 66` | = 1,867,878 |
| 0x0151 | `00 04 D1 89` | = 315,785 |
| 0x0153 | `00 00 AC FF` | = 44,287 |
| 0x0158 | `00 04 24 88` | = 271,496 |
| 0x015A | `00 07 FB 4B` | = 522,059 |

**ASCII DIDs (state-dependent, not stable):**

DID 0x0105 (`_rC_`), 0x0106 (`03_2`), 0x0107 (`3_fr`) appeared across the two runs at
adjacent addresses. These appear to be fragments of a software version or build string
split across consecutive DIDs. The exact DID address where each fragment lands shifts
between runs, suggesting an indexed/relative DID namespace.

No hits in 0x0200-0x021F, 0x4000-0x403F, or 0xF400-0xF43F ranges.

### 6d. DID scan on 0x716 -- 0x0100-0x01FF

Only 4 hits, all in 0x0100-0x0103. No hits anywhere else in the scanned ranges.

| DID | Raw bytes | Notes |
|-----|-----------|-------|
| 0x0100 | `00 14 00 00 00 00 00 00 00 00` | 10-byte response; 0x14=20 in first word |
| 0x0101 | `3A 39 00 02  3A 38 00 02  39 39 00 03  3B 38 00 02  39 39 00 02  3A 35 00 02` | 24 bytes -- 6 groups of 4 bytes. Each group: `[XX][YY][00][02 or 03]`. XX/YY values 0x35-0x3B (53-59 decimal). |
| 0x0102 | `38 36 00 3C 00 36 36 36 3B 33 91` | 11 bytes; similar byte range |
| 0x0103 | `00 01 00 19 96 00 00 00 00 00` | 10 bytes; 0x1996=6550 in bytes 3-4 |

DID 0x0101 returns 24 bytes structured as 6 groups of 4: [B0 B1 00 ZZ] where ZZ is
0x02 or 0x03 (status/flag, uncharacterized). B0/B1 values span 0x35-0x3C (53-60
decimal). Identity of 0x716 not yet confirmed.

### 6e. 0x065B investigation closed (2026-04-05)

KWP Continental subfn=0x00 request sent to 0x7E5 three times with 8s watch windows
each; 0x065B never appeared. Combined with the full corpus search finding zero 0x065B
frames across all logs including normal operation and deliberate fault events, the
conclusion is that 0x065B either requires a Via-proprietary trigger not yet identified,
or the EPRI app's 29-entry DTC lookup table was coded for a feature that was never
active in any captured session. Further pursuit is low priority.

### 6f. Outstanding items (updated 2026-04-05)

Items resolved this session:
- Tx echo bug in decoder: already fixed before session
- DCDC DM2: confirmed no response even at 5s -- DCDC does not implement DM2. Closed.
- DID scan on 0x7E7 and 0x716: done (sections 6c, 6d)
- PCAN driver: installed and confirmed working (Vehicle bus identified correctly)
- 0x065B trigger: closed (section 6e)

Items remaining: superseded by section 7f (2026-04-17).

---

## Part 7 -- Session 2026-04-17

Tools: an HCU probe tool (internal-only), `projects/vtrux/notes/artifacts/identify_obd_module.py`, `projects/vtrux/notes/artifacts/pt_bus_functional_broadcast.py`

Dongles: ixxat on OBD bus (Via P1 pins 10/2), kvaser on PT bus (Via P2 pins 1/9), PCAN on Vehicle bus (DLC pins 6/14).

**Power steering did not trigger this session.** In prior sessions diagnostic traffic caused EPS disable + 4WD warning. The root cause was never confirmed; this session ran the same traffic patterns (including functional broadcast on PT bus and DSC requests on Vehicle bus) without triggering it.

### 7a. GM ECM confirmed at 0x7E0 -- not the Woodward HCU

Prior sessions labelled the module at 0x7E0/0x7E8 as "VCM" without verifying which ECU it was. This session confirmed it is the **GM ECM (LV3 engine controller)**, not the Woodward HCU:

- **Mode 09 ECU Name**: `ECM-EngineControl` (ASCII, 20 bytes)
- **VIN**: `3GCUKPEH2EG488714` (standard GM VIN, first digit 3 = Mexico, G = GM)
- **Calibration IDs** (8 entries, all GM-format part numbers):
  `12663390`, `12660319`, `12660131`, `12625016`, `12642480`, `12656298`, `12643728`, `12659513`
- **Mode 01 engine PIDs** all respond with live engine data:
  - RPM = 0.0 (engine off, ignition on)
  - Coolant = 22°C
  - Throttle = 31.8%
  - MAF = 0.0, intake air temp responding
- **Mode 09 subfn 0x08** (In-Use Performance Tracking): responded -- a GM-specific legislated subfunction not implemented by Woodward MotoHawk
- **Security Access** 0x27 levels 1 and 3: both return seed `0x462A`
- **DSC extended** (0x10/03): accepted, returns subfn=0x00 (non-standard GM response format)
- **UDS 0x19, RDBI F1xx, 0x85, 0x31, KWP 0x18**: all rejected

The GM ECM bridges OBD and Vehicle buses -- identical responses at 0x7E8 on both. This explains why all prior UDS 0x19 attempts on 0x7E0 failed: we were querying the GM ECM, which is OBD-II only.

### 7b. Woodward HCU diagnostic endpoint -- not found

A new tool (internal-only) was written to probe all Woodward ISO 15765 MotoHawk services (Mode 09, 0x10, 0x22, 0x19, 0x27, 0x85, 0x31, 0x28, 0x3E). The HCU was searched systematically:

| Method | Buses covered | Result |
|--------|--------------|--------|
| Targeted probe at 0x7E0 | OBD, Vehicle, PT | OBD/Vehicle = GM ECM; PT = silent |
| Targeted probe at 0x7E5, 0x7E7, 0x712 | PT | Same as prior sessions (see below); 0x712 silent |
| Broad TesterPresent + DSC sweep 0x700-0x7DF | Vehicle | No real modules (two false positives from 0x772/0x785 periodic broadcasts) |
| Functional broadcast 0x7DF with TP + DSC + DSC-ext | PT | Only 0x7ED (0x7E5) responded |

**The Woodward HCU does not surface to any standard UDS/OBD discovery method on any bus.**

Likely explanations (not yet resolved):
1. The Woodward MotoHawk ISO 15765 blockset is deployed with TesterPresent disabled or responding with subFunctionNotSupported -- meaning sweep-based discovery won't find it even if it's alive.
2. The HCU is reachable only through GM ECM gateway extended addressing (not yet attempted).
3. Via configured the HCU with no interactive diagnostic endpoint; 0x065B broadcast is the only diagnostic output.

### 7c. PT bus 0x7E5 -- unchanged

KWP Continental subfn=0x00 still returns `58 01 C1 00 24` = U0100 (lost comm ECM) status=0x24.
Security Access 0x27 level 1 seed: `0xCD3E`. All UDS services rejected.

### 7d. PT bus 0x7E7 -- state-dependent, likely TRAC MCU

DID scan confirmed 26 hits in 0x0100-0x01FF range, same DIDs as 2026-04-05 with slightly incremented counter values. Notable values:

| DID | Value | Notes |
|-----|-------|-------|
| 0x0105 | `_rC_` (ASCII) | Build string fragment |
| 0x0107 | `3_fr` (ASCII) | Build string fragment |
| 0x0140 | 10,145,778 | Large counter (~2,818 hrs if seconds) |
| 0x0141 | 952,988 | Matches April 5 value |
| 0x0146 | 1,867,878 | Matches April 5 value |
| 0x0134 | 8 | Small constant |
| 0x0136 | 9 | Small constant |

DSC default returned `serviceNotSupported` this run (previously returned `DSC OK`). State-dependent inconsistency persists -- module behaviour depends on vehicle operating state. Counter values suggest odometer/operating-time style data consistent with a drivetrain controller (TRAC MCU candidate).

### 7e. PT bus 0x712 -- silent this session

No response to any probe. Was responsive on 2026-03-30. Vehicle or drivetrain state dependency suspected.

### 7f. Outstanding items (updated 2026-04-17)

Items resolved this session:
- GM ECM at 0x7E0 confirmed and characterised (section 7a)
- Vehicle bus broad diagnostic sweep completed (section 7b)
- PT bus functional broadcast 0x7DF attempted (section 7b)
- Power steering trigger: did NOT fire this session -- root cause still unconfirmed but less reproducible than previously assumed

Items remaining:
1. **Woodward HCU diagnostic endpoint** -- not found. Next candidate: GM ECM gateway extended addressing (sub-address routing). Alternatively, accept that no interactive UDS endpoint exists.

2. **Identify modules 0x712, 0x716, 0x717** -- 0x712 silent this session. Serial `EE00001702` on 0x712 (when responsive) may be searchable. 0x717 placeholder DTCs suggest test/debug firmware.

3. **Live logging during fault events** -- three previously-cleared Bel charger faults (0xFBB6E4, 0xFC16F2, 0xF90000) are candidates to correlate against a known charge failure event.
