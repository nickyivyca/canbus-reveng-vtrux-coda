# Coda — Energy Efficiency in Wh/mile

Corpus-wide energy accounting: how much energy the car uses per mile, split into
drivetrain / HVAC / 12 V aux, and what that costs at the wall once charging losses are
included.

**Source:** InfluxDB `canbus-data`, the whole uploaded corpus decoded against
`CODA-B-CAN.dbc` and `CODA-D-CAN.dbc`. No raw-log parsing.
**Tools:** `artifacts/coda_efficiency.py` (pack side), `artifacts/coda_charge_efficiency.py`
(wall side), `artifacts/coda_efficiency_crosscheck.py` (validation),
`artifacts/coda_bus_coverage_timeline.py` (capture coverage).
**Date:** 2026-08-25. Corpus as of that date: 175 usable trips / 898.4 mi of driving,
10 charge events / 75.2 kWh from the grid.

> Supersedes the 2026-08-23 run (102 trips / 595.0 mi). The 0x276 bus fix in Sec.5 plus
> subsequent uploads brought the corpus from 595.0 to 898.4 mi; every figure below is from
> the re-run, taken after the 2026-08-25 full re-upload (see `../../tools/tools.md`).

---

## 1. Headline

### From the pack — the number that predicts range

175 trips, 898.4 mi, 31.7 h. Distance-weighted (total energy over total distance, never
an average of per-trip figures).

| Bucket | Energy | Wh/mi | Share |
|---|---|---|---|
| Drivetrain (net of regen) | 239.36 kWh | **266.4** | 90.6% |
| HVAC total | 11.56 kWh | **12.9** | 4.4% |
| &nbsp;&nbsp;PTC cabin heater | 4.64 kWh | 5.2 | 1.8% |
| &nbsp;&nbsp;A/C compressor | 6.92 kWh | 7.7 | 2.6% |
| 12 V aux (via DC-DC) | 13.16 kWh | **14.7** | 5.0% |
| **Net from pack** | **264.08 kWh** | **294.0** | 100% |

Gross discharge 320.0 kWh (356.2 Wh/mi); regen recovers 55.9 kWh (62.2 Wh/mi, 17.5% of
gross).

**The HVAC row is diluted and should not be read as a load figure** — most trips never
switch HVAC on. See Sec.2a for what it costs while running.

### From the grid — the number that predicts cost

| Stage | Energy | Efficiency |
|---|---|---|
| Grid in | 75.20 kWh | |
| Charger DC out | 61.83 kWh | conversion **89.6%** |
| Arrived at pack | 60.34 kWh | delivery **90.3%** |
| | | **wall-to-pack 80.2%** |

| | Wh/mi |
|---|---|
| From the pack (range) | **294.0** |
| From the grid (cost) | **366.4** |
| Charging overhead | 72.4 (+24.6%) |

Grossed up to the wall: drivetrain 332.1, 12 V aux 18.3, A/C 9.6, PTC 6.5 Wh/mi.

---

## 2. Conditions

### HVAC

| | Trips | Miles | Total | Drivetrain | HVAC | 12 V |
|---|---|---|---|---|---|---|
| HVAC off | 105 | 566.9 | 291.5 | 279.0 | 0.1 | 12.5 |
| Heater (PTC) on | 24 | 138.6 | 309.1 | 252.7 | 35.6 | 20.8 |
| A/C on | 53 | 228.9 | 300.9 | 240.1 | 42.3 | 18.4 |

HVAC averages down to 12.9 Wh/mi across the corpus only because most trips do not use
it. On the trips where it runs it is 35–42 Wh/mi, and while it is actually drawing power
it is ~1.1 kW (Sec.2a). The heater-on and A/C-on rows show a
*lower* drivetrain figure than HVAC-off, which is a confound rather than a finding:
those trips skew slower and shorter (see the speed table).

### 2a. What HVAC costs while it is actually running

The tables above divide HVAC energy by **all** miles, and even the "Heater on" / "A/C on"
rows distance-weight across the *whole* trip including the miles where HVAC was off. Neither
is an HVAC-active figure, and the difference is large. Over the 70 trips where HVAC ran at
all (331.4 mi, 13.7 h):

| | |
|---|---|
| Headline, spread over all 898 mi | **12.9 Wh/mi** |
| Spread over the trips that use it | **34.8 Wh/mi** (2.7x) |
| Mean power over those whole trips | 841 W |
| Duty cycle (PTC or compressor above 0.2 kW) | **77.4%** |
| **Mean power while actually drawing** | **1086 W** (a further 1.3x) |

Two dilutions stacked; the larger by far is the 105 trips that never switch it on.

### 2b. HVAC cost falls with trip length — pull-down vs steady state

Binning the same 70 trips by duration:

| Trip duration | Trips | Miles | HVAC Wh/mi | Duty | W while on | Mean mph |
|---|---|---|---|---|---|---|
| 0–5 min | 10 | 11.2 | **64.3** | 90% | 1409 | 19.8 |
| 5–10 min | 32 | 97.8 | 41.6 | 77% | 1273 | 23.7 |
| 10–20 min | 20 | 89.8 | 41.1 | 87% | 1020 | 21.5 |
| 20–40 min | 5 | 51.3 | 37.2 | 66% | 1384 | 24.7 |
| >40 min | 3 | 81.3 | **13.9** | 69% | **594** | 29.6 |

A 4.6x spread. Two effects compound: mean power *while running* falls 2.4x (1409 -> 594 W)
as the cabin approaches setpoint, and long trips also run faster so that lower load is
spread over more miles. Duty cycle stays high throughout (66–90%), so the on-fraction is
not what drives it — the load level is. The 20–40 min row bucks the trend on 5 trips.

A single trip shows the same curve internally: on `coda_20260818_135227` the compressor
starts at 1.21 kW and settles to ~0.4 kW over the first 40 minutes (Sec.2d).

Tool: `artifacts/trip_profile_analysis.py` phases 1–2.

### Average speed

| Avg speed | Trips | Miles | Total | Drivetrain | HVAC | 12 V |
|---|---|---|---|---|---|---|
| <15 mph | 17 | 31.4 | 317.6 | 251.2 | 37.0 | 29.4 |
| 15–25 mph | 77 | 213.4 | 291.5 | 247.3 | 23.8 | 20.4 |
| 25–35 mph | 54 | 305.5 | 298.2 | 266.5 | 17.1 | 14.6 |
| 35–45 mph | 22 | 215.5 | 287.8 | 276.0 | 0.5 | 11.3 |
| ≥45 mph | 5 | 132.6 | 292.7 | 285.1 | 0.0 | 7.6 |

HVAC and 12 V are time-based loads, so their Wh/mi falls as speed rises — 29.4 → 7.6
Wh/mi for the 12 V system across the range. Drivetrain moves the other way.

### Charging

| Split | Events | Grid kWh | Pack kWh | Wall-to-pack |
|---|---|---|---|---|
| ≥6 kW | 8 | 59.97 | 48.80 | 81.4% |
| 4–6 kW | 1 | 9.02 | 7.03 | 77.9% |
| 2–4 kW | 1 | 6.21 | 4.52 | 72.8% |
| ~208 V site (mean 202.0 V) | 7 | 47.13 | 37.02 | 78.5% |
| ~240 V home (mean 233.1 V) | 3 | 28.08 | 23.32 | 83.1% |

Two levers: charge rate (fixed overhead spread over a smaller flow) and supply voltage.
The 2–4 kW and 4–6 kW rows are single events each — directional, not established.

---

### 2c. Highway vs city — elevation has to be controlled

Binning by speed alone mostly measures terrain here. Two 16.3 mi trips in the corpus come in
at 136.8 and 445.3 Wh/mi — same distance, opposite directions of one hill. So trips are
first profiled into speed classes from the odometer (0x491 differenced over 60 s bins;
there is no usable instantaneous speed on the bus, the ESC wheel-speed scale being
unresolved), and then **out-and-back pairs are averaged to cancel elevation**.

Uncontrolled, by speed class:

| Class | Trips | Miles | Mean mph | Drivetrain | 12 V | HVAC | Regen |
|---|---|---|---|---|---|---|---|
| Highway (>=50% of time at 45+ mph) | 10 | 187.8 | 47.5 | 281.7 | 7.7 | 0.1 | 9.3% |
| Mixed (15–50%) | 70 | 432.4 | 30.0 | 265.4 | 13.3 | 10.6 | 18.5% |
| City (<15%) | 50 | 219.8 | 22.2 | 259.1 | 20.8 | 27.3 | 20.5% |

With elevation cancelled by pairing (37 pairs found: two trips within 16 h and 10% on
distance — the logger opens a session per screen-on, so an out-and-back nearly always spans
two sessions):

| | Pairs | Miles | Drivetrain | 12 V |
|---|---|---|---|---|
| Highway pairs | 3 | 88.7 | **280.2** | **6.6** |
| City pairs | 34 | 449.9 | **268.3** | **14.8** |

**Elevation control halves the apparent highway penalty**, from +8.7% uncontrolled to
**+4.4%**. That the pairing works is visible directly: the `coda_20260603_205514` pair reads
283.5 Wh/mi where its two halves were 445.3 and 136.8 individually.

The larger effect is the other way. **12 V is 2.2x cheaper per mile on the highway**
(6.6 vs 14.8 Wh/mi) and HVAC likewise, because both are time-based. The drivetrain's aero
penalty is largely offset by spreading the fixed hotel loads over more miles, which is why
total Wh/mi barely separates the two classes.

Tool: `artifacts/trip_profile_analysis.py` phases 3–4.

### 2d. Case study: the 2026-08-18 out-and-back

The cleanest natural experiment in the corpus — same road, opposite directions, two hours
apart, with opposite driving styles. Driver's account: outbound climbs slow winding roads
and finishes on the highway, close enough to the limit that power limiting was felt, A/C
running a good part of the way; return is highway essentially throughout with minimal A/C.
The data matches on every point.

| | Outbound | Return |
|---|---|---|
| Session | `coda_20260818_135227` | `coda_20260818_193350` |
| Miles / avg mph | 35.1 / 27.4 | 32.6 / 48.5 |
| Total Wh/mi | 307.6 | 272.5 |
| Drivetrain | 274.2 | 263.7 |
| A/C | **21.3** | **0.0** |
| 12 V | 12.1 | 8.8 |
| Regen % of discharge | 12.0% | 8.1% |
| SoC | 94.3% -> 54.2% | 100% -> 72.3% |
| Mean cell T | 20.0 degC | 26.5 degC |
| BMS discharge limit | **396 -> 174 A** | never derated |

Pair total 67.7 mi -> drivetrain **269.1**, 12 V **10.5**, HVAC **11.0** Wh/mi, elevation
cancelled.

The outbound speed profile is 0–18 mph for the first 40 minutes and then sustained ~60 mph,
so the heavy load arrives at the *end*, at low SoC — which is why this leg derated and the
return, running the same road at 100% -> 72% SoC, did not despite reaching the same
-119 A peak. The derate is analysed in `battery-degradation.md` Sec.5; it extends that
section's onset-SoC trend with a 2026-08-18 point at 59.4% / 3020 mV, `VminId` = Cell95.

Note the two legs are **not** matched on SoC or temperature (the car was charged at the
destination), so the leg-to-leg efficiency difference carries those confounds as well as
the driving style. The pair average is sound for elevation; it is not a controlled A/B on
speed alone.

Tool: `artifacts/aug18_roundtrip_analysis.py`.

## 3. Method

### Signals

| Bucket | Source | Notes |
|---|---|---|
| Pack energy | 0x275 `BMSDriveLimits` — `PackVoltage` × `PackCurrent` | `PackCurrent` −ve = discharge, +ve = charge/regen (independently re-confirmed here; matches `artifacts/packcurrent_sign_check.py`) |
| PTC heater | 0x276 `HVACStatus` `PTC_PowerConsumption` (kW) | B CAN native (AICM); absent from InfluxDB for pre-2026-08-23 uploads — see §5 |
| A/C | 0x276 `ACCM_PowerConsumption`, else 0x439 `AC_Compressor_Status` `ACTUAL_POWER_CONSUMPTION` | the two agree to +0.0% |
| 12 V aux | 0x1D5 `DCDCStatus1` `HV_Input_Current` × `PackVoltage` | HV side, not LV — see §4 |
| Distance | 0x491 `IPK_Cluster` `Primary_ODO` | the only confirmed distance reference; ESC wheel-speed scale is still TBD (`driver-inputs.md`) |
| Grid | 0x27B `CMSInputValues` + 0x27D `CMMInputValues` `ACInPower` | **both units must be summed**, each reports only its own ~15 A leg (`../../notes/ac-resistance.md`) |
| Charger DC out | 0x27C + 0x279 `HVOutVoltage` × `HVOutCurrent` | |
| Cross-check | 0x1C0 `MCM_CoreTelemetry` `HV_Voltage` × `HV_Current` | D CAN; `HV_Current` +ve = discharge, opposite sign to 0x275 |
| Covariates | 0x383 `SoC`/`HVBattCharging`, 0x390 `FrontInletAirTemp`, 0x382 `Cell_T_avg` | inlet air is an ambient *proxy* only (`outside-air-temp-investigation.md`) |

Drivetrain is a **residual**: `pack_net − HVAC − 12 V aux`. It therefore absorbs any
unmodelled HV load and all measurement error. §4 quantifies how much that is.

### Integration

Every channel is pulled onto a shared **server-side 1 Hz grid** (`GROUP BY time(1s)`),
which InfluxDB aligns to the epoch, so all channels land on identical bucket boundaries
and can be index-aligned without resampling. Energy is a zero-order-hold sum over that
grid.

Using 1 s means for V and I separately, rather than the mean of their product,
introduces a covariance error. Bounded: within a 1 s window under hard acceleration,
current swings ~±30 A and pack voltage sags ~∓1.5 V of 340, so the term is ~45 W against
~34 kW — about 0.13%.

### Trips, not sessions

A trip runs from just before one odometer increment to the last increment within
`--max-stop` seconds (default 300). Distance and energy use the *same* window, so the
energy counted is exactly the energy that produced the distance counted.

This is load-bearing. Six sessions are ~24 h captures with the logger left running while
the car sat; charging a full day of parked 12 V draw against the half mile the car moved
produced figures of 8,000–18,000 Wh/mi that dominated the aggregate. Energy outside any
trip is reported separately as `parked_Wh` (19.5 kWh across the corpus) and charged to
no mile.

Trips under 0.5 mi are dropped — at 0.1 km odometer granularity the distance error alone
would be tens of percent.

---

## 4. Validation

| Check | Result |
|---|---|
| Residual drivetrain vs. inverter-measured (0x1C0) | **−2.1%** over 132 trips / 763.4 mi |
| Pack↔inverter gain (regression slope) | 1.002–1.007 across sessions |
| PackVoltage ÷ MCM HV_Voltage | 0.994 at rest, 1.003 under >80 A load |
| A/C: 0x276 vs 0x439 | **+0.0%** over the 63 trips carrying both |
| DC-DC HV input vs pack power, quiescent | within ~22 W |

The −2.1% agreement between two independent current sensors over 765 miles is the main
confidence anchor for the drivetrain and pack numbers. Per-drive scatter is larger — one
session (`frombonnydoon`) came in at +15.7% — but the intercepts flip sign between
sessions (+715 W, −254 W), so it is scatter, not a systematic bias.

### The 12 V bucket uses the HV side, and why

Pooling 343k quiescent seconds (HV up, no HVAC, inverter idle, not charging):

| | Mean power |
|---|---|
| Pack draw | 227.2 W |
| DC-DC HV input (`HV_Input_Current` × `PackVoltage`) | 204.8 W |
| 12 V output as reported (`Voltage_14V` × `Current_14V`) | **351.9 W** |

The 12 V reading exceeds the *entire pack draw* in **99.4%** of those seconds, which is
physically impossible. The HV-side figure exceeds pack draw in 0.1% and otherwise sits
~22 W below it, consistent with small residual HV loads. So the accounting uses the HV
side; the LV pair is carried in the CSV as `aux12v_lv_reported_Wh` for reference only.

> **Resolved 2026-08-24 — the DBC is right, and the HV side is the wrong suspect.**
> The Delphi U2C manual (`dcdc/U2C Manual Rev03_2-15-2011.pdf`, now in the repo) is the
> primary source for this converter, and it confirms every DC-DC field verbatim:
> `Current_14V` really is 7 bits of byte 6 at 2 A/count. The DBC decodes the manual's own
> worked example exactly. So the earlier scale hypothesis is dead.
>
> The U2C also reports its own calculated loss (0x48A `U2C_Power_Loss`), which closes the
> balance with no external reference — `(P_LV + P_loss) / I_HV` should equal pack voltage:
>
> | HV input current | balance | implied efficiency |
> |---|---|---|
> | < 1.5 A | 1.13–2.09× | impossible |
> | ≥ 1.5 A | **0.97–0.99×** | **89–92%** |
>
> Over 962k frames the implied pack voltage is 353.8 V median against the BMS's own
> 338.0 V — a ratio of 1.046. Above 1.5 A the converter's three numbers add up and give a
> textbook efficiency curve; below it they do not, and `U2C_Power_Loss` reads exactly 0,
> so the U2C is not computing loss in that regime. The divergence is not charging-related
> (1.42× charging vs 1.38× not).
>
> **What this means for the table above:** the quiescent pool sits at ~0.6 A HV input,
> squarely inside the unreliable band. The observation stands but the sign of the error
> is now the open question — if the LV reading is the sound one there, the HV side
> *under*-reports at light load and this 12 V bucket is **understated**, not the reverse.
> An hour with a clamp meter on the 12 V output at a known light load would settle it.
> Nothing in the accounting has been changed. See `dcdc/README.md` and
> `artifacts/dcdc_12v_scale_check.py`.

### PTC honesty

Regressing the unexplained gap (`P_pack − P_mcm − P_hvac − P_aux`) on reported PTC power
across the 12 heater sessions gives per-session slopes scattered from −0.60 to +0.23 with
no consistent sign. **No evidence that `PTC_PowerConsumption` under-reports.**

### Unaccounted charger loss

5.9% of charger DC output (3.67 kWh of 61.83) does not appear at the pack and is not
explained by the 12 V draw during charging (2.33 kWh) or HVAC (0.00 kWh).
`charging-analysis.md` already noted the same thing on a single frame: CMM 8.625 A +
CMS 8.594 A = 17.22 A into a pack shunt reading 16.4 A.

> **Hypothesis (not acted on):** a calibration offset between the charger output current
> sensors and the pack shunt, rather than real loss — 275 W of cable/contactor heating at
> this current would be implausible. Note the pack shunt's *discharge* gain is validated
> to ~0.3% by the inverter cross-check above, so if there is a shunt error it is
> charge-direction-specific.

---

## 5. Missing PTC data is an upload artifact, not capture coverage

0x276 `HVACStatus` appears in InfluxDB only in sessions that also recorded D CAN. Across
262 sessions the rule "0x276 is in InfluxDB iff a `d_can` channel was captured" holds in
**261**; the one exception, `coda_20260505_194301`, is a 1,000-frame fragment matching no
anchor set, so it was tagged `ch2` and escaped a bus-keyed filter. That near-perfect rule
is the tell: it is our uploader's exclusion list, not the vehicle.

> **Resolved 2026-08-23.** `projects/coda/README.md` was right and this corpus observation was an
> artifact of our own uploader. `influx_upload.py` carried
> `{"can_id": 0x276, "bus": "b_can"}` as a gateway-dedup exclusion, so the B CAN copy
> was dropped at upload time by construction — InfluxDB could never have shown it.
>
> The raw logs say the opposite, and say the exclusion was pointed at the wrong bus:
>
> - 0x276 is on B CAN in **all four** multi-bus captures, at the same frame count as on
>   D CAN (`driverinputpart4.log`: 8,854 on B vs 8,831 on D), and on **zero** C CAN
>   channels — so the "also on C CAN" guess above was wrong too.
> - It is in **239 of 239** non-empty Android sessions, including **all 73** B-only ones.
> - The B copy is faithful, not a masked bridge: 99.89% / 100.00% of B frames are
>   byte-identical to the nearest-in-time D frame, with identical unique-payload sets.
> - **B CAN is the native bus.** In `codapumprunningwhencaroffthenturningoncar.log` and
>   `DCDCRUNNingwithoutkeyon-then-key-on.log` the AICM transmits 0x276 on B CAN from
>   +0.07 s with D CAN fully asleep; 0x276 reaches D CAN only when D CAN wakes
>   (+23.1 s, +41.9 s), landing 65–94 ms *ahead* of D CAN's own 0x308/0x312. Corroborated
>   by the system diagram, which puts all HVAC on B CAN.
>
> The exclusion now targets `d_can` (`tools/influx_upload.py`). **Sessions uploaded before
> 2026-08-23 still lack the signal.** Changing the exclusion changes the profile encoding,
> so `influx_sync.py --plan` schedules a full `reupload_file` of all 262 Coda sessions
> (20.5 GB), not a targeted per-ID repair — `--delete` drops a whole session regardless of
> `--only-id`, so there is no cheap in-place path that also keeps the manifest honest.
> **Every number in this document predates that re-upload.** Method and per-session data:
> `artifacts/x276_bus_presence.py`, `artifacts/x276_bus_presence.csv`.

The tables below therefore describe the *upload*, not the trips or the captures. Note that
0x439 `AC_Compressor_Status` *is* on B CAN and was uploaded from it, so the A/C is measured
even in those sessions. Only the PTC heater is unmeasured, and those trips are flagged
`ptc_measured=0` and kept out of the headline so heater energy cannot land silently in the
drivetrain residual.

Bus combinations by month (`coda_bus_coverage_timeline.py`). The "Has 0x276" column
is what InfluxDB held before the fix; the raw logs carry it in 239 of 239 non-empty
sessions:

| Month | Sessions | Bus combos | Has 0x276 |
|---|---|---|---|
| 2026-02 | 17 | BC:6, BCD:11 | 11/17 |
| 2026-03 | 32 | **B:25**, BC:6, BCD:1 | 2/32 |
| 2026-04 | 69 | B:43, BD:16, BCD:4, BC:3, D:3 | 23/69 |
| 2026-05 | 54 | BD:49, BCD:4 | 54/54 |
| 2026-06 | 64 | BD:57, BCD:7 | 64/64 |
| 2026-07 | 26 | BCD:18, BD:8 | 26/26 |

Excluded miles track it precisely:

| Month | Kept mi | Excluded mi | Loss |
|---|---|---|---|
| 2026-02 | 29.3 | 0.0 | 0% |
| 2026-03 | 41.3 | 5.5 | 12% |
| 2026-04 | 144.0 | 2.1 | 1% |
| 2026-05 | 196.7 | 15.7 | 7% |
| 2026-06 | 250.5 | 15.3 | 6% |
| 2026-07 | 86.2 | 5.0 | 5% |
| 2026-08 | 150.2 | 32.6 | 18% |

**After the fix**, only **one** session in the whole corpus genuinely lacks 0x276
(`coda_20260426_150934`, an 11-signal fragment). The 20 trips / 76.2 mi still excluded are
sessions where 0x276 *gaps out inside the trip window* — 24 h logger captures — not missing
bus coverage. Re-uploading cannot recover them, and the tool's "B-CAN-only captures with no
0x276" wording is now stale.

The residual May/June losses are not bus coverage — they are the 24 h logger sessions
where 0x276 gaps out inside the trip window.

**Every excluded mile above is recoverable from data already on disk** — the raw logs
carry 0x276 for all of them. That includes all of March (46.9 mi, 100% excluded) and
most of April (91.3 mi, 63%), which are the heater months whose absence is what makes
the PTC bucket sample-limited. This does not need a winter of three-bus captures; it
needs a re-upload.

**The corpus is still not seasonally balanced, but the bus-coverage cause is gone.**
Retention is now 92% overall and 88–99% in every month except 2026-08 (82%). What remains
is the calendar: this corpus starts in February, so it holds one shoulder season and one
summer, and PTC sits at 5.2 Wh/mi against A/C at 7.7. A genuine winter would move the HVAC
split and nothing else here predicts by how much. The drivetrain and 12 V buckets are not
sample-limited in the same way.

---

## 6. Gotcha: never use InfluxQL `fill(previous)` for integration

The server-side fill is unbounded and cannot distinguish "value held steady" from
"message stopped transmitting". One charge log (`coda_20260715_164623`) has a 2 h charge
followed by a 24 h silence; `fill(previous)` carried the last ~6 kW reading across the
whole gap and the session integrated to **146.75 kWh out of a 31 kWh car**.

Both scripts now fetch with the default null fill and apply a bounded hold in Python
(`ffill(..., max_hold_s=5)`). The write policy guarantees a point at least every second
while a message is live, so a gap beyond a few seconds means the message stopped.

Effect of the fix on the drive side was small — 293.2 → 293.6 Wh/mi on the corpus as it
stood then — but `parked_Wh` fell from 67.6 kWh to 15.8 kWh, almost entirely this artifact.

---

## 7. What is not in these numbers

- **The pack's own round-trip loss.** The wall-side figure counts energy arriving at the
  pack terminals, not energy retrievable from it later. True wall-to-wheels is somewhat
  worse than 366.4 Wh/mi.
- **Parked HV-on draw.** 19.5 kWh across the corpus, real grid cost but no miles. The
  sample is biased — it only counts time the logger happened to be running — so it is not
  scaled into the per-mile figures.
- **Vampire drain with HV down**, which no captured message measures.
- **Charging sessions the corpus missed.** Two sessions show grid power but have too few
  points to integrate and are skipped.

---

## 8. Re-running

```bash
py tools/influx_sync.py --apply                              # only if new logs landed
py projects/coda/notes/artifacts/coda_efficiency.py          # ~0.7 s if nothing changed
py projects/coda/notes/artifacts/coda_charge_efficiency.py   # ~0.4 s
```

Both are incremental: a session is re-integrated only when its InfluxDB point counts
change (new upload or DBC re-decode) or `--refresh` is passed. Full rebuild with the
inverter cross-check is `--refresh --mcm` (heavier; pulls 0x1C0).

Useful flags: `--since 2026-05`, `--include-partial`, `--max-stop`, `--min-mi`,
`--session NAME`.

Artifact inventory and per-file detail: `artifacts/README.md`.

---

## 9. Open questions

1. ~~`Current_14V` scale (§4) — needs a clamp meter or a known-load sweep.~~
   **Resolved 2026-08-24**: the scale is correct per the Delphi U2C manual. What
   remains is which side under/over-reports below 1.5 A HV input, and therefore
   whether the 12 V bucket is understated (§4).
2. The 5.9% unaccounted charger→pack gap (§4) — charge-direction shunt calibration?
3. ~~0x276's actual bus, and correcting `projects/coda/README.md` (§5).~~ **Resolved 2026-08-23**:
   B CAN native, `projects/coda/README.md` was correct, uploader exclusion fixed. Remaining work is
   full re-upload of the pre-2026-08-23 Coda sessions (20.5 GB, scheduled by
   `influx_sync.py --plan`) and re-running both scripts (§5).
4. ~~Winter three-bus captures to make the HVAC split seasonally representative (§5).~~
   Superseded by #3 — the winter miles are already captured, just not uploaded.
5. ESC wheel-speed scale, which would give a distance reference finer than the 0.1 km
   odometer and make sub-0.5 mi trips usable (`driver-inputs.md`). It would also let
   Sec.2c classify highway/city per-second instead of per-60 s-odometer-bin.
6. Only 3 highway pairs survive the elevation-cancelling filter (Sec.2c), so the
   +4.4% highway drivetrain penalty rests on 88.7 mi. More long out-and-backs would
   firm it up.
7. The Sec.2b pull-down curve conflates falling HVAC power with rising speed. Splitting
   them needs HVAC power binned by *elapsed time within the trip* rather than by trip
   duration — straightforward, not yet done.
