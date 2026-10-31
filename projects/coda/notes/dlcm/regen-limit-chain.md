# What limits regen on the Coda

Written 2026-09-24, from the C2 one-pedal drive (`coda_20260924_004341_T1`, includes a
highway decel to a full stop) plus the two drives before it.

The user's question was specific: *"I don't want there to be anything other than power
limitations limiting regen at higher speed... would be good to double check what's in action
there."* This file answers it.

Flash record and image lineage: `dlcm-cal-flash-campaign.md`.

> **This file was split on 2026-10-03.** It had grown to 1198 lines covering three
> separate topics. Section numbering below is unchanged so existing references still
> resolve, which is why there are gaps:
>
> | was | now lives in | why |
> |---|---|---|
> | section 2 (`MMAX_ESP_REGEN_TQ_REQ`) | [`esp-torque-intervention.md`](esp-torque-intervention.md) Part II | **and it is falsified** -- B4-5 *is* a limit; see that file's Part I section 3 |
> | sections 4, 4b (C2 problem, C3 fix) | [`pedal-map-envelope-design.md`](pedal-map-envelope-design.md) section 11 | pedal-map design, not regen limiting |
> | section 6 (`0x312`'s limit fields) | [`esp-torque-intervention.md`](esp-torque-intervention.md) Part II | the torque-limit interface |
> | section 7 (the ESC clamp) | [`esp-torque-intervention.md`](esp-torque-intervention.md) | superseded there with the firmware path traced |
>
> What remains here is the original question and its answer: at speed, regen is
> limited by **power**, nothing else.

---

## 1. The answer: nothing but power

Three candidates sit between the accelerator map and the motor. Measured, in order:

| limiter | where | verdict |
|---|---|---|
| the coast row | `0x80044070` z `0xA0023C44` | binds **below ~3000 rpm** |
| M_MIN | DLCM, `0x312` B6–7 | binds **above ~3000 rpm** — constant power |
| `ESP_TractiveTqLimit` (was `MMAX_ESP_REGEN_TQ_REQ`) | ESC, `0x300` B4–5 | ~~never binds~~ — **it does bind, when armed by B4 bit 6.** See [`esp-torque-intervention.md`](esp-torque-intervention.md) Part I section 3 |
| `C_LO` | limiter clamp, `0xA0021542` | −3000, never approached at −1562 |
| **`0x300` B2–3** (`ESP_BrakingTqLimit`) | **ESC** | **a fourth limiter, not known when this file was written — see [`esp-torque-intervention.md`](esp-torque-intervention.md).** Forward, it is the **regen** limit: it went to **0 Nm** on 2026-10-02 and took all 156 Nm with it |
| **`0x300` B4–5** | ESC | forward, this is the **drive** limit, and it binds — 34 armed episodes across 29 sessions, 0.02–0.86 s, limit to 148–223 Nm. See [`esp-torque-intervention.md`](esp-torque-intervention.md) Part I section 3.5 |

> **Scope caveat on this section, added 2026-10-03.** "Nothing but power" is
> measured over *coasting samples in ordinary driving*, and it holds there. It
> is not a statement about every state the car can enter. A fourth limiter
> exists, it is external, and when it acts it dominates everything in this
> table — see [`esp-torque-intervention.md`](esp-torque-intervention.md). The population used here contained no instance of it, which is
> why the list of candidates was three long: `AGENTS.md` → Filters that fail
> silently, mode 1.

**The per-sample gap is zero.** With `gap = delivered − min(map, M_MIN)`, over 2,591 coasting
samples (pedal 0, brake off, >500 rpm): **median gap 0, and 0.0 % as a fraction of the
binding limit.**

| rpm | delivered | M_MIN | map | binding | gap | ESC |
|---|---|---|---|---|---|---|
| 1000–1499 | −1562 | −3000 | −1562 | −1562 | −0 | −1570 |
| 2500–2999 | −1562 | −1815 | −1562 | −1562 | −0 | −1570 |
| 3000–3499 | −1449 | −1515 | −1562 | −1515 | +0 | −1440 |
| 4000–4499 | −1145 | −1148 | −1562 | −1148 | +0 | −1150 |
| 5500–5999 | −790 | −798 | −1562 | −798 | +0 | −790 |

The 18.7 % of samples with a large positive gap are **the rate limiter, not a third
limiter** — they are ramps, not clamps. A representative one runs −8, −35, −70, −122, −182,
−242 on consecutive 20 ms samples: `gradientLimiterNegative_TrqLast` building regen in after
a lift-off. Transient in every case, never sustained.

**Wheel slip rules out stability intervention.** Front-minus-rear wheel speed has a median of
0.0 to +1.5 wheel rpm in every bin including the highway decel. +1.5 wheel rpm is ~0.17 km/h.
(Note this test is only valid at speed — the rear channel's 8 wheel-rpm cutoff makes
low-speed slip unmeasurable in principle; see `../low-speed-driveline-signals.md`.)

**M_MIN is a constant-power limit at about 48 kW.** −2130 at 2250 rpm = 204.5 Nm = 48.2 kW;
−1200 at 4000 = 48.3 kW; −790 at 6000 = 47.6 kW. A −1562 request is 150 Nm, which crosses
48 kW at 3056 rpm — essentially the measured cutover.

**The cutover is a cliff, not a taper.** Fraction of coast samples where M_MIN is shallower
than −1562, i.e. would clamp the request:

| rpm | 2500–2749 | 2750–2999 | 3000–3249 | 3250–3499 | 3500+ |
|---|---|---|---|---|---|
| clamped | 13.2 % | 14.1 % | 29.5 % | **96.6 %** | 100 % |

So −1562 is delivered essentially always below ~34 mph and essentially never above ~35 mph.
Below the cliff the ~10 % that does clamp is SOC-driven, so decel is slightly weaker on a
full battery. At 62 mph the car delivers about 51 % of what the map asks — **purely from
power**, and that is what the user felt.

---

## 3. A contaminated histogram that nearly became a theory

The phase-4 M_MIN sweep showed a bin at 2125 rpm with p5 = p50 = p95 = exactly −2300 — zero
spread, a hard step down from −3000 below and up from −2130 above. A single value across a
whole distribution looks like a discrete limit: a mode boundary, a protection threshold, a
table breakpoint. At 22.8 mph, squarely inside where one-pedal decel lives.

**It is an artifact.** That bin holds **4,337,546 samples against ~27,000–34,000 in its
neighbours** — about 160×. A single value, −2300, is **99.37 %** of it. Strip that one value
and the bin is entirely ordinary: n = 27,502, p5 −2570, p50 −2390, p95 −1100 — and −2390 sits
almost exactly on the straight interpolation between its neighbours (−2730 at 1875, −2130 at
2375 → ~−2430 at 2125). The curve is smooth and continuous through 2125 rpm.

Corroborated from the calibration side: **−2300 appears nowhere in the CAL** (searched as
LE int16; +2300 occurs 10 times but every hit is a positive cell inside the R-gear maps), and
**2125 rpm is not a breakpoint in any speed axis in the torque path** — it is 4681 DLCM
counts, and the accel/brake axis steps 2560 → 6400 there while the speed limb steps
256 → 10240. M_MIN is broadcast *by* the MCM in any case, so a DLCM CAL constant was never
the right place to look.

**Action outstanding:** 4.31 M identical samples is roughly 24 hours at 50 Hz, so this is not
one drive. Something stationary or stuck is being swept in. `one_pedal_model.phase4` should
cap per-session contribution before that distribution is trusted again — **any conclusion
drawn from its tails is suspect until it does.**

---

## 5. Open

- **C3 was built, then rejected.** It is written up in [`pedal-map-envelope-design.md`](pedal-map-envelope-design.md)
  section 11 (migrated from this file's sections 4 and 4b), and its rejection is recorded
  in that file's section 7. The map actually flashed is C4c. This item is closed; it is
  kept because the open list is referenced elsewhere.
- The f = 0.5 design the in-car session still held after its compaction is **dead** — it
  answered a superseded objective, and its open "464 rpm cell" decision is moot under C3.
- **The R maps were not touched by C2** and are still on the −690 plateau with their own
  pedal shape. Symmetry would be a separate change list. Not started.
- Whether the factory's low-speed early crossing is *wanted* once the rest of the pedal
  shifts later is genuinely open. Nobody has deliberately chosen that behaviour — it is what
  the factory did and every flash so far has avoided disturbing it.
- `one_pedal_model.phase4`'s per-session capping (§3).

---

- **A fourth limiter was found 2026-10-03 and this file's section 1 answer did
  not know about it** — `0x300` B2–3, external, commanded 0 Nm on the
  2026-10-02 commute and took all 156 Nm of regen with it. **This is now
  resolved and lives in
  [`esp-torque-intervention.md`](esp-torque-intervention.md)**, not here: the
  magnitude reading was confirmed, both ESC limits were traced from the RX
  accessor to the application site, and the user's own test — that the early
  `codadriveslowturnonwithdefroster*.log` drives should show the same clamp on
  the **positive** torque side — came back **positive**, with the longest armed
  tractive episode in the corpus (0.70 s) in `defroster2`.

  What remains open *for this file* is narrower: whether "nothing but power"
  should be restated now that a fifth and sixth limiter are known. The answer
  in section 1 is still correct for coasting in ordinary driving, which is the
  population it was measured on, and the scope caveat above says so.
