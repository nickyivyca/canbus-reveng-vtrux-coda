# Vtrux Cell Balancing Investigation

Analysis of `bcm_balancing_cnt` and related signals during completed charge sessions.

---

## Pack Configuration

- **116 cells total** (4×26s3p modules + 1×12s3p module)
- `bcm_balancing_cnt` max observed: **116** — the full pack above the balancing threshold simultaneously
- Balancing first appears when the leading (highest) cells reach ~3400 mV, which corresponds to the LFP CC→CV knee at high SOC.

---

## Signals Available

From `epri-pt-bus.dbc`:

| Signal | Source | Description |
|--------|--------|-------------|
| `bcm_balancing` | 0x440 B0 bit7 | Boolean -- balancing active |
| `bcm_balancing_cnt` | 0x440 B7 | Count of cells currently being balanced (0-253, invalid if >=0xFE) |
| `bcm_cell_vmax` | 0x430 | Highest cell voltage, 13-bit Motorola, 1 mV/count |
| `bcm_cell_vmin` | 0x430 | Lowest cell voltage, 13-bit Motorola, 1 mV/count |

**No per-cell identification is available.** The BMS broadcasts only aggregate min/max voltages and a count of how many cells are balancing. There is no signal indicating *which* cells are above threshold, nor a cell index for vmax/vmin.

---

## Findings from Completed Charge Sessions

Analysis script: `artifacts/balancing_cnt_completed_charges.py`

### Onset

Balancing consistently begins in the **93-96% SOC range** across all sessions with active balancing. It does not occur earlier in the charge.

### Session Summary

| Session | Duration | SOC range | First non-zero cnt | SOC at onset | Time after 100% at onset | Peak mean cnt | Max cnt |
|---------|----------|-----------|-------------------|--------------|--------------------------|---------------|---------|
| full_charge_then_fail | 122 min | 53->100% | t+4956s (82.6 min) | ~95.5% | -17 min (before 100%) | ~91 (t+100-110 min) | 116 |
| after_swap_M0_a (charge_M0) | 298 min | 45->100% | t+8357s (139.3 min) | ~100.0% | ~+40 min after 100% | ~59 (t+150-160 min) | 116 |
| after_swap_M0_b (another_M0) | 548 min | 25.5->100% | t+7710s (128.5 min) | ~93.5% | -10 min (before 100%) | ~63 (t+150-180 min) | 116 |
| after_swap_charge_9pm | 35 min | 86.5->100% | never | n/a | n/a | 0 | 0 |

### Onset timing relative to 100% SOC

Balancing onset varies across sessions:
- **full_charge_then_fail** and **M0_b**: balancing begins *before* reaching 100% SOC (~93-96%)
- **M0_a**: balancing begins ~40 minutes *after* SOC has already been at 100%
- **charge_9pm**: no balancing at all (cells already balanced -- M0_b immediately preceded it)

A possible explanation: onset timing reflects cell imbalance state entering the charge. When cells are more out of balance, the BMS starts balancing earlier (still in CV taper phase). When cells are already close to balanced, balancing is delayed or skipped entirely.

### Decay after reaching 100% SOC

In both M0_a and M0_b, after peaking the mean balancing count decays steadily while SOC stays at 100%:
- **M0_a**: peak ~59 at t+150-160 min, then decays to near-zero by t+230 min (~80 min to converge)
- **M0_b**: peak ~63 at t+150-180 min, then long tail decaying over ~6+ hours at 100% SOC
- **full_charge_then_fail**: peak ~91 at t+100-110 min, then drops sharply -- session ended (charge failure) shortly after

The longer tail in M0_b vs M0_a likely reflects a more imbalanced pack at the start of that session (SOC started lower at 25.5% vs 45%).

### charge_9pm: zero balancing at 100%

This 35-minute session ran from 86.5% to 100% with `bcm_balancing_cnt` = 0 throughout. M0_b immediately preceded it (9+ hour session with a long balancing tail). Most likely explanation: cells were already balanced by the end of M0_b, so no balancing was needed.

### Count distribution spikes — module structure visible

Analysis script: `artifacts/balancing_count_spikes.py`

A spike-finder (value > 3x local median within +-8 neighbors) run across all four active sessions reveals statistically significant peaks at specific count values. These map onto the pack module architecture:

**Module-count spikes** (cells within a module cross the threshold together):

| cnt | Interpretation | Sessions |
|-----|---------------|---------|
| 12 | 12s small module balancing | all 4 sessions (9-28x) |
| 52 | 2 large 26s modules (2x26) | M0_a, Jan25 |
| 104 | all 4 large 26s modules (4x26) | M0_a, M0_b, Jan25 |
| 116 | full pack (all 116 cells) | M0_a, M0_b, Jan25 |

**Module-count ±1 spikes** (one outlier cell above or below its module group):

| cnt | Interpretation | Sessions |
|-----|---------------|---------|
| 1 | one high cell, all others finished | M0_b |
| 103 | 104-1: one low cell in the large-module group | full_charge_then_fail only |
| 115 | 116-1: one low cell finishing before the rest | M0_a, Jan25 |

The ±1 variants reflect a single cell that is either higher than its peers (still being bled when others have finished) or lower (drops below threshold before its peers). The module-count spikes reflect cells within a module being tightly enough matched that they cross the balancing threshold nearly simultaneously, producing a natural plateau in the count.

**cnt=116 frequency**: In well-behaved sessions (M0_a, Jan25), cnt=116 is the single most frequent non-zero count value. A well-matched pack charges to the same voltage simultaneously, putting all cells above the balancing threshold at once.

**cnt=103 in full_charge_then_fail only**: This session is the only one ending in a charge failure. cnt=103 (5388 frames, 12.4% of balancing time, 7.1x ratio) could indicate one cell in the large-module group was persistently below threshold — either a weak cell or a cell that never fully balanced. Whether this is related to the subsequent charge failure is not established.

---

---

## Phase 2 — Cell Voltage Spread vs Balancing Behavior

Analysis script: `artifacts/balancing_cell_voltage_spread.py`

Signals: `bcm_cell_vmax` and `bcm_cell_vmin` (0x430, 1 mV/count) alongside `bcm_balancing_cnt` (0x440 B7).

### Spread at key moments

| Session | Spread at onset | vmax/vmin at onset | Spread at cnt peak | Spread after convergence |
|---------|----------------|-------------------|-------------------|--------------------------|
| full_charge_then_fail | 8 mV (SOC 95.5%) | 3401/3393 mV | 9 mV | n/a (session ended) |
| after_swap_M0_a | 15 mV (SOC 100%) | 3405/3390 mV | 23 mV | 2-4 mV |
| after_swap_M0_b | 11 mV (SOC 93.5%) | 3400/3389 mV | 13 mV | 2-4 mV |
| after_swap_charge_9pm | n/a (no balancing) | n/a | n/a | n/a |

### Spread grows during active balancing, then collapses

In both M0_a and M0_b, spread increases substantially during the heavy balancing phase before collapsing:

- **M0_a**: spread grows to 32-54 mV at t+140-150 min, then drops sharply to 3-4 mV by t+160 min and holds there for the remaining ~130 min
- **M0_b**: spread grows to 47-63 mV at t+160-170 min (peak), then drops to 2-4 mV by t+190 min and holds for the remaining ~350 min
- **Convergence spread**: both sessions stabilize at 2-4 mV, which appears to be the balanced equilibrium state for this pack

The spread increase during balancing reflects cells traversing the steep LFP CC->CV knee at different times — cells with slightly higher SOC hit the knee first, producing large voltage differences for small SOC differences. Bleed resistors respond to this spread; they do not cause it. Once cells have been equalized, spread collapses.

### full_charge_then_fail: spread still rising at failure

In this session the spread kept increasing past 100% SOC (up to 56 mV at t+100-110 min) while balancing was heavy (cnt_mean ~91). Unlike M0_a and M0_b where the spread peaked and then collapsed, this session ended (charge failure) while spread was still elevated and cnt was high. Whether the large spread was a cause, a symptom, or unrelated to the failure is not established from this data alone.

### charge_9pm anomaly: 25 mV spread, zero balancing

This session peaked at 25 mV spread near 99% SOC yet triggered no balancing at all, despite M0_b starting balancing at only 11 mV spread at 93.5% SOC. The 9pm session immediately followed M0_b (which ended with a long balancing tail converging to 2-4 mV). Possible explanations:
- The BMS may require observing the spread at rest/settled rather than during active charging taper
- There may be a hysteresis threshold — balancing was not triggered because the BMS considered cells "already balanced" from the end of M0_b
- The 25 mV spread observed may have been transient and not sustained long enough to trigger the BMS threshold

---

## Phase 3 — Onset, Ramp, and Balancing Threshold

Analysis scripts: `artifacts/balancing_onset_threshold.py`, `artifacts/balancing_onset_to_116_ramp.py`

Sessions: full_charge_then_fail, M0_a, M0_b, Jan25 (vtrux_charge_M1, January 2026)

### Balancing onset voltage

Balancing first appears when the leading cells reach ~3400 mV. At the moment the first non-zero cnt frame appears, vmax is consistently 3400–3406 mV across all sessions, with a spread of only 8–15 mV. There is no step change in voltage at onset — cells were hovering at that level throughout the 120s window before and after the first counted frame.

| Session | vmax at onset | cnt at onset | SOC at onset |
|---------|--------------|-------------|-------------|
| full_charge_then_fail | 3401 mV | 3 | 95.5% |
| M0_a | 3405 mV | 11 | 100.0% |
| M0_b | 3400 mV | 28 | 93.5% |
| Jan25 | 3404 mV | 5 | 95.5% |

The count at first onset reflects how many cells had already crossed the threshold at that moment — a proxy for pack imbalance entering the charge. M0_b's onset count of 28 at the lowest SOC (25.5% starting SOC) is consistent with the most imbalanced starting state.

### Two distinct cnt=116 episodes per charge session

cnt=116 occurs at two very different voltages per charge:

1. **Ramp transient (~3400–3420 mV, SOC ~96–98%)**: a brief flash to 116 during the 2-minute count rise as all cells cluster at the LFP knee. Voltage barely moves during the entire ramp.
2. **Sustained CV plateau (~3590–3600 mV, SOC ~100%)**: the long cnt=116 phase after the charger reaches CV, when all cells have converged at full-charge voltage. This is where the 1100–2200 cnt=116 frame windows from Phase 1 occur.

### Ramp duration

| Session | Ramp duration | SOC range during ramp | vmax range during ramp |
|---------|--------------|----------------------|----------------------|
| full_charge_then_fail | 141s (2.3 min) | 95.5→96.0% | 3399→3411 mV |
| M0_a | 137s (2.3 min) | 100→100% | 3401→3420 mV |
| M0_b | 586s (9.8 min) | 93.5→98.0% | 3397→3407 mV |
| Jan25 | 121s (2.0 min) | 95.5→96.5% | 3398→3405 mV |

Three sessions ramp in ~2 minutes. M0_b takes nearly 10 minutes with the count oscillating between 0 and ~100 for the first ~250s before building steadily — consistent with its more imbalanced starting state (25.5% SOC) causing cells to repeatedly cross and recross the threshold during CC charging.

### Milestone sequence during ramp confirms module grouping

In the three fast-ramp sessions, count milestones are reached in order:

| Milestone | full_charge (141s ramp) | M0_a (137s) | Jan25 (121s) |
|-----------|------------------------|-------------|-------------|
| cnt=1 | +0s | +0s | +0s |
| cnt=12 | +16s | +26s | +71s |
| cnt=52 | +52s | +50s | +79s |
| cnt=104 | +75s | +124s | +105s |
| cnt=116 | +141s | +137s | +121s |

The 12s module and the four large 26s modules cross the threshold in sequence, not simultaneously, consistent with the module-level count spikes seen in the distribution analysis.

---

## Phase 4 — January 2026 Charge Session Audit

Analysis script: `artifacts/balancing_jan_audit.py`

Four sessions audited: M0_a (Jan 16-17), charge_9pm (Jan 17), another_M0 (Jan 23), vtrux_charge_M1 (Jan 25). These were post-battery-swap sessions intended to bring the pack to balance after installation.

### Session Overview

| Session | Date | Duration | SOC range | Bulk spread (pre-balance) | Peak spread | Convergence | Balancing tail |
|---------|------|----------|-----------|--------------------------|-------------|-------------|----------------|
| M0_a | Jan 16-17 | 298 min | 45->100% | 5-8 mV | 32 mV (t+140 min) | 2-3 mV by t+160 min | tail through t+280+ min |
| charge_9pm | Jan 17 | 35 min | 86.5->100% | 4-25 mV (mean 12 mV) | n/a | n/a | no balancing |
| another_M0 | Jan 23 | 548 min | 25.5->100% | 9-17 mV | 47-63 mV (t+160-170 min) | 2-3 mV by t+190 min | tail through t+540 min (~9 h) |
| vtrux_charge_M1 | Jan 25 | 145 min | 76->100% | 5-10 mV | 27 mV (t+40 min) | 2-3 mV by t+60 min | settled by t+90 min |

### CC->CV Transition Visible in vavg

The vavg column (mean of vmax and vmin over a 10-minute bucket) clearly shows the CC->CV transition as a sharp rise in average cell voltage within a single 10-minute bucket:

| Session | CC->CV bucket | vavg before | vavg after |
|---------|--------------|-------------|------------|
| M0_a | t+130->140 min | 3385 mV | 3433 mV |
| another_M0 | t+140->150 min | 3402 mV | 3429 mV (gradual, spread over 3 buckets) |
| vtrux_charge_M1 | t+30->40 min | 3385 mV | 3454 mV |

another_M0's transition is more gradual (t+140-180 min) and spread is 9-17 mV rather than 5-10 mV, consistent with the more imbalanced starting state causing cells to cross the LFP knee at different times.

### Settled Equilibrium

All sessions that completed balancing converge to 2-3 mV spread and hold there. This appears to be the natural floor for this pack — likely a combination of manufacturing spread and the bleed threshold hysteresis.

### Pack Imbalance Trajectory

The bulk pre-balancing spread (before cnt rises) tracks the imbalance state entering each session:

- **M0_a** (Jan 16-17): 5-8 mV — reasonable starting state after swap
- **another_M0** (Jan 23): 9-17 mV — widest spread seen; pack had drifted further out of balance or the Jan 16-17 session did not fully converge
- **vtrux_charge_M1** (Jan 25): 5-10 mV — tighter than Jan 23, consistent with the 9-hour Jan 23 session having improved balance

The Jan 23 session was the longest at 548 min with a 9-hour balancing tail, and the Jan 25 session shows the tightest spread and fastest convergence (settled within ~90 min of onset vs. ~80 min for M0_a and ~100 min for another_M0). This confirms the Jan 23 marathon session meaningfully reduced cell-to-cell imbalance.

### charge_9pm (Jan 17): Zero Balancing Again

This session ran from 86.5% to 100% immediately after M0_a (same day). Like the previously documented charge_9pm behavior, no balancing occurred despite spread reaching 25 mV near 100% SOC. This is consistent with the BMS not re-triggering balancing when it considers the pack balanced from the prior session.

---

## Open Questions

- Can per-cell identification be obtained from a diagnostic bus or proprietary protocol?
- Does `bcm_cell_vmin` correspond to the unbalanced (low) cell's voltage during active balancing?
- Why did charge_9pm show 25 mV spread near 100% SOC without triggering balancing?
- Is the spread growth during active balancing a normal artifact of the bleed process, or does an unusually high spread (as in full_charge_then_fail) indicate a problem?
- Is cnt=103 in the failed charge session related to the charge failure, or coincidental? Does the persistently low cell correspond to the high voltage spread seen in that session?
- Why does cnt=52 appear in M0_a and Jan25 but not M0_b? Do those two sessions happen to have the same two modules finishing last?
