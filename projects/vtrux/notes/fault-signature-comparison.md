# Vtrux HV/BMS Fault Signature Comparison

Cross-cutting reference for telling Vtrux HV fault modes apart from CAN data alone.
Every row was measured with the same harness against the same signals, so the
columns are directly comparable.

**Artifacts:** `artifacts/fault_signature_compare.py`, `artifacts/contactor_sequence_compare.py`,
`artifacts/type1_precursor_scan.py`, `artifacts/preswap_failure_signature.py`,
`artifacts/type1_census_merged.py`, `artifacts/type1_magnitude_compare.py`,
`artifacts/m2_outlier_bytewise.py`, `artifacts/m2_outlier_3xx_sweep.py`,
`artifacts/temp_mirror_test.py` (+ matching `.txt` outputs).
`artifacts/recovered_fault_scan.py` is superseded for counts (no chunk merging) but its
contactor-state census is unique; `artifacts/gmlan_on_pt_scan.py` should not be re-run
(premise disproven — see its header).

Related: `specific-trucks/truck3-truck.md`, `specific-trucks/precharge-fail-investigation.md`,
`isolation-fault-analysis.md`, `interlock-bitfields-analysis.md`,
`specific-trucks/full-charge-then-fail-summary.md`.

---

## Read this first — two signals that are easy to misread

### 1. `vbus_pos` / `vbus_neg` (0x440) are node voltages, not the bus

The DC link is the **difference**. Both rails float up together during CLOSE_MAINR
while the actual bus sits at 0 V. Reading `vbus_pos` alone will tell you the bus is
at ~385 V when it is at ~0 V. Verified against two independent references
(AC compressor 0x870A047 B2, and 0x482) — see the table in
`specific-trucks/precharge-fail-investigation.md`.

**Contactor order is: precharge resistor (R) -> negative (N) -> positive (P), then open R.**
With N still open during CLOSE_MAINR, no current can flow and the bus cannot charge.

### 2. The terminal signature is identical for every fault mode

TYPE3 + EPO + `ALL_OPEN_SHUTDOWN` + `iso_r -> 0` + `B1 -> 0xCF` appears in **all**
fault modes below, including the two deliberately induced ones. It is the BMS's
generic shutdown response. **It carries no diagnostic information** — it tells you the
BMS tripped, never why. All discrimination comes from what happens *before* it.

### 3. TYPE1 — not a warning, but a useful classifier

**At startup**, TYPE1 is the normal transient alarm state (wake -> HV up -> TYPE2). It
has no causal or predictive effect there, and its duration is just the length of the
startup window. Do not read severity into it.

**In steady state it means something different, and it is diagnostic.** A `NONE ->
TYPE1` transition while already charging is the main-orig steady-state fault beginning.
Corpus census over 274 merged sessions found **5 such events, and all 5 escalated to
TYPE3** — none ever cleared. It is a committed countdown, not a warning that resolves.

**Use TYPE1 to tell an internal fault from an external disconnect:**

| | TYPE1 present? | HVIL timing | Elapsed |
|---|---|---|---|
| **Internal fault** | **yes**, ~10 s before the trip | drops ~1 s **after** | ~10 s |
| **Operator unplug** | **no** — straight to TYPE3 | drops **before**, and causes it | ~0.3 s |

Both appear in `truklog_M2`: an unplug at t=4297 (hvil→0 first, no TYPE1, 0.30 s total)
and a genuine fault at t=4112 (TYPE1, everything still connected, hvil→0 at T3+0.96).
This is the cleanest way to filter the unplug confound in section 4.

### 3a. The steady-state escalation delay is a fixed ~10.21 s timer

Four of five instances fall within 94 ms (10.165–10.259 s), and the delay is
**independent of everything the BMS reports** — two instances differing in SoC
(49.9 % vs 100 %), current (7.75 A vs 0.60 A), cell vmax (3325 vs 3600 mV), spread
(3 vs 27 mV) and charge limit (300 vs 0 A) trip **1 ms apart**.

One outlier (`truklog_M2`, 8.810 s) is unexplained and is not data loss. Full detail and
the ruled-out variable list: `specific-trucks/before-battery-swap-failed-charge-analysis.md`.

**The trigger does not appear to be broadcast.** An exhaustive byte-level sweep of
0x300–0x5FF (every ID, every byte, all five escalations) finds nothing that distinguishes
the trip, and nothing changes at the TYPE1 instant. Scope note: this covers what the
main-orig pack **does** broadcast. That pack does not publish the conditioning-module
group (`0x370`–`0x375`, `0x506`, `0x507`, `0x50F` — see `battery-thermals.md`), so that
tier is **untested rather than cleared**. Note also that on packs which do publish it,
`0x507` is only a rebroadcast of `0x430`, so part of the missing tier is redundant.

### 4. CONFOUND: a normal EVSE unplug produces the full fault signature

**`EPO=1` + `TYPE3` + `ALL_OPEN_SHUTDOWN` is also what a routine unplug looks like.**

Confirmed in `../../CANLogs/VtruxLogs/vtrux_20260714_161319_T74.log` — the owner
unplugged mid-charge at 93.9% SoC and the BMS latched the identical terminal state:

```
21:55:53.0  EVSE_SW  1 -> 0      (operator unplugs)
21:55:53.1  on_plug  1 -> 0
21:55:53.2  epo      0 -> 1
21:55:53.2  contactor -> ALL_OPEN_SHUTDOWN     + alarm goes TYPE3
```

So the terminal signature does not distinguish a fault from an ordinary charge
termination. **Always check whether `on_plug` / `EVSE_SW` dropped in the ~200 ms
BEFORE the EPO.** If they did, it is an unplug, not a fault. Any corpus scan keying on
"EPO + TYPE3 + ALL_OPEN_SHUTDOWN" without this check will be full of false positives.

### 5. CONFOUND: Android-logger captures have total blackout windows

Captures under `../../CANLogs/VtruxLogs/` are **not** rate-limited or decimated — within
any covered window they match the primary captures exactly. Measured in
`vtrux_20260714_161319_T74.log`: 0x410 has a median gap of 49.9 ms and a p99 of 55.0 ms,
i.e. a clean 20 Hz, and only 2 of its gaps in the entire file exceed 2.5x the median.

The failure mode is instead **multi-second windows where every bus goes silent
simultaneously** — the USB dongles detach and re-enumerate. The same file has blackouts
of 17.9 s, 83.4 s and 15.2 s (200 s of a 300 s segment), and shows 8 bus indices for the
physical dongles, two of which live 1.4 s before dying. Each re-attach costs a hard 4 s
minimum before frames resume (`CanPipelineManager.addDevice` debounce).

These blackouts are most likely explained by marginal USB cable seating rather than any
specific software bug. They occur in short bursts confined to a minority of segments —
most sampled dates show zero — and the capture returns to full fidelity for hours
between episodes. The longest gaps also far exceed any software delay, so the dongle is
simply not enumerated for the duration; the 4 s debounce amplifies each reattach but
does not cause the outage.

Consequences:
- **Check for blackout gaps before measuring any interval.** Timing *within* a covered
  window is reliable; timing across a gap is meaningless. The apparent 15.4 s
  `WAIT_PRECHARGE` -> `PN_CLOSED_DRIVE` in this file spans the 15.2 s blackout at
  t=252.7; the real figure is ~350 ms and the intermediate `CLOSE_MAINP` / `OPEN_MAINR`
  states fell inside the hole.
- Absent states do not mean skipped states.
- Bus index numbers are especially unreliable here — one physical bus appears under
  several indices within a single file.
- Primary captures (`projects/vtrux/logs/`, Kvaser/Innomaker) do not show these
  blackouts.

### 6. Trigger-window caveat when classifying recoveries

Operator actions can appear to precede the effect they cause by more than 15 s once a
blackout (section 5) falls between them. A key-on at t=251.8 produced a contactor
recovery at t=267.9 (16.1 s later) purely because the 15.2 s blackout at t=252.7 sat
between the two.

Widening the trigger window is the wrong fix — it does not help when the gap is 83 s, and
it invites false attributions elsewhere. Instead: **check the gap structure first, and do
not attribute cause across a blackout.** If the action and its apparent effect are
separated by a bus-wide silence, the interval is unmeasured, not measured-and-long.

---

## Master discriminator table

| Fault | Context | Aborts from | Interlock bit | B1 path | Lead time |
|---|---|---|---|---|---|
| **Welded MAINN contactor** | startup | `CLOSE_MAINR` @502 ms | 1 (closed) | `0x7F->0xCF` | — |
| **Bad precharge contactor** | startup | `CLOSE_MAINR` @501 ms | 1 (closed) | `0x7F->0xCF` | — |
| **BMS master power loss** | never wakes | **module absent** | n/a | n/a | n/a |
| **Precharge fail (main-orig)** | startup | `CLOSE_MAINN` @53-152 ms | 1 (closed) | `0x3F->0xCF` | none |
| **Isolation fault** | running | `MAIN_PN_CLOSED_DRIVE` | 1 (**stays closed**) | `0xBF->0xB0->0xF0->0xC0` | 146 ms |
| **Interlock fault** | running | `MAIN_PN_CLOSED_DRIVE` | **0 — clears first** | `0xBF->0xFF->0xCF` | 200 ms |
| **main-orig steady-state charge fault** (5 instances, incl. 2025-08-22) | running (charge) | `MAIN_P_CLOSED_CHARGE` | 1 (**stays closed**) | `0x7F->0xFF->0xCF` | **8.8–10.3 s** (TYPE1 lead) |
| **Operator EVSE unplug** (not a fault — confound) | running (charge) | `MAIN_P_CLOSED_CHARGE` | **0 — drops first, causes trip** | `->0xCF` | none (**no TYPE1**) |

### Fastest way to classify a new fault

1. **Is the BMS master block (0x400/0x410/0x411/0x412/0x420/0x430/0x440/0x460) present at all?**
   If absent while pack section boards (0x370-0x375, 0x506, 0x50F) still broadcast ->
   **BMS master power/wake failure**. There is no fault event to find; the absence is
   the signature.
2. **Does `interlock` (0x410 B0 bit3) clear before EPO?** -> **interlock fault**.
   Uniquely, this bit leads the trip by ~200 ms.
3. **Does B1's lower nibble clear during shutdown** (`0xB0`/`0xF0`/`0xC0`)? ->
   **isolation fault**. Every other mode keeps the lower nibble at `F` and goes
   straight to `0xCF`. This is the isolation fault's unique tell.
4. **Otherwise, which contactor state does it abort from?** That separates the
   remaining startup faults — see the sequence table below.

---

## Contactor sequence comparison

Full state-machine walks with dwell times. `DIFF` = bus DC link = vbus_pos - vbus_neg.

| | CLOSE_MAINR | CLOSE_MAINN | WAIT_PRECHARGE | Result |
|---|---|---|---|---|
| Healthy — main drive | 146 ms, DIFF 19 V | 102 ms, DIFF 23 V | 354 ms, DIFF 370 V | SUCCESS |
| Healthy — main export | 144 ms, DIFF ~22 V | 153 ms, DIFF ~22 V | 347 ms, DIFF 375 V | SUCCESS |
| Healthy — truck3-export | 102 ms, DIFF ~0 V | 144 ms, DIFF ~0 V | 356 ms, DIFF 367 V | SUCCESS |
| **Welded MAINN** | **502 ms, DIFF 0 -> 378 V** | *never entered* | — | FAIL |
| **Bad precharge contactor** | **501 ms, DIFF 0 -> 0 V** | *never entered* | — | FAIL |
| **BMS master absent** | *no sequence exists* | — | — | FAIL |
| **main-orig 2025-08-21** | 148 ms, DIFF 0.8 V | **152 ms**, DIFF -0.2 V | *aborts* | FAIL |
| **main-orig 2026-04-25** | 147 ms, DIFF 0.7 V | **53 ms**, DIFF 0 V | *aborts* | FAIL |
| **main-orig 2026-05-03** | 146 ms, DIFF 0 V | **56 ms**, DIFF -0.2 V | *aborts* | FAIL |

**Two structurally different startup faults — do not conflate them:**

- **Contactor faults (Truck 3's):** never reach CLOSE_MAINN. Stall in CLOSE_MAINR for a
  fixed **~501 ms** and abort. No other known fault aborts at this step.
- **main-orig precharge fault:** executes CLOSE_MAINR normally (146-148 ms, matching
  healthy), closes the negative correctly, then aborts **mid-precharge** at 53-152 ms.

### Weld vs open, within CLOSE_MAINR

`vbus_neg` alone separates them:

| | `vbus_neg` during CLOSE_MAINR | Bus DIFF | Meaning |
|---|---|---|---|
| Healthy | floats up with vbus_pos (4.5 -> 364 V) | stays ~19 V | negative open (correct) |
| **Welded MAINN** | **pinned at 0.0** | **0 -> 378 V** | negative already closed = weld |
| **Bad precharge** | tracks vbus_pos (13.5 -> 12.0) | 0 -> 0 | negative open, bus never charges |

A `vbus_neg` pinned at 0 during CLOSE_MAINR means the negative contactor is connected
before it was commanded. This reproduces the welded-MAINN diagnosis on Truck 3's truck
using a single BMS signal, independently of the AC-compressor bus proxy originally used.

---

## What does NOT discriminate

Recorded so these are not re-tested:

| Variable | Why it fails as a discriminator |
|---|---|
| **12V rail sag** | Truck 3's truck completed a **successful** precharge sagging to **9.0 V**; main-orig fails at **11.0 V**. Parts-orig succeeds 79/79 with sags to 10.3 V. |
| **Precharge rate** | In one session, the failing attempt precharged to 261.8 V at 55 ms while a **successful** attempt reached only 150.0 V. |
| **Terminal fault signature** | Identical across all modes (see above). |
| **`iso_r` dropping to 0** | Happens at every trip — any contactor opening drops HV and reads 0. Only causal when it drops from a *valid* reading simultaneously with the trip (the isolation-fault case). |
| **TYPE1 alarm** | Normal startup state; no demonstrated causal or predictive effect. |
| **Pack temperature (within a session)** | All four attempts in the 05-03 session were at 14.5 C with mixed outcomes. Does not rule out a longer-timescale seasonal effect. |

---

## The 2025-08-22 mystery — where it does and does not fit

Confirmed facts (`artifacts/fault_sig_mystery2025.txt`):

- Trips from `MAIN_P_CLOSED_CHARGE` after ~2 hours of successful charging.
- **`cell_overvolt` flag never set** — not once in the entire log. This upgrades the
  earlier "cell overvoltage ruled out" from inference to direct confirmation.
  (Note: the flag is 0x420 **B6 bit7**, per `tools/diagnose_vtrux.py`. An earlier
  analysis pass used the wrong bit and produced a spurious result.)
- `cell_vmax` peaked at exactly **3600 mV and never exceeded it**.
- BMS had commanded **`chg_max = 0.0 A` for 23.5 minutes** before the trip.
- `iso_r` healthy at 200 until the trip; interlock closed throughout.
- Nothing observable changes in the 10.2 s between TYPE1 and EPO.

**Commonality with the contactor faults: only the non-diagnostic terminal signature.**
Everything discriminating differs — the contactor sequence completed cleanly two hours
earlier, and this is a running trip rather than a startup abort.

**Commonality with the main-orig precharge fault: circumstantial but real.** Same pack,
and the owner reports both forms belong to one progressive intermittent fault (see
`specific-trucks/precharge-fail-investigation.md` backstory). The shared feature is
that **no broadcast signal explains either trip** — which is what an intermittent
physical connection looks like from the CAN bus. This is a hypothesis, not a
confirmed link.

**Open item:** the 10.2 s TYPE1-to-EPO gap remains unexplained. The owner reports the
driving shutdowns were instantaneous with no warning, so if the driving events and this
charge trip share a mechanism, the 10.2 s delay is probably specific to charge mode
rather than a property of the fault. Not confirmed either way.
