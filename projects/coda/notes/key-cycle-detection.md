# Key-cycle detection, and what a module dropout actually means

**Established 2026-09-26/27.** Started from a narrow question — a staggered multi-module
dropout in two 2026-03-22 captures, which looked like it might be a vehicle fault — and
ended with a general way to date an ignition cycle from inside a capture.

## The problem: the obvious witness dies with the key

`0x240` is the natural place to look for key state. Its `CM_` calls B0 the system power
mode, `0x11` key-on and `0x01` Ready. But `0x240` is an IGN-switched module: it stops
transmitting during a key-off, so it cannot report the off period. Measured across
`coda_20260322_153141_T0`: **11,670 frames of `0x01`, and a single frame each of `0x15`
and `0x11` as it reboots**. It tells you the car came back, never that it left.

Every module that could confirm a key-off is one of the modules that stops. The way out is
to look only at what **survives**, and ask which of those bytes change and revert.

## The witness: `0x370` `VehiclePowerState` (B0[3:0])

`0x370` is transmitted by the **GWM**, which stays powered, so it keeps talking through a
key-off. The sender is documented, not inferred: factory DTC master list row 215,
`U0146 "COM Timeout with GWM (Vehicle Faults - 0x370)"` set by the BMU, the same naming
convention as row 214's `U0108 "COM Timeout with CHM (0x615)"`.

The state ladder, read off `codadriveslowturnonwithdefroster2.log` — a deliberate slow
key-on with pauses at each key position:

| t (s) | B0[3:0] | B3 | key position |
|---|---|---|---|
| 0.00 | 2 | `0xF1` | wake / accessory, sub-mode not yet valid |
| 9.46 | 4 | `0x11` | **ignition on** |
| 17.10 | 9 | `0x11` | crank |
| 17.28 | 6 | `0x12` | post-crank |
| 19.22 | 5 | `0x14` | **ready**, HV up |
| 701.73 | 3 | `0x14` | key-off begins |
| 706.73 | 1 | `0x11` | shutting down |

**The descent is time-ordered, and how far it gets depends on how long the key stays off.**
It runs `5 -> 3 -> 1 -> 0`, with state 3 taking 5.0 s and state 1 a further ~5.2 s. A
restart resumes from wherever it had reached, so **both `1 -> 2` and `0 -> 2` ascents are
real**: a key-off under about ten seconds turns around in state 1 and never reaches 0, a
longer one reaches 0 and ascends from there.

`coda_20260322_160846_T0` settles this on its own, containing both behaviours on one
channel in one file:

```
5(92.2s) 3(5.0s) 1(1.8s) 2 4 9 6 5(17.5s) 3(5.0s) 1(5.0s) 0(1.6s)
         mid-file cycle, 8.7 s off        end-of-file key-off
         turns around in state 1          runs all the way to 0
```

`coda_20260507_162751_T0` does the same with state 1 truncated to 0.7 s. Established with
the `Coda wheel speed TPMS` session, 2026-09-27.

**A short state-1 dwell has two different causes and only one is an artefact.** On D CAN it
can be the 6.2 s hold-off cutting the state short (artefact — the state continued, you
stopped seeing it). On any bus it can be a quick restart genuinely interrupting the step
(real). Distinguish them by what follows: a truncation ends the message, an interruption is
followed by `2`.

This showed the `"Off"` label on state 1 in the DBC's `VAL_` table to be wrong — 0 is the
resting off state and 1 is a timed shutdown step that a quick restart interrupts.
**Corrected in `CODA-D-CAN.dbc` on 2026-09-29** (owner-approved): the table now reads
`0 "Off"` and `1 "Shutdown"`, where before it had `1 "Off"` and no entry for 0.
The evidence is the descent timing above, not the shape of the ascent — an ascent leaves
from wherever the descent reached, so both `1 -> 2` and `0 -> 2` are real and neither
says which value is the resting state.

Those timings match the key positions recorded independently in
`driving-sequence-investigation.md` (2026-02-19, from event-cluster analysis) **to 0.04 s**
— two methods, seven months apart, same capture, same answer.

Four things make this usable rather than suggestive:

- **B0's high nibble is a constant `0x1`** across 15,000 frames. All the motion is in the
  low nibble, which is exactly the field the DLCM firmware reads (`FUN_80080666`, mask
  `0x0F`), feeding its DTC evaluation block. The firmware agrees the field exists.
- **B0 is bus-independent.** The B and D CAN copies are byte-identical in all 34,919
  matched pairs except B1, which carries what looks like a bus tag.
- **Four other survivors walk their own ladders in step** — `0x248` B4, `0x378` B0,
  `0x270` B7, `0x271` B0 — each matching the 2026-02-19 note in both directions.
  `0x378` B0 going `0x41 -> 0x11 -> 0x21 -> 0x41` is an **HV precharge cycle**, which no
  capture-side artefact can produce.
- **The B CAN copy exists with the key off; the D CAN copy appears only at KEY ON.** The
  GWM forwards to D CAN once that bus wakes.

**It is not the spec's `Powermode`.** Same state set, but the DLCM functional requirements
compare Powermode ordinally (`< Ignition_On`, `< Ready`) and these codes are not ordered:
Crank is `9`, Ready is `5`. Treat it as a coded enum over the Powermode states. The value
*names* above are inferred from ladder position; the field boundaries are not.

## The discriminator

A real key-off shows the descent **before** the GWM stops. So:

| observation | meaning |
|---|---|
| ladder moves across the event | **key cycle** — holds whether or not the witness survived the gap |
| ladder steady, witness transmitting through the gap | modules stopped while the car stayed on |
| same state either side, no descent anywhere | **the capture lost the bus** |

The third row is the one that matters, and it needs stating because it is counter-intuitive:
six captures show 38–39 IDs going silent for 45–145 s with a 4–6 s *staggered* descent,
which looks exactly like a key-off. In all six, `0x370` reads `5` for the entire 300 s
capture — one value, never changing. The key never moved. That recurring
"39 IDs, ~5 s descent, steady Ready" shape is the logger's USB teardown order, not the car's.

## Read the B CAN copy, not the D CAN one

**Corrected 2026-09-27, with the `Coda wheel speed TPMS` session.** Everything above was
originally measured on D CAN, because the bus was picked by D-CAN anchors. That is the
copy that dies first.

The GWM stops rebroadcasting `0x370` onto D CAN about six seconds into the off period
while still transmitting it on B CAN — a consistent figure, not noise:

| capture | B CAN ends | D CAN ends | B - D | B ladder | D ladder |
|---|---|---|---|---|---|
| `coda_20260722_112256_T0` | 36.5 | 30.3 | **6.2** | `31024310` | `31431` |
| `coda_20260724_143053_T0` | 181.3 | 175.1 | **6.2** | `531010` | `531` |
| `coda_20260801_122531_T0` | 178.8 | 172.7 | **6.2** | `5310` | `531` |
| `coda_20260822_164155_T1` | 273.6 | 267.5 | **6.1** | `5310` | `531` |

Two consequences:

- **The D CAN copy truncates the descent.** It typically ends mid-state-1 and never
  reaches the terminal state 0, which is why state 0 was missed and why state 1 looked
  like a 1.1 s flicker when its real dwell is **5.2 s** (B CAN median, n=6).
- **Dwells, measured on B CAN.** State 1: median 5.2 s. State 3: median 5.0 s but ranging
  3.6–12.5 s, and observed at **56.9 s** in `coda_20260424_224500_T0` — so state 3 is
  *not* a fixed-length transition and something can hold the car there. The earlier
  "~5 s in state 3 and ~3 s in state 1" was wrong on both halves.

A short key-off is still fully visible on D CAN, but anything longer needs B CAN. The
corpus classification is unaffected: it keys on the *descent*, which appears on D CAN
before that copy stops.

### The bus discriminator I used was broken

**Corrected 2026-09-27.** The detector scripts identified the D bus with the anchor set
`{0x200, 0x208, 0x212, 0x240, 0x315, 0x278}`. **Every one of those is rebroadcast to B CAN
by the gateway**, so the set scores equally on both buses and cannot tell them apart. The
two 2026-03-22 captures were labelled D CAN on that basis and are in fact **B CAN**: zero
D-CAN-exclusive ids present, all six B-CAN natives present.

The right discriminator is the D-CAN-exclusive set `{0x308, 0x312, 0x325, 0x330, 0x580}`,
which is never rebroadcast — the same set `influx_upload`'s coda profile uses. The scripts
now use it.

Selecting a bus still worked, because these are single-channel captures and there was
nothing to choose, so no result changes. But every statement about *which* bus was wrong,
and this is the invariant in `AGENTS.md` — identify a bus by content — failed by using the
wrong content rather than by ignoring the rule.

**A ladder string is not evidence on its own — check the dwells.** `coda_20260426_150940_T0`
reads `530` and looks like it skips state 1. It does not: state 3 ends at t=32.5 and state 0
appears at t=42.2, with a **9.7 s GWM silence** between them, comfortably long enough to
contain a 5.2 s state 1. That capture settles nothing about whether state 1 is mandatory.

## Corpus result

1,085 Coda captures; 93 multi-module dropout events in 76 captures.

| class | events | captures |
|---|---|---|
| **key cycle** | **23** | 19 |
| DLCM reflash | 1 | 1 |
| capture-side bus loss | 66 | 58 |

**Most multi-module dropouts are the logger or dongle, not the car.** Ladders seen across
the 23: `531`, `534`, `5314`, `4314`, `53124965`, `5314314965`, `5315`. `534` is a drop out
of Ready straight back to Ignition-On with no crank; `53124965` is a full off-and-restart.

The single reflash is `coda_20260924_222022_T11` — 16,855 `0x7E0` frames across the window,
only DLCM-sourced IDs silent, GWM steady at Ready.

Excluded: 462 further events, all from `chargepointcharge.log`, a charging capture with no
`0x370` on the bus. One capture would otherwise have supplied 83 % of the corpus total.

### The 2026-03-22 pair, which started this

```
coda_20260322_153141_T0   17 ids  stop spread 6.02 s  restart spread 1.85 s  off 7.9 s
coda_20260322_160846_T0   13 ids  stop spread 4.78 s  restart spread 1.76 s  off 6.8 s
```

Both are complete key-off/key-on cycles including a crank and an HV precharge, off for
under 8 s — quick restarts, not end-of-drive shutdowns. **Staggered going down,
near-simultaneous coming back up**, which is the shape of modules timing out at different
delays and then all waking together.

## Three detector traps, all of which produced confident wrong answers

1. **A silence threshold must be relative to the message's own period.** `0x620`'s native
   period is 6.0 s, so a flat 2 s threshold flagged it as the first module down in *every*
   event. It never dropped out at all. Because it fires on the slowest messages first, it
   landed at the head of the stop ordering and inflated the recorded spreads
   (10.3 s / 8.1 s reported, against 6.02 s / 1.85 s real).
2. **File order is not time order.** Some captures interleave a few seconds out of order
   within a single `(bus, id)` series. Reading gaps from raw arrival order turned a 78 s
   silence into a 202 s one. Sort each series first.
3. **`SHOW`-style aggregates hide an unrepresentative population.** 462 of 555 raw events
   came from one charging capture; any corpus-wide rate taken before splitting that out
   would have been meaningless.

The first two are recorded as rules in `AGENTS.md` under *Filters that fail silently*.

## Scripts

All in `notes/dlcm/artifacts/`:

| script | does |
|---|---|
| `keyon_indicator_hunt.py` | survivor bytes that change across a dropout's common silence |
| `keyon_state_timeline.py` | the candidate power-state bytes as transition lists |
| `keycycle_corpus_sweep.py` | parallel corpus sweep for dropout events + witness excursion |
| `keycycle_classify.py` | three-way classification of each event |
| `keyoff_dropout_order.py` | the original stop-order detector (period-relative fix applied) |

## Related

- `driving-sequence-investigation.md` — the 2026-02-19 slow key-on that the ladders were
  validated against
- `driver-inputs.md` — gateway rebroadcast table
- `dlcm/coda-dlcm-decompile-notes.md` — the accessor band and the `0x370` field list
- `dlcm/artifacts/dlcm_functional_requirements_full.md` — `Powermode` / `HV_Powermode`
