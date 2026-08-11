# Vtrux — Energy Consumption (Wh per mile)

First-pass estimate of the Vtrux's road energy consumption from CAN logs, with
explicit treatment of the elevation confound.

**Status:** complete over 22 trips / 647 miles, drawn from five Ixxat drive logs
plus the 20 largest Android-logger sessions (2026-08-02).

Scratchpad and extracts: `notes/artifacts/wh_per_mile_estimate.py`,
`notes/artifacts/whpm_trips.json` (see `notes/artifacts/README.md`).

---

## Headline

**~530 Wh/mi** at the HV bus (1.9 mi/kWh; ~64 MPGe measured at the battery, so
roughly 54 MPGe from the wall at typical charging efficiency).

Three independent ways of dealing with elevation converge, which is the main
reason to trust the number:

| Estimator | Sample | Result |
|-----------|--------|-------:|
| All valid trips, uncorrected | 647.3 mi, 22 trips | **531 Wh/mi** |
| Elevation-neutral trips only (\|grade\| < 25 Wh/mi) | 302.8 mi, 10 trips | **557 Wh/mi** |
| Grade-corrected via MAP altimeter | 511.9 mi, 17 trips | **532 Wh/mi** (541 uncorrected) |

The grade correction barely moves the aggregate (541 -> 532) because climbs and
descents very nearly cancel across 17 trips. That is the "elevation averages
out over many trips" assumption — but here it is *demonstrated* rather than
assumed, which is what the altimeter buys us.

Individual trips range from **193 to 840 Wh/mi**, and that spread is dominated
by net elevation change and regen recovery, not by average speed.

### Per-trip results

Sorted by Wh/mi. Every trip listed passed the power-balance validity check
(accessory residual positive and under 10 kW).

| Capture | Trip | Distance | Avg speed | Wh/mi | Regen | Net dh |
|---------|-----:|---------:|----------:|------:|------:|-------:|
| `@20260513_195030` | 0 | 13.1 mi | 41 km/h | **840** | 14% | +509 m |
| `vtruxevapdrivelog4` | 0 | 16.7 mi | 68 km/h | **743** | 7% | 0 m |
| `vtruxanotherevaplogpart2` | 0 | 17.7 mi | 57 km/h | **700** | 9% | n/a |
| `vtruxscottsvalleydrive` | 0 | 7.4 mi | 41 km/h | **672** | 10% | +124 m |
| `@20260617_193900` | 1 | 19.2 mi | 52 km/h | **669** | 15% | 0 m |
| `@20260726_160923` | 0 | 3.7 mi | 18 km/h | **661** | 31% | 0 m |
| `@20260719_164520` | 0 | 18.1 mi | 48 km/h | **647** | 12% | 0 m |
| `@20260724_211556` | 1 | 89.3 mi | 62 km/h | **642** | 11% | +1103 m |
| `@20260726_160923` | 1 | 53.2 mi | 67 km/h | **601** | 16% | 0 m |
| `@20260802_123318` | 0 | 17.5 mi | 47 km/h | **582** | 23% | +211 m |
| `@20260714_161319` | 3 | 40.0 mi | 81 km/h | **546** | 10% | +41 m |
| `@20260617_193900` | 0 | 26.6 mi | 56 km/h | **529** | 23% | 0 m |
| `@20260724_162517` | 0 | 34.0 mi | 66 km/h | **526** | 23% | +41 m |
| `@20260726_142628` | 0 | 59.9 mi | 63 km/h | **519** | 16% | n/a |
| `@20260714_161319` | 2 | 18.0 mi | 41 km/h | **494** | 17% | 0 m |
| `@20260714_075545` | 0 | 41.4 mi | 62 km/h | **487** | 22% | n/a |
| `@20260724_172621` | 0 | 73.1 mi | 47 km/h | **472** | 25% | -41 m |
| `@20260719_190019` | 0 | 15.7 mi | 62 km/h | **378** | 28% | -209 m |
| `vtruxscottsvalleydrive` | 1 | 7.7 mi | 31 km/h | **355** | 44% | -124 m |
| `@20260726_124205` | 0 | 58.4 mi | 64 km/h | **277** | 42% | **-1103 m** |
| `@20260618_002023` | 0 | 16.3 mi | 48 km/h | **193** | 61% | n/a |

The elevation signal is unmistakable: every trip above 640 Wh/mi is either a
net climb or a low-regen cycling drive, and every trip below 400 Wh/mi is a net
descent (or, for `@20260618_002023`, has no altimeter but 61% regen recovery,
which is only reachable on a sustained descent).

`debuglog_M6` and several Android sessions were checked and discarded — the
truck never moved (stationary charge/idle).

**Definitions used above:**

- **HV bus total** = battery net discharge + generator output. This is the
  energy the vehicle actually consumed, whatever its source, and is the number
  comparable to a manufacturer's Wh/mi figure. Charging losses are *not*
  included.
- **Propulsion only** = traction inverter DC energy (`0x462`), net of regen.
  The difference between the two is accessory load.
- Accessories (DCDC/12 V loads, AC compressor, coolant and oil pumps) measured
  **1.1–3.6 kW average** across all 21 valid trips, typically ~2–3 kW. That is
  10–25% of total consumption, and it is the reason short low-speed trips look
  disproportionately expensive per mile.

---

## Method

### A logger session is not a trip — split first

**This is the single most important correctness step, and getting it wrong
produces silently absurd numbers.** Android-logger sessions routinely contain a
drive followed by hours of parked wall charging. Charging drives `battery net +
generator` negative, which scores as *negative consumption*. Before splitting,
three sessions reported **-3069, -2666 and +243 Wh/mi** (the last with 243 Wh/mi
"total" against 608 Wh/mi propulsion — impossible).

Trips are therefore cut as maximal runs of movement, allowing standstills of up
to 300 s (lights, brief stops) but breaking at anything longer. Parked charging
falls outside every trip automatically.

**Validity check:** the accessory residual (`HV bus total - traction`) must be
positive and under 10 kW. It is a physical quantity that cannot be negative, so
any trip failing this has contamination somewhere and is excluded. 21 of 22
trips passed; the one failure is `oghighwaydrive`, a PT-only capture with no
traction channel, so its residual is undefined rather than wrong.

### Energy

Pack power from `0x410` (`bcm_vbat` x `bcm_ibat`), generator DC power from
`0x482` (`GENE_HighPwr_Volt` x `GENE_HighPwr_Curr`), traction inverter DC power
from `0x462` (`TRAC_HighPwr_Volt` x `TRAC_HighPwr_Curr`). All decoded through
`cantools` against `epri-pt-bus.dbc` / `epri-obd-bus.dbc`.

`0x598` `ess_power` / `trac_power` (formerly `DBL_ESSPwrAvg` / `DBL_TracPwrAvg`
in `epri-pt-bus.dbc`) were deliberately **not** used as the primary energy
source — see [Encoding corrections](#encoding-corrections-found-along-the-way).
Their encoding is now fixed in `vtrux-powertrain-experimental.dbc`, but `0x410`
pack V×I remains the primary source since it is a direct measurement rather than
a VCU-computed average.

**Validation — the power balance closes.** On the two logs carrying all three
channels, `pack + generator - traction` resolves to a plausible, near-identical
accessory load:

| Log | Residual |
|-----|---------:|
| `vtruxevapdrivelog4` | 2.01 kW |
| `vtruxanotherevaplogpart2` | 2.04 kW |

Two independent logs agreeing to 1.5% on a residual that is the *difference* of
three separately-scaled channels is strong evidence that all three decodings are
correct in both sign and scale.

### Distance

Four independent sources agree to within 0.15%:

| Source | Resolution | Notes |
|--------|-----------|-------|
| `0x3E9` `Distance_Rolling_Count_Average_Driven` (Vehicle bus) | 0.125 m | Best source. 13-bit rolling counter, unwrapped in software (wraps every 1024 m). **Vehicle bus only** — the OBD-bus copy is VCM-zeroed. |
| `0x625` `VehicleOdometer` (PT bus) | 1 km | The truck's own odometer; coarse but absolute, and the arbiter for the others. |
| `0x120` `VehicleOdometer` | 15.6 m nominal | Needs a 256x correction — see below. |
| Integrated `0x3E9` `Vehicle_Speed_Average_Driven` | — | Agrees with the rolling count to 0.15%. |

Note `Distance_Rolling_Count_Average_Driven` is actually in
**metres** at 0.125 m/count. `epri-obd-bus.dbc` declares the unit as `km`,
which is wrong by 1000x.

**Motor-speed-to-road-speed expansion.** For captures without a Vehicle bus
(PT-only Ixxat logs, and all Android-logger sessions), distance is derived from
traction motor speed. Least-squares fit of `0x5A2` `trac_rpm` against `0x3E9`
`Vehicle_Speed_Average_Driven` on the three 3-bus logs gives:

```
62.48 rpm per km/h
```

This is consistent across all three logs and reproduces the GMLAN speed
distribution almost exactly (p50 64 vs 64, 55 vs 55, 18 vs 14 km/h). Validated
end-to-end on `oghighwaydrive`: integrating `trac_rpm / 62.48` gives 39.13 km
against 39 km on the truck's own `0x625` odometer.

The previously-noted range of 63–68 rpm/(km/h) in `vtrux.md` is superseded by
this direct calibration for the logs tested here.

### Android-logger sessions

The 32.8 GB `CANLogs/VtruxLogs/` library (1072 sessions) is the same BUSMASTER
format and parses with the same code, but three things differ and each will
produce wrong answers silently if missed:

1. **Chunk clocks reset.** Each `_T{n}` chunk restarts its data-line timestamp
   at `00:00:00`. The per-chunk `***START DATE AND TIME***` header is the only
   thing tying chunks to one timeline, so chunks must be stitched by header
   epoch (with a midnight-rollover guard), not concatenated.
2. **Channel numbers are arbitrary and change mid-session.** Observed values
   include 43/44 and 7/8, and a session will renumber its own channels on USB
   reconnect (bus 1/2 -> 7/8 within `20260802_123318`). Bus roles must be
   resolved by anchor content and then *merged across channel numbers*, with
   the merged series re-sorted by time.
3. **No Vehicle bus.** These captures carry PT + OBD only. `0x3E9` is present
   on the OBD bus but is VCM-zeroed there, so the GMLAN distance and speed
   sources are unavailable. **Distance must come from `trac_rpm / 62.48`.**
   Cross-check every session against the `0x625` odometer.

`0x2C3` is present on the OBD bus, so the barometric altimeter works on these
sessions — 18 of the 22 trips have usable altitude, including net changes of
+1103 m and -851 m.

---

## Elevation handling

This was the main methodological problem: a hill can dominate the energy budget
of any single trip. Three approaches were tried; one works.

### The confound is large

From `vtruxscottsvalleydrive`, the same road driven in both directions at the
same speed:

| Leg | Distance | Avg speed | Net dh | Wh/mi |
|-----|---------:|----------:|-------:|------:|
| Climb | 5.76 mi | 54 km/h | +124 m | **733** |
| Descent | 2.88 mi | 56 km/h | -124 m | **-41** (net regenerating) |

A one-way analysis of that route could land anywhere in a ~775 Wh/mi band.
Whole-trip closure removes the confound completely.

### `0x2C3` MAP works as a barometric altimeter (engine-off only)

The Vtrux is an EREV, so the engine is off much of the time. **With the engine
not rotating there is no manifold vacuum, so MAP reads ambient barometric
pressure.** `0x2C3` B6 (`ECM_MAP`, 0.5 kPa/count) therefore doubles as an
altimeter whenever engine RPM is zero.

Gating: engine RPM (`0x0C9` on the OBD bus, or `0x054` `GENE_RotSpd` on the PT
bus) must have been zero for >= 10 s to let the manifold equalise, then a
median filter over a +/-60 s window. Altitude from
`h = -8434 * ln(p / 101.325)` m.

On `vtruxscottsvalleydrive` the engine never ran at all, giving 100% coverage
and a clean, physically sensible profile:

```
102.5 kPa  (start)
   |  climb, ~10 min
100.5 kPa  (highest point, ~167 m above start)
   |
101.0 kPa  <- 41-minute plateau
   |  descent, ~5 min
102.5 kPa  (end -- identical to start)
```

Start pressure equals end pressure, so **net grade energy is zero by
construction** and no correction is needed at all.

`0x599` B2:B3 — described elsewhere as a "barometric reference" — is **not** a
live sensor. It reads a constant 103.0 kPa (exactly one unique value across
every log checked) and is useless for altimetry.

### Resolution limit: trip scale only

0.5 kPa/count is ~42 m, which at an assumed 3000 kg is ~0.34 kWh of potential
energy. That error budget behaves very differently depending on the span it is
spread over:

| Span | Elevation uncertainty |
|------|----------------------:|
| 15-mile trip | +/- 22 Wh/mi (negligible) |
| 1 km segment | +/- 340 Wh/mi (useless) |

### Contamination gate (added 2026-08-02)

The engine-off gate alone is not sufficient. Two MAP samples in
`@20260724_172621` passed it while still reading manifold vacuum, yielding
altitudes over 1,200 m and — via gap interpolation — a bogus +1,034 m "summit"
where the truck was actually at +27 m.

The fix follows from the physics: **manifold pressure can never exceed ambient**,
so contamination is always one-sided (low). The ambient estimator therefore
takes an **upper quantile (p90)** of the +/-60 s window rather than the median,
and requires **>= 20 valid samples with spread <= 2.0 kPa**, emitting "unknown"
otherwise.

Effect on published numbers: **the 531 Wh/mi headline is unchanged**; only
elevation attribution moved. `@20260726_124205` corrected from -851 m to
**-1103 m**, which then exactly mirrors the +1103 m climb of
`@20260724_211556` on the same round trip — an independent confirmation that
the corrected altimeter is right. `@20260618_002023` correctly dropped to "no
altimeter" rather than reporting a contaminated -467 m. See
`weekend-trip-2026-07-24.md`.

**Conclusion: the MAP altimeter is trustworthy at whole-trip scale only.**
Per-segment grade correction is not supportable with this data.

Across the 22-trip sample the quantisation error is comfortably small: for
trips of 13–89 miles it works out to +/- 4 to 26 Wh/mi. It only becomes
crippling on the sub-2-mile fragments (+/- 282 Wh/mi), which is one more reason
those are excluded.

### The correction is small in aggregate, and now we know that

Over 17 trips with altimetry the grade correction moves the aggregate from 541
to 532 Wh/mi — under 2%. Climbs and descents cancel. This is the assumption
most casual Wh/mi estimates make implicitly; the value of the altimeter is that
it converts that assumption into a measurement, and it also lets individual
trips be interpreted honestly (the +1103 m trip at 642 Wh/mi and the -851 m
trip at 277 Wh/mi are not contradictory data, they are the same truck).

### What did not work

Both attempts to extract an elevation-independent road-load model failed, and
are recorded here so they are not retried without better data:

1. **Pooled road-load regression** (`E_seg = F0*d + k*int(v^2 dx) + grade terms`,
   1 km segments): returned a **negative** aero coefficient (physically
   impossible), R2 = 0.15 without a grade term and 0.27 with one.
2. **Steady-cruise windows binned by speed**, using the median within each bin
   as a grade-robust estimator: also returned a negative aero coefficient.
   Interquartile range within a single speed bin was 329–1024 Wh/mi.

The cause is straightforward: at 3000 kg a 3% grade is ~880 N against a road
load of only ~600 N at 90 km/h, so grade dominates the signal, and these five
logs contain only ~24 minutes of steady cruise in total.

**To get a level-road Wh/mi-vs-speed curve, a dedicated flat out-and-back run
is needed** — ideally steady-speed holds at several speeds on the same flat
road in both directions. That would nail Crr and CdA properly.

**Superseded 2026-08-03 — see the next section.** Retrying on the flat legs of
the 2026-07-24/26 weekend trip did produce a usable curve, though not by
least-squares on raw windows.

---

## Road load from the flat weekend legs (2026-08-03)

Scratchpad: `notes/artifacts/flat_section_roadload.py`.

Two genuinely flat stretches of the weekend trip were used — selected by
*phase*, not by whole session:

| Section | Window | Conditions | Steady windows |
|---------|--------|-----------|---------------:|
| `@20260726_142628` | 14:26–15:05, all phases dh = 0, at -97 m | 33–35 °C, rho 1.159–1.166 | 71 |
| `@20260726_160923` | 16:42–17:09, incl. the 17.9 mi @ 97 km/h run | 25–26 °C, rho 1.186–1.192 | 69 |

10 s windows requiring speed >= 40 km/h, spread <= 2 km/h and drift <= 1 km/h.
Cruise control was active (`0x644 cruise_mode` = 0xA) in 112 of 140 windows.
**Air density is computed per window from CAN** (`0x2C3` ambient + `0x4C1`
outside air temp) rather than assumed, so the aero regressor is `rho*v^2` and
its coefficient is directly CdA/2. Density spans 1.159–1.192 — a 3% effect the
earlier attempts ignored.

Forces are **apparent at the DC bus** (`0x462` traction power / speed), so they
include inverter, motor and gearbox losses and exclude accessory load.

### Result

Least squares on the raw windows is still **not identifiable**: R2 = 0.084, the
3-parameter form still returns a negative aero coefficient, and the split-half
check gives wildly different coefficients (`rv2` = +0.10 vs -4.72). The cause is
no longer grade but **sampling**: 94 of 135 windows sit in the 100–110 km/h bin,
leaving almost no leverage to separate a constant from a `v^2` term.

Fitting the **bin medians** instead — which both de-weights that one bin and uses
a grade-robust estimator within each — gives physically credible coefficients for
the first time:

| Estimator | Crr (apparent) | CdA (apparent) |
|-----------|---------------:|---------------:|
| Equal-weight bin medians | **0.0137** | **1.36 m²** |
| n-weighted bin medians | 0.0156 | 1.19 m² |
| *Expected for a 2014 Silverado 1500* | *0.010–0.014* | *1.1–1.4 m²* |

Level-road traction consumption (equal-weight fit, rho = 1.17):

| km/h | mph | Force N | Wh/mi |
|-----:|----:|--------:|------:|
| 40 | 25 | 500 | **224** |
| 56 | 35 | 594 | **266** |
| 72 | 45 | 720 | **322** |
| 88 | 55 | 877 | **392** |
| 104 | 65 | 1065 | **476** |
| 112 | 70 | 1171 | **524** |

Empirical bin medians behind that fit (no model):

| km/h bin | n | median N | IQR N | Wh/mi |
|----------|--:|---------:|------:|------:|
| 70–80 | 11 | 746 | 214 | 334 |
| 80–90 | 10 | 808 | 118 | 361 |
| 90–100 | 13 | 1029 | 316 | 460 |
| 100–110 | 94 | 1043 | 248 | 466 |

**Best-determined single point:** 100–110 km/h, n = 94, **1047 +/- 28 N =
468 +/- 12 Wh/mi** (traction only, statistical SE).

### Cross-check against the phase analysis

Adding the measured ~2.5 kW accessory load at 105 km/h (86 N = 38 Wh/mi) to the
468 Wh/mi traction figure gives **~506 Wh/mi at the HV bus**, which sits inside
the 405–531 Wh/mi flat-highway band measured independently from the phase
breakdown in `weekend-trip-2026-07-24.md`.

### Remaining limits

- **The noise floor is road undulation, not measurement.** Residual sd is 271 N,
  which at 3000 kg corresponds to a **0.92% grade**. Even a section held at
  constant barometric altitude undulates by about that much, and no analysis
  choice removes it — only more samples average it down.
- **Wind is not identified.** These are one-way runs, so it cannot be cancelled
  by direction pairing, and the 3-parameter fit that would estimate it from the
  linear term is unstable. Sensitivity: a 9 km/h headwind shifts the highway
  figure by **+/-33 Wh/mi**, an 18 km/h headwind by **+/-65 Wh/mi**. This
  dominates the +/-12 Wh/mi statistical uncertainty by 3–5x and is the single
  largest error term in the table above.
- The speed distribution is still poor below 70 km/h. The low-speed end of the
  curve is extrapolation, not measurement.
- An out-and-back run at several held speeds on one flat road would fix both the
  wind and the sampling problem at once, and remains the right way to do this
  properly.

---

## Encoding corrections found along the way

These were discovered while cross-checking energy channels and are recorded
here.

> **Status update 2026-08-02 — the 0x598 entry below is now resolved and the DBCs
> have been edited.** `BO_ 1432` in `epri-pt-bus.dbc` is a stub with its `SG_`
> entries removed, and the corrected signals live in
> `vtrux-powertrain-experimental.dbc` as `ess_power` / `gen_power` / `trac_power`.
> The measured-V×I evidence recorded below was independently confirmed twice: by a
> channel-balance test on raw frames, and by Ghidra analysis showing the signed
> decode is a defect in the EPRI app itself rather than a decompile artifact. Any
> other corrections in this section remain unapplied.

### `0x598` DBL_ESSPwrAvg / DBL_TracPwrAvg — signedness

`epri-pt-bus.dbc` declares these as **signed** 16-bit with offset 0.
`vtrux.md` and `vtrux-powertrain-experimental.dbc` (`gen_power`) say
**unsigned centered at 32768** (offset -327.68). Tested both interpretations
against measured V x I:

| Field | Interpretation | r | mean abs error |
|-------|---------------|--:|---------------:|
| `p598_gen` | centered @ 32768 | **+0.9998** | **209 W** |
| `p598_gen` | signed int16 | -0.46 | 327,695 W |
| `p598_ess` | centered @ 32768 | +0.60 to +0.81 | ~8–10 kW |
| `p598_ess` | signed int16 | -0.24 to -0.60 | ~328 kW |
| `p598_trac` | centered @ 32768 | +0.74 to +0.79 | ~8–11 kW |
| `p598_trac` | signed int16 | -0.33 to -0.50 | ~328 kW |

#### Why gen_power matched so much better: the channels are filtered differently

The three centered-decode rows above differ enormously (209 W vs ~8–11 kW), and
it is tempting to read that as gen_power being "more correct". It is not — it is
a **filtering** difference, confirmed 2026-08-02 by sweeping a moving-average
window over the measured V×I and re-correlating (`vtruxevapdrivelog4`):

| Boxcar window | `ess` vs `0x410` V×I | `trac` vs `0x462` V×I | `gen` vs `0x482` V×I |
|--------------:|---------------------:|----------------------:|---------------------:|
| 0 s (raw) | r=0.807, 10084 W | r=0.794, 11381 W | **r=0.9998, 209 W** |
| 5 s | r=0.968, 4420 W | r=0.904, 5974 W | r=0.988, 1586 W |
| **8 s** | **r=0.984, 2850 W** | **r=0.916, 4468 W** | r=0.980, 2084 W |
| 15 s | r=0.929, 5301 W | r=0.871, 7011 W | r=0.960, 3032 W |

`ess_power` and `trac_power` peak sharply at a **~8 s boxcar-equivalent
filter**; `gen_power` degrades monotonically under *any* smoothing and is best
raw. So the `Avg` in the original EPRI names (`DBL_ESSPwrAvg`,
`DBL_TracPwrAvg`) is literal and applies to exactly the two fields carrying it,
while the B2–B3 generator field is instantaneous — most likely a direct
passthrough of the `0x482` V×I product.

8 s is the boxcar-equivalent; the real filter is probably IIR/exponential, so
treat it as "~8 s equivalent" rather than a literal window.

**A subtraction hypothesis was also tested and rejected** — `trac_power` is not
computed arithmetically from the other two fields:

| Hypothesis | mean \|diff\| | exact matches |
|------------|--------------:|--------------:|
| `trac == ess + gen` | 521 counts (5.2 kW) | 0 / 1462 |
| `trac == ess - gen` | 4215 counts | 0 / 1462 |
| `trac == gen - ess` | 3481 counts | 0 / 1462 |

`ess + gen` is much the closest of the three and its ~5 kW residual is the right
order for accessory load plus filter mismatch, so the three fields do obey the
physical power balance — but none is computed bit-for-bit from the others.

**Practical consequence:** `0x598` is an HCU *virtual sensor* bundle (the EPRI
message name is `EPRI_HCU_VIRTSENS_7_PwrStatAvg_0598`, the same VIRTSENS family
as the `0x599` pressures), computed inside the VCM rather than measured at a
device. `0x462` and `0x482` by contrast are broadcast by the Dana TM4 CO150
inverters themselves and are instantaneous hardware measurements. **Use
`0x410` / `0x462` / `0x482` for energy integration, never `0x598`.** This also
explains why the accessory residual closes so cleanly at ~2 kW: all three
channels used for that balance are unfiltered direct measurements.

**Centered-at-32768 is correct; the DBC's `signed` declaration is wrong.** The
327 kW error under the signed interpretation is exactly the 32768 x 10 W offset
being applied in the wrong direction.

**RESOLVED 2026-08-02.** Two further independent checks agreed with the table
above, and the DBCs were corrected. (1) The channel balance
`trac = ess + gen` closes only under the centered reading — residual sd 7.4 kW
(`vtruxevapdrivelog4part2`) and 2.9 kW (`vtruxcurrentlimitingtest`), versus
327 kW and 371 kW under the signed reading, which also implies a 655 kW
frame-to-frame discontinuity every time the raw value crosses 0x8000
(`artifacts/check_0598_balance.py`). (2) Ghidra analysis of the EPRI app showed
the signed decode is **the app's own defect**, not a decompile artifact:
`FUN_00045af0(v, 0x10)` is exactly `(int16_t)v` over all 65536 inputs and
`parseEPRIMessage` contains no bias operation on either the ARMv7 or ARM64
slice. `epri-pt-bus.dbc` had faithfully reproduced an app bug. See
`epri-decompile.md` 0x0598.

**Amplitude context for the error column** — these are *disagreements between
two channels*, not power levels. The `p598_gen` figures come from
`vtruxevapdrivelog4`, where generator power swept -5.2 kW to +55.6 kW (peak
56.9 kW). A 209 W mean absolute error is therefore ~0.4% of full scale, and
that is what makes the match meaningful.

Do **not** read the same significance into the `vtruxscottsvalleydrive` run of
this check, which reports r = 0.9953 / 22 W: the engine never ran in that log,
so generator power only wandered between -1.75 and +1.54 kW. Both channels
agreeing on approximately zero is close to vacuous. The evidence for the
encoding rests on the log with real generator operation.

The `gen_power` (B2-B3) match simultaneously confirms both
the `0x598` gen_power scale and the `0x482`-derived generator power used here.
The weaker correlation on the ESS and TRAC fields is expected — they are
explicitly *averages* (`PwrAvg`), so instantaneous comparison against V x I is
poor by design.

### `0x120` VehicleOdometer — 256x scale error

`epri-obd-bus.dbc` decodes `0x120` as a 32-bit BE field at 0.015625 km/count.
On `vtruxevapdrivelog4` this yields a 6888 km delta for a 27 km drive — a factor
of 255.1. Dividing by 256 gives 26.906 km, matching the `0x3E9` rolling count
(26.912 km) to 0.02%. The field is misaligned by one byte, or the message is
24-bit rather than 32-bit and EPRI over-declared it.

### `0x3E9` distance unit

`epri-obd-bus.dbc` gives `ECM_DistRollCntAvgDrvn_dist` in km, but the values
only make sense as metres at the same 0.125 scale — confirmed by agreement
to 0.15% across four independent distance sources.

---

## Observations (unconfirmed)

These are working hypotheses raised by the data, not confirmed findings.

### Motor-speed ratio vs the open axle-ratio question

The measured 62.48 rpm/(km/h) implies a total ratio near 9.15:1 for a ~2.44 m
tire circumference, which would match 2.68 x 3.42 (GU6, the factory axle) rather
than 2.68 x 3.73 (GT4). **However this is entirely tire-size dependent** — with
stock 265/65R18 (~2.51 m) the same measurement favours 3.73 instead. This
measurement cannot settle the GU6-vs-GT4 question without
the actual fitted tire size. Recording the measurement only.

### SoC is not linear in energy

Pack capacity implied by measured energy over the observed SoC swing differs
markedly by SoC band:

| Log | SoC band | Net energy | Implied full-pack |
|-----|----------|-----------:|------------------:|
| `vtruxevapdrivelog4` | 93.6% -> 73.4% | 3.284 kWh | 16.3 kWh |
| `vtruxscottsvalleydrive` | 81.4% -> 49.6% | 8.023 kWh | 25.3 kWh |

Hypothesis: the A123 BMS SoC estimate is non-linear in energy (expected on LFP,
whose flat OCV curve makes OCV-based SoC estimation poorly conditioned,
particularly near the top of the range). **Practical consequence regardless of
cause: do not use delta-SoC as an energy proxy.** Use integrated pack V x I.

---

## Caveats

- **Vehicle mass assumed 3000 kg.** Not documented anywhere in this repo. It
  affects only the grade and kinetic-energy terms, never the headline
  energy/distance figures.
- Two of the four trips have no usable altimeter (engine ran continuously, or
  PT-only capture), so their figures are elevation-uncorrected and could each be
  off by a few tens of Wh/mi in either direction.
- Charging losses are excluded throughout. Wall-to-wheel consumption is higher.
- Four of 22 trips have no usable altimeter (engine ran continuously, or
  PT-only capture). They are included in the headline aggregate but not in the
  grade-corrected one.
- Trips at nearly identical average speed still differ substantially — e.g.
  `vtruxevapdrivelog4` at 743 Wh/mi vs `@20260714_075545` at 487 Wh/mi, both
  around 62–68 km/h with >90% moving. Distance error is ruled out (both
  validated against `0x625`). Regen recovery (7% vs 22%) and accel/decel
  cycling explain most of it; genuine load or terrain differences cannot be
  excluded.
- Only the 20 largest of 1072 Android sessions were processed (~25 GB of
  32.8 GB). The remainder are mostly short fragments, but the sample is
  size-biased toward long drives by construction.

---

## Open items

- [ ] Dedicated flat out-and-back steady-speed run to extract Crr and CdA and
      produce a level-road Wh/mi-vs-speed curve.
- [ ] Fuel-to-electricity efficiency (Wh per gallon of gasoline). Generator
      electrical output is already solved and validated; the open part is the
      fuel denominator (`0x3D1` `ECM_InstFuelConsmpRate_volPt`, with `0x4D1`
      fuel level as a coarse cross-check).
- [ ] Deep dive on the 2026-07-24/26 weekend trip, which contains long flat
      highway running, engine-on hill climbs and all-electric descents as
      cleanly separated regimes. Trips `@20260724_162517`, `@20260724_172621`,
      `@20260724_211556` (+1103 m), `@20260726_124205` (-851 m),
      `@20260726_142628` and `@20260726_160923` are already in the table above
      and together cover 368 miles.
- [ ] Fix `0x598` signedness in `epri-pt-bus.dbc`, the `0x120` 256x scale, and
      the `0x3E9` distance unit.
- [ ] Confirm vehicle mass (weigh, or find the VIA conversion spec).
- [ ] Establish fitted tire size, which would let the 62.48 rpm/(km/h)
      measurement bear on the GU6-vs-GT4 axle question.
