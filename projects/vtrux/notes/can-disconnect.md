# Vtrux CAN Disconnect Tests

Structured notes for experiments where a specific connector or module is physically
disconnected while the dongle captures all three buses.

**Interpretation rules:**
- `P` = present after disconnect (definitively NOT sourced through that path)
- `A` = absent after disconnect (sourced through that path, OR collateral from a wake/enable line on that connector)
- `?` = not captured in this test or uncertain

**Attribution caveat:** The "Module / Attribution" labels in the ID presence matrix are working hypotheses. Do **not** use these labels as source attribution in other analyses. Only use module attributions that have been confirmed and promoted to `Vtrux.md`.

**Known errors flagged 2026-06-06 (during trailer-brake Phase 5):**
- The "ECM / EBCM -- native OBD" row for 0x189, 0x1A6, 0x1DF (and others) is a lumped-bucket label that conflates sources. Forum reverse-engineering identifies 0x189 as TCM-to-ECM torque request and 0x1A6 as a TCM TX ID. Other IDs in that row (e.g. 0x2F9, 0x1E9) are EBCM; 0x2C3 is ECM; 0x1E1 / 0x1F1 are gateway.
- The Vehicle bus row attribution "0x1A3, 0x1A6 -- VCM bridges to Vehicle bus" is wrong for 0x1A6. The reference log (`genlog-survey.json`) shows 0x1A6 has never been on the Vehicle bus, so VCM is **not** bridging it. 0x1A3 IS bridged correctly. 0x1A6 should be reclassified as OBD-only, not bridged.

Cross-reference for these corrections: `projects/vtrux/notes/trailer-brake-investigation.md` Phase 5.

For T2, the "A" column reflects IDs that dropped due to the HV LV disconnect event and its
cascade effects. The deliberate 12V battery cycle at the end of the same log (t=118s) caused
additional dropouts — those IDs are marked `P` for T2 because their dropout was a deliberate
follow-on action, not caused by the HV LV connector pull.

---

## Test Inventory

| Test | Date | What was disconnected | Log |
|------|------|-----------------------|-----|
| [T1] PE pump CAN | before 2026-02 | PE coolant pump CAN connector | `logs/vtruxunplugpumpthenhvbatterylvconnector.log` (~t=34s) |
| [T2] HV battery LV connector | before 2026-02 | HV battery LV (BMS power/CAN) connector | `logs/vtruxunplugpumpthenhvbatterylvconnector.log` (~t=75s) |
| [T3] VCM B-connector | 2026-03-06 | Woodward ECM-5554 VCM B-connector | `logs/vtruxwoodwardbconnectordisconnected.log` |
| [T4] Gene inv fuse | 2026-04-17 | Generator inverter fuse (fuse out at log start; inserted ~t=102s) | `logs/vtrux_no_gene_inv_fuse.log` |

---

## ID Presence Matrix

### Powertrain Bus

IDs from the reference log (`logs/generator on then off.log`, Bus 3, 93 IDs).

| ID(s) | Module / Attribution | T1 Pump | T2 BMS LV | T3 B-conn | T4 Gene inv fuse |
|-------|---------------------|---------|-----------|-----------|-----------------|
| **0x18FF0320** | PE coolant pump (SA=0x20) | **A** | P | A | P |
| 0x370, 0x371, 0x372, 0x373, 0x374, 0x375 | BMS -- function unknown | P | **A** | A | P |
| 0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460 | BMS status / SoC / cell voltages | P | **A** | A | P |
| 0x506, 0x507 | BMS -- function unknown | P | **A** | A | P |
| 0x474 | Unknown -- source unresolved; drops ~32s after BMS pull. Present even with gene inv fuse removed (see T4 anomaly note). | P | **A** (~32s after BMS pull) | A | P |
| 0x478 | Unknown -- source unresolved; drops ~32s after BMS pull | P | **A** (~32s after BMS pull) | A | **A** |
| 0x480, 0x481 | Unknown -- source unresolved. Previously suspected traction inverter; attribution invalidated — traction inverter (TRAC MCU) is on OBD bus, not PT bus (EPRI 2026-03-28). Drops ~32s after BMS pull. | P | **A** (~32s after BMS pull) | A | **A** |
| 0x55C | TCM heartbeat (BorgWarner) -- drops ~32s after BMS pull | P | **A** (~32s after BMS pull) | A | P |
| 0x580 | Unknown -- source unresolved; drops ~32s after BMS pull | P | **A** (~32s after BMS pull) | A | P |
| 0x619 | Unknown -- source unresolved. Previously suspected traction inverter; attribution invalidated — traction inverter is on OBD bus (EPRI 2026-03-28). Drops ~32s after BMS pull. | P | **A** (~32s after BMS pull) | A | P |
| 0x053, 0x054 | VCM-sourced -- drops ~33s after BMS pull | P | **A** (~33s after BMS pull) | A | **A** |
| 0x470, 0x471, 0x472, 0x475, 0x479, 0x482 | Generator inverter (GENE MCU) -- drops ~33s after BMS pull. Traction inverter (TRAC MCU) is on OBD bus (EPRI 2026-03-28); these are generator-only PT bus IDs. | P | **A** (~33s after BMS pull) | A | **A** |
| 0x681 | Unknown -- source unresolved; drops ~33s after BMS pull | P | **A** (~33s after BMS pull) | A | P |
| 0x0868A047, 0x0870A047 | Sanden EAC compressor (SA=0x47) -- drops ~33s after BMS pull | P | **A** (~33s after BMS pull) | A | P |
| 0x18FECAB3, 0x18E8FFB3, 0x18FFD4B3, 0x18FFD6B3, 0x1CEBFFB3, 0x1CECFFB3 | Bel DCDC (SA=0xB3) -- role unknown. 0x18FECAB3 drops ~3s after BMS pull and only returns after key-on; others drop ~33s after BMS pull. | P | **A** (various, see note) | A | P |
| 0x050, 0x051, 0x052 | VCM EV torque / RPM commands | P | P | **A** | P |
| 0x08C | VCM -- function unknown | P | P | **A** | P |
| 0x308 | TCM park pin (BorgWarner) | P | P | **A** | P |
| 0x395 | Generator phase current (VCU-sourced) | P | P | **A** | P |
| 0x3FE | Unknown | P | P | **A** | P |
| 0x505 | Unknown | P | P | **A** | P |
| 0x592, 0x594, 0x595, 0x596, 0x597, 0x598, 0x599, 0x5A0, 0x5A2 | VCM driver inputs / motor signals / SoC | P | P | **A** | P |
| 0x600, 0x601, 0x617, 0x625, 0x626, 0x62F | VCM status / generator active flags | P | P | **A** | P |
| 0x639, 0x63A, 0x63C, 0x63D, 0x63F, 0x640, 0x644, 0x645, 0x646, 0x647, 0x648, 0x649, 0x64A, 0x64B | VCM BMS relay cluster | P | P | **A** | P |
| 0x651, 0x6A0 | VCM -- function partially known | P | P | **A** | P |
| 0x06000001, 0x06000002, 0x0C0CA040 | VCM extended IDs | P | P | **A** | P |
| 0x18EF2000, 0x18EFB3FE | VCM / Bel DCDC extended IDs | P | P | **A** | P |
| **0x390** | Unknown (survives all tests) | P | P | **P** | P |
| **0x61F** | Unknown (survives all tests) | P | P | **P** | P |
| 0x473 | Rare / motor-active-only | P | ? | A | **A** |
| 0x483, 0x484 | Rare / motor-active-only. Appear ~1s after the rest of the GENE MCU group on fuse insertion (103.16s vs 102.12s for the others -- see T4). | P | ? | A | **A** |
| 0x000, 0x71E, 0x18DB1033 | Rare / transient (startup-only frames) | P | ? | A | ? |

---

### OBD Bus

T1 and T2 tested PT bus modules; GM buses were not directly affected. All OBD bus IDs are
assumed present for T1 and T2 (marked `-`). T4 only removed a PT bus fuse; OBD bus not
directly affected (marked `-`).

| ID(s) | Attribution | T1 Pump | T2 BMS LV | T3 B-conn | T4 Gene inv fuse |
|-------|-------------|---------|-----------|-----------|-----------------|
| 0x0C9, 0x3D1, 0x3D3, 0x3E9 | ECM-native engine/speed signals | - | - | P | - |
| 0x0AA, 0x0BE, 0x0D3 | ECM/EBCM-native on OBD bus (VCM bridges these to Vehicle bus) | - | - | P | - |
| 0x1C3, 0x1C4, 0x1C5 | Real ECM torque/engine data on OBD bus (VCM replaces on Vehicle bus) | - | - | P | - |
| 0x189, 0x18E, 0x1A1, 0x1A3, 0x1A6, 0x1AA, 0x1AF, 0x1BA, 0x1C6, 0x1CF, 0x1DF | ECM / EBCM -- native OBD | - | - | P | - |
| 0x1E1, 0x1E9, 0x1ED, 0x1F1, 0x1F4, 0x287, 0x2C3, 0x2F9 | ECM / EBCM -- native OBD | - | - | P | - |
| 0x3C1, 0x3C9, 0x3F1, 0x3F9, 0x3FB, 0x3FC | ECM / chassis -- native OBD | - | - | P | - |
| 0x451 | **Conflict** -- EPRI Ghidra decompile names this TRAC_Mot_Trq (traction motor torque), which would make it a TRAC MCU message (should be A at T3). Marked P here from the T3 log, but traction inverter may not broadcast torque messages at idle/rest, so 0x451 could simply have been absent from the capture window rather than genuinely surviving T3. Needs re-verification with an active-motor T3 log. | - | - | P | - |
| 0x4C1, 0x4C5, 0x4C7, 0x4D1, 0x4E1, 0x4E9, 0x4F1, 0x4F3 | Chassis modules -- native OBD | - | - | P | - |
| 0x4C9 | Source unknown. Present on both GM buses in T3 without VCM — broadcaster has native connections to both buses. Not VCM (ruled out by T3). Not shift box (shift box disconnect: 0x4C9 kept broadcasting after box unplugged). Hypothesis: Via-added electronics under the dashboard (possibly IPC driver hardware). | - | - | P | - |
| 0x589, 0x772 | Unknown -- native OBD bus | - | - | P | - |
| 0x0D1 | Shared ECM signal | - | - | P | - |
| 0x040, 0x041, 0x042, 0x043, 0x044 | TRAC MCU (traction inverter) native OBD messages and/or VCM-forwarded commands to traction inverter. EPRI Ghidra decompile (2026-03-28) confirms 0x044 = TRAC_RotSpd (traction motor speed) -- native traction inverter data, not VCM-generated content. Previously labeled VCM-generated based on freq/DLC match with PT 0x050-0x054 (may be coincidental or command-forwarding by VCM). | - | - | **A** | - |
| 0x0C7 | VCM-generated on both GM buses | - | - | **A** | - |
| 0x0F1 (DLC=4 variant) | VCM-generated on OBD bus (Vehicle bus has DLC=6 version from a different source) | - | - | **A** | - |
| 0x0F9 | VCM-generated TCM stub | - | - | **A** | - |
| 0x19D | VCM-generated, unknown role | - | - | **A** | - |
| 0x1C7 | VCM-generated EBCM substitute on OBD bus (real EBCM version lives on Vehicle bus) | - | - | **A** | - |
| 0x1F5 | VCM-generated frozen-Park on OBD bus | - | - | **A** | - |
| 0x441, 0x442, 0x443, 0x444, 0x445, 0x446, 0x449, 0x44A | Likely TRAC MCU (traction inverter) feedback on OBD bus -- symmetric to GENE MCU 0x471-0x479 on PT bus. EPRI names 0x0451 = TRAC_Mot_Trq (traction motor torque). Previously labeled VCM-generated based on freq/DLC match with PT 0x470-0x479. | - | - | **A** | - |
| 0x460, 0x461, 0x462, 0x463, 0x464 | Likely TRAC MCU feedback -- symmetric to GENE MCU 0x480-0x484 on PT bus. EPRI names 0x0462 = TRAC_HighPwr_Curr/TRAC_HighPwr_Volt (traction HV bus). Previously labeled VCM-generated based on freq/DLC match with PT 0x480-0x484. | - | - | **A** | - |
| 0x661 | VCM-generated/bridged on OBD (same content as PT 0x681 and Vehicle 0x681) | - | - | **A** | - |
| 0x7E0, 0x7E8 | OBD scanner session (not VCM, not present when no scanner is active) | - | - | **A** | - |

---

### Vehicle Bus

T1 and T2 did not directly affect the Vehicle bus. All Vehicle bus IDs assumed present
for T1 and T2 (marked `-`). T4 only removed a PT bus fuse; Vehicle bus not directly
affected (marked `-`).

| ID(s) | Attribution | T1 Pump | T2 BMS LV | T3 B-conn | T4 Gene inv fuse |
|-------|-------------|---------|-----------|-----------|-----------------|
| 0x17D | EBCM-native (Vehicle bus anchor) | - | - | P | - |
| 0x1E5, 0x500, 0x514, 0x52A, 0x52B, 0x530, 0x778, 0x780, 0x785, 0x788 | Vehicle native anchors | - | - | P | - |
| 0x1C7 | Real EBCM data on Vehicle bus (VCM generates a separate substitute on OBD bus) | - | - | P | - |
| 0x1E9 | Real EBCM chassis status (VCM substitutes frozen version on OBD) | - | - | P | - |
| 0x4C9 | Source unknown — not VCM, not shift box (see OBD bus table and 0x4C9 attribution correction below) | - | - | P | - |
| 0x0D0, 0x0D1, 0x0F1, 0x120, 0x121, 0x12A, 0x135, 0x137, 0x139, 0x140, 0x148 | Native chassis modules | - | - | P | - |
| 0x160, 0x182, 0x185, 0x18E, 0x1A1, 0x1AA, 0x1AF, 0x1BA, 0x1C6, 0x1CF | Native chassis modules | - | - | P | - |
| 0x1E1, 0x1ED, 0x1F1, 0x1F3, 0x1F4, 0x1FC, 0x210, 0x214, 0x232, 0x233, 0x234 | Native chassis modules | - | - | P | - |
| 0x287, 0x2F9, 0x32A, 0x348, 0x34A, 0x34C, 0x350, 0x362 | Native chassis modules | - | - | P | - |
| 0x3C1, 0x3C9, 0x3D3, 0x3F1, 0x3F9, 0x3FB, 0x3FC, 0x451 | Native chassis modules | - | - | P | - |
| 0x4C1, 0x4C5, 0x4C7, 0x4D1, 0x4E1, 0x4E9, 0x589 | Native chassis modules | - | - | P | - |
| 0x0AA, 0x0BE, 0x0D3 | ECM/EBCM-native on OBD bus; VCM bridges to Vehicle bus -- absent here without VCM | - | - | **A** | - |
| 0x0C7 | VCM-generated on both GM buses | - | - | **A** | - |
| 0x0C9 | VCM-generated ~800 RPM synthetic on Vehicle bus | - | - | **A** | - |
| 0x0F9 | VCM-generated TCM stub | - | - | **A** | - |
| 0x19D | VCM-generated, unknown role | - | - | **A** | - |
| 0x1A3, 0x1A6 | ECM/EBCM-native on OBD bus; VCM bridges to Vehicle bus | - | - | **A** | - |
| 0x1C3, 0x1C4, 0x1C5 | VCM motor torque substitutes on Vehicle bus (real ECM versions survive on OBD) | - | - | **A** | - |
| 0x1F5 | VCM-mediated Via shift sensor data | - | - | **A** | - |
| 0x2C3, 0x3D1, 0x3E9 | ECM-native on OBD bus; VCM bridges to Vehicle bus | - | - | **A** | - |
| 0x4F1, 0x4F3, 0x772 | Native OBD bus IDs; VCM bridges to Vehicle bus | - | - | **A** | - |
| 0x681 | PT bus source; VCM bridges to Vehicle bus (also bridged to OBD as 0x661) | - | - | **A** | - |
| 0x7E8 | OBD scanner response -- not present when no scanner active | - | - | **A** | - |

---

## T1 -- PE Coolant Pump CAN Disconnect

**Log:** `logs/vtruxunplugpumpthenhvbatterylvconnector.log` (~t=34s event)

The PE pump CAN connector was physically unplugged at t=34s. Only one ID dropped:

- **0x18FF0320** (J1939, SA=0x20): drops immediately at t=34s; does not resume until t=162s
  (after pump reconnected and system restarted).

No other ID dropped at this event. The pump has its own CAN transceiver and its own IGN
input pin -- it is fully independent and does not carry wake/enable signals for other modules.

---

## T2 -- HV Battery LV Connector Disconnect

**Log:** `logs/vtruxunplugpumpthenhvbatterylvconnector.log` (~t=75-108s)

HV battery LV connector pulled at t=75s. This powers the BMS board. Summary of what dropped
and when:

| Time after pull | IDs affected |
|----------------|-------------|
| Immediate (by t=75.2s) | 0x370-0x375, 0x400, 0x410-0x412, 0x420, 0x430, 0x440, 0x460 (PT bus), 0x506, 0x507 — BMS board stops transmitting |
| ~3s | 0x18FECAB3 (Bel DCDC, SA=0xB3) — role unknown; does not return on BMS reconnect, only returns after key-on |
| ~32s | 0x474, 0x478, 0x480, 0x481, 0x55C, 0x580, 0x619 |
| ~33s | 0x053, 0x054, 0x470-0x475, 0x479, 0x482, 0x681, 0x0868A047, 0x0870A047, 0x18E8FFB3, 0x18FFD4B3, 0x18FFD6B3, 0x1CEBFFB3, 0x1CECFFB3 |

The ~32s and ~33s groups stopped well after the BMS disconnect — consistent with either a
module-internal comms-loss watchdog or the VCU commanding shutdown. These timings do not
attribute module identity or power source. IDs that survived the HV LV pull (0x050-0x052,
0x308, 0x390, 0x61F, etc.) only dropped when the 12V battery was deliberately cycled at
t=118s — that event cuts the entire 12V bus and provides no individual attribution.

---

## T3 -- VCM B-Connector Disconnect

**Log:** `logs/vtruxwoodwardbconnectordisconnected.log` (2026-03-06)
**Reference:** `logs/generator on then off.log`
**Surveys:** `notes/artifacts/vcm-disconnect-survey.json`, `notes/artifacts/genlog-survey.json`

### Survey Summary

| Metric | Disconnect | Reference |
|--------|-----------|-----------|
| Duration | 36.66s | 64.23s |
| Total frames | 118,438 | 455,900 |
| Unique IDs | 124 | 260 |
| PT bus IDs | **3** | 93 |
| OBD bus IDs | 50 | 77 |
| Vehicle bus IDs | 71 | 90 |

### PT Bus Collapse

90 of 93 PT bus IDs are absent. The B-connector likely carries a **wake-up or enable signal**
that brings PT bus modules online. Without it, inverters, BMS, and other modules stay in
sleep/unpowered state and produce no CAN traffic.

Supporting evidence:
- BMS messages (0x370-0x375, 0x400, 0x410-0x460) disappear despite having independent CAN
  transceivers -- a missing wake/enable signal explains this better than physical CAN disconnection.
- The PE pump has a documented IGN input pin (from T1). The VCM likely drives the pump IGN
  through the B-connector; pump IDs are absent in T3.
- The truck could not start; the entire powertrain was non-functional.

**Attribution limit of T3:** Because the collapse is near-total, T3 cannot distinguish "VCM broadcasts this ID" from "the B-connector carries the wake/power signal for whichever module broadcasts this ID." The "VCM ..." labels in the matrix above are working hypotheses, not confirmed attributions. T2 results are stronger: an ID that survives T2 but drops at T3 is definitively NOT BMS-sourced, but its actual broadcaster remains ambiguous until a more targeted test (e.g. reconnecting only the CAN pins of the B-connector, not the enable pin) is performed.

**Surviving PT bus IDs:**
- **0x390** (10 Hz): present; B0 constant 0x0E vs 0x12-0x68 in reference (different vehicle state).
  Source is NOT through B-connector and NOT VCM-sourced. Source module unidentified.
- **0x61F** (1 Hz): present; byte content identical in both logs (00 00 00 11 00 24 00 00).
  Same caveat as 0x390. Source module unidentified.
- **0x71F** (1 frame only): not in reference log; spurious.

### OBD Bus -- Notable Findings

**0x4C9 attribution:** 0x4C9 (TCM health flags) is present on both GM buses without VCM active — ruling out VCM as source. The shift box was previously hypothesized as the source, but the shifter box disconnect test (see `shifting-transfer-case-investigation.md`) ruled that out too: 0x4C9 continued broadcasting at 2 Hz after the box was physically unplugged (frame-count confirmed — not stale data). Source is currently unknown. Hypothesis: Via-added electronics under the dashboard, possibly related to IPC driving, which would explain native presence on both GM buses.

**Real ECM data confirmed on OBD bus:** 0x0C9 present at 80 Hz with engine speed = 0 RPM
(no start -- expected). 0x3D1, 0x3E9, 0x1C3, 0x1C4, 0x1C5 all present as real ECM messages.

**VCM bridging confirmed (OBD->Vehicle):** 0x0AA, 0x0BE, 0x0D3, 0x3D1, 0x3E9, 0x4F1, 0x4F3,
0x772 are native to OBD bus (present in T3) but absent from Vehicle bus in T3 -- VCM was
bridging them to the Vehicle bus.

### Vehicle Bus -- Notable Findings

**0x1C7 confirmed EBCM-native on Vehicle bus:** Present on Vehicle bus in T3; absent from OBD
bus in T3 (VCM was generating a separate substitute on OBD bus). Confirms prior attribution.

### Open Questions from T3

- **Source of 0x390 and 0x61F:** Not through B-connector. Survive T3 and survive the HV LV
  pull; only drop at the 12V battery cycle. Source module unidentified — not VCM-sourced.
- **B-connector wake signal:** Which specific pin carries the wake/enable? A test reconnecting
  only CAN pins (not the enable pin) could isolate CAN disconnection from module wake loss.
- **0x19D:** VCM-generated on both GM buses at 50 Hz, DLC=8. Role unknown.
- **0x040-0x044, 0x441-0x44A, 0x460-0x464:** Frequency/DLC match PT bus IDs suggests VCM
  bridging with ID remapping, but content comparison needed to confirm.

---

## T4 -- Generator Inverter Fuse Disconnect

**Log:** `logs/vtrux_no_gene_inv_fuse.log` (2026-04-17)

### Sequence

Log started with gene inv fuse already removed. Truck was started and shift-to-M was attempted
(no engine start -- expected, since the gene inv starts the engine). Fuse was then inserted at
~t=102s. Truck was turned off at ~t=148s (truck-off caused the broader ID drop at that point,
not a second fuse pull).

### IDs gated by the gene inv fuse

When the fuse was inserted at ~102s, two groups of IDs appeared:

**Group 1 -- appeared within a ~110ms window (102.12s to 102.23s):**

| ID | First seen |
|----|-----------|
| 0x473 | 102.1196s |
| 0x474 | 102.1186s |
| 0x478 | 102.1186s |
| 0x471 | 102.1306s |
| 0x482 | 102.1306s |
| 0x54  | 102.1356s |
| 0x479 | 102.1606s |
| 0x53  | 102.1706s |
| 0x472 | 102.1946s |
| 0x470 | 102.2266s |
| 0x480 | 102.2266s |
| 0x475 | 102.2186s |
| 0x481 | 102.2276s |

**Group 2 -- appeared ~1s later (103.1585s), together:**

| ID | First seen |
|----|-----------|
| 0x483 | 103.1585s |
| 0x484 | 103.1585s |

The ~1s lag for 0x483/0x484 relative to the rest of the GENE MCU group is consistent across
fuse insertion. These two IDs are the "GENE MCU feedback -- symmetric to TRAC MCU 0x460-0x464"
group (see matrix row), which may require an extra initialization step.

### 0x474 anomaly

0x474 appeared in Group 1 at 102.1186s, but was also present during the fuse-out phase (last
seen at 95.5s before fuse insertion). It is the only ID in the 0x470-0x484 range that broadcasts
without the gene inv fuse. Its source is unresolved; it likely has a different broadcaster than
the rest of the GENE MCU group.

### Correlation with T2/T3

All IDs gated by the gene inv fuse are also absent in T2 (~33s after BMS pull) and absent in
T3 (VCM B-connector disconnect). This is consistent: the GENE MCU requires both HV bus power
(via BMS, gated by T2) and VCM enable (via B-connector, gated by T3) to operate.
