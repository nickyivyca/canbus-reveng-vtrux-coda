# Vtrux Isolation Fault Analysis

Logs captured 2026-03-06. First deliberate isolation fault test -- 1 kOhm resistor
connected HV-to-chassis while truck was key-on.

- **vtruxisolationtest.log** (19 MB, ~65s): key on, resistor inserted, contactor trip,
  resistor removed (fault stays latched).
- **vtruxisolationtestrecovery.log** (12 MB, ~45s): fault latched after key-off; 12V
  battery disconnect/reconnect cleared the latch; truck restarted normally.

---

## Phase 1 -- Fault Signature (COMPLETED 2026-03-06)

### Model: Periodic Isolation Test

The BMS likely runs isolation tests on a periodic cycle (Bender-type IMD behavior). The
resistor insertion is not detected continuously -- the gap between insertion and contactor
trip is the time remaining until the next scheduled test fires. Once the test fails, the
contactor trip is immediate. The pre-fault CAN traffic shows no BMS changes; the shutdown
sequence begins at the same instant detection is reported.

Confirmed by the pre-fault window (t=33--38s): no BMS ID (0x4xx range) changes in this
period. Only background GM PPEI/odometer traffic. The fault sequence starts cold at t=38.10s.

### 0x410 B1 -- Operational State and Fault Sequence

B1 = **0xBF is the normal running state** (HV up, contactors closed, no fault).
B1 = 0x3F is the pre-HV startup state.

| B1 value | Meaning |
|----------|---------|
| 0x3F = 0011 1111 | Pre-operational (startup, HV not yet up) |
| 0xBF = 1011 1111 | Normal operation (HV up, contactors closed) |
| 0xB0 = 1011 0000 | Shutdown step 1 (lower nibble clears) |
| 0xF0 = 1111 0000 | Shutdown step 2 transient (bits 6,5,4 set) |
| 0xC0 = 1100 0000 | **Fault latched** (bit6 = universal fault, bit7 retained) |
| 0xCF = 1100 1111 | Settled latched state (~9s after trip, lower nibble re-appears) |

Fault shutdown sequence (all within ~200ms):

```
t=38.10s  0x410 B1: 0xBF -> 0xB0  (lower nibble clears -- shutdown begins)
          0x410 B2: 0xA0 -> 0x00
t=38.25s  0x410 B0: 0x19 -> 0x1B  (bit4 sets transiently)
          0x410 B1: 0xB0 -> 0xF0  (bits 6,5,4 set transiently)
          0x412 B0: 0x2D -> 0x00  (BMS lifecycle clears simultaneously)
          0x420 B3: 0xC7 -> 0x00
t=38.30s  0x410 B0: 0x1B -> 0x0B  (bit4 clears -- contactors open)
          0x410 B1: 0xF0 -> 0xC0  *** UNIVERSAL FAULT BIT6 LATCHES ***
t=47.51s  0x410 B1: 0xC0 -> 0xCF  (settled; lower nibble re-appears)
          0x410 B2: 0x00 -> 0xFE
```

After t=47.51s, 0x410 B1 does not change for the remainder of the log (~18 more seconds)
even though the resistor was removed. **The fault latch does not self-clear** -- it requires
the 12V battery cycle seen in the recovery log.

### 0x410 B0 -- Interlock Not Involved

At the fault moment: B0 = 0x0B = 0000 1011

- Bit3 = 1: interlock loop **still closed** -- isolation fault does not open the interlock
- Bit4 = 0 after trip (was 1 during normal operation at 0x19). Possible contactor-closed
  flag (clears when contactors open). Hypothesis only, not confirmed.

Recovery log: B0 = 0x0B, B1 = 0xCF throughout (both latched, never change).

### 0x420 B3 -- Isolation Resistance Reading (see Phase 2)

B3 dropped from 0xC7=199 (most recent test result: good insulation) to 0x00 at t=38.26s
simultaneously with the fault. Phase 2 confirmed B3 is the BMS isolation monitor's
periodic test result broadcast. See Phase 2 for full evidence and interpretation.

Note: B3=0 at a fault moment is NOT isolation-specific -- any contactor opening drops HV
and causes B3 to read 0. B3 is only a causal indicator when it drops from a valid
reading (not 0xC8 init) simultaneously with the trip, as happened here.

### 0x412 -- BMS Lifecycle Mirror ID

B0 = 0x2D during normal operation, drops to 0x00 at the fault (t=38.25s, simultaneous).
B2 = BMS SoC-based charge current ceiling (HIGH CONFIDENCE — r=0.999 vs 0x050 CCL during
charge ramp; static during driving). See `notes/current-limits-investigation.md` Phase 4.
B3-B7 always 0x00.

### 0x644 B0 -- No Change at Fault

Settled at 0x10 during startup and did not change at the fault moment. The 0x17 pattern
seen in interlock fault logs did not appear. Isolation fault uses a slower BMS-managed
shutdown path, not the VCU emergency cutoff path that produces 0x17.

### 0x63D -- Not Present

Not present in either isolation test log (charge-bus-only message).

### 0x410 B2 -- Isolation-Specific Indicator

B2 = 0xA0 during normal operation, clears to **0x00 at the first step of the isolation
fault sequence** (t=38.10, simultaneous with B1: 0xBF->0xB0), then settles to 0xFE
when the fault latch stabilizes (t=47.51).

Phase 3 comparison confirmed B2=0x00 does NOT appear in the interlock fault log or any
charge fault log -- those show only 0xA0 and 0xFE (B2 Uniq=2). Only the isolation test
has Uniq=3 (adding 0x00). This makes B2=0x00 at fault onset the strongest
isolation-specific positive indicator found in this investigation.

The B2=0x00 intermediate and the 4-step B1 sequence both start at the same moment and
likely reflect the BMS-ordered shutdown path triggered by its own isolation test, as
opposed to the abrupt emergency-trip path that interlock and charge faults take.

### Resistor Removal (Post-Fault, First Log)

After the contactors open (t=38.30s) the resistor was removed. No BMS status byte changes
after t=47.51s -- the fault latch does not self-clear. 0x420 B3 (isolation resistance)
does not recover after resistor removal because the HV bus is offline once contactors
open; the isolation monitor cannot measure anything. See Phase 2 for B3 details.

---

## Phase 2 -- Isolation Resistance Broadcast (COMPLETED 2026-03-06)

**Finding: 0x420 B3 is the isolation resistance reading.**

### Evidence

**Driveway log** (`movingaroundindriveway.log`, 92s, no fault):
- B3 initializes to 0xC8=200 at t~17s
- Descends from 200 to a minimum of ~188-190 over the first ~20s of operation
- Then slowly recovers upward to ~194 by end of log (~90s total)
- Never reaches 0 during normal operation
- At key-off: drops from 194 to 0 instantly (power-down, not a fault)

**80% charge log** (`vtruxchargeafterexportchargetest-80pctcv.log`, ~2.6 hours, healthy charge):
```
t=80s:           B3=200 (initialized)
t=80-380s:       200->192 (settling over ~5 min)
t=480-7430s:     B3=192  (locked for ~1.9 hours -- entire bulk charge phase)
t=7430-7940s:    192->200 (recovery -- CV phase begins, current tapers, resistance rises)
t=7940-9290s:    B3=200  (locked for last 22 min)
t=9299s:         B3=0    (key-off power-down)
```

**Isolation fault log** (`vtruxisolationtest.log`):
- B3 initialized to 0xC8=200, first test result 0xC7=199 at t=10.43s
- Stayed at 199 through multiple test cycles (good insulation = no fault)
- Dropped directly to 0 at t=38.26s when the periodic test fired with the 1 kOhm
  fault resistor present -- one test cycle, one result: near-zero resistance

**Recovery log** (`vtruxisolationtestrecovery.log`):
- B3=0 throughout the latched-fault/key-off phase (t=0-30s: BMS completely powered off)
- After 12V reconnect at t~30s: B3 initialized to 200, first test gives 199 at t~37s
- Drops to 0 at t=44.94s (log end) -- this is key-off power-down, not a new fault
  (user confirmed truck started fine after 12V cycle)
- Log too short (~15s of active BMS time) to observe B3 stabilize at its nominal value

### Interpretation

B3 is updated by each periodic isolation test cycle:
- **B3=200 (0xC8)**: initialization / "no measurement yet"
- **B3=192**: nominal healthy isolation resistance during this truck's operation
  (stable plateau for the entire bulk charge phase)
- **B3=188-200**: normal variation range across operating conditions (temperature, current)
- **B3=0**: fault -- measured resistance near zero (1 kOhm resistor to chassis)
- **B3=0 at key-off**: power-down, always drops to 0, not a fault indicator

The slow descent from 200 to ~192 after startup reflects the first few test cycles
calibrating to the actual bus insulation resistance. The recovery from 192 back to 200
at the end of the bulk charge phase likely reflects the CV taper -- less current flow
means less resistive heating of HV cables, which slightly improves insulation resistance.

### Scale

The absolute kOhm/MOhm encoding is not yet determined. Known data points:
- B3=192-200 = healthy (good insulation, >100s of kOhm)
- B3=0 = fault (1 kOhm fault resistor to chassis)

The jump from 192 directly to 0 with a 1 kOhm resistor suggests the encoding is likely
non-linear or that 1 kOhm is far below the measurement floor of the isolation monitor
(i.e., any resistance below some threshold rounds to 0). The actual healthy resistance
of the HV bus is likely on the order of MOhm, far above 1 kOhm.

### Fault detection: no CAN signal before the trip

The isolation test fires periodically. In the fault log, B3 held at 199 for ~27 seconds
across multiple test cycles (good insulation each time), then one cycle detected 0 and
triggered the trip immediately. There is no gradual decline in B3 before the fault --
the fault resistor is either present for a test cycle or it isn't.

### Causal vs lagging indicator

B3=0 at the trip moment is only a causal indicator when B3 was at a valid non-zero
reading (not 0xC8 init) immediately before. In that case, the isolation monitor's test
result IS the trigger. If B3 was at 0xC8 at the trip (as in some charge fault logs), the
BMS had not completed any test cycle yet and B3=0 is just a power-down consequence.

---

## Phase 3 -- Comparison to Other Fault Logs (COMPLETED 2026-03-06)

**Logs compared:** `full charge then fail.log` (~2hr, 2 fault events at t~7243s and t~7246s),
`rainychargedebug.log` (~61min, 1 fault), `vtruxinterlocktest.log` (~315s, 1 fault).
**Artifacts:** `fullchargethenfall-0x410.txt`, `rainy-0x410.txt`,
`full-charge-then-fail-analysis.txt` (status_events), `isolation-0x411.txt`,
`interlock-0x411.txt`, `rainy-0x411.txt`.

### Isolation Fault Signature vs Other Fault Types

Summary of 0x410 byte behavior at the fault moment across all fault types:

| Signal | Isolation fault | Interlock fault | Charge faults |
|---|---|---|---|
| B1 latch | 0xCF | 0xCF | 0xCF |
| B1 path | 0xBF->0xB0->0xF0->0xC0->0xCF | 0xBF->0xFF->0xCF | varies (see below) |
| **B2 at fault onset** | **0xA0->0x00** | stays 0xA0 | stays 0xA0 |
| B2 settled | 0xFE | 0xFE (+15s) | 0xFE |
| B0 bit3 | 1 (interlock closed) | 0 (interlock open) | 1 |
| 0x412 B0 | 0x2D->0x00 | 0x2D->0x00 | 0x2D->0x00 |
| 0x420 B3 | valid reading->0x00 | valid reading->0x00 | varies (see below) |

**Key finding: 0x410 B2 = 0x00 at fault onset is isolation-test-specific.** It appears
in no other fault log. B2 clears simultaneously with B1's first step (0xBF->0xB0) and
holds at 0x00 for ~9s before settling to 0xFE. All other fault types show only 0xA0 and
0xFE -- never 0x00 (B2 Uniq=2 in interlock and all charge logs vs Uniq=3 in isolation).

### B1 Fault Paths

The path to the 0xCF latch depends on the operating mode, not the fault type:

| Fault | Pre-fault B1 | Notes |
|---|---|---|
| Isolation (today, traction bus, drive mode) | 0xBF | 4-step ordered shutdown |
| Interlock fault | 0xBF | abrupt: 0xBF->0xFF->0xCF |
| Charge fault -- rainy | 0xBF | direct: 0xBF->0xCF |
| Charge fault -- full charge then fail | 0x7F (brief) | 0x7F->0xFF->0xCF |

The 4-step B1 sequence (0xBF->0xB0->0xF0->0xC0) is unique to the isolation test among
all logs examined. Together with B2=0x00, these both reflect the BMS-ordered shutdown
triggered by its own isolation test result, as opposed to the abrupt-trip path taken by
interlock and charge faults. The different intermediate states in charge faults also
reflect a different contactor un-sequencing order (charge contactors are secondary to
main contactors; all contactors open for any major fault but in a different order).

### Charge Mode B1 Starting State

- `rainychargedebug.log`: B1 = 0xBF during charge (mean=190.8) -- same as drive mode.
- `full charge then fail.log`: B1 = 0x3F for ~98% of the 2hr log, briefly 0x7F
  immediately before fault. Traction contactors remained open during this charge session.

### 0x420 B3 in Charge Faults

- `full charge then fail.log` (both fault events): B3 = 0xC8=200 (init, no test result)
  at the fault moment. B3 drops to 0 as a consequence of contactors opening, not as a
  causal isolation detection event. The fault fired before the isolation monitor completed
  its first test cycle.
- B1 changed 13ms before B3 in these events (B1 leads B3), confirming B3=0 is a
  lagging consequence.

### Fault-Type Discriminator Search

Searched for any BMS byte that positively identifies fault type beyond what 0x410 B2
already provides:

- **0x411 B0-B1**: confirmed bms_soc_hires (14-bit Motorola, 0.01%/count; raw = B0×64 +
  (B1>>2)). r>0.998 vs 0x596. The 3048 unique pair values and ADC bit-toggle pattern are
  consistent with a 14-bit hi-res SoC reading. No change at fault moment in any log.
- **0x63D**: not present in isolation or interlock logs (charge-bus-only message).
- **0x410 B0 bit3**: interlock loop physical state (0 = open). Discriminates interlock
  from isolation/charge but is a hardware consequence, not a BMS fault-type assertion.

No dedicated fault-type byte found. The BMS does not appear to broadcast a signal that
explicitly labels the fault as "isolation" vs "interlock" vs other. The combination of
B2=0x00 + 4-step B1 sequence + B0 bit3 remaining 1 is the strongest available signature
for identifying a traction-bus isolation fault in drive mode.

---

## Phase 4 -- bcm_vbus_pos / bcm_vbus_neg Behavior (2026-03-28)

**Signals:** `bcm_vbus_pos` and `bcm_vbus_neg` from 0x0440, both 12-bit Motorola BE.
- `bcm_vbus_pos`: raw * 0.25 V (no offset), measures positive HV rail to chassis
- `bcm_vbus_neg`: raw * 0.25 - 500 V (offset -500), measures negative HV rail to chassis;
  raw=2000 = 0 V (chassis potential)

### Normal operation baseline

Checked across `vtruxcurrentlimitingtest.log` (1795s) and `vtruxevapdrivelog.log` (277s):

- `bcm_vbus_pos` ≈ **374-387 V** (tracks pack voltage, stable throughout)
- `bcm_vbus_neg` ≈ **+0.50 V** (raw ≈ 2002; essentially chassis ground, rock-solid)

The negative HV rail sits at chassis potential during all normal operation. The pack is
**not** floating symmetrically -- the negative terminal is effectively bonded to chassis.
The 0.50 V reading is likely an ADC zero-point offset.

Normal shutdown (captured at end of `vtruxcurrentlimitingtest.log`): pos drops from 374 V
and neg rises slightly from 0 V, but both reach sentinel (1023.50 V / 523.50 V = raw 0xFFE)
within ~150ms as the BMS powers off. No symmetric redistribution occurs.

### Isolation test behavior

In `vtruxisolationtest.log`, at t=50s (approximately when the fault resistor was connected
to the positive terminal), both signals shift dramatically:

```
t=49.69  pos= 387.00  neg=  0.50  (normal)
t=50.19  pos= 123.00  neg=-110.25  sum= +12.75  <-- sudden shift
t=50.69  pos= 102.75  neg=-117.25  sum= -14.50
t=51-58  pos ~55-95   neg ~-50 to -117  sum ~-15 to -6  (symmetric, both decaying)
t=57.20  pos=  57.75  neg= -58.75  sum=  -1.00  (near-perfect symmetry)
t=59+    neg recovering toward 0, pos still elevated (sum rising again)
t=69+    both approaching small values as pack discharges
```

The sum (pos + neg) near zero means |pos| ≈ |neg| -- both rails equidistant from chassis.
This is the floating/symmetric pattern the isolation monitor's measurement scheme produces
when the pack is not chassis-bonded. The symmetric decay from ~±115 V toward zero reflects
residual capacitive charge dissipating after the contactors opened.

The symmetric behavior is **unique to the isolation test**. It does not appear in normal
shutdowns (where both signals just go to sentinel within 150ms). It is consistent with the
positive terminal being forced to chassis, causing the isolation monitor to re-center itself
across the pack, and/or the contactors opening and leaving the pack floating.

### Interpretation

`bcm_vbus_pos` and `bcm_vbus_neg` are the A123 BMS isolation monitor's two rail-to-chassis
voltage readings. In normal operation, the BMS actively anchors the negative rail to chassis
(or the pack architecture has a hard chassis bond on the negative side). The isolation monitor
detects a fault when one rail is suddenly pulled hard to chassis potential, which shows up as
both signals briefly reading equal and opposite during the fault/discharge transient.

---

## Phase 5 -- 0x0440 bcm_fault_mon / bcm_mainc_stat and 0x0410 bcm_gfd (2026-03-28)

### bcm_fault_mon -- periodic 1 Hz isolation test pulse

`bcm_fault_mon` (0x0440 B0 bit 6) toggles HIGH for ~100ms, LOW for ~900ms, every second
throughout all normal operation. The pattern is identical across every log examined
(current_limit, evap_drive, generator_on_off, isolation_test). It does **not** latch HIGH
after the isolation fault -- it continues toggling normally after the contactors open and
through the end of the log.

This is the BMS continuously running its isolation test injection cycle (Bender-type IMD
behavior). The 0x420 B3 isolation resistance result updates less frequently (~27s) because
it reflects the validated result of multiple injection cycles, not each individual pulse.

### bcm_mainc_stat (0x0440) -- contactor sequence at fault

Normal running state is index 11. Startup sequence: 0→2→5→7→8→9→11.

At the isolation fault (t=49.89s): direct **11→14** transition (skips state 13).
At normal shutdown: **11→13→14** (two-step ordered sequence).

Key EPRI-confirmed state strings (4-bit index, 16-entry array):
- 7 = WAIT_PRECHARGE
- 11 = MAIN_P_CLOSED_TRAC (drive) or MAIN_P_CLOSED_CHARGE (charge)
- 13 = SHUTDOWN_REQUEST (ordered shutdown intermediate)
- 14 = ALL_OPEN_SHUTDOWN (contactors open/offline)

The isolation fault skips SHUTDOWN_REQUEST and hits ALL_OPEN_SHUTDOWN directly -- abrupt
trip vs. ordered power-down.

### bcm_gfd -- ground fault detection confirmed

`bcm_gfd` (0x0410, 12-bit Motorola BE startbit=11, scale 0.25 V) holds **1000.0 V**
(raw=4000) throughout all normal operation and **all charge fault logs**. It drops to
**0.0 V** (raw=0) only in the isolation test, at t=49.70s -- **150ms before** the
TYPE3+EPO fires at t=49.85s.

| Log | bcm_gfd |
|-----|---------|
| vtruxcurrentlimitingtest.log | 1000.0 stable, no transitions |
| vtruxevapdrivelog.log | 1000.0 stable, no transitions |
| generator on then off.log | 1000.0 stable, no transitions |
| truk1log_M1_T14.log (charge fault EPO) | 1000.0 stable, no transitions |
| vtruxisolationtest.log | 1000.0 → **0.0** at t=49.70s, stays 0 |

`bcm_gfd` is a leading detection indicator, not a consequence of the shutdown. It fires
150ms before the EPO, does not fire in any charge fault, and does not fire in normal
operation. The signal name is the EPRI plist label; role is now confirmed as ground fault
detection.

---

## Phase 6 -- bcm_alarm TYPE2 Background Behavior (2026-03-28)

### Observation

`bcm_alarm` (0x0410 14-bit field, decoded as NONE/TYPE1/TYPE2/TYPE3) shows a consistent
NONE→TYPE2 transition ~4-5 seconds after HV-up in every log of the **main truck with parts
truck battery**:

| Log | Config | TYPE2 onset after HV-up |
|-----|--------|------------------------|
| vtruxevapdrivelog.log | main truck, parts battery | +3.8s after mainc CLOSED |
| generator on then off.log | main truck, parts battery | +4.3s after mainc CLOSED |
| vtruxcurrentlimitingtest.log | main truck, parts battery | already TYPE2 at log start |
| vtruxisolationtest.log | main truck, parts battery | +5.0s after ready |

This pattern is **absent** in the other battery/chassis combinations:

| Log | Config | bcm_alarm behavior |
|-----|--------|--------------------|
| oghighwaydrive.log | main truck, original battery | NONE throughout startup; TYPE2 fires ~12.8 minutes into drive |
| truk1log_M1_T0.log | main truck, original (pre-swap) battery | NONE throughout startup (matches oghighwaydrive pattern — original battery does not show quick TYPE2; was mislabeled as parts truck, corrected 2026-04-11) |

### Significance for isolation fault analysis

The quick TYPE2 at startup is **not** an isolation fault indicator -- it fires in every
main-truck/parts-battery session regardless of whether a fault occurs. It is a background
alarm condition specific to that truck+battery combination.

The isolation fault alarm sequence is therefore:
```
t=22.57s  TYPE2 (routine background, fires ~5s after HV-up as always)
...
t=49.70s  bcm_gfd: 1000 -> 0     (isolation fault detected)
t=49.85s  TYPE2 -> TYPE3 + epo=1 (immediate escalation, ~150ms after gfd)
t=49.90s  contactors open
```

There is no isolation-specific warning window -- gfd fires and EPO follows within 150ms.

The original battery in the main truck also eventually shows TYPE2 (mid-drive, ~12.8 min
after HV-up) with no EPO -- a different character from the 4-5s startup pattern, and likely
a separate fault event specific to that session. The parts truck with its own battery shows
no background TYPE2 at all (alarm=NONE throughout).

### Comparison to charge fault alarm path

In the before-battery-swap charge fault session (truklog_M1_T14 in `actual-failed-charges/`, ~61 min charge; note: previously written as `truk1log_M1_T14` — that is a different file, the Oct 2025 clean charge session with no fault):
- TYPE2 fires ~5s after ready (same background pattern as drive sessions)
- EPO fires 61 minutes later: TYPE2→TYPE3 + epo=1 simultaneously
- hvil_mon drops 0.3s **before** EPO (HVIL opens first; leads EPO in this session)
- bcm_gfd = 1000.0 throughout (never fires)

Both isolation and charge fault paths end in TYPE2→TYPE3+EPO, but only isolation faults
trigger bcm_gfd=0. The hvil_mon behavior at the charge fault (opens before EPO) differs
from the isolation fault (stays HIGH through entire fault sequence), consistent with Phase 1
findings.
