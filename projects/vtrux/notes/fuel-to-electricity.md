# Vtrux — Fuel to Electricity Efficiency (Wh per gallon)

How much electrical energy the generator delivers to the HV bus per gallon of
gasoline burned, normalised to a baseline E8 blend.

**Status:** complete over 16 engine-run trips / 583 miles (2026-08-02).
Companion to `energy-consumption.md`, which covers Wh per mile.

Scratchpad: `notes/artifacts/wh_per_mile_estimate.py` (`fuel` phase),
results in `notes/artifacts/whpm_fuel.json`.

---

## Headline

| Metric | Value |
|--------|------:|
| **Electrical energy per baseline-E8 gallon** | **~10,100 Wh/gal** |
| **Tank-to-HV-bus efficiency** | **30.9%** |
| Per-trip range | 28.4% – 33.5% (CV 4.6%) |
| Implied charge-sustaining economy | **18.6 mpg** (E8-equivalent) |
| Measured E8-equivalent economy over these trips | **21.1 mpg** |

"Tank-to-HV-bus" is engine brake thermal efficiency multiplied by generator and
inverter efficiency — everything from the fuel in the tank to DC electricity on
the HV bus. ~31% is a realistic figure for a 5.3L spark-ignition V8 held near a
favourable operating point; the L83's peak BTE is around 35–37% and the
generator/inverter chain costs another 6–8%.

The two economy figures differ because these trips were not purely
charge-sustaining: the generator supplied **88%** of HV bus energy and grid
charging supplied the other **12%**. 18.6 mpg is what the truck would return on
fuel alone; 21.1 mpg is what it actually returned with that 12% grid
contribution.

---

## Ethanol normalisation

The truck is run on everything from pump E7 to E85, which shifts Wh-per-gallon
by ~30% on its own. All figures here are normalised to a **baseline E8 gallon**
using exactly the math in `projects/vtrux/notes/Vtrux Gas.xlsx` sheet 1, so
they are directly comparable with that sheet:

```
F = ( E*B*ETH_LHV + E*(1-B) ) / BASE_ENERGY          (sheet column F)
BASE_ENERGY = (1 - BASE_ETH) + BASE_ETH*ETH_LHV       (sheet M11)

ETH_LHV  = 0.669    ethanol energy content vs gasoline   (sheet M9)
BASE_ETH = 0.08     baseline pump-gas ethanol fraction   (sheet M10)
         => BASE_ENERGY = 0.97352                        (matches sheet M11)
```

**The sheet's math was checked and is correct.** `BASE_ENERGY` recomputes
self-consistently from M9/M10, and 0.669 matches the real ethanol/gasoline
lower-heating-value ratio (76,100 / 114,000 BTU/gal = 0.667). No changes needed.

### Blend is read from CAN, not assumed

`0x3FB` `Engine_Fuel_Status` carries `Fuel_Alcohol_Composition`, along with
its validity and adaptation-in-progress flags. The flex-fuel
sensor is present and working — validity was good for 100% of samples in every
session checked.

Measured blends across the sample: **E7, E12, E29, E67, E68** — confirming the
truck really does see a wide range and that assuming a fixed blend would be a
significant error.

**Blend is fuel-flow weighted per trip, not taken as a session median.**
`@20260724_211556` refuels mid-trip: composition steps from 29% to 68% partway
through and the tank level *rises*. Weighting the blend by instantaneous fuel
rate handles this correctly; a median would not.

### The normalisation demonstrably works

Spread across the 16 trips, before and after:

| Quantity | Mean | SD | CV |
|----------|-----:|---:|---:|
| Wh per gallon **as pumped** | 9177 | 892 | **9.7%** |
| Wh per **baseline-E8** gallon | 10205 | 469 | **4.6%** |
| Tank-to-bus efficiency | 0.3110 | 0.0143 | **4.6%** |

Normalising halves the scatter. This is also an independent check on the ECM's
fuel-rate signal: raw Wh/gal is *systematically low* on the E67–E68 trips
(7769–8722) and *high* on the E7–E12 trips (9775–10449), exactly as it must be
if the ECM correctly increases volumetric fuel flow to compensate for ethanol's
lower energy density. After normalisation that pattern disappears.

---

## Per-trip results

| Capture | Trip | Miles | Engine on | Blend | Gal pumped | Gal E8-equiv | Gen kWh | Wh/gal raw | Wh/gal-E8 | Efficiency |
|---------|-----:|------:|----------:|------:|-----------:|-------------:|--------:|-----------:|----------:|-----------:|
| `@20260724_211556` | 1 | 89.3 | 93.8 min | E31 | 5.934 | 5.473 | 57.19 | 9637 | **10449** | 31.8% |
| `@20260724_172621` | 0 | 73.1 | 89.4 min | E68 | 4.115 | 3.278 | 31.97 | 7769 | **9753** | 29.7% |
| `@20260726_142628` | 0 | 59.9 | 67.6 min | E29 | 3.233 | 3.002 | 29.85 | 9234 | **9944** | 30.3% |
| `@20260726_124205` | 0 | 58.4 | 40.8 min | E29 | 2.183 | 2.027 | 19.09 | 8742 | **9415** | 28.7% |
| `@20260726_160923` | 1 | 53.2 | 49.6 min | E67 | 3.236 | 2.586 | 26.97 | 8335 | **10430** | 31.8% |
| `@20260714_075545` | 0 | 41.4 | 20.6 min | E12 | 1.228 | 1.212 | 12.83 | 10449 | **10585** | 32.3% |
| `@20260714_161319` | 3 | 40.0 | 10.2 min | E68 | 1.006 | 0.802 | 8.78 | 8722 | **10950** | 33.4% |
| `@20260724_162517` | 0 | 34.0 | 39.9 min | E68 | 2.031 | 1.618 | 16.59 | 8168 | **10255** | 31.3% |
| `@20260617_193900` | 0 | 26.6 | 45.2 min | E12 | 1.618 | 1.597 | 14.91 | 9215 | **9335** | 28.4% |
| `@20260617_193900` | 1 | 19.2 | 27.9 min | E12 | 1.336 | 1.318 | 13.06 | 9775 | **9902** | 30.2% |
| `@20260719_164520` | 0 | 18.1 | 16.0 min | E68 | 1.023 | 0.815 | 8.56 | 8360 | **10496** | 32.0% |
| `@20260714_161319` | 2 | 18.0 | 14.6 min | E68 | 0.795 | 0.632 | 6.36 | 8002 | **10057** | 30.7% |
| `vtruxanotherevaplogpart2` | 0 | 17.7 | 26.2 min | E7 | 1.171 | 1.174 | 11.98 | 10236 | **10203** | 31.1% |
| `vtruxevapdrivelog4` | 0 | 16.7 | 16.8 min | E7 | 0.877 | 0.879 | 8.94 | 10198 | **10166** | 31.0% |
| `@20260513_195030` | 0 | 13.1 | 16.4 min | E12 | 0.953 | 0.939 | 9.72 | 10205 | **10351** | 31.5% |
| `@20260726_160923` | 0 | 3.7 | 2.4 min | E40 | 0.246 | 0.219 | 2.41 | 9786 | **10991** | 33.5% |

---

## Method

**Numerator** — generator electrical energy onto the HV bus: `0x482`
`GENE_HighPwr_Volt` x `GENE_HighPwr_Curr`, integrated per trip. This channel is
an instantaneous hardware measurement from the Dana TM4 CO150 inverter itself
and was independently confirmed against `0x598` `gen_power` at r = 0.9998 /
209 W mean error against a -5.2 to +55.6 kW swing (see `energy-consumption.md`).

**Denominator** — `0x3D1` `Instantaneous_Fuel_Consumption_Rate` (OBD bus),
integrated per trip. Note `0x3D1` is a multi-signal message; the fuel rate
must not be confused with the throttle position also carried in this frame.

**Trip splitting** is the same as in `energy-consumption.md` — sessions are cut
into movement runs so that parked wall-charging is excluded.

---

## Validation

### 1. Against the owner's own fill-up records — the decisive check

`Vtrux Gas.xlsx` cell J1 computes lifetime E8-equivalent economy directly from
pump gallons and odometer readings: `SUM(D3:D501)/SUM(F3:F501)` = **22.13 mpg**.

The CAN-derived figure over these 16 trips is **21.13 mpg**, also
E8-normalised — an apples-to-apples comparison agreeing to **4.5%**.

### 2. Physical plausibility

30.9% tank-to-bus sits exactly where a spark-ignition V8 driving a generator
should. Per-trip values cluster at 28.4–33.5% across blends from E7 to E68 and
trips from 3.7 to 89 miles.

### 3. The fuel-rate signal cannot be off by 2x

12 bits at 0.025 L/hr gives a full scale of 102.4 L/hr, which is the right
design range for a 5.3L V8 (roughly 90–100 L/hr at wide-open throttle).
Observed values are p50 13.0, p90 28.2, max 63.2 L/hr — comfortably inside
range and never saturating. If the scale were actually 0.05 L/hr, peak flow
would be 126 L/hr, beyond what a 5.3L can physically flow at any RPM.

---

## The fuel-gauge cross-check does NOT agree — and the gauge is the one at fault

An independent cross-check using `0x4D1` `Fuel_Level_Percent` x
`Fuel_Total_Capacity` disagrees badly. Summed over sessions with no mid-session
refuel:

| Source | Fuel consumed |
|--------|--------------:|
| `0x3D1` fuel rate, integrated | 71.44 L |
| `0x4D1` tank-gauge drop | 129.24 L |
| Ratio | **1.81x** |

Per-session ratios scatter from 0.34x to 2.21x. If the gauge were correct,
tank-to-bus efficiency would be 17.1% and economy 11.68 mpg — which would
contradict the owner's actual pump records by 47%. **The fuel-rate integration
is therefore the trustworthy channel and the gauge is not usable
quantitatively.**

Two known contributors to the gauge error:

1. **`Fuel_Total_Capacity` reports the stock 98.4 L.** The EV conversion shrank
   the fuel tank (`vtrux.md`), so converting level-percent to litres with the
   factory capacity constant overstates volume by an unknown factor. The
   largest single fill-up recorded in `Vtrux Gas.xlsx` is 21.43 gal (81 L) with
   a median of 14.37 gal, suggesting real capacity nearer 81–85 L than 98.4 L —
   about a 1.2x correction, so this explains part but not all of the 1.81x.
2. **Float-sender damping, hysteresis and slosh**, plus non-linear tank
   geometry. The residual scatter (0.34x to 2.21x) is characteristic of this.

**Open item:** the actual fuel tank capacity is still unknown. Determining it
would close the remaining gap and make `0x4D1` usable as a coarse independent
fuel check.

---

## Caveats

- Efficiency here is trip-averaged and includes cold-start, warm-up and
  transient operation. Steady-state efficiency at the generator's preferred
  operating point is presumably higher than 30.9%.
- The `@20260726_160923` trip 0 result (3.7 mi, 2.4 min of engine time, 33.5%)
  rests on very little fuel (0.246 gal) and should carry little weight.
- Fuel rate is read from the OBD bus, where the ECM is real. The Vehicle-bus
  copy of `0x3D1` was extracted in parallel but not used, since VCM-substituted
  engine data on that bus cannot be assumed genuine.
- Gasoline LHV taken as 33.705 kWh/gal (the EPA MPGe constant) for the
  efficiency calculation.
- `@20260617_193900` is the **smog-pass session** (`vtrux-smog-pass.md`), in
  which the generator was driven by an experimental script that produced a
  ~4945 RPM runaway and a VCM throttle-lift/DFCO event. Its two trips return
  28.4% and 30.2%, both inside the normal band, so they were retained — but
  they are not representative of ordinary generator operation and should be
  dropped if this analysis is ever tightened.
