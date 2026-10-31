# Coda Gateway ECU — Firmware Decompile Notes

## Binary Provenance

| Item | Value |
|------|-------|
| Source log | `projects/coda/logs/flash/coda_gateway_flash.log` |
| Capture date | 2026-04-25 |
| Tool | Omitec scanner, BUSMASTER 500 kbps |
| Extracted binary | `projects/coda/notes/gateway/coda_gateway.bin` |
| Binary size | 90,112 bytes (0x16000) |

## UDS Flash Session Summary

- **Tester**: 0x710 (Omitec scanner)
- **ECU**: 0x718 (Gateway)
- **Session**: DiagnosticSessionControl → Programming (0x02)
- **SecurityAccess**: Level 0x03/0x04, seed/key challenge
- **RequestDownload**: address 0x00020000, size 0x16000 (uncompressed, no encryption)
- **Transfer**: 358 blocks × (up to 252 data bytes) = 90,112 bytes exact
- **TransferExit response**: `77 00 00 35 39` (checksum/status bytes)

## Architecture

| Property | Value |
|----------|-------|
| Architecture | ARM32 classic (ARM7TDMI-S family) |
| Endian | Little-endian |
| Linked base address | **0x00000000** |
| Flash storage address | 0x00020000 (bootloader stores image here) |
| SRAM | 0x40000000 (inferred from stack pointer value 0x40002910) |
| MCU family | NXP LPC2xxx or ST STR7xx (both ARM7TDMI-S with SRAM at 0x40000000) |
| Ghidra language | ARM:LE:32:v8 |

The RequestDownload address (0x20000) is where the bootloader writes the image in flash. All internal code addresses use base 0x0000 — the bootloader remaps the vector table to 0x0000 at runtime before handing off to the application.

## Exception Vector Table (offset 0x0000)

All reset/undef/swi/abort vectors use `LDR PC, [PC, #0x18]` (0xE59FF018). IRQ/FIQ use `LDR PC, [PC, #0x14]` (0xE59FF014). The reserved slot (offset 0x14) holds value `0xB8A06F60` — likely a module ID or version signature.

Jump table (offsets 0x20–0x3F, loaded by vector LDRs):

| Vector | Target Address | Name |
|--------|---------------|------|
| Reset | 0x0000A230 | reset_handler |
| Undefined | 0x0000A29C | undef_handler |
| SWI | 0x0000A2A0 | swi_handler |
| Prefetch Abort | 0x0000A2A4 | prefabort_handler |
| Data Abort | 0x0000A2A8 | dataabort_handler |
| IRQ | 0x0000A2AC | irq_handler |
| FIQ/Reserved | 0x00016680 | fiq_handler |

## Startup Code (offset 0x0040)

Classic ARM multi-mode stack initialization: reads CPSR, clears mode bits, ORRs each mode ID (UND=0x1B, ABT=0x17, IRQ=0x12, FIQ=0x11, SVC=0x13), writes CPSR, loads SP from PC-relative literal pool. This confirms ARM (not Cortex-M, which doesn't do mode-switching startup).

## Known Strings

| Offset | String | Notes |
|--------|--------|-------|
| 0xEAEC | `UNDEFINED ` | Fault/error message |
| 0xEAF8 | `NOT DEFINED   ` | Fault/error message |
| 0xEB08 | `%5d_%d%d%02d` | Format string |
| 0xEB18 | `NOT DEFINED      ` | Fault/error message |
| 0xEB2C | `UNKNOWN   ` | Fault/error message |
| 0xF004 | `AK21080200    ` | Part number |
| 0xF014 | `0000000000    ` | Software revision (all zeros) |
| 0xF02C | `718       ` | CAN node ID (0x718 = gateway) |
| 0xF038 | `ABCDEFGHI12345678` | Test/init string |
| 0xF34C | `0123456789abcdef0123456789ABCDEF(null)` | Hex table + null literal |

The part number `AK21080200` and node ID `718` confirm this is the gateway ECU firmware.

## Ghidra Project

- Project: `projects/coda/notes/artifacts/ghidra-project/coda_gateway`
- Runner: `projects/coda/notes/artifacts/run-ghidra-gateway.bat`
- Export script: `projects/coda/notes/artifacts/GatewayExport.java`
- Decompile output (when generated): `projects/coda/notes/artifacts/coda_gateway_decompile.c`

---

## Analysis Goals

### Goal 1: CAN Bus ID Table
Find where CAN message IDs are stored in the firmware and trace how messages are dispatched/processed. Use known Coda CAN IDs from the DBC as search anchors.

**Status: Complete** — table found at 0xF060–0xF2C8, 77 × 8-byte records (not 88; 77 × 8 = 616 = 0x268 bytes), four groups (sentinel, bus A, bus B, UDS ECU pairs). B3/B4 fields fully decoded. See Findings section.

### Goal 2: DID Table → CAN Bus Mapping
Find the DID dispatch table and trace how DIDs are resolved to CAN signals. The flash log shows DID 0x6401 being polled (`22 64 01` / `62 64 01 03`) — use this as an anchor.

**Status: Complete** — DID dispatch found in literal pool at 0x01A10–0x01BB8. See Findings section.

---

## Options to Move Forward

### Option A: Decode CAN ID Table B3/B4 Fields (highest leverage, pure data analysis)

**Status: Complete.** See Finding 6.

Each 8-byte CAN ID table record has two undecoded bytes (B3/B4). Given B0–B1 = CAN ID, B2 = bus/direction, these remaining bytes likely encode something per-message — candidate interpretations include a payload byte offset, a signal category flag, or a DLC hint. If they encode byte positions, this yields signal extraction hints for every message in the DBC for free.

Approach: write a script that reads all 88 records, groups by B2, and cross-references B3/B4 values against known signal byte positions in the Coda DBC to see if a pattern matches.

### Option B: Trace CAN Signal Extraction Chain (maps CAN bytes → SRAM)

**Status: Partially complete — blocked at bootloader boundary. See Finding 7.**

The CAN processing pipeline was traced: IRQ → `FUN_000066a0` (enqueue to circular buffer) → `FUN_0000869c` main loop dequeues via `FUN_00006854` → scans CAN ID table → dispatches via `FUN_00007e10` (per-slot signal extraction) + `FUN_00008598` (bus bridging/forwarding). A 22-entry dispatch table at binary offset 0x84EC holds SRAM address pairs for the 22 signal slots.

Blocked: `FUN_00007e10`'s switch-case handlers (cases 1-4) branch to code at address 0x19060+, which is in the bootloader flash region above the 90 KB application binary. Ghidra marks these as "bad instruction data." The byte extraction logic — which CAN payload byte → which SRAM slot — lives in the bootloader, not the application.

**Note:** `FUN_000074b0` (0x74B0) was identified as a **GPIO debouncer**, not a CAN signal collection function. It calls `FUN_00003598(port, pin)` to read GPIO bits, debounces 8 boolean I/O states. It does not process CAN frames.

Remaining options: (1) extract bootloader flash region 0x16000–0x20000 via separate UDS session or JTAG; (2) read DID handler stubs (Option C) to anchor known SRAM addresses to DID semantics.

### Option C: DID Response Code as Signal Anchors (cross-check / ground truth)

The DID handler stubs at 0xA100–0xA22F read specific SRAM cells and assemble UDS response frames. Because DID semantics are known (0xF190 = VIN, 0xF191 = ECU HW number, etc.), each handler gives a ground-truth link: `DID meaning → SRAM address → CAN message source`. This can cross-validate whatever B3/B4 and the signal loop reveal.

Approach: for each DID in the literal pool, read the handler stub to find which SRAM address it copies into the response buffer, then trace that SRAM address back through FUN_000074b0 to find the originating CAN message and byte offset.

---

## MCU Identification

**NXP LPC2xxx** (ARM7TDMI-S family) confirmed by multiple independent indicators:

| Indicator | Evidence |
|-----------|----------|
| SRAM base | Stack pointers at 0x40002910, 0x40002810, 0x40002710 → SRAM at 0x40000000 |
| ROM API | `FUN_00004ab4` calls `(*(code *)0x7FFFFFF1)(...)` — NXP LPC2xxx CAN/peripheral ROM API |
| Boot ROM address | `0x7FFFFFF1` is the NXP LPC2xxx ROM API Thumb entry point (fixed for entire LPC2xxx family) |
| Startup | ARM multi-mode stack init (UND/ABT/IRQ/FIQ/SVC) — classic ARM7TDMI-S pattern |

The ROM API call at `0x7FFFFFF1` is the definitive NXP LPC2xxx fingerprint — no other vendor places a ROM API at that exact address. Specific sub-variant (LPC21xx/22xx/23xx/24xx) not yet confirmed; 6 CAN channel slots probed in `FUN_00004ab4` but LPC2xxx CAN count varies by part.

---

## Findings

### Finding 1: CAN Bus ID Table

Located at binary offset **0xF060–0xF2C8** (address 0xF060, 88 entries × 8 bytes each).

**Record format** (8 bytes, LE):

```
Bytes 0–1:  CAN ID (little-endian 16-bit)
Byte  2:    Bus/direction field
            0x02 = B CAN (battery-side body/powertrain bus — see Finding 8)
            0x01 = D CAN (driveline bus — see Finding 8)
            0x05 = UDS ECU request ID
            0x06 = UDS ECU response ID
Bytes 3–4:  additional fields (TBD)
Bytes 5–7:  0x00 0x00 0x00
```

**Three groups of entries:**

- **Group 1 (B2=0x02, B CAN)**: Messages on the B CAN (battery-side body/powertrain bus): BMS, DCDC, HVAC, ACCM, IPK, GWM. Also includes D CAN signals that the gateway rebroadcasts onto B CAN (DLCM_Keepalive, ParkingBrake, ESC signals). See Finding 8 for bus identification evidence.
- **Group 2 (B2=0x01, D CAN)**: Messages on the D CAN (driveline bus): DLCM, ESC, EPS, TCM, RCU. The gateway subscribes to D CAN signals and publishes selected B CAN signals outward to D CAN for driveline modules. See Finding 8.
- **Group 3 (B2=0x05/0x06 pairs)**: UDS request/response CAN ID pairs for each ECU, routed via the Diag CAN (OBD port pins 6/14). All ECU pairs from the wholescan (0x710/0x718, 0x712/0x71A, 0x714/0x71E, 0x722/0x72A, 0x726/0x72E, 0x720/0x728, 0x716/0x71E) are present.

The table is in ROM (read-only flash), accessed by the UDS routing handler via PC-relative loads through SRAM pointer variables.

### Finding 2: UDS Dispatcher

**Function**: `FUN_00000a5c` at address 0x00A5C (called from `irq_handler`)

The dispatcher validates the incoming frame then switches on `(service_byte - 0x10)`:

| Switch case | UDS Service | Description |
|-------------|-------------|-------------|
| 0x00 | 0x10 | DiagnosticSessionControl |
| 0x09 | 0x19 | ReadDTCInformation |
| 0x12 | 0x22 | ReadDataByIdentifier (RDBI) |
| 0x17 | 0x27 | SecurityAccess |
| 0x18 | 0x28 | CommunicationControl |
| 0x1E | 0x2E | WriteDataByIdentifier |
| 0x1F | 0x2F | InputOutputControlByIdentifier |
| 0x21 | 0x31 | RoutineControl |
| 0x24 | 0x34 | RequestDownload |
| 0x26 | 0x36 | TransferData |
| 0x27 | 0x37 | RequestTransferExit |
| 0x2E | 0x3E | TesterPresent |
| 0x75 | 0x85 | ControlDTCSettings |

Code at **0x01924** verifies the tester CAN ID == **0x710** before processing any request.

**CORRECTED 2026-09-24.** An earlier version of this line continued "...non-matching IDs
receive NRC 0x11 (serviceNotSupported)". Both halves were wrong, read back off the
disassembly:

```
0x0191C  ldr  r0, =0x400004A8      ; received tester id
0x01920  ldr  r0, [r0]
0x01924  cmp  r0, #0x710
0x01928  bne  0x01D3C              ; MISMATCH -> branches away, emits nothing
0x0192C  and  r2, r2, #0x7F        ; match: mask suppressPosRsp off the subfunction
0x01930  cmp  r2, #0x1
0x01934  beq  0x025F0
0x01938  mov  r2, #0x7F  / strb [r3,#0]
0x01940  mov  r2, #0x11  / strb [r3,#1]
0x01948  mov  r2, #0x12  / strb [r3,#2]
0x01950  mov  r0, #0x3            ; 3-byte negative response
```

A non-matching id **branches away** rather than producing a negative response. And the
`0x11` in the block below is the **service byte** of `7F 11 12` — ECUReset refused with
subFunctionNotSupported, reached only when the id *does* match and the subfunction is not
`0x01` (hardReset). It is not an NRC.

*Verified with:* `../artifacts/gateway_uds_routing_analysis.py`

### Finding 3: DID Dispatch Table

The gateway handles a set of DIDs **locally** (not forwarded to other ECUs). The DID values, handler stubs, and SRAM buffer pointers are all stored together in the **literal pool** of the UDS handler function at binary offsets **0x01A10–0x01BB8**.

**Confirmed local DIDs:**

| DID | Standard meaning | Handler stub | Notes |
|-----|-----------------|--------------|-------|
| 0xF183 | ApplicationSoftwareFingerprint | 0xA101 | Static string from bootloader flash |
| 0xF190 | VehicleIdentificationNumber (VIN) | 0xA122 | Static string from bootloader flash 0x18AE8. Corrected from 0xA104 (Finding 9). |
| 0xF191 | ECU HW Part Number | 0xA104 | Static string from bootloader flash. Corrected from 0xA122 (Finding 9). |
| 0xF1A0 | (manufacturer specific) | 0xA10A | Static string from bootloader flash 0x18B08/0x18AF8 |
| 0xF1A1 | (manufacturer specific) | 0xA121 | Reads live SRAM: DCDCStatus1 slot (0x400004F0, 0x400004CC) and BMS_FaultStatus slot (0x40000664) |
| 0xF18C | ECU Serial Number | — | Static string from bootloader flash 0x18AEC/0x18B2C |
| 0xF101 | (manufacturer specific) | — | Reads live SRAM including AC_Compressor slot (0x40000688) |
| 0xF102 | (manufacturer specific) | — | Reads live SRAM including AC_Compressor slot (0x40000688) |
| 0x6402 | (Coda-specific) | — | Reads SRAM 0x40000538 (not a CAN signal slot — see Finding 9) |
| 0x6403 | (Coda-specific) | — | Reads many SRAM cells (0x40000644, 0x40000547, 0x400004A0, and others — see Finding 9) |
| 0x6441 | (Coda-specific) | — | Reads SRAM 0x4000009C, 0x40000094, 0x40000644, 0x40000690 (see Finding 9) |
| 0x6443 | (Coda-specific) | — | Reads SRAM 0x4000009C, 0x40000094, 0x40000644, 0x40000690 (see Finding 9) |
| 0xFFE4 | (unknown) | — | Present in literal pool near DID 0x6402 — role unknown |

**Handler stubs** (e.g., 0xA101, 0xA104, 0xA10A, 0xA121, 0xA122) live in the region 0x0A100–0x0A22F, just before the exception handlers at 0xA230+. These small stubs read from SRAM (populated at boot from flash) and build the UDS positive response frame.

**Critical observation**: The actual DID response data (VIN string, serial numbers, etc.) is stored in the **bootloader flash region** at addresses **0x18A14, 0x18AE8, 0x18AF8, 0x18AEC, 0x18B08, 0x18B1C, 0x18B2C** — all above 0x16000, which is outside the 90,112-byte application binary extracted via UDS download. The bootloader writes/stores manufacturing data (VIN, serial) in its own read-only flash area and the application references it at runtime via these pointers. **To read the VIN and serial number, the bootloader flash region (0x18000–0x1FFFF) must be extracted separately** — it was not included in the UDS download.

### Finding 4: DID 0x6401 is a Bootloader DID

DID 0x6401 does **not** appear anywhere in the application binary. From the diagnostic logs, the Omitec scanner polling `22 64 01` → `62 64 01 03` is handled by the **bootloader**, not the application. The byte `03` in the response likely indicates "programming-readiness state = 3" (application running, ready to accept download).

### Finding 5: Cell Voltage DIDs Come from the BMS, Not the Gateway

DIDs 0x8776, 0x8778, etc. (cell voltages seen in the diagnostic logs) are **not** handled by the gateway (0x718). They are handled by the **BMS ECU at 0x72A**. The Omitec sends requests from CAN ID 0x722 to ECU 0x72A. The gateway's CAN routing table (Group 3 entries) enables the gateway to transparently forward these UDS frames between the OBD port and the internal CAN bus.

### Finding 6: CAN ID Table B3/B4 Field Decoding

Analysis script: `projects/coda/notes/artifacts/gateway_b3b4_analysis.py`

**Corrected record count:** The table has **77 entries** (0xF2C8 − 0xF060 = 0x268 = 616 bytes ÷ 8), not 88 as previously noted. Entries 77–87 are past the table boundary and are garbage from the subsequent binary region.

**Corrected record format:**

```
Bytes 0-1:  CAN ID (little-endian 16-bit)
Byte  2:    Bus/direction group (B2)
            0xFF = sentinel guard entry (idx 0: CAN ID 0x0FFF, all 0xFF)
            0x02 = B CAN (battery-side body/powertrain bus — see Finding 8)
            0x01 = D CAN (driveline bus — see Finding 8)
            0x05 = UDS ECU request ID
            0x06 = UDS ECU response ID
Byte  3:    B3 — meaning depends on B2 (see below)
Byte  4:    B4 — home-bus flag (2=B CAN origin, 4=D CAN origin, 1=UDS)
Bytes 5-7:  0x00 0x00 0x00
```

**B4 = message home-bus flag (consistent across all groups):**
- `B4=2` — message **originates on B CAN** (native B CAN module is the transmitter). On the B CAN table (B2=0x02) this means gateway *receives* it; on the D CAN table (B2=0x01) this means gateway *transmits* it there as a forward from B CAN.
- `B4=4` — message **originates on D CAN** (native D CAN module is the transmitter). On the D CAN table (B2=0x01) this means gateway *receives* it; on the B CAN table (B2=0x02) this means gateway *transmits* it there as a rebroadcast from D CAN.
- `B4=1` — UDS entries only; does not encode bus origin.

**B3 on B CAN (B2=0x02) = SRAM signal slot index:**

Every B CAN entry has a *unique* B3 value. The 21 B CAN entries occupy slots 1–24, with gaps at slots 6, 16, and 21 (unused or fed by D CAN-only sources). Multiple rows with the same CAN ID (e.g. 0x0378 appears 3 times) represent separate signals extracted from the same message — each stored in a different SRAM slot. The gateway has at least 24 named signal slots.

B CAN signal slot assignments (B3 = SRAM slot, B4 = home bus):

| CAN ID | B3 (slot) | B4 | DBC name |
|--------|-----------|-----|----------|
| 0x0051 | 1 | 4 | (not in DBC) |
| 0x0643 | 2 | 2 | (not in DBC) |
| 0x0378 | 3 | 2 | BattPowermode |
| 0x0410 | 4 | 2 | AC_Compressor_Command |
| 0x0278 | 5 | 4 | DLCM_DriveKeepalive |
| *(slot 6 unused)* | — | — | — |
| 0x01D5 | 7 | 2 | DCDCStatus1 |
| 0x0378 | 8 | 2 | BattPowermode |
| 0x0270 | 9 | 2 | BMS_FaultStatus |
| 0x0052 | 10 | 4 | ParkingBrake_0x052 |
| 0x0410 | 11 | 2 | AC_Compressor_Command |
| 0x0276 | 12 | 2 | HVACStatus |
| 0x0278 | 13 | 4 | DLCM_DriveKeepalive |
| 0x0215 | 14 | 4 | misc_0x215 |
| 0x0491 | 15 | 2 | IPK_Status |
| *(slot 16 unused)* | — | — | — |
| 0x0208 | 17 | 4 | ESC_BrakePressure |
| 0x0383 | 18 | 2 | BMSBattStatus |
| 0x0052 | 19 | 4 | ParkingBrake_0x052 |
| 0x0200 | 20 | 4 | ESC_FrontWheelSpeeds |
| *(slot 21 unused)* | — | — | — |
| 0x0378 | 22 | 2 | BattPowermode |
| 0x0275 | 23 | 2 | BMSDriveLimits |
| 0x0248 | 24 | 2 | ExteriorLights_0x248 |

**B3 on D CAN (B2=0x01) = processing sub-type (group flag, not a slot index):**
- `B3=1, B4=4` (5 entries: 0x0591, 0x0592, 0x0593, 0x0603, 0x0745): Not in DBC; proprietary D CAN protocol IDs the gateway monitors (B4=4 = D CAN origin)
- `B3=2, B4=4` (12 entries: 0x0052, 0x0080, 0x01C0, 0x0200, 0x0208, 0x0210, 0x0212, 0x0215, 0x0240, 0x0241, 0x0418, 0x0600): Native D CAN signals the gateway subscribes to and rebroadcasts onto B CAN. All confirmed D CAN IDs per projects/coda/README.md (EPS, DLCM, ESC, RCU, TCM, etc.). B4=4 = D CAN origin.
- `B3=4, B4=2` (8 entries: 0x0051, 0x0168, 0x0275, 0x0276, 0x0383, 0x01D5, 0x0491, 0x0643): B CAN signals the gateway publishes onto D CAN for driveline modules to consume (BMSDriveLimits, HVACStatus, BMSBattStatus, DCDCStatus1, IPK_Status, etc.). B4=2 = B CAN origin.

**B3 on UDS req (B2=0x05):** B3 appears to be an ECU priority/type group:
- `B3=0`: 0x07DF (broadcast OBD address — special case)
- `B3=1`: 0x0710 (Omitec tester — gateway's own tester ID)
- `B3=2`: 7 ECU request IDs
- `B3=4`: 6 ECU request IDs

**UDS resp (B2=0x06):** B3=1 for all; B4=2 or 4 (direction of response forwarding).

**Next step:** Cross-reference the 24 SRAM slot indices against the 22-entry dispatch table at 0x84EC and DID handler stubs (Option C) to determine what physical quantity each slot holds. The actual byte extraction logic is in the bootloader region (blocked). See Finding 7 for CAN processing architecture.

### Finding 7: CAN Processing Architecture and Dispatch Table

**CAN frame pipeline (full chain):**

```
IRQ (irq_handler @ 0xA2AC)
  → FUN_00007c98 @ 0x7C98 (gate: checks bus-active flag, conditionally routes)
    → FUN_000066a0 @ 0x66A0 (enqueue received frame to per-bus circular buffer)

FUN_0000869c @ 0x869C (main application loop — runs continuously in foreground)
  → FUN_00006854 @ 0x6854 (dequeue frame from circular buffer for B CAN or D CAN)
  → scans CAN ID table for matching CAN ID
  → FUN_00007e10 @ 0x7E10 (per-slot signal extraction dispatcher)
  → FUN_00008598 @ 0x8598 (CAN bus bridge: forwards frames between B CAN and D CAN)
```

**Function roles:**

| Function | Address | Size | Role |
|----------|---------|------|------|
| `FUN_000066a0` | 0x66A0 | 0x19C | Enqueue received CAN frames to per-bus circular buffer |
| `FUN_00006854` | 0x6854 | 0x14C | Dequeue CAN frames from circular buffer |
| `FUN_0000869c` | 0x869C | 0x1A00 | Main application loop; CAN dequeue and dispatch |
| `FUN_00007e10` | 0x7E10 | 0x34 | Per-slot signal extraction dispatcher (switch on B3 slot index) |
| `FUN_00008598` | 0x8598 | 0xF8 | CAN bridge / forwarder (routes frames between B CAN and D CAN) |
| `FUN_00007c98` | 0x7C98 | 0x14C | IRQ gate: conditionally calls FUN_000066a0 |
| `FUN_000074b0` | 0x74B0 | 0x640 | **GPIO debouncer** (NOT CAN signal collector — reads GPIO bits via FUN_00003598) |
| `FUN_00003598` | 0x3598 | 0x60 | GPIO bit reader: returns `DAT_000035f8[port*4] >> bit & 1` |

**Dispatch table at binary offset 0x84EC (22 entries × 8 bytes):**

Each entry is two 32-bit words. Entries 1–15 and 18–19 are pairs of valid SRAM addresses (0x4000xxxx). Entries 0, 16, 17, 20–21 contain one or both words pointing to non-SRAM values (ROM? addresses or large integer constants like 0x00F423EF = 999,999 decimal, suggesting timer tick constants mixed in):

| Idx | Word0 | Word1 | Notes |
|-----|-------|-------|-------|
| 0 | 0x00019060 | 0x400017D0 | Word0 = bootloader flash — entry point of extraction handler |
| 1 | 0x40001A50 | 0x400017E6 | SRAM pair |
| 2 | 0x40001954 | 0x400019C6 | SRAM pair |
| 3 | 0x4000178C | 0x40000688 | SRAM pair |
| 4 | 0x4000064C | 0x400019BC | SRAM pair |
| 5 | 0x40000088 | 0x40000098 | SRAM pair |
| 6 | 0x400004F0 | 0x400004CC | SRAM pair |
| 7 | 0x40001960 | 0x400017B0 | SRAM pair |
| 8 | 0x40000068 | 0x40000664 | SRAM pair |
| 9 | 0x40001C00 | 0x400017A0 | SRAM pair |
| 10 | 0x40001BD4 | 0x40001810 | SRAM pair |
| 11 | 0x40001A24 | 0x40001974 | SRAM pair |
| 12 | 0x40001800 | 0x40000060 | SRAM pair |
| 13 | 0x40001A20 | 0x400019C7 | SRAM pair (C7 = odd byte addr) |
| 14 | 0x4000052C | 0x400017C8 | SRAM pair |
| 15 | 0x400019C4 | 0x40000BB0 | SRAM pair |
| 16 | 0x00F423EF | 0x4000008C | Word0 = 999,999 (timer constant?) |
| 17 | 0x0000FFF4 | 0x40001808 | Word0 = 65524 |
| 18 | 0x4000197C | 0x400017A4 | SRAM pair |
| 19 | 0x40001798 | 0x40001940 | SRAM pair |
| 20 | 0x000493E0 | 0x00F423F0 | No SRAM addresses |
| 21 | 0x40001BE0 | 0xE5D02012 | Word1 = ARM opcode? |

**Blockage:** `FUN_00007e10` switches on a case value (B3 slot index from the CAN ID table). Cases 1–4 all branch to code at address 0x19060+, which is in the **bootloader flash region above the 90 KB application binary**. Ghidra cannot decompile these paths and marks them as "bad instruction data." The actual CAN payload byte → SRAM slot extraction logic is therefore in the bootloader, not the application.

**Note:** The literal address 0xF060 (CAN ID table start) does not appear anywhere in the binary as a 32-bit word. The table is accessed through SRAM pointer variables loaded at runtime by the bootloader.

### Finding 8: Bus Identity — B CAN, D CAN, and Diag CAN

**The firmware's two data buses map to the Coda vehicle buses as follows:**

| Firmware label | B2 value | Physical bus | Coda DBC | OBD-II pins |
|---------------|----------|-------------|----------|-------------|
| Bus A | 0x02 | **B CAN** — battery-side body/powertrain | `CODA-B-CAN.dbc` | 2 (H), 3 (L) |
| Bus B | 0x01 | **D CAN** — driveline control | `CODA-D-CAN.dbc` | 10 (H), 11 (L) |
| Diag CAN | 0x05/0x06 | **Diag CAN** — OBD scan tool routing | — | 6 (H), 14 (L) |

**Evidence for Bus A = B CAN:**

The B CAN slot table (B3 = SRAM slot index, all B2=0x02 entries) is composed of:
- **B4=2 entries (B CAN origin, gateway receives):** 0x0378 BattPowermode (BMS), 0x0275 BMSDriveLimits (BMS), 0x0383 BMSBattStatus (BMS), 0x0270 BMS_FaultStatus (BMS), 0x01D5 DCDCStatus1 (DCDC), 0x0276 HVACStatus (HVAC), 0x0410 AC_Compressor_Command, 0x0491 IPK_Status (IPK) — all confirmed B CAN modules per `projects/coda/README.md`.
- **B4=4 entries (D CAN origin, gateway rebroadcasts onto B CAN):** 0x0278 DLCM_Keepalive (DLCM), 0x0052 ParkingBrake_Crank (misc_Recvd), 0x0215 misc_0x215 — all confirmed D CAN signals per `projects/coda/README.md` "also rebroadcast to B CAN by the GWM gateway."

**Evidence for Bus B = D CAN:**

The B3=2 subscribe list (D CAN native signals the gateway monitors) is an exact match for D CAN modules:
0x0080 EPS_Steering, 0x01C0 MCM_Telemetry, 0x0210 ThrottlePedalPos, 0x0212 DLCM_TorqueRequest, 0x0241 MCM_Thermal, 0x0418 DLCM_Globals, 0x0600 TPMS_Pressure — all confirmed D CAN per `projects/coda/README.md`.

The B3=4 publish list (B CAN signals the gateway forwards onto D CAN): 0x0275 BMSDriveLimits, 0x0276 HVACStatus, 0x0383 BMSBattStatus, 0x01D5 DCDCStatus1, 0x0491 IPK_Status — all confirmed B CAN per `projects/coda/README.md`.

**Diag CAN is the UDS routing layer:**

The Diag CAN (OBD standard pins 6/14) is not a data bus in the CAN ID table's B2 sense. Instead, the gateway's UDS routing function handles Diag CAN traffic: it listens for tester requests from 0x710 and routes them to ECUs on B CAN and D CAN. The B2=0x05/0x06 entries represent which physical bus each ECU's UDS node lives on.

**B4 field meaning (corrected):**

B4 is a *home-bus* flag encoding which physical bus is the native source of the CAN message:
- `B4=2` = B CAN origin. On the B CAN table (B2=0x02): gateway receives it. On the D CAN table (B2=0x01): gateway is transmitting it there (forwarded from B CAN).
- `B4=4` = D CAN origin. On the D CAN table (B2=0x01): gateway receives it. On the B CAN table (B2=0x02): gateway is transmitting it there (rebroadcast from D CAN).

This is consistent with every entry: no B CAN-origin message has B4=4 on the B CAN table, and no D CAN-origin message has B4=2 on the D CAN table.

### Finding 10: Diagnostic routing is per-CAN-ID, with no service filtering (2026-09-24)

Established to answer a specific question from the BMS work: when the GWM forwards a
tester request to an ECU, does it inspect the UDS **service** and refuse some — possibly
synthesising a negative response of its own? If it did, a module could appear to refuse a
service it never actually received.

**It does not.** Three independent checks against this image:

**1. The routing records carry no service field.** The 28 `B2=0x05`/`0x06` entries of the
CAN ID table (Finding 1) are CAN id + source/destination bus and nothing else:

| offset | CAN id | B2 | B3 | B4 | meaning |
|---|---|---|---|---|---|
| `0x0F1E8` | `0x722` | 05 | 02 | 01 | BMS request, Diag -> **B CAN** |
| `0x0F1F0` | `0x72A` | 06 | 01 | 02 | BMS response, B CAN -> Diag |
| `0x0F258` | `0x7E0` | 05 | 04 | 01 | DLCM request, Diag -> **D CAN** |
| `0x0F260` | `0x7E8` | 06 | 01 | 04 | DLCM response, D CAN -> Diag |

B3 is the destination bus and B4 the source, in Finding 8's codes (01 Diag, 02 B CAN,
04 D CAN). Every record says "this id moves from bus X to bus Y". `0x722` is routed by
exactly the same mechanism as `0x7E0`, differing only in destination bus.

**2. The firmware never constructs another module's response id.** Scanning the whole
image for each diagnostic id, both as an ARM MOV/MVN immediate and as a 4-byte literal:

| id | constructed? |
|---|---|
| `0x718` (its own response id) | literal at `0x0969C` |
| `0x7DF` (functional) | literal at `0x004A0` |
| `0x710`, `0x722`, `0x72A`, `0x7E0`, `0x7E8` | **never**, in either form |

`0x710` appears only inside `cmp r0,#0x710`. Forwarded ids are read from the table at
runtime, so the only diagnostic id the gateway can *originate* a frame on is `0x718`.

**3. Its own negative responses are service-matched.** Three builders sit together in the
same region, each storing three bytes and branching to a 3-byte send:

| address | bytes | meaning |
|---|---|---|
| `0x018FC` | `7F 34 33` | RequestDownload -> securityAccessDenied |
| `0x01938` | `7F 11 12` | ECUReset -> subFunctionNotSupported |
| `0x01968` | `7F 85 31` | ControlDTCSetting -> requestOutOfRange |

Each names the service actually being refused. There is no canned negative, and the byte
sequence `7F 10 12` does not occur anywhere in the image in either byte order.

**Scope limit.** This covers the gateway **application**. Finding 7 records that some CAN
handling lives in the bootloader above the 90 KB application, which has never been
extracted. A filter there is not excluded by any of the above; the routing table's shape
argues against one, but that is an argument, not a measurement.

*Artifact:* `../artifacts/gateway_uds_routing_analysis.py` (+ `_out.txt`), which includes a
small ARM disassembler written for this check — neither `capstone` nor an ARM-capable
`objdump` is available on `the Linux box`.

### Finding 9: DID Handler Literal Pool and SRAM Signal Anchors

Analysis scripts: `projects/coda/notes/artifacts/gateway_did_stubs.py`, `projects/coda/notes/artifacts/gateway_sram_xref.py`

**Literal pool at 0x1A10–0x1BB8** is the UDS handler's data section. It contains ~80 SRAM cell pointers, DID values, stub addresses, bootloader flash pointers (for static strings), and timer constants. The DID handler reads these to assemble UDS response frames.

**Confirmed CAN signal → SRAM → DID chains:**

The dispatch table hypothesis (entry N = slot N+1, 0-indexed) was validated by cross-referencing dispatch SRAM addresses against the DID literal pool. Confirmed anchors:

| Dispatch entry | Slot (B3) | CAN ID | Signal name | SRAM addr (dispatch) | In DID pool | DID that reads it |
|---------------|-----------|--------|-------------|---------------------|-------------|-------------------|
| 3 | 4 | 0x0410 | AC_Compressor_Command | w1=0x40000688 | YES | 0xF101, 0xF102 |
| 4 | 5 | 0x0278 | DLCM_DriveKeepalive | w0=0x4000064C | YES | (in pool) |
| 5 | 6 | (unused in B CAN table) | — | w0=0x40000088, w1=0x40000098 | YES (both) | (in pool) |
| 6 | 7 | 0x01D5 | DCDCStatus1 | w0=0x400004F0, w1=0x400004CC | YES (both) | 0xF1A1 |
| 8 | 9 | 0x0270 | BMS_FaultStatus | w1=0x40000664 | YES | 0xF1A1 |
| 14 | 15 | 0x0491 | IPK_Status | w0=0x4000052C | YES | 0x6403 (data block) |
| 15 | 16 | (unused in B CAN table) | — | w1=0x40000BB0 | YES | 0xF1A1 |
| 16 | 17 | 0x0208 | ESC_BrakePressure | w1=0x4000008C | YES | (in pool) |

**Coda-specific DIDs (0x6402, 0x6403, 0x6441, 0x6443) read from SRAM not in the dispatch table.** Their SRAM addresses (e.g. 0x40000538, 0x4000009C, 0x40000094, 0x40000644, 0x40000690) are not covered by the 22-slot dispatch system. These likely hold values from D CAN messages that the gateway monitors on Bus B but does not forward to B CAN — making them accessible only via UDS, not via normal B CAN monitoring. Candidate source messages: 0x0080 (EPS), 0x01C0 (MCM_Telemetry), 0x0240, 0x0241 (MCM_Thermal), and other D CAN IDs in the B3=2 subscribe list.

**Slot 6 is "unused" in the B CAN slot table but has a valid dispatch entry (0x40000088, 0x40000098) referenced by the DID pool.** This slot is likely populated from the D CAN side (bus B monitoring) or from bootloader-initialized data.

**DID 0xF1A1 reads from 3 dispatch slots** — DCDCStatus1 (slot 7, both words), BMS_FaultStatus (slot 9, w1), and slot 16 (w1=0x40000BB0, unknown). This DID response likely aggregates multiple live signal values into a combined status frame.

**Notable constants and markers in the literal pool:**
- Bootloader flash pointers: `0x00018A14`, `0x00018AE8`, `0x00018AF8`, `0x00018AEC`, `0x00018B08`, `0x00018B1C`, `0x00018B2C` — point to VIN, serial number, and fingerprint strings stored in bootloader flash (above the 0x16000 application binary boundary)
- Timer/staleness constants embedded in pool: 5000, 14999, 19999, 3000, 10010 ticks — likely message-stale thresholds
- `0xDEADDEAD` at pool offset 0x1A88 — debugging sentinel between DID data sections; confirms non-production-optimized build
- `0x51EB851F` at pool offset 0x1A74 region — likely a fixed-point reciprocal constant for scaling arithmetic

**DID stub address ordering in pool:** stub address appears at offset N, DID value at offset N+4 (e.g. stub=0xA122 at 0x1A5C, DID=0xF190 at 0x1A60; stub=0xA104 at 0x1A64, DID=0xF191 at 0x1A68). This corrects the earlier Finding 3 stub-DID table: F190→0xA122, F191→0xA104 (the original table had these swapped).

---

## Ghidra Run Details

| Item | Value |
|------|-------|
| Ghidra project | `%LOCALAPPDATA%\ghidra-projects\coda_gateway\` |
| Import log | `%LOCALAPPDATA%\ghidra-projects\coda_gateway_import.log` |
| Decompile output | `%LOCALAPPDATA%\ghidra-projects\coda_gateway_decompile.c` (also copied to `artifacts/`) |
| Functions found | 123 functions, 0 failed to decompile |
| Warnings | "non-existing memory" at 0x17xxx–0x18xxx (addresses in bootloader region, expected) |
| Note | Ghidra project must use a **local path** (not SeaDrive path) — the `.bat` runner uses `%LOCALAPPDATA%\ghidra-projects\` |

Run command: `projects/coda/notes/artifacts/run-ghidra-gateway.bat`
