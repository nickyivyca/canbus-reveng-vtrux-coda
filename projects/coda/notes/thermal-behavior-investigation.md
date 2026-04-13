# Thermal Behavior Investigation

## Observation — 2026-03-28 morning drive

During a normal morning drive the CODACAN display showed two unusual things:
1. **Heater graphic flickering** — the cabin heater icon was intermittently toggling on/off throughout the latter part of the drive, even while the heater was running normally.
2. **"Pack heater running" message** — the display explicitly showed this message for a period during the drive.

The pack fan was not audibly running (or was inaudible) when these indicators appeared.

### What the CAN data shows

Log: `coda_20260328_101624_T0.log` + `_T1.log` (415s, 440k frames, B CAN)

| Time | Event |
|------|-------|
| t=0s | `0x382` Cell_T_avg=15°C, max=16°C, min=14°C |
| t=0–10s | CASS (AC compressor cold-start) — `0x276 B2` briefly `0x11` during spinup |
| t=32–34s | Second CASS attempt |
| t=0–415s | `0x378 B2` (BMSmode) = `0xEA` throughout — not normal driving value `0xD2` |
| t=0–415s | `0x276 B5` (PTCHeaterPWM) NOISY — cabin PTC heater varying continuously |
| t=208.94s | **`0x391 B0`: `0xFC → 0xC1`; `0x276 B6` (RadiatorFanPWM) `0x00 → 0x22`; `0x276 B2`: `0x01 → 0x0D`** |
| t=209–248s | `0x276 B2` oscillates `0x01 ↔ 0x0D` at ~1–2s cycle; `0x391 B0` oscillates `0xFC ↔ 0xC1` in lockstep |
| t=244s | `0x276 B7` (labeled BattFanPWM) first goes non-zero: `0x00 → 0x1E` (12%) |
| t=248s | `0x276 B2` settles back to `0x01`; oscillation ends |
| t=248–415s | `0x276 B7` slowly increments: 0x1E → 0x3C → ... → 0x43 (26%) |
| t=415s | Cell temps still 14–16°C, unchanged from start |

The heater graphic flickering is correlated with the `0x276 B2` oscillation period (t=209–248s). When B2=`0x0D`, the graphic disappears; when B2=`0x01`, it returns.

Cell temperatures were flat at 14–16°C for the entire 415s session — no warming trend visible. This is well above any threshold that would normally justify active pack heating.

### Comparison: `codabatteryconditioningrunningendofdrive.log`

This earlier log captured a known conditioning-active state (the display was showing conditioning running at end of drive). Comparing `0x276` in that log vs the morning drive:

| Signal | Conditioning log (26.7s) | Morning drive (415s) |
|---|---|---|
| B2 (HVACHVDisableStatus) | `0x05`, constant | `0x01` ↔ `0x0D` oscillating |
| B5 (PTCHeaterPWM) | 21 (8.2%), constant | NOISY, continuously varying |
| B7 (BattFanPWM) | **175 (68.6%), constant from t=0** | 0 → 67 (26%), slow ramp |

Key observations:
- When conditioning is definitively active, B7 = 175 (68.6%) — high, constant, and audible. This argues that the **BattFanPWM label is correct** and a real pack fan runs at that speed.
- In the morning drive, B7 only reached 26% after a slow 170s ramp — either a much milder or different mode than full conditioning.
- B2 = `0x05` in the conditioning log is a new value not seen in the morning drive (`0x01`/`0x0D`). The three observed B2 states so far: `0x01` (normal), `0x05` (confirmed conditioning), `0x0D` (morning unknown), `0x11` (CASS). What `0x0D` means remains open.

---

## Open hypotheses

### H1 — CODACAN signal labels are wrong (most likely for BattFanPWM)

**Weakened** by conditioning log comparison. When conditioning is definitely running, B7 = 68.6% which is high and audible — consistent with a pack fan. The label is likely correct.

Remaining question: the morning drive B7 ramp to only 26% is still much gentler than confirmed conditioning. This could mean:
- The morning event was a different/milder mode (early-stage conditioning, or cabin thermal management with incidental pack involvement)
- The real pack fan was already spinning down at the start of the morning log (log starts mid-event?)

- **Test**: bench test with pack fan connector — disconnect and confirm B7 drops to zero.

### H2 — PTC heater runs briefly at full-cold dial setting

The cabin PTC heater (`0x276 B5` PTCHeaterPWM) was NOISY from t=0 throughout the entire drive. If the temp dial was set to full cold, the PTC shouldn't be running at all.

- If the heater was running with the dial at cold, it could mean the HVAC ECU runs a brief warm-up or anti-condensation cycle regardless of user setting on cold starts.
- Alternatively the dial position isn't transmitted on B CAN (it may only be on D CAN or interior CAN), so we can't confirm dial position from this log alone.
- The heater graphic appearing on the display is consistent with the PTC actually running — the display reads the same CAN signal we're reading.
- **Test**: drive with cabin temp dial explicitly at full cold and note whether PTCHeaterPWM is still non-zero. Cross-reference with D CAN if available for dial position signal.

### H3 — BMSmode 0xEA is not a thermal management mode

`0x378 B2` = `0xEA` throughout vs. normal `0xD2` during driving. We've flagged this as an "unusual" value but haven't confirmed what it means. It's possible `0xEA` is just a normal variant:

- A different firmware version
- A mode the car enters after a full charge (SoC was high this morning)
- A mode related to a minor fault that doesn't affect driving (but which the BMS flags internally)
- Completely unrelated to pack thermal management

If `0xEA` is benign, the entire pack heating narrative unravels — the state change at t=209s might have a different explanation.

- **Test**: capture BMSmode across multiple drives and charging sessions. Look for patterns: does `0xEA` appear only after overnight charging? Only at high SoC? Only on cold mornings?

### H4 — 0x276 B2 oscillation is HVAC PID regulation, not pack heating

`0x276 B2` (HVACHVDisableStatus) oscillating `0x01 ↔ 0x0D` was interpreted as the HVAC HV circuit switching between cabin and pack heat. But this could alternatively be:

- Normal duty-cycle regulation of the cabin PTC heater (chopping the HV at low demand)
- A transient HVAC fault/recovery loop unrelated to pack heating
- The CODACAN display's "pack heater running" label being triggered by a different condition than what the signal name suggests

The lockstep oscillation of `0x391 B0` (`0xFC ↔ 0xC1`) is curious — those values are very high if interpreted as humidity (504% / 386%). It's more likely B0 is a status bitfield rather than a pure humidity reading in this state.

- The conditioning log shows B2 = `0x05` (not `0x0D`) when conditioning is confirmed active. This suggests `0x0D` in the morning drive is a *different* state from full conditioning — possibly an intermediate or transitional mode.
- Known B2 values so far: `0x01` (normal HV enabled), `0x05` (confirmed conditioning), `0x0D` (morning unknown state), `0x11` (CASS spinup).
- **Test**: replicate the "pack heater running" display message deliberately (e.g. by chilling the pack overnight) and correlate with `0x276 B2` and `0x391 B0` transitions. Look specifically for whether B2 reaches `0x05` or stays at `0x0D`.

### H5 — 0x382 cell temp readings are wrong or represent something other than cell temps

~~Cell temps read exactly 14–16°C and never moved across 415s of driving.~~ **Probably not a concern.** This was a short, low-speed, low-power drive. Cell temps have been seen to move on longer drives and when the pack starts genuinely cold. Flat temps on a 7-minute urban drive are expected — the pack is well-insulated and the heat input from low discharge current is negligible. 0x382 decoding is considered valid.

---

## Next steps

- [ ] Confirm what BMSmode `0xEA` means — sweep `0x378 B2` across multiple sessions and correlate with display
- [ ] Confirm BattFanPWM identity (`0x276 B7`) with a bench test
- [ ] Capture a cold-start drive (pack genuinely cold, below 10°C) to see if the same behavior reproduces with lower cell temps
- [ ] Capture a drive with cabin dial explicitly at full cold to test H2
- [ ] Check if `0x391 B0` has a different meaning in the pack-heater-active state vs normal (bitfield vs humidity)
