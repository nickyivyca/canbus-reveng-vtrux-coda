# Vtrux Battery Pack Thermals & Cooling

Investigation into the A123 pack cooling system and its CAN signature. Kicked off
2026-07-14 when the driver heard the battery cooling fan come on **for the first
time** during an evening charge session.

**Primary log:** `CANLogs/VtruxLogs/vtrux_20260714_161319_T*.log` — one contiguous
Android capture, 89 chunks (`T0`–`T88`), ~16:18–22:47 on 2026-07-14, single
500 kbps channel (Innomaker). Covers: 4pm charge -> drive -> idle -> drive ->
long evening charge (fan heard) -> final drive.

**Analysis artifacts:** `notes/artifacts/battery_fan_signature.py` (phases 1–5),
`battery_fan_phase6.py`, `battery_fan_phase7.py`, `battery_fan_phase8.py`, plus
cached CSVs `battery_fan_04{10,30,40}.csv`.

---

## Cooling Hardware (from Via docs)

Per the Via LV fuse/relay inventory (`notes/via-docs/via-docs.md`), the 12V side has
dedicated cooling actuators:

| Fuse / Relay | Name | Rating | Likely role |
|---|---|---|---|
| F12 / K10 | FAN 1 | 30A | Battery / cooling fan |
| F13 / K9 | FAN 2 | 30A | Battery / cooling fan |
| K12 | ESS COOLER | — | ESS (HV battery) cooler relay |
| F14 | EPT W.PUMP | 30A | PE-loop coolant pump (EMP WP29) |
| F29 | PTC PUMP | 10A | PTC heater coolant pump |

"ESS" = Energy Storage System = the HV battery. The pack cooling design is understood
to use **Peltier (thermoelectric) modules** coupling the pack's internal air to the PE
water loop; the pack enclosure is otherwise sealed (no direct air exchange with outside).
Whether the Peltiers still function is unknown — see Outstanding Tasks.

---

## Session Timeline (2026-07-14)

Segmented by pack current `bcm_ibat` (0x410, charge = ibat > +5 A):

| Phase | Time | SoC | Notes |
|---|---|---|---|
| Charge #1 (4pm) | 16:18–17:13 | 35 -> 63% | **fan never engaged** |
| Idle | 17:13–17:56 | ~63% | |
| Drive | 17:54–18:39 | 63 -> 45% | short + longer drive |
| **Charge #2 (evening)** | 18:39–21:56 | 45 -> 100% | **fan heard**; engaged 20:37 |
| Final drive | 21:59–22:47 | 100 -> 36% | |

---

## Confirmed Findings (measured)

### The cooling-active CAN signature
Three independent signals switch together at **20:37:04** and hold until charge-end
**21:55:53** (79 min), and are **completely absent from the 4pm charge**:

1. **0x508** — a BMS-range message that is *only broadcast while cooling is active*
   (payload B6/B7 constant = 100; presence is the signal). Not decoded in any DBC.
2. **0x506 B0 bit 5** — byte steps 0x0F <-> 0x2F; sustained-high runs match 0x508
   presence to the second.
3. **12V load step** — DCDC LV output current (`DCDC_LV_Curr`, 0x18FFD6B3 B2-B3,
   x0.05 A) steps **~6 A -> ~100 A** at 20:37:04, at a regulated ~14.3 V (so real
   load, not battery charging). Reverts at 21:55:53.

Mean 12V load by phase (confirms cooling on/off):

| Window | 12V load | Cooling |
|---|---|---|
| 4pm charge (16:20–17:10) | 5.9 A | off entire charge |
| Evening charge, first ~2 h (19:00–20:35) | 5.3 A | off |
| Evening charge (20:39–21:55) | 100.6 A | **on** |

### Cooling-on windows (0x508/0x506-bit5) and drive overlap
| Window | Context | 12V step at ON edge |
|---|---|---|
| 17:58–18:31 | drive (89% of drive covered) | +103 A |
| 20:37–21:56 | **evening charge top** | +95 A |
| 21:59–22:47 | final drive (99% of drive covered) | +172 A |

Cooling ran during **both drives** as well as the evening charge — the driver simply
did not notice it over driving noise; the quiet garage charge was the first *audible*
occurrence.

### Cell temperature at each cooling edge (`bcm_cell_tmax`, 0x430)
| Edge | tmax | tmin |
|---|---|---|
| ON 17:58 (drive) | 38.0 | 36.0 |
| OFF 18:30 (mid-drive!) | 36.5 | 36.0 |
| ON 20:37 (charge) | 39.5 | 36.5 |
| OFF 21:55 (charge end) | 41.5 | 37.0 |
| ON 21:59 (final drive) | 41.5 | 37.0 |
| OFF 22:46 | 41.0 | 35.5 |

The 4pm charge peaked at **37.5 °C** and never triggered. During the first drive,
cooling switched **off at 18:30 while the drive continued to 18:39** — i.e. it dropped
out when the pack cooled, not when driving stopped.

### Signals ruled out as the trigger
- **`bcm_cool_req`** (0x410 B6 bit5) is **on ~100% of the session** — a standing
  cooling-loop *enable*, not the fan trigger.
- **Cell balancing** (`bcm_balancing`, 0x440 B7) fires only **21:46–21:58** (top of
  charge, 100% SoC) — too late/brief to explain the 20:37 activation. Not the trigger.

---

## Working Model (cross-validated across 30 sessions)

> The 0x508 / 0x506-bit5 state = **"battery cooling package active"**, driving the ESS
> COOLER (K12) and/or FAN 1/FAN 2 (K9/K10). Engagement rule:
> **HV path active (charging OR driving) AND cell tmax crossing ~40 °C ON, dropping
> out around ~36.5 °C OFF (thermostat with hysteresis).**

This explains every observation:
- **4pm charge never triggered** — pack peaked at 37.5 °C, well under the ~40 °C ON.
- **Evening charge triggered it** — the long full charge warmed the pack across ~40 °C
  at 20:37 (ran, audible in a quiet garage).
- **Drives run cooling from ~37 °C** — hysteresis tail: the pack crossed 40 °C earlier
  and cooling stays latched on while tmax decays toward the ~36.5 °C off-point; sensor
  lag under bursty drive heat likely contributes.
- **OFF at 21:55 at 41.5 °C** (hottest point) = charge-end opened the HV path -> the
  HV-active gate dropped cooling despite high temp; it resumed 3 min later at drive
  start.

The **~95 A** 12V step is far more than one fan (~1.3 kW), so it is likely the **whole
cooling package** (both fans + coolant pump, possibly Peltiers) energizing together,
not a single fan. Device-level attribution is unconfirmed on a single-channel log.

**Confidence:** activation events, the ~40 °C ON threshold, and the 12V correlation are
all confirmed by cross-session measurement (see below). The ~36.5 °C OFF point and the
driving-vs-charging threshold difference are hysteresis/sensor-lag effects, well
supported but not to 0.5 °C precision.

---

## Cross-Session Validation (confirmed 2026-07-15)

Raw-log scan of **30 gap sessions** (>20 MB, 2026-04-25 → 2026-07-14; ~89k 1 Hz
samples). Run directly against the android logs (0x508/0x506 are raw bytes, not in any
DBC or in InfluxDB). Artifacts: `battery_cooling_xsession_raw.py`,
`cooling_xsession_samples.csv`; InfluxDB current-data probe:
`battery_cooling_influx_check.py`.

- **0x506 B0 bit5 ≡ 0x508 presence: 99.9 %** agreement across all sessions — the two
  are the same cooling state everywhere.
- **P(cooling | cell tmax), CHARGING only:** 0–1 % below 39.5 °C, then **100 % at
  40.0 °C** and above. A clean step -> **~40 °C ON threshold**.
- **DRIVING only:** on-behavior from ~37 °C (77 % at 37.0 °C) — hysteresis tail (see
  model). Below 36 °C never on; above 40 °C always on, in both modes.
- **12V load (`DCDC_LV_Curr`) by state** — the ~+95 A step is universal:

  | Mode / state | n | median 12V |
  |---|---|---|
  | Charging, cooling OFF | 39,951 | 6.1 A |
  | Charging, cooling ON | 5,906 | 100.7 A |
  | Driving, cooling OFF | 15,331 | 51.7 A |
  | Driving, cooling ON | 3,488 | 142.8 A |

- **Per-session:** every session that stayed below ~36 °C never triggered cooling;
  every session reaching 38–41 °C did. First-cooling-ON tmax clustered at 38–40 °C
  (drive edges lower per hysteresis).

**InfluxDB note:** the current DB (latest data 2026-04-24) has these BMS/DCDC signals in
only **1 of 71** sessions, so the check could not be done there — it was done on raw
logs instead. A re-upload of the gap (decoded with `epri-pt-bus.dbc`, `--raw` for the
0x506/0x508 bytes) is deferred until findings are locked.

---

## The conditioning telemetry is PACK-SPECIFIC (added 2026-08-09)

### main-orig does not have it; parts-orig and Truck 3's pack do

The whole ID group that reports conditioning — `0x370`–`0x375`, `0x506`, `0x507`,
`0x50F` — is **present or absent as a unit**, and which it is depends on the pack:

| Pack | Logs checked | Group present? |
|------|--------------|----------------|
| **main-orig** | **35** (main truck 2025-06→2025-08, parts truck 2026-04→2026-05) | **0 of 35** |
| parts-orig | 7 | all |
| Truck 3's pack | 1 | yes |

Every main-orig log has a healthy `0x051` PT-bus anchor count (2,408–27,887 frames), so
the bus was definitely captured — this is not a logging filter. It **follows the pack
across both trucks**.

**The 12V actuator side is common to both packs.** F12/K10 (FAN 1), F13/K9 (FAN 2) and
K12 (ESS COOLER) are fuse-box-side and were not touched during the 2025-12-09 pack swap
(owner-confirmed; the pack itself contains only HV fuses). So the difference is entirely
**pack-side** — consistent with T2 in `can-disconnect.md` dropping the whole group when
the HV battery LV connector is pulled.

### What the group actually contains

| ID | Role | Evidence |
|----|------|----------|
| `0x506` B2 / B3 | **cold side / hot side pair** | At the cooling edge B2 **falls** ~5 °C (39–42 → 35–36) while B3 **rises** ~12 °C (46–50 → 58–61). Opposite directions = thermoelectric. Cells move the other way again (0x430 tmax 35.5–36.5 → 40.5–41.0). |
| `0x506` B0 bit5 | cooling-active flag | already documented above |
| `0x507` B0 / B1 | **rebroadcast of `0x430`** | floor(cell_tmin) / floor(cell_tmax), 100% over 8,149 samples |
| `0x370`–`0x375` | conditioning-side sensing | read above cell temp, **rise** when cooling engages, and the payload expands (B2/B3/B5/B7 populate) only while conditioning is active |

**This partly answers the "do the Peltiers still function?" question in Outstanding
Tasks — on parts-orig, yes:** the hot/cold split at the cooling edge is direct evidence
the thermoelectric hardware is doing thermodynamic work, not merely being energised.

> **Scaling caveat.** `raw − 40` gives plausible values for `0x506` B1/B2/B3 (35–61 °C)
> but implausible ones for `0x370`–`0x375` (B0/B1/B4/B6 reach 64–85 °C under cooling;
> B3/B7 reach 108–121 °C). Some bytes may use `raw × 0.5 − 40` as `0x430` does — under
> that scale B3/B7 land at 34–40.5 °C, squarely in the cell range. **Absolute
> temperatures in this group are provisional. The directions of movement are not.**

### Open: can main-orig request cooling at all?

**Untested, and now confirmed untestable from existing data.** Full-corpus scan
(`artifacts/mainorig_cooling_test.py`, 2026-08-09):

| Pack | Logs | Peak `cell_tmax` | Logs reaching 38 °C |
|------|------|------------------|---------------------|
| **main-orig** | **108** | **31.5 °C** | **0** |
| parts-orig | 909 | 43.5 °C | 113 |

main-orig has **never once approached the engagement threshold** in anything captured, so
we cannot say from CAN whether it would engage cooling. On parts-orig the test behaves as
designed — every hot log carries the 12 V step (97–235 A against a ~6 A baseline).

**Do not read this as "main-orig runs cooler."** The datasets are not comparable:
parts-orig's hot logs are dominated by one long 2026-07-14 session, while main-orig's 108
logs skew to 2025 summer and 2026 spring. main-orig may simply never have been logged
working hard in heat.

The 12V step (`DCDC_LV_Curr`) is the way to test this without the missing telemetry —
it comes from the Bel DCDC on J1939 extended IDs, independent of the pack, and is
present on both packs. If a main-orig log ever crosses ~38 °C with no ~+95 A step, that
is direct evidence the pack has no working conditioning. Owner reports never having
heard the fan on main-orig.

**This has no bearing on the main-orig charge fault** (see
`specific-trucks/before-battery-swap-failed-charge-analysis.md`): all five escalations
occurred at `cell_tmax` 26.0–30.0 °C, 8–12 °C *below* the engagement threshold. Cooling
would have been idle regardless, so its absence cannot explain those faults.

Scripts: `artifacts/temp_mirror_test.py`, `artifacts/mainorig_cooling_test.py`.

---

## Outstanding Tasks

1. ~~**Cross-session threshold validation.**~~ **DONE 2026-07-15** (raw-log scan, 30
   sessions) — see Cross-Session Validation above. ON threshold refined to **~40 °C**
   (charging-clean). InfluxDB re-upload of the gap (with `epri-pt-bus.dbc` + `--raw`)
   deferred until findings are locked, then re-run `battery_cooling_influx_check.py`.

2. ~~**12V-step correlation across all fan-on events.**~~ **DONE 2026-07-15** — every
   cooling-on state carries the ~+95 A `DCDC_LV_Curr` step in both charging and driving
   across all 30 sessions (table above). The 12V step is a reliable independent cooling
   detector.

3. ~~**Whole-pack thermal-model feasibility + lumped model build.**~~ **DONE 2026-07-15**
   — see "Lumped Thermal Model" spec + results above. Lumped 0-D model built and fit;
   ambient (`ECM_OutsideAirTemp` 0x4C1) and PE-loop sink (`DCDC_HW_Temp` 0x18FFD6B3 B6-B7)
   identified and usable.
   - **Still open — spatial resolution:** only pack-aggregate `tmax`/`tmin` today. Per-
     module *structure* exists (0x370–0x374 = 5 IDs = 5 modules) but reads as per-module
     **voltage** (rises with SoC), not temperature. Decoding a per-module *temperature*
     channel (if one exists) is the gate for the **exhaust-corner** question — we cannot
     currently attribute `tmax` to a specific corner. Speculative decode work.

4. ~~**Peltier liveness test.**~~ **INVESTIGATED, INCONCLUSIVE 2026-07-15** — see verdict
   above. No measurable pack cooling in any observable window, but confounded by a
   chronically-hot sink; no clean (cool-sink + warm-pack + cooling-on) window exists
   (structural). Cannot be resolved from passive CAN logs. Resolution paths below.

5. **[NEXT] Peltier resolution — controlled test.** Arrange a window with a **warm pack +
   pre-cooled PE loop + cooling forced on**, and log. Hard because cooling is HV-gated
   (drops when parked). Ideas: log the *first minutes* of a drive/charge started with a
   warm pack after the loop has cooled (loop lags pack on cooldown?); or find whether
   cooling can be commanded independent of HV. A working Peltier would show clear pack
   cooling; a dead one would not.

6. **Peltier current identification.** Try to isolate the Peltier's share of the ~95 A
   12V package load (vs FAN 1/FAN 2 + coolant pump). If the package current **modulates
   with the pack/sink ΔT** or pack temp, that implies a live, thermostatically-driven
   Peltier; a flat on/off load suggests fans-only (Peltier unpowered/dead). Look at
   `DCDC_LV_Curr` fine structure during cooling-on across temperatures.

7. **Exhaust heat contribution — ATTEMPTED, INCONCLUSIVE 2026-07-15.** Exhaust runs the
   rear-right corner behind a heat shield; loop cold-plate is front-right. Tested on the
   20260714 final drive's engine-on hill climb (22:22:20–22:32:01, 9.7 min, peak
   3595 RPM). **No exhaust signature found:** the tmax−tmin spread did widen (2→5 °C)
   around the event, but driven by **tmin falling, not tmax rising** — the wrong shape
   for corner heating. Cause was the loop flipping from source to sink (it cooled
   63→30 °C during the drive, crossing below the pack ~22:10, so the front-right
   cold-plate began *extracting* heat) plus reduced pack load when the generator took the
   hill. tmax showed no bump during or after engine-on. Blockers: 9.7 min ≪ pack's ~2 h
   lag; loop dynamics dominate/mask it; and **aggregate tmax/tmin can't localize a corner
   the exhaust heats unless it becomes the single hottest cell.** Real unlock =
   per-module temps (task 3 spatial). Artifact: `pack_exhaust_heating.py`.

8. ~~**Per-module temperature decode.**~~ **DONE 2026-07-15 — NEGATIVE: no per-module
   temps exist on the bus.** Correlated every BMS-range byte (0x300–0x5FF) against
   `bcm_cell_tmax` over the another_M0 winter session, then discriminated temp-vs-voltage
   on the 20260714 final drive (SoC crashed 100→36 with tmax flat — voltage channels
   crash with SoC, temp channels stay flat). Findings:
   - **0x370–0x374** (5 IDs = 5 modules) = **per-module cell VOLTAGE** (B0/B1/B4/B6 track
     SoC, r≈0.8), not temperature.
   - **0x507** = a **redundant copy of aggregate tmax/tmin** (B1=tmax, B0=tmin, ×0.5,
     r_tmax 0.91), not per-module.
   - No other byte tracks the thermal trend; **no multiplexed temp** (no counter+value
     structure, no byte cycling in the temp raw band).
   - **The BMS broadcasts only pack-aggregate tmax/tmin (0x430).** No per-module/per-cell
     temperatures anywhere. Note: the tail correlation alone is confounded (post-charge
     cell-voltage relaxation falls like cooling); the discharge test is what settled it.
   - **Consequence:** the exhaust-corner question and any *spatial* thermal model are
     **permanently blocked from CAN** — only the 2-point tmax/tmin spread is available,
     and it is dominated by the front-right loop cold-plate. Artifacts:
     `module_temp_hunt.py`, `module_temp_discriminate.py`.

> **Pack-swap caveat (applies to tasks 3–8).** The dataset spans a **battery swap**
> (see `notes/after-battery-swap-charge-fail-analysis.md`). The **old pack and new pack
> may have different amounts of Peltier function (if either has any)**. Any cross-session
> thermal/Peltier analysis MUST **segment by pack** (before/after the swap date) and not
> pool them — otherwise a working pack and a dead-Peltier pack would average into a
> meaningless middle. Establish the swap date and tag each session's pack first.

---

## Lumped Thermal Model (v1 spec)

**Purpose:** quantify the pack heat balance and use it to test **Peltier liveness** —
active heat rejection (working heat pump) vs fan-only internal air stirring (dead
Peltier).

**Available signals** (per session, ~1 Hz): pack temp `bcm_cell_tmax`/`tmin` (0x430,
0.5 °C quantized); heat driver `bcm_ibat` (0x410); cooling state 0x506-bit5/0x508 and
`DCDC_LV_Curr` (0x18FFD6B3); sink temp = PE-loop / DCDC HW temp (0x18FFD6B3 B6-B7,
signed 0.1 °C); ambient = `ECM_OutsideAirTemp` (0x4C1, 0.5 °C/ct −40, OBD bus — present
only in multi-bus captures).

**Single-node lumped model:**

```
C · dT/dt = a·ibat²  +  P0  −  UA_passive·(T − T_amb)  −  Q_active
```

- `T` — model both `T_mean ≈ (tmax+tmin)/2` (bulk) and `tmax` (hottest cell); track
  spread `S = tmax − tmin` separately.
- `a·ibat²` — Joule (I²R) heating; `P0` — parasitic/charge-inefficiency offset.
- `UA_passive·(T − T_amb)` — passive loss to ambient/enclosure.
- `Q_active` — active cooling, nonzero only when 0x506-bit5 = 1.

**Peltier physics (heat pump).** The cooler can move heat from the pack (cold side) into
a **hotter** PE loop, and can drive the pack **below** ambient and below the sink, up to
the module's **ΔTmax**. A hot loop lowers COP and pumping capacity (and shrinks
achievable ΔT) but does not disable it unless `(T_sink − T_pack) > ΔTmax`. Hence:
- **Working Peltier:** `Q_active > 0` (reduced when the PE loop is hot, but nonzero) —
  produces measurable heat removal beyond passive; can pull `T` toward/below `T_amb`.
- **Dead Peltier (fan only):** `Q_active ≈ 0` net to outside; the fan only redistributes
  internal air, so **spread `S` shrinks** while the mean tracks the passive curve.

**Fit / test procedure:**
1. Bin each session to ~60 s means (tmax is 0.5 °C quantized — derivative needs
   smoothing). Compute `dT/dt` per bin.
2. **Fit** `{1/C, a, P0, UA_passive}` on **cooling-OFF** samples by linear regression of
   `C·dT/dt = a·ibat² + P0 − UA·(T − T_amb)`.
3. **Test** on **cooling-ON** samples: residual `R = (dT/dt)_actual −
   (dT/dt)_passive_pred`; active removal `Q_active = −C·R`.
   `Q_active > 0` significant → Peltier working; `Q_active ≈ 0` → fan-only / dead.
4. **Corroborate** with spread `S`: fan-only predicts `S` shrinks with ~zero mean
   removal; working Peltier shows mean removal (and `S` may shrink too).

**Segmentation:** all 30 gap sessions are the **post-swap (new) pack** — fit per pack,
never pool old/new (Peltier function may differ). Old-pack test needs pre-2026 logs;
truck identity separable via odometer (0x625).

**Limitations:** tmax 0.5 °C quantized; `C` unknown (removal is relative unless
calibrated — but relative is enough to distinguish working vs dead); OAT has mild
afternoon heat-soak; the hottest cell (tmax) may be a local hot-spot not obeying bulk
I²R, so `T_mean` is the primary model target with tmax as secondary.

Artifacts: `battery_thermal_model.py` (build + fit + Peltier test).

---

## Lumped Model — Results & Peltier Test (2026-07-15)

Built and fit on the 30 post-swap gap sessions (`battery_thermal_model.py`,
`thermal_model_samples.csv`).

**Passive fit** (cooling-OFF bins): `dT/dt = 0.28·(ibat/100)² − 0.0025·(T−Tamb) +
0.055` °C/min. Passive loss is very weak — **time constant several hours (~6–9 h)**; the
heat balance is dominated by I²R input, and the pack barely sheds heat passively (huge
thermal mass, only ~10 °C above ambient).

**The regression-based Peltier residual is unreliable — discarded.** Cooling only
engages when hot, so cooling-ON bins cluster at ~38 °C while the OFF training data sits
at ~28 °C. The passive model is unconstrained at high T (a matched refit diverged to a
non-physical −3 °C/min). Do not trust the regression residual for the Peltier call.

**Model-free matched test (the trustworthy one)** — raw decay rate at matched T and
near-zero current (|ibat|<15 A), cooling-ON (hysteresis tail) vs cooling-OFF
(parked-hot):

| T band | OFF dT/dt | ON dT/dt |
|---|---|---|
| 36–38 °C | +0.007 | −0.009 |
| 38–40 °C | −0.018 | +0.009 |

**No detectable difference** — both flat within the ±0.02 °C/min quantization floor
(tmax is 0.5 °C-quantized). The pack does **not** cool measurably faster with cooling
ON. **Spread (tmax−tmin) also does not shrink** during cooling (dS/dt ≈ +0.015 both
states), so it isn't even doing obvious internal air-mixing.

### Peltier verdict: no useful cooling observed; liveness INCONCLUSIVE

- **Observed:** cooling provides no measurable pack heat removal in any window.
- **But confounded:** whenever cooling runs, the PE-loop sink is **hotter than the pack
  — by 12.9 °C on average** (loop ~60 °C vs pack ~41 °C during charge). A fully-working
  Peltier pumping ~19–22 °C uphill would *also* show ~no net pack cooling here, so a null
  result cannot distinguish dead vs alive-but-outmatched.
- **No clean window exists to break the tie.** Mining all sessions: only 29/159
  cooling-ON bins have the sink cooler than the pack, and **28 are one confounded
  stretch** (the 20260714 final drive — night ambient crashing 36→18 °C, drive current
  swinging −114→+12 A, dT/dt noise −0.38…+0.25). Unusable.
- **Why it's structural, not bad sampling:** cooling is HV-gated; HV-active (charge/
  drive) heats the PE loop (charger/DCDC/inverter dump into it, as does the Peltier
  itself); so the sink is hot exactly when cooling is demanded. Cool-sink + warm-pack
  only occurs in the brief post-activity tail, coincident with falling load/ambient.

**Actionable takeaway** (independent of Peltier health): the pack cooling system's own
heat sink is hot precisely when cooling is demanded, so **pack cooling is likely
ineffective by design during charge/drive.** This matches the observation that the pack
net-heats through the whole evening charge despite cooling running.

---

## Passive Loop→Pack Heating & Winter Pre-Conditioning (2026-07-15)

Prompted by a proposed mod: remove the Peltiers, run the cold-plate as a raw water/air
exchanger, and force the fan on in winter to dump PE-loop waste heat into a cold pack
(LFP charge-acceptance + longevity). Artifacts: `winter_loop_heat.py`,
`pack_corner_heating.py`.

**"Never runs in winter" = the threshold, not a fault.** Cooling is HV-gated and trips at
cell tmax ~40 °C, so a cold pack never triggers it. Confirmed on two Jan post-swap
charges (cooling 0.0 % of both).

**Loop→pack heating gradient is real, year-round, and *larger* in winter:**

| Session | pack temp | PE loop | loop−pack (charging) |
|---|---|---|---|
| charge_M0 (Jan 16) | 20→24.5 °C | 18→43 °C | +15.6 °C avg |
| another_M0 (Jan 23, cold start) | 12→23.5 °C | 21→44 °C | +22.4 °C avg (max +26) |
| 20260714 (summer, pre-cool) | 34.5→40 °C | 40→64 °C | +15.2 °C avg |

Even at ~14 A charge, the Bel's ~500 W fixed loss holds the loop ~20 °C above a cold
pack. Full-power charge or a drive pushes it far higher.

**No hidden heating mode.** During the winter charges the 12V load (`DCDC_LV_Curr`)
stayed flat at the ~4–6 A baseline — never the ~95 A cooling-package step. So the
+11.5 °C pack warming (another_M0) was **passive** — loop heat conducted through the
cold-plate with nothing powered. The reversible Peltiers are wired for cooling only; the
winter-heating direction is unused.

**Corner heating confirmed (spread signature).** Heat enters at one corner (the loop
cold-plate, front-right of pack), so tmax leads tmin and the tmax−tmin spread widens
while heating, then collapses as the pack homogenizes:
- another_M0 (winter): spread 0.5 → **5.5 °C** during charge, → 3.0 °C after.
- 20260714 (summer, pre-cool): spread 0.5 → ~5 °C, same shape.
At 14 A, internal I²R cannot make a 5 °C gradient — so it is external, localized heat.

**Charge→idle homogenization (another_M0), no drive involved:** loop peaked 44 °C at
h4.7 (peak charge current); pack tmax/spread peaked ~2 h later (h6.4–6.8) — the pack
lags the loop by **~2 h** (thermal mass). After charge stopped, the loop cooled
**passively** (44→34 °C, no fan, no drive — matches "never hear the radiator fan while
charging"), the corner heat input faded, and internal conduction evened the pack out
(tmax fell faster than tmin). ibat never went below −5 A — it was charge→idle, not
charge→drive.

**Ambient — UNVERIFIED in winter (correction).** Winter logs are PT-bus only (no ECM
OutsideAirTemp); the Bel 0x18FFD5C0 B4-B5 is a *component* (BDC) temp, not air. Earlier
"~20 °C garage" was wrong (truck is not charged in a garage). Best inference: the pack
cold-soaked to 12 °C and the Bel floored at 21 °C, so true ambient was likely **≤~12 °C**.
That means the pack **held ~8 °C above ambient for 12 h post-charge, pinned ~12 °C below
the idle loop** — evidence of fairly strong passive loop coupling. To pin ambient: a
winter OBD-bus log (has OutsideAirTemp) or weather data for the log date.

**Mod outlook.** The passive path already delivers a few °C unpowered; a forced fan
across a raw water/air core would harvest much more of the ~20 °C gradient. Energy
budget: Bel ~500 W × ~5 h ≈ 2.5 kWh available; pack ≈ 200–250 kJ/K → ~1 kWh warms
~15 °C. Trade-offs: a raw exchanger is bidirectional (would heat the pack in summer when
the loop is hot — fan-off is the summer switch); losing Peltier cooling is minor (it was
measured ineffective); forced circulation also improves uniformity (evens the ~5 °C
corner gradient).

---

## Related
- `notes/via-docs/via-docs.md` — LV fuse/relay inventory (cooling actuators)
- `notes/hvac-investigation.md` — separate cabin HVAC blower (0x451 B4), unrelated
- `vtrux.md` — 0x410/0x430/0x440 BMS signal encodings (`epri-pt-bus.dbc`)
