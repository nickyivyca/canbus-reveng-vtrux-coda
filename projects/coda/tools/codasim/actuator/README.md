# codasim/actuator

The MCM (owner: `Coda drivetrain lash model`). Interface `../interfaces.py` `Actuator`.

| File | Contents | Ported from |
|---|---|---|
| `mcm.py` | `McmDelay`: command counts x 0.096 delivered Nm (fitted), gear-frame -> motor-frame flip from the gear it is told (GEAR418_R negates), then a 25 ms pure delay (MCM_DELAY_STEP3) | `rd_shift_episodes._closed`, `closed_loop_sim.run_episode` |
