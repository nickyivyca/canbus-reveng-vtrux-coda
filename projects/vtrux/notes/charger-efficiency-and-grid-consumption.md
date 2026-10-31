# Vtrux — Charger Efficiency and From-Grid Wh/mile

How much AC energy the wall delivers per mile driven, and how badly the Bel
on-board charger degrades at low power.

**Status:** complete over 16 charge sessions / 118 kWh of AC input
(2026-08-03). **Corrected 2026-10-10** against real-power metering -- see the
correction block below. Companion to `energy-consumption.md` (Wh/mile at the HV bus) and
`fuel-to-electricity.md` (Wh/gallon).

Scratchpad: `notes/artifacts/charger_efficiency.py`; per-session results in
`notes/artifacts/charger_sessions.json`.

> ## Correction, 2026-10-10 -- read this before any number below
>
> Two of the measurements this note rests on are wrong in ways the CAN data
> alone could not show. Both were found by adding real-power metering (the
> garage 14-50 Emporia CT, and the Enphase consumption CTs as a second meter):
>
> 1. **The AC side is apparent power, and the charger's AC current reads
>    ~8 % low at full power.** Real power from the CT is 1.09-1.12x the
>    charger's `V x I` at full power, and only 0.30-0.40x at the Low Power
>    hold. Measured and written up in
>    `Infrastructure/vehicle-cost-per-mile.md` section 6 (6.1-6.3), which
>    this note never referenced. Every efficiency and wall-to-pack figure
>    below that divides by CAN AC power is affected: high-power figures are
>    optimistic, and hold figures are pessimistic.
> 2. **`BELINV_hvBatteryCurrent` reads high at low output.** The error is
>    ~0 above ~10 A, +0.14 A at 6-8 A, +0.4 A at 4-5 A and **+1.5 A at a
>    2.0-2.5 A reading**. So the "~940 W of DC" at the hold is not produced;
>    the true current is ~0.8-0.9 A. Details in
>    [The charger's DC current reading at low output](#the-chargers-dc-current-reading-at-low-output-2026-10-10).
>    The "HV aux" (`Idc - Ibat`) is inflated wherever low-current time is
>    included.
>
> **What stands:** the full-power DC reading (cross-checked against the BMS in
> export mode at 15-18 A), the voltage-dependence analysis (its contrasts are
> within-session and at high current), and the charger-unit comparison.
>
> **Superseded:** the headline efficiency, wall-to-pack and Wh/mi figures (see
> the CT-based column added to the headline table), and the "losses are
> essentially fixed" mechanism. In real power, the charger loss is ~1.05 kW at
> full power and at most ~0.5 kW at the hold.
>
> Scripts: `artifacts/charger_dc_error_fit.py`, `artifacts/hold_load_fit.py`
> (phase 8), `artifacts/hold_burst_check.py`, `artifacts/hold_msgrate_check.py`.

---

## Headline

> **See also [`charge-termination-behaviour.md`](charge-termination-behaviour.md).**
> `CHARGER_LOW_POWER` (mode 3) is a hold, not a stop: the charger keeps drawing
> ~7.9 A at ~244 V (~1.9 kVA apparent). It is not brief -- the balance hold
> at top of charge ran 7.7 h on the parts truck.
>
> **Corrected 2026-10-10:** the hold draws **~570-600 W real** (main truck;
> ~1,020 W on the parts truck, whose pump adds ~220 W at 12 V), not 1.9 kW.
> Its "~940 W of DC" was the charger's own reading, which is ~1.5 A high at
> this output. The true DC is ~0.8-0.9 A, almost all of it consumed by HV aux
> and the DC-DC. Wall-to-pack during the hold is ~3 %.


| Metric | Original value (CAN apparent power) | **Real power (CT), 2026-10-10** |
|--------|------:|------:|
| **From-grid consumption** | ~750 Wh/mi (typical mixed charging) | **~786 Wh/mi** (vehicle-cost-per-mile 6.3) |
| — if always charging at 32 A | ~650 Wh/mi | **~700 Wh/mi** |
| — if always charging at 16 A | ~890 Wh/mi | not re-measured |
| Charger efficiency at 6.5 kW (32 A) | 92–93% | **~85%** (real loss ~1,050 W) |
| Charger efficiency at 2.9 kW (16 A) | 77–82% | not re-measured |
| Wall-to-pack at 32 A | 84–86% | **79.5%** (6.2: 78.5%) |
| Wall-to-pack at 16 A | ~63–65% | not re-measured |
| Pooled wall-to-pack, all productive sessions | 74.3% | **71.1%** (18 sessions, 6.3) |

The "~700 Wh/mi at 32 A" is 531 / (0.795 x 0.95). The 16 A rows have no CT
data: the 16 A and weak-supply sessions were charged away from home.

**Charging at 16 A instead of 32 A costs about 29% more grid energy for the
same charge** — 15.4 kWh from the wall per 10 kWh into the pack, versus
11.9 kWh at 32 A. **Not re-measured, and its mechanism is contradicted
(2026-10-10):** the claim rests on the fixed-loss picture below, which does
not hold in real power. 16 A probably still costs more, because the HV aux
and DC-DC run for longer, but the size of the penalty is unknown.

---

## Why: the losses are essentially FIXED, not proportional

> **Superseded 2026-10-10 -- this section holds only in apparent power.** In
> real power (CT) the charger loss is **~1,050 W at full power** (real
> efficiency ~0.85; ~1,275 W / 0.82 on the parts truck). At the Low Power
> hold, charger loss + DC-DC loss + HV aux total **~510 W** (478-524 W in
> every hold on both trucks), so the charger alone is at most ~0.5 kW there.
> The loss scales with power. The flat "loss W" column below was produced by
> the AC current under-reading at high power and the power factor collapsing
> at low power.
>
> The ~510 W can only be split with an assumption. If the HV aux stays at its
> bulk value through the hold, the split is roughly ~220 W charger, ~150-340 W
> HV aux, and a small DC-DC loss (`artifacts/charger_dc_error_fit.py`
> phase 3). The CT alone gives only the sum.
>
> The tables below are kept as the apparent-power record.

This is the whole story. Two overheads, both roughly independent of charging
power:

| Loss | Magnitude | Source |
|------|----------:|--------|
| Charger conversion | **~470–650 W** | Bel on-board charger |
| HV auxiliary | **~460–620 W** | DCDC converter, coolant pumps running during the charge |

Against a 6.5 kW input those two together are ~15%. Against a 2.9 kW input they
are ~35%. Nothing about the charger gets worse at low power in absolute terms —
there is simply less useful throughput to amortise a fixed overhead over.

### Measured efficiency vs AC input power

Pooled across all 16 sessions, 658,647 samples, CV-hold excluded:

| P_ac (kW) | n | eta q1 | **eta median** | eta q3 | loss W |
|-----------|--:|-------:|---------------:|-------:|-------:|
| 1.5–2.0 | 2,367 | 0.649 | **0.661** | 0.672 | 653 |
| 2.0–3.0 | 21,897 | 0.756 | **0.774** | 0.787 | 642 |
| 3.0–4.0 | 14,156 | 0.766 | **0.816** | 0.835 | 562 |
| 4.0–5.0 | 7,800 | 0.889 | **0.899** | 0.943 | 467 |
| 5.0–6.0 | 238,502 | 0.901 | **0.908** | 0.919 | 486 |
| 6.0–7.0 | 373,924 | 0.915 | **0.926** | 0.936 | 466 |

The `loss W` column is the point: it moves only from ~650 W to ~470 W across a
4x change in throughput. Efficiency is `1 - loss/P_ac` and nothing more.

---

## Method

All four quantities come from **one message**, `0x18FFD7C0`
(`BELINV_hvBatteryAndCharger`), so AC input and DC output are sampled
simultaneously with no cross-message alignment needed:

| Field | Bytes | Encoding |
|-------|-------|----------|
| `hvBatteryVoltage` | B0:B1 | x0.05 V DC out |
| `hvBatteryCurrent` | B2:B3 | x0.05 A DC out, signed |
| `chargerInputVoltage` | B4:B5 | x0.05 V AC RMS in |
| `chargerInputCurrent` | B6:B7 | x0.05 A AC RMS in |

Sample validity follows `notes/ac-resistance.md`: `0xFFFF` is a no-data sentinel
decoding to 3276.75 and must be filtered, else a handful of samples dominate
every statistic. Accept only `80 <= Vac <= 300`, `0 <= Iac <= 60`.

Pack-side energy is taken independently from the BMS (`0x410` `bcm_vbat` x
`bcm_ibat`), so `E_dc - E_pack` gives the HV auxiliary load directly.

> **2026-10-10:** that last step only holds at high charger current.
> `hvBatteryCurrent` reads increasingly high below ~6 A (see
> [the DC current section](#the-chargers-dc-current-reading-at-low-output-2026-10-10)).
> Any `E_dc` integrated over a taper or a hold therefore over-counts, and the
> `E_dc - E_pack` "HV aux" with it. `chargerInputCurrent` reads ~8 % low at
> full power (vehicle-cost-per-mile 6.1).

### Three corrections that materially changed the answer

1. **`hvBatteryCurrent` sign is documented backwards.** `BelInverter-v2.dbc`
   comments it as "positive = charging", but the logged value is negative
   throughout every charge session while the pack is demonstrably gaining
   energy. Magnitudes are right (|E_dc|/E_ac lands at 90–93%); only the
   documented sign is wrong. **The DBC comment needs correcting.**
2. **CV-hold is not low-power charging.** The `80pctcv` session sits for hours
   at ~1.9 kVA in / 0.95 kW out with only **2.45 A** of DC current — the charger
   idling against its setpoint. Pooling it produced a fake 49% efficiency bin
   that was 98.6% one session. Samples with `Idc < 3 A` are now excluded.
   **(2026-10-10:** the "0.95 kW out" was never real. At a 2.45 A reading the
   DC current is ~1.5 A high, and real input is ~570 W, not 1.9 kVA. The
   `3 A` cut also leaves the 3-6 A taper in, where the reading is still
   0.1-1.0 A high.)
3. **Pack energy must be integrated over charging intervals only.** Integrating
   across the session span counts the pack *discharging* into HV aux during idle
   gaps. `@20260714_161319` charges 3.28 h inside a 5.63 h span; before the fix
   its wall-to-pack read 58.8%, after 74.4%.

### The low-power result is not a single-session artifact

Worth stating because it nearly was. On the seven Ixxat sessions alone, the
2–3 kW and 3–4 kW bins were **81% and 71% from one session**
(`vtruxchargeafteroverheattest-16asetpoint`) — recorded immediately after an
overheat test, so plausibly a hot, derating charger.

Scanning the Android library for `0x18FFD7C0` found 10 more sessions with
charger data (~13 GB), which triples the sample and spreads the low-power bins
across independent days:

| Bin | Session provenance |
|-----|--------------------|
| 2–3 kW | overheattest-16a 62%; `@20260503_192242` 16%; scottsvalley2-16a 7% |
| 3–4 kW | `@20260503_192242` 42%; overheattest-16a 20%; `@20260726_191901` 18% |
| 4–5 kW | `@20260503_192242` 46%; `@20260714_161319` 37%; `@20260726_191901` 13% |

The low-power penalty reproduces on 2026-05-03, 2026-06-27 and 2026-07-26. It
is a property of the charger, not of that one hot session.

> **Qualified below.** Those additional days are all on the *replacement* Bel
> unit (swapped 2026-05-03), so this is not day-to-day reproducibility on one
> device — it is reproducibility across two different devices. See
> [Charger unit: original vs replacement](#charger-unit-original-vs-replacement-2026-05-03).

---

## Voltage dependence — two separate terms, opposite signs

AC supply voltage and DC bus (pack) voltage are **not one "voltage" effect**.
They act on different stages of a two-stage charger and have opposite signs:

- **V_ac** drives the input / PFC stage — higher line voltage means a higher
  switching voltage, and switching loss scales with blocking voltage
  (`E_sw ~ V x I` per transition).
- **V_dc** drives the isolated output stage — at a given output power, higher
  pack voltage means proportionally *lower* output current, so less `I^2 R`
  conduction loss and less rectifier drop.

Fitted jointly on the replacement unit only (one hardware unit), steady-state
samples, **n = 343,447**, spanning V_ac 180–241 V and V_dc 379–415 V:

| Model (loss in W) | R² | RMSE | V_ac | V_dc |
|-------------------|---:|-----:|-----:|-----:|
| `a + b*V_ac + c*V_dc` | 0.461 | 57 W | **+2.48 W/V** | **-11.03 W/V** |
| `+ d*I_ac` | 0.609 | 48 W | +2.57 W/V | -15.50 W/V |
| `a + c*V_dc` only | 0.199 | 69 W | — | -9.88 W/V |
| `a + b*V_ac` only | 0.215 | 68 W | +2.23 W/V | — |

**The two terms are separately identifiable here:** `r(V_ac, V_dc) = +0.10`, so
they are close to orthogonal in this dataset rather than trading off against
each other. Dropping either one collapses R² from 0.46 to ~0.2, so both are
needed.

### DC bus term, checked independently within sessions

The V_dc term also shows up without any fitting. During the CC phase the pack
voltage sweeps while the charger holds AC current constant, isolating it with no
cross-day confound (samples within +/-0.6 A of each session's median AC current):

| Session | V_ac | I_ac | 380–390 V | 390–400 V | 400–410 V | slope |
|---------|-----:|-----:|----------:|----------:|----------:|------:|
| `vtruxchargeblueevse` | 238 | 26.5 A | 501 W (0.920) | 403 W (0.936) | 303 W (0.952) | **-9.9 W/V** |
| `...exportchargetest-80pctcv` | 233 | 27.3 A | 448 W (0.930) | 373 W (0.941) | — | **-6.4 W/V** |
| `@20260726_191901` | 230 | 26.9 A | 518 W (0.916) | 433 W (0.930) | — | — |
| `@20260714_161319` | 195 | 26.2 A | 445 W (0.913) | 340 W (0.933) | 261 W (0.949) | **-9.2 W/V** |

Consistent across four sessions and both supply voltages, n up to 115,000 per
bin. **Efficiency gains roughly 3 points as the pack rises from ~380 V to
~405 V.**

### AC supply term, and why it looks small in practice

At **matched AC current** on the replacement unit (the right comparison, since
the charger is EVSE current-limited and conduction loss is current-driven):

| I_ac | LOW V (190–215) | HIGH V (228–250) |
|------|-----------------|------------------|
| 26–28 A | 198 V, 5.18 kW, eta **0.907**, loss 484 W (n=148,406) | 232 V, 6.19 kW, eta **0.913**, loss 537 W (n=120,644) |

The higher-voltage case carries **more absolute loss at the same current**
(537 vs 484 W, about +1.6 W/V here) — that is the V_ac term, and its sign
matches the fitted +2.5 W/V. It costs efficiency directly, but only by ~0.6
points, because the same current buys **19% more power** at 232 V than at 198 V
and that extra throughput more than pays for the extra switching loss. Net
wall-to-pack: **81.9% at 198 V vs 84.8% at 232 V**.

Ramp transitions at 20–26 A appear to show low voltage doing dramatically better
(eta 0.95, loss ~200 W) on 500–1,600 samples against 120,000+ in the steady
bins; those are not steady-state and should not be read as a voltage effect.

### Identifiability — how the terms are separated when most sessions are constant-power

Most charging runs at fixed EVSE current on a fixed supply, so `P_ac` is
constant and the obvious worry is that nothing is separable: along a
constant-power line `V_dc` up implies `I_dc` down, and a fitted "voltage"
coefficient would really be a net movement along that line rather than a partial
derivative. Three things rescue it, and the first is an empirical check rather
than an assumption.

**1. During the V_dc sweep, I_dc is nearly constant — the sweep is not a
constant-power trajectory.**

| Session | V_dc 375–385 | V_dc 385–395 | V_dc 395–405 |
|---------|--------------|--------------|--------------|
| `blueevse` | I_dc 15.20 A, loss 477 W | I_dc 14.85 A, loss 431 W | I_dc 14.95 A, loss 374 W |
| `@20260714_161319` | I_dc 12.25 A, loss 475 W | I_dc 12.10 A, loss 430 W | I_dc 12.05 A, loss 302 W |

`I_dc` moves by **under 2%** across the whole sweep while `V_dc` moves 5% and
loss moves 20–35%. Conduction loss scales as `I_dc^2`, so a 2% current change
cannot produce it. **The V_dc term is not a disguised conduction term.** What is
happening is that the charger holds DC current while the pack voltage rises, so
it delivers more watts out for the same watts in — a real efficiency gain.

**2. A natural experiment breaks the V_dc/I_dc tie directly.** Two sessions on
the same day, same truck, at *adjacent* SoC — so matched bus voltage — but 2.5x
different current:

| Session | V_ac | I_ac | **V_dc** | **I_dc** | loss | eta |
|---------|-----:|-----:|---------:|---------:|-----:|----:|
| `...overheattest-16asetpoint` | 241 V | 12.2 A | **387 V** | **5.85 A** | **663 W** | 0.772 |
| `...overheattest-32asetpoint` | 235 V | 26.5 A | **389 V** | **14.75 A** | **487 W** | 0.921 |

At essentially identical bus voltage, **2.5x the current produces LESS loss**
(487 W vs 663 W). That is the opposite of conduction, and it is measured with
`V_dc` held fixed, so it cannot be a voltage effect in disguise. It confirms
that the negative current coefficient in the pooled fit is real in the sampled
range, not a regression artifact — though see the caveat below on what is
actually driving it.

**3. The V_ac contrast comes at matched current.** Because the charger is EVSE
current-limited, the 195 V and 232 V sessions both settle at ~26–27 A, giving
`V_ac` variation at fixed `I_ac` (the 26–28 A comparison above).

So the three coefficients come from three different subsets, each with a
different quantity held fixed — not from one pooled regression trying to
untangle a single collinear cloud. That is also why `r(V_ac, V_dc) = +0.10`
across the pooled data: the contrasts are structurally independent.

**What is still NOT separable:** there is no measurable conduction (`I^2 R`)
term anywhere in the sampled range — it is swamped by the fixed overhead and by
the apparent-power artifact, both of which push the other way. Nothing here
bounds it. Extracting it would need real-power metering, or operation at
currents well above 27 A where `I^2 R` finally dominates.

### Caveats on the model

- **V_dc variation is within-session and clean; V_ac variation is
  between-session** and therefore confounded with day, ambient temperature and
  EVSE. The V_dc coefficient is the better-supported of the two.
- Within a session V_dc and SoC are perfectly correlated, so this cannot fully
  separate bus voltage from any other SoC-dependent effect.
- The fitted `I_ac` coefficient is **negative** (-20 W/A), which is unphysical
  for conduction loss taken alone. The 16 A / 32 A natural experiment above
  confirms the sign is real in the sampled range, so it is not merely a
  regression artifact — but the most likely driver is still the apparent-power
  problem: `P_ac` is `V_RMS x I_RMS`, and light-load PF degradation inflates
  apparent loss at low current. A genuine conduction term must exist and must be
  positive; it is simply not visible under these two larger effects. **The model
  is descriptive, not mechanistic**, and the coefficients should not be taken as
  device parameters.

### Practical consequence

The penalties stack, and they all bite hardest in the same place: **low SoC (low
bus voltage), low current setpoint, weak supply**. A deeply discharged pack on a
16 A weak outlet is the worst case on every term at once.

---

## Charger unit: original vs replacement (2026-05-03)

The Bel unit was **replaced on 2026-05-03** (`vtrux_newcharger.log` starts 15:52
that day). That creates a confound that is total rather than partial:

> **All 7 Ixxat charge logs are March 2026 (ORIGINAL unit) and all 10 Android
> charge sessions are May-July 2026 (REPLACEMENT unit).** Era and logger source
> are perfectly aliased. Any pooled statement mixes two different devices.

This matters for a claim made earlier in this file. The low-power bins were
originally dominated by one March session, and adding the Android sessions was
described as showing "the penalty reproduces on independent days". Those days
were on a *different charger*. The statement survives — but as the stronger and
differently-worded claim that **the low-power penalty appears on both units** —
not as the day-to-day reproducibility it was presented as.

### Voltage-matched, power-matched comparison

A straight era comparison is invalid because **60% of REPLACEMENT-era samples
are below 215 V AC** (the weak-supply days of 2026-05-13 and 2026-07-14) versus
0% for the ORIGINAL era, and lower supply voltage means more current for the
same power. Restricting both eras to 228-250 V:

| P_ac | ORIGINAL unit | REPLACEMENT unit |
|------|---------------|------------------|
| 2.0–3.0 kW | eta 0.777, loss 646 W (n=16,760) | eta 0.673, loss 697 W (n=1,596) |
| 3.0–4.0 kW | eta 0.764, loss 715 W (n=4,062) | eta 0.818, loss 557 W (n=3,975) |
| 4.0–5.0 kW | eta 0.897, loss 463 W (n=274) | eta 0.900, loss 455 W (n=1,041) |
| 5.0–6.0 kW | eta 0.920, loss 434 W (n=7,931) | eta 0.922, loss 433 W (n=1,249) |
| 6.0–7.0 kW | eta 0.933, loss 425 W (n=213,322) | eta 0.913, loss 537 W (n=122,287) |

**There is no evidence the original unit was degraded and improved on
replacement.** The two mid bins where both units are well sampled (4–5 and
5–6 kW) are identical to within 0.3 points. The differences elsewhere have no
consistent direction: the replacement is better at 3–4 kW, the original better
at 2–3 and 6–7 kW. If anything the original is marginally better at the top of
the range (0.933 vs 0.913 at 6–7 kW, both with >100k samples), which is the
opposite of the degradation hypothesis.

**The low-power penalty is present on both units**, so it is a property of the
design and its fixed overhead, not a symptom of a failing charger.

> **2026-10-10 -- three units, and the low-current DC error is common to
> them.** The parts truck has always had its own Bel unit; the main truck got
> a new unit on 2026-05-03 (user, 2026-10-10). So the hold data covers three
> units:
>
> - main original (another_M0, charge_M0, charge_M1, 80pctcv,
>   full-charge-then-fail);
> - main replacement (0503, 0726, 0816, 0912);
> - the parts truck.
>
> At a 2.0-2.5 A reading the DC error is 1.30-1.50 A on the original and
> 1.42-1.59 A on the replacement, which is indistinguishable. The parts truck
> first appeared worse (2.07 A at a 2.5-3.0 A reading). That most likely
> comes from the constant-HV-aux assumption failing on a truck with a
> 270-320 W 12 V load. Its assumption-free bound (reported DC minus CT,
> 314 W, so at least 0.8 A) is no larger than main's. **No difference between
> the three units has been measured.**

### The pooled per-era totals differ, but not because of the unit

| Era | E_ac | E_dc | E_pack | eta_chg | wall-to-pack | implied grid Wh/mi |
|-----|-----:|-----:|-------:|--------:|-------------:|-------------------:|
| ORIGINAL | 41.3 kWh | 37.8 | 34.2 | 91.5% | **82.7%** | 676 |
| swap day | 12.1 kWh | 10.2 | 8.5 | 83.8% | 69.8% | 800 |
| REPLACEMENT | 61.8 kWh | 52.7 | 42.9 | 85.2% | **69.4%** | 805 |

That 13-point gap is **charge-profile driven, not unit driven**. The ORIGINAL
era is dominated by three long high-power sessions; the REPLACEMENT era includes
`@20260627_164210` (median 1.86 kW, mostly CV taper, 59.2% wall-to-pack) and
several low-voltage sessions. Once power and voltage are matched, as above, the
units are equivalent. **Do not read these era totals as a unit comparison.**

The headline ~750 Wh/mi is a blend of both eras. A user who always charged at
32 A on a strong 240 V supply would see closer to the ~650 Wh/mi figure on
either unit.

---

## Truck separation — the parts-truck pump confound does NOT apply here

The parts truck runs its PE coolant pump uncontrolled (its `0x18FF0320` has zero
frames, so the VFD never receives a speed command and free-runs), which adds a
standing 12 V draw and would inflate the apparent auxiliary load during
charging. **Every session in this analysis was checked and all 16 are the MAIN
truck**, so that confound is absent.

Three independent checks agree:

| Check | Result |
|-------|--------|
| Odometer `0x625` B0:B2 | **96,424 – 98,614 km** on all 16 sessions. Main is >= 90,000 km; parts is ~44,000 km (`specific-trucks/battery-degradation-tracking.md`). |
| `0x18FF0320` present | **Yes, 47 – 19,558 frames** in every session. The parts truck has zero frames in all logs (`warning-lamp-investigation.md`), so presence alone proves the pump is on CAN and under speed command. |

> **A third check was attempted and is void.** Pump speed feedback
> (`0x18FF0320` B5, 0–241) reads 3–20 in these sessions, never near the 241
> free-running value — but that proves nothing, because **B5 only exists while
> the pump is connected to CAN.** In the free-running condition the message is
> absent entirely, so 241 is unobservable by construction and the check could
> not have failed. Frame *presence* is the only informative test; the speed
> value adds nothing.

Note that `@20260503_171127` and `@20260503_192242` fall on a date where
`precharge-fail-investigation.md` records *parts truck* activity — but the
odometer puts both charge sessions at ~96,895 km, i.e. the main truck. Both
trucks were evidently worked on that day; the charge logs are the main one.

**The truck check is now built into `charger_efficiency.py` and printed per
session, so any future addition of parts-truck data will be visible rather than
silently pooled.**

### The related within-truck effect is real, though

12 V load through the DCDC varies substantially between main-truck sessions:

| Session | 12 V load | Session | 12 V load |
|---------|----------:|---------|----------:|
| `@20260719_190019` | 47 W (3.3 A) | `vtruxchargeblueevse` | 110 W (7.7 A) |
| `@20260513_180408` | 52 W (3.7 A) | `@20260714_112312` | 150 W (10.6 A) |
| `@20260627_164210` | 54 W (3.8 A) | `@20260714_102812` | 186 W (13.1 A) |
| `@20260714_161319` | 87 W (6.1 A) | `vtruxchargemegearevse` | 293 W (20.6 A) |

A 6x spread, and the high-12 V sessions are the same ones with elevated
auxiliary load. This is the same physical mechanism the parts truck exhibits
continuously, just smaller and intermittent.

---

## The auxiliary load is real, not sensor disagreement — settled by export mode

The "HV aux" quoted above is `E_dc(charger) - E_pack(BMS)`, a difference between
two *independent* current sensors, and at ~390 V it takes only 1.1 A of
calibration offset to manufacture 440 W of phantom load. That ambiguity is
resolved by looking at **export mode**, where the same power stage runs
backwards and the current through both sensors reverses.

| Mode | Charger `Idc` | BMS `Ibat` | `Idc - Ibat` |
|------|--------------:|-----------:|-------------:|
| Charging (6.3 kW) | ~14.9 A | ~13.5 A | **+1.13 A (~440 W)** |
| Exporting (5.7 kW, both legs loaded, n=530) | ~17.8 A | ~18.2 A | **+0.02 A (~9 W)** |

Two failure modes are excluded by this:

- **Additive sensor zero-offset.** An offset `d` on the charger's sensor appears
  as `D = -d` in *both* directions, so it would read the same +1.13 A while
  exporting. It reads +0.02 A. **Ruled out.**
- **Gain error.** A gain error scales with current and flips sign with
  direction. Export carries *more* current (17.8 A vs 14.9 A) yet shows a
  *smaller* discrepancy. **Ruled out.**

What remains is a **real HV load that is mode-dependent** — roughly 440 W while
charging and essentially nothing while exporting. That is physically sensible:
the charging aux is dominated by thermal management of a unit dissipating
several hundred watts into a cold-soaked pack, and by the DCDC.

**Consequence:** the wall-to-pack figures and the ~750 Wh/mi from-grid number
stand as measured. An earlier draft of this file hedged the headline down to
~680 Wh/mi on the possibility of sensor error; that hedge is **withdrawn**.

> **Scope, added 2026-10-10.** This check was made at ~15-18 A, and it holds
> there. It says nothing about low output. Below ~6 A the charger's reading
> is high by a current-dependent amount: not an additive offset, so the
> offset argument above does not cover it, and not a gain error either. The
> ~440 W aux at 6.3 kW is a real load. The "HV aux" at the hold (~850-970 W)
> is not.
>
> The "~750 Wh/mi stands" consequence is also superseded on the AC side. Real
> power gives ~786 Wh/mi (vehicle-cost-per-mile 6.3).

### Export also confirms the "high fixed loss" character

From the same session, pack output **6,730 W** against AC output **5,740 VA** —
a loss of **975 W** at 5.7 kW delivered, i.e. ~14.5%. Since the AC figure is
apparent power, real output is lower and the true loss is **at least** 975 W.
The unit carries a large standing loss in both directions, which is the whole
reason the low-power charging efficiency is so poor.

Note the low-power export sessions (`exportpowerattempt.log`,
`vtruxexportafterucsc.log`, ~1 kW) are **not usable** for efficiency: their legs
are badly unbalanced (1.6 A vs 7.2 A) and the AC reading is V_RMS x I_RMS, so a
reactive load makes apparent power exceed real power — they compute to >100%
efficiency, which is the artifact, not a measurement.

---

## The charger's DC current reading at low output (2026-10-10)

Found by the charge-interposer review (`artifacts/hold_load_fit.py` phase 8)
and finished here (`artifacts/charger_dc_error_fit.py`,
`artifacts/hold_burst_check.py`, `artifacts/hold_msgrate_check.py`).

### At the hold, the reported DC output exceeds the real AC input

Settled windows, 20 min or more after the Low Power command, in all nine
holds with CT coverage:

| | CT real W | charger VA | reported DC W | pack W | 12 V W |
|---|---:|---:|---:|---:|---:|
| main truck (8 holds, Jan-Sep 2026) | 569-752 | 1,840-1,890 | 837-1,079 | 0-169 | 42-70 |
| parts truck (1 hold) | 1,020 | 1,947 | 1,334 | 226 | 273 |

A charger cannot output more than it draws, so the DC reading is high by at
least `(reported DC - CT) / Vdc`, about 0.8-1.1 A, even at 100 % efficiency.

**The CT is trustworthy at this load, confirmed by a second meter.** The CT
had only been validated at ~6.8 kW (against the Coda, vehicle-cost-per-mile
6.1). At every point where it fell from a steady plateau to ~0, the step was
compared with the Enphase consumption CTs on the main panel, which have their
own CTs and voltage reference:

- 29 full-power ends: Enphase/CT 0.99 (quartiles 0.98-1.00);
- 6 hold ends with a quiet house: 0.88 (0.80-1.22).

For the DC reading to be physically possible, the CT would have to read
1.4-1.7x low at the hold.

**What stays fixed across every hold:** CT - pack - 12 V = **~510 W**
(478-524 W). That holds on both trucks, from January to September, and in
the 80 % hold. It is charger loss, DC-DC loss and HV aux combined, in real
watts. The parts truck's extra ~220 W of 12 V load (its uncommanded pump)
costs about the same ~220 W at the wall.

### Shape of the error: grows as the current falls, not an offset

**ASSUMPTION:** the non-DC-DC HV load stays at the value it has in that
session's own bulk (Idc >= 10 A), where the sensors agree. Then
`true Idc = ibat + (aux_ref + P12 / 0.9) / Vdc`. `aux_ref` is 144-341 W on
the main truck. Main truck, 2,011 sixty-second windows:

| Reported Idc | Implied true | Error |
|---|---:|---:|
| 13-16 A | 14.7 | ~0 (zero by construction) |
| 10-13 A | 12.4 | +0.02 A |
| 6-8 A | 6.1 | +0.14 A |
| 4-5 A | 4.1 | +0.41 A |
| 3.5-4 A | 2.9 | +0.85 A |
| 3-3.5 A | 2.2 | +1.03 A |
| 2.5-3 A | 1.4 | +1.31 A |
| 2-2.5 A | 0.83 | **+1.49 A** (n=921) |

- **An additive offset fits badly** (RMSE 0.74 A).
- `reported = 0.891 x true + 1.51` fits to RMSE 0.23 A.
- `sqrt(true^2 + 2.12^2)` fits to 0.21 A, but is **rejected** by the
  parts-truck 83 % start (`vtrux_partstruck_chargeagain3`, 2026-04-25,
  raised by the interposer review and reproduced here): the charger reported
  a steady 1.40 A for ~43 s at a 0 A setpoint, which a quadrature form
  cannot produce.
- **The linear form is a fit, not a mechanism.** It comes from one truck plus
  that one point. "Delivers ~0 at a 0 A setpoint" is a modelling choice the
  reading allows, not a measurement: the CT rows around that start are
  2 minutes apart, so they do not bound the wall power.

**Consequence for the hold.** In the full-charge holds the setpoint and the
reading track (set 2.30 A, read 2.35 A). If the charger regulates its own
reading, a ~2.3 A setpoint delivers **~0.8-0.9 A true**, nearly all of it
consumed by HV aux and the DC-DC, which leaves the pack at ~0.05 A. The
reading does not follow the setpoint at 0 A (0 A set, 1.4 A read).

### The real power factor, and what was ruled out

Real W / charger VA is 0.30-0.40 at the hold (0.52 on the parts truck), and
1.09-1.12 at full power, the latter from the ~8 % AC current under-read.

- **No burst-mode transmit gating.** In the raw logs of all 10 hold sessions,
  `0x18FFD7C0` runs at 9.99-10.00/s and `0x410` at 19.96-19.98/s, in bulk and
  in the hold alike. That covers both main-truck units, the parts truck, and
  both logger types. The reported Idc is never 0 in the hold; it swings
  2.0-2.6 A on the ~11 s setpoint cycle.
- **The "message rate drops to 55 % / 20 %" in vehicle-cost-per-mile 6.2 is
  an InfluxDB point-count effect.** Influx stores on change plus a 1 s
  heartbeat. Hold/bulk point-rate ratios are 0.55-0.68 for
  `BELINV_hvBatteryCurrent` and 0.17-0.40 for `bcm_vbat`, against flat frame
  rates. It is not known which fields 6.2 counted; the match in magnitude is
  the evidence.

### What this invalidates

- "~940 W of DC" at the hold, here and in `charge-termination-behaviour.md`.
- Any "HV aux" figure that includes taper or hold time. The 460-620 W "HV
  auxiliary" in the loss table is a whole-session figure. Bulk-only HV load,
  DC-DC input included, is ~220-410 W on the hold sessions.
- **DC-DC efficiency estimates that relied on the hold** (the interposer
  review's ~63-67 %). A bulk-only fit gives no usable estimate either
  (session medians n=5, R^2 0.02). Treat DC-DC efficiency as unknown.

### Open

- Whether the parts-truck unit differs. One session, and the constant-aux
  assumption is weakest there. A second parts-truck hold with CT data would
  settle it.
- The charger/HV-aux split of the ~510 W without the constant-aux assumption.
- The physical mechanism of the error.

---

## From-grid Wh/mile

Driving consumption at the HV bus is **531 Wh/mi** (`energy-consumption.md`).
That figure is energy *out of the pack* and is independent of whether the
electrons came from the grid or the generator, so it combines directly:

```
Wh/mi from the wall = 531 / (wall-to-pack x pack round-trip)
```

| Charging regime | Wall-to-pack | Pack r/t 100% | Pack r/t 95% |
|-----------------|-------------:|--------------:|-------------:|
| Pooled, as actually charged | 74.3% | 715 Wh/mi | **753 Wh/mi** |
| Always 32 A | 86% | 617 Wh/mi | **650 Wh/mi** |
| Always 16 A | 63% | 843 Wh/mi | **887 Wh/mi** |

Pooled totals: **E_ac 115.3 kWh -> E_dc 100.7 -> E_pack 85.6 kWh** across 15
productive sessions. One session (`@20260719_190019`) drew 2.53 kWh and put
0.03 kWh in the pack — sitting plugged in at full charge — and is excluded from
the productive pooling but is real grid consumption nonetheless.

---

## Caveats

- **`P_ac` is apparent power, not real power.** The charger reports V_RMS and
  I_RMS, so `V x I` is VA. The Bel unit is power-factor-corrected and PF is
  typically 0.98–0.99 at load, but PF degrades at light load — which is exactly
  where the interesting result is. **The low-power efficiency figures are
  therefore LOWER BOUNDS on true conversion efficiency**, and the real grid
  penalty at 16 A is somewhat less severe than measured, since a residential
  meter bills real kWh not kVA. The residual downward slope of the loss column
  (650 W -> 470 W) is consistent with exactly this. CAN carries no PF or
  real-power field, so the two cannot be separated from this data.
  **Closed 2026-10-10:** the garage CT separates them (vehicle-cost-per-mile
  6.1-6.3). The direction is mixed. At full power the CAN figures are
  *optimistic* (the AC current reads ~8 % low, so real W/VA is 1.09-1.12). At
  the hold they are *pessimistic* (W/VA 0.30-0.40). So the high-power figures
  are not lower bounds.
- **Pack round-trip efficiency is assumed, not measured.** 95% is a reasonable
  LFP figure at these rates but was not established from the logs.
- No loss model is fitted. `P_loss` falls slightly with power, which no
  switching converter does — conduction loss rises with current. A linear fit
  returns a negative proportional term and extrapolates to -72% efficiency at
  0.5 kW, which is meaningless. The binned medians are the measurement.
  **(2026-10-10:** in real power the loss does rise with power, from ~1,050 W
  at full power to at most ~0.5 kW at the hold. The falling VA-based loss was
  the measurement artefact.)
- `vtrux_newcharger.log` / `_part2.log` (2026-05-03 15:52 and 17:14) mark the
  **Bel unit replacement** and are still undocumented in the logs README — worth
  adding. They were not analysed directly; the swap date was taken from their
  headers and used to split the sessions above.
- Two sessions show unusually high HV aux (`@20260714_102812` at 2090 W,
  `@20260714_161319` at 884 W) versus the typical ~500 W. Battery thermal
  management is the obvious suspect (see `battery-thermals.md`) but this was not
  investigated. **(2026-10-10:** these are whole-session `E_dc - E_pack`
  figures, which the low-current DC over-read inflates wherever taper or hold
  time is included. Bulk-only, `@20260714_102812` is ~400 W, and
  `@20260714_161319` is still ~1,690 W
  (`artifacts/hold_load_fit_p5.txt`).)

---

## Practical implication

> **Superseded 2026-10-10.** This section rests on the fixed-loss picture,
> which holds only in apparent power, and its 16 A row was never measured in
> real power. In real watts the charger loss scales with power. What stays
> roughly fixed is the HV aux and DC-DC load, ~220-410 W in bulk, which a
> slower charge pays for over more hours. The 32 A row is ~12.6 kWh from the
> wall per 10 kWh into the pack (79.5 % wall-to-pack, CT). The size of the
> 16 A penalty is unknown.

The fixed ~1 kW combined overhead means **charge rate matters a lot more than it
would on a car with a well-loaded charger**. Per 10 kWh delivered into the pack:

| Rate | From the wall |
|------|--------------:|
| 32 A / 6.5 kW | 11.9 kWh |
| 29 A / 5.2 kW | 12.4 kWh |
| 16 A / 2.9 kW | 15.4 kWh |

Halving the charge current does not halve the loss — it roughly doubles the
*fraction* lost. Charging at the highest available current is worth ~29% of
grid energy.
