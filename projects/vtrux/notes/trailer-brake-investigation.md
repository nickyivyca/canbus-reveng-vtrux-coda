# Trailer Brake CCM Investigation

**Status:** Phase 1 complete. Phase 2 complete. Phase 3 complete. Phase 4 (schematic re-verification) complete -- corrects an error in Phase 1/2. Phase 5 (bus-side analysis) in progress.
**Logs:** `vtruxtrailerpokinglog.log` (primary), `vtruxpartstruck.log` (baseline)

---

## Phase 1 Findings -- Architecture Research

### CCM is Not Reachable via Scanner

The most direct evidence: a GM-specific scan tool **cannot communicate with the CCM (K38)** on either the Vtrux or at the GM dealership that diagnosed the truck. This rules out the CCM being present-but-faulted and points squarely at hypothesis **(a): the CCM is physically absent, unpowered, or its GMLAN harness connector is disconnected**.

### System Architecture (from GM TSBs PIT5509 series + 2014 Electrical Manual)

**Modules involved:**
- **K38 CCM** (Chassis Control Module) -- the primary trailer brake controller; a GMLAN HS-CAN node; the module that holds DTCs; sends low-power duty cycle command to TBPM
- **K133 TBPM** (Trailer Brake Power Control Module) -- amplifies CCM commands and drives trailer brake circuit 47; communicates with CCM on a **dedicated LIN bus only** -- never appears on CAN
- **S76** -- dash control panel (gain +/- buttons, manual apply lever); wired to CCM only (see Phase 4 correction below -- earlier draft claimed CCM/BCM, but the 2014 BBM pg 68 schematic and 2015 manual pg 710 connector pinout both show CCM-only)
- **BCM** -- sets U0137 when it loses communication with the CCM on GMLAN

**GMLAN bus topology:**
```
ECM (internal 120-ohm terminator) --> ... --> K17 (EBCM) --> K38 (CCM) --> R6A (external 120-ohm terminator)
```
The CCM is at the **end of the bus**, after EBCM. The R6A termination resistor is a separate component located after the CCM. If the CCM connector is physically disconnected, both the CCM and R6A are isolated from the bus, leaving only the ECM's internal terminator -- 120 ohms instead of 60 ohms. The Vtrux still drives normally, so either the bus operates acceptably with one terminator missing, or Via bypassed/re-terminated the harness.

**CCM power and ground (2014 LD underhood fuse block):**
- F18UA "ICCM" 10A -- K38 constant battery positive (circuit 1940)
- F33UA "ECM IGN" 15A -- K38 key-on power (circuit 439) -- also powers ECM and K111
- Ground: circuit 2150 (pin 25 on CCM connector)

**CCM GMLAN connector pins:** 5+6 = GMLAN+ (circuit 2500), 17+18 = GMLAN- (circuit 2501).

### Relevant DTCs

| DTC | Set by | Meaning |
|-----|--------|---------|
| C1114 | CCM | Circuit 47 (trailer brake output) fault: short to power = "Service Trailer Brake System"; short to ground = "Check Trailer Wiring" |
| U0137 | BCM | BCM lost communication with CCM (K38) on GMLAN -- CCM absent from bus |
| U1556 | CCM | CCM lost communication with TBPM (K133) on LIN -- TBPM absent or not responding |

### DIC Message Interpretation

The Vtrux shows **"Check Trailer Brake System"** at startup with no trailer connected. Per the 2014 Electrical Manual, this message appears when "there is a problem with the trailer brake control system." Given that the scanner cannot reach the CCM at all, U0137 is almost certainly active: the BCM cannot see the CCM on GMLAN and tells the IPC to display the fault.

### Reference Log (rawlog_201704221049.log) -- Not Usable

The stock 2017 GM truck reference log is captured on the **SWCAN (Single Wire CAN)** bus, not HS-GMLAN. All IDs are 29-bit extended (0x10xxxxxx pattern). No overlap with the Vtrux HS-GMLAN ID space. The three-way comparison (Phase 3) reduces to a two-way diff: main Vtrux vs. parts truck only.

### No Public CAN IDs for CCM Found

No specific GMLAN HS-CAN arbitration IDs for CCM-transmitted messages are publicly documented in any source found (TSBs, forums, GMLAN Bible). The CCM's CAN presence -- or absence -- must be determined empirically from the log data.

### Sources

- GM TSB PIT5509 series (original Jun-2016 through PIT5509K May-2023) -- NHTSA OIDS
- 2014 GM Light Duty Electrical/Body Builders Manual (gmupfitter.com)
- [Vehicle Service Pros -- GM trailer brake deep dive](https://www.vehicleservicepros.com/service-repair/article/53098535/a-deep-dive-into-gms-trailer-brake-technology)
- Silverado/Sierra forum threads (bus topology detail)

---

## Phase 2 Findings -- Button Poking Log Analysis

**Log:** `vtruxtrailerpokinglog.log` (66s, 470,888 frames, 3 buses)
**Tools run:** `survey.py`, `status_events.py`, custom cross-log filter script
**Artifacts:** `trailer_poking_survey.txt`, `trailer_poking_events.txt`, `button_candidates.txt`, `cross_log_button_filter.py`

### Bus Identification

| Bus | Anchor IDs | Identity |
|-----|-----------|---------|
| 1 | 0x1E5, 0x500 | Vehicle / HS-GMLAN Unfiltered |
| 2 | 0x040-0x044 | OBD / Diagnostic |
| 3 | 0x051 | Powertrain |

### Cross-Log Filter

To isolate button-press-specific signals, a cross-log filter compared Bus 1 of the poking log against three reference Vtrux logs (movingaroundindriveway, vtruxevapdrivelog4, vtruxinterlocktest). Any byte that varies in the poking log but is completely static in all reference logs is a candidate -- the assumption being that the trailer brake buttons are not pressed in any reference log.

**Results on Vehicle bus (Bus 1):**
- 214 (ID, byte) pairs vary in the poking log
- **Category A (static in all refs, active in poking): 6** -- examined below
- **Category B (absent from all refs): 0** -- no trailer-package-exclusive IDs at all
- Category C (varies in refs too): 208

Full output: `artifacts/button_candidates.txt`

### Key Signal: 0x350 -- CCM Trailer Brake Status (PHASE 2 INTERPRETATION SUPERSEDED, see Phase 5.10)

`0x350` is a 4-byte, 20 Hz message broadcast by the K38 CCM on the Vehicle (GMLAN) bus. Phase 2 attributed B2 to "manual apply lever analog position" based on the trailerpoking log. **Phase 5.10 isolated tests prove this attribution was wrong:**

- **B2 = gain value scaled by 25.4** (gain 0.0 to 10.0 maps to B2 = 0 to 254 in 0.5 unit steps). Confirmed by `vtrux_trailergainsetting.log` and `vtrux_trailerbrakeleverpull.log`.
- **B0 bit 4 (0x10 mask) = "show trailer brake DIC page" signal.** Set by CCM when any S76 input is detected (lever or button); cleared after a short input-idle timeout.
- **B0 bit 1 (0x02 mask) = "trailer brake system initialized"** flag. Set after CCM init and stays set.
- B0's 4 observed states (0x00, 0x02, 0x10, 0x12) decompose as combinations of these two bits.
- **B3 = 0x03** in steady operation. Phase 2 had B3 transitioning during the trailerpoking sweep -- that was during a now-suspect activity sequence and not re-verified here.

What Phase 2 described as a "smooth lever ramp" (~13 counts per 0.25s) is now believed to be the user **holding a gain button**. The BBM page 65 explicitly says "pressing and holding a gain button will cause the trailer gain to continuously increment or decrement", and the timing (~2 gain steps per second × 12.7 ≈ 25 counts/sec) matches the auto-repeat rate, not analog potentiometer travel.

**The raw lever position is not broadcast on the Vehicle bus**, at least not anywhere we have identified. In `vtrux_trailerbrakeleverpull.log`, when the user pressed the lever, B2 stayed exactly at 0x3F (gain 2.5) and no other Vehicle-bus byte showed a clean lever-correlated change. The CCM likely reads the lever analog input and uses it internally to drive the trailer brake output to TBPM over LIN -- it does not need to expose the raw lever value to other GMLAN nodes.

### Key Signal: 0x287 -- Status Flag (PHASE 2 INTERPRETATION SUPERSEDED, see Phase 5.10)

`0x287` is a 3-byte, 40 Hz message. B0 is a 4-state rolling counter. B2 is always 0x00. Phase 2 attributed **B1** to a "trailer brake lever engaged" flag based on the trailerpoking log (B1 = 0x01 at rest, dropped to 0x00 from t=12.9s to t=60.2s).

Phase 5.10 isolated tests show this attribution is also unreliable:

- In the **gain-only test**, the user adjusted gain from 1.0 down to 0 then up to 10 and back -- B1 stayed at 0x01 the entire time.
- In the **lever-pull test**, the user actuated the lever and re-activated the trailer brake DIC display -- B1 stayed at 0x01.

So B1's transition to 0x00 in the trailerpoking log is triggered by something other than lever movement or gain button activity, and we don't yet know what. The "trailer brake lever engaged" label should be removed from B1 until a controlled experiment finds the actual trigger.

### Gain Buttons (+/-): Signal Identified in Phase 5.10

Phase 2 could not isolate the gain signal. Phase 5.10 (`vtrux_trailergainsetting.log`) isolated it cleanly:

**The gain value is broadcast in 0x350 B2 as `gain × 25.4`** (within ±1 LSB rounding):

| Gain | B2 (hex) | B2 (dec) |
|------|---------|---------|
| 0.0 | 0x00 | 0 |
| 0.5 | 0x0C | 12 |
| 1.0 | 0x19 | 25 |
| 1.5 | 0x26 | 38 |
| 2.0 | 0x33 | 51 |
| ... | ... | ... |
| 10.0 | 0xFE | 254 |

Pressing and holding +/- produces the smooth ramp at ~25 counts/sec. Releasing leaves B2 at the last gain value (does NOT decay back to 25). Each press increments the display promptly.

The other byte that transitions during gain presses is **0x350 B0 bit 4** (the DIC-page-show signal), which is also set during lever activity.

Three additional Vehicle-bus bytes flip a single bit during gain-button activity (echoed across messages): 0x12A B6 bit 3, 0x18E B4 bit 4, 0x1AA B5 bit 4. These are gateway-mirrored flags of the same "S76 panel input active" event -- not gain values themselves.

(superseded Phase 2 text retained below for history)

**Reconciliation (superseded by Phase 4):** Earlier draft assumed the gain buttons were wired to the BCM because the IPC display still updates with the CCM "absent". Phase 4 schematic re-verification shows the gain +/- buttons are wired to the CCM (S76 pin 4, circuit 7635, to K38 pin 20 -- "Integrated Trailer Brake Controller User Gain Signal"). The IPC display updating on button press therefore implies the CCM is at least partially functional. The CAN signal for gain has not been isolated for one of two reasons:

1. **No timestamp log:** The gain signal is likely present in Category C (varies in reference logs due to other factors in the same byte), but without a log that records exactly when each button was pressed we cannot separate gain transitions from background noise.
2. **Body network not captured:** The CCM-to-IPC gain message may travel on a network segment not exposed through the OBD port. The Via VCM filters messages.

A timestamped action log (recording button-press times) would resolve which explanation applies.

### Phase 2 Conclusion (superseded by Phase 4)

**Category B = 0** -- there are no IDs on the Vehicle bus exclusive to the poking log. The original interpretation was "the CCM is not transmitting anything" and that the BCM was handling S76 input. Phase 4 schematic re-verification overturns this: S76 is wired only to the CCM, so 0x350 (lever) and 0x287 (mode flag) appearing on the Vehicle bus implies the **CCM is broadcasting them**. Category B = 0 then means the CCM's CAN footprint is steady-state -- it is always emitting these IDs, even when the lever is at rest -- so the poking action does not create new IDs, only varies bytes in already-present ones.

**Hypothesis (a) -- CCM physically disconnected or unpowered -- is no longer supported.** Re-evaluation in Phase 5.

---

## Phase 3 Findings -- Two-Way Cross-Comparison

**Logs:** `vtruxtrailerpokinglog.log` (main Vtrux) vs. `vtruxpartstruck.log` (parts truck, no trailer package)
**Tools run:** `survey.py` on both logs, custom cross-log ID diff, `cross_log_vtrux_only_confirm.py`
**Artifacts:** `partstruck_survey.txt`, cross-log diff results, `button_candidates.txt`

### Parts Truck Log Notes

The parts truck survey (`partstruck_survey.txt`) shows 229 unique IDs across 3 buses in a 45-second capture:
- Bus 1 (OBD, 0x040-0x044 anchors): 68 IDs
- Bus 2 (Vehicle, 0x1E5/0x500 anchors): 84 IDs
- Bus 3 (PT, 0x051 anchor): 77 IDs

**Important caveat:** The parts truck had no HV battery installed at time of capture. This means the truck was in an abnormal state -- some modules may not have powered up, and some IDs that would normally be present may have been absent due to fault conditions rather than the absence of the trailer package. Any ID-level comparison with the parts truck is therefore inconclusive on its own.

### ID Diff Results

**Parts-truck-only IDs (absent from main Vtrux Vehicle bus):** None found.

**Vtrux-only IDs (present on main Vtrux Vehicle bus, absent from parts truck Vehicle bus):**

| ID | Rate | Behavior | Notes |
|----|------|----------|-------|
| 0x1AF | 40 Hz | Constant bytes | Present in all main Vtrux reference logs |
| 0x210 | 20 Hz | Active rolling counter in B0 | Present in all main Vtrux reference logs |
| 0x350 | 20 Hz | S76 lever position (B2) + mode flags | Present in all main Vtrux reference logs |
| 0x4C9 | 2 Hz | Constant bytes | Present in all main Vtrux reference logs |
| 0x785 | 1 Hz | All-zeros NM heartbeat | Present in all main Vtrux reference logs |
| 0x7E8 | sporadic | OBD response frame | Not trailer-related; query artifact |

All five genuine Vtrux-only IDs (excluding 0x7E8) were confirmed present in every main Vtrux reference log (movingaroundindriveway, vtruxevapdrivelog4, vtruxinterlocktest, vtruxcurrentlimiting).

### Interpretation

**These IDs may or may not be trailer-package-specific.** The parts truck fault state (no HV battery) is a confounder -- IDs absent from the parts truck could be absent because the truck has no trailer package, or simply because modules were offline due to the missing battery. Without a stock GM truck log pair (with trailer package vs. without) captured under comparable conditions, the source of these extra IDs cannot be determined.

Notable signals worth flagging:

- **0x350** is confirmed as the S76 manual apply lever position. This ID being Vtrux-only is consistent with the trailer package being present on the main Vtrux and absent from the parts truck -- but cannot be confirmed conclusively.
- **0x785** is in the GMLAN Network Management range (0x780-0x7FF). Node address 0x05 broadcasts NM at 0x785. The identity of node 0x05 is unknown; it is a candidate for a trailer-package module but this is speculative.
- **0x210** has an active rolling counter, suggesting a live module is transmitting it. Its role is unconfirmed.
- **0x1AF** and **0x4C9** are constant-byte IDs; their role is unconfirmed.

### Phase 3 Conclusion

The two-way diff is inconclusive. The 5 Vtrux-only IDs are candidates for trailer-package-specific traffic -- particularly 0x350 (confirmed lever position) and 0x785 (NM range) -- but the parts truck fault state prevents any definitive attribution. The comparison also cannot tell us whether the CCM is present and transmitting on the main Vtrux; if the CCM is absent from both trucks, any IDs associated with it would be absent from both diffs.

**All three hypotheses (a, b, c) remain open.** A longer parts truck capture after the HV battery is reinstalled, and ideally stock GM truck logs with/without the trailer package, would be needed to advance further.

---

## Phase 4 Findings -- Schematic Re-Verification (Correction)

**Sources:** 2014 BBM Electrical Manual, page 68 (Trailer Brake Control System Schematic, rendered as `artifacts/trailer_schematic/2014_pg68-068.png`); 2015 Sierra/Silverado Service Manual, page 710 (S76 connector pinout table).

### What the schematic actually shows

S76 has an 8-pin connector. Five signal wires leave S76, pass through X61A (Junction Block - Instrument Panel) and X185, and land **directly on K38 Chassis Control Module**. No BCM connection appears on this schematic anywhere.

| S76 Pin | Circuit | Wire | K38 Pin | Function (per 2015 manual) |
|---------|---------|------|---------|----------------------------|
| 3 | 7632 | D-BU/RD | 16 | 5V Reference / Manual Apply Signal / Redundant Manual Apply |
| 4 | 7635 | YE | 20 | User Gain Signal (+/- buttons) |
| 5 | 7634 | BN | 18 | Switch Low Reference |
| 6 | 7633 | L-GN/BK | 21 | (signal line, function row absent in pdftotext-extracted table) |
| 8 | 7631 | BK/BN | 19 | Switch Low Reference |

Pin 7 (circuit 6817 YE) is panel backlight illumination and goes to the Interior Lights Dimming subsystem, not to any communication module.

### Correction to Phase 1 and Phase 2

The Phase 1 note "S76 wired to CCM/BCM" was not supported by either source document. The 2014 schematic and 2015 connector table both show S76 wired only to the K38 CCM. The BCM is not on this circuit at all.

This invalidates the Phase 2 reasoning that "the BCM correctly handles S76 lever input" and "the gain buttons must be wired to the BCM."

### Implication for the CCM-absent hypothesis

In the poking log, 0x350 B2 tracks the manual apply lever's analog position and 0x287 B1 toggles when the lever is engaged. If S76 is wired only to K38, then **some module is reading the S76 analog/switch inputs through the K38 connector and broadcasting the result on GMLAN**. The simplest reading is that this module is K38 itself -- i.e. the CCM is present on the bus and at least partially functional.

The scanner's inability to communicate with K38 (Phase 1) is then a different fault mode than physical absence -- likely diagnostic addressing/routing, UDS-layer fault, or Via-Motors-specific behavior. The CCM is broadcasting periodic status traffic but is not responding to scan-tool requests.

**Revised hypothesis ranking:**

- **(a) CCM physically disconnected/unpowered -- demoted.** Inconsistent with 0x350/0x287 being live on the bus given the corrected wiring.
- **(b) CCM present but not responding to scanner -- promoted.** Consistent with all known evidence: 0x350/0x287 live, IPC gain display working on +/- press, scanner times out, U0137 likely set (because some BCM-side handshake is missing even though CAN traffic is present), C1114 plausible (TBPM not driven).
- **(c) LIN-side fault (CCM-to-TBPM) -- still possible.** Could co-exist with (b) -- the CCM is broadcasting status but its low-power duty-cycle command to TBPM over LIN is failing.

### Phase 4 Conclusion

The Phase 1 wiring claim was wrong. With the corrected wiring, the most likely scenario is that the CCM is on the bus and broadcasting, but either not responding to UDS or not driving the TBPM properly. The investigation now needs to verify (a) which messages on the Vehicle bus are CCM-emitted (cross-check vs. parts truck, which visually has no CCM) and (b) whether anything CCM-sourced is missing or addressed to the wrong bus.

---

## Phase 5 Findings -- Bus-Side Re-Analysis

### 5.1 -- 0x350 and 0x287 bus residency

Per-bus residency from `trailer_poking_survey.txt` and `partstruck_survey.txt` (anchor-ID-resolved):

| ID | Main Vtrux Vehicle | Main Vtrux OBD | Main Vtrux PT | Parts truck Vehicle | Parts truck OBD |
|----|--------------------|----------------|---------------|---------------------|------------------|
| 0x350 | yes, 20 Hz, B2 lever | absent | absent | **absent** | absent |
| 0x287 | yes, 40 Hz, B1 toggles | yes, 40 Hz, identical content | absent | yes, 40 Hz, B1=01 static | yes, 40 Hz, identical to Vehicle |

**0x350 is CCM-sourced** -- present on the Vehicle bus only, completely absent on a truck with no CCM.

**0x287 is not CCM-sourced** -- it remains present on the parts truck (no CCM) on both Vehicle and OBD buses with identical content. There are two independent native broadcasters of 0x287, one on each GM bus. The B1 toggle on main Vtrux (0x01 at rest → 0x00 when lever engaged) is a downstream derivation: the broadcaster reacts to CCM's 0x350 when it is present, and reports the rest state when it is not. This **reverses** the earlier Phase 4 implication that 0x287 was a CCM-emitted "trailer brake mode flag."

### 5.2 -- VCM disconnect test (T3) cross-check

From `notes/can-disconnect.md` T3 (VCM B-connector pulled, log `vtruxwoodwardbconnectordisconnected.log`):

| ID | Bus | Survives T3? | Frame count (36.66s) |
|----|-----|--------------|----------------------|
| 0x350 | Vehicle | yes | 732 frames @ 20 Hz |
| 0x287 | Vehicle | yes | 1463 frames @ 40 Hz |
| 0x287 | OBD | yes | 1463 frames @ 40 Hz |

Both copies of 0x287 survive the VCM disconnect with identical frame counts -- the VCM is not gateway-bridging 0x287. There are two physically distinct broadcasters (one per GM bus), and both are independent of the VCM.

### 5.3 -- IDs that are truly single-bus (not VCM-bridged) and survive T3

Single-bus IDs in normal operation (reference: `genlog-survey.json`) that also survive T3:

**OBD-only, never bridged to Vehicle, survives T3 (3 IDs):**

| ID | Rate | DLC | Source attribution |
|----|------|-----|--------------------|
| 0x189 | 40 Hz | 7 | **Not in GMW8762 PPEI spec.** Forum reverse-engineering identifies it as TCM-transmitted torque request to ECM (see `notes/deprecated/gmlan-additional-investigation.md` § "0x189 -- TCM Torque Requests to ECM"). |
| 0x1A6 | 40 Hz | 1 | **Not in GMW8762 PPEI spec.** Listed in the same deprecated note as a TCM TX ID ("TCM TX IDs not yet investigated from the TX list: 0x197, 0x1A6, 0x1AF, 0x77F"). Note also: the `can-disconnect.md` matrix incorrectly attributes 0x1A6 to the "VCM bridges to Vehicle bus" row; the reference data shows 0x1A6 has never been on the Vehicle bus, so the bridging claim is wrong. |
| 0x1DF | 40 Hz | 3 | **Not in GMW8762 PPEI spec.** No solid attribution; flagged in `gmlan-additional-investigation.md` line 402 only as an ID that would need to be added for T87A use. |

Vehicle-only IDs that the CCM has direct access to (not the gap candidates): 36 IDs including 0x350 itself, EBCM Vehicle anchors (0x17D, 0x1E5), GMLAN NM range (0x778-0x788), and various 10-50 Hz chassis traffic.

### 5.4 -- GMW8762 PPEI spec dual-transmitter usage

The PPEI spec table format allows a `Transmitter` field with multiple modules, indicating the message may originate from any of them depending on platform configuration (extracted from `gmlan-info/gmw8762_tables_extracted.json`):

- `TCM, ECM`: 0x0F9, 0x120, 0x1F5, 0x4C9
- `EBCM, EPS`: 0x1E5
- `TCCM/RDCM`: 0x1CC, 0x1CF, 0x1D1
- `TCCM/FDCM`: 0x1D0

This is a "list of valid transmitters per platform variant" notation, not a primary/secondary handoff. None of 0x189, 0x1A6, 0x1DF appear in the spec at all, so the concept does not apply to them.

### 5.5 -- Attribution correction summary

The earlier-cited "ECM/EBCM -- native OBD" lumped attribution (covering 0x189, 0x18E, 0x1A1, 0x1A3, 0x1A6, 0x1AA, 0x1AF, 0x1BA, 0x1C6, 0x1CF, 0x1DF, 0x1E1, 0x1E9, 0x1ED, 0x1F1, 0x1F4, 0x287, 0x2C3, 0x2F9 in `can-disconnect.md`) is misleading. The in-spec entries actually come from a mix of transmitters:

| Spec module | IDs from that lumped row |
|-------------|--------------------------|
| ECM | 0x2C3, 0x3D1 (not in row), 0x3E9 (not in row) |
| EBCM | 0x17D (not in row), 0x1C7 (not in row), 0x1E9, 0x2F9 |
| GW (gateway) | 0x1E1, 0x1F1, 0x451 (not in row), 0x4E1 (not in row) |
| TCM (per forum, not spec) | 0x189, 0x1A6 |
| Unattributed | 0x1A1, 0x1A3, 0x1AA, 0x1AF, 0x1BA, 0x1C6, 0x1CF, 0x1DF, 0x1ED, 0x1F4 |

### 5.6 -- Hypothesis for "CCM expecting a message it is not getting"

The CCM lives on the Vehicle (GMLAN) bus. Three IDs are OBD-bus-native and never reach the Vehicle bus (not bridged): **0x189, 0x1A6, 0x1DF**. If the CCM expects any TCM-sourced torque message (0x189 is the documented TCM-to-ECM torque request) or any of the unattributed OBD-only IDs, the CCM is blind to them on the Vtrux.

Test plan: bridge 0x189, 0x1A6, 0x1DF from the OBD bus to the Vehicle bus using two USB CAN dongles and observe whether the CCM behavior changes (DTCs cleared, scanner reaches CCM, "Service Trailer Brake System" message clears). The bridge was a small python-can script forwarding those three IDs one-way between the two dongles.

### 5.7 -- Pre-bridge baseline: what "scanner cannot reach CCM" looks like

**Log:** `projects/vtrux/logs/vtrux_ccmscan.log` (2026-06-06, 42s, GM-specific scan tool actively attempting to talk to the CCM).

Bus identification: Bus 1 = PT (anchors 0x051, 0x644), Bus 2 = Vehicle (anchors 0x1E5, 0x500), Bus 3 = OBD (anchor 0x040).

**Entire diagnostic activity in the 42-second window:**

| t (s) | Bus | Arb ID | Data | Direction |
|-------|-----|--------|------|-----------|
| 35.506 | 2 (Vehicle) | 0x7E3 | `01 3E 00 ...` (TesterPresent) | Tx by scanner |
| 38.436 | 2 (Vehicle) | 0x7E3 | `01 3E 00 ...` (TesterPresent) | Tx by scanner |

**Nothing else** -- no responses anywhere. Specifically:
- No frames at 0x7EB (the +0x08 ISO 15765-4 response slot for 0x7E3)
- No frames at 0x5E8 (the Via VCM's proxy response channel, where ECM-side queries land -- see §5.7 ECM comparison below)
- No NRC frames at any address
- The 0x7E3 Tx is **not bridged to the OBD or PT bus** by the Via VCM (zero copies on Bus 1 or Bus 3)
- After the second TesterPresent ~2.93s after the first, the scanner gives up

This is the discovery-timeout signature: the GM tool tries the CCM's standard ISO 15765-4 chassis slot, gets nothing, and stops trying. The bus is healthy and busy with all the normal periodic traffic during this entire window -- only the K38 responder is mute.

**Comparison to ECM-scan signature** (`vtrux-obdbus_obd-then-gm-tool-scan.log`, same tool, different module target):

| | CCM scan (this log) | ECM scan (prior log) |
|---|---|---|
| Scanner request address | 0x7E3 | 0x7E0 |
| TesterPresent reply | none | `01 7E AA AA AA AA AA AA` at 0x7E8, every time |
| GM-specific service reply | n/a (gave up before sending) | `81 06 21 00 XX 00 00 00` at **0x5E8**, via Via VCM proxy |
| VCM bridges Tx request to OBD bus | no | yes (identical Tx on both Vehicle and OBD buses) |

So the Via VCM intercepts and answers ECM-slot (0x7E0) requests itself, even forwarding GM-specific 0xA9 services back via the proprietary 0x5E8 channel -- but for CCM-slot (0x7E3) requests it does neither: no proxy, no bridging. The K38 CCM itself does not answer at 0x7E3.

**Implication for the Phase 5.6 bridge experiment:**

This log is the **negative-control baseline**. After the bridge is running (forwarding 0x189, 0x1A6, 0x1DF from OBD to Vehicle), repeat the same GM-tool CCM-scan capture. The expected outcomes:

- **Hypothesis confirmed:** post-bridge capture shows responses at 0x7EB (or 0x5E8 via VCM proxy) when the scanner sends TesterPresent at 0x7E3. The CCM was waiting for one of the missing TCM-sourced messages to come alive before it would respond to diagnostics.
- **Hypothesis falsified:** post-bridge capture looks identical to this baseline -- 2 TesterPresent Tx, no Rx -- meaning the CCM's silence is unrelated to the missing OBD-bus traffic, and the gap is somewhere else (LIN to TBPM, CCM firmware/security state, physical wiring, etc.).

### 5.8 -- Bridge result (2026-06-06): hypothesis falsified for dashboard-message clearing

**Log:** `../../CANLogs/VtruxLogs/vtrux_20260606_115543_T0.log` (126s, Android-logger capture; the PC was running the bridge so PC-side logging was unavailable, hence the Android backup path).

**Bridge verification (factual):**
- 0x189, 0x1A6, 0x1DF appeared on the Vehicle bus at 40 Hz between t=78.8s and t=103.2s -- 2931 frames over 24.4s of clean bridging.
- Same three IDs also present on the OBD bus throughout (native).
- Bridge content fidelity not separately verified frame-by-frame, but rate and byte-range match the OBD-bus originals.

**GM scanner CCM-scan attempt during the bridge window:**
- One 0x7E3 TesterPresent `01 3E 00 ...` Tx at t=81.637s -- 2.8s after the bridge started, with 21+ more seconds of bridging available.
- Zero responses anywhere on any bus (no 0x7EB, no 0x5E8, no NRC, no forwarded copies). Identical signature to the baseline in §5.7.

**Dashboard observation:** the "Check Trailer Brake System" warning did **not** clear with the bridge running.

**Conclusion:**

The intended test outcome was the dashboard message clearing -- nothing about the diagnostic responsiveness was expected to change, since the scanner-reaches-CCM question is independent. The dashboard message did not clear, so Phase 5.6 is **falsified for its intended outcome**: missing 0x189/0x1A6/0x1DF on the Vehicle bus is not the reason the BCM raises the "Check Trailer Brake System" message.

Where the gap actually lives -- LIN-side fault between CCM and TBPM, BCM-side handshake the CCM is not completing, security/programming state of K38, or a different missing input -- is still open.

### 5.9 -- Key-on bit-flip investigation: no diagnostic sequence, only candidates ruled out

**Observation:** the warning beep and "Check Trailer Brake System" message appear ~a couple of seconds after ignition-on, not immediately.

**Log:** `../../CANLogs/VtruxLogs/vtrux_20260606_121426_T0.log` -- clean key-on capture (truck off at t=0, modules waking at t=5.4s = key insertion / accessory power, contactor close at t=12.0s = key to RUN).

**Finding 1 -- No active diagnostic sequence.** Zero frames at 0x7DF, 0x7E0-0x7EF, 0x5E8 or 0x6E8 in the first 15 seconds after key-on. The "Check Trailer Brake System" trigger is **not** an active UDS/OBD-II diagnostic exchange. It must be passive heartbeat monitoring -- the BCM (or IPC) is watching for some CCM-emitted message and timing out when an expected condition is not seen.

**Finding 2 -- Eliminated bit-flip candidates.** A thorough scan of Vehicle-bus persistent bit flips in the t=12-20s window (1-8s after key-on) found these candidates and ruled them all out:

| ID / byte / bit | Flip time | Verdict |
|----|---|----|
| 0x1F1 B0 / B7 | +0.1-1.1s | Normal startup signalling, not the warning. |
| 0x0C9 B0 / B6 | +0.9s | Engine General Status -- engine state at start. Not warning. |
| 0x1A3 B0 bit 7 | +1.2s | Set on every truck post-startup (main AND parts) -- normal init state, not warning. |
| 0x350 B0 / B3 | +1.3s | CCM mode flags (now correctly understood per Phase 5.10). |
| 0x4C1 B3 / 0x3D3 B6 | +1.4s | Engine Intake Air Temp (0x3D3 B6 confirmed identical to 0x4C1 B3 byte-for-byte across 6 logs). Not warning. |
| 0x3F1 B1 | +1.4s | Normal startup signalling, not the warning. |
| 0x785 | +2.4s | GMLAN NM heartbeat node 0x05. Initially looked like a strong "couple-seconds-after-keyon" match, but cross-log comparison with other main-Vtrux key-on logs (`vtruxtrailerpokinglog`, `generator-on-then-off`, `rainychargedebug2`) showed all-zero payload in normal conditions. The non-zero transition only appears in this log and `vtruxisolationtest.log` -- both involved 12V disconnect / isolation reset events. Concluded: 0x785 transition = **window calibration warning** (12V disconnect side effect), not trailer brake. |
| 0x12A B3 bit 5 | +2.3s | Set 68-96% across ALL trucks including parts -- dynamic byte content, not a flag. |

**Finding 3 -- The parts-truck bit-level diff also fell through.**

Two candidates from a "set in main / clear in parts" comparison (`0x1ED B6.4`, `0x3D3 B6.3`) both turned out to be normal signal data once verified -- 0x3D3 B6 carries Engine Intake Air Temp identically with 0x4C1 B3 across all logs, and 0x1ED B6 carries engine-running-state information (set when engine is running, clear otherwise).

**Finding 4 -- 0x1AF was wrongly listed as Vtrux-only in Phase 3.**

Re-checked across all logs: 0x1AF broadcasts the identical static signature `[20 00 00 30 00 00 00 FF]` at 40 Hz on the Vehicle bus on **both main Vtrux AND parts truck**. Phase 3's "Vtrux-only" attribution was incorrect. 0x1AF is not a trailer-package-exclusive ID.

**Finding 5 -- The trailer brake warning bit was not isolatable by these methods.**

Combining all of the above, the persistent CCM/trailer fault indicator is not surfacing in standard byte-/bit-level transition scans on the captured logs. Plausible reasons:
- The indicator may be in a message that already has dynamic data in the relevant byte (so it doesn't stand out in stability filtering).
- The indicator may be a bit that the CCM emits to indicate its own fault state -- the CCM's silence to the scanner (Phase 5.7) is the strongest available evidence that something is wrong on the CCM side, independent of whatever the BCM/IPC decides to display.
- The warning-displayed timing (a couple of seconds after key-on) may be driven by the IPC's own display-debounce / lamp-test sequence rather than a CAN-side transition, with the underlying fault bit set earlier and consistently.

### 5.10 -- Phase 2 0x350/0x287 corrections (lever vs gain isolation)

**Logs (new):**
- `projects/vtrux/logs/vtrux_trailergainsetting.log` -- gain-only test: started at gain 1.0, walked down to 0, then up to 10, then back down to 1.0. Lever not touched.
- `projects/vtrux/logs/vtrux_trailerbrakeleverpull.log` -- lever-only test: trailer brake DIC display was visible at log start (gain at 2.5), display timed out at t=6.94s, then user pulled lever at t=10.19s reactivating display. Gain stayed at 2.5 throughout.

**Result -- 0x350 B2 is the gain value, not the lever position.**

In the gain-only test, B2 took clean 12.7-unit steps from 0 (gain 0) up to 254 (gain 10.0) with no lever input. In the lever-only test, B2 stayed exactly at 0x3F = 63 (gain 2.5) the entire time even while the user actuated the lever and reactivated the DIC display. This is incompatible with Phase 2's "B2 = lever position" interpretation.

What Phase 2 described as a smooth lever ramp in `vtruxtrailerpokinglog.log` (~13 counts per 0.25s) matches the gain button auto-repeat rate (the BBM page 65: "pressing and holding a gain button will cause the trailer gain to continuously increment or decrement"). The trailerpoking session was almost certainly the user holding the gain +/- buttons, not sliding the lever.

**Result -- 0x350 B0 bit 4 (the 0x10 mask) is the "show trailer brake DIC page" signal.**

In the lever-pull log, B0 took values 0x12 → 0x02 → 0x12 mapping exactly to the user-narrated DIC display states (visible -> timed out -> visible again at lever press). Bit 4 set = display shown; bit 4 clear = display not shown. Bit 1 (the 0x02 mask) is a separate "CCM init complete" flag that stays set after first init.

**Result -- the raw lever position is not broadcast on the Vehicle bus.**

When the lever was actuated in the lever-pull log, B2 did not move, and no other Vehicle-bus byte showed a clean lever-correlated change. The CCM appears to read the lever potentiometer locally and use the value internally to drive the LIN command to the TBPM, without broadcasting it to GMLAN consumers.

**Result -- 0x287 B1's "lever engaged" attribution is unsupported.**

In both clean tests B1 stayed at 0x01 (no transition) despite gain button presses and lever actuation. The trailerpoking-log B1 -> 0x00 transition documented in Phase 2 happened during an activity sequence we now know was not what Phase 2 thought it was. B1's actual trigger condition is unknown.

**Other side findings (gain-button activity flags echoed across messages):**

| ID | Byte | Bit | Behavior |
|----|------|-----|----------|
| 0x12A | B6 | bit 3 | Set during gain button press; clear at idle |
| 0x18E | B4 | bit 4 | Same |
| 0x1AA | B5 | bit 4 | Same |

Likely gateway-mirrored copies of "S76 panel input active". Not gain values.

### 5.12 -- CCM Accessory Wakeup Serial Data (circuit 5985) hypothesis

**Sources (independently verified by subagent investigation 2026-06-06):**
- 2014 BBM Electrical Manual, K38 Chassis Control Module Connector page (Pg. 69)
- 2015 Sierra/Silverado BBM, K38 Chassis Control Module pinout (footer page 553/896)
- 2015 BBM "Accessory Wakeup and Communications Enable" schematic (footer page 140/896)
- 2015 BBM Connector Location table (footer pages 205-218)

**What circuit 5985 is:**

Circuit 5985 = "Accessory Wakeup Serial Data" (wire color VT/YE, 0.5 mm²). It is a single-wire serial wakeup signal that energizes at IGN and is shared among many modules on the GM platform.

It is **not** the GM Low-Speed GMLAN signal. The actual LS-GMLAN data signal is **circuit 5060** (color L-GN), confirmed in both BBMs (2014 line 3124, 2015 K36 module pinout line at footer page 550/896). The two are entirely separate buses.

**K38 connection:**

K38 receives circuit 5985 on **pin 8** (per both 2014 BBM Pg. 69 and 2015 BBM K38 pinout at footer page 553/896). The schematic on 2015 footer page 140/896 shows the wire landing at pin 14, which is a BBM internal inconsistency between the schematic and pinout table. The pinout tables agree (8 in both 2014 and 2015), so pin 8 is the more trustworthy attribution.

**Trace from source to K38** (from 2015 wakeup schematic, JL1 trailer-brake-equipped branch):

```
F7DL fuse (instrument panel left fuse block X51L)
  --> wire 5985 (VT/YE)
  --> K9 Body Control Module connector X4 pin 22  [also a node on the bus]
  --> J309 splice  (no physical location in BBM index)
  --> X138 "Chassis Harness to Body Harness" inline connector pin 20
  --> K38 pin 8  (Accessory Wakeup Serial Data)
```

The 2015 BBM connector-location index does NOT contain an entry for X138 (the table skips from X125 to X150 — documentation gap). J309 is a splice and splices are not assigned physical locations in either BBM.

**Module locations** (from 2015 BBM Connector Location, footer page 206/896 — verified by rendering the page to `notes/artifacts/trailer_schematic/2015_k38_location_p208-208.png` and reading the table visually after a first pdftotext extraction misaligned columns and incorrectly attributed the K40 row to K38):

| Module | Location |
|---|---|
| K9 Body Control Module (source-side) | Passenger compartment, behind driver side of instrument panel, outboard of steering column |
| **K38 Chassis Control Module (sink-side)** | **Under the vehicle, mounted to the bracket above the spare tire** (rear underbody) |
| X138 inline connector (in-trace) | Not specified in BBM -- documentation gap. "Chassis Harness to Body Harness" inline, typically a rear-of-cab body/chassis boundary connector. |

**Vtrux-specific K38 location:**

On the Vtrux, the spare tire has been removed and replaced by the "big charge module" in that same physical location. **K38 itself is in its original stock mounting position** -- sitting on top of the charge module, on the same bracket above where the spare tire used to be. Via did not relocate K38; they only changed what's underneath it.

**Implications for the Vtrux:**

The K38 sits at the rear underbody. The wire from K9 BCM (cab dash) to K38 has to traverse: cab body harness -> chassis/body inline (likely X138) -> chassis harness running along the underbody -> K38 connector at the rear.

An earlier draft of this section hypothesized that Via Motors broke the 5985 connection at X115 ("Body Harness To Engine, in the front of the engine compartment, near the upper left of the radiator support") when redoing engine-bay wiring. That hypothesis is **invalidated** -- X115 is on the K20 ECM branch of 5985, not on the K38 branch.

A later draft hypothesized Via relocated K38 and skipped 5985 in a Via-built harness extension. That hypothesis is also **invalidated** -- K38 is in its stock mounting position.

The remaining hypothesis (weaker, but still testable): **if** Via Motors disrupted the body or chassis harness section that 5985 traverses (e.g. running HV cabling through the cab floor, modifying the dashboard area for the BCM-tap CAN dongle, or anything that crossed X138 or the J309 splice region), the 5985 wire could be broken. There is no strong circumstantial evidence this happened -- it's now just a "worth physically checking" hypothesis rather than a "Via almost certainly broke this" hypothesis.

**Predicted symptom pattern if 5985 is missing at K38:**

| Observation | Consistent with 5985 missing? |
|---|---|
| K38 has power and broadcasts 0x350 at 20 Hz | Yes -- 1940 Battery+ (pin 1), 439 Run/Crank IGN (pin 21), and 2150 Ground (pin 25) are independent of 5985; basic CAN TX runs without the wakeup signal |
| K38 receives S76 input (lever/gain) and reports it on 0x350 | Yes -- S76 pins are local cab wiring untouched by powertrain rework |
| K38 does not respond to 0x7E3 TesterPresent | Yes -- the diagnostic-protocol stack on GM modules is typically gated by the accessory-wakeup handshake; without 5985 the UDS stack may remain in a low-power state that ignores requests |
| BCM displays "Check Trailer Brake System" | Yes -- the BCM's CCM-presence check on the wakeup bus does not see the expected response from K38, so BCM concludes the CCM is not fully online |
| Bridging 0x189/0x1A6/0x1DF did not clear the warning | Yes -- the missing signal is a hardware line, not a CAN message |

**Direct verification (recommended):**

Open the K38 connector and probe pin 8 (VT/YE) for 5985 and pin 17 (per X138 mapping in the trace; also check K38's pinout for its own 5986 pin if defined). With ignition in RUN:
- If pin 8 is unpopulated or wire is open --> confirmed: 5985 is missing at K38, Phase 5.12 hypothesis stands
- If pin 8 has the wire and shows expected wakeup-bus activity at key-on --> 5985 is connected, look elsewhere for the CCM-silence cause

The wakeup-bus signal at key-on may be a steady ~12 V or a low-rate pulse pattern; an oscilloscope (or just multimeter for presence/absence check) will tell.

**X138 also makes a good mid-trace probe point** -- the same connector that carries the S76 panel signals (which we know reach K38 because the gain test works) also carries 5985 on pin 20 and 5986 on pin 17 (per 2015 BBM footer page 789/896 X138 pinout). If you find X138 in the cab/floor harness area and pin 20 is alive while K38 pin 8 is not, that pinpoints the break to the chassis-side harness between X138 and K38.

If 5985 is missing at K38, an external 12V supply pulled in via a switched relay (IGN-triggered) into K38 pin 8 would be a non-invasive test to see if the CCM transitions to a more responsive state (responds to UDS, BCM clears U0137, dashboard message clears).

### 5.13 -- Interpretation given all of the above (was 5.11)

Across Phase 5.6 (bridge experiment falsification), Phase 5.7-5.8 (scan tool gets zero response at 0x7E3, even with bridge running), Phase 5.9 (no diagnostic sequence and no isolable warning bit at key-on), and Phase 5.10 (CCM is clearly broadcasting 0x350 with valid gain data on the Vehicle bus):

- **The CCM is alive on the bus** -- it emits 0x350 at 20 Hz, the gain value (B2) tracks user button presses correctly, the "show DIC page" bit (B0 bit 4) toggles correctly with user input.
- **The CCM does not respond to the GM scan tool** -- 0x7E3 TesterPresent gets nothing, and bridging OBD-side TCM-source IDs to the Vehicle bus did not change that. The scan-tool unreachability is a property of the CCM itself or its diagnostic addressing, not a missing upstream input.
- **The "Check Trailer Brake System" warning is independent of either fix attempted so far.** It persists with the bridge running and is not driven by a key-on diagnostic exchange.

The most parsimonious remaining hypotheses center on the CCM's own internal state:
- CCM has a stored DTC it cannot clear (e.g. C1114 trailer brake output circuit fault), which it reports via some persistent indicator the BCM/IPC reads, AND its UDS stack is unresponsive for an unrelated reason (firmware/security state).
- Or, the LIN-side fault between CCM and TBPM (hypothesis (c) from Phase 4) is what the CCM is broadcasting, and the scan-tool silence is a separate problem.

The fact that the GM scan tool **does not want to talk to the CCM** is now the central anomaly. A healthy K38 should respond to 0x7E3 TesterPresent regardless of stored DTCs. That it is silent suggests either a security / programming state on the CCM, a damaged diagnostic stack, or that the module is something other than a stock K38 in slot 0x7E3.

---

## Phase 6 -- Synthesis (Not Yet Started)

Produce a final verdict section in this file covering:

1. **CCM module status:** Present on Vtrux CAN bus or absent? Evidence from each log.
2. **Button events:** Do trailer brake button presses produce any CAN activity? On which IDs?
3. **Trailer-specific IDs:** What IDs are in the main Vtrux but not the parts truck?
4. **Hypothesis verdict:** Which scenario fits:
   - **(a) CCM physically disconnected/unpowered** -- absent from GMLAN, no scanner communication (already strongly supported)
   - **(b) CCM present but VCM not forwarding needed messages**
   - **(c) LIN issue (CCM->TBPM)** -- CCM active, buttons produce events, TBPM not reached
   - **(d) Combination**
5. **Next steps:** What would fix it? What further capture would help?

Update `projects/vtrux/Vtrux.md` module topology table to add CCM status.
