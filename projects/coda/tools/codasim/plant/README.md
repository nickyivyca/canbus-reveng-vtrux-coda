# codasim/plant

Physical plant and road load (owner: `Coda drivetrain lash model`; plan `projects/coda/notes/plans/codasim_full_model.md`).
Interface: `../interfaces.py` (`Plant`, `Load`, `LoadSource`). Ported 2026-10-09; bit-identical to the old
closed loop on all 371 scorable reversals (`notes/dlcm/artifacts/codasim_plant_gate.py` phase 1).

| File | Contents | Ported from |
|---|---|---|
| `lash.py` | constants (J_V, GEOM, RATIO, J_TOT), lash contact spring/damper, `LashPlant` (no friction) | `lash_plant.py` |
| `vehicle.py` | `FrictionPlant` (grade + Coulomb friction, stiction), `BodyPlant` (fore-aft body suspension), `MountPlant` (tested hypothesis, not adopted). OPT-IN 2026-10-15 (`regen13_model_screens.md` step 3, default off, bit-for-bit when off on 387 reversals): `BodyPlant(z_hold=)`, the body spring's damping ratio while the wheel is held at standstill, a modelling patch so braked stops settle as the car's do (`notes/dlcm/artifacts/body_rock_check.py`, `stop_ring_proto.py`); `cosim.run(body_hold_z=)` passes it | `rd_shift_episodes.py` phases 7, 10; `rd_shaft_refit` phase 6 |
| `presets.py` | `make(name)`: `current` (adopted step-3 plant), `msm` (trial, not adopted), with sources | `rd_shift_episodes.PLANTS`, `STEP3_BODY` |
| `road.py` | `RoadLoad` LoadSource (provenance `estimated`, not causal): const / slow / meas_step / meas_blend (adopted) / meas_hold; inverse dynamics; phase-7 friction R0/kb (default). Options (2026-10-14, `regen13_model_screens.md` step 2, defaults unchanged): `friction="measured"` (car-measured friction curve `FRICTION_MEAS` at the plant's gain), `grade_fallback=True` (opt-in grade from all moving samples, for braked stops). 2026-10-15 (step 3, opt-in, default off): `stop_grade="parked"` ramps the grade over the last `STOP_GRADE_RAMP_S` (0.5 s) before the car's recorded standstill to the slope its 0x330 reads parked; stop episodes in D only, refused where unmeasurable (`cosim.run(..., stop_grade=, stop_grade_ramp_s=)`) | `rd_shift_episodes.py` phases 7, 9, 21 |

`rpm` in plant outputs is the TRUE motor speed; `w_m_sensed` (MountPlant) is rotor-relative-to-housing kinematics.

The source files named in the last column (`lash_plant.py`, `rd_shift_episodes.py`, ...) were deleted at codasim step 7 (2026-10-10); they are provenance only.
