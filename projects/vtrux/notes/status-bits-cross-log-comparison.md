# Status Bit Cross-Log Comparison

**Date:** 2026-02-17
**Status:** ✅ VALIDATED across 6 driving logs

## Logs Analyzed

| Log File | Description | Duration | Generator Activity |
|----------|-------------|----------|-------------------|
| `../logs/generator on then off.log` | Generator startup/shutdown cycles | 64s | Backdriving + Generating |
| `../logs/movingaroundindriveway.log` | Driving back and forth | 115s | None (never started) |
| `logs/debuglog_M0_T7.log` | EV mode driving | ~50s | None (previously used) |
| `logs/debuglog_M0_T2_short.log` | Hybrid mode driving | ~50s | Generating (continuous) |
| `logs/debuglog_M0_T4.log` | Generator shutdown event | 300s | Generating → Off at t=58s |
| `logs/debuglog_M0_T0_half.log` | Startup sequence | ~50s | Backdriving + Generating |

---

## Summary Table

| Log | 0x051 Command | 0x644 Byte 6 | 0x63A Bytes 6-7 | 0x649 Byte 7 |
|-----|---------------|--------------|-----------------|--------------|
| **generator on/off** | 81% neutral<br>17% generating<br>2% backdriving | 81% 0xF0 normal<br>16% 0xE0 init<br>3% 0x90 backdrive | 73% 0x1804<br>27% 0x1AC4 | 99% 0x40 idle<br>1% pulses |
| **movingaround** | 100% neutral | 80% 0xF0 normal<br>20% 0xE0 init | **100% 0x1804** | 100% 0x40 idle |
| **T7 (EV mode)** | 100% neutral | 57% 0xF0 normal<br>43% 0xE0 init | **100% 0x1AE4** | 100% 0x40 idle |
| **T2 (hybrid)** | 100% generating | 100% 0xF0 normal | **100% 0x1AE4** | **74% 0x00 active**<br>24% 0x40 idle<br>2% 0xA0 |
| **T4 (gen shutdown)** | 81% neutral<br>19% generating | 99.9% 0xF0 normal<br>0.1% 0x90 backdrive | **100% 0x1AE4** | 84% 0x40 idle<br>15% 0x00 active<br>1% pulses |
| **T0_half (startup)** | 19% neutral<br>79% generating<br>3% backdriving | 97% 0xF0 normal<br>3% 0x90 backdrive<br>1% 0xE0 init | 21% 0x1804<br>79% 0x1AC4 | 96% 0x40 idle<br>4% 0x00 active<br><1% pulses |

---

## Disconnect Attribution

All three signals analyzed here (0x644, 0x63A, 0x649) are in the **VCM BMS relay cluster** per `can-disconnect.md`: they survive the HV battery LV connector pull (T2 = P) and only drop when the VCM B-connector is removed (T3 = A). Source is B-connector-dependent — either VCM-generated or transmitted by a module whose wake/enable runs through the B-connector. See `can-disconnect.md` T3 "PT Bus Collapse" notes.

---

## Validated Status Bit Fields

### 0x644 Byte 6 - Generator Operating Mode ✅

**Distribution across logs:**
- `0xF0`: Normal operation (57-100% depending on log)
- `0xE0`: Initialization/Shutdown (0-43%)
- `0x90`: Backdriving active (0-3%)

**Validation:**
- ✅ **movingaround**: No 0x90 (backdriving) - generator never started
- ✅ **T7 (EV)**: No 0x90 (backdriving) - generator not active
- ✅ **T2 (hybrid)**: 100% 0xF0 - engine already running, no startup needed
- ✅ **generator on/off**: All three states present, transitions match 0x051 command
- ✅ **T4 (gen shutdown)**: 0.1% 0x90 - brief backdriving event, mostly normal operation
- ✅ **T0_half (startup)**: 3% 0x90 backdriving, 1% 0xE0 init - captures startup sequence

**State definitions:**
- **0xE0 (1110 0000):** Initialization or Shutdown
- **0xF0 (1111 0000):** Normal operation (idle, generating, or neutral)
- **0x90 (1001 0000):** Backdriving active (generator motoring engine)

**Bit pattern:**
- Bit 6 high = normal/init, low = backdriving
- Bit 5 high = ready, low = not ready
- Bit 4 varies with state

**Note — byte 6 only:** This analysis covers 0x644 byte 6 exclusively. Later analyses found additional fields: B0 = VCU-sourced contactor leading indicator (0x07/0x08/0x10/0x17 enum); B2[7:4] = cruise mode; B2[3:0]:B3 = cruise speed setpoint (12-bit Motorola, 0.125 km/h/count). See `projects/vtrux/README.md` contactor flow and `cruise-control-analysis.md`.

---

### 0x63A Bytes 6-7 - Generator Initialization State ✅ MAJOR DISCOVERY

> **CORRECTION 2026-07-26 — read this before using the section below.**
> Two claims here were invalidated by the 2026-07-24 trip logs (8 h, main truck):
>
> 1. **The field is not purely persistent.** B7 bit5 (the `0xC4`↔`0xE4` difference,
>    described below as the "operational/ready flag" that persists once set) toggles
>    **at least a dozen times across a single day**, tracking generator activity rather
>    than latching. The "advances through levels and stays" model holds for the
>    `0x1804`→`0x1AC4` step but not for bit5.
> 2. **B7 bit4 was never observed** in the six logs this section was built from, so the
>    values `0xD4` and `0xF4` are absent from the tables and the bit gloss below. Both
>    values do occur in later logs.
>
> **RE-CORRECTED 2026-08-09 — point 2 above went too far.** It claimed B7 bit4 was "evap
> purge in progress." **That is withdrawn.** A full evap purge completes with bit4 clear
> across all 640,380 `0x63A` frames of `vtrux_20260719_190019`. The correct reading is
> that **B7 bits[5:4] are a single 2-bit field** taking all four values — bit5 and bit4 are
> not independent flags, and neither should be read in isolation. The field is
> **generator related, not further characterized**, consistent with this section's overall
> subject. See `evap-cycle-analysis.md` Phase 6 for the retraction. Use `0x649` for evap.
>
> **FALSIFIED 2026-08-09 (Phase 7).** The evap reading is now excluded by counterexample, not
> just unsupported: on Sunday 2026-07-26 `vcm_evap_counter` held 0 all day and
> `vcm_evap_active` was never set, yet bits[5:4] reached state 1 for a continuous 329 s.
> The same state ran 100% evap-active on Friday and 100% evap-inactive on Sunday. Note also
> that "bit4 tracks generator power, median 40 kW" — asserted in the first version of this
> box — is too strong: bit4 set means a *bounded* ~16-57 kW band (zero samples above 60 kW
> in 2,075 s), while the highest generator output occurs with bit4 **clear**.
>
> **ALSO FALSIFIED 2026-08-09: bits[7:6] is not an HV-up flag.** The tables below and the
> `0x1804`/`0x1AC4` gloss treat bits[7:6] clear as "HV / VCM not up". On Saturday 2026-07-25
> B7 was `0x04` for 100.0% of 27,926 sampled frames while `ess_power` reached 22.4 kW and
> `trac_power` 20.1 kW on `0x598` — power export plus light driving, so the HV bus was live
> the whole time. Both reference signals are read straight from the DBC on a different
> message, so this does not depend on any `0x63A` interpretation. What bits[7:6] encodes is
> unresolved.
>
> The `0x1804`/`0x1AC4`/`0x1AE4` observations below remain valid as far as they go; treat
> them as a partial view of B6-B7 rather than a complete decode.

**Distribution across logs:**
- `0x1804`: Never started (100% in movingaround)
- `0x1AC4`: Generator initialized (27% in generator on/off after startup)
- `0x1AE4`: Operational state (100% in T2 hybrid and T7 EV)

**Key finding: This is a PERSISTENT STATE that advances through initialization levels!**

**State progression:**
```
0x1804 (startup)
   ↓ (first generator activation)
0x1AC4 (generator initialized)
   ↓ (after regular use)
0x1AE4 (operational)
   ↓ (PERSISTS even in EV mode!)
0x1AE4 (stays in this state)
```

**Evidence:**
- **movingaround**: 100% at 0x1804 - generator NEVER started this session
- **generator on/off**: Transitions from 0x1804 → 0x1AC4 at t=46.8s (after first backdriving/generating)
- **T0_half (startup)**: Transitions from 0x1804 (21%) → 0x1AC4 (79%) during startup sequence
- **T7 (EV mode)**: 100% at 0x1AE4 - generator not currently running BUT was used previously
- **T2 (hybrid)**: 100% at 0x1AE4 - same operational state while actively generating
- **T4 (gen shutdown)**: 100% at 0x1AE4 - generator was running earlier, state persists after shutdown

**Bit differences:**
```
0x1804 = 0001 1000 0000 0100
0x1AC4 = 0001 1010 1100 0100  (bits 9,7,6 set from 0x1804)
0x1AE4 = 0001 1010 1110 0100  (bit 5 set from 0x1AC4)
```

**Interpretation:**
- Bit 9: Generator first activation complete
- Bits 7,6: Initialization sequence flags
- Bit 5: Operational/ready flag
- **This does NOT indicate if generator is currently running - it's a persistent initialization state**

---

### 0x649 Byte 7 - Generator Load/Activity Indicator ✅ MAJOR DISCOVERY

**Caveat — drive logs only:** Message content differs between drive and charge modes; do not interpret byte 7 from charge logs. A separate signal found by later analysis: B0 bit 7 = `vcm_evap_active` (1=evap in progress), clears ~6.1s before VCM commands generator stop. See `evap-cycle-analysis.md` and `projects/vtrux/README.md`.

**Distribution across logs:**
- `0x40`: Idle/generator off (23-100% depending on activity)
- `0x00`: **Generator actively producing power** (0-74%)
- `0xE0`: Transition event pulse (<1%)
- `0xA0`: Transition event or alternate state (<3%)

**Key finding: NOT just event pulses - has SUSTAINED OPERATING STATES!**

**Evidence:**
- **movingaround**: 100% at 0x40 - generator idle (not running)
- **T7 (EV mode)**: 100% at 0x40 - generator idle (not running)
- **T2 (hybrid)**: **74% at 0x00** - generator actively loaded and producing power!
- **T4 (gen shutdown)**: 84% at 0x40, **15% at 0x00** - generator producing power for first part, then idle
- **T0_half (startup)**: 96% at 0x40, 4% at 0x00 - brief power production after startup
- **generator on/off**: 99% at 0x40 - mostly idle except during brief startup events

**State definitions:**
- **0x40 (0100 0000):** Generator idle / not producing power
- **0x00 (0000 0000):** Generator actively loaded (producing significant power)
- **0xE0 (1110 0000):** Transition event pulse
- **0xA0 (1010 0000):** Alternate transition or state

**Transition example from generator shutdown (t=54.4s):**
```
t=54.004s: 0x00 (actively generating)
t=54.385s: 0xE0 (brief pulse during transition)
t=54.405s: 0x40 (returned to idle)
```

**Hypothesis:**
- 0x00 = Generator under load (producing >threshold power)
- 0x40 = Generator unloaded or off
- Pulses (0xE0, 0xA0) = State transition events

---

## Cross-Log Validation Results

| Status Field | Purpose | Validation Status |
|--------------|---------|-------------------|
| **0x644 byte 6** | Current operating mode (init/normal/backdriving) | ✅ **VALIDATED** - Consistent across all 6 driving logs |
| **0x63A bytes 6-7** | Generator initialization state (partly persistent) | ⚠️ **PARTIALLY SUPERSEDED 2026-07-26, re-corrected and falsified 2026-08-09** - progression 0x1804→0x1AC4 holds, but B7 bits[5:4] are a 2-bit field that toggles repeatedly within a session (not persistent); generator related, not further characterized. The interim "bit4 = evap purge" reading was retracted, then **falsified by counterexample** (2026-07-26: bit4 set 329 s with evap idle all day). Separately, **bits[7:6] is not an HV-up flag** - clear for 100% of 2026-07-25 while ess_power hit 22.4 kW. See correction box above. |
| **0x649 byte 7** | Generator load indicator (idle vs active) | ✅ **VALIDATED** - 0x40=idle, 0x00=producing power (confirmed in T2, T4, T0_half) |

---

## Key Insights

### 1. 0x63A is NOT "generator currently running"
- It's a **partly persistent initialization state** that advances through levels
- Stays at 0x1AE4 even when generator is off (EV mode)
- Indicates "generator subsystem initialization level" not "current activity"
- **Corrected 2026-07-26, re-corrected 2026-08-09:** the persistence claim is true of the
  0x1804→0x1AC4 step, but B7 bits[5:4] do *not* persist — that field toggles repeatedly
  within a session. Read bits[5:4] as one 2-bit field (B7 = 0xC4/0xD4/0xE4/0xF4), not as two
  independent flags. It is unassigned; an interim "bit4 = evap purge" reading was retracted
  2026-08-09. See correction box above.

### 2. 0x649 byte 7 IS "generator currently producing power"
- 0x40 = Idle/off
- 0x00 = Actively loaded and generating
- This is the REAL indicator for "generator is running under load"

### 3. 0x644 byte 6 indicates current physical mode
- 0x90 = Backdriving (generator physically motoring the engine)
- 0xF0 = Normal (can be idle, generating, or neutral - check 0x649 for load status)
- 0xE0 = Init/shutdown

### 4. Complete state determination requires all three fields
To know generator state:
- **0x644 = 0x90**: Generator backdriving engine (starting it)
- **0x644 = 0xF0 AND 0x649 = 0x00**: Generator producing power
- **0x644 = 0xF0 AND 0x649 = 0x40**: Generator idle or off
- **0x644 = 0xE0**: System initializing or shutting down
- **0x63A**: Tracks initialization level (persistent across modes)

---

## Generator Startup Sequence (from generator on/off log)

```
t=39.1s:  Trigger (shift to Manual mode on Vehicle bus)
          0x63A: 0x1804 (never started)
          0x649: 0x40 (idle)

          [6.5 second delay]

t=45.6s:  Backdriving starts
          0x644: 0xF0 → 0x90
          0x051: 32768 → 33096
          0x649: 0x40 (still idle - engine cranking, no load yet)

t=46.8s:  State transition
          0x63A: 0x1804 → 0x1AC4 (initialization complete!)

t=46.9s:  Backdriving ends
          0x644: 0x90 → 0xF0
          0x051: → 32768 (neutral)

t=47.1s:  Generating starts
          0x051: 32768 → 32474 (generating)
          0x649: 0x40 → 0x00 (load applied!)
```

---

## Generator Shutdown Sequence (from generator on/off log)

```
t=54.0s:  Second backdriving event starts
          0x644: 0xF0 → 0x90
          0x051: generating
          0x649: 0x00 (active)

t=54.4s:  Shutdown
          0x644: 0x90 → 0xF0
          0x051: → 32768 (neutral)
          0x649: 0x00 → 0xE0 → 0x40 (transition pulse, return to idle)
          0x63A: 0x1AC4 (stays initialized - persistent!)
```

---

## Recommended DBC Definitions

```dbc
BO_ 1604 Generator_Control_Status: 8 Vector__XXX
 SG_ Operating_Mode : 54|8@1+ (1,0) [0|255] "" Vector__XXX

VAL_ 1604 Operating_Mode
  240 "Normal_Operation"
  224 "Initialization_Shutdown"
  144 "Backdriving_Engine" ;

BO_ 1594 Generator_Initialization_State: 8 Vector__XXX
 SG_ Init_State : 48|16@1+ (1,0) [0|65535] "" Vector__XXX

VAL_ 1594 Init_State
  6148 "Never_Started"
  6852 "Initialized"
  6884 "Operational" ;

BO_ 1609 Generator_Load_Status: 8 Vector__XXX
 SG_ Load_Indicator : 63|8@0+ (1,0) [0|255] "" Vector__XXX

VAL_ 1609 Load_Indicator
  64 "Idle_No_Load"
  0 "Active_Producing_Power"
  224 "Transition_Event_1"
  160 "Transition_Event_2" ;
```

---

## Additional Validation Findings

### From T4 (Generator Shutdown at t=58s)

This 300-second log captured a generator shutdown event, providing additional validation:

- **0x644 byte 6:** 99.9% at 0xF0 (normal operation), with only 0.1% at 0x90 (brief backdriving event)
- **0x63A bytes 6-7:** 100% at 0x1AE4 - confirms this state persists even after generator shuts off
- **0x649 byte 7:** Transitions from 0x00 (15% - active generating) to 0x40 (84% - idle after shutdown)
- **Key insight:** 0x649 transitions from 0x00→0x40 correlate with generator shutdown, while 0x63A remains at 0x1AE4

### From T0_half (Startup Sequence)

This ~50-second startup log captured the initial generator activation:

- **0x644 byte 6:** 97% 0xF0, 3% 0x90 (backdriving), 1% 0xE0 (initialization)
- **0x63A bytes 6-7:** Captures the 0x1804→0x1AC4 transition (21% → 79%)
- **0x649 byte 7:** Mostly 0x40 (96%), with 4% at 0x00 (brief power production after startup)
- **0x051 command:** 79% generating, 19% neutral, 3% backdriving
- **Key insight:** This log provides a second observation of the critical 0x1804→0x1AC4 transition during generator first use

### Validation Summary

All 6 driving logs show **perfect consistency**:

1. **0x644 = 0x90 only appears when generator is backdriving** (starting engine)
2. **0x63A progresses unidirectionally:** 0x1804 (never used) → 0x1AC4 (first use) → 0x1AE4 (operational)
3. **0x649 = 0x00 correlates strongly with generator power output** (T2: 74%, T4: 15% during gen operation, T0_half: 4% brief)
4. **0x649 = 0x40 when generator is idle or off** (all EV mode logs, post-shutdown periods)

No contradictory behavior was observed across any of the 6 logs.

---

## Open Questions

1. **What determines transition from 0x1AC4 to 0x1AE4?**
   - Time-based? Cycles? Successful operation duration?
   - Need more logs showing this specific transition

2. **What power threshold triggers 0x649 byte 7 = 0x00?**
   - Correlate with 0x051 magnitude in T2 hybrid log
   - Is it absolute power or % of capacity?

3. **Can 0x63A state regress?**
   - Does it reset on key cycle?
   - Does it ever go backwards (e.g., after long idle)?

4. **What do 0x649 pulses (0xE0, 0xA0) specifically indicate?**
   - Different types of transitions?
   - Different event sources?

---

## Next Steps

- [x] ~~Validate status bits across additional driving logs~~ - **COMPLETED** (validated across 6 logs)
- [ ] Analyze T2 hybrid log in detail - correlate 0x649 transitions with 0x051 power level to find exact threshold
- [ ] Find log showing 0x1AC4 → 0x1AE4 transition (none of the 6 driving logs captured this)
- [ ] Compare with failed charge/generator logs for error states
- [ ] Test hypothesis: 0x649 = 0x00 when |0x051 - 32768| > threshold
- [ ] Map complete state machine with all possible transitions
- [ ] Investigate what causes 0xA0 pulses vs 0xE0 pulses in 0x649
