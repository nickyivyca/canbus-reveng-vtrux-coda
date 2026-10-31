# Vtrux — How a charge session actually ends

**What stops a Vtrux charge is the energy-flow bit, not the charger mode.** The
VCU drops `chgcmd_enable` to 0 and then commands `STAND_BY`; the mode usually
stays at `CHARGER` throughout. `CHARGER_LOW_POWER` (mode 3) is **not** a
completion state — it is a hold, and at a genuine top of charge that hold is
where the pack balances. On the parts truck it ran for **7.7 hours**, until the
handle was pulled.

**The VCU does not decide when a session ends** (corrected 2026-09-16, raw
captures at 0.1 ms, section 4b). In every captured ending the charger left
state 12 first — for a handle pull or for an internal fault — or the BMS
asserted EPO first, and the VCU's flow drop and `STAND_BY` followed within
about a second. No hold has ever been seen to end on its own.
**Exception, 2026-09-25 (section 4c):** a charge that never got started -- the
VCU dropped the flow bit first, ~2.1 s into state 12, with the charger at 0 A.

Established 2026-09-12 across **49 charging sessions**, corrected 2026-09-16.
This is general Vtrux charging behaviour, not specific to any one project; the
charge-interposer work is one consumer of it.

| Related | |
|---|---|
| `charging-vs-exporting.md` | charger state codes (11/12/15 charge, 30/31/32 export) and startup/shutdown sequences |
| `charger-efficiency-and-grid-consumption.md` | what the AC draw in each state costs |
| `balancing-investigation.md` | the balancing mechanism itself |

---

## 1. The command

`0x18EFC000` (`VCU_ChargerCmd_18EFC000`) is page-multiplexed. Page `00` — the
master page — carries the only two fields that matter here:

| Byte | Signal | Meaning |
|---|---|---|
| B1 | `chgcmd_enable` | energy flow enable. **This is the one that stops the charger.** |
| B2 | `chgcmd_mode` | 0 EXPORT, 1 CHARGER, 2 STAND_BY, 3 CHARGER_LOW_POWER, 4 INVALID |

**The master page is edge-triggered, not cyclic.** Measured on the 80 % evap
capture: the six cyclic pages (`09`, `03 04`, `03 06`, `03 02`, `03 07`, `01`)
each appear at **3.325 /s**, uniform to four significant figures. The master
page appears at **0.035 /s** — 321 frames in the whole 2.56 h session, in **3
bursts**, with 7,335 s and 1,869 s of complete silence between them. The VCU
announces a mode change once and never repeats it.

That matters to anything sitting in the middle of this bus: a stop command that
is swallowed is gone for good.

---

## 2. What actually terminates a session

Across 49 charging sessions:

| Termination sequence | Sessions |
|---|---|
| `CHARGER/- -> CHARGER/0 -> STAND_BY` | 17 |
| `CHARGER/1 -> CHARGER/0 -> STAND_BY` | 5 |
| `CHARGER/0 -> STAND_BY` | 5 |
| `CHARGER/1 -> LOW_POWER/1 -> STAND_BY` | 3 |
| remainder (truncated captures, export sessions) | 19 |

- **39 of 49** terminations contain a `flow -> 0` step
- **38 of 49** end on `STAND_BY`
- **only 16 of 49** involve `LOW_POWER` at all
- the single most common ending — **27 of 49** — is flow dropping to 0 with the
  mode left at `CHARGER`, then `STAND_BY`

---

## 3. Mode 3 is a hold, not a stop

Commanding `CHARGER_LOW_POWER` does not stop the charger. Measured at the 80 %
evap cutoff:

| | DC | AC | AC volts | `BELINV_state` |
|---|---|---|---|---|
| charging | -15.19 A | 27.20 A | 234.6 V | 12 |
| after mode 3 | **-2.40 A** | **7.94 A** | 244.5 V | **12** |
| 27 min later | -2.42 A | 7.89 A | 244.8 V | 12 |

Current falls to a floor in about two minutes and then holds, dead steady, with
the charger still in state 12. (Raw log, 2026-09-19,
an internal-only bench timeline: the mode command alone
takes the charger from 15 A to ~6 A, via a reset 12 -> 15 -> 12; the fall to
~2.4 A is the VCU's page-01 setpoint, ramped 19.8 -> 0 A in 3 A steps starting
155 s after the mode command and then alternated 0 / 2.9 A every ~10 s.) Roughly **1.9 kVA apparent draw for ~940 W of DC**
— light-load power factor makes the AC draw look disproportionate to the DC
delivered. (AC figures are RMS, so V*I is apparent power; see
`charger-efficiency-and-grid-consumption.md`.)

> **Corrected 2026-10-10: the "~940 W of DC" is withdrawn.**
>
> - The garage CT measures this hold at **~570 W real**, so 1.9 kVA is
>   apparent power (W/VA 0.30).
> - The -2.40 A above is the charger's own reading, which is ~1.5 A high at
>   this output. The true DC is ~0.8-0.9 A, almost all of it consumed by HV
>   aux and the DC-DC.
> - The table's state, mode and timing observations stand; only the DC
>   current *magnitude* is wrong.
>
> See `charger-efficiency-and-grid-consumption.md`, "The charger's DC current
> reading at low output".

A real end of charge looks nothing like this: DC **0.00 A**, AC **0.00 A**, out
of state 12, pack voltage reading collapsing as the contactors open.

---

## 4. Two ways a session ends, and what decides which

### Not full: stop immediately

35 sessions ended with no hold — mean SoC **79.1 %**, mean `bcm_chg_max`
**185 A**. The pack was mid-charge, there was nothing to balance, and the VCU
went straight to `flow 0` then `STAND_BY`.

### Full: hold while the pack balances

7 sessions passed through a `LOW_POWER` hold. **Hold duration tracks the cell
spread at the moment mode 3 is commanded:**

| hold | SoC | `chg_max` | spread at mode 3 | balancing | spread at `STAND_BY` | session |
|---|---|---|---|---|---|---|
| **27,634 s** | 100.0 | 0.00 A | **116.8 mV** | 1 | **2.1 mV** | `vtrux_partstruck_charge` |
| **4,816 s** | 100.0 | 0.00 A | **94.5 mV** | 1 | **2.7 mV** | `vtrux_20260503_192242` |
| 2,118 s | 48.5 | 300 A | 1.8 mV | 0 | 3.0 mV | `debuglog_M3` |
| 1,872 s | 79.7 | 300 A | 7.0 mV | 0 | 2.9 mV | `...80pctcv` (evap) |
| 117 s | 100.0 | 0.00 A | 27.8 mV | 1 | 27.8 mV | `full-charge-then-fail` |
| **0 s** | 100.0 | 0.00 A | **2.3 mV** | 0 | 2.3 mV | `charge_M0` |
| **0 s** | 100.0 | 0.00 A | **2.3 mV** | 0 | 2.3 mV | `vtrux_charge_M1` |

The ordering is monotonic in spread: 116.8 mV buys 7.7 hours, 94.5 mV buys 1.3
hours, and a pack already at **2.3 mV is released with no hold at all**. Every
hold that ran to completion ended at a converged **2.1–3.0 mV**.
`full-charge-then-fail` is the exception that fits — it broke off after 117 s
still at 27.8 mV, which is what its name says happened.

**Corrected 2026-09-16: the hold's length is the operator's, not the VCU's.**
Every hold in this table that could be checked in its raw capture ended with
the charger reporting `shutdownSource` 11 and both connected-flags dropping in
the same frame — a handle pull — one second *before* the VCU's flow drop
(section 4b). The spread had converged by then because the operator waited
for it; nothing in the VCU released the hold. Split by phase on the parts
truck (`balance_convergence_rate.py`): **1.78 h** from the mode-3 command to
a 3 mV spread, then **5.89 h** of converged hold before the pull. The three
measured tails are 1,395 s, 1,847 s and 21,221 s.

The two short-SoC rows are a different animal: `chg_max` still at 300 A means
the BMS was still permitting full current, so those holds are interrupted
charges (the evap ceiling, and a mid-charge stop), not balance holds. The evap
one also ended at a handle pull, 1,872 s after the mode-3 command.

**The spread opens up before it closes.** The parts-truck charge in 2 h buckets:

| phase | spread | balancing | DC |
|---|---|---|---|
| bulk CC | 3.8 mV | 0.00 | -14.3 A |
| approaching full | 39.1 mV | 0.59 | -11.8 A |
| peak divergence | **68.2 mV** | 0.78 | -3.1 A |
| converged | **2.2 mV** | 0.07 | -2.9 A |
| holding | 2.3 mV | 0.03 | -2.9 A |

Cells diverge as they approach full, balancing engages, and the spread then
collapses. This is the part of the charge that actually does the balancing work.

**Resolved 2026-09-16: there is no release trigger.** The earlier reading —
`STAND_BY` arriving hours after convergence, so "not a simple balanced,
therefore stop" — was right about the symptom and wrong about the cause: the
VCU never released the hold at all (section 4b). `bcm_balancing` staying
non-zero (0.03–0.07) through the tail is simply the pack still trimming while
the truck waited for a person.

`bcm_chg_done` is not the BMS's opinion either. Across the corpus it first
latches at the moment the VCU commands the hold: at vmax 3.596–3.600 V with
`chg_max` 0 on the full charges, but also at **80.5 % SoC with the BMS still
granting 300 A** on the evap capture, and at 29–48 % SoC in several 2026-07-14
sessions. It follows the command, so it cannot be used to judge fullness.

---

## 4b. Who actually ends a session — millisecond ordering from the raw logs

InfluxDB's 1 s heartbeat puts every ending inside a ~2 s window and cannot
order it. The raw BUSMASTER captures can (`termination_ordering_raw.py`,
0.1 ms ticks, all through cantools). Relative to the VCU's flow drop, in ms:

| session | charger leaves 12 | `shutdownSource` | VCU flow 0 | `STAND_BY` | BMS EPO | contactors leave 12 |
|---|---|---|---|---|---|---|
| `vtrux_partstruck_charge` (7.7 h hold) | −1118 | 1 → **11** | 0 | +261 | +296 | +337 |
| `charge_M0` (hold) | −1024 | 1 → **11** | 0 | +253 | +287 | +280 |
| `...80pctcv` (evap hold, 1,872 s) | −1129 | 1 → **11** | 0 | +248 | +262 | +303 |
| `debuglog_M6` (64 %, mid-charge) | −1035 | 0 → **11** | 0 | +648 | +254 | +294 |
| `vtruxchargeafterucsc2` (direct stop) | −584 | 0 → **3** | 0 | +652 | +1129 | +1168 |
| `...scottsvalley2-16asetpoint` (direct stop) | −228 | 1 → **3** | 0 | +700 | +1183 | +1222 |
| `full-charge-then-fail` (BMS fault) | +176 | 1 → 7 | 0 | — | **−103** | **−9** |

Three initiators, and the VCU is none of them:

- **Handle pull (`shutdownSource` 11, `evseConnected` and `vehicleConnected`
  dropping in the same frame).** Every hold ending, plus the mid-charge M6
  stop. The VCU drops flow ~1.0–1.1 s later, `STAND_BY` +250 ms, EPO and
  contactors within a further ~100 ms. On the parts truck and `charge_M0` the
  BMS then **resets** ~1.5 s after the pull — ready, chg_done and EPO all
  drop, `chg_max` reads the all-ones fill (1023.5), the 0x440 contactor state
  goes to 0, then everything ramps back over ~2 s. The 8.19 V cell readings at
  session boundaries are the same fill value.
- **Charger-internal fault (`shutdownSource` 3, a retry to 12, then 14).**
  Every "direct stop" checked — the intermittent charger failure documented in
  `specific-trucks/after-battery-swap-charge-fail-analysis.md`. The VCU drops
  flow 0.2–0.6 s after the first 12 → 15, `STAND_BY` +650 ms, EPO +1.1 s.
- **BMS trip.** EPO and contactors first, the VCU's flow drop ~100 ms later,
  the charger last (`shutdownSource` 7).

So the 27-of-49 "direct stop" pattern in section 2 is not a VCU choice; it is
what the VCU does after the charger has already stopped. (All seven rows are
endings of a running charge. A failed *start* in which the VCU does move first
is in section 4c.) Whether it reacts to
the charger's state, to `chargingInProgress` clearing, or to the pilot is not
separable from these captures; all three move together.

---

## 4c. A start the VCU abandoned -- buck-boost OVERLOAD (2026-09-25)

A fourth initiator, seen once: **the VCU**, on a charge that never delivered
current. Work ChargePoint, `vtrux_20260925_155857` (Android logger,
`CANLogs/VtruxLogs/`, T0-T12). The first station failed ~20 s after plug-in;
the truck was driven to a second station, which charged normally from 25 %.

Times are T0's `t` (first frame = 0 s ~= 15:59:04 by the chunk header):

| t (s) | event |
|---|---|
| 31.68 | `EVSESwitchState` 0 -> 1 (plug-in); BMS `on_plug`, HVIL closed, `ready` by 32.24 |
| 32.95-48.10 | **logger gap** (USB re-enumeration, ch 10 -> 14): precharge, contactor close, the page-01 setpoint and the flow-on are not in the capture |
| 48.34 | first frames after the gap: `chgcmd_enable` ON, mode CHARGER; contactors MAIN_P_CLOSED_CHARGE |
| 48.41 | Bel AC input 207 V (steady to the end) |
| 48.61 | Bel state 11 -> 12 |
| 48.71 | **`BELINV_buckBoostState` 0 -> 10**; `inverterState` stays 1 |
| 48.6-50.7 | Bel DC current and AC input current 0.00 A throughout |
| 50.738 | **VCU `chgcmd_enable` ON -> OFF** (first mover) |
| 50.743 | VCM warn lamp (0x646) on |
| 50.79-50.94 | VCU page-03 burst: 03.00, 03.05, 03.06, 03.07 |
| 50.987 | VCU mode -> STAND_BY |
| 51.009 | Bel 12 -> 8 (STANDBY), `shutdownSource` 0 |
| 51.038 | VCU page 03.01 (end of session) |
| 51.257 | BMS HVIL monitor open |
| 51.409 | Bel 8 -> 15, `shutdownSource` 14 |
| 51.505 / 51.545 | BMS EPO + alarm TYPE3 / contactors ALL_OPEN_SHUTDOWN |
| 51.88, 53.43 | BMS fault records pushed: `F6 CF 00`, `F0 00 00`, `FB C0 00` (catalog: `battery-fault-codes.md`) |

**The working start at the second station** (T1, t relative to flow-on at
1.986 s): page 03.05, then page 01 (`01 88 21 06 ..`), then flow-on; the
EVSE's AC came up at +0.5 s and the charger dropped 12 -> 15 -> 12 once as it
did; `buckBoostState` then ran 1 -> 13 -> 14 -> 4 and `inverterState`
1 -> 33 -> 26; AC input current at +2.5 s, `chargingInProgress` at +3.0 s; the
startup-transient Low Power command (spec section 7) at +3.1 s.

Enum labels from the EPRI app decompile (`epri-decompile.md`, not in the Bel
DBC): buck-boost 10 = **OVERLOAD**, 1 = IDDLE, 13 = DCDC_SOFTSTART,
14 = BB_SOFTSTART, 4 = RUNNING; inverter 1 = IDDLE, 33 = PFC_ENABLE_N,
26 = PFC_RUNNING; Bel state 8 = STANDBY.

**`buckBoostState` 10 has never appeared before:** zero points in any of the
69 InfluxDB sessions carrying `0x18FFD4C0` (queried 2026-09-25, before this
session was uploaded).

**Hypothesis (unconfirmed):** the charger's buck-boost stage reported OVERLOAD
on entering state 12 and never soft-started, so no current flowed, and the
VCU abandoned the start >= 2.4 s after its flow-on; the HVIL-open, EPO and BMS
fault records are the ordinary teardown that follows a VCU stop (section 4b,
spec section 7), not the cause.

**Not known:**

- **Why the buck-boost reported OVERLOAD.** CAN shows only that the stage did
  not soft-start. It cannot separate the station from the charger; the charge
  worked at a second station minutes later, which is one retry, not a test.
- **What the VCU reacted to** -- a no-current timeout, the charger's internal
  state, or something else. The flow-on time is inside the logger gap, so the
  delay from flow-on to the VCU's stop is unknown (>= 2.40 s).
- **What the VCU sent inside the gap.** An earlier reading of this capture as
  "the VCU skipped the setpoint and precharge" was a gap artifact and is
  withdrawn.

Artifacts: `artifacts/charge_20260925/` (ordering tables for both starts,
V/I and raw command frames, channel spans, frame gaps).

---

## 5. Data quality: DC current extremes

`BELINV_hvBatteryCurrent` carries occasional single-sample corruptions. Audited
over the whole corpus:

**10 out-of-range samples in 1,834,895 (0.0005 %)**, spread across 8 sessions at
1–2 each, clustering on recurring impossible values (`385.8 A` four times,
`-1572.4 A` twice, `-1367.6 A` once).

These are isolated bad frames, not a systematic decode error. Means, medians and
any windowed statistic are unaffected. **Anything quoting MIN/MAX must reject
outside +/-100 A** — otherwise a single frame becomes the headline, which is how
the parts-truck session first appeared to peak at -1367 A.

---

## 6. Method

Queried from InfluxDB against the current DBCs.

`0x18EFC000` was **missing from InfluxDB entirely** until 2026-09-12. It was
added to `vtrux-powertrain-experimental.dbc` after the sessions were uploaded,
and `influx_sync`'s drift check only ever compared messages a file had *already*
recorded — so a newly defined message was invisible to it and `--plan` reported
nothing to do. See the interposer's internal-only working log for the fix
(`--backfill-id`) and for the separate discovery gap that had kept
`big-logs/`, `actual-failed-charges/` and `after-battery-swap-charges/` outside
the corpus, which is why the parts-truck full charge was missing from the first
pass of this analysis.

Scripts, all internal-only:

| Script | Produces |
|---|---|
| `vcu_master_page_cadence.py` | page rates and master-page burst structure from a raw capture |
| `charge_termination_survey.py` | per-session mode/flow termination sequences, corpus-wide |
| `charge_termination_discriminators.py` | held vs direct contrast, balance convergence, DC audit |
| `lowpower_mode_behaviour.py` | AC/DC behaviour in mode 3 vs a normal end |
| `standby_gap.py` (+ `.txt`) | flow → 0 to `STAND_BY` gap per session: median 1.0 s direct, 0 s out of a hold |
| `balance_convergence_rate.py` (+ `.txt`) | the hold split into converging and tail phases, with convergence rates in mV/h |
| `standby_contactor_sequence.py` (+ `.txt`) | InfluxDB ordering of charger state, pilot, EPO and 0x440 contactors around every `STAND_BY` (1 s resolution; superseded by the next script for ordering) |
| `termination_ordering_raw.py` (+ `.txt`) | the section-4b table: millisecond ordering from the raw captures, with `shutdownSource` and the page-01 setpoint |
| `knee_charge_to_voltage.py` (+ `.txt`) | charge into the weakest cell during each hold against its voltage — the pack model's knee calibration |
