# Vtrux failed generator starts (no inhibitor involved)

**Completed:** 2026-10-04 (reviewing session of the generator inhibitor; findings reviewed and
approved for this note by the user the same day).
**Script and outputs:** `artifacts/natural_failed_start_scan.py`, `artifacts/natural_failed_start/`
(described in `artifacts/README.md`, "Natural Failed Engine Starts").
The inhibitor's own truck tests and its specification are internal-only;
the inhibitor firmware is in the public `canbus-esp-fw-vtrux` repo.

---

## Question

The owner has seen the truck fail to start normally: it cranks and does not catch. Does the CAN
history contain such starts, with no inhibitor involved? Are they linked to the evap-mode stalls?
And how do the VCM and the GM ECM respond? The answer bears on what a start blocked by the generator
inhibitor does to those two controllers.

## How a start looks on the bus

The engine has no starter motor. The VCM cranks it with the generator, which shows on the
powertrain bus as **positive `gen_torque_cmd` on `0x051`** (motoring). Once the engine runs, the
generator absorbs power and the command goes negative.

From the raw logs, a start sequence is two positive-torque segments: one of ~0.72 s, then a second
~0.83 s after it began.

## Method

1. **InfluxDB first pass.**
   - Scope: every Vtrux session with powertrain `0x051` (248 of 270, after excluding the six
     2026-06-17/18 rig sessions listed in `data-sources.md`).
   - Found every motoring episode (`gen_torque_cmd` > 100): 255 episodes, about 125 start
     sequences.
   - Classified each by whether the engine was running within 5 s:
     - generator speed (`GENE_RotSpd`, `0x054`) >= 600 rpm; or
     - the ECM's own `Engine_Speed` / `Engine_Run_Active` (`0x0C9`, OBD bus) where the capture has
       it.
2. **Raw logs.**
   - Every attempt in the three flagged captures was re-measured frame by frame.
   - Buses were identified by content. The OBD bus is the GM channel with `0x0C9` and none of the
     Vehicle-bus-only markers, because the Vehicle bus carries a VCM-substituted ~800 rpm.
3. **How the engine stopped before each attempt.**
   - The last time generator speed was >= 600 rpm marks the stop.
   - **Commanded stop:** the VCM's `gen_rpm_ref` drops to its engine-off null (< 0) after the stop.
   - **Stall:** the VCM keeps asking (>= 0) for at least 95 % of the 5 s after it.
   - A first version judged on the seconds *before* the stop. It called every stop a stall,
     including 4- and 11-minute engine-off periods, because the reference is >= 0 before any stop.
     It was replaced.

## Result: 8 failed start sequences, all recovered on the next attempt

| Capture | Date | Failed sequences (log time, s) |
|---|---|---|
| `vtruxgeneratoroverheattest.log` | 2026-03-18 | 5 (1012.9, 1265.1, 1428.8, 1749.6, 1983.3) |
| `vtrux_to980.log` | 2026-04-24 | 2 (976.7, 1191.0) |
| `vtruxanotherevaplogpart2.log` | 2026-03-04 | 1 (1445.1) |

Every failure has the same shape:

- **The engine turns but does not catch.**
  - The VCM cranks for 0.72 s, then for 1.40 s.
  - The generator shaft reaches 287-394 rpm in the first segment, and the ECM reports 46-288 rpm.
  - Afterwards both spin down to near zero.
- **The VCM retries 9.5 s later**, measured from the start of one sequence to the start of the
  next (8.67-8.68 s after the second segment began).
- **The retry caught every time**, within 5 s.

InfluxDB flagged no other session, and the raw re-measurement agrees with it on all 8.

### The VCM raised no fault

- **`0x617` B7** read `0xC8` (normal) throughout, from 2 s before each failed attempt to 12 s after.
  It never read `0xCA` (FAULT ACTIVE).
- **`0x644` B6** cycled `0x90` / `0xF0`, the same values it shows during a start that catches.

### The ECM's DTC broadcast showed nothing new

`0x772` (`Diagnostic_Trouble_Code_Information_Extended`, ECM) is present throughout all three logs.

- **Overheat test:** all zeros for the whole capture, through all five failures.
- **The other two logs:** each has a single code event, at 1012 s (evap log) and 2372 s
  (`to980`). That is minutes away from any failure. In both, the triggered byte goes to 1 for two
  frames and the payload then stays `00 11 05 75 00 5B 03`.
- These were read from raw bytes. The frames are DLC 7 against the DBC's 8, and the DTC number
  `0x0575` was not looked up.
- The broadcast is not a DTC read. What the ECM has stored is unknown.

### Not linked to evap

The evap flag (`0x649` `vcm_evap_active`) was **off** at every failure, around the crank attempt
and around the preceding stop. There is a link to the evap-mode stalls, but it runs the other way:

| Preceding stop | Sequences | Outcome |
|---|---|---|
| Stall, evap flag on (`vtruxanotherevaplogpart2` 803.9 s, the stall covered by an internal-only note; `vtrux_to980` 628.9 s) | 2 | **both caught first time** |
| Commanded stop, restart 12.2-53.2 s later | 8 | **all 8 failed once** |
| Commanded stop, restart 9.8-12.5 s later (overheat test) | 4 | caught |
| Commanded stop, restart after 242 s / 685 s (`vtrux_to980`) | 2 | caught |

Two caveats on the table:
- The `vtrux_to980` stall at 628.9 s is a mixed reading: the VCM asked for 83 % of the following
  5 s.
- The overheat-test restarts at 12.2 s (failed) and 12.5 s (caught) overlap at the boundary.

**Hypothesis, not established:** restarting a hot engine roughly 12-55 s after a commanded stop is
the condition that fails, which suggests a hot-restart window. The sample is 8 failures, 5 of them
in one stop/start test session, so it is not enough to call. Nothing here tests why.

## What this means for a start blocked by the generator inhibitor

- **VCM: the same response.**
  - A crank that does not catch is routine for it. It retries on a fixed ~9.5 s cadence with
    `0x617` normal.
  - That matches the six blocked attempts of 2026-09-06 (`truck_real3`): no fault, a retry every
    9.59 s. That figure came from a different tool.
  - Those blocked attempts mirrored B0. A blocked start with B0 held at `0x08` has not been seen on
    the truck.
- **ECM: a blocked start shows it less, not something different.**
  - In a natural failed start the engine turns, so the ECM sees crank signals and has every reason
    to fuel it.
  - In a blocked start the engine does not turn at all (0 rpm on `0x0C9` through blocked attempts 2-6,
    the five the truck test doc tabulates), so there is no crank signal.
  - No fault-code broadcast appeared after any natural failure, and the MIL stayed off after the
    blocked attempts (owner-observed).
  - A DTC read before and after the first blocked starts on the truck is what confirms nothing is
    stored.

The generator inhibitor spec (section 13, 2026-10-04) carries these as items to confirm at truck
bring-up rather than as risks.

## Limits

- **Coverage:** only the InfluxDB part of the corpus. The opt-in log subfolders (`other-logs`,
  `big-logs` and others) were not swept; the user judged the evidence sufficient.
- **Not checked:** the `0x051` B0 state byte across these sequences.
- **InfluxDB durations** are bounded by its on-change storage. Every duration and spacing above is
  from the raw logs.
