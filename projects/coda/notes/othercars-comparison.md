# Coda Other Cars -- Comparison Analysis

**Reference (my Coda):** `projects/coda/logs/codadriveslowturnonwithdefroster2.log` (708 s, 1,919,708 frames, 174 IDs)

This file documents CAN analysis of other Coda vehicles (parts car and Car 2's car) compared
to the reference capture from my Coda.

---

# Part A -- Parts Car

**Log:** `projects/coda/notes/partscar_capture_20260304/codapartscarlog.log` (154 s, 378,200 frames, 169 IDs)
**DTCs on parts car:** ABS C102B, C2202; Airbag B1382, B2505; DLCM C2100, U0110; HVAC B111D, B112D; BMS P1811

Survey artifacts: `artifacts/survey_partscar.txt`, `artifacts/survey_normal.txt`

---

## Phase 1 -- Survey Results (2026-03-04)

### Bus mapping

Bus numbers differ between captures (dongle insertion order is arbitrary).
Identified by anchor IDs per projects/coda/README.md: presence of B CAN anchors (0x270, 0x271, 0x3A0,
0x381, etc.) identifies B CAN. D CAN signals visible on B CAN (e.g. 0x1C0) are GWM
rebroadcasts. D CAN anchors (0x212, 0x241, 0x278, 0x315 native) but no B CAN exclusives
= D CAN. Cell IDs 0x000-0x119 = C CAN.

| Bus | Parts car | Normal Coda |
|-----|-----------|-------------|
| B CAN | Bus 3 (39 IDs) | Bus 3 (39 IDs) |
| D CAN | Bus 2 (31 IDs) | Bus 1 (35 IDs) |
| C CAN | Bus 1 (99 IDs) | Bus 2 (100 IDs) |

### IDs absent in parts car (present in normal Coda)

| ID (hex) | Bus | Freq in normal | Notes |
|----------|-----|---------------|-------|
| 0x536 | C CAN | 17.8 Hz | Unidentified; 7306 frames. Not in projects/coda/README.md. |
| 0x600 | B CAN + D CAN | 1.9 Hz | Unidentified; 1320 frames over 708 s. Appears on both Bus 1 (D CAN) and Bus 3 (B CAN) in normal Coda with identical data -- GWM rebroadcast on both buses. Not in projects/coda/README.md. |
| 0x591 | D CAN | 1 frame | Startup one-shot: `A0 00 00 00 00 00 00` (7 bytes). |
| 0x592 | D CAN | 1 frame | Startup one-shot: `CC 12 A5 7D 46 A6 4A FB` (8 bytes). |
| 0x603 | D CAN | 3 frames | Sparse; D CAN. |
| 0x614 | D CAN | 1 frame | Startup one-shot. |

**DLCM U0110 (Lost Communication with MCM):** MCM telemetry 0x1C0 IS present in both
logs at 100 Hz, so the MCM was communicating during the parts car capture. U0110 is a
stored (past) fault, not active during this capture. The absence of 0x600 is noted but
its identity is unknown -- it is NOT the explanation for U0110.

**Hardware note:** The parts car does not have an RCU (Radio Control Unit — TPMS, keyfob
receiver, immobilizer). This may account for some or all of the IDs absent from the parts car.
Not yet investigated or attributed — recorded here as a known hardware difference.

### IDs present in parts car only (absent from normal Coda)

| ID (hex) | Bus | Freq | Bytes |
|----------|-----|------|-------|
| 0x7FE | D CAN + B CAN | ~1 Hz | `0A 05 00 00 xx 06-09 00 00`. Likely a diagnostic keepalive or tester-present frame. |

### Key byte-range differences on matching IDs

All IDs below are on B CAN (Bus 3) unless noted.

| ID (hex) | Signal (projects/coda/README.md) | Normal B-range | Parts car B-range | Interpretation |
|----------|-----------------|----------------|-------------------|----------------|
| 0x270 B0 | BMS fault status | 0x00-0x12 | **0x00-0x02** | Narrower; P1811 is stored not active during capture |
| 0x271 B0 | VehicleFaultLampReq | 0x00-0x06 | 0x00-0x06 | Same range; need analyze_id for steady-state value |
| **0x491 B0** | Odometer high byte (B0:B1:B2 = 24-bit BE, 0.1 km) | **0x08 (fixed)** | **0x0F (fixed)** | Odometer high byte -- differs by mileage, not a fault |
| **0x491 B1** | Odometer mid byte | **0x5B (fixed)** | **0x41 (fixed)** | Odometer mid byte -- differs by mileage, not a fault |
| **0x492 B0** | Second odometer broadcast (mirrors 0x491 B0:B1:B2) | **0x08 (fixed)** | **0x00 (fixed)** | All-zero in parts car -- that module silent, not fault-related |
| 0x3A0 B0 | SRS/seatbelt area | 0x20-0xAA | **0xA0-0xAA** | Lower bound raised; bits 5+7 forced HIGH in parts car |
| 0x382 B0-B2 | BMSThermal | 0x8A-0x99 (~10-25 degC) | **0x8D/8E/8D (fixed)** | Stuck at 13-14 degC; short cold capture, likely not a fault |
| 0x390 B0-B3 | HVAC thermal limits | 0x80-0x8A | **0x8E (fixed)** | Stuck; may relate to HVAC B111D temp sensor fault |
| 0x2C1 B1 | BMSDrivingRange | 0x00-0x63 | **0xAA-0xAC** | 0xAA may be invalid/sentinel value |
| 0x439 B1-B2 | ACCM status | 0x00-0x1E, 0x00-0x09 | 0x00, 0x00 | AC compressor not running (expected for parts car) |

### IPK 0x491 -- odometer bytes (B0:B1:B2)

Fixed values of the two high bytes throughout each entire capture:

```
           B0             B1
Normal:  0x08 = 0000_1000   0x5B = 0101_1011
Parts:   0x0F = 0000_1111   0x41 = 0100_0001
```

**B0:B1:B2 is a 24-bit big-endian odometer, 0.1 km/count.** The cross-car byte
differences are *mileage*, not fault bits. Decoded against known mileage:
reference car 0x085B57 = 547671 -> ~34.0k mi; parts car 0x0F41EA = 999914 -> ~62.1k mi.
A per-bit XOR is meaningless here -- these bytes count up with distance travelled.

**0x492** mirrors 0x491 B0:B1:B2 exactly in the normal Coda (a second odometer /
IPK-cluster broadcast), but is all zeros in the parts car. The all-zeros = that module
was silent in the parts car configuration, not a fault-related state.

### SRS 0x3A0 -- fault state flag

Normal B0 lower bound 0x20 (`0010_0000`); parts car lower bound 0xA0 (`1010_0000`).
Bits 5 and 7 are forced HIGH in the parts car. This is the SRS/seatbelt module ID --
the forced-high pattern likely encodes an airbag fault state (B1382, B2505).

---

## Phase 2 -- Fault Lamp IDs 0x270, 0x271 (2026-03-04)

Artifacts: `analyze_270_partscar.txt`, `analyze_271_partscar.txt`, `analyze_270_normal.txt`,
`analyze_271_normal.txt`, `compare_ids.txt`.

### 0x271 B0 -- VehicleFaultLampReq (refined encoding)

B1-B7 = all zero in both logs throughout. All information is in B0.

**Encoding:**

| B0 value | bits[2:0] | Meaning |
|----------|-----------|---------|
| 0x00 | 000 | All fault lamps OFF |
| 0x01 | 001 | YELLOW fault lamp ON |
| 0x02 | 010 | RED fault lamp ON |
| 0x04 | 100 | Lamp-test flag only (no lamp commanded -- or brief transition) |
| 0x05 | 101 | YELLOW + lamp-test flag |
| 0x06 | 110 | RED + lamp-test flag |

Bit 2 (0x04) = "lamp test in progress" flag. It is set during the startup lamp test sequence
and briefly accompanies fault-lamp state changes. It does NOT encode a distinct lamp.

**Standard lamp test sequence (both logs):**
```
0x00 -> 0x05 (YELLOW+flag) -> 0x06 (RED+flag) -> 0x04 (flag only) -> [settle to fault state]
```

**Parts car B0 transitions (t=0-154 s):**
```
t=  0.00s  0x00  OFF  (startup)
t= 18.40s  0x05  YELLOW+flag  (lamp test starts)
t= 19.90s  0x06  RED+flag
t= 22.40s  0x04  flag only
t= 24.00s  0x05  YELLOW+flag  <- post-test fault lamps remain ON
t= 51.40s  0x01  YELLOW       <- flag cleared, YELLOW steady
t=134.10s  0x05  YELLOW+flag  (brief transition)
t=143.80s  0x00  OFF          (brief)
t=151.40s  0x01  YELLOW       (back on to end of log)
```

**Parts car steady-state = YELLOW (0x01/0x05).** Consistent with non-critical faults:
ABS C102B, Airbag B1382/B2505, HVAC B111D/B112D. No RED = no critical fault active.

**Normal Coda (defroster2) B0 transitions:**
```
t=  0.08s  0x00  OFF
t=  9.48s  0x01  YELLOW   (lamp test starts)
t=  9.58s  0x05  YELLOW+flag
t= 10.98s  0x06  RED+flag
t= 12.58s  0x04  flag only
t= 38.78s  0x00  OFF       (lamp test ends, no active fault)
t=136.18s  0x02  RED       (fault lamp turns RED)
t=662.29s  0x06  RED+flag
t=674.39s  0x02  RED
t=694.69s  0x06  RED+flag
t=701.79s  0x00  OFF
```

Normal Coda steady-state = OFF (0x00) until t=136s, then RED (0x02).

### 0x270 B0 -- BMS fault echo (confirmed behaviour)

Parts car B0 transitions:
```
t=  0.02s  B0=0x00  B6=0x40  B7=0x00  (startup)
t= 18.62s  B0=0x01  B6=0x40  B7=0x88  (echoes lamp test YELLOW; 0.22 s lag after 0x271)
t= 20.02s  B0=0x02  B6=0x40  B7=0x88  (echoes lamp test RED; 0.12 s lag)
t= 21.52s  B0=0x00  B6=0x40  B7=0x08  (clears; stays 0x00 for remainder of 154 s log)
```

**0x270 B0 reflects BMS-sourced fault severity ONLY.** When 0x271 commands YELLOW due to
ABS/Airbag/HVAC faults (from t=24 s onward in parts car), 0x270 B0 stays 0x00. Only the
lamp-test pulses (which are driven by the BMS as part of key-on init) briefly set B0 to
0x01/0x02. This distinguishes BMS-active faults (B0 non-zero persistently) from other-module
faults (B0=0x00, only 0x271 carries the lamp request).

Parts car BMS P1811 confirmed **stored, not currently active** during this capture.

**0x270 B6:**
- Normal (defroster2): 0x10 at startup, ramps to 0x41 (~B CAN initialisation sequence)
- Parts car: fixed at 0x40 (no startup ramp visible in 154 s capture)
- B6 meaning unknown; may be a BMS state/mode nibble. Note for future investigation.

### compare.py ID diff note

compare.py matched 42 IDs across both logs (all on Bus 3 / B CAN, same bus number).
Buses 1 and 2 did not match because bus numbering swapped between captures.
Genuinely absent from parts car confirmed:
- `0x600` on B CAN (Bus 3) and D CAN (Bus 1) in normal Coda at 1.9 Hz (GWM rebroadcasts to both buses)
- `0x536` on C CAN only in normal Coda at 17.8 Hz
Genuinely only in parts car:
- `0x7FE` on D CAN (Bus 2) and B CAN (Bus 3) at ~1 Hz

## Phase 3 -- Per-DTC Signal Mapping (2026-03-04)

Artifacts: `analyze_308_partscar.txt`, `analyze_312_partscar.txt`, `analyze_308_normal.txt`,
`analyze_312_normal.txt`, `analyze_3A0_partscar.txt`, `analyze_391_partscar.txt`,
`analyze_276_partscar.txt`.

### Summary table

| DTC | Module | CAN ID | Field | Fault indicator |
|-----|--------|--------|-------|-----------------|
| ~~ABS C102B~~ | ~~ESC~~ | ~~0x312 B6-B7~~ | ~~RR wheel speed~~ | **WITHDRAWN 2026-09-24 — 0x312 is a DLCM torque frame; see below** |
| ~~ABS C102B~~ | ~~ESC~~ | ~~0x312 B0 bits 2-0~~ | ~~Fault status~~ | **WITHDRAWN 2026-09-24** |
| ABS C2202 | ESC | VIN frames | VIN mismatch | Deferred to Phase 4 |
| Airbag B1382+B2505 | SRS | 0x3A0 B0 bit 7 | SRS fault flag | 1=fault, 0=no fault |
| HVAC B111D | HVAC | 0x391 B4 | ReturnAirTemp | 0x58 (-40 degC sentinel) vs -7 to +7 degC normal |
| HVAC B112D | HVAC | -- | Airmix flap actuator | No CAN status observable (see below) |
| DLCM C2100 | DLCM | -- | Key interlock | No candidate found; low priority |

### ABS C102B (RR Wheel Speed Sensor Circuit) -- 0x312, D CAN

> **WITHDRAWN 2026-09-24.** `0x312` is not an ESC message and carries no wheel speeds. It is
> transmitted by the DLCM (TX record 10) and carries a torque feedback field duplicated at
> B0-B1 and B2-B3, **M_MAX** at B4-B5 and **M_MIN** at B6-B7, all at 0.25 Nm/count with zero
> at 2000. See `notes/dlcm/coda-dlcm-decompile-notes.md`.
>
> The parts-car measurements below are real and are explained by that reading: B6-B7 in
> {1860, 2000} is a regen limit of −35 … 0 Nm, i.e. a car sitting with HV off, and "B0 bits
> 2-0 = 0x07 vs 0x00" is the top of a 13-bit torque value, not per-channel fault flags.
> **No CAN indicator for ABS C102B has been identified.** The wheel speeds are on `0x200`
> (front) and `0x208` (rear); re-run this comparison against those before concluding
> anything about the RR sensor.


0x312 is a 100 Hz frame containing 4 x BE uint16 wheel speed channels:
B0-B1, B2-B3, B4-B5, B6-B7. The upper byte of each pair carries magnitude;
the lower byte carries both fine speed data and fault-status bits in bits 2-0.

**B6-B7 is the RR wheel channel and is stuck in the parts car:**

| | Normal Coda | Parts car |
|--|-------------|-----------|
| B6-B7 pair range | 800-2000, **908 unique** | 1860-2000, **2 unique** |
| B6 alone | 3-7 (5 unique) | **7 fixed** |
| B0 bits 2-0 | 0x00 (all clear) | **0x07 (always set)** |
| B2 min | 0 | 7 |

0x07D0=2000 is the "stationary/default" value for all four wheel channels. During
normal driving B6-B7 spans 800-2000 with 908 unique values. Parts car B6-B7 = {1860,
2000} only -- the RR sensor is not producing valid speed data.

The lower 3 bits of the status bytes (B0, B2, B6) encode per-channel fault flags:
0x00 = no fault (normal), 0x07 = fault (parts car B0 and B6). B4 min=7 in both
logs, suggesting one wheel always has a minor flag set (possibly a known platform
behaviour unrelated to C102B).

Normal startup: `00 00 00 00 07 D0 07 D0` (channels 1-2 at zero, channels 3-4 at 2000)
Parts startup:  `67 D0 07 D0 07 D0 07 D0` (B0=0x60 counter + 0x07 fault bits)

### Airbag B1382 / B2505 -- 0x3A0, B CAN

B0 bit 7 is the SRS/airbag fault flag.

| B0 value | Context |
|----------|---------|
| 0x20 = 0010_0000 | Normal steady state (bit 5 = module-active; bit 7 = 0 = no fault) |
| 0xA0 = 1010_0000 | Parts car steady state (bit 7 = 1 = fault active) |
| 0xAA = 1010_1010 | Brief startup sequence (airbag lamp test; bits 7,5,3,1 set) |

B1-B7 are zero at steady state in both logs. B1 carries data only during the startup
airbag lamp test sequence (0x35->0x21->0x00 transition). B1382 and B2505 are both
SRS module faults; they cannot be distinguished individually from this byte -- both
raise B0 bit 7 collectively.

0x3A0 starts transmitting at t=18.43 s in the parts car (same time as 0x271 lamp
test sequence starts). No frames before this -- SRS module is silent until key-on
completes.

### HVAC B111D (Battery Evap Air Off Temp Sensor) -- 0x391, B CAN

Most likely indicator is 0x391 B4 (ReturnAirTemp):
- Parts car B4 min = 0x58 = -40 degC -- the standard automotive "open/disconnected
  sensor" sentinel, never seen in normal Coda (normal min -7 degC).
- Parts car B4 reaches 0x96 = +22 degC later in the capture, so the value is not
  permanently stuck; the -40 degC sentinel appears during the initial measurement
  phase before a valid reading is established (or intermittently on a marginal sensor).

Other anomalies in 0x391 (less conclusive):
- B1 (UnderHoodTemp) = 0xFF fixed (127 degC) in parts car vs 0x58-0xFF varying in
  normal. Possible "out of range high" sensor condition.
- B5 (EvapAirOffTemp) = 0x80-0x8E (0-14 degC) -- plausible cold temperature; no
  obvious fault sentinel. Does not show a clear B111D signature on its own.

Note: 0x391 B4=ReturnAirTemp shows the clearest fault sentinel (-40 degC). Whether
the DTC B111D maps to B4 specifically or to B5, the HVAC module reports at least
one temperature channel as invalid during this capture.

### HVAC B112D (Cabin Airmix Motor Fault) -- no CAN status observable

The airmix flap is a downstream actuator. The cabin temperature radiator
(CIntTempRadOutlet, 0x276 B3) is located upstream of the flap. During the parts car
capture the PTC heater ran (B5 PTCHeaterPWM up to 74%, B3 rising 10->24 degC), which
confirms the heating circuit is working normally. The fault in the flap motor affects
air distribution downstream of the sensor, so B3 shows no anomaly regardless of flap
position. No CAN fault status bit is broadcast by the HVAC module for this actuator.

### DLCM C2100 (Key Interlock Solenoid) -- no candidate found

Intermittent / low-priority fault. No ID in the survey diff stands out as a key
interlock solenoid status. Not investigated further.

## Phase 4 -- VIN Investigation (2026-03-05)

Artifacts: `vin_search.py`, `vin_search_normal.txt`, `vin_search_partscar.txt`.

### VIN broadcast: 0x6FA, B CAN + D CAN (GWM), 10 Hz

VIN is broadcast continuously at 10 Hz on 0x6FA, split across 3 sequential frames.
B0 = frame counter (0/1/2). B1-B7 = 7 ASCII VIN bytes per frame (21 bytes total,
17 chars + 4 zero padding in frame 2).

The GWM rebroadcasts 0x6FA to both B CAN and D CAN (same content on both buses,
interleaved in the log at ~20 Hz total).

**Normal Coda (53G1U4A46CB000090):**
```
Frame 0: 00 35 33 47 31 55 34 41  ->  "53G1U4A"
Frame 1: 01 34 36 43 42 30 30 30  ->  "46CB000"
Frame 2: 02 30 39 30 00 00 00 00  ->  "090"
```
Note: VIN character 2 is uppercase 'G' (0x47) on-bus. The known VIN string
53g1U4A46CB000090 has a lowercase 'g' -- this appears to be a transcription artefact;
the actual VIN broadcasts as `53G1U4A46CB000090`.

**Parts car:**
```
Frame 0: 00 41 42 43 44 45 46 47  ->  "ABCDEFG"
Frame 1: 01 48 49 31 32 33 34 35  ->  "HI12345"
Frame 2: 02 36 37 38 00 00 00 00  ->  "678"
```
Parts car VIN = **ABCDEFGHI12345678** -- a sequential placeholder/test VIN.

### ABS C2202 (Original VIN Mismatch) -- confirmed

The ESC module stores the original VIN programmed at manufacture. C2202 fires when the
VIN it reads from the bus (0x6FA, sourced from the GWM) does not match its stored
value. The parts car GWM is broadcasting placeholder VIN `ABCDEFGHI12345678`, which
does not match any real Coda VIN -- this is a factory default or reprogrammed
placeholder, likely set when the GWM or ESC was replaced or not properly VIN-coded.

The vin_search.py grep found 0 frames in the parts car log matching any 3-byte
subsequence of the normal Coda VIN, confirming the VINs are completely disjoint.

---

## Phase 5 -- IPK Dash Light Bit Sweep (2026-03-05)

Artifacts: `analyze_491_normal.txt`, `analyze_491_partscar.txt`, `analyze_492_normal.txt`.

### 0x491 B0:B1:B2 -- odometer (24-bit BE, 0.1 km/count)

```
         B0             B1
Normal:  0x08 = 0000_1000   0x5B = 0101_1011
Parts:   0x0F = 0000_1111   0x41 = 0100_0001
```

B0 and B1 are **completely fixed throughout each capture**, including the normal Coda
lamp test window (t=9-38s). The IPK lamp test commanded by 0x271 does NOT change them,
and the normal Coda RED fault lamp event at t=136s also does not change them.

They are fixed because **B0:B1:B2 is a 24-bit big-endian odometer at 0.1 km/count** --
odometer mileage does not change measurably over a short capture, so the high bytes stay
constant. The earlier "IPK fault state latched at key-on" reading was wrong: the cross-car
byte differences are accumulated *mileage*, not fault bits.

**Decoded odometer:** reference car 0x085B57 = 547671 -> ~34.0k mi; parts car
0x0F41EA = 999914 -> ~62.1k mi. B2 is the least-significant byte (normal 0x57-0x9B,
parts car 0xE9-0xEB); its slow count within each capture is the 0.1 km digit ticking,
consistent with the phase-4 CODACAN scan that showed B2 drives the ODO display.

**The internal tell:** another Coda (Part B) shows B0 == the parts car's B0 == 0x0F
despite an entirely different fault set from the parts car. If B0 were a fault latch the
two cars could not share it while differing in their faults; B0 matching is simply two
cars near the same odometer high byte. B0 is the odometer high byte, not a fault latch.

**B3:** 4-5 unique values in both logs (0x00-0x33 range). Likely lighting state
(Interior Illum, Side Light, Low Beam -- confirmed field set for this ID).

### 0x492 -- second odometer / IPK-cluster broadcast, all-zeros in parts car

In normal Coda, 0x492 mirrors 0x491 B0:B1:B2 exactly (B0=0x08, B1=0x5B, B2 same
active range) -- a second odometer / IPK-cluster broadcast, not an echo of 0x491.
B3=0 always (unlike 0x491 B3 which carries lighting state). 0x492 starts at t=0.08s,
before 0x491 (t=9.55s).

In parts car, 0x492 transmits all zeros for the entire 154s capture. The module
generating 0x492 was silent in the parts car configuration -- the all-zeros is a silent
module, not a fault-related state.

---

# Part B -- Car 2's Car (2026-03-05)

**Log:** `projects/coda/logs/(Car 2 log) 03-08-25 16-14-24.asc` (Vector ASC format)
**Duration:** 1012.87 s  **Frames:** 1,092,308  **Unique IDs:** 39
**Logger:** CODACAN (owned by Car 2, another Coda owner)
**Survey artifact:** `artifacts/survey_car2.txt`

## Bus Identification

All 39 IDs land on Bus 1 (single-bus capture). Bus identity confirmed by anchor IDs:
B CAN anchors present: 0x270, 0x271, 0x381, 0x382, 0x383, 0x390, 0x391, 0x392, 0x3A0,
0x439, 0x48A, 0x491, 0x492. **Conclusion: B CAN.**

D CAN IDs 0x1C0, 0x212, 0x241 are visible as GWM rebroadcasts (same pattern seen on
B CAN in multi-bus logs). No C CAN cell IDs (0x000-0x119) present, confirming this is
not C CAN.

Note: Format is Vector ASC (`.asc`), same as CODACAN nilog. Required adding
`VectorAscParser` to `canre/parsers/vector_asc.py` -- now handles all ASC files project-wide.

## Survey Comparison (B CAN vs my Coda B CAN from defroster2)

### IDs absent from Car 2 log vs my Coda B CAN

| ID | Notes |
|----|-------|
| 0x536 | Absent (also absent in parts car). On C CAN (Bus 2) in multi-bus logs; not native B CAN, not expected in a B-CAN-only capture. |
| 0x7FE | Absent. Parts-car-only diagnostic keepalive; not expected in a healthy car. |

0x600 **is present** at 1.9 Hz (1,932 frames) -- same frequency as my car. Consistent with
a healthy car; absent from parts car.

### 0x271 B0 -- Fault lamp state

Range = 0x01-0x05. YELLOW fault lamp ON throughout (0x01 = YELLOW, 0x05 = YELLOW +
lamp-test flag). Car 2's car has at least one active YELLOW fault.

0x270 B0 = 0x00 fixed throughout -- BMS is **not** the fault source. The active fault
is in a non-BMS module (same logic as parts car Phase 2 analysis).

### 0x3A0 B0 -- SRS/airbag status

Range = 0x20-0x2A, same as my normal Coda. Bit 7 = 0 throughout. **No SRS fault.**
Unlike parts car (0xA0, bit 7 forced HIGH).

### 0x491 / 0x492 -- odometer (24-bit BE, 0.1 km/count)

```
                 B0      B1
My car:          0x08    0x5B   (~34.0k mi)
Parts:           0x0F    0x41   (~62.1k mi)
Another Coda:    0x0F    0x0D   (~61.3k mi)
```

These are the two high bytes of the 24-bit big-endian odometer (0.1 km/count), not a
fault latch. Another Coda's B0:B1:B2 = 0x0F0D4F = 986383 -> ~61.3k mi. Its B0 = 0x0F
matches the parts car's B0 = 0x0F simply because both cars are near the same odometer
high byte -- despite the two cars carrying entirely different fault sets. The differing
B1 (0x0D vs the parts car's 0x41) is the odometer mid byte differing by mileage.

0x492 in another Coda: B0=0x0F, B1=0x0D, mirroring 0x491 B0:B1:B2 exactly -- the second
odometer / IPK-cluster broadcast is active (unlike the parts car's all-zeros). Consistent
with my car's behaviour.

### 0x2C1 B1 -- BMSDrivingRange_Exp

Range = 0x68-0x69 (104-105 decimal). My car's range in defroster2 was 0x00-0x63 (0-99).
Car 2's value exceeds my car's max -- likely higher SoC at time of capture or a different
displayed-range calibration for Car 2's pack.

### 0x382 B0-B2 -- BMSThermal (pack temperature)

Range = 0x8D-0x8E / 0x8E-0x8F / 0x8D-0x8E = 13-14 degC avg/max/min. Narrow range
across 1012 s. Cold ambient, pack temperature barely moved during the capture. No anomaly.

### 0x390 B0-B3 -- HVAC thermal limits

Range = 0x8E-0x90 = 14-16 degC. Similar narrow range to parts car (fixed 0x8E) and
colder than my car (0x80-0x8A). Cold capture again; not a fault indicator.

### 0x378 B2 -- BMSmode

Range = 0xF2-0xF8 (242-248 decimal). My car in driving mode = 0xD2 (210 decimal).
Unknown enum range; not yet decoded. B0 = 0x41 fixed throughout (HVPowermode=4 = HV On
Drive confirmed, Chargemode=1 = No Prox) -- car is in drive mode. The BMSmode difference
(0xF2 vs 0xD2) warrants future investigation.

### 0x600 -- Unidentified module (B CAN + D CAN via GWM)

Present at 1.9 Hz. Confirms the module is active in Car 2's car, same as my car.
Native bus unknown (GWM rebroadcasts to both B CAN and D CAN). Absent from parts car.

## Summary: Car 2's Car vs My Car vs Parts Car

| Signal | My Coda | Car 2's Coda | Parts Car |
|--------|---------|-------------|-----------|
| Fault lamp (0x271 B0) | OFF (0x00) | YELLOW ON (0x01/0x05) | YELLOW ON (0x01/0x05) |
| BMS fault source (0x270 B0) | 0x00 | 0x00 (not BMS) | 0x00 (not BMS) |
| SRS fault (0x3A0 B0 bit7) | 0 | 0 (no fault) | 1 (B1382+B2505) |
| Odometer high byte (0x491 B0) | 0x08 (~34.0k mi) | 0x0F (~61.3k mi) | 0x0F (~62.1k mi) |
| Odometer mid byte (0x491 B1) | 0x5B | 0x0D | 0x41 |
| 0x492 active | Yes (2nd odo broadcast) | Yes (2nd odo broadcast) | No (all-zeros, module silent) |
| BMSmode (0x378 B2) | 0xD2 (210) | 0xF2-0xF8 (242-248) | 0xF2-0xF8 (same as Car 2) |
| DrivingRange_Exp (0x2C1 B1) | 0-99 | 104-105 | 0xAA-0xAC (invalid sentinel) |
| Pack temp (0x382) | 10-25 degC | 13-14 degC (cold) | 13-14 degC (cold) |
| 0x600 | Present 1.9 Hz | Present 1.9 Hz | Absent |
