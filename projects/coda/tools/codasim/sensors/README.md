# codasim/sensors

Plant outputs -> bus-signal views (owner: `Coda drivetrain lash model`). Interface `../interfaces.py` `Sensor`:
`step(plant_out)` runs at the plant step and returns a value only at the signal's frame instant.

| File | Signal | Contents | Ported from |
|---|---|---|---|
| `speed.py` | `0x1C0.Motor_Speed` | `EdgeSpeedSensor`: per-q_deg edge update, 0.25 s timeout, 0.5 rpm quantum, 10 ms transport, emitted every 10 ms | `closed_loop_sim.EdgeSpeedSensor` (worklog 3AP) |
| `accel.py` | `0x330.Long_Accel` | `AccelSensor`: optional low-pass, 18 ms delay, 0.08 quantum, 50 Hz | `lash_plant.AccelSensor` + `rd_shift_episodes._closed` |

The DLCM's own 2-tick speed delay (0x308 vs 0x1C0) is not here; it is a DLCM-side timing parameter.

The source files named in the last column (`lash_plant.py`, `rd_shift_episodes.py`, ...) were deleted at codasim step 7 (2026-10-10); they are provenance only.
