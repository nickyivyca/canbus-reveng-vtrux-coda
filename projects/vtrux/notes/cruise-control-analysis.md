# Cruise Control — Signal Reference

**Logs:** `vtruxevapdrivelog4.log`, `vtruxanotherevaplogpart2.log`
**Investigation completed:** 2026-03-08 (Phase 9). Full PT bus investigation history in `deprecated/cruise-control-pt-bus-investigation.md`.

---

## 0x644 — Cruise Speed Setpoint (PT Bus)

Confirmed in Phase 9 (2026-03-08). In `vtrux-powertrain-experimental.dbc` as `CruiseSetpoint_0x644`.

### B2 — Mode + Speed MSB

| B2 (hex) | Hi nibble [7:4] | State |
|----------|-----------------|-------|
| 0x80 | 8 | Idle / cruise off |
| 0x88 | 8 | Standby (Engage pressed, awaiting Set) |
| 0x9x | 9 | Throttle override / auto-disengage |
| 0xAx | 10 | Active cruise |

- **High nibble** = mode indicator (DBC signal: `CruiseMode`, 4-bit Motorola, VAL_ 8=IdleStandby 9=ThrottleOverride 10=Active)
- **Low nibble** = MSB of 12-bit speed field

### 12-bit Speed Field: `(B2[3:0] << 8) | B3`

- **Scale:** 0.125 km/h per count (8 counts/km/h). DBC signal: `CruiseSpeedSetpoint`, 12-bit Motorola, scale=0.125 km/h.
- **Step:** +8 counts = +1 km/h (Speed+); -8 counts = -1 km/h (Set press / Speed-)
- **Engage sequence:** Engage press → B2=0x88, 12-bit=2048 (sentinel). Set press → captures current vehicle speed, B2→0xAx.
- B3 overflow (255→0) increments B2 lo nibble (e.g. 2→3), acting as a 4-bit MSB extension.
- **B3 step values confirmed:** [0, 8, 176, 184, 192, 200, 208, 216, 224, 232, 240, 248] — all multiples of 8.

### Speed Calibration

Calibrated against 0x3E9 GMLAN vehicle speed across both logs. Mean ratio ~8.03, consistent with 8 counts/km/h.

| Event | 12-bit raw | GMLAN speed | km/h |
|-------|-----------|-------------|------|
| Set at t=994 (evaplog2) | 664 | 83.3 km/h | 83.0 |
| Speed+ at t=1052 (evaplog2) | 720 | 89.7 km/h | 90.0 |
| Speed+ at t=1104 (evaplog2) | 768 | 91.1 km/h | 96.0 |
| Engage at t=705 (evaplog4) | 776 | 97.7 km/h | 97.0 |

### Cancel Mechanisms

Two distinct cancel paths confirmed in evaplog2 (t=1370-1445s):

1. **Throttle override:** Throttle pedal press → B2 mode 10→9 (autonomous VCU action, no button press)
2. **Manual cancel:** Engage/Cancel button → B2 9→8 (full reset to idle)

---

## 0x1E1 B5 — Cruise Button State (VCU Extension, Vehicle Bus)

Non-standard VCU extension to the GMLAN 0x1E1 message (not in GMLAN DBC). Encodes cruise button events as brief pulses — **not a sustained setpoint.** Full tier table in `../Vtrux.md` (Cruise Control section).

---

## Cruise Torque Command

The traction torque command during cruise is **0x041 B1-B2 on the OBD bus** (not PT bus). Confirmed in `traction-inverter-control.md` Phase 2. The cruise speed controller runs in the VCU and does not use throttle simulation.

---

## Related Files

| File | Relevance |
|------|-----------|
| `vtrux-powertrain-experimental.dbc` | `CruiseSetpoint_0x644`: CruiseMode + CruiseSpeedSetpoint signals |
| `traction-inverter-control.md` | Cruise torque command: 0x041 B1-B2 (OBD bus) |
| `deprecated/cruise-control-pt-bus-investigation.md` | Full investigation history (Phases 1-8); PT bus scans |
| `../Vtrux.md` | 0x1E1 B5 tier table; Cruise Control section |
