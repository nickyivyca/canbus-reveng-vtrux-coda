# Driving Sequence Investigation

## Session 1: codadriveslowturnonwithdefroster2.log

**Log:** B+C+D CAN, ~708s, 1.9M frames
**Capture notes:** Slow deliberate key-on with pauses between steps. Fan/defroster may have been turned on before driving. Traction control events near end of drive.
**Analyzed:** 2026-02-19
**Tool:** `python tools/status_events.py <log>` (auto-discovery mode, default settings)
**Full output:** `projects/coda/notes/defroster2-event-clusters.txt`

---

### Startup Timeline

The first 8 event clusters map cleanly to the startup sequence:

| Cluster | Time | Event | Key Evidence |
|---|---|---|---|
| **#1** | 0.3-3.0s | **WAKE / ACCESSORY** | D CAN 0x200-0x203 wake from 0x9C sleep. B CAN modules initialize. |
| | *6.4s gap* | *user pausing at accessory position* | |
| **#2** | 9.5-13.5s | **KEY TO ON** | 0x248 B4: 0->4. 0x370 B0: 0x12->0x14. Many modules activate. |
| | *2.0s gap* | *user pausing at ON position* | |
| **#3** | 15.5-20.7s | **KEY TO START / CRANK + PRECHARGE** | 0x052 toggles 0x04<->0x0C (cranking). 0x378 B6 ramps 0->0x12 (DC link). 0x1D7 activates (DCDC). |
| | *5.2s gap* | *precharge completing* | |
| **#4** | 25.9-26.2s | **READY MODE** | 0x248 B1: 0x03->0x0B. 0x491 B3: 0->0x33 (traction inverter online). |
| **#5** | 30.3-31.4s | **SYSTEMS SETTLING** | 0x391 B1 initialized. 0x410 B2 flag on. |
| **#6** | 37.3-42.5s | **HVAC ON (defroster)** | 0x391 B0 ramps 0x65->0xC1 (PTC heater warming). 0x418 B0/B4 change (HVAC state). 0x55C toggles. |
| **#7** | 46.5-49.3s | **HVAC settling** | 0x248 heartbeat. 0x391 B0->0xFC (temp still climbing). |
| **#8** | 53.5-55.3s | **Startup complete** | 0x418 B4: 0xBB->0x00->0x11 (HVAC mode stabilized). |

---

### Signal Hypotheses

#### Ignition / Power State Signals

> **CONFIRMED 2026-09-27, independently of this capture.** The hypotheses below were
> drawn from one deliberate slow key-on. They were then rediscovered from the opposite
> direction: 23 mid-capture key cycles across 19 captures, found by looking for bytes
> that change across a multi-module dropout and revert. Every ladder below reproduces
> **in both directions**, and `0x370` B0 matches this capture's key-position timings to
> 0.04 s. `0x370` B0[3:0] and B3 are now declared signals in `CODA-D-CAN.dbc` as
> `VehiclePowerState`, `PowerSubMode` and `PowerSubMode_Valid`, with the sender
> confirmed as the GWM from the factory DTC list. Method and corpus results:
> `key-cycle-detection.md`.
>
> One caveat that survives: the **value names** are still inferred from ladder position.
> `0x370` B0[3:0] covers the same state set as the spec's `Powermode` but is **not** that
> signal — the spec compares Powermode ordinally and these codes are not ordered
> (Crank is 9, Ready is 5).

| Signal | Bus | Evidence | Reading | Status |
|---|---|---|---|---|
| **0x248 B4** | B+C | Steps 0->4->5->4->3->1 through startup stages, reverses on shutdown | **Ignition position / key state** | confirmed, both directions |
| **0x248 B1** | B+C | Different value at each startup stage (0x41->0xC3->0x83->0x86->0x82->0x03->0x0B) | **Ignition sub-state / mode flags** | partly — moves with the key cycle, values not assigned |
| **0x370 B0** | B+C | Steps up at each key position: 0x12->0x14->0x19->0x16->0x15 | **Vehicle operating mode** | confirmed; now `VehiclePowerState`. High nibble is a constant 0x1 — the ladder is B0[3:0] |
| **0x370 B3** | B+C | 0xF1->0x11 at wake, then 0x12->0x14 at precharge | **Power sub-mode** | confirmed; now `PowerSubMode` + `PowerSubMode_Valid`. The 0xF high nibble is an asleep/invalid sentinel, read separately by the DLCM |

#### HV / Drivetrain Signals

| Signal | Bus | Evidence | Hypothesis |
|---|---|---|---|
| **0x052 B0** | B+C | Toggles 0x04<->0x0C repeatedly during cluster #3 only -- classic crank pattern | **Starter motor / crank request** |
| **0x378 B6** | B only | Ramps 0->5->8->0A->0B->0C->0E->11->12 during crank/precharge. Returns to 0 at shutdown. | **DC link voltage (scaled)** -- ramp during precharge is characteristic |
| **0x378 B0** | B only | 0x11->0x21->0x41 at precharge, reverses at shutdown | **HV system mode** (bit field?) -- CONFIRMED 2026-09-27, reproduces in both directions across the key cycles. An HV precharge cycle here is what rules out a capture artefact as the cause of a module dropout. |
| **0x1D7 B0/B1** | B only | B0: 0->0x80 at precharge, 0x80->0 at shutdown. B1: drifts slowly during operation. | **DCDC converter status** -- B0 = on/off, B1 = output voltage? |
| **0x270 B7** | B only | 0->0x08->0x88->0xC8 through startup, reverse at shutdown | **HV system state flags** (bit field accumulating) -- CONFIRMED 2026-09-27, reproduces in both directions across the key cycles. |
| **0x271 B0** | B only | 0->1->5->6 through startup, 6->2->0 at shutdown | **Power stage state machine** -- CONFIRMED 2026-09-27, reproduces across the key cycles. |
| **0x275 B6** | B+C | 0->4->0xC at startup (confirmed: B0=discharge limit, B1=charge limit from bonnydoon) | **BMS status flags / limits active** |
| **0x491 B3** | B+C | Only appears at "ready" (cluster #4): 0->0x30->0x33, goes to 0 at shutdown | **Traction inverter / drive readiness** |

#### HVAC / Thermal Signals

| Signal | Bus | Evidence | Hypothesis |
|---|---|---|---|
| **0x391 B0** | B only | Ramps 0x50->0x65->0xFC over ~50s after HVAC on. Slow thermal profile. | **PTC heater temperature or coolant temp** |
| **0x418 B0/B4** | B+C | State changes at HVAC events. B4 cycles through 0xDD->0xBD->0xBB->0x00->0x11->0xDB->0xDD | **HVAC mode / compressor state machine** |
| **0x55C B0** | C only | Toggles 0x42->0x04->0x85 near HVAC events | **Compressor or blower status** |
| **0x240 B6** | B+C | Toggles between 0x08/0x10/0x18/0x1C during operation, modulating rapidly in later clusters | **HVAC duty cycle / modulation** |
| **0x308 B0** | C only | Steps 0->0x20->0x40 through startup, reverses at shutdown | ~~Accessory power state~~ **SUPERSEDED 2026-09-26**: 0x308 is the DLCM park request (`DLCM_ParkRequest`, signal `ParkRequest`), established from the DLCM firmware TX table and corroborated by the Vtrux EPRI DBC. Whatever B0 is doing here, it is not accessory power. |

#### D CAN Signals

| Signal | Bus | Evidence | Hypothesis |
|---|---|---|---|
| **0x200-0x203 all bytes** | D only | ALL wake from 0x9C to ~0x0A/0x0B at t=1.2-1.6s. Drift slowly +1 over minutes. | **Battery module temperatures or cell group voltages** -- 0x9C is sleep sentinel, ~10-11 is initial reading, slow +1 drift = warming |
| **0x680 B0** | D only | 0x03->0x01 at startup, toggles 0/1 during operation, 0x01->0x03 at shutdown | **BMS communication mode** |
| **0x0FF B6** | D only | Rapid changes during transitions (0x7A->0x30->0x2E), settles | **Module status / handshake** |

---

### Key Observations

1. **The gaps between clusters confirm the "slow key-on" description.** There's a 6.4s pause between wake and key-to-ON, and a 2s pause between ON and START -- the user was deliberately waiting at each key position.

2. **0x052 is the crank signal.** The 0x04<->0x0C toggling at ~250ms intervals during cluster #3 only is textbook starter engagement. It stops once the vehicle is "running" (EV equivalent = precharge complete).

3. **0x378 B6 is almost certainly related to DC link voltage.** It ramps monotonically from 0 to 0x12 (18 decimal) during the crank/precharge window. Cross-reference: the charging analysis shows the pack voltage is ~352V. If 0x12 = 18 and represents full voltage, the scale factor might be ~19.5V/LSB (18 x 19.5 = 351V). Need to extract the full timeseries to verify.

4. **The D CAN 0x9C->0x0A wake pattern is distinctive.** All bytes of 0x200-0x203 start at 0x9C (156 decimal) -- this is almost certainly a sentinel/invalid value. The real readings (~10-11) then drift slowly upward by +1 count over 5-10 minutes, consistent with battery module temperatures increasing from an ~ambient baseline.

5. **HVAC engagement (cluster #6) is separate from ready mode (cluster #4)** -- there's an 11s gap. This matches the capture notes: "may have turned on cabin fan before starting drive instead of after."

6. **Cluster #81 (t=700-708s) is the shutdown sequence** -- 109 transitions, essentially the mirror image of the startup. Every signal reverts: 0x052 stops, 0x1D7 B0 -> 0, 0x378 B6 -> 0, 0x491 -> 0, 0x275 -> 0, etc.

### Recurring Patterns After Startup (clusters #9-#80)

- **0x248 B0/B1 heartbeat**: A repeating pattern (0x0B->0xCB->0x8B->0x0B with B0 toggling 0<->8) appears every ~30-130s throughout the log. This is likely a diagnostic/network management heartbeat.
- **0x2C1 B1/B3 slow drift**: Very slow decreasing count (~1 LSB per 20-60s). Temperature-like, cooling.
- **0x418/0x240 HVAC modulation**: Clusters #72-#80 (t=648-696s) show intense HVAC cycling -- 0x418 B0/B4 toggling between states, 0x240 B6 modulating rapidly. This suggests the defroster was working hard.
- **Traction control events** (clusters #73, #75, #80): 0x052, 0x271, 0x308, 0x55C all change in the last ~50s of driving. The 0x052 B0: 0x0C->0x08 and 0x308 B0 changes correlate with the "traction control kicking in" noted in the capture description.

---

### AC-Compressor — CONFIRMED (0x410 command, 0x439 status)

**Hardware:** Ford AM64-19D623-AB electric scroll compressor, 500 kbps CAN, 220-400V DC, max 6000 rpm, max 4.5 kW.

**Source docs:** `projects/coda/components/AC-Compressor/CAN control message.txt` and `AC-Compressor2023.pdf`

**Key finding:** The signal definitions in `CAN control message.txt` use byte-reversed bit numbering (`actual_byte = 7 - doc_byte`). Resolutions and widths are correct but byte positions must be transformed. The corrected layout is now in `CODA-B-CAN.dbc`.

**0x410 — AC_Compressor_Command (from HVAC controller, 9.6 Hz):**

| Actual Byte | Signal | Resolution | Observed |
|---|---|---|---|
| B7 | max_pwr_consumption | x 0.1 kW | 8.1 kW (power limit) |
| B6 | target_compressor_speed | x 60 rpm | 0-1500 rpm (960 rpm steady) |
| B2 bit 6 | compressor_on_off | boolean | on at t=31.00s |
| B2 bit 3 | CASS_on_off | boolean | not observed active |
| B2 bit 1 | warmup_cycle_cntr_incr | boolean | not observed active |

**0x439 — AC_Compressor_Status (from compressor, 10 Hz):**

| Actual Byte | Signal | Resolution | Observed |
|---|---|---|---|
| B0 bits 0-1 | COMPRESSOR_STATUS | enum | 3=Off, 0=Standby, 1=Running |
| B1 | ACTUAL_COMPRESSOR_SPEED | x 60 rpm | 0-1800 rpm (960 rpm steady) |
| B2 | ACTUAL_POWER_CONSUMPTION | x 0.1 kW | 0-0.9 kW (0.1-0.2 kW steady) |

**Timeline in this log (defroster mode):**
- t=9.7s: 0x439 appears, status=Off (0x03), all zeros -- HV not yet available
- t=20.66s: status Off->Standby (0x00) -- HV precharge complete, compressor ready
- t=31.00s: 0x410 compressor_on_off set to 1 -- HVAC controller commands run
- t=31.36s: status Standby->Running (0x01), 360ms response latency
- t=31.76s: spool-up overshoot to 1800 rpm / 0.9 kW, settles to 960 rpm / 0.2 kW
- t=701.81s: shutdown, status Running->Off (0x03)

**Validation:** target speed (0x410 B6 mean=16.3) matches actual speed (0x439 B1 mean=16.2). PDF's off-state frame `03 00 00 00 00 00 00 00` confirmed. DBC decode tested against actual log frames.

**Note:** Running at 960 rpm / 0.2 kW is for defroster mode (dehumidification), not cabin cooling. The compressor was operating at ~16% of max speed.

---

### Cross-References

- **0x275 B0/B1**: Confirmed discharge/charge limits from bonnydoon-limp-analysis.md. B0=discharge limit (x2 for amps), B1=charge limit. B4=binary HV active flag. B6 seen here stepping 0->4->0xC at startup may be a status/mode byte.
- **0x381**: Pack min/max cell voltages at 1 Hz (confirmed from bonnydoon analysis).
- **0x279/0x27D**: Charger signals (confirmed from charging-analysis.md) -- not relevant during driving but share the B CAN bus.
- **0x390 B0**: ~~BMS status byte (confirmed from bonnydoon: 0x80=startup, 0x8D=driving)~~ **Corrected 2026-10-30: `FrontInletAirTemp`** (raw − 128 °C; see `bonnydoon-limp-analysis.md`, which already corrects it). Seen here: B2/B3 (`ReturnAirTempPsg`/`ReturnAirTempDrv`) change 0x80->0x89 at wake.

---

### Battery Thermal Management — Cold-Start Derating (defroster2 log, 2026-03-02)

Analysis of `pack_thermal_correlation.png` (0x276 B7=BattFanPWM × 0x382 cell temps × 0x275 limits). **Note on byte assignment**: 0x276 B5=PTCHeaterPWM, B7=BattFanPWM (corrected by fine sweep 2026-02-26; prior docs may use "BattFanPWM" loosely without byte — in this section "BattFanPWM" always refers to B7).

**Conditions:** Cold morning start. Pack at ~11°C avg at key-on.

**Observation:** The BattFanPWM (0x276 B7) runs at 24–32% for the first ~330s of the drive then steps down and cuts off completely at ~t=395s. Given ambient conditions and the PTC heater running simultaneously, the fan is almost certainly circulating warm air through the battery pack (heating mode), not cooling it.

**Correlation with limits:**
- BattSentChargeLimit (0x275 B1) starts at ~120A and rises to ~145A over the same ~330s window, then holds flat once the fan shuts off. The ~25A gain corresponds directly to cold-derating being lifted as the pack crosses the target temperature threshold.
- BattSentDischargeLimit (0x275 B0) hits 400A essentially immediately at startup and holds throughout — LFP discharge derating activates at a colder threshold than charge derating, so 11°C was not cold enough to restrict discharge.
- Cell temps (0x382) only move ~1°C (11→12°C avg) across the entire drive. The pack needed minimal thermal input to cross the charge-derating knee.

**Interpretation:** The pack was just barely below the BMS charge-derating threshold at startup. The battery thermal system (BattFanPWM circulating warm air) applied proportional heating — fan peaks at ~32% around t=100s then tapers as the pack approaches target — and the charge limit responded in lockstep. Once the threshold was cleared (~t=330–395s) the fan shut off and the limit stabilised. This is consistent with standard LFP cold-charge protection: regen into a very cold LFP cell risks lithium plating, so charge derating is more aggressive than discharge derating at the cold end.

**Key thresholds (inferred from this log):** Discharge limit unaffected at 11°C; charge limit begins recovering above ~11°C; full charge limit (~145A) reached at ~12°C. A colder start would show a more dramatic recovery curve.

---

### Vehicle Fault Light Investigation (2026-03-03)

**Question:** What leads/correlates with the RED vehicle fault light turning on at t=136s in the defroster2 log?

**Signal chain (confirmed):**
- 0x270 B0: 0x00 -> 0x12 at t=136.098s — BMS declares fault code 18
- 0x271 B0: LampReq OFF -> RED at t=136.183s (85ms later) — GWM relays to dashboard lamp
- Fault persists for rest of drive; clears to 0x00 at key-off (t=701.88s)

**Cross-log 0x270 B0 survey (all logs scanned):**

| Log | 0x270 transitions | Lamp lit? |
|-----|------------------|-----------|
| `codadriveslowturnonwithdefroster.log` | 0x00 -> 0x10 at t=20s (startup), persists whole drive | No |
| `codadriveslowturnonwithdefroster2.log` | lamp test (0x01->0x02->0x00), then 0x00->0x12 at t=136s | Yes (RED) |
| `frombonnydoon.log` | lamp test, then 0x00->0x12 at t=63.57s | Yes (RED) — limp mode drive |
| `DCDCRUNNingwithoutkeyon then key on.log` | starts 0x10, steps 0x10->0x11->0x12->0x10 during key-on | No (0x12 transient only) |
| `chargepointcharge.log` | starts at 0x10, stays there | No |
| `drivewaycharge2/4.log` | 0x10 appears after hours of charging | No |
| `prndnrp...log` | starts at 0x10 | No |
| All other-logs | 0x00 or lamp test only | No |

**Fault code 16 (0x10) vs fault code 18 (0x12):**
- 0x10 (bit 4 only): a non-lamp BMS condition. Appears at startup in drives that begin from near-full charge, and during/after charging sessions. Does not trigger 0x271 LampReq. Likely a high-SoC or post-charge housekeeping state.
- 0x12 (bit 4 + bit 1): the fault that triggers the RED lamp. Appears only in defroster2 (mid-SoC drive, 91.5%) and bonnydoon (limp mode). Cleared by key-off.
- Key-on lamp test in 0x270: 0x00->0x01->0x02->0x00. These are test codes (1=yellow test, 2=red test), separate from the real fault codes.

**What B CAN showed at the moment of the defroster2 fault (t=136s):**
- PackCurrent: only -12.8A (very light discharge, coasting)
- Cell Vmin (0x381): 3213 mV — completely normal
- Cell Vmax: 3258 mV — normal
- Temps (0x382): unchanged
- DischgLim (0x275 B0): still 400A — BMS did not reduce limits
- MCM: 3-4 Nm torque, 3-5A HV current at ~2440 RPM (steady cruise)
- 0x270 B6/B7: 0x40/0xC8 — static, unchanged before and during fault (not fault indicators)
- 0x271 VehicleFault (B1-B4): 0x00000000 — no fault code word populated

**Prior UV sag events in defroster2 (before the fault):**
- t=87-92s: hard acceleration from near-stop, peak pack current 120A, Vmin reached 3053 mV
- t=104-108s: second hard acceleration, peak 86A, Vmin reached 3104 mV
- Both events on a cold 12°C pack (BMS charge derating still lifting)
- Fault appeared ~45s after the last significant discharge event, at a quiescent moment

**Comparison with defroster1 (no lamp):**
- Defroster1 started from near-full charge (Vmin ~3300 mV); 0x10 set during startup before any driving
- Defroster1 had far worse sags during the drive: Vmin reached 2916 mV at t=407s (vs 3053 mV worst in defroster2)
- Despite much deeper sags, 0x270 never escalated to 0x12 in defroster1 and 0x271 stayed OFF

**Conclusion:** The RED fault light is driven by BMS fault code 18 (0x270 B0 = 0x12), relayed by the GWM (0x271 LampReq = RED). The cause of the BMS declaring code 18 is an **internal BMS diagnostic not fully traceable from external CAN**. None of the observable B CAN signals (pack current, cell min/max voltage, temperature, limits) show an anomaly at the moment the fault fires. The defroster1 comparison actively contradicts a simple UV-threshold hypothesis — that log had sags nearly 150 mV deeper with no fault code 18. The BMS is likely running an internal cell impedance, coulomb counter, or multi-condition evaluation that concludes a fault condition exists. Without BMS firmware access, the specific trigger cannot be determined.

---

## Future Sessions to Analyze

- `frombonnydoon.log` -- long drive with limp mode. Check startup sequence and compare driving-phase signals.
- Any future captures with different HVAC settings to isolate 0x418/0x391/0x55C behavior.
