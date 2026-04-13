# Trailer Brake CCM Investigation

**Status:** Phase 1 complete. Phase 2 complete. Phase 3 complete. Phase 4 not yet started.
**Logs:** `vtruxtrailerpokinglog.log` (primary), `vtruxpartstruck.log` (baseline)

---

## Phase 1 Findings -- Architecture Research

### CCM is Not Reachable via Scanner

The most direct evidence: a GM-specific scan tool **cannot communicate with the CCM (K38)** on either the Vtrux or at the GM dealership that diagnosed the truck. This rules out the CCM being present-but-faulted and points squarely at hypothesis **(a): the CCM is physically absent, unpowered, or its GMLAN harness connector is disconnected**.

### System Architecture (from GM TSBs PIT5509 series + 2014 Electrical Manual)

**Modules involved:**
- **K38 CCM** (Chassis Control Module) -- the primary trailer brake controller; a GMLAN HS-CAN node; the module that holds DTCs; sends low-power duty cycle command to TBPM
- **K133 TBPM** (Trailer Brake Power Control Module) -- amplifies CCM commands and drives trailer brake circuit 47; communicates with CCM on a **dedicated LIN bus only** -- never appears on CAN
- **S76** -- dash control panel (gain +/- buttons, manual apply lever); wired to CCM/BCM
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

### Key Signal: 0x350 -- S76 Manual Apply Lever Position

`0x350` is a 4-byte, 20 Hz message present in all Vtrux logs. **B2 is the manual apply lever analog position.** It sits at 0x19 (25 decimal) at neutral rest when the lever is not touched, and is static at that value in every reference log. During the poking session the lever was swept through its full range:

| Time (s) | B2 | Event |
|----------|----|-------|
| 0 | 0x19 = 25 | Neutral/rest |
| 5.6 | -- | B0/B3 mode flags activate |
| 29.1 | 0x19 -> ramp | Lever pushed up |
| 32.4 | 0xCC = 204 | Lever at maximum |
| 32.9 | 0xCC -> ramp | Lever released |
| 36.1 | 0x00 = 0 | Lever fully released |
| 37.7 | 0x0C -> 0x19 | Returns to rest |
| 61.7 | 0x10, B3=0x00 | Mode flags deactivate |

Step size is approximately 13 counts per 0.25s, consistent with smooth lever travel. **This confirms the S76 lever and its BCM wiring are intact and functional.**

B0 carries mode flags (4 states: 0x00, 0x02, 0x10, 0x12) and B3 a secondary flag (0x00 or 0x03). These activate when the lever is first moved and deactivate when it returns to stowed.

### Key Signal: 0x287 -- Trailer Brake Mode Flag

`0x287` is a 3-byte, 40 Hz message. B0 is a 4-state rolling counter. B2 is always 0x00. **B1 is a binary flag** (0x01 = inactive, 0x00 = active) that is static at 0x01 in all reference logs and drops to 0x00 at t=12.9s (first lever operation), returning to 0x01 at t=60.2s. Interpreted as a BCM-broadcast "trailer brake lever engaged" mode flag. Not in the GMLAN DBC (DBC coverage is incomplete for body/chassis IDs).

### Gain Buttons (+/-): Signal Not Isolated

The gain adjustment value changes on the IPC screen when the buttons are pressed (confirmed by user observation). No gain-button-specific signal appeared in Category A on Bus 1, and Category B = 0 rules out the CCM broadcasting a gain acknowledgment.

**Reconciliation:** The gain buttons must be wired to the BCM -- if they were wired only to the CCM (absent), the IPC display would never update. The BCM receives the button inputs and sends the current gain value to the IPC. The CAN signal for this has not been isolated for one of two reasons:

1. **No timestamp log:** The gain signal is likely present in Category C (varies in reference logs due to other factors in the same byte), but without a log that records exactly when each button was pressed we cannot separate gain transitions from background noise.
2. **Body network not captured:** The BCM-to-IPC gain message may travel on a body network segment (body HS-CAN or LS-CAN) that is not exposed through the OBD port. The Via VCM filters messages; body display traffic may be on the BCM side of the gateway.

A timestamped action log (recording button-press times) would resolve which explanation applies. This is a minor open question and does not change the CCM-absent conclusion.

### Phase 2 Conclusion

**Category B = 0 is the key finding.** There are no IDs on the Vehicle bus exclusive to the poking log. The CCM is not transmitting anything. The BCM correctly handles S76 lever input (0x350, 0x287) and gain button input (display confirmed working), but there is no CCM present to receive those messages and drive circuit 47.

**Hypothesis (a) -- CCM physically disconnected or unpowered -- remains strongly supported.**

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

## Phase 4 -- Synthesis (Not Yet Started)

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
