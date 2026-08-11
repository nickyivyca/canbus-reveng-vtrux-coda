# Via Warning Lamp (Amber Triangle) — CAN Signal Identification

The Vtrux dash carries a Via-added amber warning telltale. It is **not** part of the
original GM telltale system and is not driven by any GMLAN malfunction bit — the
GMLAN `*_Malfunction_Active` / `Warning_Indicator_Requested_Status` fields were
checked and stay clear even while the lamp is lit (see "What it is not" below).

**The lamp state is carried on the PT bus in `0x646` B7 bits[6:4].**

Investigated 2026-07-26/27 from the 2026-07-24 trip logs plus the parts-truck corpus.
Artifacts: `artifacts/lamp_bit_fault_logs.py`, `artifacts/lamp_timeout_partstruck.py`,
`artifacts/telltale_latch_scan.py`, `artifacts/telltale_bus_diff.py`,
`artifacts/telltale_intersect.py` and their `.txt` outputs.

---

## The signal

| Field | Value |
|-------|-------|
| CAN ID | `0x646` (PT bus, 1606 decimal) |
| Byte / bits | B7 bits[6:4] (mask `0x70`) |
| Rate | ~100 Hz, DLC=8 |
| Source | VCM (part of the VCU cluster `0x639`-`0x64B`; drops only on VCM B-connector removal — see `can-disconnect.md`) |

Three observed states:

| Value | Meaning |
|-------|---------|
| `0` | HV not up — either pre-start at key-on, or shut down by a major HV fault |
| `6` (bit6+bit5) | HV up, lamp **off** |
| `5` (bit6+bit4) | HV up, lamp **on** |

Bit6 is set whenever the HV system is up. Bit5 and bit4 are mutually exclusive, so
the practical encoding is **bit5 = normal, bit4 = warning**.

**B7 bit7 is a separate 1 Hz heartbeat** and must be masked off — the raw byte
alternates `0x60`/`0xE0` when normal and `0x50`/`0xD0` when the lamp is lit. Reading
the whole byte without masking makes the field look like it is toggling when it is not.

---

## Evidence

| Log | Truck | Lamp | `0x646` B7 bits[6:4] |
|-----|-------|------|----------------------|
| `vtrux_partstruck_exclamationindicatorforunpluggedpump.log` | parts | on (log named for it) | `5`, 100% |
| `vtrux_partstruck_testdrive.log` | parts | on | `5`, 100% |
| `vtruxpartstruck.log` (45 s) | parts | comes on | `6` -> `5` at t=30.99 s |
| `big-logs/vtrux_partstruck_charge.log` (9.5 h) | parts | comes on | `6` -> `5` at t=20.4 min, held 9.2 h |
| `vtrux_partstruck_startup_test.log` | parts | off | `6`, 100% |
| `vtrux_partstruck_evapfuseexperiment.log` | parts | off | `0`/`6` only |
| `vtrux_partstruck_testgeningarage.log` | parts | off | `0`/`6` only |
| `vtrux_partstruck_pumpplugin.log` | parts | off | `6`, 100% |
| `vtrux_ccmscan.log` | main | off | `6`, 100% |
| `vtrux_trailergainsetting.log` | main | off | `6`, 100% |
| `generator-on-then-off.log` | main | off | `6`, 100% |
| `vtruxgeneratorpumpunplug.log` | main | off | `6`, 100% |
| `vtruxscottsvalleydrive.log` | main | off | `6`, 100% |
| `vtrux_mysterybox_unplug.log` | main | off | `6`, 100% |
| `vtrux_transfer_case_test.log` | main | off | `6`, 100% |
| `vtrux_trailerbrakeleverpull.log` | main | off | `6`, 100% |
| `vtrux_shifter_disconnect.log` | main | off | `6`, 100% |
| 2026-07-24 trip (8 h, main truck) | main | on 21:36:04-21:39:41 | `5` for exactly that 217.7 s, `6` for the other ~8 h |

Nine healthy main-truck logs sit at `6` without exception. Both an off->on transition
(parts truck, pump timeout) and an on->off clear (2026-07-24 key cycle) were captured.

---

## Behaviour during major HV faults

**The field does not toggle during major HV faults, and never reaches `5`.** It goes to
`0` and stays there, tracking the HV shutdown.

| Log | Fault | Behaviour | Lamp-state flips |
|-----|-------|-----------|------------------|
| `vtruxisolationtest.log` | isolation fault | `6` -> `0` at t=49.83 s, held to end | 0 |
| `vtruxinterlocktest.log` | interlock fault | `6` -> `0` at t=68.2, `6` at 211.2, `0` at 245.7 | 0 |
| `vtruxinterlocktest2.log` | interlock fault | `6` -> `0` at t=30.1 | 0 |
| `vtruxisolationtestrecovery.log` | recovery | `0` -> `6` at t=27.9 | 0 |
| `vtruxunplugpumpthenhvbatterylvconnector.log` | BMS LV pull | `0`/`6` | 0 |
| `vtrux_no_gene_inv_fuse.log` | gene inverter fuse out | `6` throughout | 0 |
| `vtruxwoodwardbconnectordisconnected.log` | VCM B-conn off | no `0x646` frames at all | n/a |

Timing is tight against the BMS fault state in `vtruxisolationtest.log`:

```
t=49.700  0x410 B1  BF -> B0    isolation fault trips (lower nibble clears)
t=49.833  0x646 field 6 -> 0    133 ms later
t=49.846  0x410 B1  B0 -> F0
t=49.900  0x410 B1  F0 -> C0
t=59.110  0x410 B1  C0 -> CF    fault latched
```

**Consequences for analysis:**

- A blinking lamp is **not** encoded here. Absence of toggling does not mean the lamp
  was steady during those faults — it means `0x646` is not what drives a blink.
- Field `0` is ambiguous on its own: it reads the same at a normal pre-HV-up key-on as
  it does after a fault shutdown. Pair it with `0x400` B0 or `0x410` B1 to tell those
  apart.
- `vtrux_no_gene_inv_fuse.log` stays at `6` despite a missing generator inverter fuse,
  so field `5` does not cover every fault the truck can have. Consistent with the
  observed vehicle behaviour (that fault does not light the lamp).

This is consistent with `interlock-bitfields-analysis.md`, which already listed
`0x646` B7 among the uncharacterized bytes that change in every fault event.

---

## Pump-missing lamp timeout — approximately 20 minutes, timer-based

The parts truck has its PE coolant pump missing (`0x18FF0320` has **zero frames in all
20 parts-truck logs**), and the lamp comes on only after a delay rather than immediately.

Measured in `big-logs/vtrux_partstruck_charge.log` (9.5 h overnight charge):

```
t=  0.3 min   charge starts (0x18FFD7C0 appears)
t= 20.4 min   0x646 field 6 -> 5    LAMP ON, 20.1 min after charge start
t=570.3 min   brief 5 -> 6 -> 5
t=571.4 min   5 -> 6                charge ends
```

Bounded from the other side by `vtrux_partstruck_pumpplugin.log`: 16.6 min from a single
key-on with no assertion. **So the delay is between ~16.6 and ~20.1 minutes.**

Every other parts-truck log is consistent — none has a continuous key-on interval longer
than ~13 min while showing the lamp off, so none contradicts the timeout.

**It is a timer, not a thermal threshold.** Across the assertion in the charge log the Bel
charger ambient temperature (`0x18FFD5C0` B4-B5, 0.1 degC) rises smoothly and
monotonically with no inflection, and `INVCH_Bdc_TempPercent` stays at 0 throughout:

| t (min) | Bdc ambient | TempPercent |
|---------|-------------|-------------|
| 0.3 | 12.8 C | 0 |
| 10.3 | 20.7 C | 0 |
| **20.3** | **24.9 C** | **0** (lamp asserts at 20.4) |
| 31.4 | 29.7 C | 0 |

---

## What it is not

Checked and ruled out, so these are not worth re-testing:

- **GMLAN is not the source.** The Via lamp is a Via system, unrelated to the original GM
  telltale set. Across the whole 2026-07-24 trip `0x772` `Warning_Indicator_Requested_Status`
  is 0 in every frame (only the known permanent ECM P0621 is broadcast, src `0x11`,
  DTC# 1397); `0x3D1` B0 is constant `01` and `0x4C9` B0 constant `40`, so no
  `Engine_`/`Transmission_Non_Emissions_Related_Malfunction_Active` ever sets; and every
  `*_Indication_On` bit in `0x4D1 Engine_General_Status_5` — including
  `Check_Fuel_Filler_Cap_Indication_On` and
  `Engine_Diagnostic_Trouble_Code_Present_Indication_On` — is 0 all day.
- **`0x65B` (HCU DTC) has zero frames** across the entire 2026-07-24 trip, so the lamp does
  not require an HCU DTC broadcast.
- **Not a "shifter input lost" flag.** In `vtrux_shifter_disconnect.log` the shifter position
  box is physically unplugged for ~9 s and the field stays at `6` for the whole log. A clean
  sustained loss does not assert the lamp (the VCM simply reports Neutral — see
  `shifting-transfer-case-investigation.md`).

---

## Open questions

- Exact timeout value between 16.6 and 20.1 min, and whether the key-on timer and the
  charge-start timer are the same timer.
- What distinguishes the conditions that assert the lamp from those that do not (missing
  PE pump does; missing generator inverter fuse does not).
- How a **blinking** lamp is encoded. `0x646` carries steady state only; during major HV
  faults the field goes to `0` rather than oscillating.
- Whether the IPC is driven directly from a VCM message on the Vehicle bus, with `0x646`
  merely reflecting internal VCM state. The Vehicle bus was not captured on 2026-07-24.
