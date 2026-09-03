# APP GEN MOD Investigation

## Physical Description

- Module labeled **"APP GEN MOD"** — installed under the dash on the main truck (app_disconnect test vehicle)
- **Not present on the parts truck**, despite both trucks having the same overall drivetrain architecture (analog throttle, same ECM)
- External enclosure with a **6-pin connector** under the hood
- Location and label confirmed by visual inspection

---

## Background: How Throttle Works on the Vtrux

From `projects/vtrux/README.md` (confirmed architecture):

> The VCM commands engine throttle via analog wire to the ECM's APP input pins — this is not on CAN.

**Correction 2026-08-14:** this section previously continued "...the GMLAN DBC contains only validity
flags with no percentage value." That was wrong — an artifact of the deprecated DBC extraction. The
ECM *does* echo the APP voltage it receives onto CAN as `Accelerator_Actual_Position` (0x0C9, OBD bus), and `Accelerator_Effective_Position` (0x1C3). The VCM→ECM path itself
is still analog; what is on CAN is the ECM's readback of that analog input. See `projects/vtrux/README.md`.

The GM ECM uses a two-sensor **Accelerator Pedal Position (APP)** input system — standard GM redundant safety design. Both APP sensor circuits must agree within tolerance; if either drops to zero (circuit low), the ECM sets fault codes and the MIL illuminates.

On a stock GM truck, these sensor wires run from the physical accelerator pedal. On the Vtrux, the engine throttle is VCM-commanded — the driver's physical pedal position (0x592 B2-B3 on PT bus) is processed by the VCM, which then outputs an analog APP voltage to the ECM. The "APP GEN MOD" sits in that signal path.

---

## Disconnect Test — `vtrux_app_disconnect_test.log`

**Test sequence (per operator notes):**
1. Module physically disconnected
2. No immediate effect observed (this is consistent — the ECM needs the engine running and performing readiness checks to set APP codes)
3. Generator started, engine cranked
4. Check engine light illuminated immediately on engine start
5. OBD scan tool connected — two codes present

**Log duration:** 218.7 s  
**OBD scan window:** t~106–162 s

**OBD result (Mode 01 PID 01):**
- At t=106.28s: MIL=off, stored DTC count=0
- At t=106.84s: **MIL=ON, stored DTC count=2**

The MIL transition happened within the first second of the scan polling cycle — the codes were already latched from engine start.

**DTCs retrieved (Mode 03/07/0A — all three agree):**

| Code | SAE Description | Circuit |
|------|----------------|---------|
| **P2122** | Throttle/Pedal Position Sensor/Switch D Circuit Low Input | APP sensor 1 |
| **P2127** | Throttle/Pedal Position Sensor/Switch E Circuit Low Input | APP sensor 2 |

Both codes in **stored, pending, and permanent** memory simultaneously. The permanent flag means a standard scan-tool clear will not extinguish the MIL — a complete OBD drive cycle is required after restoring the module.

**Interpretation:** Both APP sensor circuits read 0 V (low). The ECM's two APP inputs both lost their analog voltage source simultaneously, which is the exact expected result of unplugging the module that generates those voltages.

### CAN-side confirmation (added 2026-08-14)

The DTCs are corroborated on CAN. In `vtrux_app_disconnect_test.log`, `Accelerator_Actual_Position` (0x0C9) reads **0 in 21,868 of 21,868 frames** on the OBD bus while the engine was running (RPM 800–848), with `Accelerator_Actual_Position_Validity` asserting "Valid" throughout. Three stray non-zero frames appear on the second captured channel out of 17,504.

The parts truck, which has no APP GEN MOD at all, shows the same thing — 0x0C9 B4 constant 0 across 3,332 and 4,170 frames in `vtrux_partstruck_testdrive_part3_engine.log`, with the engine idling and TPS swinging to 99.6%.

By contrast, a normal main-truck drive log (`vtruxanotherevaplogpart2.log`) shows 0x0C9 B4 taking 230 distinct values spanning the full 0–254 range (0–99.6%).

**This upgrades the module's role from hypothesis to confirmed:** the APP GEN MOD is what drives the ECM's APP input, and removing it drives that input — and therefore the CAN-reported APP value — to zero. It also gives a non-invasive CAN-only test for the module's health: engine running with APP pinned at 0% means the module or its wiring is not delivering voltage.

---

## Hypothesis: Analog Signal Conditioner / Buffer

**Hypothesis (unconfirmed):** The APP GEN MOD takes an analog signal from the VCM and outputs two conditioned analog voltages (APP sensor D and APP sensor E) to the ECM. It likely buffers, scales, or cleans up the throttle signal — not a mandatory conversion but may be needed for impedance matching or noise rejection on this specific build.

Supporting evidence:
- Disconnect causes both APP sensor inputs to drop to 0 V simultaneously — consistent with a shared active voltage source being removed
- The VCM already has the throttle command internally (from 0x592 B2-B3 pedal + its own control logic)
- The module is physically distinct from the ECM and has its own connector, implying it takes input from somewhere (most likely analog from the VCM)
- No CAN: disconnecting caused no message dropouts and no modules going offline
- The parts truck lacks this module — **open question: how does the parts truck's ECM receive APP signal?** Possibilities: (a) direct wire from VCM analog output to ECM without this module, (b) parts truck ECM configured to not require APP (different calibration)

**6-pin connector hypothesis (unconfirmed):**

| Pin | Likely function |
|-----|----------------|
| 1 | 12V switched power |
| 2 | Ground |
| 3 | Analog or PWM input from VCM |
| 4 | Signal return / spare |
| 5 | APP sensor D analog output (to ECM) |
| 6 | APP sensor E analog output (to ECM) |

Pins 3/4 assignment requires oscilloscope or DMM trace to confirm.

---

## Open Questions

1. **Parts truck APP input wiring:** The parts truck has the same analog-throttle architecture but no APP GEN MOD. How does its ECM receive APP signal? Does it simply not have the generator enabled/wired, making throttle control irrelevant? Or is there a direct wire from the VCM analog output to the ECM without going through this module?

2. **No CAN confirmed — input unknown:** Disconnect caused no message dropouts and no modules going offline, ruling out CAN. Input is likely analog or PWM from the VCM. Oscilloscope or DMM trace on pins 3/4 while powered would confirm.

3. **Connector pinout:** Measure with a DMM while module is powered: identify 12V/GND, then trace the signal outputs to the ECM harness and the inputs back toward the VCM or CAN bus.

4. **Why this truck but not the parts truck?** Possibly: (a) VIA retrofit kit for trucks that have the generator option; (b) emissions compliance requirement for the generator-equipped variant; (c) original wiring difference between two build dates.

---

## Related Files

| File | Relevance |
|------|-----------|
| `vtrux_app_disconnect_test.log` | Disconnect test log (`projects/vtrux/logs/`) |
| `artifacts/app_disconnect_obd.txt` | Decoded OBD exchanges from the disconnect log |
| `projects/vtrux/README.md` — "No APP on GMLAN" section | Architecture background: analog throttle path |
| `tools/extract_obd.py` | Tool used to decode the OBD scan (`projects/vtrux/tools/`) |
| `can-disconnect.md` | Other disconnect tests (PE pump, HV battery, VCM) for comparison methodology |
