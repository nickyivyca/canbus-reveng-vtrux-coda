# Outside Air Temperature — Investigation & Decision (DROPPED)

**Status:** Investigated and **dropped.** An "Outside: NN°F" display was briefly added to
the Coda green-screen, then removed in `coda-debug (19).apk` (2026-05-22) after testing showed
no CAN sensor reads true ambient reliably.

**Question:** Does the Coda broadcast a usable outside-air temperature on CAN that could be shown
on the Android display?

**Answer:** No. There is no clean ambient-temperature sensor on the Coda CAN bus. The signal
named for the job (OPAirTemp) is a poorly-calibrated estimate, and the best physical proxy
(battery pack inlet air) is only accurate when the pack is near ambient.

---

## Sensor findings

All temps decode as `T_degC = raw - 128` (DBC source of truth) → °F.

| Signal | ID·byte | Behavior | Verdict |
|--------|---------|----------|---------|
| **OPAirTemp** | 0x391 B3 | Damped/computed *estimate*, not a clean thermistor. ~+12 °F mean high vs ground truth; high even parked at night; stuck at 62 °F on a 44 °F highway. Error ranges +5 to +20 °F. | Worst. Not calibratable by a constant offset (error is not constant). |
| **FrontInletAirTemp** | 0x390 B0 | BMS-sent battery-pack inlet air. = true outside air **only when pack ≈ ambient** (cold start / normal driving): dropped to the real 44.6 °F on the Feb-17 highway and *ignored the defroster*. When the pack is warm (post-charge / hot day) it reads **pack temp** (tracks AvgCell) and converges only as the pack cools over hours. | Best available, but pack-confounded exactly when you'd notice (post-charge/hot soak). |
| AvgCellTemp | 0x382 B0 | Battery thermal mass; slow. Used as the discriminator below. | Not ambient. |
| EvapAirOffTemp | 0x391 B5 | Cabin/evaporator air — *rises* with defroster heat. | Not ambient (HVAC-coupled). |
| UnderHoodTemp | 0x391 B1 | All-sentinel (0x80) in every log — not wired on this vehicle. | Absent. |

**Discriminator for FrontInlet trustworthiness:** `FrontInlet < AvgCell` = real airflow pulling
in outside air (trust it); `FrontInlet ≈ AvgCell` = pack-dominated, true ambient unknown.

---

## Evidence

**1. Weather comparison (driving logs vs Open-Meteo Santa Cruz hourly).** OPAirTemp is high in
every condition, never low:

| When | Actual ambient | OPAirTemp | OPAir err | FrontInlet | FrontInlet err |
|------|---------------:|----------:|----------:|-----------:|---------------:|
| May 1 ~09:15 (cool AM) | 58 °F | 66 | +8 | 61 | +3 |
| May 1 ~17:44 | 70 °F | 75 | +5 | 70 | 0 |
| May 5 ~19:25 | 61 °F | 73 | +12 | 61 | 0 |
| May 7 ~16:27 | 75 °F | 90 | +14 | 72 | −3 |
| May 7 ~19:47 (post-charge) | 64 °F | 90→84 | +20 | 79 | +15 |

Mean abs error: OPAir ≈ 13 °F (σ ≈ 5.7); FrontInlet ≈ 0 °F when pack is cool (σ ≈ 3).

**2. Cold-start convergence (Feb 17, "slowturnon with defroster", 2 drives).** With a cold pack
(50 °F), FrontInlet dropped to the true 44.6 °F outside air within ~4 min of highway driving and
did **not** rise with the 5 kW defroster — proving it reads outside air, not cabin air. OPAirTemp
sat at 60–64 °F the whole drive and never moved (a ~16 °F gap at highway speed kills any
airflow/heat-soak explanation). EvapAirOffTemp *rose* 59→68 °F with the heater (cabin air).

**3. Hot-soak non-convergence (May 7 evening).** After a charge warmed the pack to ~77 °F,
FrontInlet got pinned at ~78 °F and tracked AvgCell exactly — through a 9-minute evening drive
and 2+ hours parked — while true ambient fell from 64 °F to 56 °F. The gap *grew* (+15 → +21 °F).
Unlike a normal car's cowl sensor (recovers in minutes), the "thermal mass" here is the whole
battery pack (cools over hours), and with no cooling-fan airflow it doesn't converge at all.

---

## Method & data

- Ground truth: Open-Meteo hourly `temperature_2m`, Santa Cruz (36.97, −122.03), local time, °F.
  Note: the archive host (`archive-api.open-meteo.com`) is unreachable from this network (TLS
  timeout, both via WebFetch and direct, even off-corp); only `api.open-meteo.com` works, which
  serves only the last ~92 days. Feb 17 could not be anchored absolutely — but FrontInlet's own
  44.6 °F at highway speed serves as the ground truth there (cold pack).
- Logs: Feb 17 slowturnon drives (`projects/coda/logs/codadriveslowturnonwithdefroster*.log`);
  May 1/5/7 Android backups (`../../CANLogs/CodaLogs/`).
- Scratchpads (kept in `notes/artifacts/`):
  - `outside_temp_weather_compare.py` — per-sensor median vs ambient, all candidate temp bytes.
  - `slowturnon_temp_trajectory.py` — Feb 17 cold-start defroster test, time series.
  - `frontinlet_convergence_may7.py` — May 7 hot-evening convergence trace.
  - `fetch_weather.py` — reusable Open-Meteo fetch (run off this network for old dates).
  - `op_air_temp_sanity.py`, `op_air_temp_sentinel_scan.py` — earlier OPAirTemp sanity / 0x80
    sentinel characterization (sentinel runs are all 0.5–0.6 s).

## If revisited

There is no fix on the data side — the encoding is correct (DBC `(1,-128)` verified). Any future
"outside temp" display would have to either (a) use FrontInlet gated on `FrontInlet < AvgCell`,
accepting it goes blank/stale after charging and hot days, or (b) add an external sensor. Neither
was judged worth the misleading-reading risk.
