# Three-Bus Investigation: Vtrux CAN Architecture

Most high-level findings from this investigation have been promoted to `../Vtrux.md` (bus identification anchor IDs, quick-check rules, bus roles, module topology, VCM gateway behavior). This file retains the detailed investigation methodology and evidence that informed those conclusions: per-log bus number mappings, frame-level masking evidence, OBD passthrough/scanner timing detail, GM proprietary diagnostic exchange, and common-message inventory.

For confirmed powertrain signals, see `powertrain-messages.md`. For generator activation sequence, see `../Vtrux.md` "Generator Activation Sequence" section.

## Findings

### Bus Identification Method

**IMPORTANT:** Bus numbers in log files are arbitrary! Always identify buses by message content, not by capture bus ID.

#### Bus Identification (confirmed 2026-02-18; DLC port assignment corrected 2026-03-30)

**IMPORTANT — DLC port correction (2026-03-30):** The standard OBD2 DLC port on the Vtrux is wired to the **Vehicle bus**, NOT the OBD bus. The OBD bus (with 0x040–0x044) is only accessible via harness P1 connector (pin 10 CAN-H / pin 2 CAN-L) — a standard scan tool plugged into the stock DLC pins reaches the Vehicle bus and talks to the ECM via VCM gateway. This corrects the earlier assumption that the DLC port was wired to the OBD bus.

Bus numbers change between sessions (dongles plugged in randomly), so always identify by message content.

**Primary method — exclusive ID fingerprint (no scanner needed):**
- OBD bus has **0x040–0x044** and **0x441–0x464** and does NOT have 0x1E5 or 0x500–0x530
- Vehicle bus has **0x1E5, 0x500, 0x514, 0x52A–0x530, 0x778, 0x780, 0x785, 0x788** and does NOT have 0x040–0x044 or 0x441–0x464
- Either exclusive set alone is sufficient; a quick `survey.py --bus N` and check for presence/absence of these IDs settles it

**Secondary — ID count:** Vehicle bus has more unique IDs (~90–93) than OBD bus (~74–79). Useful as a quick sanity check but not conclusive on its own.

**Confirmatory — scanner timing (only relevant when a scan tool is attached):**

Forwarding direction depends on where the scanner is connected:

- **Scanner on OBD bus (P1 harness connector, direct ECM access):** `0x7DF` appears on OBD bus only — NOT forwarded to Vehicle bus. `0x7E8` responses originate on OBD bus and are echoed to Vehicle bus shortly after. `0x7E0` tester-present originates on OBD bus and is echoed to Vehicle bus.
- **Scanner on Vehicle bus (standard DLC port, VCM-mediated):** `0x7DF` originates on Vehicle bus and is forwarded to OBD bus ~2–4ms later by the VCM. `0x7E8` responses originate on OBD bus and are echoed back to Vehicle bus. `0x7E0` tester-present originates on Vehicle bus and is forwarded to OBD bus ~3ms later.

The asymmetry in 0x7DF forwarding (forwarded Vehicle→OBD but not OBD→Vehicle) cleanly distinguishes the two scanner positions. (Confirmed 2026-03-30: vtrux-obdbus_obd-then-gm-tool-scan.log and vtrux-drivetrainbus_obd-then-gm-tool-scan.log)

#### Known Bus Numbers by Log Set

| Log set | Powertrain | Vehicle | OBD |
|---------|-----------|------------|--------|
| generator on then off / movingaroundindriveway | bus 3 | bus 2 | bus 1 |
| vtruxcodereading / vtruxobdenginespeed | bus 1 | bus 2 | bus 3 |
| vtrux-drivetrainbus_obd-then-gm-tool-scan / vtrux-obdbus_obd-then-gm-tool-scan | bus 3 | bus 2 | bus 1 |

Bus numbers are coincidental — dongles are plugged in randomly each session.

### Three Bus Roles

| Bus Name | Identifier Messages | Characteristics |
|----------|---------------------|-----------------|
| **Powertrain** | 0x051 + extended IDs (0x18xxxxxx) | Via Motors EV control |
| **Vehicle** | Real sensor data in GMLAN messages; exclusive 0x1E5, 0x500–0x530 | Direct ECU, unfiltered |
| **OBD** | Masked sensor data; exclusive 0x040–0x044, 0x441–0x464; 0x7E0/0x7E8 when scanner active | Filtered; accessible via harness P1 connector only (NOT standard DLC) |

### Powertrain Bus

**How to identify:**
- **0x051** present @ ~100 Hz (generator torque command)
- Multiple extended IDs (0x18FF0320, 0x18FFD6B3, 0x18E8FFB3, etc.)
- Message IDs concentrated in 0x5xx-0x6xx range
- Mirrored GMLAN messages offset by 0x30 (e.g., 0x470-0x484 mirroring 0x440-0x454)

**Confirmed characteristics (generator on then off / movingaroundindriveway = bus 3; vtruxcodereading / vtruxobdenginespeed = bus 1):**
- 0x051 @ 100 Hz with varying data during generator operation
- 93 unique message IDs
- Extended IDs present: 0x18FF0320, 0x18FFD6B3, 0x18E8FFB3, 0x06000001/2, etc.

**Message categories:**
- 0x050-0x054: Via control (mirrors OBD 0x040-0x044 pattern)
- 0x308: BorgWarner TCM park pin state (100 Hz; same ID/structure as Coda -- confirmed 2026-03-05)
- 0x370-0x375, 0x390, 0x395, 0x3FE, 0x400: Powertrain control
- 0x410-0x412, 0x420, 0x430, 0x440, 0x460: BMS-dependent messages (interlock/status/voltage)
- 0x470-0x484: Mirrored GMLAN (offset +0x30 from OBD 0x440-0x454)
- 0x505-0x507: BMS-originated (drop immediately when HV battery LV connector is unplugged); 0x506 B1/B2/B3 and 0x507 B0/B1 = battery temperatures (raw-40=degC); 0x505 role unknown
- 0x55C: BorgWarner TCM heartbeat (10 Hz; same ID/structure as Coda -- confirmed 2026-03-05; previously mis-categorized here)
- 0x580: Charger/inverter
- 0x592, 0x594-0x5A2, 0x600, 0x617, 0x619, 0x61F, 0x625, 0x626, 0x62F: Driver inputs, charger
- **0x639, 0x63A, 0x63C, 0x63D, 0x63F, 0x640, 0x644-0x64B, 0x651:** Battery pack (A123 BMS)
- 0x6A0, 0x71E: Unknown
- **Extended IDs:** J1939/vendor protocols (DCDC, charger, etc.)

### Vehicle Bus (Direct ECU)

**How to identify:**
- GMLAN messages with **real sensor data**
- **0x0C1** shows actual rotation values during driving
- **0x1F5** byte 3 shows actual gear changes (1-9)
- More message IDs than OBD bus (~90–93 vs ~74–79)
- Additional platform/body messages (0x1E5, 0x1FC, 0x210, 0x214, 0x232, 0x34A, 0x500, 0x514, etc.)

**Evidence from driveway log (driving):**
- 0x0C1: Full rotation data `00-F3 00-FF 00-FF 00-FF...` ✅ REAL DATA
- 0x1F5 byte 3: Varies `00-04` showing actual gear changes ✅ REAL DATA
- 0x3E9 (vehicle speed): Varying values ✅ REAL DATA

**Unique message IDs (not on OBD):**
- 0x0D0, 0x120, 0x121, 0x12A, 0x135, 0x137, 0x139 (platform messages)
- **0x1E5** @ 100 Hz (unknown, high-frequency signal)
- 0x1FC, 0x210, 0x214, 0x232, 0x348, 0x34A, 0x34C, 0x350, 0x362 (platform/body control)
- **0x500, 0x514, 0x52A, 0x52B, 0x530** (VIN/configuration data)
- 0x778, 0x780, 0x785, 0x788 (periodic body module status frames — not scanner traffic)

**OBD passthrough behavior:** When an OBD scanner is active on the **Vehicle bus** (standard DLC port), the VCM forwards `0x7DF` requests to the OBD bus ~2–4ms later, the ECM responds with `0x7E8` on the OBD bus, and that response is echoed back to the Vehicle bus. When a scanner is on the **OBD bus directly** (P1 harness connector), `0x7DF` is NOT forwarded to the Vehicle bus — only the `0x7E8` response is echoed across. For GM proprietary diagnostics (service 0xA9 via `0x7E0`), the request and response are both echoed across buses regardless of which side the scanner is on.

### OBD Bus (Filtered, OBD2 DLC wired here)

**How to identify:**
- GMLAN messages with **masked/filtered sensor data**
- **0x0C1** = all zeros EVEN WHEN DRIVING
- **0x1F5** mostly constant, simplified
- Fewer message IDs than Vehicle (~74–79 vs ~90–93)
- Subset of GMLAN standard messages

**Evidence from driveway log (driving):**
- 0x0C1: All zeros `00 00 00 00 00 00 00 00` ❌ MASKED
- 0x1F5: Mostly constant `0F 0F 00 01 00 00 08 00` ❌ SIMPLIFIED

**Unique message IDs (not on Vehicle):**
- **0x040–0x044:** Filtered/simplified versions of Powertrain 0x050–0x054 (same ECU, different IDs per bus)
- **0x441–0x464:** Chassis/transmission messages (mirrored to Powertrain as 0x471–0x484)
- 0x661 (intermittent)

**When OBD scanner is active (definitive indicators):**
- **0x7DF** (OBD broadcast requests) — if scanner is on OBD bus (P1): appears here only, NOT forwarded to Vehicle bus. If scanner is on Vehicle bus (DLC): appears on Vehicle bus first, forwarded to OBD bus ~2–4ms later.
- **0x7E8** (ECU responses) originate here — echoed to Vehicle bus shortly after, regardless of where the scanner is.
- **0x7E0** Tester Present (`01 3E 00`) — originates where the scanner is, echoed to the other bus.
- **0x5E8** — Enhanced diagnostic response ID; only appears in response to GM scanner service 0xA9 (`03 A9 81 1A`); echoed to Vehicle bus. Source is likely the ECM's own enhanced (GM-proprietary) diagnostic channel — distinct from its standard OBD channel (0x7E8) — rather than a Via proxy, because it responds even when the scanner is directly on the OBD bus bypassing the VCM. Not yet confirmed on a stock (non-conversion) GM vehicle. See GM Proprietary Diagnostic section below for current response content.

**GM proprietary diagnostic:**

Observed in vtruxcodereading.log (early capture, no active DTCs):
```
Request:  0x7E0  03 A9 81 1A 00 00 00 00   (GM service 0xA9 -- proprietary DTC read)
Response: 0x5E8  81 00 00 00 FF 00 00 00   (empty DTC list)
```

Observed in vtrux-drivetrainbus/obdbus logs (2026-03-30, P0621 present):
```
Request:  0x7E0  03 A9 81 1A 00 00 00 00
Response: 0x5E8  81 06 21 00 5B 00 00 00   (DTC entry: 06 21 = P0621, status 5B)
          0x5E8  81 00 00 00 FF 00 00 00   (end of list)
```

Service 0xA9 is GM's proprietary `ReadStatusOfDTCGroup`. The response comes from `0x5E8`, which is likely the ECM's enhanced/GM-proprietary diagnostic response channel (separate from its standard OBD response at `0x7E8`), rather than a Via proxy — the response appears even when the scanner talks directly to the ECM on the OBD bus without going through the VCM. Not yet confirmed on a stock non-conversion GM vehicle. The 2-byte DTC encoding: `06 21` = P0621 (Generator Lamp "L" Control Circuit). This is a non-emission, non-MIL code in this ECM calibration — not visible via standard OBD service 03/07/0A even when querying the ECM directly.

**0x772 — ECM DTC status broadcast (OBD bus, 1 Hz):**

The ECM continuously broadcasts its internal DTC status on 0x772 at ~1 Hz. Format (7 bytes):
```
00 11 06 21 00 5B 03
```
Bytes 2–3 = `06 21` = P0621, present from the start of every capture. This frame is also echoed to the Vehicle bus ~50ms later by the VCM. It predates any scan tool activity — the DTC is always there.

**P0621 — Generator Lamp "L" Control Circuit:**

P0621 is stored in the ECM because the original alternator's L-terminal (charge indicator lamp / tachometer feedback wire) was removed during the EV conversion. The ECM tracks this fault internally and broadcasts it via 0x772 and reports it via GM service 0xA9, but has it classified as a non-emission enhanced diagnostic — not OBD-reportable, no MIL. Standard OBD service 03/07/0A returns 0 DTCs and PID 01 shows MIL OFF, even when the scanner is talking directly to the ECM via P1. The suppression is in the ECM's own calibration, not at the VCM gateway.

### Common Messages (All GM Buses)

Both Vehicle and OBD have these GMLAN messages (but with different data quality):
- 0x0C1, 0x0C5 (rotation data) - MASKED on OBD
- 0x0C9 (engine status)
- 0x0F1 (platform)
- 0x1C3, 0x1C5, 0x1C6, 0x1C7 (engine/chassis torque)
- 0x1F1, 0x1F5 (platform status)
- 0x3E9 (vehicle speed)
- 0x451 (engine torque status)
- Plus ~50 more GMLAN standard messages

---

## Notes

- If simultaneous 3-bus capture exists, it will be in a single file or clearly documented
