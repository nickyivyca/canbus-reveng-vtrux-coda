# AC Supply Voltage and Source Resistance — CAN Notes

Cross-vehicle topic: estimating the **AC-side source resistance** (total loop impedance
upstream of the on-board charger) and the **supply voltage** actually seen during charging,
from CAN-logged charger telemetry.

The method is vehicle-agnostic — it needs only an AC input voltage and AC input current
signal from the on-board charger, plus (optionally) a J1772 pilot duty signal.

| Vehicle | Status | Section |
|---------|--------|---------|
| Vtrux | Analysed 2026-07-21 | [Vtrux](#vtrux) |
| Coda | Analysed 2026-07-21 | [Coda](#coda) |

**Headline cross-vehicle result:** both vehicles independently measure the 208 V commercial
sites at roughly **half** the source impedance of the 240 V residential ones
(~0.24 ohm vs ~0.41-0.47 ohm). See [Cross-vehicle comparison](#cross-vehicle-comparison).

---

## Method

### Signals used (Vtrux)

From `0x18FFD7C0` (`BELINV_hvBatteryAndCharger`), per `projects/vtrux/BelInverter-v2.dbc`
and `projects/vtrux/README.md`:

| Field | Bytes | Encoding |
|-------|-------|----------|
| `chargerInputVoltage` | B4:B5 | LE unsigned, x0.05 -> V AC RMS |
| `chargerInputCurrent` | B6:B7 | LE unsigned, x0.05 -> A AC RMS |

EVSE rating comes from `0x18FFD8C0` (`BELINV_j1772Info`) B2 `pilotDuty`. Per J1772, for
duty in 10-85% the EVSE advertises `I = duty% x 0.6 A`. This gives the EVSE's rating
independently of what the vehicle chooses to draw.

### Core principle

For a Thevenin source, `V_measured = V_open_circuit - I x R_source`. Regressing measured
AC voltage against AC current gives `R_source` as the negative slope. Everything below is
about making that slope mean what it should.

### Sample validity

`0xFFFF` on either field is a no-data sentinel (decodes to 3276.75). About 33 samples in
2.84 M are sentinels or otherwise wild. They are rare but extreme enough to dominate a
least-squares fit and **must** be filtered before any statistics. Accept only
`80 <= V <= 300` and `0 <= I <= 60`.

### Five estimators, in increasing robustness

The charger runs at pilot-limited **current plateaus**, not a continuous sweep, so the
useful signal is the voltage difference *between* plateaus.

1. **Within-session plateau ladder** (`level_fit`). Bin samples by current, take the median
   V at each plateau, regress those points. Fits the session's own open-circuit intercept,
   so day-to-day differences in baseline supply voltage cannot affect the slope.
2. **Fixed-effects pooled fit** (`fixed_effects_fit`). Pool many sessions but subtract each
   session's own mean V and mean I before fitting one shared slope. Between-session baseline
   offsets cancel mathematically. Use this instead of naively pooling samples.
3. **Fast-step estimator** (`step_estimates`). Compare median V/I in a window immediately
   before and after an abrupt current step. Because the two windows are ~30 s apart, slow
   grid drift over a long charge cannot bias the result.
4. **Plateau-pair estimator** (`plateau_pair_estimates`). Segment the session into runs of
   near-constant current, then compare *adjacent* plateaus within 20 minutes of each other.
   Generalises (3) to transitions that take minutes rather than being instantaneous, which
   is what captures the **CV taper (ramp-down)** side of a charge.
5. **Load-dump anchor** (`load_dump_anchor`) -- *the strongest available*. When a charge
   stops, current falls to zero while the charger keeps reporting for around a second
   before powering down. The voltage in that window IS the supply's open-circuit voltage:
   measured directly, no extrapolation, and immune to drift because it spans under a
   second. Take the p95 of sub-0.5 A samples, not the mean -- the subsequent power-down
   collapses the reading toward zero, so the settled value is the ceiling.

   **This is available far more often than expected: 23 of 35 Vtrux outlets recorded a
   true load dump, and all 35 yielded some low-current anchor.** Prefer it over any fitted
   intercept, and key supply classification off it.

### Pitfalls found the hard way

These each produced a wrong answer before being caught. They are the reason the method
looks over-engineered.

- **Never pool samples across outlets.** A single capture session can span two different
  EVSEs (Vtrux capture `vtrux_20260714_161319` starts on a 40 A unit and later moves to a
  30 A unit). Pooling hands the dominant pilot value the other outlet's current draw and
  produces a physically impossible negative derate. Define an *outlet* as
  (capture event x pilot-advertised current) and never pool wider.
- **Never classify supply voltage from a loaded reading.** Capture
  `vtrux_20260715_202222` reads 228.6 V at 23.5 A and 241.9 V at 7.6 A at the *same*
  outlet. Using the loaded value misclassifies a 240 V service as 208 V. Classify on a
  fitted or load-compensated open-circuit voltage.
- **Whole-session regressions read high.** They are inflated relative to the drift-immune
  estimators (see [Estimator disagreement](#estimator-disagreement)). Treat them as
  upper bounds.
- **Duty-cycled loggers fragment one charge into many "sessions."** The Android logger
  sometimes records only 1-6 s of CAN every 5 minutes. A time-gap session splitter then
  reports one plug-in as five sessions. Always report distinct *capture events* alongside
  session counts, or n will be overstated.
- **Never silently drop short captures.** A 33-sample capture held the only load dump in
  the dataset -- and with it the only directly measured open-circuit voltage. Sample-count
  thresholds should log what they discard.
- **Comparing scatter of differences against scatter of ratios is meaningless** — different
  units. To compare a subtractive against a multiplicative model, fit each by least squares
  and compare RMS prediction error.

### Reproducing

Extract the frames of interest with grep first (streaming 64 GB of logs through Python is
far slower), then analyse:

```bash
grep -RH  "18FFD7C0"              projects/vtrux/logs --include="*.log" > raw_primary.txt
grep -RH  "18FFD7C0"              ../../CANLogs/VtruxLogs --include="*.log" > raw_android.txt
grep -RHE "18FFD8C0|18FFD9C0"     projects/vtrux/logs "../../CANLogs/VtruxLogs" --include="*.log" > raw_pilot.txt

py -3.12 projects/vtrux/notes/artifacts/ac-voltage/ac_voltage_source_resistance.py
py -3.12 projects/vtrux/notes/artifacts/ac-voltage/evse_derate.py
```

Scripts and outputs: `projects/vtrux/notes/artifacts/ac-voltage/`. The `raw_*.txt`
intermediates are ~635 MB and are regenerable from the commands above.

For Coda, extract `0x27D`/`0x27B` from both roots and run the Coda script:

```bash
grep -RHE "0x27D|0x27B" projects/coda/logs --include="*.log" > raw_coda_primary.txt
grep -RHE "0x27D|0x27B" ../../CANLogs/CodaLogs --include="*.log" > raw_coda_android.txt

py -3.12 projects/coda/notes/artifacts/ac-voltage/coda_ac_source_resistance.py
```

Coda scripts and outputs: `projects/coda/notes/artifacts/ac-voltage/`.

`oc_anchors.py` (Vtrux artifacts folder) is a standalone cross-check of the open-circuit
anchors, grouping strictly by (capture event x pilot current) straight from the raw
extracts. Useful for verifying the main script's classification independently.

---

## Vtrux

Analysed 2026-07-21 over **both** log roots — `projects/vtrux/logs/` (45 GB) and
`../../CANLogs/VtruxLogs/` (19 GB). 2.84 M AC frames from 936 log files, resolving to
**182 charge sessions** across 35 distinct outlets (15 of them 240 V / 31 A).

### AC voltage seen

Session-median AC voltage under load, across all 182 sessions:

| | V |
|---|---|
| min | 180.7 |
| p05 | 198.0 |
| p25 | 210.6 |
| median | 236.5 |
| p95 | 245.0 |
| max | 246.3 |

The distribution is bimodal by supply class: a 240 V nominal residential group and a
208 V nominal industrial group, plus one weak-supply outlier (below).

### Resistance by supply / EVSE bucket

`R per-session` = median of within-session ladder fits. `R fixed-eff` = within-session
centred pooled slope. `R steps` = median of settled (30 s) fast-step estimates — the
most drift-immune column, and the one to quote.

| Nominal supply | EVSE advert | Sessions | Capture events | Outlets | Vac med (range) | R per-session | R fixed-eff | **R steps** |
|---|---|---|---|---|---|---|---|---|
| 240 V | 31 A | 131 | 15 | 15 | 242 (228-246) | 0.480 (24) | 0.493 (33) | **0.413** (43) |
| 240 V | 32 A | 4 | 1 | 1 | 239 (234-245) | 0.448 (4) | 0.524 (4) | **0.332** (10) |
| 240 V | 23 A | 6 | 2 | 2 | 239 (234-245) | 0.778 (5) | 0.791 (6) | **0.467** (9) |
| 240 V | 16 A | 2 | 1 | 1 | 241 | — | 0.840 (2) | **0.407** (5) |
| 240 V | 8 A | 1 | 1 | 1 | 242 | — | — | — |
| 208 V | 29 A | 26 | 13 | 13 | 205 (195-211) | 0.465 (9) | 0.396 (13) | **0.237** (24) |
| 190 V | 40 A | 12 | 2 | 2 | 181 (181-186) | — | **0.242** (2) | — |

Session counts are not a measure of independence: 131 sessions at 240 V / 31 A still come
from 15 outlets, and the 12 at the 40 A site are one plug-in event fragmented by logger
gaps. **Quote outlets and capture events, not sessions.**

### Open-circuit voltage per bucket (measured)

`V @ min I` is the p95 voltage at the lowest current bin with data. Every row below reached
**0.0 A via a load dump** -- these are measurements, not fitted intercepts.

| Supply | EVSE advert | Outlets | **V @ 0.0 A** | Max I | V @ max I | Drop |
|---|---|---|---|---|---|---|
| 240 V | 32 A | 1 | **250.8 V** | 28.3 A | 235.1 V | 15.8 V |
| 240 V | 23 A | 2 | **250.5 V** | 20.2 A | 238.6 V | 11.9 V |
| 240 V | 31 A | 15 | **249.2 V** | 28.4 A | 235.3 V | 13.9 V |
| 240 V | 16 A | 1 | **247.9 V** | 13.0 A | 240.9 V | 6.9 V |
| 240 V | 8 A | 1 | **245.6 V** | 12.2 A | 242.1 V | 3.5 V |
| 208 V | 29 A | 13 | **213.6 V** | 27.7 A | 201.2 V | 12.5 V |
| **190 V** | **40 A** | 2 | **190.1 V** | **37.0 A** | **181.4 V** | **8.8 V** |

The 190 V row is the key one: it carries the **highest current in the dataset (37 A) for
the second-smallest drop (8.8 V)**. Its supply is ~60 V below the 240 V sites but its
wiring is the best of any site measured.

**Do not assume a nominal open-circuit voltage and back-compute resistance from a loaded
reading.** Assuming ~198-200 V for the 190 V site (rather than its measured 190.1 V)
inflates the apparent resistance to 0.5-1.7 ohm and makes it vary with current -- and that
current-dependence is itself the signature of a wrong assumed source voltage. A real
resistance is the same at 6 A and 36 A.


**Typical source resistance: ~0.4 ohm on the 240 V circuits, ~0.24 ohm on the 208 V
industrial circuits.** This is total loop impedance at the charger's AC sense point —
EVSE cable, any extension cord, building wiring and transformer combined. CAN data alone
cannot apportion it between those.

### Estimator disagreement

The drift-immune estimators read consistently **~20% lower** than the whole-session
regressions. This is not a settling artifact — sweeping the step comparison window shows
convergence:

| Settle window | n steps | R median |
|---|---|---|
| 5 s | 49 | 0.146 |
| 10 s | 47 | 0.389 |
| 20 s | 44 | 0.395 |
| 40 s | 43 | 0.412 |
| 90 s | 40 | 0.400 |

5 s is genuinely unsettled; past 20 s the estimate is stable at ~0.40 ohm. The residual
gap versus the ~0.49 ohm regression value therefore reflects something the regression is
absorbing that the step measurement is not.

**Hypothesis (not yet confirmed):** within a charge, current is high early and tapers,
while grid voltage typically *rises* through the evening as area load drops. A
whole-session regression would read that correlation as extra resistance. Confirming this
requires an independent measurement of the supply voltage over the same window — see the
open task on InfluxDB/Emporia correlation.

### Ramp-up vs ramp-down agreement

The CV taper (ramp-down) side is a valid and productive source of measurements — it
supplies more usable plateau pairs than the ramp-up side, since most sessions have one
ramp-up but several taper steps.

| Bucket | Pairs | Up n | Up R | Down n | Down R |
|---|---|---|---|---|---|
| 240 V / 31 A | 18 | 5 | 0.452 | 13 | 0.432 |
| 208 V / 29 A | 15 | 7 | 0.323 | 8 | 0.296 |
| All | 37 | 14 | 0.382 | 23 | 0.427 |

Up and down agree closely. This is a real validation: for an ohmic supply they must match,
and a systematic ramp-down excess would have indicated conductor heating. No such excess
is present.

### Extension cord A/B

Two captures at what appears to be the same outlet (fitted open-circuit voltages 1.5 V
apart), one charging through an extension cord and one after repositioning so the EVSE
cable reached directly:

| | Ladder fit | Fast steps | Voc | Vac med |
|---|---|---|---|---|
| With extension (`vtruxextensioncabletest.log`, 2026-03-05) | 0.538 | 0.465 (n=2) | 249.4 V | 236.5 V |
| Without (`chargingafterturningaroundandnotusingextension.log`, 2026-02-16) | 0.421 | 0.363 (n=2) | 247.9 V | 239.1 V |
| **Delta** | **+0.117 ohm** | **+0.102 ohm** | 1.5 V | −2.6 V |

Two independent estimators agree on **~+0.10 to +0.12 ohm** for the cord. That is
physically credible: 0.117 ohm round-trip is about 37 ft of 12 AWG or 58 ft of 10 AWG
copper. At 27 A it costs an extra ~3.2 V of sag and burns ~85 W in the cord.

Confidence: **strong but not conclusive** — one session per condition, 17 days apart,
only 2 fast steps each. Direction and magnitude are consistent across methods.

### The 180 V charge (2026-07-14)

The lowest AC voltage in the entire dataset. Capture `vtrux_20260714_161319`, a **40 A
industrial EVSE** (pilot duty 66% = 39.6 A advertised), truck drawing **36.5 A at
180.7-181.8 V** (~6.6 kW) for roughly 45 minutes.

A **load dump** captured in `vtrux_20260714_151732_T2.log` at 16:10:17 gives a direct,
drift-immune measurement. The charger cuts from 23.4 A to 0 A in 0.6 s:

```
23.4 A -> 184.2 V
12.4 A -> 188.0 V
 3.2 A -> 189.5 V
 0.0 A -> 190.1 V     <- open circuit, held steady ~0.7 s
```

(The charger then powers down entirely: Vac collapses and HV decays 373 -> 199 V as the
contactors open.)

| Derivation | R |
|---|---|
| (190.1 - 184.2) / 23.4 | **0.252 ohm** |
| (190.1 - 181.3) / 36.5, against the steady plateau | **0.241 ohm** |

**Voc = 190.1 V is measured, not extrapolated.** A phone screenshot at 16:09:10
independently corroborates the low-current end: 189.4 V at 6.4 A, with the J1772 offer
shown as 39.6 A (pilot 66%), confirming the 40 A EVSE rating.

**The low voltage is not a resistance problem.** At ~0.245 ohm this is the *lowest* loop
impedance of any site in the dataset — it sags less per amp than anywhere else measured,
and delivered the highest current in the dataset (36.5 A) for only 8.8 V of drop. The
supply itself was simply ~190 V open-circuit, a 208 V nominal service sitting ~9% low.
Of the ~18 V below nominal, only ~8.8 V is the truck's own load; the rest was already
missing at zero current, i.e. upstream of the building.

Later the same evening the truck moved to a 29 A EVSE and logged 26.2 A at 195 V with an
excellent fit (R = 0.507, Voc = 208.5, r = -1.00), confirming the ~190 V reading was
specific to that first outlet.

**Charge was interrupted.** The 16:10:17 load dump is a charge *stopping*; a fresh ramp
from 15.5 A appears at 16:18:19 in the next capture. So this was at least two charge
attempts, not one continuous 45 min session.

**Caveat.** Still one outlet on one afternoon. The resistance figure is now well founded
(a load dump is the cleanest possible measurement), but site-to-site generality is not.

### Logging gaps at this site -- corrected

An earlier version of this note claimed the logger was "duty-cycling" and that no
sub-15.5 A data existed. Both were wrong. What the files actually show:

| Period | Header spacing | Data per file | Internal gaps >1 s |
|---|---|---|---|
| `_161319` T0-T11 (16:13-17:08) | exactly 300 s | 1.1-5.7 s | **zero** |
| `_161319` T12-T32 (17:12-18:24) | 215 s | 215 s | **zero** |

Files rotate on whichever comes first, 50 MiB (~1,051,400 frames) or 300 s. From T12 the
header spacing equals the data span exactly -- fully contiguous. For T0-T11 the 300 s
timer fires but only 1-6 s of traffic ever arrived, so ~295 s is genuinely missing
*between* files while each file is itself clean.

The vehicle was charging normally throughout those gaps: every burst shows 104 unique IDs
at 3,124-3,160 fps (a fully alive bus at the normal charging rate), and T2-T11 each open
already at 36.3-36.9 A with no ramp. The CAN adapter handles also stayed at channels 9/10
across all 11 files, so the interface was never re-opened -- it simply stopped delivering
data to the app. **Hypothesis (unconfirmed): a host/app-side stall, not vehicle or bus
behaviour.** A phone screenshot taken at 16:09:10 shows the app UI live and streaming
while nothing was being written, which is consistent with the write path stalling rather
than the whole app being frozen.

Practical lesson: `MIN_FIT_SAMPLES` was set to 40 and silently discarded the entire
`_151732` capture (33 loaded samples) -- the one holding the load dump. Only two capture
groups fall in the 1-39 sample range, so the threshold is now 10. **Short captures can
contain the single most valuable measurement; never drop them silently.**

### EVSE current derate: fixed subtraction, not a percentage

The Vtrux draws less than the EVSE advertises. Pairing pilot-advertised current against
sustained draw, per log file (per *file*, not per session — a session can span two EVSEs):

| Advertised | Drawn | Difference | Ratio |
|---|---|---|---|
| 15.6 A | 12.7 A | 2.95 A | 0.811 |
| 23.4 A | 19.6 A | 3.80 A | 0.838 |
| 29.4 A | 26.8 A | 2.60 A | 0.912 |
| 31.2 A | 27.1 A | 4.07 A | 0.870 |
| 31.8 A | 27.4 A | 4.39 A | 0.862 |
| 39.6 A | 36.6 A | 3.01 A | 0.924 |

Fitting both one-parameter models by least squares: subtraction **RMS 0.65 A**, percentage
**RMS 1.03 A**.

The decisive evidence needs no fitting: the extreme points at 15.6 A and 39.6 A are a
2.5x range apart yet show **the same ~3.0 A offset**, while the ratio moves 14 points
(0.811 -> 0.924). A fixed percentage cannot produce that.

**Conclusion: `drawn ~= advertised - 3 A`** (point estimate 3.0-3.5 A depending on the
per-level statistic). Confidence: **high** — six advertised levels spanning 15.6-39.6 A,
from deliberate EVSE-setpoint tests plus opportunistic captures.

---

## Coda

Analysed 2026-07-21 over `projects/coda/logs/` (2.3 GB) and `../../CANLogs/CodaLogs/`
(16 GB). 617 k charger frames from 72 log files, resolving to **12 charge sessions**.

### Signals

The Coda has **two Lear on-board chargers in parallel on one AC feed**:

| ID | Message | Node |
|----|---------|------|
| `0x27D` | `CMMInputValues` | CMM (master) |
| `0x27B` | `CMSInputValues` | CMS (slave) |

Each carries `ACInVoltage` / `ACInCurrent` / `ACInPower`, Motorola 16-bit, scale 0.03125,
on B CAN. Decoding was verified against `cantools` before use.

**Both units must be summed.** Each reports only its own current (~15 A each), so the
current causing the volt drop is the sum, ~30 A. Using one charger alone halves the
apparent current and doubles the apparent resistance.

The two units' voltage readings agree extremely well — **median difference 0.00 V, p95
0.50 V across 74,040 paired samples** — confirming they share one supply and validating
the summing approach.

> **Resolved 2026-07-21 — `ACInPower` DBC field corrected.** This analysis originally
> flagged `ACInPower` as decoding to ~0.09 W against ~3.1 kW actual. Cause: the DBC
> had it as 16-bit at scale 1/32 (`39|16@0+`), reading only bytes 4–5. It is really a
> **32-bit BE field over bytes 4–7 at scale 1/64** (`39|32@0+ (0.015625,0)`), now
> fixed in `projects/coda/CODA-B-CAN.dbc`. Verified to ±0.000 % against V×I over
> 367,728 frames. The field equals V×I exactly, so it is charger-computed apparent
> power and carries no information beyond V and I — **this analysis loses nothing by
> not having used it, and its conclusions are unaffected.** See
> `projects/coda/notes/charging-analysis.md`.

### AC voltage seen

| Session-median Vac | V |
|---|---|
| min | 199.0 |
| p05 | 199.6 |
| median | 203.2 |
| p95 | 233.6 |
| max | 235.5 |

Ten of twelve sessions are ~199-206 V (208 V nominal commercial, mostly ChargePoint);
two are 232-235 V (240 V nominal home driveway).

### Method limitation on Coda

The Coda holds a **near-constant ~30 A for an entire charge** — there is essentially no
current modulation to regress against. Consequently:

- plateau-pair estimator: **0 usable pairs** (the whole session is one plateau)
- fast-step estimator: no abrupt steps
- ladder fit: only 1 session qualifies
- fixed-effects slope: 0.428 ohm but only r = −0.36 — weak, do not rely on it

The workable estimator here is the **open-circuit anchor**: the charger keeps reporting
during the very-low-current moments at session start/end, so the settled voltage there is
effectively open-circuit. Startup transients pull the reading far below line voltage, so
take a high percentile (p95) of the sub-2 A samples rather than a mean.

This is a weaker method than the Vtrux plateau ladders — it rests on two points rather
than a fitted line, and assumes the idle reading is settled line voltage.

### Results

| Site | Date | Vac med | Iac med | R ladder (r) | Voc anchor | R anchor |
|---|---|---|---|---|---|---|
| ChargePoint | 2026-02-18 | 201.5 | 30.0 | 0.234 (−1.00) | 211.5 | 0.333 |
| ChargePoint | 2026-03-11 | 199.0 | 30.2 | — | 207.5 | 0.282 |
| Driveway (home) | 2026-02-19 | 232.0 | 29.1 | 0.471 (−0.98) | 248.5 | 0.568 |
| Driveway (home) | 2026-02-19 | 235.5 | 28.6 | 0.638 (−0.76) | 249.1 | 0.476 |

- **208 V ChargePoint sites: ~0.23-0.33 ohm**
- **240 V home driveway: ~0.47-0.64 ohm**

Confidence: **moderate.** Only 4 of 12 sessions yield any estimate, and the two methods
differ by up to 0.1 ohm on the same session. The 208 V vs 240 V split is nonetheless
consistent across both methods and both sites.

---

## Cross-vehicle comparison

Two vehicles, different charger vendors (Bel vs Lear), different CAN messages, different
current profiles, and largely different measurement methods — yet the same pattern:

| Supply class | Vtrux | Coda |
|---|---|---|
| 208 V commercial | ~0.24 ohm (24 step estimates, 13 outlets) | ~0.23-0.33 ohm (2 sites) |
| 240 V residential | ~0.41 ohm (43 step estimates, 15 outlets) | ~0.47-0.64 ohm (1 site, 2 sessions) |

**Commercial 208 V service shows roughly half the source impedance of residential 240 V
service.** This is consistent with larger service transformers and shorter, heavier feeder
runs at commercial sites, but that explanation is a **hypothesis** — the CAN data measures
only total loop impedance and cannot apportion it between transformer, feeder, and cordage.

The agreement matters because the two vehicles' numbers are near-independent: the Vtrux
figure comes mainly from fast current steps, the Coda figure from open-circuit anchors.
Methodological error common to both is therefore unlikely to explain it.

---

## Panel-side correlation (InfluxDB / Emporia / Enphase)

Analysed 2026-07-21. Script: `projects/vtrux/notes/artifacts/ac-voltage/influx_correlation.py`.

The truck measures voltage at the *end* of everything. The Enphase Envoy measures voltage
at the service panel. Differencing them splits the loop impedance in two:

```
R_total   = (V_open_circuit - V_truck) / I     (CAN only)
R_house   = (V_panel        - V_truck) / I     (needs Influx)
R_utility = R_total - R_house
```

### Sources

| Entity | Measurement | Role |
|--------|-------------|------|
| `envoy_202220094881_voltage_net_consumption_ct` | `V` | Service-panel voltage |
| `garage_14_50_power_minute_average` | `W` | The NEMA 14-50 EVSE circuit |

Connection details in `../Infrastructure/ha-claude-connection/notes.md`
(localhost:8086, db `homeassistant`). **Log timestamps are local
(America/Los_Angeles); InfluxDB is UTC** — the conversion must handle PST/PDT.

### Matching

20 of 32 candidate 240 V sessions overlap the garage 14-50 circuit at >3 kW, confirming
they were charges at the home EVSE. 14 are usable; 6 were dropped because the truck's
session-median current (which spans the CV taper) disagreed with the Emporia EVSE-on
average by more than 3 A — those describe different time windows and give meaningless
(sometimes negative) R_house.

Emporia current runs a median **1.26 A above** the charger's own report on the agreeing
sessions, as expected: it sees whole-circuit power including EVSE overhead, and assumes a
power factor.

### Decomposition

| Segment | R |
|---|---|
| **R_house** — panel -> garage run -> EVSE -> cord | **0.238 ohm** (n=14, range 0.173-0.303) |
| **R_utility** — transformer -> service drop -> panel | **0.175 ohm** (by difference) |
| R_total (CAN step estimator, 240 V / 31 A) | 0.413 ohm |

So at the home EVSE roughly **58% of the loop impedance is inside the house** and 42% is
utility-side. The house share is the actionable part, and it is consistent with the
independently measured extension-cord contribution (~0.11 ohm, which is itself about half
of R_house when the cord is in use).

### Grid drift confirmed — and it explains the estimator gap

Panel voltage over a session (last quarter minus first quarter):

- Across the 14 short/steady sessions: median **+0.43 V** (range −3.83 to +4.19)
- Across the 6 **long tapering** sessions: **+1.45 to +6.49 V, every one positive**

| Session | Duration | Panel drift |
|---|---|---|
| 2026-01-16 19:42 | 259 min | +5.62 V |
| 2026-01-23 12:53 | 548 min | +4.47 V |
| 2026-01-25 19:31 | 145 min | +3.15 V |
| 2026-04-22 10:45 | 570 min | +1.45 V |
| 2026-05-03 19:35 | 141 min | +6.49 V |
| 2026-06-27 16:42 | 273 min | +2.04 V |

This is the mechanism proposed under [Estimator disagreement](#estimator-disagreement),
now **confirmed with independent panel-side data**: during long overnight charges the grid
voltage rises several volts as area load drops, while the truck's current tapers from
~27 A to ~7.8 A. A whole-session regression sees rising voltage alongside falling current
and books the difference as resistance.

Dividing each session's drift by its current swing gives the spurious resistance this
adds: **median ~0.23 ohm** (wide spread, 0.08-1.8 — a rough order-of-magnitude figure, as
the current swing is approximated from the truck/Emporia difference). That is the same
order as the ~0.08 ohm gap between the regression (0.493) and step (0.413) estimators, and
more than sufficient to explain it.

**Conclusion: the drift-immune step and plateau-pair estimators are the correct ones to
quote. Whole-session regressions are biased high on long tapering charges, and should not
be used for overnight sessions at all.**

---

## Open tasks

- Extend the panel-side correlation to the 208 V commercial sites (no Emporia coverage
  there, so this needs another voltage reference).
- Re-run the Vtrux buckets excluding overnight tapering sessions from the regression
  columns, now that the drift bias is confirmed.
- Investigate why the logger stalled at the 40 A site (app write path vs Android
  suspension). CAN data cannot settle this; it needs phone/app-side evidence.
- Apply the load-dump anchor to Coda (its two Lear chargers also shut down at end of
  charge, so directly measured Voc should be available there too, replacing the weaker
  p95-of-idle anchor currently used).
- ~~Investigate the `ACInPower` scale/bit-position error in `projects/coda/CODA-B-CAN.dbc`
  (decodes ~0.09 W against ~3.1 kW actual).~~ **DONE 2026-07-21** — it was 16-bit/32 in the
  DBC but is really 32-bit BE over bytes 4–7 at 1/64. Fixed. Field is charger-computed
  V×I, so it adds no information beyond V and I and this analysis is unaffected.
- Coda resistance rests on only 4 of 12 sessions. A deliberate EVSE-setpoint sweep on the
  Coda (as was done for the Vtrux) would create the current steps the method needs.
