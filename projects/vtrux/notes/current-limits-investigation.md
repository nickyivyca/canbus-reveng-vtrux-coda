# Vtrux BMS Current Limits — Signal Reference

**Started:** 2026-03-01 | **Last updated:** 2026-03-28
**Negative scan phases (Phases 1, 2, 2b Steps 4/4b, Phase 5 bit scans) archived in `deprecated/current-limits-negative-scans.md`.**

---

## Background

The Vtrux BMS broadcasts regen (charge current limit, CCL) and discharge current limit (DCL) on
the powertrain bus via its BMS-originated cluster (0x400-0x507). Two limiting events were observed
in `vtruxcurrentlimitingtest.log` (per `.txt` sidecar):

1. **Regen limit** -- driving downhill, regen partially then fully blocked. Fully available at
   <=80% SoC; BMS progressively restricts it above that.
2. **Discharge limit** -- highway merge limited to ~half full power (~90 kW vs 180 kW full).

**Reference event windows (corrected):**
- t=30-72s: downhill unrestricted regen (reference baseline)
- t=348.6-365.6s: regen current limit active (auto-detected from 0x050; Phase 2c)
- t=606s+: highway discharge limit active (Phase 2b Step 3)

---

## Phase 2b Steps 1-3 -- Torque Demand Characterization and DCL Window

**Log:** `logs/vtruxcurrentlimitingtest.log`
**Script:** `artifacts/characterize_torque_demand.py`; output: `artifacts/characterize_torque_demand.txt`

**Brake idle threshold:** 156 counts (sensor floor; unpressed pedal reads 0/39/78/117/156 --
multiples of 39). Genuine brake presses are brake > 156.

**Pass 1a -- Brake-demand regen model (brake > 156 only, 271 frames):**
- Model: |torque| = 0.669 * brake_demand + 476  (R2=0.848)
- Regen torque cap at brake ~1900 counts (torque ~2100 counts); beyond this, additional pedal
  goes to friction brakes without increasing regen.

**Pass 1b -- Speed-stratified regen envelope (lift-off vs brake-pressed, two windows):**

| Speed bin | Unrestricted lift-off p50 | Unrestricted brake-press p50 | Regen-limit brake-press p50 |
|-----------|--------------------------|------------------------------|-----------------------------|
| 3081-4913 | ~448 counts (flat)        | 68-2253 counts (speed-vary)  | ~458 counts (collapsed)     |

**Key CCL finding:** During the regen limit window, brake-pressed regen collapses to the same
level as lift-off regen (~458 counts). The CCL is set to approximately 458 torque counts --
enough to allow coast/lift-off regen but blocking all additional brake-commanded regen.

**Pass 2 -- Throttle demand to discharge torque (16111 frames, t>720s):**
- Model: torque = 0.609 * throttle_demand + 10  (R2=0.957)
- Flux-weakening onset: ~3500 RPM (motor torque feedback drops from plateau of ~4000 counts
  above this speed; torque decreases while power stays roughly constant).

**DCL-active window (Step 3):** t=606s onset confirmed. Full-power threshold (user-confirmed):
~150 kW. DCL unambiguously active at steady state during t=614.2-618.2s and t=620.2-622.2s
(full throttle, above flux-weakening speed, power capped below 150 kW).

---

## Phase 2c -- 0x050 as DC Bus Input Current Limit

**Discovery origin:** `notes/cruise-control-analysis.md` Phase 7, 2026-03-03.

**Encoding:** `(B1 & 0x03) << 8 | B0` -- 10-bit unsigned, VCU-sourced, 9.1 Hz.

**Behavior:**
- **Raw = 0:** no regen allowed (CCL fully engaged)
- **Raw ~292-305:** nominal baseline during normal driving
- Dynamic: rises with throttle/discharge demand during unconstrained driving; falls or caps when a
  limit is active. Does not distinguish source of limit (BMS CCL, VCM discharge protection, etc.)
  but reflects the effective ceiling the VCU is imposing in real time.

**Regen limit timing (climit log):** Signal drops to near-zero at t=348.6-365.6s (auto-detected
as first contiguous block < raw 282 while RPM > 100). Supersedes the previous visual estimate of
t=401-503s.

**VCM pre-limit + BMS ramp sequence (2026-03-28):**
1. t=350.4-356.3s: VCM pre-limits -- 0x050 steps down 305->~187 in discrete -20 count decrements
   while brake pedal remains at full press. bcm_chg_max still at 300 A. VCM-internal, not BMS-driven.
2. t=356.3-358.7s: bcm_chg_max ramps 300->60 A. 0x050 tracks it in near-lockstep once bcm_chg_max
   drops below the VCM pre-limit equivalent (~t=357.5s), becoming the binding constraint.
3. t=358.7-361.4s: bcm_chg_max holds at 60 A and 0x050 stays at 41-45. TRAC_HighPwr_Curr
   (0x462) reads ~0 A -- confirmed zero regen. VCU command hits its functional minimum (~43 raw)
   while bcm_chg_max is still at 64 A; both floors converge within one frame.

**Interpretation:** `0x050 = min(VCM_internal_limit, bcm_chg_max_equivalent)`. The BMS takes ~6s
to update and broadcast its new setpoint after the VCM begins pre-limiting.

**Status:**
- Signal role (DC bus current limit, VCU-to-inverter command): **HIGH CONFIDENCE**
- Encoding (10-bit, VCU, 9.1 Hz): **HIGH CONFIDENCE**
- Scale (A/count): TBD -- computable as `bcm_chg_max_A / 0x050_raw`; at baseline (SoC 25-74%)
  0x050_raw ~= 300 and bcm_chg_max_raw is available from another_M0.

Script: `artifacts/plot_0x050_cltest.py`; output: `artifacts/plot_0x050_cltest3.png`.
Verification: `artifacts/verify_0x420_limits.py` (bcm_chg_max + driver input cross-check).

---

## Phase 3 -- Charging Cycle Confirmation (COMPLETE 2026-03-03)

**Logs:** `logs/after-battery-swap-charges/charge_M0_T*.log` (60 files, ~5h) and
`logs/after-battery-swap-charges/another_M0_T*.log` (55 files, ~9h).
**Script:** `artifacts/ccl_charge_plot.py`; output: `artifacts/ccl_charge_output.txt`
**Ground truth:** `0x18FFD7C0 B2-B3` LE signed x 0.05 A = charger DC output current.

**0x050 present in both charge sessions** (162,579 frames at 9.1 Hz over 5h; 299,415 frames over 9h).

**CCL vs SoC ramp (another_M0, initial pass from 25% SoC -- cleanest dataset):**

| SoC | CCL raw | I_chg (A) |
|-----|---------|-----------|
| 25-74% | 300 | -14.7 |
| 74-82% | 286->280 | -14.7 |
| 84-91% | 280->232 | -14.4 |
| 94-96% | 166->97 | -14.6 |
| 99% | 10 | -12.6 |
| 100% (CV taper) | 10 | -12 to -2.3 |

**Key results:**
- CCL drop is a smooth ramp, not a hard cutoff at 80% -- consistent with LFP cell OCV behavior.
- CV taper phase (SoC=100%): CCL stays flat at 10 while charger current tapers, confirming CCL
  is a limit setpoint (set once at 99%), not a real-time current tracker.
- The minimum broadcast value in charge context is CCL=10 (not 0).

**Confirms:** 0x050 CCL signal identity at HIGH CONFIDENCE.

---

## Phase 4 -- 0x412 B2: BMS Charge Current Limit (COMPLETE 2026-03-04)

**Approach:** Scanned BMS-originated IDs against the 0x050 CCL ramp in `another_M0`
(SoC 74%->99%, CCL 286->10 over ~50 min).
**Script:** `artifacts/scan_ccl_charge.py`; output: `artifacts/scan_ccl_charge_output.txt`
**Verification plot:** `artifacts/plot_0x412_vs_ccl.py` -> `artifacts/plot_0x412_vs_ccl.png`

### Pass A top findings

| Signal | r | uniq | Note |
|--------|---|------|------|
| **0x412 B2** | **+0.999** | **186** | **Primary finding -- analog, continuously tracks ramp** |
| 0x420 B1 | +0.983 | 5 | Correlated; role confirmed in Phase 6 (bcm_chg_max MSB nibble) |
| 0x420 B4 | +0.945 | 156 | Tracks ramp; not decoded by EPRI; role unconfirmed |
| 0x410 B3 | -0.793 | 48 | Inverse (rising as CCL drops) -- SoC/temp consequence |

### 0x412 B2 -- BMS SoC-based charge current limit (HIGH CONFIDENCE)

**Linear regression:** `CCL_0x050 = 1.1840 * B2 - 3.30   (R2 = 0.9980)`

- 28,435 paired samples; effectively a 1:1.184 rescaling with near-zero offset
- 186 unique values -- analog, continuously varying over the charge ramp
- Tracks both the gentle early slope (SoC 74-91%) and the steep final drop (91-99%)

**Static during driving:** In `vtruxcurrentlimitingtest.log`, 0x412 B2 was nearly static
(only 3 non-nominal frames in 17,937). The brief 13s CCL dip at t=350-363s produces no change
in 0x412 B2 -- VCM pre-limiting is VCU-internal, not driven by the BMS during driving.

**Interpretation:** The BMS broadcasts its SoC-based charge current ceiling in 0x412 B2. During
charging at high SoC, the BMS reduces B2 and 0x050 follows closely (scaling ~1.184). During
driving, B2 is static at a high value because the BMS is not restricting charge current at normal
drive SoC — the dynamic behavior of 0x050 during driving comes from VCU-internal logic, not from
0x412 B2.

### 0x420 B4 -- unresolved

r=+0.945, 156 unique analog values, drops to 0 at the climit regen limit event (t=348-366s).
Not decoded by EPRI. Role and interpretation unconfirmed -- not investigated further.

### Open question: 0x412 B2 vs 0x420 B2 (bcm_chg_max)

Phase 6 confirmed bcm_chg_max is encoded in 0x420 B0-B2 (12-bit Motorola nibble-split, B2 =
lower 8 bits). If B1[3:0] (the 4-bit MSB of bcm_chg_max) is always 0 throughout the charge ramp
(i.e., bcm_chg_max_raw < 256 throughout), then 0x420 B2 = bcm_chg_max_raw exactly. In that case,
0x412 B2 tracking the same value would mean 0x412 is a second BMS message rebroadcasting a related
quantity. Verify by decoding full 12-bit bcm_chg_max from another_M0 and checking B1[3:0].

---

## Phase 5 -- 0x050 During Discharge Limiting (COMPLETE 2026-03-04)

**Note:** Bit scans from this phase are in `deprecated/current-limits-negative-scans.md`.

### DCL-active period: t=606s onset confirmed

0x483 B6 was the top bit scan candidate: pre_mode=243, dcl_mode=3, drop=-240. Full-log analysis
showed the upper nibble of B6 continuously descends 9->0 over the first ~530s as battery
discharges, and hits 0 again at t=606s. This is a gradual drain counter/SoC proxy, not a discrete
limit setpoint. **0x483 B6 eliminated as DCL candidate.** The t=606s DCL onset is confirmed from
the torque divergence analysis (Phase 2b Step 3).

### 0x050 CCL behavior during discharge limiting

Raw CCL timeseries around the DCL event (t=570-660s, 9.1 Hz):

- t=570-593s: CCL ~304 flat (vehicle stopped at stop sign)
- t=593-606s: CCL rises continuously 307->~875 as driver applies full throttle on merge
- t=606-610s: CCL gradually declines from ~875 as DCL starts capping motor output
- t=610.1s: CCL snaps back to 304 (momentary throttle lift)
- t=610.8-617s: CCL rises again to ~560-565 then slowly slopes down during confirmed DCL-active window
- t=617.7s: Another snap back to 304

**Interpretation:** 0x050 rises with throttle/discharge demand and falls when discharge is
limited -- consistent with it being a DC bus current limit command from the VCU to the inverter,
dynamically updated each frame. During unconstrained driving the VCU sets it generously; when DCL
is active the VCU holds the ceiling at or near the actual limited current. The gradual slope during
the DCL window (~560->~510 over ~7s) is consistent with an analog ceiling being tightened in real
time.

### Phase 5 conclusion

Both bit scans found no CCL or DCL setpoint signal on any bus. Discharge and charge current limits
are controlled within the VCM, not broadcast as explicit setpoints by the BMS or any other module.
The BMS does broadcast a charge current limit source in 0x412 B2 (Phase 4), and the VCM scales
that into 0x050 -- but the VCM applies its own discharge limiting without any corresponding BMS
broadcast visible on the bus.

**bcm_dis_max cross-check (2026-03-28):** `artifacts/verify_0x420_limits.py` decoded bcm_dis_max
from the climit log. bcm_dis_max is constant at 612 A across all windows -- baseline, CCL event,
post-CCL, DCL event, and post-DCL. **Discharge limiting is conclusively VCM-internal** -- the BMS
is broadcasting full discharge permission (612 A) throughout.

---

## Phase 6 -- EPRI Cross-Reference: BCM Current Limits Confirmed (2026-03-28)

**Source:** `epri-pt-bus.dbc` (`EPRI_BCM_Limits_0420`), confirmed by Ghidra decompile
of `ViaCANbusParser`.

### 0x420 B0-B2: bcm_dis_max + bcm_chg_max (12-bit Motorola each)

| Signal | Formula | Scale | Units |
|--------|---------|-------|-------|
| bcm_dis_max | `(B0[7:0]<<4)\|(B1[7:4])` | 0.25 A/count | A (max discharge) |
| bcm_chg_max | `((B1[3:0])<<8)\|B2` | 0.25 A/count | A (max charge) |

B1 is split: upper nibble (B1[7:4]) = dis_max LSBs; lower nibble (B1[3:0]) = chg_max MSBs.
Already defined in `epri-pt-bus.dbc` -- not in the experimental DBC.

**Why manual scans missed these:** All manual scans (Phases 1-5) tested byte-level (8-bit) and
16-bit LE/BE pairs. The 12-bit Motorola nibble-split was never tested. B1 mixes bits from two
signals; B0 was flat during charge sessions (dis_max stays at max while charging); B2 alone
looks like a noisy partial-signal without knowing B1[3:0] supplies the MSBs.

### 0x420 B1 reconciliation

Phase 4 saw r=+0.983, 5 unique values. Explained: B1[3:0] is the 4-bit MSB of bcm_chg_max.
As bcm_chg_max ramps 300->10 raw counts during SoC 74%->99%, the upper 4 bits step through
5 discrete coarse values. Role now CONFIRMED.

### 0x050 scale (open -- computable)

`scale = bcm_chg_max_A / 0x050_raw = (bcm_chg_max_raw * 0.25) / 0x050_raw`. At baseline
(SoC 25-74%): 0x050_raw ~= 300. Decode bcm_chg_max from another_M0 at baseline to close this.

---

## Status Summary (2026-03-28)

| Signal | Status | Notes |
|--------|--------|-------|
| bcm_chg_max (0x420 B0-B2) | CONFIRMED (EPRI) | 12-bit Motorola, 0.25 A/count; in `epri-pt-bus.dbc` |
| bcm_dis_max (0x420 B0-B2) | CONFIRMED (EPRI) | 12-bit Motorola, 0.25 A/count; in `epri-pt-bus.dbc` |
| 0x050 CCL (VCU-sourced) | HIGH CONFIDENCE | 10-bit LE, 9.1 Hz; scale A/count TBD but computable |
| 0x412 B2 | HIGH CONFIDENCE | r=0.999 vs CCL during charge ramp; role vs bcm_chg_max open (see Phase 4) |
| 0x420 B4 | UNKNOWN | r=0.945 vs CCL; not decoded by EPRI; no further investigation |
| bcm_dis_max during DCL | RESOLVED | Constant 612 A throughout -- DCL is VCM-internal |
| Discharge current limit broadcast | NONE FOUND | BMS does not broadcast DCL setpoint on PT bus |
