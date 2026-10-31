# `:tpms` — Coda indirect TPMS (Android library module)

Everything the Coda app needs for wheel-speed indirect TPMS, including the GPS common-mode
channel, as one module. **Only `:coda` depends on it**, so none of it reaches any other app. The
Vtrux APK carries no TPMS classes and no location permission; that was checked by inspecting both APKs
when the module was split out on 2026-09-24. It depends on `:cancore` for `CanFrame` and the log
format. Nothing in `:cancore` knows it exists.

Design, decisions and verification: `../../android-coda-tpms-implementation.md`. The algorithm and
file format are the algorithm session's spec: `../../../projects/coda/notes/tpms-algorithm-spec.md`.
Current work: `../../notes/plans/coda-tpms-gps.md`.

| File (`src/main/java/com/reverseit/tpms/`) | Role |
|---|---|
| `TpmsCalibration.kt` | The UI seam: `Corner`, `TpmsCalibrationEntry`, `TpmsEstimate`, `TpmsCalibrationStore` |
| `TpmsEpochStore.kt` | The store in `CodaLogs/tpms/` as immutable fragments (schema 2, since build 29): set / undo (tombstone) / amend / completed rows / per-minute partial rows, content-based dedupe with GPS inheritance, in-memory index with a bounded startup read. Reads legacy append-only files as they are. Android-free |
| `FileTpmsCalibrationStore.kt` | `TpmsCalibrationStore` over `TpmsEpochStore`, on one background thread; republishes the detector's estimate after every change except a partial-row checkpoint |
| `TpmsDetector.kt` | The detector: port of the prototype's `run()`. Pools rows by session, `FrozenBaseline`, outlier corner psi, hysteresis and confirmation, STALE on an un-announced fill. Stateless, replays the epoch each time |
| `WheelRatioExtractor.kt` | Port of the Python `extract_one` (ratios), temperatures, `SteeringCentre`, the `0x3FFF` stuck-wheel guard, and `selectDCan`: the ratios are read from D CAN only, identified by anchor ids that are never rebroadcast (a capture without it gives a row with `reject` set) |
| `DriveRowProducer.kt` | Closed log segment -> drive row; catch-up on start |
| `SegmentWatcher.kt` | Detects segment closes from `CanLoggingService.currentSegmentName` (no hook in `:cancore`) |
| `GpsRateAccumulator.kt` | GPS speed x rear wheel speed, per segment and speed band, plus elevation change while moving. Speed only, never position. Wheel frames from D CAN only, by the same anchor rule applied live per segment |
| `GpsSpeedService.kt` | Location foreground service feeding the accumulator; fix times more than 10 s from arrival are replaced by the arrival time (`GpsRateAccumulator.fixTimeNanos`) |
| `HardwareReport.kt` | One JSON inventory of the head unit per installed APK (build, platform properties, display, requested permissions with their platform definition, system features, GNSS hardware, cameras, SIM state, every sensor with a 5 s live sample, dynamic sensors and sensor HAL libraries), written to `CodaLogs/diag/` so it reaches Seafile without ADB. No position, no identifiers |
| `TpmsLamp.kt` | The `0x600` dash-lamp prototype: `TpmsLampPolicy` (detector state -> off / steady / flash), `RcuStatusFrames` (payloads shaped like the RCU's own, measured), `TpmsLampSlot` (registers it with `PeriodicTransmitter`). Transmits only where the app enables the transmitter; see `CodaConstants.TPMS_LAMP_TX_ON_CAR` |
| `TpmsHost.kt` | Implemented by the host `Application`, so the service can reach the accumulator |
| `TpmsLog.kt` | Logging sink; the host points it at its own logger |

`src/main/AndroidManifest.xml` declares the location permissions, `HIGH_SAMPLING_RATE_SENSORS` (for `HardwareReport`) and `GpsSpeedService`. They are
here, not in the app, so only apps that include this module ask for location.

| Test (`src/test/java/com/reverseit/tpms/`) | Covers |
|---|---|
| `TpmsEpochStoreTest.kt` | The fragment store vs the prototype's `FragmentStore` (phases 5-7: fragments stand alone, `(1)` copies, partial ranking by `gps.fixes`, GPS inheritance in any read order, the two loss properties of R = 0, tombstone undo, precalibration, consolidation by completed rows), legacy migration, immutability, and the bounded read with its full-scan fallback, and a `reject` row still inheriting GPS (36) |
| `TpmsStoreParityTest.kt` | Env-gated (`TPMS_PARITY_DIR`): the store over a real folder, for `android-app/notes/artifacts/tpms_fragment_parity.py` (1, skipped without the env) |
| `DriveRowProducerTest.kt` | Rows, steering centre, catch-up, temperatures vs the B CAN DBC, D CAN selection by anchors and the `reject` field (32) |
| `WheelRatioParityTest.kt` | Exact parity with the Python corpus tool on real captures, under both rule sets: `Filters.LEGACY` (`TPMS_PARITY_JSON`) and `Filters.V24` (`TPMS_PARITY_V24_JSON`, generated with `--v24`). Each skipped unless its variable is set; see `../../notes/artifacts/tpms_ratio_parity.py`. Gradle does not see the variables as inputs, so run `:tpms:cleanTestDebugUnitTest` first or a changed file re-reports the last result |
| `ExtractorProc3ReferenceTest.kt` | Proc 3 (20 Nm on every contrast, 2 %, fast centre, D CAN pinned) against the algorithm session's D CAN references (spec section 8a item 3) for `coda_20260926_155726` and `coda_20260926_181156`, plus F/R and its n identical to v24 on the same frames. Skipped unless `TPMS_CODA_LOGS` is set |
| `Change14BenchTest.kt` | Host timings for `outstanding-changes.md` Change 14: `readFrames`, extract + temperatures, and `GpsRateAccumulator.observe` on real segments (wall time, bytes allocated). Prints a SHA-256 of every output; with `TPMS_BENCH_FP` it writes them to that file on the first run and compares on later runs, so a performance change can be checked for unchanged results. Skipped unless `TPMS_CODA_LOGS` and `TPMS_BENCH` (`default` or segment names) are set (1) |
| `SteeringCentreTest.kt` | `SteeringCentre` against a sorted-list median after every add, at three spreads, and the ends of the 16-bit range (3) |
| `GpsBusSelectionRealLogTest.kt` | The live D CAN rule over every frame of a real two-channel capture: settles once on the extractor's channel and never moves. Skipped unless `TPMS_CODA_LOGS` is set |
| `GpsRateAccumulatorTest.kt` | Pairing, strict/loose separation, lags, grade, plausibility gate, elevation, privacy key list, fix-time conversion and skew guard, D CAN-only pairing (25) |
| `TpmsLampTest.kt` | The `0x600` prototype: the first 12 real RCU frames reproduced byte for byte, counter and flash patterns, the lamp policy, and the slot through `PeriodicTransmitter` (gate, bus resolution, 525 ms, contention with an RCU on the same bus but not the other) (10) |
| `TpmsDetectorParityTest.kt` | The detector vs the prototype's `run()` on the 154-drive corpus epoch, 20 settings cases: events, states, every per-drive number to 1e-9 psi (3). Fixture in `src/test/resources/detector_parity/`, written by `../../notes/artifacts/tpms_detector_parity.py` |
| `TpmsDetectorTest.kt` | Session pooling, file-order window, write-once baseline, STALE suppression, the page's estimate (8) |
| `WheelDecodeTest.kt` | 14-bit wheel count, the stuck-wheel guard, brake pressure with invalid-as-braking (3) |
| `SegmentWatcherTest.kt` | Close detection (1) |

Run: `gradlew.bat -p android-app/CanLoggerApps :tpms:testDebugUnitTest` (JAVA_HOME per
`../../android-tools-reference.md`).
