# Traction Inverter Control

**Investigation started:** 2026-03-29
**Log used for Phase 1:** `projects/vtrux/logs/vtruxevapdrivelog4part2.log` (P2, 118 MB, no cruise, 342.5s)
**Scratchpad:** `projects/vtrux/notes/artifacts/traction-inverter-control.py`

---

## Phase 1 Findings — Traction Torque Command Identification (2026-03-29)

### Correction: 0x451 is NOT the TRAC torque feedback

The investigation plan and `epri-obd-bus.dbc` both name 0x451 B0-B1 as `TRAC_Mot_Trq`. This is wrong. In P2, 0x451 appears on Bus 1 (OBD bus) at 39.3 Hz with bytes 0-3 constant at 0x00 and only B4 varying (0-110). This does not match the expected ~100 Hz high-variance torque feedback.

**EPRI data review (2026-03-29):** 0x451 is the standard GMLAN message `Gateway_LS_General_Information`. B0-B3 carry airbag severity flags (all zero = no deployment). B4 is `Climate_Control_Front_Blower_Fan_Speed` (uint8, scale 0.392157%, 0.0-100.0%). The observed B4 range 0-110 decodes to 0-43.1% fan speed. This is a GM-standard broadcast that passes through the OBD bus; it has no Via-specific encoding.

The Ghidra decompile confirms the EPRI app read `*(ushort *)(puVar20+2)` from the 0x451 handler — i.e., CAN B0:B1 — but that field contains airbag flags, not torque. The 2-byte CAN ID prefix convention (`puVar20[0:1]` = CAN ID, `puVar20[2+]` = CAN data) means the formula is reading CAN B0:B1 correctly; the earlier "B2:B3" label in the Ghidra session notes was a heading transcription error, not a byte offset error. The core mistake is that the plist misidentified the message as TRAC MCU output.

**DBC status:** `epri-obd-bus.dbc` 0x451 `SG_ TRAC_Mot_Trq` entry removed (2026-03-29). Message retained as a stub with conflict documented in `CM_ BO_`. GMLAN signal definitions for this message belong in a GMLAN DBC.

**Effect on EPRI conclusions:** Limited. EPRI's primary findings (BMS SOC, current limits, charge state machine, fault codes) all come from the PT bus (`Via_CANid_List.plist`): 0x420, 0x440, 0x410, 0x430, 0x050, 0x051, etc. None are affected. The OBD bus TRAC signals were secondary. B4 ≈ 43% fan speed during driving would have appeared as a near-constant nonsensical "torque" value and been treated as unavailable data.

**The actual TRAC torque feedback is 0x442 B0-B1:**
- 98.1 Hz, DLC 7, Bus 1 (OBD)
- B0-B1: LE uint16 centered at 32768 (neutral = 0 Nm); range 31683-35796 in this log
- B3, B5 are low-entropy status bytes; B6 is a rolling counter (nibble, 0x00/0x10/0x20/... steps)
- Structurally identical to 0x471 (GENE torque feedback, PT bus): same rate, DLC, byte layout, center encoding
- Cross-validated against 0x5A2 B4-B5 (VCM rebroadcast on PT bus): r=0.9998, mean residual -159 counts, max residual 819 counts — consistent with genuine control-loop feedback, same ballpark as GENE's 0x471 vs 0x051 relationship

**ID offset correction:** The -0x020 offset stated in the plan for the GENE→TRAC high-group mapping is wrong. Actual offset: 0x471 - 0x442 = **-0x02F** (not -0x020). The low-group command offset (-0x010) is unchanged.

**Revised GENE/TRAC symmetry table:**

| Signal type | GENE MCU (PT bus) | TRAC MCU (OBD bus) | Offset |
|-------------|-------------------|--------------------|--------|
| RPM response | 0x054 | 0x044 | -0x010 |
| Torque feedback | 0x471 | **0x442** | -0x02F |
| Thermal (assumed) | 0x479 | **0x449?** | -0x02F (unverified) |
| HV bus info | 0x482 | 0x462 | -0x020 (anomaly — doesn't fit -0x02F) |
| **Torque command** | **0x051** | **0x041** | **-0x010** |

Note: 0x462 does not fit the -0x02F pattern. The high-group offset may not be uniform; 0x462 confirmed in DBC and survey (97.7 Hz on OBD bus). This warrants a separate check when mapping remaining TRAC IDs.

### 0x5A2 Divergence Window

One significant divergence between 0x442 B0-B1 (direct TRAC) and 0x5A2 B4-B5 (VCM rebroadcast) was observed at **t=13.5-19.5s** (~6 seconds, 603 frames). During this window the two signals differ by more than 500 counts, suggesting either a transient state at log start or the VCM applying a different value when rebroadcasting. The remainder of the log tracks within 819 counts (rms 220).

### Command Signal: 0x041 B1-B2 Confirmed

**0x041 is the VCM-to-TRAC-MCU traction torque command.** Found on Bus 1 (OBD bus) at 100.0 Hz, DLC 6.

**Signal structure:**

| Byte | Content |
|------|---------|
| B0 | Status nibble (values 8-11 observed) |
| B1-B2 | Torque command — LE uint16, centered at 32768 (neutral); >32768 = motoring, <32768 = regen |
| B3 | 0xFF constant |
| B4 | 0x7F constant |
| B5 | Rolling counter, nibble 0x0-0xF (identical structure to 0x051 B5) |

**Encoding:** identical to 0x051 B1-B2 (generator torque command). Same center (32768), same counter structure, same status-byte position.

**Correlation results:**

| Metric | Value |
|--------|-------|
| Pearson r vs 0x442 B0-B1 feedback (full-log) | **0.9994** |
| Windowed r (30s windows, active only) | 0.9986 – 0.9995 |
| Pearson r vs throttle pedal 0x592 B2-B3 (full-log) | **0.9782** |
| Pearson r vs throttle (motoring frames only) | **0.9862** |

### Regen Direction (Step 5 — P2 log)

- 7.0% of frames have cmd < 32768 (regen torque); 80.8% have cmd > 32768 (motoring); 12.2% neutral
- Regen depth is shallow: mean 32563, std 232 counts, max deviation -1086 from neutral (-136 Nm)
- r(cmd vs brake pedal 0x592 B4-B5) during regen frames: **-0.034** — near zero
- P2 regen is coasting-driven; brake pedal was not significantly exercised in that log.

### Regen Bidirectionality Confirmed — climit log (2026-03-29)

Validated using `vtruxcurrentlimitingtest.log` (30-min drive with deliberate brake-press regen and CCL event). Scratchpad phase: `climit_regen`.

**0x041 B1-B2 is a single bidirectional torque command — no separate regen signal exists.**

| Metric | Value |
|--------|-------|
| Regen frames (cmd < 32768) | 57,774 / 180,972 (31.9%) |
| Max regen depth | -2298 counts (-287.2 Nm) |
| Max motoring peak | +3040 counts (+380.0 Nm) |
| r(cmd vs 0x442 feedback) during regen | **+0.9982** |
| r(cmd vs brake 0x592 B4-B5) during regen | -0.4513 |

The r=0.9982 cmd-vs-feedback during regen matches the motoring-regime correlation, confirming the same signal and encoding governs both directions. The moderate brake correlation (-0.45) reflects the CCL actively clamping regen depth during this test — the deepest regen frames (t≈66s, -287 Nm) show brake held at a constant position while the CCL limit, not pedal depth, sets the command floor.

Encoding is identical in both directions: LE uint16 centered at 32768, values above = motoring, values below = regen. Scale 0.125 Nm/count (unconfirmed, consistent with GENE symmetry).

### Command Architecture — VCM Closes the Limit Loop (2026-03-29)

Investigated using `vtruxcurrentlimitingtest.log` discharge limit event (t=598s+). Scratchpad phase: `climit_discharge_divergence`.

**0x041 is an achievable torque command, not a desired-torque wish list.** The VCM already accounts for battery DCL, flux weakening, and other limits before sending the command. The TRAC MCU follows it; it does not perform unilateral limiting behind the VCM's back.

| Window | n | cmd_mean | fbk_mean | residual_mean | residual_max | r |
|--------|---|----------|----------|---------------|--------------|---|
| pre-limit t=400-598s | 5,323 | 695 | 724 | -28.5 | 285 | 0.9995 |
| during-limit t=598-700s | 8,869 | 631 | 661 | -30.6 | 228 | 0.9993 |
| post-limit t=700-900s | 16,265 | 347 | 367 | -20.7 | 92 | 0.9987 |

r stays ≥0.999 across all windows. cmd_mean tracks the drop from 695 → 631 → 347 counts as the limit bites — the VCM is actively reducing the command in real time, not holding a high request. No frames had |cmd-fbk| > 500 counts during motoring. The small consistent negative residual (~-28 counts, ~3.5 Nm at assumed scale) is normal steady-state error in a torque control loop where feedback runs slightly above command.

This also supports the Nm interpretation of the encoding: the VCM runs a closed loop that converges command to feedback, which only makes sense if both are in the same units.

---

## Phase 2 — Cruise Control Re-Investigation (2026-03-29)

**Logs used:** `vtruxevapdrivelog4.log` (P1, cruise t=706–1108s) and `vtruxanotherevaplogpart2.log` (cruise t=994–1413s). Cruise windows identified from 0x644 B2 mode nibble (0xA = active).
**Scratchpad phases:** `cruise_hyp_ab`, `cruise_regen_scan` in `traction-inverter-control.py`

### Result: **Hypothesis A confirmed — VCM closes the speed loop**

The traction torque command (0x041 B1-B2) varies continuously throughout both cruise windows and includes regen torque during downhill sections. The inverter does not run its own speed loop; it follows the VCM's torque command (r=0.9994 cmd-vs-feedback from Phase 1).

### Per-cruise-window statistics (values centered at 32768)

| Log | Cruise window | n frames | mean | std | min | max | regen frames |
|-----|--------------|----------|------|-----|-----|-----|-------------|
| evaplog4 P1 | t=706–1108s (402s) | 40,146 | +344 (+43 Nm) | 217.9 | −341 (−42.6 Nm) | +822 | 1,474 (3.7%) |
| anotherevap P2 | t=994–1413s (419s) | 41,873 | +397 (+50 Nm) | 218.9 | −142 (−17.8 Nm) | +1189 | 963 (2.3%) |

The command is actively varying (std ~218 in both logs) and spans both motoring and regen. The std is consistent across two independent runs of the same route. The mean torque (+43–50 Nm) is physically plausible for steady-state highway cruise against aero drag and rolling resistance. For reference, peak motoring torque in `vtruxcurrentlimitingtest.log` (hard acceleration) was +3040 counts (+380 Nm), so steady-state cruise runs at roughly 11–13% of peak motor capability.

### Regen during cruise — downhill sections

Regen occurs in brief 4–11 second blocks, consistent with downhill sections. It is shallow compared to brake-commanded regen (max −287 Nm in the climit log).

**evaplog4 P1 regen blocks:**

| Block | Duration | Frames | Min torque |
|-------|----------|--------|-----------|
| t=835.7–836.5s | 0.8s | 38 | −3.2 Nm |
| t=839.7–839.9s | 0.2s | 19 | −3.2 Nm |
| t=995.0–1006.4s | 11.4s | 950 | −15.1 Nm |
| t=1061.6–1062.5s | 0.9s | 38 | −4.4 Nm |
| t=1090.6–1090.9s | 0.3s | 30 | −2.8 Nm |
| t=1101.2–1102.1s | 0.9s | 38 | −4.2 Nm |
| t=1104.2–1107.8s | 3.6s | 361 | **−42.6 Nm** |

**anotherevap P2 regen blocks:**

| Block | Duration | Frames | Min torque |
|-------|----------|--------|-----------|
| t=994.4–994.5s | 0.1s | 3 | −8.0 Nm |
| t=1149.6–1155.9s | 6.3s | 444 | **−17.8 Nm** |
| t=1311.1–1320.8s | 9.7s | 516 | −8.1 Nm |

### Superseded conclusion from Phase 5-8

The prior "no torque command found during cruise / inverter closes the loop" conclusion from `cruise-control-analysis.md` Phase 5-8 was based on PT bus scans only. The VCM-to-TRAC-MCU command (0x041) is on the OBD bus and was not included in those scans. Hypothesis B is refuted.

---

## Valid Findings From Prior Cruise Investigation

The original `cruise-control-analysis.md` (Phases 1-9) produced these still-valid results:

| Finding | Location | Status |
|---------|----------|--------|
| 0x1E1 B5 cruise state pulse tiers (16-28 baseline, 48-60 Set, 80-92 Engage/Cancel) | Phase 1-2 | VALID |
| 0x644 B2-B3 cruise speed setpoint (12-bit, 0.125 km/h/count, 1 km/h/press) | Phase 9 | VALID |
| CruiseMode nibble encoding (0x8=idle, 0x9=throttle override, 0xA=active) | Phase 9 | VALID |
| Two cancel mechanisms (throttle override vs manual button) | Phase 9 | VALID |
| Throttle simulation ruled out | Phase 3 | VALID |
| Phase 5-8 conclusion "no torque command found" | Phase 5-8 | **INCOMPLETE** — PT bus only; OBD bus not scanned |
