# Vtrux HVAC Investigation

**Started:** 2026-03-04
**Logs:** vtruxanotherevaplogpart1/2/3.log (anotherevaplog series, highway drive Mar 4 2026)

---

## Context

Highway drive with HVAC-relevant events:
- Part 2 end: engine running, heater on -> stopped at quarry -> heater off (~2 min) -> heater on again
- Part 3: drove out of quarry EV-only with heater running; then generator on for hill; generator on/off cycle

**No OBD scanner active.** Coolant temp must come from the GM broadcast messages on the Vehicle bus.
**Key question:** When engine stops (still warm), does VCM switch to PTC heat immediately or after coolant cools below a threshold?

---

## Phase 1 -- GM-Bus HVAC Signal Catalog

*(Completed: 2026-03-04)*

### 1A. Survey Results

**Bus identification** (anchor ID method — bus numbers are not stable across sessions):

| Part | Bus 1 | Bus 2 | Bus 3 |
|------|-------|-------|-------|
| Part 1 | Vehicle (90 IDs) | OBD (77 IDs) | PT (94 IDs) |
| Part 2 | Vehicle (90 IDs) | OBD (77 IDs) | PT (93 IDs) |
| Part 3 | OBD (77 IDs) | Vehicle (90 IDs) | PT (94 IDs) |

Bus numbers swapped between sessions (dongle insertion order). PT bus identified by extended-frame IDs and unique content.

**Total durations:** Part 1 = 364s, Part 2 = 2011s, Part 3 = 521s.

**0x4C1 B2 (ECM_EngineCoolantTemp, EPRI-attributed) range across all parts:**

| Part | B2 raw range | degC range (raw - 40) |
|------|-------------|----------------------|
| Part 1 | 55-103 | 15-63 degC (cold start -> warm) |
| Part 2 | 97-140 | 57-100 degC (warm through highway) |
| Part 3 | 119-140 | 79-100 degC (hot; engine recently off) |

### 1B. Unknown IDs on GM Buses

Comparing the Vehicle bus (90 IDs per Part 2 survey) against the set of GM IDs known from the EPRI decompile and prior reference correlation (0x0AA, 0x0BE, 0x0C1, 0x0C5, 0x0C7, 0x0C9, 0x0D0, 0x0D1, 0x0D3, 0x0F1, 0x0F9, 0x1A1, 0x1E5, 0x1F1, 0x3F1, 0x3F9, 0x4C1, 0x4D1, etc.), there are approximately 40 IDs on the Vehicle bus that were not previously catalogued. These are candidates for Body/HVAC module messages.

Notable unknown Vehicle IDs in HVAC-relevant ranges:
- **0x210, 0x214** (20 Hz) — uncatalogued; B0 range 0x00-0x06
- **0x232, 0x287** (49-80 Hz) — uncatalogued
- **0x2C3** (20 Hz) — B0: 0x00-0x0F; B2-B3 static (0x06, 0xA0); B6 varies 0x29-0xD1
- **0x3C1, 0x3C9** (10 Hz) — B0 fixed 0x07; B2 varies 0x14-0xF7 — wide range, could be temperature or blower
- **0x3D1, 0x3D3** (10 Hz) — B2 varies on 0x3D1; B1 varies on 0x3D3
- **0x3FB, 0x3FC** (4 Hz) — same frequency as confirmed engine messages (0x3F1, 0x3F9) — adjacent; likely engine-related

**No Phase 1D (unknown ID HVAC scan) was performed.** The unknown IDs above are candidates for further investigation if Phase 2 does not identify the heater fan event. The most promising for HVAC behavior are **0x3C1 B2** (wide range, 10 Hz) and **0x2C3 B6** (wide range).

### 1C. Confirmed HVAC-Adjacent Signals

**0x4C1 B2 -- ECM_EngineCoolantTemp (EPRI-attributed): CONFIRMED**
- EPRI DBC encoding: `23|8@0+`, 1 degC/count, offset -40 degC. Raw 0 = -40 degC.
- Validation: warm-idle/highway values of 57-100 degC are physically plausible. Part 3 start (85 degC) consistent with engine that had just shut off on a hot highway drive.
- Signal is **faithfully bridged** — ECM broadcasts it continuously regardless of engine run state.
- Artifacts: `notes/artifacts/analyze_4C1_part2.txt`, `notes/artifacts/coolant_temp_part2.csv`, `notes/artifacts/coolant_temp_part3.csv`

**0x4D1 B0 -- A/C-off indicator: B0 = 0x00 constant throughout all parts**
- AC is off (B0 = 0) for the entire capture. Expected — this is a heater investigation.
- B2 (range 0-115) and B5 (range 200-228) are unidentified varying signals within 0x4D1.
- Artifact: `notes/artifacts/analyze_4D1_part2.txt`

**0x3F1 B0 -- cooling-fan adjustment candidate: B0 = 0x00 constant throughout Part 2**
- No active cooling fan speed adjustment seen. The byte does not respond to HVAC events.

**Generator flag (0x600 B0):**
- 0x34 = generator active, 0x24 = inactive.
- Part 2 final generator shutoff: **t = 1668.9s** (user pulled into quarry gate and shut off generator).
- Artifact: `notes/artifacts/gen_flag_part2.csv`, `notes/artifacts/gen_flag_part3.csv`

### 1D. Unknown ID HVAC Scan

Ran analyze_id on top candidate IDs from 1B. Results:

**0x3C1 (20 Hz, bridged both GM buses):**
- B0=0x07, B1=0x65 constant. B2: only **5 discrete states**, min=20, max=247, mean=203.3 -- mode/status register, not a continuous sensor.
- B3-B7: almost always zero with tiny-count non-zero events.
- Not HVAC blower speed. Ruled out.

**0x2C3 (39.5 Hz):**
- Bus 1 and Bus 2 send **different content simultaneously** -- two independent modules each broadcasting 0x2C3 on their respective buses (not a normal bridge).
- B1 (0-255) and B6 (41-209) continuously varying, high entropy. B3 (6-160) varies too.
- Not consistent with HVAC. Not ruled in.

**0x3D1 (20 Hz):**
- Bus 1 and Bus 2 again send different B1 values, confirming two independent modules.
- B5 (0-255) and B1 (247 unique values) look like continuous analog sensors. Not HVAC.

**0x3D3 (20 Hz):**
- B4-B5 cycles through 4 fixed states at exactly 0.251 toggle rate (periodic mechanical pattern).
- B1 continuously varies (0-201). B6 slowly varies (52-60). Looks like ABS/wheel speed. Not HVAC.

**No GM bus message identified as a clear HVAC module message (blower speed, setpoint, or mode).**
Either the HVAC module messages are not on the captured GM buses, or they are static during this drive.

**0x451 B4 -- cabin heater blower speed: CONFIRMED empirically**

0x451 is present on **both GM buses** in all parts at 39 Hz. It is **bridged** (identical content on both buses). Absent from PT bus (Bus 3). B4 is the only varying byte; all other bytes are 0x00 constant.

The blower-speed role of B4 was established empirically (thermal validation below), not from any spec signal table. A scan of fan-related IDs (0x3F1/0x3F9/0x451) did not yield a usable fan signal on the GM bus beyond this empirical B4 finding.

| Part | B4 raw range | Unique raw values |
|------|-------------|-------------------|
| Part 2 | 0-84 | 9 |
| Part 3 | 0-85 | (not extracted) |
| Part 4 | 0-85 | 5 |

Max observed ~33% of B4 full scale, consistent with driver setting fan to a partial step (not full speed).

**Validation:** Part 2 zoomed plot (`notes/plots/blower_plot.png`) shows the coolant temperature clearly responding to blower state:
- At t~1833s: blower drops to 0 -> coolant temp inflects from declining to rising (heat soak)
- At t~1985s: blower resumes -> coolant temp rapidly resumes decline

The thermal signature is unambiguous -- this is confirmed as the cabin heater blower speed signal (0x451 B4), validated thermally.

Artifacts: `notes/artifacts/blower_part2.csv`, `notes/artifacts/blower_part4.csv`, `notes/artifacts/blower_plot.py`, `notes/plots/blower_plot.png`

**DC-DC (0x18FFD6B3) B2-B3 -- investigated, not usable for HVAC event detection:**
- 12-bit LE value (B2 = 8-bit LSB, B3 = lower nibble MSB), range 0-4095.
- Extracted timeseries (notes/artifacts/dcdc_lv_current_part2.csv) and plotted end of Part 2 (t >= 1668.9s). See notes/artifacts/dcdc_current_part2_plot.png.
- Signal is extremely noisy -- alternating +/-150-200 counts at every 0.1s sample period (likely DC-DC switching ripple aliased at 10 Hz). No clear HVAC system on/off edge is visible above the noise.
- **Conclusion: no usable HVAC event signal in DC-DC B2-B3.** HVAC system on/off edges will need to be detected via HV battery current (0x598 B0-B1 LE) -- the electric compressor and PTC heater are HV loads and will show there -- or via coolant dT/dt inflection in 0x4C1 B2.
- Artifacts: notes/artifacts/analyze_BELDCDC_part2.txt, notes/artifacts/analyze_3C1_part2.txt,
  notes/artifacts/analyze_2C3_part2.txt, notes/artifacts/analyze_3D1_part2.txt,
  notes/artifacts/dcdc_lv_current_part2.csv, notes/artifacts/dcdc_current_plot.py,
  notes/artifacts/dcdc_current_part2_plot.png

---

## Phase 2 -- Engine Coolant Temp vs. Heater Fan Events (Part 2)

*(Completed: 2026-03-05)*

### Event Timestamps

Identified via HV battery current (0x598 B0-B1 LE) and coolant temp (0x4C1 B2) timeseries plotted together over t=1668.9s to end of Part 2. See notes/plots/hvac_phase2_plot.png.

| Timestamp | Event |
|-----------|-------|
| t=1668.9s | Generator final shutoff (confirmed from 0x600 B0) |
| t=1669-1833s | EV driving on quarry road, HVAC on throughout |
| t=1833s | Truck stops AND HVAC turned off -- 0x451 B4 drops to 0; coolant inflects from declining to rising |
| t=1833-1985s | HVAC off -- heat soak, coolant rising; 0x451 B4 = 0 throughout |
| t=1985s | HVAC turned back on -- 0x451 B4 resumes; rapid coolant descent begins |
| t=1985-2010s | HVAC on, log ends at t~2010s |

**HV battery current observation:** Zero HV current throughout the entire post-gen-shutoff window. No HV compressor or PTC active -- the HVAC system in this log is purely coolant-loop cabin heating (engine residual heat + 12V blower fan). HVAC on/off has no HV electrical signature here.

### dT/dt by Window

| Window | Duration | Coolant | dT/dt |
|--------|----------|---------|-------|
| HVAC on, EV driving (t=1669-1833s) | 164s | 95 -> 89 degC | -2.2 degC/min |
| HVAC off, heat soak (t=1833-1985s) | 152s | 89 -> 97 degC | +3.2 degC/min |
| HVAC back on (t=1985-2010s) | 26s | 97 -> 88 degC | -21 degC/min |

**Heater thermal load on coolant circuit: ~5.4 degC/min differential** (heater-on driving vs heater-off soak).

**Interpretation:** The fact that coolant temperature responds directly and cleanly to blower on/off confirms that 0x4C1 B2 (ECM_EngineCoolantTemp) represents the temperature of coolant being circulated to the cabin heater core — not a dedicated engine block sensor or ECM thermal model. The signal reflects heating demand drawn from the coolant loop. It is not a reliable standalone indicator of engine thermal state when the cabin heater is active.

The -21 degC/min rate for the final window is elevated because the cabin had cooled during the ~2.5 min HVAC-off period, producing a large cabin-to-coolant delta-T. The log ends before the rate settles to steady state.

**Heat soak rate (+3.2 degC/min)** quantifies how fast residual engine heat migrates back into the coolant with no fan load -- useful reference baseline for Part 3 PTC analysis.

### Artifacts

- notes/artifacts/batt_current_le_part2.csv -- HV battery current, 0x598 B0-B1 LE
- notes/artifacts/coolant_temp_part2.csv -- coolant temp, 0x4C1 B2
- notes/artifacts/hvac_phase2_plot.py -- plot script
- notes/plots/hvac_phase2_plot.png -- two-panel plot (HV current + coolant temp)
- notes/artifacts/hvac_dtdt_analysis.py -- dT/dt computation script

---

## Phase 3 -- PTC Heater Current and Switch-Over Behavior (Part 3 + Part 4)

*(Completed: 2026-04-11)*

### Logs

- Part 3: `vtruxanotherevaplogpart3.log` (521s, engine warm, EV+gen, heater on)
- Part 4: `vtruxanotherevaplogpart4-batteryonly.log` (1826s, battery-only ~2h later, heater on)

### Findings So Far

**Part 3 coolant:** 79-100°C arc. Rises sharply during generator-on periods (t~150-250s, t~350-480s). Falls when generator off. Consistent with warm engine + shared coolant loop.

**Part 4 coolant:** Actual behavior (confirmed from raw timeseries 2026-03-05): starts at 39°C, rises to 68°C by t~495s, declines to ~44°C by t~1025s, rises again to 68°C at t~1301s, then declines to 38°C by end. Two full thermal cycles over 1826s. **Correction: earlier note ("starts ~68°C, monotonically declines") was wrong.** The oscillations are driven by temperature setpoint adjustments (driver reported the truck poorly regulates cabin temp on PTC -- oscillates between too hot and too cold; inflection points correspond to setpoint dial changes, not blower speed changes -- blower was largely constant throughout). Coolant responding to temperature setpoint changes confirms heat is flowing through the engine coolant loop in this session. A temperature setpoint CAN signal has not yet been identified.

**No HV PTC signature found:** HV battery current in both parts is dominated by motor driving noise. Any PTC load (~20-30A HV) would be buried.

**0x4C1 B4 (ECM_OutsideAirTemp, EPRI-attributed):** Investigated as potential independent temperature. EPRI DBC encodes scale=0.5, offset=-40. Correct decoded range: Part 3 = 9-12°C, Part 4 = 8-18°C. In Part 4 it starts at raw=116 (18°C), decays via staircase to raw=97 (8.5°C) by t~511s, then holds flat for remainder. This is the ECM's outside air temperature low-pass filter converging from an inflated prior toward actual ambient -- purely an estimation artifact, not an independent sensor. (Earlier notes used scale=1.0 in error, producing spurious 57-76°C values -- those are now corrected.)

### Cold vs Warm Engine PTC Routing -- Key Finding (2026-03-05)

Cross-log comparison of `vtruxevapdrivelog4.log` (cold engine) vs `vtruxanotherevaplogpart4-batteryonly.log` (warm engine, PTC-only driving):

| Condition | Log | Coolant at start | Coolant behavior | Blower |
|-----------|-----|-----------------|-----------------|--------|
| Cold engine, EV-only (432s before gen-on) | evap4 | 17°C | Flat throughout -- no rise | Running 100% of pre-engine frames, 36-43% |
| Warm engine (~39°C), EV-only | Part 4 | 39°C | Rises/falls with setpoint adjustments (39->68->44->68->38°C) | Largely constant; setpoint dial changes drive coolant cycles |

**Finding:** Blower is running in the cold-engine session with coolant completely flat; in the warm-engine session coolant responds directly to heat demand. If PTC is the heat source in the cold-engine session, it is not routing heat through the engine coolant sensor. HV current in evap4 has not been confirmed as a PTC load signature -- driving discharge dominates and no clean PTC step has been isolated.

**Hypothesis:** The Vtrux has at least two small pumps for selecting heat source. When engine coolant is cold (~17°C), the system may route PTC heat through a path that does not circulate the engine coolant sensor -- possibly a dedicated air-side heater or a short PTC-only loop bypassing the block. When coolant is warm (~39°C+), heat routes through the heater core shared with the engine coolant loop. A passive thermostat or VCM-controlled valve/pump switchover is the likely mechanism. Switchover threshold unknown.

**Engine Oil Temperature candidate (0x4D1 B1): dead in both logs** -- raw=0x00 constant, decodes to -40°C. Not implemented on Vtrux.

Artifacts: `ptc_check_evap4.py/png`, `ptc_cold_vs_warm_comparison.py/png`, `blower_evap4.csv`, `coolant_temp_evap4.csv`, `batt_current_evap4.csv`, `gen_rpm_evap4.csv`

**Transmission Oil Temperature candidate (0x4C9 B1):** raw=0x41=65 constant throughout Part 2. Frozen value, not a real sensor.

### Temperature Signal Offset Confirmation (resolved 2026-04-11)

All 0x4C1 temperature signal offsets are confirmed from the EPRI DBC (`epri-obd-bus.dbc`, message 0x4C1 = ECM engine temperatures):

| Signal | Encoding | Notes |
|--------|-------------|-------|
| ECM_EngineCoolantTemp (B2) | `(1.0, -40)` | Matches what was used throughout |
| ECM_EngineAirIntakeTemp (B3) | `(1.0, -40)` | Not actively used in this investigation |
| ECM_OutsideAirTemp (B4) | **(0.5, -40)** | Scale was wrong in earlier scripts (used 1.0) -- corrected in phase3_plot.py |

The Engine Oil Temperature candidate (0x4D1 B1 = 0x00 constant, decodes to -40°C with offset) is confirmed not implemented on Vtrux. The -40°C output at raw=0 is consistent with a "not implemented" sentinel encoded as raw zero.

### Artifacts

- notes/artifacts/coolant_temp_part3.csv
- notes/artifacts/coolant_temp_part4.csv
- notes/artifacts/batt_current_le_part3.csv
- notes/artifacts/batt_current_le_part4.csv
- notes/artifacts/oat_powertrain_part3.csv
- notes/artifacts/oat_powertrain_part4.csv
- notes/artifacts/blower_part3.csv -- 0x451 B4 blower speed, Part 3
- notes/artifacts/blower_part4.csv -- 0x451 B4 blower speed, Part 4
- notes/artifacts/phase3_plot.py
- notes/plots/phase3_plot.png -- 4-row plot: HV current / coolant / OAT est / blower
- notes/artifacts/survey_anotherevap_part4.txt

---

## Phase 4 -- AC-Compressor Extended IDs (EAC_STATUS1/2)

*(Not yet started)*

### Background

The EPRI decompile of the Via Motors iPhone app (`notes/original-datalogging-investigation.md`)
identified two extended-frame CAN IDs on the PT bus attributed to the Sanden MI-EV36-BNKx
HV electric AC compressor:

| CAN ID | EPRI name | Signals | Units |
|--------|-----------|---------|-------|
| `0x0868A047` | `EAC_STATUS1` | `EAC_Elec_Curr` (compressor current), `EAC_Elec_Pwr` (compressor power) | A (%.2f), W (%d) |
| `0x0870A047` | `EAC_STATUS2` | `EAC_CompHVInput` (HV input voltage) | VDC (%d) |

Both IDs drop ~33s after BMS LV disconnect (along with the generator inverter cluster),
confirming they ARE real extended-frame CAN IDs present in BUSMASTER logs, not artifacts. Both share source address **SA=0x47** (J1939 format confirmed by
SA field in ID). The J1939 priority field is 0 (non-standard; typical J1939 uses priority 6),
which is why these don't match the familiar `0x18xxxxxx` pattern.

### The Encoding Problem

The EPRI decompile byte positions are expressed as `pbVar15[N]` where N=2 corresponds to CAN
payload byte 0 (the GoPoint BT1 dongle prepends a 2-byte header before the CAN payload in its
internal packet format). The plist sub-indices (`.2`, `.3`) are GoPoint-packet byte offsets, not
raw CAN payload byte offsets.

From the plist:
- `0x0868A047.2` = `EAC_Elec_Curr` → GoPoint byte 2 → **CAN payload B0**
- `0x0868A047.3` = `EAC_Elec_Pwr` → GoPoint byte 3 → **CAN payload B1**
- `0x0870A047` (no sub-index) → byte position within the frame not yet determined from decompile

The Ghidra decompile for these specific IDs was listed in the ID table but the detailed byte
decode (equivalent to the 0x0410/0x0430/0x0482 sections) was not completed. Scales and exact
bit layouts are unknown.

From the binary format strings, the signal types are:
- `EAC_Elec_Curr`: `%.2f` format → floating-point, likely a scaled integer
- `EAC_Elec_Pwr`: `%d` format → integer (watts direct?)
- `EAC_CompHVInput`: `%d` format → integer (volts direct?)

The compressor status and fault enum structures were noted as present (4-entry status, 8-entry
fault) but not decoded from the binary.

### Findings (2026-03-28) — oghighwaydrive.log

Both IDs present at 10 Hz in `oghighwaydrive.log` (PT-bus-only, ~35 min summer highway drive).
Analysis script: `notes/artifacts/eac_compressor_decode.py`.

**0x0870A047 (EAC_STATUS2, EAC_CompHVInput) — DLC=4:**

| Byte | Range | Mean | Interpretation |
|------|-------|------|---------------|
| B0 | 0x00/0x07 | ~0 | Status: 0x07 at startup (5 frames), 0x00 = normal |
| B1 | 0–80 | 72.7 | Likely temperature sensor 1 (degC, slowly rises 59→80 over 35 min) |
| B2 | 0–102 | 94.6 | **HV input voltage, 4 V/count** — CONFIRMED (see below) |
| B3 | 0–81 | 73.6 | Likely temperature sensor 2 (degC, similar rise to B1) |

**B2 × 4 = EAC_CompHVInput cross-validated** against `0x0482 GENE_HighPwr_Volt` (11-bit LE,
1 V/count) across t=50–200s: agreement within ±4V (one count) at every sample point. Example:
0x0482=384V, B2=96, 96×4=384V. The match is consistent throughout. **Confirmed: B2 × 4 V.**

**Extended confirmation (2026-03-28, Phase 6) — three independent contexts:**

| Log | Compressor state | B2 range | 0x0482 mean err | Notes |
|-----|-----------------|----------|----------------|-------|
| `oghighwaydrive.log` | Running (summer) | 93–102 | <±4V | Original confirmation, t=50–200s |
| `vtruxanotherevaplogpart2.log` | Off (entire log) | 0–102, mean 95.2 | — (0x0482 not on PT bus) | 20,073 frames at 10.0 Hz; 5 non-zero 0x0868A047 frames only |
| `vtruxcurrentlimitingtest.log` | Off (cooler day) | varies 87–100 | **mean 1.3V**, max 33V (1 sample) | Full 30-min drive, 17,955 paired samples, voltage range 348–400V. Single 33V outlier at t=1795.348s is the **first frame of an end-of-drive HV bus shutdown** (contactor open at ~t=1795.35s). 0x0482 shows 374V→339→222→145→67V over ~40ms as caps bleed. All other sources agree at 372–375V in pre-collapse window: bcm_vbus_pos (0x0440)=374.2V at −6ms, bcm_vbat (0x0410)=374.5V at +1ms (BMS cycle stale), TRAC 0x0462=375V at −7ms, DCDC=374.1V at −43ms. Sanden B2=93 (372V) at +0.1ms — filtered measurement one cycle behind. bcm_vbus_neg=0.5V (expected; negative rail vs chassis). 17,954/17,955 samples within ±5V. |
| `charge_M0_T0.log` | Off (charging) | 0 then 95–96 | — | B2=0 before HV contactors close (t<50s), 380–384V thereafter |

**0x0870A047 is a continuous HV bus monitor**, not a compressor-activity signal. It broadcasts
at exactly 10 Hz regardless of whether the compressor is running. The Sanden ECU (SA=0x47)
sends both 0x0870A047 and 0x0868A047 as a synchronized pair — frame counts are always identical.

**B2=0 at startup** (charge log t=24.4s): the zero row is a real "HV contactors not yet closed"
state, not a sensor floor. Confirms B2=0 is meaningful (no HV bus present), not just noise.

B1 and B3 slowly rising together (59→80, 63→80) over 35 minutes of compressor operation
strongly suggests two internal temperature sensors. Values in degC direct (no scale). B3
starts ~4°C higher than B1, suggesting different measurement points (e.g. inverter vs motor winding).
In the climit and charge logs (compressor off), both sensors start warmer and drift slightly
downward toward ambient — consistent with a Sanden unit that was recently warm and is cooling.

### EAC HV reading lags BMS vbus_pos during fast transients (2026-05-20)

The `eac_hv_input` (B2 × 4 V) is an accurate steady-state HV bus monitor (±4 V vs 0x0482, above)
but it is **not** suitable for sub-100 ms timing during fast transients (precharge, contactor
open/shutdown). Two compounding factors:

1. **10 Hz broadcast** — only one sample per ~100 ms.
2. **Internal filtering** — the Sanden ECU's reported value is ~one cycle behind the actual bus
   (already noted in the climit shutdown event above: "Sanden B2=93 (372V) at +0.1ms — filtered
   measurement one cycle behind").

Net effect: during a rapidly changing bus, EAC samples report the bus state from up to ~100 ms
earlier than the BMS's own `bcm_vbus_pos` (0x0440, 12-bit Motorola, 0.25 V/count, sampled at BMS
frame rate). This can make EAC appear to **rise after** a shutdown — an artifact of the lag
reporting the still-rising pre-shutdown bus, not a real post-shutdown rise.

**Quantitative example — failed precharge, `debuglog_M4_T20.log`** (times relative to CLOSE_MAINR
entry; EAC vs BMS `bcm_vbus_pos` side-by-side):

| Time | mainc_stat | EAC (B2×4) | BMS vbus_pos |
|------|-----------|-----------|--------------|
| +207 ms | CLOSE_MAINN | 164 V | 121.5 V |
| +263 ms | CLOSE_MAINN | 164 V | 341 V |
| +307 ms | ALL_OPEN_SHUTDOWN | 336 V | 367 V |
| +388 ms | ALL_OPEN_SHUTDOWN | 336 V | 330 V |
| +407 ms | ALL_OPEN_SHUTDOWN | **368 V** | 340 V |
| +507 ms | ALL_OPEN_SHUTDOWN | 364 V | 339 V |

At the shutdown instant (+307 ms) the BMS already read 367 V while EAC still read 336 V; EAC's
matching peak (368 V) did not appear until ~100 ms later (+407 ms), after which EAC began its true
monotonic decay (368 → 364 → 360 ...). The BMS reading peaked and began decaying ~100 ms earlier.

**Guidance:** for timing-sensitive transient analysis, use BMS `bcm_vbus_pos` (0x0440), not EAC.
EAC is fine for steady-state HV monitoring. Promoted to overview as a behavior:
`vtrux.md` → Documented Behavior → HV Bus Voltage Measurement Sources. Artifact:
`notes/artifacts/keith_precharge_profile.py` / `keith_precharge_profile_output.txt`.

**0x0868A047 (EAC_STATUS1) — DLC=6:**

| Byte | Range | Mean | Interpretation |
|------|-------|------|---------------|
| B0 | 0x00/0x84/0x94 | ~0 | Status/flags at startup only; 0x00 = normal running |
| B1 | 0–27 | 13.0 | Unknown — active signal, goes to 0 with compressor off; ≈2× B4 |
| B2 | 0–10 | 5.7 | **EAC_Elec_Curr candidate** (best remaining candidate by elimination) |
| B3 | 0–255 | 125.4 | **CONFIRMED checksum/counter** — NOT EAC_Elec_Pwr (see P=V×I below) |
| B4 | 0–14 | 7.1 | Unknown — correlated with B1 (≈B1/2); goes to 0 with compressor off |
| B5 | 0 | 0 | Always zero |

B1, B2, B4 go to zero simultaneously during compressor off-cycles. B3 also goes to zero
when off (consistent with a checksum of an all-zero payload).

**P=V×I cross-check result (2026-03-28, Phase 9 — oghighwaydrive.log, 17,626 active frames):**

B3 was tested as EAC_Elec_Pwr by computing whether B3 tracks B2×V_hv or B1×V_hv:
- **r(B3, B2×V_hv) = −0.155** — essentially zero. No correlation with computed power.
- **CV of ratio B3/(B2×V_hv) = 0.626** — ratio varies ±63% around mean; a true P=V×I
  signal would give CV near 0.
- **B3 monotonicity**: 8225 increases vs 7620 decreases across active frames — near-equal
  up/down transitions, the statistical signature of a counter or checksum, not a physical measurement.
- Sample: at identical compressor load (B2=7, V=384V), B3 reads 203, 248, 180, 240, 225, 180,
  240 across consecutive 30-second windows — jumps with no relationship to operating state.

**Conclusion: B3 = checksum or rolling counter. It is NOT EAC_Elec_Pwr.**

The EPRI plist index `.3` → B3 interpretation for EAC_Elec_Pwr is therefore wrong. Either the
GoPoint index notation means something different, or the EPRI app was not successfully reading
this signal. The actual power signal location is unknown — it is not any of the remaining bytes
at face value. B1 (range 0–27) and B4 (≈B1/2) are the only other active bytes; neither
correlates with V×I (r=0.055 for B1×V_hv vs B3).

**GoPoint offset note:** The earlier ambiguity between `.N`=raw-CAN-byte vs `.N`=GoPoint-packet-byte
is now moot for the power signal — B3 is ruled out as power regardless of interpretation.

**GM A/C command note:** The truck no longer has the original belt-driven A/C compressor.
The GM ECM's A/C command signal for the OEM unit was not seen active in the available multi-bus logs.
It is unresolved whether the VCM still asserts an A/C request when cabin cooling is requested and
translates it into commands to the Sanden HV compressor, or whether the A/C request path is
entirely separate. `oghighwaydrive.log` is PT-bus-only and cannot be used for this.

**Partial result (2026-03-28) — vtruxanotherevaplogpart2.log (multi-bus):**
- The GM A/C command bit was set for only ~0.6s (12 frames) at t=1002.7–1003.3s — a brief transient,
  probably triggered by defrost/dehumidify momentarily engaging.
- `0x0868A047` was **all zeros throughout the entire log** — EAC compressor never ran in this
  session. This was likely a cooler-weather drive where A/C was not needed.
- **Cannot determine VCM translation behavior** from this log. The compressor being entirely off
  means no correlation is possible. Need a log where the Sanden compressor was actually running
  AND multi-bus capture was active simultaneously.
- Summer logs (e.g. `oghighwaydrive.log`) show the compressor running, but that's PT-bus-only.
  A future multi-bus capture on a warm day would resolve this.

### What Remains to Confirm

**RESOLVED (0x0870A047):** B2 × 4 = HV bus voltage confirmed in three independent logs and
conditions (driving with compressor on, driving with compressor off, charging). Temperature sensors
B1/B3 confirmed by behavior across conditions. B0 = startup status. No remaining open items on
this message.

**RESOLVED (B3):** B3 = checksum/rolling counter. Confirmed NOT EAC_Elec_Pwr via P=V×I
cross-check (r=−0.155, CV=0.626 on 17,626 active frames). The EPRI plist `.3`→EAC_Elec_Pwr
attribution is incorrect for this byte.

1. **EAC_Elec_Curr scale (0x0868A047 B2)** — B2 remains the best current candidate by
   elimination. Range 0–10 (mean ~6.5 in summer drive). EPRI format `%.2f` implies sub-count
   resolution, so scale is not 1 A/count — likely 0.5 or 0.1 A/count. Cannot confirm scale
   without a ground-truth power or current reference (e.g. a log with simultaneous DCDC current
   measurement while the compressor cycles on/off).

2. **EAC_Elec_Pwr location unknown** — B3 ruled out. No other byte in 0x0868A047 shows a
   smooth signal with plausible power scaling. The EPRI plist attribution may be wrong, or the
   power signal may be derived/computed from other bytes rather than broadcast directly.

3. **B1 and B4 identity** — B4 ~= B1/2 throughout. B1 range 0–27, B4 range 0–14. Neither
   correlates with V×I (r=0.055). Not RPM at obvious scales (0–27 × 100 = 2700 RPM is too low
   for a Sanden compressor; typical operating range is ~1000–8000 RPM). Could be a compressor
   speed in a non-obvious unit, torque, or duty cycle. Open.

4. **Status/fault enum bytes** — EPRI noted 4-entry status and 8-entry fault enums in
   EAC_STATUS1. B0 is the most likely location (seen {0x00, 0x84, 0x94} at startup, 0x00 during
   normal running). Full enum values not yet observed; need a log with fault events.

5. **GM A/C command translation** — need a multi-bus log from a warm day where the EAC
   compressor was actually running (B1/B2/B4 > 0) to check whether the GM ECM A/C command bit is
   simultaneously asserted. Cannot answer from current available logs.
