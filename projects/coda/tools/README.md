# projects/coda/tools/

> **Staleness check:** Each section shows a `Source last modified` timestamp. If the `.py` file's mtime is newer than the timestamp shown here, re-read the source before relying on this documentation.

Coda-specific CLI tools. These scripts use the `canre` framework or operate directly on Coda hardware/software artifacts (LabVIEW VIs, CODACAN display).

---

## cowork_replay.py
*Source last modified: 2026-02-21 14:44:38*

Cowork-driven CAN replay tool for CODACAN signal discovery. Reuses hardware detection from `tools/can_replayer.py`. Designed to be run alongside `codacan_capture.py` for autonomous mapping of CODACAN display fields to CAN IDs, byte positions, and scalings.

**Usage:**
```
py -3.12 projects/coda/tools/cowork_replay.py <mode> <logfile> [options]

Modes:
  baseline     Replay entire log faithfully. All CODACAN fields populate.
  drop-id      Replay log minus specified ID(s). See what fields disappear.
  solo-id      Replay ONLY specified ID(s). See what fields appear.
  sweep-byte   Replay background traffic; sweep one byte of target ID.
  inject       Send a single crafted frame on repeat (no logfile needed).

Common options:
  --bitrate, -b   CAN bitrate in bps (default: 500000)
  --brands        Comma-separated dongle brands (e.g. ixxat)
  --speed, -s     Replay speed multiplier (default: 1.0, 0=no delay)
  --dry-run       Print summary without sending frames
  --no-wait       Skip the "Press Enter to start" prompt
  --state-file    Path to state file for coordination (default: cowork_state.json)

Mode-specific options:
  --target, -t    CAN ID(s) for drop-id/solo-id/sweep-byte (hex, comma-separated)
  --loop, -l      Loop replay indefinitely (baseline/drop-id/solo-id)
  --byte          Byte index or range for sweep-byte (e.g. 2 or 2-3)
  --dwell         Seconds per sweep step (default: 3.0)
  --step          Sweep value increment (default: 1)
  --id            CAN ID for inject mode
  --data, -d      Frame data hex for inject (e.g. "00 FF 80 12 00 00 00 00")
  --interval      Inject interval in seconds (default: 0.1)
```

**Examples:**
```bash
py -3.12 projects/coda/tools/cowork_replay.py baseline capture.log --brands ixxat --loop
py -3.12 projects/coda/tools/cowork_replay.py drop-id capture.log --target 0x275 --brands ixxat --loop
py -3.12 projects/coda/tools/cowork_replay.py solo-id capture.log --target 0x1D5,0x48A --brands ixxat --loop
py -3.12 projects/coda/tools/cowork_replay.py sweep-byte capture.log --target 0x275 --byte 2 --step 16 --brands ixxat
py -3.12 projects/coda/tools/cowork_replay.py baseline capture.log --dry-run
```

**State file:** Writes `cowork_state.json` continuously with current mode, target ID, sweep value, and step number. `codacan_capture.py watch` polls this to coordinate screenshots with the experiment state.

**Protocol document:** See `notes/plans/cowork-codacan-protocol.md` for the full 7-phase workflow.

---

## codacan_capture.py
*Source last modified: 2026-02-21*

Python-native screenshot capture and OCR tool for CODACAN signal observation. Works in conjunction with `cowork_replay.py`.

**Sub-commands:**

| Sub-command | Purpose | Requires CODACAN live? |
|---|---|---|
| `init-layout` | Auto-detect value boxes from reference screenshots, build `ui_layout.json` | No (offline) |
| `calibrate` | Interactive live fine-tuning of coordinates | Yes |
| `snapshot` | One-shot capture of all fields across tabs, write JSON | Yes |
| `watch` | Continuous capture synced with `cowork_state.json` during sweep-byte | Yes |

**Usage:**
```
py -3.12 projects/coda/tools/codacan_capture.py init-layout
py -3.12 projects/coda/tools/codacan_capture.py init-layout --screenshots-dir "logs/codacan-screenshots"
py -3.12 projects/coda/tools/codacan_capture.py calibrate
py -3.12 projects/coda/tools/codacan_capture.py snapshot
py -3.12 projects/coda/tools/codacan_capture.py snapshot --tabs BMS,DCDC --output results/baseline.json
py -3.12 projects/coda/tools/codacan_capture.py watch --tabs BMS
py -3.12 projects/coda/tools/codacan_capture.py watch --tabs BMS --state-file cowork_state.json --results-dir notes/artifacts/cowork-results
```

**Dependencies:**
- `Pillow` — required for all sub-commands: `pip install Pillow`
- `pyautogui` — required for calibrate/snapshot/watch: `pip install pyautogui`
- OCR (snapshot/watch): `pip install pytesseract` (+ Tesseract binary) OR `pip install easyocr`

**Reference screenshots:** `logs/codacan-screenshots/2026-02-21 (9-17).png` (one per tab).

**Protocol document:** See `notes/plans/cowork-codacan-protocol.md` for the full 7-phase workflow.

---

## codacan_autosweep.py
*Source last modified: 2026-07-24*

Autonomous orchestrator that runs a whole queue of CODACAN replay experiments end-to-end with **no second terminal and no human in the loop** — it replaces the old two-terminal workflow (`cowork_replay.py sweep-byte` + `codacan_capture.py watch`). Per experiment it spawns `cowork_replay.py` as a background subprocess (it owns the CAN TX and writes `cowork_state.json`) and does the screen capture in-process by importing `codacan_capture`'s navigate/screenshot/OCR helpers, so exactly one process touches the GUI. It launches/restarts CODACAN.exe and clicks **Connect to CAN** automatically (CODACAN opens to a splash screen that must be dismissed before it reads the bus).

**Machine/deps:** bench machine only (the bench laptop). Uses `py -3.11` (32-bit) — it has python-can + Kvaser canlib **and** Pillow/pyautogui/pytesseract. TX dongle default is **Kvaser** (`--brands kvaser` baked in). CODACAN must be able to RX via its NI side. pyautogui takes over the mouse/keyboard for the whole run.

**Usage:**
```
py -3.11 projects/coda/tools/codacan_autosweep.py check  [--queue Q.json] [--launch-codacan]
py -3.11 projects/coda/tools/codacan_autosweep.py run --queue Q.json [--dry-run] [--only names] [--restart each|first|never]

  check        Validate preconditions (Kvaser TX, CODACAN window, layout, queue); sends no frames.
  run          Execute a queue JSON. --dry-run validates + prints the plan with no hardware.
  --restart    CODACAN lifecycle: each (relaunch+reconnect per experiment, default) | first | never.
  --only       Comma-separated experiment names to run a subset.
```

**Queue format:** JSON list (or `{"experiments":[...]}`) of experiment objects (`mode` = sweep-byte | inject | solo-id | drop-id | baseline; plus `tabs`, `log`, `target`, `byte`, `step`, `id`, `data`, `start_time`/`end_time`, etc.). See the module docstring for the full field list. The full verification queue is generated by `notes/artifacts/cowork-results/build_sweep_queue.py` -> `sweep_queue_full.json`; `sweep_queue_test.json` is a 2-experiment validation queue. Worklist rationale: `notes/codacan-replay-verification-queue.md`.

**Capture/TX sync:** sweep dwell is auto-bumped to `n_tabs * 3s + margin` so a step is never overwritten before it is OCR'd. Outputs land per-experiment under `notes/artifacts/cowork-results/autosweep/<name>/` (per-step JSON + merged `sweep_results.json` for sweeps, `snapshot_<name>.json` for the others), plus an `autosweep_run.log` summary.

---

## labview_xml_extract.py
*Source last modified: 2026-02-18 10:30:03*

Extracts CAN signal definitions from decompiled LabVIEW VI XML files by parsing the VCTP (VI Consolidated Data Types) section. Resolves cluster hierarchies, detects embedded CAN IDs in cluster names, and merges multi-file results with deduplication.

**Usage:**
```
py -3.12 projects/coda/tools/labview_xml_extract.py <xml_file> [<xml_file2> ...] [options]
py -3.12 projects/coda/tools/labview_xml_extract.py --batch <directory> [options]

  files            One or more decompiled LabVIEW .xml files
  --batch DIR      Scan directory recursively for .xml files
  --output, -o     Write JSON output to file
  --quiet, -q      Suppress stdout summary
  --flat           Include flat signal list in JSON
```

**Multi-file merge:** Clusters merged by name; version with detected CAN ID preferred.

**Notes:** Skips `_FPHb` and `_BDHb` sidecar files in batch mode. Max recursion depth 10 with cycle detection. Use `--quiet --output FILE` to avoid CP1252 encoding errors on Windows (LabVIEW uses the infinity symbol as degree symbol).

---

## dbc_skeleton_labview.py
*Source last modified: 2026-02-18 10:48:24*

Generates skeleton DBC files for B CAN and D CAN from a LabVIEW signal inventory JSON (produced by `labview_xml_extract.py`). Maps LabVIEW types to DBC signal stubs, assigns clusters to correct bus by module, and uses embedded hex IDs from cluster names or a hardcoded lookup.

**Usage:**
```
py -3.12 projects/coda/tools/dbc_skeleton_labview.py <signals.json> --b-can <output_b.dbc> --d-can <output_d.dbc>

  signals.json     Merged signal inventory JSON
  --b-can          Required. Output B CAN skeleton DBC
  --d-can          Required. Output D CAN skeleton DBC
```

**Bus assignment:** DLCM, TCM, ESC, EPS, MCM -> D CAN; everything else -> B CAN.

**Notes:** Clusters without a detectable CAN ID get placeholder IDs starting at 0x1FFF. DLC always 8. Signal bit widths guessed from LabVIEW types.

---

## vicd_disasm.py
*Source last modified: 2026-02-18 11:02:47*

Disassembles LabVIEW VICD (VI Compiled Data) code binary files using x86 32-bit disassembly. Identifies byte loads, bitfield extraction, float scale/offset operations, and CAN ID dispatch comparisons.

**Usage:**
```
py -3.12 projects/coda/tools/vicd_disasm.py <binary> [options]

  binary           Path to a _VICD_code.bin file
  --start OFFSET   Start offset in hex or decimal (default: 0)
  --length N       Bytes to disassemble (default: 0x200)
  --full           Disassemble all detected code regions
  --scan-patterns  Scan for CAN decode patterns instead of disassembling
```

**Modes:**
- **Default / --full:** Annotated disassembly with byte loads, masks, shifts, float ops, comparisons highlighted.
- **--scan-patterns:** Surveys for CAN decode idioms: byte/word loads, float ops, bitfield ops, hex comparisons, 64-bit float constants.

**Notes:** Requires `capstone` (`pip install capstone`). Expects x86 32-bit code. Code regions auto-detected by scanning for runs of >16 zero bytes.

---

## update_skeleton_dbcs.py
*Source last modified: 2026-02-18 16:28:23*

One-off script that patches the Coda B CAN and D CAN skeleton DBCs with message IDs from VICD disassembly. Remaps placeholder IDs to real CAN IDs and inserts new message definitions with signal stubs and provenance comments.

**Usage:**
```
py -3.12 projects/coda/tools/update_skeleton_dbcs.py
```

No arguments. Hardcoded paths: `projects/coda/CODA-B-CAN-skeleton.dbc` and `projects/coda/CODA-D-CAN-skeleton.dbc`.

**Note:** One-shot migration script, not intended for repeated use. All remaps and new messages are constants in the source.
