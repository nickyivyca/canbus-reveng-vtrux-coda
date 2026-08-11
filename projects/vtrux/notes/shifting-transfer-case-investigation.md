# Shifting & Transfer Case Investigation

**Logs:**
- `projects/vtrux/logs/vtrux_transfer_case_test.log` (54.4s) — TC shift sequence: 4H → 2H → N → 4L → N → rev drivetrain motor → 2H
- `projects/vtrux/logs/vtrux_shifter_disconnect.log` (59.1s) — Truck in Park, shifted to Drive (creep against parking brake), shifter position box connector disconnected and reconnected, then shifted back to Park

---

## Transfer Case Position on CAN Bus

Two GMLAN signals track the transfer case state. Neither distinguishes 4H from 4L — both indicate only whether the front (secondary) axle is engaged.

### Primary: `0x1CF` B0 — `Secondary_Axle_Operational_Mode`

- **GMLAN message:** `Secondary_Axle_General_Information` (decimal 463), from `TCCM_RDCM`
- **Present on both OBD and Vehicle buses** (bridged faithfully, identical content)
- **Encoding:** lower nibble of B0. B1 and B2 always 0x00.

| B0 | `Secondary_Axle_Operational_Mode` | TC state |
|----|-----------------------------------|----------|
| `0x02` | 2 ("4 Wheel Drive Low Locked" per DBC enum) | **Front axle engaged** — both 4H and 4L |
| `0x00` | 0 ("2 Wheel Drive High") | **Front axle free** — both 2H and Neutral |

**Timeline from test log:**
```
t= 0.000s  0x02  (started in 4H)
t= 7.050s  0x00  (shifted to 2H)
t=14.949s  0x02  (shifted to 4L)
t=19.848s  0x00  (shifted to N -- stays 0x00 through motor rev and back to 2H)
```

4H and 4L are indistinguishable on this signal. The DBC enum name "Low Locked" is misleading — on this truck, any 4WD engagement (high or low) reports mode=2. No other signal visible on the logged buses distinguishes 4H from 4L.

**Source:** Either a residual TCCM_RDCM or the VCM synthesizing this GMLAN message from an internal 4WD state input (not yet determined).

### Secondary: `0x17D` B0 bit 5 — EBCM response

- **GMLAN message:** `Antilock_Brake_and_TC_Status_HS` from EBCM
- **Vehicle bus** (DLC=6; cantools decode fails as DBC declares DLC=8)
- Responds **~85ms after** 0x1CF transitions — the EBCM reacts to the TCCM state change

| B0 | B1 | State |
|----|----|-------|
| `0x02` | `0x04` | 4WD engaged (4H or 4L) |
| `0x22` | `0x24` | 2WD or Neutral |

Bit 5 (value 0x20) sets in both B0 and B1 simultaneously when the front axle is free, and clears when engaged. This bit is not covered by any signal in the GMLAN DBC (`Traction_Control_System_Operating_Mode` occupies bits[4:2] of B0 and stays at 0 throughout). It is an undocumented EBCM flag — most likely the "TC active / available" indicator, consistent with the driver observation that traction control turns off when the transfer case is engaged. When 4WD is on (bit5=0), TC is inhibited; when 2WD/N (bit5=1), TC is available.

---

## Shift Lever Position on the PT Bus (`0x639` B6) — CONFIRMED 2026-07-26

There is a **PT-bus** shift lever position field, independent of the Vehicle-bus `0x1F5`
described below:

**`0x639` B6 bits[6:4]** (mask `0x70`), 3-bit unsigned, ~100 Hz, DLC=8, VCM-sourced:

| Value | Position |
|-------|----------|
| 0 | Park |
| 1 | Reverse |
| 2 | Neutral |
| 3 | Drive |
| 4 | M (manual / generator mode) |

Confirmed against the two ground-truth logs already used in this file:

- `generator-on-then-off.log` — steps 3→4 at t=39.08s and 4→3 at t=53.26s, matching the
  M engagement documented below (engaged t=39.1s, held ~14s).
- `vtrux_shifter_disconnect.log` — drops to 2 (Neutral) the instant the shifter box is
  unplugged at t=20.30s, returns to 3 on reconnect at t=29.56s. This is the same
  Neutral safe-default behaviour documented in the Shifter Position Box Disconnect
  section below, visible on the PT bus.

`0x644` B0 bits[7:6] mirrors the index but is only 2 bits and **cannot distinguish M from
Park** (both read 0). `0x601` B0 bit5 also tracks the transition. Use `0x639` B6.

**Why this matters:** the OBD-bus copy of `0x1F5` is VCM-frozen at Park (see below), so on
any capture that lacks the Vehicle bus, `0x639` B6 is the only available shift-position
source. Both the 2026-07-24 trip logs and most Android-logger captures are PT+OBD only.

---

## Simulated Gear Position (`0x1F5` Transmission_General_Status_2)

The VCM broadcasts a synthetic `Transmission_Estimated_Gear` and `Transmission_Shift_Lever_Position` on the Vehicle bus (0x1F5) to satisfy the IPC. These are not real TCM signals — the BorgWarner 32-01 is a single-speed transmission with no actual gear selection.

The **OBD bus** also carries 0x1F5, but the VCM substitutes a static "Park Gear / Park Range" on that bus for the entire session regardless of actual state. The OBD bus copy is for diagnostic equipment only; the IPC reads from the Vehicle bus. Confirmed directly: the Vehicle bus 0x1F5 content matches all observed IPC states (D, N, R, P, M), leaving no role for a separate hidden message.

### GMLAN enum values (from `GMW8762_PPEI_GMLAN.dbc`)

`Transmission_Estimated_Gear` and `Transmission_Shift_Lever_Position` use standard GMLAN enumerations. Relevant values observed on this truck:

| `Transmission_Estimated_Gear` | Value | `Transmission_Shift_Lever_Position` | Value |
|-------------------------------|-------|-------------------------------------|-------|
| First Gear | 1 | Forward Range A (Drive) | 4 |
| Second Gear | 2 | Forward Range F (M mode) | 9 |
| Third Gear | 3 | Neutral Range | 3 |
| Fourth Gear | 4 | Reverse Range | 2 |
| Fifth Gear | 5 | Park Range | 1 |
| Sixth Gear | 6 | Between Ranges | 0 |
| Neutral Gear | 13 | Lever Position Unknown | 15 |
| Reverse Gear | 14 | | |
| Park Gear | 15 | | |

M mode uses **"Forward Range F"** (value 9) for LevPos. The `Transmission_Tap_Up_Tap_Down_Mode_Status` field (0x1F5 B5 bits[1:0]) simultaneously transitions to 2 = "Electronic Range Select Active" (normal Drive = 0 = "No Activation"). Confirmed from `generator on then off.log`: M mode engaged at t=39.1s, held ~14s, then returned to Drive.
| Park Gear | 15 | | |

### Validity flags — never set

`Transmission_Estimated_Gear_Validity` and `Transmission_Shift_Lever_Position_Validity` both remain "Valid" (0) in all conditions observed across both logs — normal driving, TC neutral with motor rev, and shifter disconnect. The VCM does not use the GMLAN validity bits to signal abnormal states. Any anomalous indication on the IPC dash is caused by the position value itself, not an explicit invalidity flag.

`Transmission_Creep_Mode_Active` also remains False throughout both logs, including during active creep torque operation.

### Gear estimation algorithm

The VCM estimates gear from **traction motor RPM** (0x5A2 B2-B3 on PT bus), using ~1250 RPM/gear thresholds. Vehicle speed tracks proportionally in normal driving (~125 RPM/km/h), so either could appear as the input — but the decoupled case (below) reveals the VCM uses RPM, with a vehicle-speed consistency check.

Confirmed from `vtruxcurrentlimitingtest.log`:

| Gear | Upshift RPM | Downshift RPM |
|------|-------------|---------------|
| 1st->2nd | ~1325-1390 | ~694-882 |
| 2nd->3rd | ~2520-2568 | — |
| 3rd->4th | ~3758-3825 | ~3036-3120 |
| 4th->5th | ~5010-5014 | ~4297-4381 |
| 5th->6th | ~6246-6248 | ~4976-4985 |

Thresholds are very consistent (~1250 RPM/gear increment). Hysteresis of roughly 500-700 RPM between upshift and downshift for the same gear boundary. In normal driving, `LevPos` = "Forward Range A" throughout; no "Between Ranges" events.

### "Between Ranges" fallback mode (motor decoupled from wheels)

When the traction motor spins but wheel speed is zero (transfer case in N, or motor otherwise decoupled), the VCM detects the RPM/speed inconsistency and abandons the RPM-threshold algorithm. It falls back to a **timer-based gear advancement**: steps through gears at ~1.1s intervals regardless of motor RPM.

Evidence: in the TC test log, gear transitions during the motor rev occur at RPM values of 7000-10500 — far above the normal thresholds (~1250-6250). The thresholds are completely ignored; only the timer fires. The descent phase is definitive: when RPM drops to ~300 (below all downshift thresholds), gear still decrements one step per ~0.5-1.1s, taking 3.6s to walk from 6th to 1st.

Once the gear estimate reaches >=4th with vehicle speed still 0, `Transmission_Shift_Lever_Position` oscillates between "Forward Range A" (0x04) and "Between Ranges" (0x00) at ~3 Hz (330ms period). This is what the IPC shows as a blinking shifter position indicator. The oscillation is a VCM output artifact — nothing else on the bus toggles at the same frequency.

Summary of "Between Ranges" events in TC test log:
- Initial transient at t=24.281s: RPM=-1, Vspd=0.0 (park-release flicker, one frame)
- Sustained oscillation t=29.5-38.3s: RPM 7848-10669, Vspd=0.0 throughout

---

## Shifter Position Box Disconnect (`vtrux_shifter_disconnect.log`)

### Test setup

Truck shifted to Drive with parking brake applied. Motor commanded creep torque against the stationary wheel. Shifter position box connector physically disconnected and later reconnected. Log ends with user shifting back to Park.

### Torque command behavior (0x041 B1-B2, OBD bus)

Creep torque before disconnect: **~910 counts above neutral = ~114 Nm** (0x041 B1-B2 LE uint16 centered at 32768; scale 0.125 Nm/count from EPRI symmetric encoding of 0x051, unconfirmed by independent calibration).

On disconnect (t≈20.3s): torque ramps down from ~114 Nm to 0 over **~270ms** — a controlled linear ramp, not an instant cut. B0 status nibble stays at 0x0B throughout; no fault status is set.

On reconnect (t≈29.6s): torque ramps back up from 0 to ~114 Nm over **~400ms**.

The 0x308 park pin signal (PT bus) shows small B1 fluctuations around the disconnect event, consistent with the drivetrain load change.

### Gear and lever position response

The VCM reports **"Neutral Gear" / "Neutral Range"** for the entire disconnect window (t=20.3–29.5s). This is a deliberate safe-default: when the VCM loses a coherent shifter input it reports Neutral rather than holding the last Drive state or setting an invalid flag.

Full decoded 0x1F5 sequence on Vehicle bus:

| Time | EstGear | LevPos | EngagedState | Meaning |
|------|---------|--------|--------------|---------|
| t=0–20.3s | First Gear | Forward Range A | Engaged in Forward | Drive, creep active |
| t=20.3–29.5s | Neutral Gear | Neutral Range | Not Engaged | Shifter disconnected |
| t=29.5–55.5s | First Gear | Forward Range A | Engaged in Forward | Reconnected |
| t=55.6s | Neutral Gear | Neutral Range | Not Engaged | Shifting to Park (passing N) |
| t=55.6s | Reverse Gear | Reverse Range | Engaged in Reverse | Passing R |
| t=55.7s | Park Gear | Park Range | Not Engaged | Park |

The end-of-log P-R-N-D gate is fully visible and cleanly decoded.

### What the IPC shows

The IPC displays **"N"** (Neutral) during the disconnect window. The dash indicator appears wrong because the driver knows they shifted to Drive — but from the IPC's perspective it is simply displaying the position the VCM reported. This is different from the TC "Between Ranges" blink:

| Condition | LevPos behavior | IPC appearance |
|-----------|-----------------|----------------|
| TC neutral + motor rev | Oscillates "Forward Range A" ↔ "Between Ranges" at ~3 Hz | Blinks (value toggling rapidly) |
| Shifter disconnect | Holds static at "Neutral Range" | Displays N (unexpected position, not blinking) |

Neither condition involves a validity flag.

### 0x4C9 (source unknown)

`0x4C9` (`Transmission_General_Status_3`) broadcasts constant `40 41 00 00 30 00 00` throughout the entire disconnect log — 19 frames at 2.1 Hz during the disconnect window (frame-count confirmed, not stale). The message kept broadcasting after the shift box was physically unplugged, which rules out the shift box as the source. See `can-disconnect.md` for full attribution discussion.

---

## Artifacts

`projects/vtrux/notes/artifacts/tc_timeline.py` — timeline extraction  
`projects/vtrux/notes/artifacts/tc_decode.py` — cantools decode + rev-window correlation  
`projects/vtrux/notes/artifacts/tc_rpm_correlation.py` — motor RPM vs EstGear threshold analysis (TC test + current limiting log)  
`projects/vtrux/notes/artifacts/transfer_case_survey.txt` — survey output for TC test log  
`projects/vtrux/notes/artifacts/shifter_disconnect_survey.txt` — survey output for shifter disconnect log  
`projects/vtrux/notes/artifacts/shifter_disconnect_decode.py` — torque command timeline + cantools full decode of 0x1F5 on both buses  
`projects/vtrux/notes/artifacts/levpos_scan.py` — LevPos transition scan; used to confirm M mode in `generator on then off.log`

---

## Open Items

- **4H vs 4L distinction:** Neither 0x1CF nor any other signal in this log distinguishes high range from low range. A dedicated test with separate 4H-only and 4L-only windows and a broader ID scan would be needed.
- **0x1CF source:** Whether this signal comes from a residual TCCM_RDCM or is VCM-synthesized is unconfirmed.
- **0x17D DLC mismatch:** The GMLAN DBC declares 0x17D as 8 bytes; actual frames are 6 bytes. The `Traction_Control_System_Operating_Mode` signal field stays at 0 throughout; the semantically meaningful change is the undocumented bit 5 of B0/B1.
- **Torque scale:** 0x041 B1-B2 scale of 0.125 Nm/count is taken from the EPRI Ghidra decompile of the symmetric GENE command (0x051); not independently calibrated against physical measurement.
- **Creep Mode Active:** `Transmission_Creep_Mode_Active` (0x1F5 B5 bit 6) reads False throughout despite active creep torque. The VCM does not set this GMLAN field.
