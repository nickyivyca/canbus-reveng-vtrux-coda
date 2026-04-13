# DCDC_LV_Curr Investigation (0x18FFD6B3 B2-B3)

> Created 2026-03-29. Branched from epri-verification.md open item 3.
> DCDC_LV_Volt (B0-B1) is CONFIRMED. This file tracks the unresolved B2-B3 current channel.

## Signal Definition (EPRI)

- **ID:** 0x18FFD6B3 (Bel DCDC converter, source address 0xB3)
- **Bytes:** B2-B3, LE signed int16
- **EPRI name:** DCDClowvoltagecurrentreading
- **EPRI scale:** 0.05 A/count
- **Expected role:** 12V output current from DCDC converter

## Evidence Gathered

### Phase 6 (epri_verify_open_items.py, 2026-03-29) — Charge session taper

Per-chunk analysis of `truk1log_M1` (19 chunks, long charge session):

| Chunk range | Mean LV_Curr | Mean LV_Pwr |
|-------------|-------------|-------------|
| T0 (start)  | 6.74 A      | 96.7 W      |
| T1          | 5.30 A      | 76.1 W      |
| T10-T18 (late) | 4.54-4.81 A | 65-69 W |

Clear downward taper over the session. Consistent with 12V battery charging from discharged state to near-full: high acceptance current early, tapering as battery approaches full charge. Physically plausible.

Voltage is constant at 14.35V throughout, consistent with DCDC in constant-voltage charge mode.

### Phase 7 (epri_verify_open_items.py, 2026-03-29) — Blower fan test

Log: `vtruxanotherevaplogpart2.log` (2010s drive, heater active, blower on/off events).
Blower: 0x451 B4 x0.392% (Climate_Control_Front_Blower_Fan_Speed, 0-32.9% observed).

**Second blower-off span** (t=1839-1982s, 143s, controlled dropout mid-drive):

| Window          | n    | Mean LV_Curr | Mean LV_Volt | Mean LV_Pwr |
|-----------------|------|-------------|-------------|-------------|
| Pre-off (1719-1839s) | 1202 | 55.9 A | 14.3V | 799 W |
| Blower-off (1839-1982s) | 1427 | 26.1 A | 14.3V | 375 W |
| Post-on (1982-2011s)    |  287 | 27.4 A | 14.3V | 393 W |

**Interpretation:**
- Pre-off → off: -29.8A drop. Too large to be blower only. Most likely explanation: generator engine shut off at ~t=1839s, taking the **generator oil pump** (12V, ~430W estimated) off the bus simultaneously with the blower dropout. Pump running at that load level is consistent with prior observations of the oil pump load being ~a few hundred watts.
- Off → post-on: +1.26A = ~18W for blower at 32.9% speed. Plausible for a truck cabin blower at partial speed.
- Generator oil pump did not restart after t=1982s, so current stayed low even when blower resumed.

**Overall blower-on vs blower-off across full log:** delta = -0.465A (statistically indistinguishable, std 13-20A). Uninformative because the long blower-off period at the start of the log (0-1002s, warmup) dominates and the pump state confounds the short dropout.

### Pump comparison attempt (Phase 4, 2026-03-29)

**Note (2026-04-11): truk1log_M1 was mislabeled as "parts truck" — odometer confirms it is the main truck (Oct 2025, pre-swap battery, clean charge session). The comparison below is therefore main truck vs main truck, not parts truck vs main truck. The pump disconnect premise was wrong.**

Compared `truk1log_M1` (main truck, pre-swap battery, Oct 2025) vs `rainychargedebug.log` (main truck, post-swap battery, Feb 2026).

truk1log_M1: ~71W mean LV power during CC phase.
rainychargedebug: ~123W mean LV power during CC phase.

**Result: inconclusive.** The ~50W difference is consistent with different 12V battery states at session start (discharged battery draws higher initial charge current). No pump state difference between sessions; the pump was on CAN in both. This phase cannot be used to characterize PE pump 12V load.

## Driving Range

From `vtruxanotherevaplogpart2.log` during active driving:
- Range: 0.00 - 200.45A
- Mean (blower on, generator on): ~55.9A (~800W)
- Mean (blower on, generator off): ~27.4A (~390W)
- Generator oil pump estimated contribution: ~30A (~430W)

At 14.35V, these are physically plausible for a heavy-duty truck 12V bus under various load conditions. The 0A minimum likely corresponds to brief DCDC idle moments or startup.

## What Would Confirm This

1. **Generator oil pump switched test**: A log capturing the generator oil pump being deliberately connected/disconnected while monitoring 0x18FFD6B3. The `vtruxunplugpumpthenhvbatterylvconnector.log` or `vtruxpartstruck.log` may be useful — check whether those logs contain 0x18FFD6B3 and show a step change in B2-B3 at the pump disconnect event.

2. **Known-load switched test**: Any log where a specific 12V load with known wattage is switched on/off. Headlights (~40-60W for LED, ~100W for halogen) would be good but the GMLAN DBC has no headlight state signal present on this bus.

3. **0x18FF0320 B2-B3 cross-check**: This separate message claims to encode 12V bus voltage at ~0.001 V/count (MEDIUM-HIGH confidence). If V is known from two independent sources, and we also have 0x18FFD6B3 B0-B1 (LV_Volt), we can check whether P = V × I closes the energy balance against HV input power (B4-B5 × 0x18FFD???? current, if ever identified).

4. **Scale sanity via generator pump**: If the pump draws ~430W at 12V, that's ~30A at 14.3V. B2-B3 change of ~30A at 0.05 A/count = 600 counts. Cross-check: in a clean pump-off event, does B2-B3 drop by ~600 counts? See note 1 above.

## Script Reference

Analysis code: `notes/artifacts/epri_verify_open_items.py` Phases 4, 6, 7.
