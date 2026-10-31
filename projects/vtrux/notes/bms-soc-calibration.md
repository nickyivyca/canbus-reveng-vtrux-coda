# Vtrux -- BMS SoC calibration and capacity learning

Does the A123 BMS count SoC against a fixed ~60 Ah, or learn each pack's real
capacity? How much usable capacity and buffer does each pack have?

**Plan:** `plans/bms-soc-learning.md`
**Status:** Steps 1-3 complete (2026-10-10). Step 4 next.
**Scripts:** `artifacts/bms_soc_learning.py` (phased); outputs
`artifacts/bms_soc_learning_step1.txt` (inventory and chain),
`artifacts/bms_soc_learning_step1_ct.txt` (CT check), and caches
`bms_soc_learning_inventory.json` and `bms_soc_learning_transitions.json`.

The pack is 3p A123 AMP20M1HD-A. The datasheet
(`a123-amp20m1hd-a-datasheet.pdf`) gives 19.6 Ah minimum per cell, so 58.8 Ah
minimum per 3p group when new. It gives no continuous voltage limits.

The hypotheses under test are the user's, and **unconfirmed**; they are listed
in the plan. In short:

- **H-learn:** the BMS learns real capacity, and its Ah-per-% differs by pack
  or over time.
- **H-10%:** after a 12 V reset the BMS runs on a nominal capacity, shows
  ~20 % at the end of a drive that really reached ~10 %, and corrects at the
  next wake from the weak cell's settled voltage.
- **Alternative:** a fixed count with voltage-based corrections, and no
  learning.

---

## Step 1 -- session inventory and the gaps between sessions (2026-10-10)

### Method

Source: InfluxDB, powertrain bus only. Every query was bounded by the
session's `upload_manifest` window, single-field and LIMIT-ed.

- **Per session:** the median of the first and of the last 30 stored points
  of:
  - `VehicleOdometer` (`0x625`, 1 km);
  - `bms_soc_hires` (`0x411`, 0.01 %);
  - `bcm_soc`;
  - `bcm_cell_vmin` and `bcm_cell_vmax`;
  - `bcm_vbat`.
  Plus whether the charger drew AC current.
- **The cell-voltage no-data value is stored in InfluxDB.** 8.19 V was
  leaking into the medians and is now filtered with `< 3.8 V`.
- **Truck** comes from the odometer (main >= 90,000 km, parts < 60,000 km).
  **Pack** comes from the truck plus the 2025-12-09 swap.

### Coverage

| Pack | Sessions | Dates | Lowest SoC seen |
|---|---:|---|---:|
| main-orig | 42 (18 in the main truck before the swap, 24 in the parts truck after) | 2025-06-25 -> 2026-08-02 | 20.67 % |
| parts-orig (in the main truck now) | 200 | 2026-01-17 -> 2026-09-26 | 12.64 % |

- 11 short captures (2026-03-23/24, 03-30, 04-25) have no odometer, so they
  carry no truck or pack. SoC is flat within each.
- **main-orig is thinly covered.** Most per-pack comparisons will be
  parts-orig against a small main-orig sample.

### Gaps between consecutive sessions, per truck

The odometer has 1 km resolution. **An unchanged odometer does not mean the
truck rested:** an unlogged charge, or stationary use such as export, leaves
it unchanged too. So the odometer-unchanged gaps are split by which way SoC
moved.

| Pack at wake | Odometer unchanged, SoC flat (<1 %) | Odometer unchanged, SoC rose | Odometer unchanged, SoC fell | Odometer moved (unlogged use) | Overlap / missing data |
|---|---:|---:|---:|---:|---:|
| parts-orig (main truck) | 124 | 13 | 9 | 29 | 25 |
| main-orig (main truck, before swap) | 4 | 2 | 0 | 5 | 6 |
| main-orig (parts truck) | 19 | 1 | 0 | 2 | 1 |

### The garage CT cannot attribute home charging to a vehicle

Each odometer-unchanged gap with |ΔSoC| >= 1 % was checked against the garage
14-50 CT.

- **What can be attributed** (`Infrastructure/vehicle-cost-per-mile.md`
  section 5): blocks over 7.3 kW are the 914, and a hold of 25 min or more at
  350-1,400 W is a Vtrux.
- **What cannot:** plain ~6.9 kW blocks.
- **The Coda's charging is mostly not logged.** Its logs cover driving (user,
  2026-10-10), so Coda logs cannot clear a block either.
- Recurring ~4-minute, ~6.9 kW top-ups every ~90 min after a large block are
  **likely unlogged Coda charges** (user, 2026-10-10).

**Consequence:**

- **Gaps where SoC rose cannot be used as evidence.** Where CT energy roughly
  matches the rise, home charging explains it (02-26, 04-25, 07-16, 07-20).
  Where it does not, another car on the outlet or charging away from home is
  possible, and nothing separates those from an upward correction. No rise
  stands out as a correction.
- **Gaps where SoC fell are usable.** Charging can only raise SoC, so the
  attribution problem does not touch them. Their alternatives are stationary
  use and parasitic draw.

### SoC falls with the odometer unchanged (parts-orig; there are none on main-orig)

| Gap (Pacific) | SoC end -> wake | Weakest cell (vmin) | CT in gap | Status |
|---|---|---|---|---|
| 2026-01-17 00:39 -> 17:28 PST (16.8 h) | 100.00 -> **86.80** (-13.2) | 3.597 -> 3.336 | only a 2-min, 547 W blip as the log ended (the full-charge hold finishing) | **unexplained candidate** |
| 2026-03-05 00:51 -> 08:36 PST (7.8 h) | 34.54 -> **18.40** (-16.1) | 3.184 (under load, end of a battery-only drive) -> 3.227 (rested) | nothing | **unexplained candidate**; both sides logged |
| 2026-07-25 17:04 -> 07-26 12:42 PDT (19.6 h) | 51.62 -> 41.56 (-10.1) | 3.276 -> 3.285 | away from home | probable export use (camping, user) |
| 2026-04-18 -> 04-20 (61.8 h) | 79.36 -> 74.88 (-4.5) | 3.299 -> 3.288 | 9 kWh, which must be another car | unexplained, small |
| five others | 1-3 % each | | | small |

- **The 01-17 fall is not a general after-full-charge behaviour.** On
  2026-03-06 the truck rested 12 h at 100 % and woke at 100.00 %.
- **The 03-05 fall is the best-bounded case:** a 16 % drop over ~8 h parked,
  with no charging on the CT and both sides logged. It is in the direction
  H-10% predicts. Unlogged parked use is not excluded.

### The ~10 % event (2026-06-17)

The user identifies this as the 2026-06-17 "found in the red" event
(`specific-trucks/battery-degradation-tracking.md`).

- **The drive that caused it was not logged.** The previous logged drive
  ended at **77.88 %** on 2026-06-14 (~17:00 PDT, odometer 97,507). The next
  logged session, `vtrux_20260617_193900` (19:39 PDT on 06-17), starts at
  **12.64 %**, the lowest SoC in the corpus, with the odometer at 97,578: 71 km
  of unlogged use in between.
- In that session the generator raised SoC to ~20.6 % over 74 km, which
  matches the "sustained to its ~21 % floor" in the degradation note.
- **H-10% is consistent with this, but only the wake value is observed.**
- The weakest cell at the 12.64 % wake read **3.228 V**, about the same as at
  an indicated 18-20.6 % in other sessions (3.227-3.233 V). That comparison
  does not control for rest time or load, and step 3 is to do it properly.
  **Corrected in step 3:** that reading was taken with the generator charging
  the pack at +15-50 A, not at rest. The log starts after the wake, so the
  rested voltage at the wake was not captured.
- That session and the following ones are **rig sessions** (laptop generator
  bridge inline, `data-sources.md`). The user states the bridge does not
  affect battery behaviour, so they are kept for this work.

### Carried into step 3

- The two unexplained falls (01-17, 03-05) and the 06-17 wake are to be
  examined in detail: SoC in the first minutes after wake, cell voltages, and
  temperature.
- Odometer-unchanged gaps with flat SoC are the clean-rest baseline: 124 on
  parts-orig, 23 on main-orig.

---

## Step 2 -- coulomb count against SoC within sessions (2026-10-10)

### Method

- **Data:** a 1 s series per session from InfluxDB (powertrain), using
  server-side `GROUP BY time(1s)` bounded by each session's window: mean
  `bcm_ibat`, mean `bcm_vbat`, last `bms_soc_hires`, max charger AC current.
  Cached in `artifacts/bms_soc_learning_1s.json.gz`.
- **Segments** break at any missing second of current or SoC. Both are
  ~20 Hz messages, so a missing 1 s bin is more than 20 frame periods.
- **Ah per % SoC** is measured per segment, and per 10 % SoC band crossed
  within a segment.
- **Mode:** charge = charger AC > 2 A throughout; drive = never.
- **Pack current sign:** + while charging. Confirmed: 66 of 66 charging
  segments with rising SoC integrate to positive Ah.
- **Scripts:** phases 4-6 of `artifacts/bms_soc_learning.py`. Outputs:
  - `bms_soc_learning_step2.txt` / `.json` (bands, segments, SoC steps);
  - `bms_soc_learning_step2_startup.txt` (startup frame);
  - `bms_soc_learning_bootframes.json` (power-on capture by month).

### Finding 1 -- each pack has its own capacity figure, not a fixed 60 Ah

**Measured.** The first `bms_soc_hires` value after a BMS power-on is a fixed
fraction *k* of the value one second later (the "startup frame"):

| Pack | Sessions | *k* median | *k* range | 58.8 Ah x *k* | Measured Ah per % on clean drives and charges |
|---|---:|---:|---|---:|---:|
| main-orig | 26 | **0.8257** | 0.8248-0.8302 | 48.6 Ah | ~0.486 (48.6 Ah) |
| parts-orig | 59 | **0.7885** | 0.7767-0.7902 (one outlier at 0.9219) | 46.4 Ah | ~0.462-0.465 (46.2-46.5 Ah) |

The outlier is `vtrux_20260714_161319`, where the step came 300 s after the
first point rather than 1 s. Low-SoC startups sit at the low end of the
parts-orig range.

- **58.8 Ah x *k* reproduces each pack's measured Ah per %.** Read the other
  way, both packs imply a reference capacity of 58.8-58.9 Ah, which is the
  AMP20 datasheet minimum (3 x 19.6 Ah).
- **parts-orig's *k* drifts slowly down:** 0.7880-0.7890 (Jan-Mar 2026),
  0.7874-0.7878 (Apr-May), 0.7867 (Jun), 0.7849-0.7858 (Sep). That is
  46.4 -> 46.2 Ah, above the 0.01 % resolution. main-orig went from
  0.827-0.830 (2025) to ~0.825 (2026).

**Hypothesis (unconfirmed):**

- The settled SoC is remaining Ah divided by a per-pack capacity estimate:
  ~48.6 Ah for main-orig, ~46.4 Ah for parts-orig.
- The startup frame is the same remaining Ah divided by 58.8 Ah nominal.
- So *k* acts like a stored state-of-health figure: ~83 % for main-orig, ~79 %
  for parts-orig.
- This supports H-learn in the form of a pack-specific, slowly updated
  capacity. Real slow fade (the weak-cell concern) would look the same and is
  not separated.

**What the figure is, and what is usable (added 2026-10-10).**

- **Ah per % is a slope:** Ah moved per 1 % of *indicated* SoC. It is flat
  across the bands measured (parts-orig driving: 0.463 at 20-30 %, 0.464 at
  30-40 %, 0.463 at 40-50 %, ~0.46 up to 80-90 %). So 46.4 / 48.6 Ah is what
  the BMS counts as 0 -> 100 % indicated.
- **In use, the generator holds a ~20 % floor** (user), so the window actually
  used is 20 -> 100 %: **~37 Ah on parts-orig, ~39 Ah on main-orig.**
- The 0-20 % band is never exercised, so the slope there is assumed, not
  measured. Whether indicated 0 % is truly empty is unobservable with no data
  below 12.6 % (plan step 4).

**Two readings of *k* ~= 0.79-0.83, not yet separated (both unconfirmed):**

1. **Faded or learned capacity.** *k* is a per-pack state-of-health figure,
   the hypothesis above.
2. **A deliberate usable window.** The BMS uses ~80 % of the cells' 58.8 Ah
   nominal as its 0-100 %, and the startup frame reports against full nominal.
   - The startup frame is proportional to settled SoC with essentially no
     offset (intercept ~ -0.1 %). So indicated 0 % lines up with nominal 0 %,
     and indicated 100 % with ~79-83 % of nominal: any reserve would be at the
     **top**.

Evidence for reading 1 over reading 2:

- At indicated 100 %, vmax holds at **3.600 V** during the hold, which is
  effectively full for LFP. That argues against a top reserve.
- The packs differ (0.826 vs 0.789), and parts-orig's *k* drifts slowly. A
  single design window would normally be identical for both and fixed.
- Against that, the two packs are **different builds** (main-orig lacks the
  conditioning-module group, `specific-trucks/battery-degradation-tracking.md`),
  so a different configured window per pack is not excluded.

Plan step 4 (integrated Ah over the largest swings, with cell voltages at both
ends) is the test.

**Caveat:** the Ah figures depend on `bcm_ibat`'s gain. It agrees with the
charger's DC reading at bulk to within a few % once the HV load is allowed for
(see `charger-efficiency-and-grid-consumption.md`). It is not independently
calibrated; that is plan step 5.

### Finding 2 -- the 2026-03-05 drop was a correction just after wake

**Measured.** The blue-EVSE capture caught the BMS waking at 08:38:27 PST:

- `bms_soc_hires` went **27.21** (the startup frame) -> **34.45** (the
  pre-rest value; the battery-only drive had ended at 34.54);
- then -> 18.92 -> 18.65 -> **18.40** within 3 s, with pack current ~0 A.

So the BMS woke still holding its pre-rest SoC, then corrected itself down
16 %, presumably from the resting cell voltage. That is the wake-time
correction H-10% needs. It rules out parked use counted by an awake BMS. It
does not rule out a drain while the BMS was asleep, though ~7.5 Ah in 8 h
with the truck off would need ~0.9 A.

The other falls did not capture the wake moment:

- 01-17, 06-17 and 07-26: the log started after the truck was already
  running or charging.
- 04-20: the drop was already in the first frames.

### Finding 3 -- parts-orig's counting rate changes in eras

**Measured.** Clean drive and charge segments give the following Ah per %:

| Period | parts-orig Ah per % | Note |
|---|---:|---|
| 2026-01-17 to 01-18 | 0.309 / 0.523 / **0.597** | 0.597 is in `charge_9pm`, right after the unexplained 01-17 fall |
| 2026-01-23 | 0.420-0.437 | |
| 2026-01-26 to 03-04 | ~0.464 | |
| **2026-03-05 to at least 04-24** | **~0.400** (charge and drive) | starts at the 03-05 corrected wake; *k* unchanged at 0.788 |
| 2026-05-04 | 0.357 / 0.407 | charger-swap day |
| 2026-05-14 to 06-11 | 0.462-0.474 | |
| **2026-06-18** | **0.402** | the session right after the ~10 % event |
| 2026-07-14 to 07-15 | 0.399-0.414, then 0.447-0.460 | |
| 2026-07-19 to 09-26 | 0.459-0.473 | steady |

main-orig is 0.483-0.492 throughout, except one drive at 0.391
(2026-08-02, parts truck).

- In the ~0.400 eras, SoC moves ~15 % faster per Ah than the stored capacity
  implies, in both directions, while *k* stays put.
- **Hypothesis (unconfirmed):** a second, temporary rescaling layered on the
  stored capacity. Two of its three eras begin right after a downward
  correction (03-05, 06-17). What starts and ends it is not established.

### Finding 4 -- the startup frame marks every BMS power-on, so it is not a 12 V-reset marker

> **Corrected in step 3:** the 8.19 V cell-voltage frame is **not specific to
> a power-on**. Of 271 mid-session 8.19 V frames, 188 have no startup frame
> with them; the frame also appears when the BMS goes offline, as at the bottom
> of the 03-04 export test. So "power-on captured" in phase 6 is an upper
> bound. The startup frame itself remains the power-on marker.

- Wherever a capture recorded the BMS power-on (its one-off 8.19 V cell
  voltage frame), the startup frame is present too. That holds for 85 of
  about 90 captured power-ons, and every startup frame bar two comes with
  one.
- How often power-ons are captured falls from March (29 of 39 sessions) to
  July (0 of 24). That follows the logger, not the truck: laptop captures were
  started before key-on, while the Android logger boots after the truck is up
  and rarely catches the startup (user-confirmed).
- The large "SoC +15-20 % with no Ah" segments in the raw output are this
  frame, not events. Two one-second blips at the end of the full-charge holds
  (`charge_M0` 100 -> 79.16 -> 100 at 00:39 PST 01-17; `another_M0` 01-24)
  carry the same ratio, which looks like a BMS re-initialisation when the hold
  ends.

### 12 V reset context (user, 2026-10-10)

- Until about **2026-06-17** the main truck had a relay on its 12 V battery
  with an undervoltage cut-off, which **often cut 12 V while the truck was
  parked**. That is why the OBD readiness monitors kept resetting.
  - It never cut while the truck was on, because the DC-DC holds 12 V up.
  - So a cut leaves no trace at the end of a session.
- It was removed around the 2026-06-17 smog-readiness work, so the monitor
  state would hold.
- **So 12 V resets were frequent before 2026-06-17 and rare after.** That date
  is the era cut for step 3.
- Readiness status is not broadcast on the bus. It is visible only to a
  polling scan tool (`vtrux-smog-pass.md` Task 4). At the start of the
  06-17 smog run, PID 01 showed Fuel, Catalyst, Evap and O2 incomplete.

Observed so far, but not yet tested:

- Before the cut: the 03-05 corrected wake, the 06-17 ~10 % wake, and the
  ~0.400 counting eras.
- After it: the counting rate settles at 0.46-0.47, and the only large
  overnight fall is the camping one, which probably involved export.

---

## Step 3 -- SoC across rests, power-ons and full charges (2026-10-10)

### Method

- **Scripts:** phases 7-12 of `artifacts/bms_soc_learning.py`, plus
  `artifacts/ct_charger_signature.py`. Outputs:
  - `bms_soc_learning_step3.txt` / `.json` -- every odometer-unchanged
    transition: SoC at the end of one session and at the next wake (after the
    startup frame), settled cell voltages at both (seconds with |ibat| < 2 A),
    temperature, and every 8.19 V frame inside a session;
  - `bms_soc_learning_wakeend.json` -- the cache behind it: the first and last
    180 s of cell vmin / vmax / tmin / tmax per session, and every 8.19 V
    frame;
  - `bms_soc_learning_timeline.txt` and `bms_soc_learning_vmin1s.json.gz` --
    a per-pack timeline, with a 1 s weakest-cell series for every session
    that goes below 40 %;
  - `bms_soc_learning_hold100.txt` / `.json` and
    `bms_soc_learning_hold_charge.txt` / `.json` -- discharges that start at
    100 %, and charge that goes in after the display reaches 100 %;
  - `bms_soc_learning_rises.txt` -- SoC rises with the odometer unchanged,
    against home charging;
  - `ct_charger_signature.txt` -- whether the garage CT can tell the cars
    apart by how power follows line voltage.
- **Pack current:** the BMS's own `bcm_ibat`, net (regen and generator charge
  included).
- **Temperature:** `bcm_cell_tmin`. 87 C is its power-on no-data value and is
  filtered out.

### Finding 1 -- the BMS keeps its SoC through 12 V loss

**Measured.** 48 mid-session power-ons have both a startup frame and an SoC
value just before. In every one the BMS came back at its pre-power-off SoC,
within 0.13 %, and *k* was unchanged. They include the deliberate cuts:

| Event | SoC before -> after |
|---|---|
| Isolation-fault recovery (12 V battery disconnected) | 100.00 -> 100.00 |
| `vtruxunplugpumpthenhvbatterylvconnector` (HV battery LV connector unplugged) | 95.73 -> 95.73 |
| Parts-truck evap fuse experiment | 80.40 -> 80.40 |
| Via fusebox cut, 06-17 21:56 | 20.64 -> startup frame 16.00 -> 20.60 |

- **The Via fusebox cut does remove BMS power** (its startup frame is there).
  This answers the plan's open question.
- **`vtruxinterlocktest`'s 12 V cycle is unresolved** from 1 s data: 8.19 V
  frames, no startup frame, SoC flat at 95.83.
- **The same holds at the start of sessions.** In 66 captured wakes after
  rests (up to 136 h), the first settled SoC matches the previous session's
  last value to within about 0.05 % in nearly all.

**So the "12 V reset restarts the BMS on nominal capacity" part of H-10% is
not supported.** **Caveat:** every observed cut lasted seconds to minutes. A
cut lasting hours while parked is covered only indirectly, by the long-rest
wakes of the relay era.

### Finding 2 -- a correction needs a rest at a low voltage

**Measured:**

1. **Never during use, even at the low end.** In every drive below 40 %,
   Ah per 5 % band stays at **0.462-0.471 down to 15 %**. That includes the
   03-04 export, where the weakest cell fell to 2.72 V at an indicated 17.5 %,
   and the 03-05 battery-only drive, which reached 2.77 V at an indicated
   ~34 %. Apart from startup frames, holds at 100 % and the re-initialisation
   blips, there are no corrections within sessions.
2. **Not after a short rest.** The 03-04 05:40 wake came 3 min after the BMS
   cut the pack (finding 3), with vmin still relaxing at 2.905 V. No
   correction.
3. **After a long rest at a low voltage.** The 03-05 wake came after 7.8 h at
   a rested vmin of 3.227 V: -16 % within 3 s (step 2, finding 2). Every
   other rested wake at an indicated 30 % or above read >= 3.275 V; rested
   wakes at ~20 % read 3.234-3.239 V. So the correction moved SoC to where the
   voltage puts it.
4. **Not after long rests in the plateau or at the top.** These include
   136 h, 69 h, and the 06-14 wake after 88 h at 3.370 V. Rest drift there is
   about 0, and at most -0.8 % after 69-148 h.

**Hypothesis (unconfirmed):** both are needed -- a rest, and a rested voltage
off the LFP plateau. There is one clear positive case and no negative case
of a long low-voltage rest with a known error present. The red wake
(2026-06-17) fits, but was not logged: the first logged point is already
12.50 % with the generator charging.

The other falls with no driving:

- **04-20 (-4.46 %):** the power-on was captured, but its startup frame
  (59.01 = *k* x 74.94) already carried the lower value. The change happened
  before that power-on, at 3.28-3.29 V, a voltage that cannot tell 75 % from
  79 %. An unlogged wake or use is more likely than a correction.
- **01-17 (-13.3 %):** unexplained, and unique. Five other rests from 100 %
  (12-335 h) woke at 99.85-100. That charge had 12.6 Ah go in after the
  display reached 100 % (finding 4), and the BMS re-initialised at the end of
  its hold.

### Finding 3 -- on 03-04 the BMS cut the pack with the weak cell at the knee, at an indicated 17.3 %

**Measured.** The export test ran down to an indicated 17.30 %. Over its
last minutes, at about 19 A, the weakest cell fell to **2.733 V** while vmax
was 3.05-3.10 V (a spread of ~0.3 V). `bcm_alarm` was at TYPE2 from at least
05:28 PST. At about 05:30:40:

- the main contactor opened (`0x410` state 1 -> 0; `0x440` state 11 -> 14);
- the discharge and charge limits went to 0;
- cell and pack voltage switched to their no-data values;
- SoC froze at 17.30, and `bcm_ibat` froze at exactly -1.725 A (a held
  value, not a reading);
- the 12 V rail fell from 14.2 to 12.4 V as the DC-DC lost HV, and the Bel
  stopped transmitting.

**It was not a logging failure:** frames kept arriving on `0x410`, `0x411`,
`0x420`, `0x430` and `0x440`; their contents changed. The BMS cut the pack
itself, most likely on the weak cell's undervoltage, and stayed awake on 12 V
reporting no-data. The next session woke with vmin at 2.907 V.

**Interpretation (unconfirmed):** the weak cell group was empty at an
indicated ~17 %. Define **E = displayed SoC minus true SoC**, in percentage
points, with "true" on the BMS's own scale (46.4 Ah for parts-orig) and 0 %
where the weak group runs empty. Here E was about +17.

- **The low end shows it too.** At an indicated 30 %, normal drives read
  vmin 3.13-3.19 V under 64-110 A. The export read **3.106 V at only 18 A**,
  and 2.90 V at 20 %.
- **E survived a charge.** The pack was charged to the 80 % hold after the
  cut, then driven on 03-05 to an indicated 34.5 % (reaching 2.77 V). The
  03-05 wake corrected by 16 %.

### Finding 4 -- holding at 100 %: charge counted above 100 %

**Measured.** Discharges that start at 100 % hold there while charge comes
out, then count at the normal rate:

| Drive | Ah drawn while held at 100 % |
|---|---:|
| 06-14 (the last logged drive before the red wake) | 12.46 (13 min) |
| 07-15 | 7.07 |
| 08-02 (main-orig, parts truck) | 6.36 |
| 03-06 | 1.28 |
| 07-19, 08-30, 09-13 (after logged full charges) | 0.1-0.2 |

Charge that goes in after the display reaches 100 % (pack current integrated
until the charger stops):

| Charge | Min after 100 | Ah in after 100 | Mean A, first hour | Mean A after |
|---|---:|---:|---:|---:|
| 01-17 `charge_M0` | 211 | 12.6 | 11.5 | 0.42 |
| 07-15 | 68 | 8.5 | 7.6 | -- (held 7.07 on the drive) |
| 05-04 `192242` | 125 | 8.1 | 7.8 | 0.27 |
| 01-23 | 406 | 5.4 | 5.1 | 0.06 |
| main-orig 04-22 | 474 | 3.0 | 2.3 | 0.10 |
| 01-26, 07-27, 08-16, 09-13 | 42-161 | 0.2-0.65 | 0.16-0.93 | 0.04 |

All of these ended with vmax at 3.597-3.601 V.

- **The held amount matches what went in after 100.** 07-15: 8.5 Ah in,
  7.1 Ah held. Parts truck 08-01 -> 08-02: about 6 Ah of a 16.4 Ah home charge
  went in after 100 % (10.6 Ah to get from 78.11 % to 100 %), and 6.36 Ah was
  held.
- **The excess comes in at several amps in the first hour**, while the
  charger is still in bulk or taper, not from the steady hold current
  (0.04-0.4 A, at most ~0.5 Ah over hours). Leaving the truck plugged in is
  what lets it go in (user observation, 2026-10-10: holds follow long charges);
  the underlying point is that the display reached 100 % while the pack still
  had 5-12 Ah to take.
- **The amount varies, 0.2-12.6 Ah,** across charges that all finished at
  3.6 V, so it is not a fixed reserve at the top. The large ones fall in
  unsettled periods (01-17 and 01-23 just after the pack swap; 05-04, the
  charger-swap day, counting at 0.36-0.41 Ah/%; 07-15, a ~0.40 era); the
  small ones in the settled period after 07-19.
- **The excess is sometimes discarded:** 05-04 `192242` (7.4 Ah in; the next
  wake, after 15.5 h and 5 km, read 94.4 %) and 01-17 (12.6 Ah in; the wake
  16.8 h later read 86.73 %). No rule separates kept from discarded; rest
  length does not.
- **Not reconciled:** the interposer spec's +0.85-2.55 A in the first hour of
  the truck's own hold. The three clean logged holds here (01-26, 07-27, 09-13)
  average 0.16-0.26 A in the first hour after the display reached 100 %. The
  spec's figure may cover a different window.

**Hypotheses (unconfirmed):**

1. The BMS keeps counting above 100 %, shows 100, and holds until the excess
   is used up.
2. **That carries E through a full charge.** If the display is E high when a
   charge starts, it reaches 100 while the pack is at 100 - E; the rest goes
   in as excess and is held on the next drive, so the count resumes still E
   high. Only a rest at a low voltage (finding 2) removes E.
3. In a fast-counting era the display climbs ~15 % too fast per Ah while
   charging and reaches 100 early, which is one way E could be created.

### Finding 5 -- the 06-11 -> 06-14 charge, and the red wake

The 06-11 drive ended at an indicated 29.36 % (rested vmin 3.24 V, which
agrees); the 06-14 drive started at 100 % after a taper and hold (cells at
3.6 V), with the odometer at 97,480 km at both. An apparent ~20 Ah shortfall
of home charging is **explained by a plug swap** (suggested by the user, then
found in the CT trace): the 06-13 block holds a single half-power minute at
14:59 PDT (3,533 W) between two plateaus at different levels.

| Charge (PDT) | Car | Wall energy | ~Ah into the Vtrux pack |
|---|---|---|---:|
| 06-11 21:50-23:08 | Coda (abrupt end, then top-ups) | 8.9 kWh | -- |
| 06-13 13:30-14:58, ~6,970 W / 28.6 A | Coda (drove home 13:04-13:28) | ~10.3 kWh | -- |
| 06-13 15:00-16:37, ~6,860 W / 28.1 A | **Vtrux**, unplugged in bulk | ~11.1 kWh | ~24 |
| 06-14 13:51-16:53, taper then 117 min hold | **Vtrux** | 7.6 kWh (6.3 bulk) | ~13.5 |

Ah estimates use 79.5 % wall-to-pack at ~370 V (+/-15 %).

- The Vtrux got ~37.5 Ah (~32-43 Ah), against ~33 Ah needed from 29.36 % to
  full on the BMS's scale. **No gap.**
- **Open:** on those numbers the display reached 100 % partway through the
  06-14 charge, leaving ~5 Ah (0-10 Ah) above 100, yet the drive held
  12.46 Ah. Either payback with both estimates on the low side, or partly
  charge drawn while the gauge did not count down. Either way, the 06-14 drive
  ended at an indicated 77.88 % with the pack lower than shown, and 71 km of
  unlogged driving followed before the wake at 12.64 %.
- **Proposed test (step 4):** after each large hold, does the weak cell run
  out early at the low end (low vmin at an indicated 25-30 % under load)?
  Early means uncounted discharge; normal means payback.

### Finding 6 -- before and after the 2026-06-17 era cut, and the two packs

- **Power-ups cannot be compared between eras:** 66 captured session-start
  power-ons before the cut, 4 after. All 4 behave as before.
- **Falls with no driving occur in both eras.** Before: 01-17, 03-05, 04-20,
  and three of 1-2 %. After: the camping fall (-10 %, probable export) and one
  of -2.9 %. Since SoC survives 12 V loss (finding 1), the relay era has no
  obvious mechanism for the falls.
- **main-orig has no falls or corrections** in 26 transitions, but it has
  never been below 20.67 %, so the packs cannot be told apart on this.

### Lead -- the 08-02 drive after the parts truck sat 90 days

After its 6.36 Ah hold, the 08-02 drive counted at **0.34-0.37 Ah/%**, against
main-orig's 0.486; over the whole drive including the hold it was 0.476.
**Hypothesis (unconfirmed):** the ~0.40 Ah/% eras may be the displayed SoC
catching back up to an internal estimate after the two diverge, rather than a
rescaling.

### Garage CT attribution, refined (user, 2026-10-10)

- **Coda:** a charge ends abruptly (minute averages fall straight to ~0) and
  is followed by ~4-min top-ups at ~6.9 kW every ~90 min. The Vtrux never
  tops up.
- **Vtrux:** a full charge tapers and then holds at ~550 W (350-1,400 W).
- **A swap inside a block** shows as one half-power minute between two
  plateaus at slightly different levels (06-13 above).
- **What does not separate them in minute data:** how power follows line
  voltage (both draw a near-constant ~28.2-29 A at the meter) and the start
  of a block (both reach 6.8 kW in 1-2 min).
- **Re-attributed with these rules, every SoC rise with the odometer unchanged
  in the CT era is accounted for by home charging** (02-26, 07-15, 07-20 by
  energy; others oversupplied by the other truck's charging), once the 06-13
  swap is counted.

### Carried into step 4

- The low-end test of holds (finding 5).
- Whether E has an origin besides the fast-counting eras.
- Bottom-buffer evidence: the 03-04 cut at an indicated 17.3 % (finding 3).
