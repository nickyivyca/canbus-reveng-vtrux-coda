# tools/

Scripts that generate or check this repo's committed test resources against a reference outside
it. Moved here from reverse-it's `android-app/notes/artifacts/` on 2026-11-03, as a reference for
how the `:tpms` port is held to its Python prototype.

All three run from the reverse-it root, because they import the TPMS prototype and corpus tools
from `$REVERSE_IT_DIR/projects/coda/notes/artifacts/` and read the Coda logs from `CANLogs`.
They find this clone from their own location.

```bash
cd "$REVERSE_IT_DIR" && <python> <clone>/tools/<script>.py ...
```

| Script | Feeds | What it does |
|---|---|---|
| `tpms_detector_parity.py` | `TpmsDetectorParityTest` (runs on every build) | Replays the prototype's `run()` over its corpus epoch file under a grid of settings, and writes `CanLoggerApps/tpms/src/test/resources/detector_parity/` (`epoch.jsonl`, `expected.json`). Re-run after the corpus or the prototype changes; it takes the prototype's current epoch file, so the fixture changes with it |
| `tpms_ratio_parity.py` | `WheelRatioParityTest` (env-gated: `TPMS_PARITY_JSON`, `TPMS_PARITY_V24_JSON`) | Runs the Python corpus tool's `extract_one` on real multi-segment sessions and writes its results to a JSON the test compares against. Needs `CC_SCRATCH` and `grep` |
| `tpms_fragment_parity.py` | `TpmsStoreParityTest` (env-gated: `TPMS_PARITY_DIR`) | Runs the app's fragment store and the prototype's over the same copy of the live store, through Gradle, and compares what each reads and writes. Needs `JAVA_HOME` and `ANDROID_HOME`; works in the system temp folder |
