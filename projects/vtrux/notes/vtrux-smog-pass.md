# Vtrux Smog-Pass Generator-Runner Analysis

**Completed:** 2026-06-18
**Primary log:** `../../CANLogs/VtruxLogs/vtrux_20260617_193900_T0..T35.log` — single session,
36 chunks (~1.45 GB), 19:39:00 → ~21:50 (130.6 min). The run where the Vtrux was driven through
its OBD readiness monitors with `generator_runner.py` and **passed CA smog**.
**Artifacts / scripts:** `artifacts/smog-test/` (extraction + analysis scratchpads, per-signal CSVs).

---

## Test setup and bus architecture

`projects/vtrux/CANsmog/generator_runner.py` is a **man-in-the-middle CAN bridge** (laptop, socketcan):
it sits between two halves of the PT bus and forwards all traffic, but intercepts **`0x051`**
(`VCM_GenControl`, the VCM→GENE-MCU generator torque command, B1-B2 LE, centered 32768,
`<32768` = generating, `>32768` = motoring). When the operator has *armed* it and the VCM's command
sits in the idle band, it overwrites the torque bytes with its own `ramped_command` that climbs
toward a motoring (positive) value — backdriving the engine to keep it running for the monitors.

Script constants (as-read version):
`idle_torque_threshold_low = 32420`, `idle_torque_threshold_high = 32768`,
`coasting_torque_command = 33110`, ramp `+5`/frame up, reset to `32420` on each (re)engage.

**The Android logger taps the DLC, downstream of the laptop bridge.** So the `0x051` we capture is the
**post-modification** command: it shows the script's `ramped_command` whenever the script is overriding,
and the real HCU command only when the script passes it through (HCU command outside `32420..32768`).
We never directly see the HCU command while the script is actively overriding.

**Capture:** 4-channel BUSMASTER; only **ch3 = OBD bus** and **ch4 = PT bus** carry data (identified by
anchor IDs, not channel number). Signals used (source-of-truth = DBC, then `projects/vtrux/README.md`):

| Signal | ID / bus | Decode |
|---|---|---|
| Generator torque command (post-bridge) | 0x051 ch4 | `torque_input = B1 + (B2<<8)`; `rpm_ref = B3+(B4<<8)`; B0 status (0x0B) |
| GENE motor torque feedback | 0x471 ch4 | `(raw-32768)*0.125` Nm, `raw=B0+(B1<<8)` |
| GENE rotation speed | 0x054 ch4 | `raw-32767` rpm |
| Engine speed (real) | 0x0C9 ch3 | `((B1<<8)|B2)*0.25` rpm |
| Throttle position (TPS) | 0x3D1 ch3 | `B1 * 0.392157` % — see Task 3 caveat |
| DFCO (coast fuel cutoff) | 0x3D1 ch3 | B2 bit6 |
| OBD readiness reads | 0x7E0/0x7DF req, 0x7E8 resp | Mode 01 PID 01 / PID 41 |

GENE rpm tracks engine rpm 1:1 (peak 4946 vs 4945), confirming the generator is rigid-coupled to the crank.

---

## Task 1 — The backdrive ↔ HCU limit cycle

Read from the post-bridge `0x051` torque_input. Whole-session distribution (range 29968–34394):

- `<32420` (HCU strong-generating, passed through) — **38.7 %**
- `32420–32768` (idle band, script trigger window) — **41.1 %**
- `≥32768` (motoring / active backdrive override) — **20.2 %**

**The cycle** (example burst t≈4270 s; matches operator's description exactly):
1. HCU idles in-band + armed → script overrides, ramps `ramped_command` +5/frame from 32420 to the
   **33110 cap** (≈ **+45 Nm** motoring per 0x471). Engine RPM rises.
2. HCU fights with **negative (generating)** torque, ramping more negative. While the script overrides
   this is hidden behind the 33110 value.
3. The instant the HCU command crosses **below 32420** (`idle_torque_threshold_low`), the override
   condition fails → the script passes the HCU command through → torque_input drops to the real HCU value
   (−80 to **−250 Nm**). Engine is braked, RPM falls.
4. HCU reduces its negative command → value rises back above 32420 into the band → script re-engages,
   resets to 32420, ramps again.

**Quantified:**
- **123** disengage events (downward crossings of 32420); **34** full motoring-overshoot cycles
  (peak ≥32768 then drop <32420).
- Active "fight" pulses period **~1.5–2.5 s**; full overshoot cycles median **~7 s**; ramp duration
  median **~5 s**.
- **Asymmetry:** HCU braking (−80 to −250 Nm) ≫ script motoring (+45 Nm), so each HCU pulse wins
  decisively and RPM drops fast.
- Two regimes: **(a) active fight** — RPM saws as above; **(b) pinned** — when engine throttle is low,
  motoring stays at the cap and RPM gently decays with no fighting.
- Cycles occur in **bursts when armed**, clustered ~t=2400–6900 s, and stop after ~6900 s (see Task 4).

---

## Task 2 — The RPM "oops" (runaway to ~4945 RPM)

**Peak engine RPM = 4945** (GENE 4946) at **t≈5732.6 s** (min 95, ≈21:14). Clear outlier; next-highest 4020.

**Root cause — confirmed from the bus: experimental script limits.** Two distinct script-config eras
are visible in the override plateau and the disengage threshold:

| Era | Minutes | Override cap plateau | `[32325–32415]` histogram band |
|---|---|---|---|
| Original | 57–84 | **33110** | filled up to 32420 → threshold 32420 |
| **Experimental** | **95, 96, 104** | **33090** | **empty (0 samples)** → threshold lowered to 32320 |

The runaway (min 95) sits exactly in the 33090-cap era, which also shows the empty `[32325–32415]`
band. Both operator-recalled edits are therefore confirmed on the wire:
`coasting_torque_command` 33110 → **33090**, and `idle_torque_threshold_low` 32420 → **32320**.

**Mechanism:** with the disengage point lowered to 32320, the script kept overriding (motoring) even
while the HCU was commanding a **mild brake in the 32320–32420 band** — those braking attempts were
overwritten instead of passed through, so the protective passthrough never fired. The script held the
override pinned at 33090 (+42 Nm motoring) for ~7 s with no HCU brake, and with engine throttle still
partly applied (TPS ~14–30 %) the engine **free-revved 1800 → 4945 RPM in ~5 s**. With the threshold at
32420 (normal bursts), the same mild HCU brake would have tripped the passthrough and capped RPM.

**Arrest mechanism:** at the 4945 peak, DFCO was still 0 (fueling). The instant the VCM lifted throttle
(TPS 30→26→12 %), **DFCO engaged** (0x3D1 B2 bit6 → 1) and held through 5733–5742 while RPM bled
4937→1399. So the rev was arrested by **VCM throttle-lift → deceleration fuel cutoff**, not by the
generator (overridden) and not by a hard rev-limiter.

*(Note: overall torque_input max 34394 at t=3577 s is an unrelated HCU motoring passthrough, no spike.)*

---

## Task 3 — Engine throttle (TPS) and DFCO

**Signal note / resolved conflict:** TPS = `0x3D1` B1 `Throttle_Position` (`B1 × 0.392157 %`). Our own decode and
the `projects/vtrux/README.md` VCM-Gateway note agree this is the VCM-commanded
throttle proxy (TPS reflects the VCM command, not the driver's foot — driver foot is 0x592 on PT bus).
The EPRI table's "fuel rate" label for 0x3D1 is the **outlier** and is treated as incorrect here.
**Engine-off baseline = 29.4 %** (raw 75) — the VCM's rest/restart command at RPM=0, not real airflow
(consistent with an internal-only stall analysis, 26–29 % TPS at RPM=0).

- During active backdrive runs, TPS modulates up to **~99.6 % (WOT)**, repeatedly, throughout the test
  (t≈2400–7500 s). **Burst-modulated, not one continuous application** — WOT when running a monitor,
  low (7–15 %) between.
- **DFCO** (0x3D1 B2 bit6) active **18.3 %** of frames, 59 onset episodes. Fires on overrun/coast
  whenever the VCM lifts throttle at elevated RPM (it is what brought the 4945 spike down).
- **Wind-down:** last WOT runs at t≈7440–7530 s (TPS 99–100 %), then throttle tapers, RPM bleeds down,
  and by ~7740–7770 s the engine is at 0 RPM with **DFCO latched 100 %** and TPS settled at the 29.4 %
  rest value.
- **Relationship to monitors/oscillation:** the backdrive *oscillation* (full cycles) stops after
  ~6900 s, coinciding with the last required monitor completing (O2 at 6941 s). A couple of high-throttle
  runs continue after that but **without** the limit-cycle (steady runs, ~0 disengage events), then the
  full throttle wind-down. So: throttle stays applied (in WOT bursts) through the test and reduces at the
  end — the oscillation stops slightly *before* the final throttle wind-down, right when the monitors finish.

---

## Task 4 — OBD monitor readiness on the bus

**Monitor completion is internal ECM state — it is NOT broadcast on the bus.** It is observable *only*
via the scanner's polls: Mode 01 **PID 01** (readiness since DTC clear) and **PID 41** (this drive
cycle) — request on `0x7E0`/`0x7DF`, response on `0x7E8`. The operator's manual refreshes appear as the
PID 01 read timestamps (474 PID01 polls). Without the scanner there would be no readiness info on the
wire at all. The readiness bits clearing over time *are* the visible "monitors passing" signature, but
they surface only because/when polled.

**Readiness progression (PID 01, since-clear):**

| time | event |
|---|---|
| start | incomplete: **Fuel, Catalyst, Evap, O2 sensor** (Misfire, Components, O2-heater, EGR already complete) |
| t≈3500 s (~58 min) | **Catalyst** completes |
| t≈4016 s (~67 min) | **Fuel** completes |
| t≈6941 s (~116 min) | **O2 sensor** completes |
| end (last poll t≈6944 s) | only **Evap** incomplete |

Supported monitors (C=`11100101`): Catalyst, Evap, O2 sensor, O2 heater, EGR. Not supported:
Heated-Cat, Secondary-Air, A/C-refrigerant. **Evap monitor never completed**, but is **not required to
be ready for CA smog** (one incomplete monitor allowed), so the vehicle **passed**. Follow-on sessions
(`vtrux_20260617_215641`, `_220758`, …) contain zero PID01 reads — the operator had already confirmed
the pass.

**The bridge caused two faults later that night (analysed 2026-09-06, see
`battery-fault-codes.md` § June 2026 drive events).** At the 21:56:51 key-on the VCM never
received the BMS half of the bus (its 0x596 SoC echo stayed 0 while 0x410 was broadcasting),
never sent 0x400, flagged `0x617 B7=CA` and looped STBY/SHTDWN/WAIT4COOLING; a Via 12V cycle
was needed. At 00:21:26 on 06-18, while driving at 38 km/h, the bridge jammed outright (its
own 0x7E0 readiness polling stopped 0.27 s before the PT forwarding did); the BMS lost 0x400
and pushed `AC 10 01`. Neither event is a vehicle fault. The bridge needs a hard forwarding
deadline / bypass so that a stall degrades to a plain wire (same conclusion as the charge
interposer's failsafe note in `tools/interposer/README.md`).

---

## Open follow-ups

- Evap monitor completion was never captured (not needed for CA). If a future run targets it, watch the
  PID01 Evap bit and `0x649` evap-cycle signals together.
- The "smog-script stall" failure mode (backdriving while vehicle speed 0 → stall + fault) documented in an
  internal-only note is a separate pathological condition, not seen in this passing run.
