# Vtrux A123 BMS Fault Records — 0x460 Battery Fault Code Catalog

**Discovered 2026-08-26.** PT-bus message `0x460` (BMS-sourced — drops with the HV battery
LV connector, per `can-disconnect.md`) is the BMS's **fault-record annunciator**: a
page-multiplexed list of 3-byte fault records that names, in the BMS's own vocabulary,
which fault it saw. It had never been decoded because the corpus-wide byte sweeps were
hunting for *differences between* fault instances, and 0x460's content is *identical
across* instances of the same fault — exactly what those sweeps were designed to ignore.

Headline results:

- **The main-orig steady-state charge fault has a specific code (`FC 22 02`)**, pushed at
  the TYPE1 instant, identical in all five instances, seen nowhere else in the corpus.
- **The main-orig precharge abort carries a different code (`F0 E0 00`)** — the BMS
  classifies the two main-orig mysteries as different faults.
- **Contactor/interlock hardware faults carry an `F6` family** with per-scenario
  subcodes (Truck 3, and one event on the main truck).
- **`FC 16 F2` = generator inverter not communicating** (owner theory, confirmed against
  the T4 fuse experiment) — pushed ~30 s after boot when the GENE MCU is silent, then
  latched until a 12V clear; its Apr–Jul 2026 persistence tracks the deliberate
  gen-inverter 12V fuse pulls (see the era timeline below).
- **Isolation faults are unnamed** — they push only the generic fault-trip records.

Scripts: `artifacts/x460_fault_register.py`, `artifacts/x460_interlock_push_timeline.py`,
`artifacts/fault_annunciator_sweep.py` (+ `.txt` outputs); discovered via
`artifacts/type1_micro_forensics.py`.

---

## Message structure (measured)

~20 Hz, DLC=8, multiplexed on **B0 = page index**:

| Page | Layout | Content |
|------|--------|---------|
| `0x00` | `00 02 <count> ?? ?? ?? ?? <tick>` | B2 = record count; B5/B6 = event counters (tick up when records are pushed, including pushes that don't change page content); B7 = slow tick |
| `0x01`–`0x0N` | `<pg> 00 R1a R1b R1c R2a R2b R2c` | Up to **two 3-byte fault records per page, newest record first**; unused slots zero |

- Empty list: only page 0x00 is transmitted (`00 02 00 00 00 00 00 <tick>`).
- With records, pages cycle continuously at ~50 ms/frame.
- Records push when the BMS latches a fault condition, **survive BMS reboot**, and clear
  with FAULT_LATCHED (plug-cycle / 12V reset). Partial expiry observed (`AC 10 00` and
  `FC B0 00` dropped off a stack within 3 minutes while deeper records persisted).
- **Push order at a fault trip: `F0 00 00` first, then `AC 10 xx` ~150 ms later**
  (visible in the gen-iso part2 intermediate page state).

### Staged restore at boot — do not mistake it for fresh pushes

On every BMS boot the standing record list restores from NVM **in stages**: the first
record appears within ~1 s of wake, the next ~15–35 s later. Observed on every
parts-truck boot in the FB/FC era (`FB B6 E4` first, `FC 16 F2` +15–35 s) and on
F7/F8-era boots (`F8` first, `F7` on top). A record "appearing" shortly after boot is
usually a restore, not a new detection. (Resolved for `FC 16 F2`: the May–Jul boots
restore it with the GENE MCU alive at full rate, while the one captured *fresh*
detection — T4 — happened with GENE silent. Stage-2 appearances are restores.)

### Capture caveats

- **The OBD bus also carries a 0x460** (TRAC MCU tier, DLC=5, pattern
  `XX 0E FE 01 <counter>`, ~1 Hz). On any multi-bus capture, filter to the PT bus — or
  to DLC=8 — before reading fault records.
- DBC entry: `BO_ 1120 BMS_FaultRecords_0460` stub in
  `vtrux-powertrain-experimental.dbc` (no `SG_` — extraction needs the mux walk).
- **There is no sibling record message.** A quiet-byte sweep across all standard PT IDs
  in six fault logs (`artifacts/fault_annunciator_sweep.py`) found no second record
  list; on clean single-bus PT captures the only IDs in 0x440–0x4FF are 0x440 and
  0x460. Secondary *flags* that respond at faults: 0x412 (BMS state machine, every
  mode), `0x617 B7` (below), 0x646 warn-lamp field (documented in
  `warning-lamp-investigation.md`).

### Secondary indicator: 0x617 B7 — VCM fault-state flag (new, 2026-08-26)

VCM-sourced near-static message (`B0–B5=00, B6=0x50`). B7 = `0xC8` + a small state
enum: `C8` normal, `C9` = other operating state (meaning unresolved; seen during a
generator window in one healthy log but also at the start of the latched M4_T20 log),
**`CA` = fault-active — sets within ~0.3 s of EPO in every fault mode tested** (steady-
state, precharge, forced isolation, deliberate interlock, gen-iso) and clears when the
condition ends. A cheap single-byte fault classifier, but carries no cause code.

---

## Code catalog

Status: **confirmed** = push moment directly observed against a known cause;
**hypothesis** = attribution inferred from context.

| Record | Status | Meaning / where observed |
|--------|--------|--------------------------|
| `FC 22 02` | confirmed (cause unknown) | **The main-orig steady-state charge fault.** Pushed exactly at the `NONE→TYPE1` instant in all five instances; sole record through the ~10.2 s countdown. Corpus-wide raw sweep: appears **only** in the 2025 main-truck logs — the five escalations plus same-day residue (M4_T20, debuglog_M6, debuglog_M7, all 2025-08-21/22). Never seen after 2025-08-22. |
| `F0 E0 00` | confirmed | **CLOSE_MAINN precharge abort** — all four logged main-orig precharge failures (2025-08-21, 2026-04-25, 2026-05-03, 2026-08-02 ×2). Never seen at any other event. Notably the Aug-2026 instances occurred in a *clean* (F7/F8) record era — the precharge fault is not the interlock condition below. |
| `F6 C0 01` | confirmed | Contactor-fault family, common record — pushed at both of Truck 3's CLOSE_MAINR-stage contactor faults. |
| `F6 C3 02` | confirmed | truck3-round 1 — **welded MAINN** (with `F6 C0 01`). |
| `F6 C5 03` | confirmed | truck3-round 2 — **bad precharge contactor** (with `F6 C0 01`). |
| `F6 CF 00` | confirmed | **Interlock opened while HV up (trip).** truck3-2026-08-05 charge attempt: clean bring-up to `P_CLOSED_CHARGE`, hvil opens spontaneously at +5.7 s, EPO 253 ms later — textbook interlock-fault signature — pushing `F6 CF 00` (with `F0 00 00`, `FB C0 00`, **no AC record**). Also present in debuglog_M6's stack (main truck, evening 2025-08-21 — the M4_T20 aftermath in which HVIL opened twice during HCU oscillation). |
| `FC 16 F2` | **confirmed** | **Generator inverter not communicating** (owner theory, confirmed 2026-08-26 against the T4 fuse experiment). Fresh detection captured live in `vtrux_no_gene_inv_fuse.log`: with the gen inverter's 12V fuse out, the entire GENE family (0x054, 0x470–0x484 except 0x474) is absent from the PT bus, and `FC 16 F2` pushes **~30–37 s after BMS boot with zero GENE frames on the bus**. The record then **latches**: it keeps broadcasting after the fuse is reinserted (GENE back at full rate) and survives until a plug-cycle/12V clear — so the May–Jul 2026 appearances at +15–40 s after every boot (GENE alive at ~100 Hz throughout) are staged NVM **restores** of the standing record from the fuse pulls, not re-detections. The GENE MCU is **12V-powered via that same fuse** (owner-confirmed; an earlier revision here wrongly called it HV-powered). The deliberate interlock test's appearance is likewise a **restore, not a test-induced push**: it lands at boot+39.4 s with GENE broadcasting continuously beforehand, and the record had been standing on the main truck since at least **2026-01-26** (`vtrux_charge_M1`, post-swap work era). Era map: pushed fresh whenever the gen-inverter fuse was out >~30 s with the BMS awake (post-swap era ≤Jan 26; Apr reinstall era; ~May 3); standing until the next 12V clear; absent in gen-in-service eras. |
| `FB B6 E4` | observed, identity unknown | Frequent standing companion to `FC 16 F2`, but with an **independent lifecycle**: the Mar-6 isolation test has `FB B6 E4` standing *without* `FC 16 F2` (something re-latched FB alone between Feb 25 and Mar 6 — the ucsc charger-debug era), and in T4 only `FC 16 F2` pushed fresh. Always restores first at boot. A DCDC-lost-comms reading was floated and is now **weakened**: in M3 the DCDC went silent at EPO+7 s with no `FB B6 E4` push (though the BMS was nearly powered down by then — inconclusive rather than falsified). Push moment never captured; **not** the isolation record (absent during gen-iso era; the forced isolation EPO pushed only generics). Note `FC 16 F2` (comms-fail, confirmed) is an FC-prefix record while this is FB — no "lost-comms family" prefix pattern is established. |
| `AC 10 xx` | confirmed | **Fault-EPO record with parameter.** `AC 10 00` at most fault-initiated EPO trips. **Not universal**: absent at Truck 3's 2026-08-05 interlock trip; `AC 10 01` (only non-zero parameter seen) at the 2026-06-18 00:21 drive-mode trip. **Not pushed at normal key-off** (which never asserts EPO — 6/6 clean key-offs 2026-06-17) and **not pushed at operator EVSE unplug** (2026-07-14). |
| `F0 00 00` | confirmed | **Universal fault-trip shutdown record** — pushed first (before `AC 10 xx`) at every fault EPO observed, including truck3-8-5. Not pushed at key-off or unplug. |
| `FB C0 00` | hypothesis (strong): charger went away during charge mode | Pushed within **30–150 ms of the Bel charger's last CAN frame** in all four measured steady-state instances — at EPO+3.0–3.2 s in M0/M1/M3 (Bel's orderly post-EPO shutdown) and at **EPO+119.1 s in 0822, where the Bel famously did not fault and stayed alive until the operator unplugged** (the push lands exactly at the unplug). Too fast for a comms timeout (~10 Hz Bel frames) — the BMS reacts simultaneously with the charger's departure (shutdown announcement / pilot loss / equivalent), i.e. a charge-termination record, not a comms-fail record. Also at Truck 3's 8-5 charge-mode trip (EPO+2.2 s) and in the M4_T20 charge-context residue; absent from every drive/idle-mode trip (no charger present). M3 falsifies a DCDC association: the DCDC outlived the push there. |
| `FC B0 00` | observed, meaning unknown | Steady-state trip cascade only; expires from the stack within minutes. |
| `FB E0 00/02/03` | observed, meaning unknown | Deep stack during the deliberate interlock test's repeated pull/EPO cycles only. |
| `F7 00 00` + `F8 00 00` | hypothesis | Standing pair in the Apr-21–May-3 and Aug-2026 parts-truck eras, on Truck 3, and on the main truck (2026-08-01) — i.e. after periods involving 12V disconnects. Hypothesis: 12V-loss/reset records. (An earlier revision called them a "boot pair"; that was the staged restore, not a push.) |
| `DE E0 03` | observed, meaning unknown | **Truck 3 only** — standing in every truck3-log with BMS data, across his contactor swap, including healthy operation. |

**What pushes nothing:** normal drive key-off (no EPO at all), operator EVSE unplug
(EPO asserted but no records — count bytes tick only), and **charger-internal failures**
(the five Feb-2026 Bel `inverterFault` charge failures produced no EPO and no records —
the BMS recorder never sees Bel-side faults, so there is no "failed charge" code).

**Isolation faults are unnamed.** The forced 1 kΩ test (gfd→0) and both generator
isolation failures (gfd 15–43) pushed identical, generics-only sets (`F0 00 00` +
`AC 10 00`) — verified with untruncated page dumps ±25 s around all three EPOs.
Isolation remains identified by the 0x410 B1 lower-nibble path (`0xB0/0xF0/0xC0`) plus
`gfd`, not by a record. The record list encodes what the BMS *decided*, not everything
it measured.

---

## Parts-truck record-era timeline (main-orig pack, 2026)

| Era | Standing records | Context |
|-----|------------------|---------|
| ≤ Apr 3 → ~Apr 18 | `FB B6 E4` + `FC 16 F2` | **Pack reinstall / generator-disconnected era.** Apr 3 19:42: BMS wake/die loop every ~64 s (open interlock during reinstall), `FC 16 F2` re-logged each cycle. Apr 8 (`vtrux__partstruck_reconnect`): live boot-fault — BMS wakes with hvil open, EPO 0.4 s in, pushes `AC 10 00`+`F0 00 00`; F7/F8 standing by then (12V work during reconnect). Apr 18 (`no_gene_inv_fuse`): pair present with the gen inverter fuse pulled. |
| Apr 21 – May 3 midday | `F7 00 00`+`F8 00 00` | **Generator connected and running** (Apr-21 testdrive gen-iso failures; May-3-morning evapfuse gen runs). Includes the Apr-25 precharge failure. |
| May 3 ~12:30 → mid-Jul | `FB B6 E4` + `FC 16 F2` | Re-established between the evapfuse log (ends ~12:20, F7/F8) and crankover_bug (12:32, pair present) — **the gen-inverter 12V fuse was pulled again after the morning's iso-fault work** (owner-confirmed method), pushing a fresh `FC 16 F2` that then latched. The fuse went back in at some point (GENE broadcasts at full rate in every scanned session of this era, though the generator never generates — 0x482 never exceeds pack voltage), but the latched record persisted; the +15–40 s post-boot appearances throughout this era are staged NVM restores. |
| Aug 1 → | `F7 00 00`+`F8 00 00` | Pair gone and `FC 16 F2` never re-appears — **generator back in service** (Aug-2 drive charges SoC 38.5→100% with ±346 A). The Aug-2 precharge failures happen in this clean era. |

### June 2026 drive events (parts truck + main-orig)

- **2026-06-10 20:45:57 — mid-drive interlock flutter.** While in `PN_CLOSED_DRIVE`,
  hvil bounces open/closed **six times in 350 ms**; the contactor state machine flaps
  `PN_CLOSED_DRIVE↔ALL_OPEN_SHUTDOWN` with each bounce; no EPO; driving resumes; hvil
  drops for good 5 s later (no EPO then either). First captured mid-drive interlock
  flutter on this pack — the leading mechanism candidate for the historical
  warning-free driving shutdowns.
- **2026-06-17 19:39 drive:** six key-off/restart cycles; every restart shows the
  staged FB→FC restore; normal key-offs push nothing.
- **2026-06-18 00:21:26 — drive-mode EPO trip.** `B1 0xBF→0xCF` directly (no `0xFF`
  step), hvil stays **closed** through the trip, from `SHUTDOWN_REQUEST`, pushing
  **`AC 10 01`** + `F0 00 00` — the only non-zero AC parameter in the corpus. Cleared
  by a plain restart 52 s later. Matches no documented fault mode; unexplained.

## Per-event evidence

What each analyzed event pushed (newest first), from the artifact outputs:

| Event | Pack/truck | Records pushed |
|-------|-----------|----------------|
| Steady-state escalation ×5 (2025) | main-orig / main | at TYPE1: `FC 22 02`; at EPO+0.2–0.6 s: `F0 00 00`, `FC B0 00`, `AC 10 00`; then `FB C0 00` when the Bel shuts down (+3.0–3.2 s in M0/M1/M3; **+119.1 s in 0822** where the Bel stayed alive until the unplug). **Recoverable vs stuck is NOT distinguishable on 0x460**: the 0822 instance — which stayed stuck **until the next day and persisted over a 12V cycle** (owner account, 2026-08-27) — is byte-identical in codes and push timing (±0.1 s) to the four instances that cleared on replug. The stuckness is not reflected in any record; since a 12V cycle wipes the BMS latches, the re-tripping condition must have been physically present, recovering with time. By September the standing records were only the `FC 16 F2`/`FB B6 E4` service-era residue (fault stack already cleared). |
| Precharge abort ×4 (2025–2026) | main-orig / both | `AC 10 00`, `F0 E0 00`, `F0 00 00` |
| Deliberate isolation fault (1 kΩ) | parts-orig / main | `F0 00 00`, `AC 10 00` only |
| Generator-isolation EPO ×3 (2026-04-21) | main-orig / parts | `F0 00 00`, `AC 10 00` only |
| Deliberate interlock test (3 EPOs) | parts-orig / main | `AC 10 00`, `F0 00 00` per EPO; `FC 16 F2` appearance = staged restore at boot+39 s of a record standing since ≤Jan 26 (GENE broadcast continuously — not a test-induced push); `FB E0 00/02/03` on repeats |
| truck3-welded MAINN (2026-05-15) | Truck 3 | `AC 10 00`, `F0 00 00`, `F6 C0 01`, `F6 C3 02` |
| truck3-bad precharge contactor (2026-07-02) | Truck 3 | `AC 10 00`, `F0 00 00`, `F6 C0 01`, `F6 C5 03` |
| truck3-charge attempt, hvil opens (2026-08-05a) | Truck 3 | `F6 CF 00`, `F0 00 00`, `FB C0 00` — no AC record |
| truck3-export attempts (2026-08-05b) | Truck 3 | nothing — export request drops (0x592 bit), clean teardown, no EPO |
| truck3-BMS power loss (rounds 3/4) | Truck 3 | no BMS frames — absence is the signature |
| Main truck evening event (2025-08-21, debuglog_M6) | main-orig / main | `F6 CF 00` on top of `F0 00 00`, `FB C0 00`, `FC 22 02` — consistent with the M4_T20 aftermath's HVIL openings |
| Reinstall boot-fault (2026-04-08) | main-orig / parts | `AC 10 00`, `F0 00 00` (hvil open at wake) |
| 2026-06-18 00:21 drive trip | main-orig / parts | `AC 10 01`, `F0 00 00` |
| Operator EVSE unplug (2026-07-14) | parts | none (count ticks only) |
| Normal drive key-off ×6 (2026-06-17) | parts | none (no EPO) |
| After-swap Bel charger failures (2026-02) | parts-orig / main | none — BMS uninvolved |

---

## Diagnostic conclusions

1. **The steady-state fault and the precharge fault carry different BMS
   classifications** (`FC 22 02` vs `F0 E0 00`), and the Aug-2026 precharge failures
   occurred in the clean record era — distinct main-orig phenomena are now separable:
   the 2025 steady-state fault, the precharge abort, the deliberate-gen-disconnect
   condition (`FC 16 F2` eras), and the genuine main-loop events (2026-06-10 flutter,
   2026-06-18 `AC 10 01` trip).
2. **Neither main-orig fault is a contactor fault in the BMS's eyes** — no F6 records;
   Truck 3's genuine contactor/interlock hardware faults all carry F6 codes.
3. **`FC 22 02` has not recurred since 2025-08-22** anywhere.
4. **Post-mortem readout works**: records survive reboot until a plug-cycle/12V clear,
   so a capture taken after towing home — before any reset — recovers a driving
   shutdown's code. The logger need not be running at the moment of failure.
5. **Records are fault-path-only**: key-offs, unplugs, and charger-internal failures
   push nothing. An empty/unchanged list after an "event" is itself informative.
6. `0x617 B7 = 0xCA` is a fast VCM-side fault-active flag (all modes, ~0.3 s).

## Open questions

- Semantics of the 3-byte encoding (F6 = contactor/interlock sequencer family, F0 =
  shutdown/abort actions, AC = EPO-with-parameter, FB/FC = condition records — pattern,
  not proof) and of the `AC 10 01` parameter.
- What condition `FC 22 02` actually names.
- `FB B6 E4`'s module: test the DCDC-lost-comms hypothesis by finding (or making) a
  capture where only the DCDC goes silent >30 s with the BMS awake and HV up.
- Whether an `FC 16 F2`-class record exists for other CAN-monitored modules (a
  per-module lost-comms family would predict more FB/FC codes).
- `FB B6 E4`'s identity; `DE E0 03` on Truck 3; `FB C0 00`/`FC B0 00`/`FB E0 0x`.
- Which interlock-loop segment maps to `FC 16 F2` vs `F6 CF 00` vs the deliberate
  test's `FB E0 0x` — a pull-by-pull mapping pass on `vtruxinterlocktest.log` is the
  remaining homework.
- `0x617 B7 = 0xC9` meaning; page-0 counter bytes B3–B6 detail.
