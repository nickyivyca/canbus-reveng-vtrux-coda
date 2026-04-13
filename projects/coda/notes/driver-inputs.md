# Driver Input Signals Analysis

**Logs analyzed:**
- `pressingthrottlethenbrake.log` (2.1 MB, 40,315 frames, 14.5s)
- `prndnrp-twice once in just key on and then once after keying to ready.log` (5.2 MB, 99,367 frames, 38.5s)

**Analyzed:** 2026-02-19

---

## Channel Identification

Both logs contain all 3 buses, identified by anchor IDs:

| Bus    | Confidence | Anchor IDs |
|--------|------------|------------|
| C CAN  | Definitive | 0x000-0x019 (cell voltages) |
| D CAN  | High       | 0x1C0, 0x208, 0x212, 0x315, 0x418 (all DLCM_Recvd IDs present) |
| B CAN  | High       | 0x48A, 0x1D7, 0x381, 0x410/0x439, 0x390/0x391 (B CAN exclusive) |

**New finding**: D CAN now identifiable by its own content (DLCM_Recvd + misc_Recvd + ESC IDs), no longer just process-of-elimination. See Gateway Rebroadcast section below.

---

## Throttle Pedal Position

### Signal Location

| Parameter | Value |
|-----------|-------|
| Bus | D CAN (rebroadcast to B CAN) |
| Message ID | 0x210 (528 dec) |
| Byte | B2 |
| Width | 8-bit unsigned |
| Scale | 0.4 (VICD: `Vehicle_Mode` cluster) |
| Range | 0-249 raw = 0-99.6% |
| Idle value | 0x00 |
| Update rate | 50 Hz |
| DLC | 6 bytes |
| Confidence | **HIGH** |

### Evidence

Throttle/brake log — controlled test: press throttle, hold, release, then press/release brake.

**Ramp up** (t=3.03-3.19s, ~160ms):
```
0x00 -> 0x0F -> 0x23 -> 0x3B -> 0x5A -> 0x80 -> 0xA9 -> 0xD1 -> 0xF7 -> 0xF9
 0%     6%     14%    24%    36%    51%    68%    84%    99%    100%
```

**Hold at 0xF9** (249 raw = 99.6%) from t=3.19-4.33s (~1.1s).

**Ramp down** (t=4.33-4.41s, ~80ms):
```
0xF9 -> 0xD8 -> 0x9F -> 0x59 -> 0x17 -> 0x00
```

Signal is zero during brake portion (t=6.6-8.2s) — clean temporal isolation. Identical pattern observed on B CAN via gateway rebroadcast.

### Other signals in 0x210

| Byte | Value/Range | Notes |
|------|-------------|-------|
| B0 | 0x00 | Constant (both logs) |
| B1 | 0x00 | Constant (both logs) |
| B2 | 0x00-0xF9 | **ThottlePedalPos (%)** |
| B3 | 0x00/0x80 | Toggle bit — alive/heartbeat, not a signal |
| B4 | 0x00/0x80 | Toggle bit — alive/heartbeat, not a signal |
| B5 | 0x00 | Constant |

---

## Brake Signals

### Brake Pressure (ESC — 0x208)

| Parameter | Value |
|-----------|-------|
| Bus | D CAN (rebroadcast to B CAN) |
| Message ID | 0x208 (520 dec) — BS_208h cluster |
| Bytes | B2-B3 (BE uint16) |
| Width | 16-bit unsigned |
| Idle value | 0x1000 (4096) |
| Active range | 0x1000-0x15AE (4096-5550) |
| Effective range | 0-1454 counts above idle offset |
| Update rate | 100 Hz |
| DLC | 8 bytes |
| Confidence | **HIGH** |

### Evidence

Throttle/brake log — active from t=6.65-8.15s (brake press/release):
- Smooth monotonic ramp up to peak 0x15AE at t=7.24s
- Smooth ramp down back to 0x1000
- Zero variation during throttle portion (t=0-6s)
- 79 unique values — genuine analog pressure signal

The idle value of 0x1000 is a fixed offset (zero-pressure baseline). The lower 12 bits of the idle value are 0x000, suggesting possible 12-bit ADC origin.

### Full 0x208 frame structure

| Byte(s) | Signal | Value/Range | Notes |
|---------|--------|-------------|-------|
| B0 | (unused?) | 0x00 | Constant |
| B1 | ESPSysSts | 0x20 (bit 5) | Active when ESC is on; goes 0x00 at key-off |
| B2-B3 | BrakePressure | 0x1000-0x15AE | BE uint16, offset 0x1000 at zero |
| B4-B5 | WheelSpeed_RR (right rear) | 0xC000 | Zero speed; 0xC000 = center offset |
| B6-B7 | WheelSpeed_LR (left rear) | 0xC000 | Zero speed; 0xC000 = center offset |

WheelSpeed_RR (B4-B5) and WheelSpeed_LR (B6-B7): BE uint16, zero = 0xC000 (49152). These are ESC-measured non-driven rear wheel speeds (Coda is FWD). Assignment confirmed via Ackermann behavior and C102B DTC (right rear sensor). Scale TBD. See `notes/traction-control-analysis.md`.

### Brake Switch

**Not found** as a clean binary signal in these captures.

The LabVIEW inventory shows `Brake_SW` (Boolean) in the DLCM and FCM_1 clusters, but no byte-level binary corresponding to brake press/release timing was detected. Possibilities:
- [ ] Embedded as a single bit within a "noisy" byte (masked by counter or other signals)
- [ ] On a message that requires bit-level analysis (the status_events tool operates at byte level)
- [ ] The DLCM cluster CAN ID may not be in the captured set — it could be a message we haven't seen

### Brake-correlated signals (not yet decoded)

**0x312 B4-B5** transitions exactly at brake press (t=6.71s) and release (t=8.15s):

| Phase | B4 | B5 | Timing |
|-------|----|----|--------|
| Idle | 0x0C | 0x7F | Before brake |
| Transitional | 0x0B | 0x2E | t=6.71 (press) |
| Brake active | 0x08 | 0x47 | t=6.73 |
| Transitional | 0x0B | 0xC3 | t=8.15 (release) |
| Idle | 0x0C | 0x7F | t=8.17 |

0x312 is an unidentified 100 Hz D CAN message (not in any disassembled VI). It may contain a brake indicator or status. D CAN exclusive — not rebroadcast to B CAN.

---

## PRND Gear Selector

### Signal Location

| Parameter | Value |
|-----------|-------|
| Bus | D CAN (rebroadcast to B CAN) |
| Message ID | 0x418 (1048 dec) |
| Byte | B0 |
| Width | 8-bit unsigned |
| Encoding | **ASCII character codes** |
| Update rate | 50 Hz |
| DLC | 6 bytes |
| Power state | Broadcasts in both key-on and Ready mode |
| Confidence | **HIGH** |

### Enumeration

| Raw (hex) | Raw (dec) | ASCII | Gear |
|-----------|-----------|-------|------|
| 0x50 | 80 | 'P' | Park |
| 0x52 | 82 | 'R' | Reverse |
| 0x4E | 78 | 'N' | Neutral |
| 0x44 | 68 | 'D' | Drive |

### Evidence

PRND log — two P-R-N-D-N-R-P cycles:

**Cycle 1 (key-on only, HV off):**
| Time | B0 | Gear |
|------|-----|------|
| t=0-5.1s | 0x50 | P |
| t=5.11 | 0x52 | R |
| t=5.93 | 0x4E | N |
| t=7.91 | 0x44 | D |
| t=9.71 | 0x4E | N |
| t=11.57 | 0x52 | R |
| t=13.71 | 0x50 | P |

**Cluster 2** (t=17-21s): Ready mode activation — not a gear cycle.

**Cycle 2 (Ready mode, HV on):**
| Time | B0 | Gear |
|------|-----|------|
| t=21-24.1s | 0x50 | P |
| t=24.11 | 0x52 | R |
| t=25.03 | 0x4E | N |
| t=26.53 | 0x44 | D |
| t=27.81 | 0x4E | N |
| t=29.13 | 0x52 | R |
| t=31.21 | 0x50 | P |

Both cycles produce identical staircase patterns. Signal is present regardless of HV power state.

> **VICD correction**: 0x418 was previously hypothesized as MCM_Temperature (DLCM_Recvd). This is **incorrect** — it is the DLCM_Globals message carrying the `PRND` (NumUInt8) signal.

### 0x418 B4 — Gear Status / Park Lock Related

B4 transitions in correlation with PRND but with intermediate values during shifts:

| Gear | B4 stable value |
|------|----------------|
| P | 0xDD |
| R | 0xBB |
| N | 0x00 |
| D | 0x11 |

Transition values (0xBD, 0xDB) appear briefly during gear changes. This could be a park lock position or interlock status byte.

### Other signals in 0x418

| Byte | Value/Range | Notes |
|------|-------------|-------|
| B0 | 0x44-0x52 | **PRND** (ASCII) |
| B1 | 0x00 | Constant |
| B2 | 0x00 | Constant |
| B3 | 0x00 | Constant |
| B4 | 0x00-0xDD | Gear status / park lock (see table above) |
| B5 | 0x00 | Constant |

---

## Additional Signals Found

### 0x308 B0 — Park Position Indicator

| Parameter | Value |
|-----------|-------|
| Bus | D CAN only (NOT rebroadcast to B CAN) |
| Message ID | 0x308 (776 dec) |
| Byte | B0 |
| Values | 0x20 = in Park, 0x40 = out of Park, 0x00 = key-off |
| DLC | 5 bytes |
| Update rate | 100 Hz |
| Confidence | Medium |

Transitions ~1s BEFORE the actual PRND change (t=4.21 vs t=5.11 for first R shift) — likely the park lock mechanism state, not the gear selector position. The PRND changes only after the lock fully disengages.

### 0x240 B0 — System State / Power Mode

| Parameter | Value |
|-----------|-------|
| Bus | D CAN (rebroadcast to B CAN) |
| Message ID | 0x240 (576 dec) |
| Byte | B0 |
| Values | 0x11 = key-on (HV off), 0x01 = Ready (HV on) |
| Confidence | Medium |

Only observed in PRND log (which has both power states). In throttle/brake log (already Ready), constant at 0x01.

### 0x278 B0-B1 — HV/Drive Ready Status

In PRND log: transitions from 0x01/0x40 to 0x00/0x00 at key-off (t=35.55). The mask 0x40 (B1 bit 6) matches the VICD-identified mask from DLCM_Recvd handler at 0x278. This appears to be a drive-ready or HV-active flag, not a brake switch.

---

## Gateway Rebroadcast (GWM)

### D CAN → B CAN (direct pass-through, same arb ID)

The following D CAN messages appear identically on B CAN:

| ID (hex) | Signal content | Confirmed by |
|----------|---------------|-------------|
| 0x210 | Throttle pedal position | Identical ramp in both D CAN and B CAN status_events |
| 0x208 | ESC brake pressure, wheel speeds | Identical B2 counter and B3 pressure on both buses |
| 0x418 | PRND gear selector | Present on both buses in survey |
| 0x1C0 | MCM data (motor signals) | Same count/freq on both buses |
| 0x200 | Heartbeat/counter | Same on both buses |
| 0x212 | EPS steering angle | Same on both buses |
| 0x215 | TCM signal | Same on both buses |
| 0x240 | System state | Same on both buses |
| 0x241 | Signed bytes (TCM/FCM?) | Same transitions on both buses |
| 0x248 | Mode flags | Same transitions on both buses |
| 0x278 | HV/drive status | Same on both buses |
| 0x315 | Counter + flags | Same on both buses |
| 0x370 | Death Counter batch | Same on both buses (different B0 count on B CAN) |
| 0x600 | TPMS pressure | Same on both buses |
| 0x276 | HVAC / body electronics status | Confirmed in Part 2 (driverinputpart4.log) |
| 0x6FA | Rolling data | Same on both buses |

### B CAN → D CAN (direct pass-through, same arb ID)

| ID (hex) | Signal content |
|----------|---------------|
| 0x275 | BMS discharge/charge limits |
| 0x383 | SoC |
| 0x1D5 | DCDC Status1 |

### D CAN exclusive (NOT rebroadcast)

0x08C, 0x300, 0x308, 0x312, 0x325, 0x330, 0x580

> **Correction (Part 2)**: 0x276 was previously listed as D CAN exclusive. The driverinputpart4.log confirms 0x276 appears on both D CAN and B CAN — it is gateway-rebroadcast.

### B CAN exclusive (NOT rebroadcast)

0x07D, 0x1D7, 0x270, 0x271, 0x2C1, 0x2C2, 0x378, 0x381, 0x382, 0x390, 0x391, 0x392, 0x3A0, 0x410, 0x439, 0x48A, 0x492, 0x620

### Common (origin unclear)

0x051, 0x052, 0x080, 0x491

> **Prior assumption corrected**: Previous analysis stated "zero shared IDs" between buses (confirmed from codacharging.log B+C CAN). That finding is correct for B↔C CAN. The GWM gateway DOES bridge D↔B CAN traffic extensively. The C CAN BMS port remains fully isolated.

---

## Signal Confidence Summary

| Signal | Bus | ID | Byte(s) | Encoding | Confidence |
|--------|-----|-----|---------|----------|------------|
| Throttle Pedal Position (%) | D CAN | 0x210 | B2 | uint8 × 0.4 | HIGH |
| Brake Pressure (ESC) | D CAN | 0x208 | B2-B3 | BE uint16, offset 0x1000 | HIGH |
| ESPSysSts | D CAN | 0x208 | B1 bit 5 | Boolean | HIGH |
| WheelSpeed_RR (right rear) | D CAN | 0x208 | B4-B5 | BE uint16, center 0xC000 | Scale TBD |
| WheelSpeed_LR (left rear) | D CAN | 0x208 | B6-B7 | BE uint16, center 0xC000 | Scale TBD |
| PRND | D CAN | 0x418 | B0 | uint8 ASCII (P/R/N/D) | HIGH |
| Gear Status | D CAN | 0x418 | B4 | uint8 enum | Medium |
| Park Indicator | D CAN | 0x308 | B0 | 0x20/0x40/0x00 | Medium |
| System State | D CAN | 0x240 | B0 | 0x11=key-on, 0x01=Ready | Medium |
| HV/Drive Ready | D CAN | 0x278 | B1 bit 6 | Boolean (mask 0x40) | Medium |
| Brake Switch | D CAN | ? | ? | Boolean | NOT FOUND |

---

## DBC Updates Required

1. **0x210**: Change placeholder ID 8193 (DLCM) → 0x210 for Vehicle_Mode cluster. Add `ThottlePedalPos` signal at B2, scale 0.4, offset 0, range 0-249.
   > Wait — 0x210 is already in misc_Recvd dispatch, hypothesized as Vehicle_Mode. The throttle signal is B2. The VICD scale for 0x210 was 0.4, which matches. But ThottlePedalPos was in the DLCM cluster (different cluster). This means 0x210 carries BOTH Vehicle_Mode and throttle data — the DLCM reads throttle from this message via global data sharing.
2. **0x208 (ESC_BS_208)**: Already has real CAN ID in skeleton. Update BrakePressure to B2-B3 BE uint16 with offset 4096. Add DHL (B4-B5) and DHR (B6-B7) as BE uint16 with offset 49152 (0xC000). ESPSysSts = B1 bit 5.
3. **0x418**: Change from MCM_Temperature placeholder → DLCM_Globals. Add `PRND` at B0 (uint8). Add gear status at B4 (uint8).
4. **0x308**: New message — ParkIndicator at B0.
5. **0x240**: Add SystemState at B0.
6. **0x278**: Confirm B1 bit 6 = HV/Drive Ready flag.

---

## Data Artifacts

All in `artifacts/` — see `artifacts/README.md` for full inventory.

| File | Contents |
|------|----------|
| `artifacts/throttle_0x210_B2.csv` | 0x210 B2 timeseries from throttle/brake log (728 samples) |
| `artifacts/brake_0x208_B3.csv` | 0x208 B3 timeseries from throttle/brake log (1457 samples) |
| `artifacts/brake_0x208_B23.csv` | 0x208 B2-B3 16-bit timeseries from throttle/brake log (1457 samples) |
| `artifacts/throttle_0x210_B3.csv` | 0x210 B3 timeseries — alive/toggle bit, not a signal |
| `artifacts/throttle_0x248_B01.csv` | 0x248 B0-B1 timeseries — mode state change |

---

## Cross-Validation Against Driving Log

Signals validated against `codadriveslowturnonwithdefroster2.log` (~12 min drive, 3 buses).

### Throttle (0x210 B2) — PASS

- 69,690 samples over 697s. Range 0–213 raw (0–85.2%).
- Zero during startup/idle (first 45s). 30 throttle application events during driving.
- 58% of driving time with throttle >0. Natural distribution: bulk 20–60%, few samples >80%.
- Smooth ramps, variable peaks, realistic event durations (0.3–33s). Zero at end.

### PRND (0x418 B0) — PASS

- 69,690 samples. Only the 4 expected ASCII values: P(80), R(82), N(78), D(68).
- Sequence: P → R (backing out, t=40s) → N→D (0.2s pass-through) → D for 10 min → R/D/P parking churning (t=648–697s) → P.
- 22 total transitions. N appears only as brief transients between R↔D shifts (<0.2s each).
- 88% of time in D. Structure matches: key-on → back out → drive → park at destination.

### Brake Pressure (0x208 B2-B3) — PASS

- 138,460 samples (~200 Hz — both D+B CAN buses). Range 4095–5173 raw.
- Idle at 4096 (0x1000) confirmed: 74.7% of samples exactly at idle, near-zero noise.
- 38 braking events. Peak 5173 (+1077 above idle) — moderate, no emergency stops.
- Pattern correlates with PRND/throttle: heavy brake at first R shift, 3-min zero-brake cruise gap, dense braking during parking maneuvers at end.

### Cross-Signal Coherence

| Phase | Time | Throttle | PRND | Brake |
|-------|------|----------|------|-------|
| Key-on / startup | 0–40s | Zero | P | Idle |
| Back out | 40–54s | Zero | R | Hard brake + taps |
| Shift to drive | 54–55s | First app | R→N→D | Light tap |
| Driving | 55–648s | 30 cycles, 20–85% | D (solid) | 38 events, cruise gaps |
| Parking | 648–697s | Zero | D/R/P churning | Dense cluster |
| Final park | 697–707s | Zero | P | Idle |

Cross-validation artifacts in `artifacts/`: `xval_throttle_0x210_B2.csv`, `xval_prnd_0x418_B0.csv`, `xval_brake_0x208_B23.csv`.

---

## Next Steps (Part 1)

- [x] ~~Find brake switch~~ — Found: 0x315 B0.bit0 (see Part 2 below)
- [ ] Determine DHL/DHR wheel speed scale factor from a driving log (speeds > 0)
- [ ] Characterize brake pressure scale factor (need known physical reference)
- [x] ~~Decode 0x312~~ — Initial observations in Part 3 below; interpretation is unclear. See `notes/traction-control-analysis.md` for the more complete decode.
- [ ] Update D CAN skeleton DBC with confirmed signals
- [ ] Investigate 0x418 B4 gear status byte intermediate values more carefully
- [ ] Fix `--bus` filter in `extract_timeseries.py` — returned 0 samples when filtering by bus number in BUSMASTER multi-bus logs

---

# Part 2: Body Electronics & Accessories Sweep

**Log analyzed:** `driverinputpart4.log` (2,526,357 frames, 921.15s, 169 IDs across 3 buses)
**Sidecar:** `driverinputpart4.txt` (stopwatch timestamps for each input activation)
**Analyzed:** 2026-02-20

---

## Channel Identification

| Bus | Identity | IDs | Anchor IDs |
|-----|----------|-----|------------|
| 1 | C CAN | 99 | 0x000–0x019 cell voltages (definitive) |
| 2 | D CAN | 31 | 0x308, 0x312, 0x325, 0x330, 0x580 (D CAN exclusive) |
| 3 | B CAN | 40 | 0x1D5, 0x48A, 0x381, 0x410/0x439 (B CAN exclusive) |

**No new IDs appeared on B or D CAN** versus prior captures. All body electronics signals are carried within existing messages as byte/bit-level changes. C CAN showed 52 new IDs (0x100–0x119 cell temps?, plus BMS telemetry) — not the focus of this investigation.

---

## Timestamp Alignment

**Offset ≈ +1–2s** (log time = stopwatch time + 1–2 seconds). Verified with 3 independent anchors:

| Anchor | Stopwatch | Log time | Offset |
|--------|-----------|----------|--------|
| AC enable (0x410 B2→0x40) | 6:30 (390s) | 391.95s | +2.0s |
| AC disable (0x410 B2→0x00) | 6:50 (410s) | 412.06s | +2.1s |
| Brake switch ON (0x315 B0.bit0) | 8:45 (525s) | 525.79s | +0.8s |

Stopwatch imprecision accounts for the ~1s variation between anchors. Stopwatch times can be used directly for ±3s correlation.

---

## Brake Switch (NEW — discovered during Part 2, validated against Part 1)

### Signal Location

| Parameter | Value |
|-----------|-------|
| Bus | D CAN (rebroadcast to B CAN) |
| Message IDs | **0x315 B0**, 0x212 B2, 0x200 B1 (all three carry identical signal) |
| Bit | **bit 0** (mask 0x01) |
| Width | 1 bit |
| Encoding | 0 = brake not applied, 1 = brake applied |
| Update rate | 50 Hz (0x315, 0x212) / 100 Hz (0x200) |
| Confidence | **HIGH** |

### Evidence

**driverinputpart4.log** — parking brake test (stopwatch 8:45–9:00):

| Log time | Bit 0 | Event |
|----------|-------|-------|
| 521.79s | 0→1 | Quick brake tap before parking brake release |
| 522.03s | 1→0 | Released brief tap |
| 525.79s | 0→1 | Foot brake held for parking brake release |
| 542.05s | 1→0 | Foot brake released after parking brake re-applied |

Only 4 transitions in the entire 921-second log — all perfectly aligned with foot brake use.

**pressingthrottlethenbrake.log** (Part 1 cross-validation):

| Log time | Bit 0 | Event |
|----------|-------|-------|
| 6.61s | 0→1 | Brake pedal pressed |
| 8.25s | 1→0 | Brake pedal released |

Matches brake pressure profile (0x208 B2-B3 active from t=6.65–8.15s). Switch engages ~40ms before measurable pressure buildup — consistent with physical contact switch on pedal mechanism.

### Why it eluded Part 1

The brake switch is a **single bit embedded in bytes that also contain rolling counters** (bits 2–7). At byte level, these bytes appear "noisy" with many unique values, so they were excluded by the status_events auto-discovery threshold. Bit-level analysis (`--bits` mode) was required to isolate the single-bit brake flag from the counter.

All three carrier bytes (0x315 B0, 0x212 B2, 0x200 B1) have the same structure: bit 0 = brake switch, bits 2–7 = synchronized rolling counter. The counter values are multiples of 4 (0x00, 0x04, 0x08, 0x0C, ..., 0x78, 0x7C) when brake is off, odd values when brake is on.

### LabVIEW correlation

This matches LabVIEW `Brake_SW` (Boolean) in the DLCM cluster. 0x315 is a DLCM_Recvd ID, confirming the DLCM reads the brake switch from this message.

---

## Parking Brake (NEW — discovered during Part 2)

### Signal Location

| Parameter | Value |
|-----------|-------|
| Bus | D CAN and B CAN (both, origin unclear — 0x052 is in "common" category) |
| Message ID | 0x052 |
| Byte | B0 |
| Bit | bit 2 (mask 0x04) |
| Width | 1 bit |
| Encoding | 1 = parking brake engaged (0x0C), 0 = parking brake released (0x08) |
| Update rate | 20 Hz |
| DLC | 8 bytes (B1–B7 all 0x00) |
| Confidence | **HIGH** |

### Evidence

**driverinputpart4.log** — only 2 transitions in 921 seconds:

| Log time | B0 | Bit 2 | Event |
|----------|-----|-------|-------|
| 0.00s | 0x0C | 1 | Parking brake engaged (start of log) |
| 526.52s | 0x08 | 0 | Parking brake released (stopwatch 8:45) |
| 541.17s | 0x0C | 1 | Parking brake re-engaged (stopwatch 9:00) |

**pressingthrottlethenbrake.log** (Part 1): B0 constant 0x0C throughout — parking brake engaged for entire test. Confirms no false triggers.

---

## Event-to-Signal Correlation Map

status_events --bits run on both D CAN (Bus 2) and B CAN (Bus 3). Every tested input produced detectable CAN transitions. The table below summarizes which CAN signals responded to each test input.

### HVAC Group (stopwatch 3:30–7:05, log t ≈ 210–425s)

| Input | Stopwatch | Log t (s) | Primary signal(s) | Notes |
|-------|-----------|-----------|-------------------|-------|
| Mode knob sweep | 3:30 | ~210 | 0x276 B1, B6 | B1 multi-value, B6 changes (D+B CAN) |
| Recirc off | 4:15 | ~255 | 0x276 B0 bits 4-6 | Bit-level flags |
| Rear defroster off | 4:35 | ~275 | 0x276 B0, B5 | Multiple bit transitions |
| Fan step down 4→0 | 5:00 | ~300 | 0x276 B0, B5 | 3 clusters — one per step |
| Fan step up 0→4 | 5:25 | ~325 | 0x276 B0, B2, B5 | B2 also changes (temp/mode coupling?) |
| Temp sweep hot→cold | 6:00 | ~360 | 0x276 B0, B2, B4 | B CAN shows 105 transitions (B CAN has more detail) |
| AC enable | 6:30 | ~390 | 0x276 B1, B2; 0x1C0 B4 | 0x1C0 B4 bits respond to AC (MCM load change?) |
| AC disable | 6:50 | ~410 | 0x276 B1, B2; 0x1C0 B4 | Mirror of AC enable |
| Temp sweep cold→hot | 7:05 | ~425 | 0x276 B0, B2, B4 | Same signals as hot→cold sweep |

**0x276 is the body electronics / HVAC master status message.** Almost all HVAC controls map to different bytes/bits within this single ID. It appears on both D CAN and B CAN (gateway pass-through).

### Steering Group (stopwatch 7:25–8:20, log t ≈ 445–500s)

| Input | Stopwatch | Log t (s) | Primary signal(s) | Notes |
|-------|-----------|-----------|-------------------|-------|
| Center | 7:25 | ~445 | 0x080 B2 bits 3-5 | |
| Full lock left | 7:40 | ~460 | 0x080 B2 bits 1-5; 0x1C0 B0 bits | 0x1C0 responds at extremes |
| Full lock right | 8:00 | ~480 | 0x080 B2 bits 1-5 | |
| Back to center | 8:20 | ~500 | 0x080 B2 bits 3-5 | |

**0x080 B2 responds to steering input**, not 0x212 as expected. 0x080 is a 100 Hz message on both buses. The bit-level changes in B2 track the steering sweep — needs deep-dive to determine if this is the steering angle or a derivative (torque sensor, assist level). 0x212 may carry the actual angle as a continuous value that the status_events tool doesn't capture (it tracks discrete transitions, not analog sweeps).

### Parking Brake (stopwatch 8:45–9:00, log t ≈ 525–542s)

| Signal | ID | Timing | Notes |
|--------|-----|--------|-------|
| Brake switch | 0x315 B0.bit0 | ON at 525.79s, OFF at 542.05s | Foot brake (see above) |
| Parking brake | 0x052 B0.bit2 | OFF at 526.52s, ON at 541.17s | Parking brake (see above) |
| Brake pressure | 0x208 B2-B3 | Spike 525.84–541.91s, peak 5406 | Foot brake pressure |
| 0x312 B4-B5 | 0x312 | Transitions at 525.87 and 541.93 | Brake-correlated (same as Part 1) |
| 0x248 B0, B1 | 0x248 | Transitions at 541.98–542.20 | State change at brake release |
| 0x271 B0 | 0x271 | Transition at parking brake event | B CAN only |

### Lights Group (stopwatch 9:15–9:40 and 12:35–13:30, log t ≈ 555–580 and 755–810s)

| Input | Stopwatch | Log t (s) | Primary signal(s) | Notes |
|-------|-----------|-----------|-------------------|-------|
| Parking lights on | 9:15 | ~555 | 0x248 B1, B6 | B1 bit 4, B6 bits 5-7 |
| Headlights on | 9:25 | ~565 | 0x491 B3; 0x2C2 B0 (B CAN only) | 0x491 B3 bits 2-3 |
| Lights off | 9:40 | ~580 | 0x248 B1, B6 | Reverse of parking lights on |
| Brights flash | 12:35 | ~755 | 0x491 B3; 0x1D5 bits | Momentary — 0x491 B3 bits 1-2 |
| Headlights on | 13:00 | ~780 | 0x248 B1; 0x491 B3 | Same as first HL event |
| Brights on (latched) | 13:10 | ~790 | 0x491 B3; 0x1D5 bits | 0x1D5 B1.bit2, B6.bit2 |
| Brights off | 13:20 | ~800 | 0x491 B3 | |
| Headlights off | 13:30 | ~810 | 0x248 B1, B6; 0x491 B3 | Full reversal |

**0x248 carries parking light / headlight on-off state** (B1 bit 4, B6 bits). **0x491 B3 carries headlight mode / brights status** (multiple bits encode off/parking/low/high). **0x2C2 B0** responds to headlights on B CAN only. **0x1D5** (DCDC Status1) bits respond to brights — likely DCDC load change, not a lighting signal per se.

### Wipers Group (stopwatch 9:50–10:30, log t ≈ 590–630s)

| Input | Stopwatch | Log t (s) | Primary signal(s) | Notes |
|-------|-----------|-----------|-------------------|-------|
| Wipers mist | 9:50 | ~590 | **None** | No CAN state change detected |
| Wiper speed steps | 10:10–10:30 | ~610–630 | **None** | No CAN state change detected |

**Deep-dive correction**: The preliminary correlation attributed 0x276 B0/B5 changes during the wiper window, but deep-dive revealed these are slow thermal drift (B5 = PTCHeaterPWM tracking heating demand, B0 = PTC power consumption). No discrete wiper speed steps are visible. **Wipers are not visible on the captured CAN buses** — likely direct-wired (relay/fuse box, no CAN involvement).

### Seatbelts (stopwatch 11:00–11:15, log t ≈ 660–675s)

| Input | Stopwatch | Log t (s) | Primary signal(s) | Notes |
|-------|-----------|-----------|-------------------|-------|
| Driver seatbelt | 11:00 | ~660 | **0x3A0 B1.bit4** (buckle), **B0.bit3** (warning) | B CAN only |
| Passenger seatbelt | 11:15 | ~675 | **0x3A0 B1.bit2** (buckle) | B CAN only, no warning bit (seat empty) |

**Both seatbelts on 0x3A0 (B CAN only).** Deep-dive confirmed exactly 3 transitions in 921 seconds: driver buckle (t=661.4) clears B1.bit4 + B0.bit3, passenger buckle (t=676.3) clears B1.bit2 only. No passenger was in the car — the driver reached over to buckle the passenger belt — so B0.bit3 is the seatbelt warning indicator (active when driver unbuckled, or when passenger seat occupied AND unbuckled). See deep-dive section below. 0x392 was a false lead — it carries continuously varying OCS weight/pressure data, not buckle state.

### Turn Signals & Hazards (stopwatch 11:45–12:25, log t ≈ 705–745s)

| Input | Stopwatch | Log t (s) | Primary signal(s) | Notes |
|-------|-----------|-----------|-------------------|-------|
| Hazard on | 11:45 | ~705 | **None** | No CAN state change detected |
| Hazard off | 12:00 | ~720 | **None** | |
| Left turn signal | 12:10–12:15 | ~730 | **None** | No CAN state change detected |
| Right turn signal | 12:20–12:25 | ~740 | **None** | No CAN state change detected |

**Deep-dive correction**: The preliminary correlation attributed 0x276 B0/B4 changes and 0x381 B7 to turn signals/hazards, but deep-dive revealed: (1) 0x276 B0/B4 changes are thermal drift, not flasher-related; (2) 0x381 B7 oscillates between 0x60/0x4D throughout the log at 1 Hz, not specific to hazard events; (3) a systematic scan of ALL IDs for rapid toggling during the hazard window (705-720s) found no flasher-rate transitions on any ID. **Turn signals and hazards are not visible on the captured CAN buses** — likely controlled by a flasher relay with no CAN reporting.

### Trunk (stopwatch 14:15, log t ≈ 855s)

| Input | Stopwatch | Log t (s) | Primary signal(s) | Notes |
|-------|-----------|-----------|-------------------|-------|
| Trunk open | 14:15 | ~855 | **None** | No CAN state change detected |

**Deep-dive correction**: 0x383 B1 appeared to change at ~855s, but deep-dive revealed B1 is a monotonically decreasing counter (0x65→0x39 over 921s, ~1 count per 27s). The transition at t=851 is just normal decrement coinciding with the trunk event. **Trunk open is not visible on the captured CAN buses.**

---

## Signal Carrier Summary

| CAN ID | Byte(s) | Signals carried | Bus | Update rate |
|--------|---------|----------------|-----|-------------|
| **0x080** | B2-B3 | Steering angle (BE uint16 ×0.1, center=2000) + B6 counter + B7 CRC8 | D+B CAN | 100 Hz |
| **0x052** | B0 | Parking brake (bit 2) | D+B CAN | 20 Hz |
| **0x248** | B1, B6 | Headlight on/off state | D+B CAN | 50 Hz |
| **0x276** | B0-B6 | HVAC: mode knob (B1), heating/AC flags (B2), PTCHeaterPWM (B5), RadiatorFanPWM (B6) | D+B CAN | ~10 Hz |
| **0x491** | B3 | Headlight mode bitfield: parking/low beam/high beam | B CAN | 10 Hz |
| **0x3A0** | B0, B1 | Seatbelt buckle switches (B1) + warning indicator (B0 bit 3) | B CAN only | 10 Hz |

---

## Part 2 Signal Confidence Summary

| Signal | Bus | ID | Byte/Bit | Encoding | Confidence |
|--------|-----|-----|----------|----------|------------|
| Brake Switch | D+B | 0x315 | B0.bit0 | Boolean (0=off, 1=brake applied) | **HIGH** |
| Parking Brake | D+B | 0x052 | B0.bit2 | Boolean (1=engaged) | **HIGH** |
| Steering Angle | D+B | 0x080 | B2-B3 | BE uint16 ×0.1, center≈2000 | **HIGH** |
| Headlight mode | B | 0x491 | B3 | Bitfield (see decode below) | **HIGH** |
| HVAC heating active | D+B | 0x276 | B2.bit3 | Boolean | **HIGH** |
| HVAC AC active | D+B | 0x276 | B2.bit4 | Boolean | **HIGH** |
| RadiatorFanPWM | D+B | 0x276 | B6 | uint8 ~13% constant during normal operation | CORRECTED (was wrongly labelled "AC compressor request"; 0x22=34 is ~13% duty, not an on/off flag) |
| Driver buckle switch | B only | 0x3A0 | B1.bit4 | 1=unbuckled, 0=buckled | **HIGH** |
| Passenger buckle switch | B only | 0x3A0 | B1.bit2 | 1=unbuckled, 0=buckled | **HIGH** |
| Seatbelt warning | B only | 0x3A0 | B0.bit3 | 1=warning active | MEDIUM |
| HVAC mode knob | D+B | 0x276 | B1 bits 0-1 | 0=face, 2=feet, 3=defog | MEDIUM |
| PTCHeaterPWM | D+B | 0x276 | B5 | uint8 PWM, tracks PTC heater demand (0=off, 0xBA=~72% at 5 kW) | CORRECTED (was wrongly labelled "blower output"; DBC fine sweep 2026-02-26 confirmed PTCHeaterPWM) |
| Headlight on/off | D+B | 0x248 | B1.bit3 | Boolean | MEDIUM |
| Turn signals / hazards | — | — | — | — | Not on CAN |
| Wipers | — | — | — | — | Not on CAN |
| Trunk open | — | — | — | — | Not on CAN |

---

## Deep-Dive Signal Decodes

### Steering Angle — 0x080 B2-B3

| Parameter | Value |
|-----------|-------|
| Bus | D+B CAN (both, origin unclear) |
| Message ID | 0x080 |
| Bytes | B2-B3 (big-endian uint16) |
| Scale | ×0.1 |
| Center | ~2000 (raw 19994 = 1999.4 scaled) |
| Left lock | ~1392 (raw 13915 = 1391.5 scaled) |
| Right lock | ~2523 (raw 25229 = 2522.9 scaled) |
| Update rate | 100 Hz |
| Security | B6 = rolling counter, B7 = CRC8 J1850 checksum |
| Confidence | **HIGH** |

Matches LabVIEW VICD scaling exactly (center=2000, left lock≈1400, right lock≈2600). The smooth sweep profile during steering test (center→left lock→right lock→center at t=445–510s) is unmistakable. The 100 Hz rate + CRC8 is consistent with a safety-critical EPS steering angle message.

**0x212 does NOT carry the steering angle** as a continuous value. 0x212 alternates between exactly 2 fixed data patterns at 25 Hz each (multiplexed sub-frames), with no variation during steering input. It carries the brake switch in B2.bit0 and other status bits.

### 0x276 — HVAC / Body Electronics Status

8-byte message at ~10 Hz on D+B CAN. Carries HVAC system state. Initial frame at baseline: `0F 02 09 3F 61 48 22 4B`.

| Byte | Signal | Encoding | Evidence |
|------|--------|----------|----------|
| B1 bits 0-1 | HVAC mode knob | 0=face, 2=feet, 3=defog | t=196: 0x02→0x03 (defog), t=215: →0x00 (face) |
| B2 bit 3 | Heating active | 1=heating | 0x09 when heat on, 0x01 when off |
| B2 bit 4 | AC active | 1=AC | 0x01→0x11 at AC enable (t=391) |
| B5 | PTCHeaterPWM | uint8 PWM, tracks PTC heater demand | 0xBA (~72%) at high heating load; 0x00 when HVAC off or AC-only. **Correction 2026-03-22**: previously labelled "blower output" — DBC fine sweep (2026-02-26) confirmed this is PTCHeaterPWM. It correlated with fan steps during the test because fan speed and PTC demand scaled together. |
| B6 | RadiatorFanPWM | uint8 PWM ~13% constant | 0x22=34 throughout log. **Correction 2026-03-22**: previously labelled "AC compressor request" — 0x22 is ~13% radiator fan duty (constant), not an AC on/off flag. |
| B0 | Temperature-related | Slowly varying, 0 when HVAC off | Correlates with heating output, not a direct setpoint |
| B3 | Cabin/evaporator temp sensor | Slowly varying (0x3E–0x4D range) | Tracks cabin temperature with thermal lag |
| B4 | Unknown slow metric | Slowly increasing, drops when fan active | May be thermal accumulator or energy metric |
| B7 | Unknown | Only active at log start, then 0x00 | Possibly initialization data |

**B1 during AC enable/disable**: B1 briefly oscillates (0→7→8→5→3→2→1→2) during AC compressor engagement, then settles. The upper bits (2-3) appear to carry AC compressor transient state, separate from the mode knob in bits 0-1.

**Fan speed / B5 correction**: B5 is PTCHeaterPWM (DBC confirmed), not blower output. It appeared to track fan steps because PTC heater demand scales with fan speed when heating. The cabin air blower speed is not directly visible on the captured buses.

### 0x491 B3 — Headlight Mode Bitfield

| Bit | Mask | Signal |
|-----|------|--------|
| 0 | 0x01 | Marker/tail lights |
| 1 | 0x02 | Marker/tail lights (redundant with bit 0) |
| 4 | 0x10 | Parking/position lights |
| 5 | 0x20 | Low beam headlights |
| 6 | 0x40 | High beam (brights) |

Observed states and their meaning:

| B3 value | Binary | State | Log time |
|----------|--------|-------|----------|
| 0x00 | 00000000 | All off | Baseline |
| 0x10 | 00010000 | Parking lights (initial, bit 4 only) | t=556.18 |
| 0x13 | 00010011 | Parking lights + markers (stabilized) | t=556.48 |
| 0x33 | 00110011 | Low beam + parking + markers | t=566.28 (headlights on) |
| 0x73 | 01110011 | High + low + parking + markers | t=791 (brights latched) |
| 0x60 | 01100000 | Flash-to-pass (high+low only, no parking/markers) | t=756 (brights flash momentary) |

The parking→headlights transition is bit 5 (0x20) going high at t=566, matching stopwatch 9:25 (~565s). Flash-to-pass (0x60) activates high+low beams without the parking light circuit — consistent with a momentary flash where the headlight switch isn't in the "on" position.

### 0x248 — Exterior Lights / Instrument Dimming (LOW confidence)

50 Hz on D+B CAN. Mostly constant `00 03 00 00 04 00 03 00`. Active bytes: B1, B6.

- **B1 bit 3** (0x08 mask): Set when exterior lights first activated (t=556, parking lights on). Cleared when lights turned fully off (t=581). Does **not** distinguish between parking lights and headlights — just "any exterior lights on."
- **B6**: 3 values observed (0x00, 0x03, 0x04). Went from 0x03 (baseline) to 0x04 at first light activation and **never returned to 0x03** even after lights were turned off. May be related to instrument panel dimming (night mode) or light switch position memory rather than actual exterior light state. Brief 0x00 glitches during transitions.
- **B0 bit 3**: Brief transient during parking brake release — not light-related.

This car does not have daytime running lights. 0x248 is not useful for determining headlight mode — use 0x491 B3 for that. 0x248 B6 may carry an interior dimming signal or similar — needs further investigation.

### 0x3A0 — Seatbelt Status

10 Hz, B CAN only. Only B0-B1 vary; B2-B7 constant 0x00. Exactly 3 transitions in 921 seconds.

| Time | B0 | B1 | Event |
|------|----|----|-------|
| 0.03s | 0x28 (bit 3=1) | 0x14 (bit 4=1, bit 2=1) | Both unbuckled |
| 661.38s | 0x20 (bit 3=0) | 0x04 (bit 4=0, bit 2=1) | Driver buckled |
| 676.28s | 0x20 (bit 3=0) | 0x00 (bit 4=0, bit 2=0) | Passenger buckled |

- **B1 bit 4**: Driver buckle switch (1=unbuckled, 0=buckled)
- **B1 bit 2**: Passenger buckle switch (1=unbuckled, 0=buckled)
- **B0 bit 3**: Seatbelt warning indicator (1=warning active). Clears when driver buckles. No passenger was in the car during this test (driver reached over to buckle the passenger belt), so the warning was only active for the driver. To confirm whether this is a combined warning (driver OR occupied-passenger unbuckled), a future log with a passenger sitting unbuckled is needed.

### Inputs Not Visible on CAN

| Input | Method of confirmation |
|-------|----------------------|
| **Turn signals / hazards** | Scanned every bit on every ID for rapid toggling (flasher rate) during hazard window (705-720s). No flasher-rate transitions found on any ID. |
| **Wipers** | 0x276 B5 changes during wiper window are slow PTCHeaterPWM drift, not discrete wiper speed steps. No other ID shows wiper-correlated transitions. |
| **Trunk open** | 0x383 B1 appeared to change at ~855s but is actually a monotonically decreasing counter (~1 count/27s). The decrement coincided with the trunk event by chance. |
| **Fan speed setting** | The discrete knob positions (0/1/2/3/4) are not directly encoded on the captured buses. 0x276 B5 is PTCHeaterPWM, not cabin blower speed. |

These inputs are likely controlled by direct wiring (relay, fuse box, or body controller with no CAN reporting on the captured buses).

---

## Data Artifacts (Part 2)

All in `artifacts/` — see `artifacts/README.md` for full inventory.

| File | Contents |
|------|----------|
| `artifacts/driverinput4_dcan_status_events_bits.txt` | D CAN status_events --bits output (full log) |
| `artifacts/driverinput4_bcan_status_events_bits.txt` | B CAN status_events --bits output (full log) |
| `artifacts/di4_brake_0x208_B23.csv` | Brake pressure timeseries (91,886 samples) |
| `artifacts/di4_steering_0x212_B23.csv` | 0x212 B2-B3 timeseries (45,939 samples) |

---

## Next Steps (Part 2)

- [x] Deep-dive 0x276: HVAC mode (B1), heating/AC flags (B2), PTCHeaterPWM (B5), RadiatorFanPWM (B6). B0/B3/B4 partially characterized. **Correction 2026-03-22**: B5/B6 were wrongly labelled blower/AC-request — see DBC.
- [x] Deep-dive 0x248: B1 bit 3 = "lights on" boolean. B6 = unknown (dimming?). Low confidence — use 0x491 instead.
- [x] Deep-dive 0x491 B3: headlight mode bitfield fully decoded (parking/low/high beam + flash-to-pass)
- [x] Deep-dive 0x080 B2-B3: steering angle confirmed — BE uint16 ×0.1, center=2000, matches LabVIEW exactly
- [x] Ruled out 0x212 as steering angle — it's multiplexed sub-frames, not continuous data
- [x] Deep-dive 0x3A0: driver buckle (B1.bit4), passenger buckle (B1.bit2), warning lamp (B0.bit3)
- [x] Ruled out 0x392 as seatbelt — it's OCS weight/pressure data
- [x] Ruled out 0x381 B7 as hazard/trunk — it's a slow counter
- [x] Confirmed: turn signals, hazards, wipers, trunk NOT on CAN
- [ ] Cross-validate steering angle (0x080) and headlight mode (0x491) against driving logs
- [ ] Capture a log with passenger seated + unbuckled to differentiate 0x3A0 B0.bit3 (warning lamp vs driver-only)
- [ ] Characterize 0x276 B0 (temperature-related) and B3 (cabin temp sensor) more precisely
- [ ] Investigate 0x248 B6 further (interior dimming? light switch position?)
- [ ] Update skeleton DBCs with new confirmed signals
- [ ] Update notes/README.md, coda.md, artifacts/README.md (housekeeping)

---

# Part 3: Analog Brake Pedal Travel Signal Investigation

**Logs analyzed:**
- `pressingthrottlethenbrake.log` (primary: clean brake press/release, t=6.6-8.2s)
- `driverinputpart4.log` (cross-validation: foot brake hold, t=525-542s)
- `codadriveslowturnonwithdefroster2.log` (cross-validation: 37 braking events during driving)

**Analyzed:** 2026-02-20

---

## Hypothesis

The Coda EV uses regenerative braking, which requires the DLCM to know brake pedal position before hydraulic pressure builds (the "free stroke" regen zone). The LabVIEW decompile shows a `BrakeCount` signal (NumFloat64) in both the DLCM and FCM_1 clusters, alongside `Brake_SW` and `ThottlePedalPos(%)`. The name "Count" suggests raw ADC counts from a pedal travel sensor. Goal: find this signal on D CAN.

## Method

### Candidates examined

| ID | Bytes | Rationale |
|----|-------|-----------|
| 0x312 | B4-B5 | Known brake-correlated from Part 1; D CAN exclusive, 100 Hz |
| 0x241 | All | DLCM_Recvd dispatch; signed bytes; FCM_1 cluster candidate |
| 0x315 | B1, B3, B5 | VICD shows 0.1 scale on these bytes; could carry BrakeCount |
| 0x1C0 | All | MCM message; motor signals should show regen response |
| ALL D CAN | All bytes | Systematic mean-shift scan: quiet (0-5s) vs brake (6.6-8.2s) |
| ALL B CAN | All bytes | Systematic mean-shift scan for exclusive B CAN signals |

### Systematic scan methodology

For every byte of every CAN ID on D CAN, computed mean value during quiet window (0-5s) and brake window (6.6-8.2s). Flagged any byte with mean shift > 2 counts AND shift > 2x quiet-window standard deviation. Repeated for B CAN. Also scanned for 16-bit big-endian pairs and checked unique value counts during brake.

---

## Results: No Analog Brake Pedal Travel Signal Found

### Systematic scan — D CAN (pressingthrottlethenbrake.log)

Only 5 bytes showed significant mean shift during braking:

| ID | Byte | Quiet mean | Brake mean | Shift | Unique (brake) | Identity |
|----|------|-----------|-----------|-------|----------------|----------|
| 0x208 | B3 | 0.0 | 131.9 | 131.9 | 74 | **Brake pressure (known)** |
| 0x312 | B5 | 127.0 | 77.1 | 49.9 | 4 | Discrete states (see below) |
| 0x208 | B2 | 16.0 | 19.8 | 3.8 | 6 | Brake pressure high byte |
| 0x312 | B4 | 12.0 | 8.4 | 3.6 | 3 | Discrete states (see below) |
| 0x600 | B5 | 164.2 | 169.3 | 5.1 | 2 | TPMS slow drift (not brake) |

No byte on D CAN or B CAN showed >10 unique values during braking other than 0x208 B2-B3.

### B CAN exclusive

Zero B CAN-exclusive bytes showed brake-correlated shifts. All detected shifts were gateway rebroadcasts of D CAN signals.

### Candidates ruled out

| Candidate | Result | Evidence |
|-----------|--------|----------|
| **0x312 B4-B5** | Discrete status, not analog pedal | 4 unique states when stationary; becomes analog only during driving (speed-dependent, see below) |
| **0x241** | Constant during brake | 1 Hz, all bytes constant (0x3D/0x3D/0x44/0x48/0x00/0x3D/0x3D/0x3C) — likely temperatures |
| **0x315 B1, B3** | Zero throughout | Constant 0x00 in both quiet and brake windows |
| **0x315 B5** | Battery voltage | Constant 0x8A-0x8B (13.8-13.9V at 0.1 scale = Batt_Volt from VICD) |
| **0x1C0 (MCM)** | No brake response when stationary | B2 varies ±3 counts (noise), no systematic shift |
| **0x278** | HV/Drive Ready status | Not brake-related (confirmed in Part 1) |

---

## 0x312 B4-B5 — Reclassified as ESC Deceleration / ABS Status

> **SUPERSEDED (2026-03-20)**: The observations below are real but the "ESC deceleration" conclusion is wrong. 0x312 is a multiplexed frame: B0=[7:4] Gray-code 4-state counter, [3:0]=channel ID (6–12). B4-B5 is `speed_inv` (inversely proportional to vehicle speed at high speeds; saturates at 3199 at low/moderate speeds and during TC intervention). B6-B7 is `speed_fwd` (proportional to vehicle speed above a floor of 800; clamped to 800 during TC). The "discrete states" when stationary and the "analog sweep" during driving both reflect this speed-dependent clamping behaviour, not deceleration. See `notes/traction-control-analysis.md` (0x312 Structure Decoded section, 2026-03-20) for the authoritative decode.

### Stationary behavior (pressingthrottlethenbrake.log)

Only 4 discrete 16-bit states, always following the same sequence:

| State | B4 | B5 | 16-bit | Context |
|-------|----|----|--------|---------|
| Idle | 0x0C | 0x7F | 3199 | No brake applied |
| Transitional (press) | 0x0B | 0x2E | 2862 | Brief, during brake onset |
| Active | 0x08 | 0x47 | 2119 | Sustained brake hold |
| Transitional (release) | 0x0B | 0xC3 | 3011 | Brief, during brake release |

### Driving behavior (codadriveslowturnonwithdefroster2.log)

During actual driving, 0x312 B5 becomes **fully analog** with 100+ unique values per braking event. The harder and longer the brake application, the wider the value sweep. Light taps produce zero or few transitions.

| Brake event | Duration | B45 transitions | Unique states | Character |
|-------------|----------|-----------------|---------------|-----------|
| Event 1 (2.4s) | Hard stop | 4 | 4 | Discrete (like stationary) |
| Event 9 (3.5s) | Moderate decel | 271 | 150+ | Full analog sweep |
| Event 13 (54.5s) | Long gentle | 27 | 20 | Moderate variation |
| Event 22 (3.7s) | Sharp decel | 61 | 36 | Analog |
| Events 24-28 | Parking taps | 0 each | 1 | No response (low speed) |

~~**Conclusion**: 0x312 B4-B5 is an ESC deceleration measurement.~~ **SUPERSEDED**: see note above. The 4 discrete states when stationary (3199/2862/2119/3011) are the clamped floor/ceiling values of `speed_inv` at zero vehicle speed. The "analog" behaviour during driving reflects actual speed variation in the signal. This is NOT a deceleration signal. Authoritative decode: `notes/traction-control-analysis.md`.

### Timing (consistent across all logs)

| Log | Switch ON | Pressure onset | 0x312 first | Switch-to-Pressure | Switch-to-0x312 |
|-----|-----------|---------------|-------------|-------------------|-----------------|
| pressingthrottlethenbrake | 6.608s | 6.652s | 6.709s | +44ms | +101ms |
| driverinputpart4 | 525.792s | 525.830s | 525.872s | +38ms | +80ms |

0x312 consistently LAGS both brake switch and brake pressure — it is a downstream measurement, not a pedal input.

---

## 0x1C0 (MCM) — Regen Response Confirmed During Driving

When stationary: no response to braking (motor is already at zero speed/torque).

When driving, 0x1C0 shows clear regen braking response:

| Byte | Before brake | During brake | Shift | Interpretation |
|------|-------------|-------------|-------|---------------|
| B0 | ~97 (0x61) | ~153 (0x99) | +55 | Motor speed/torque change |
| B4 | ~148 (0x94) | ~138 (0x8A) | -10 | Secondary motor signal |
| B6 | ~155 (0x9B) | ~19 (0x13) | -136 | Dramatic drop — likely motor torque |

B6 drops from ~155 to ~19 during braking — consistent with drive torque dropping to near-zero or going negative (regen). This is the MCM's RESPONSE to a regen command from the DLCM, not the input signal.

---

## 0x315 B5 — Battery Voltage (NEW decode)

| Parameter | Value |
|-----------|-------|
| Bus | D CAN (rebroadcast to B CAN) |
| Message ID | 0x315 |
| Byte | B5 |
| Width | 8-bit unsigned |
| Scale | 0.1 |
| Range | 0x8A-0x8B = 13.8-13.9V |
| Confidence | **MEDIUM** |

Matches VICD 0.1 scale for this byte. The DLCM cluster contains `Batt_Volt` (NumFloat64) — this is the 12V auxiliary battery voltage. Value is consistent with DCDC 14V output (~13.8-14.5V when active).

Cross-validated: constant 0x8A/0x8B across all logs, no variation with brake or throttle input. Only varies with DCDC output state.

---

## Where is BrakeCount?

The LabVIEW `BrakeCount` signal exists in the DLCM and FCM_1 global data clusters (not mapped to a specific CAN ID). The DLCM_Recvd VI dispatches on 6 CAN IDs: 0x1C0, 0x212, 0x241, 0x278, 0x315, 0x418. All 6 have been characterized:

| ID | What it carries | BrakeCount? |
|----|----------------|-------------|
| 0x1C0 | MCM motor signals (speed, torque, temps) | No |
| 0x212 | EPS sub-frames + brake switch bit | No |
| 0x241 | Temperatures (signed bytes, 1 Hz) | No |
| 0x278 | HV/Drive Ready status | No |
| 0x315 | Brake switch (B0.bit0), Batt_Volt (B5), B1/B3 = zero | No |
| 0x418 | PRND gear selector | No |

None of the DLCM_Recvd CAN IDs carry an analog brake measurement. Three possible explanations:

1. **BrakeCount = ESC brake pressure (0x208 B2-B3) relabeled.** The BS_208h cluster (containing `BrakePressure`) is in GlobalData but NOT in the DLCM_Recvd VI dispatch. The DLCM accesses it via LabVIEW global variable sharing, and the LabVIEW app stores it in both the BS_208h cluster and the DLCM cluster under different names. This is the most likely explanation.

2. **BrakeCount is a local DLCM analog input** — a pedal position potentiometer wired directly to the DLCM's ADC, never broadcast on CAN. Like the throttle pedal sensor (which the DLCM reads locally and broadcasts as 0x210 B2), the brake pedal travel sensor may be a hardwired input.

3. **BrakeCount is on Motor CAN** — the private DLCM-MCM sub-bus that is not OBD-accessible.

### Regen braking architecture (inferred)

The 44ms "free stroke" gap between brake switch activation and pressure onset is too short for proportional regen modulation based on pedal travel. The Coda likely uses a simpler regen strategy:

1. **Brake switch ON** (0x315 B0.bit0) → DLCM applies regen torque (fixed or speed-dependent)
2. **Brake pressure builds** (0x208 B2-B3) → DLCM blends regen with friction braking
3. **Brake switch OFF** → regen disengaged

This is consistent with many production EVs that use a binary brake switch for regen engagement rather than a proportional pedal travel sensor. The MCM response (0x1C0 B6 dropping from ~155 to ~19) confirms regen torque is applied during braking.

---

## Verification Against Plan Criteria

| Criterion | Result |
|-----------|--------|
| Analog signal with >10 unique values during brake | **FAIL** — no candidate found |
| Timing should lead or match brake pressure onset | **N/A** — no candidate |
| Present in driving logs at every braking event | **N/A** — no candidate |
| Zero/idle during throttle portion | **N/A** — no candidate |
| Systematic scan of ALL D CAN + B CAN bytes | **Done** — comprehensive |

---

## Data Artifacts (Part 3)

All in `artifacts/` — see `artifacts/README.md` for full inventory.

| File | Contents |
|------|----------|
| `artifacts/brake_travel_analysis.py` | Step 1: candidate timeseries extraction + systematic mean-shift scan |
| `artifacts/brake_travel_step2.py` | Step 2: 0x1C0 MCM detail, B CAN scan, precise timing, 0x312 characterization |
| `artifacts/brake_travel_xval.py` | Steps 3-4: cross-validation against driverinputpart4 and driving log |
| `artifacts/brake_window_0x312.csv` | 0x312 full dump, t=5-9s (400 frames) |
| `artifacts/brake_window_0x241.csv` | 0x241 full dump, t=5-9s (4 frames) |
| `artifacts/brake_window_0x315.csv` | 0x315 full dump, t=5-9s (200 frames) |
| `artifacts/brake_window_0x1C0.csv` | 0x1C0 full dump, t=5-9s (400 frames) |
| `artifacts/brake_window_0x208.csv` | 0x208 full dump, t=5-9s (400 frames) |

---

## Part 3 Signal Confidence Summary

| Signal | Bus | ID | Byte(s) | Encoding | Confidence |
|--------|-----|-----|---------|----------|------------|
| Analog brake pedal travel | — | — | — | — | **NOT ON CAN** |
| 0x312 B4-B5 (ESC decel/ABS) | D CAN only | 0x312 | B4-B5 | Status when stationary; analog during driving | MEDIUM |
| 0x315 B5 (Batt_Volt) | D+B CAN | 0x315 | B5 | uint8 x 0.1 = voltage (V) | MEDIUM |
| BrakeCount (LabVIEW) | — | — | — | Likely = brake pressure (0x208) or local ADC input | Hypothesis |

---

## Next Steps (Part 3)

- [ ] Decode 0x312 B4-B5 scale/encoding during driving — how does it relate to actual deceleration?
- [ ] Characterize 0x312 remaining bytes (B0-B3, B6-B7) — B0 appears to be a 50 Hz alternating pattern (0x27/0x47)
- [ ] Verify 0x315 B5 = Batt_Volt by correlating with DCDC 14VMonitor (0x1D5 B3) in a driving log
- [ ] Decode 0x1C0 byte assignments (B0=speed?, B2=temp?, B4=current?, B6=torque?) using driving log dynamics
- [ ] Investigate whether regen torque magnitude is visible on CAN during driving brakes
