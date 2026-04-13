# Shifting & Transfer Case Investigation

**Logs:**
- `projects/vtrux/logs/vtrux_transfer_case_test.log` (54.4s) — TC shift sequence: 4H → 2H → N → 4L → N → rev drivetrain motor → 2H
- `projects/vtrux/logs/vtrux_shifter_disconnect.log` (59.1s) — Truck in Park, shifted to Drive (creep against parking brake), shifter position box connector disconnected and reconnected, then shifted back to Park

---

## Transfer Case Position on CAN Bus

Two GMLAN signals track the transfer case state. Neither distinguishes 4H from 4L — both indicate only whether the front (secondary) axle is engaged.

### Primary: `0x1CF` B0 — `Secondary_Axle_Operational_Mode`

- **Source:** TCCM_RDCM module
- **Present on both OBD and Vehicle buses** (bridged faithfully, identical content)
- **Encoding:** lower nibble of B0. B1 and B2 always 0x00.

| B0 | Axle mode value | TC state |
|----|-----------------|----------|
| `0x02` | 2 | **Front axle engaged** — both 4H and 4L |
| `0x00` | 0 | **Front axle free** — both 2H and Neutral |

**Timeline from test log:**
```
t= 0.000s  0x02  (started in 4H)
t= 7.050s  0x00  (shifted to 2H)
t=14.949s  0x02  (shifted to 4L)
t=19.848s  0x00  (shifted to N -- stays 0x00 through motor rev and back to 2H)
```

4H and 4L are indistinguishable on this signal — any 4WD engagement (high or low) reports mode=2. No other signal visible on the logged buses distinguishes 4H from 4L.

**Source:** Either a residual TCCM_RDCM or the VCM synthesizing this message from an internal 4WD state input (not yet determined).

### Secondary: `0x17D` B0 bit 5 — EBCM response

- **Source:** EBCM
- **Vehicle bus** (DLC=6; cantools decode fails as DBC declares DLC=8)
- Responds **~85ms after** 0x1CF transitions — the EBCM reacts to the TCCM state change

| B0 | B1 | State |
|----|----|-------|
| `0x02` | `0x04` | 4WD engaged (4H or 4L) |
| `0x22` | `0x24` | 2WD or Neutral |

Bit 5 (value 0x20) sets in both B0 and B1 simultaneously when the front axle is free, and clears when engaged. The standard traction control status field occupies bits[4:2] of B0 and stays at 0 throughout; bit 5 is not a documented field in the known signal mapping. It appears to be an EBCM flag for "TC active / available", consistent with the driver observation that traction control turns off when the transfer case is engaged. When 4WD is on (bit5=0), TC is inhibited; when 2WD/N (bit5=1), TC is available.

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

Gear position message (0x1F5) on Vehicle bus during disconnect sequence:

| Time | Gear | Lever Position | Drive State | Meaning |
|------|------|---------------|-------------|---------|
| t=0–20.3s | 1st | Drive | Forward | Drive, creep active |
| t=20.3–29.5s | Neutral | Neutral | Not Engaged | Shifter disconnected |
| t=29.5–55.5s | 1st | Drive | Forward | Reconnected |
| t=55.6s | Neutral | Neutral | Not Engaged | Shifting to Park (passing N) |
| t=55.6s | Reverse | Reverse | Reverse | Passing R |
| t=55.7s | Park | Park | Not Engaged | Park |

The end-of-log P-R-N-D gate is fully visible and cleanly decoded.

### What the IPC shows

The IPC displays **"N"** (Neutral) during the disconnect window. The dash indicator appears wrong because the driver knows they shifted to Drive — but from the IPC's perspective it is simply displaying the position the VCM reported. This is different from the TC "Between Ranges" blink:

| Condition | Lever position behavior | IPC appearance |
|-----------|------------------------|----------------|
| TC neutral + motor rev | Oscillates "Drive" ↔ "No Gear" at ~3 Hz | Blinks (value toggling rapidly) |
| Shifter disconnect | Holds static at "Neutral" | Displays N (unexpected position, not blinking) |

Neither condition involves a validity flag.

### 0x4C9 (source unknown)

`0x4C9` (TCM status message) broadcasts constant `40 41 00 00 30 00 00` throughout the entire disconnect log — 19 frames at 2.1 Hz during the disconnect window (frame-count confirmed, not stale). The message kept broadcasting after the shift box was physically unplugged, which rules out the shift box as the source. See `can-disconnect.md` for full attribution discussion.

---

## Artifacts

`projects/vtrux/notes/artifacts/tc_timeline.py` — timeline extraction  
`projects/vtrux/notes/artifacts/transfer_case_survey.txt` — survey output for TC test log  
`projects/vtrux/notes/artifacts/shifter_disconnect_survey.txt` — survey output for shifter disconnect log

---

## Open Items

- **4H vs 4L distinction:** Neither 0x1CF nor any other signal in this log distinguishes high range from low range. A dedicated test with separate 4H-only and 4L-only windows and a broader ID scan would be needed.
- **0x1CF source:** Whether this signal comes from a residual TCCM_RDCM or is VCM-synthesized is unconfirmed.
- **0x17D DLC mismatch:** The GMLAN DBC declares 0x17D as 8 bytes; actual frames are 6 bytes. The `Traction_Control_System_Operating_Mode` signal field stays at 0 throughout; the semantically meaningful change is the undocumented bit 5 of B0/B1.
- **Torque scale:** 0x041 B1-B2 scale of 0.125 Nm/count is taken from the EPRI Ghidra decompile of the symmetric GENE command (0x051); not independently calibrated against physical measurement.
