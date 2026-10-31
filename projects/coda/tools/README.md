# projects/coda/tools/

> **Staleness check:** Each section shows a `Source last modified` timestamp. If the `.py` file's mtime is newer than the timestamp shown here, re-read the source before relying on this documentation.

Coda-specific CLI tools. These scripts use the `canre` framework or operate directly on Coda hardware/software artifacts (LabVIEW VIs, CODACAN display).

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `cell-display/` (internal-only) | Third-party vendor tool `Cell_Voltage_Display.exe` (PyInstaller/Python 3.7/Tkinter over Kvaser `canlib32`), plus the owner's annotated screenshots and `pack bussing layout.png` — the drawing the corrected cell mapping was derived from. Reverse engineered 2026-09-06; see `../notes/pack-physical-layout.md`. |
| `codasim/` | **The executable DLCM model** and its coupling to the driveline plant: integer-exact transliteration of the 10 ms torque task (including the torque-bound chain, computed by default with 0x1C0 standing in for the unlogged M-CAN 0x20B) and its ECM2 monitor (a predicted reset halts the run), log replay with declared timing and input provenance, and the plant/sensor/actuator side written by the lash-model session. Superseded the old model modules (`notes/dlcm/artifacts/{torque_path_sim,dlcm_torque_filter,creep_damper_blocks,closed_loop_sim,closed_loop_step3,lash_plant,...}.py`), deleted at plan step 7 (2026-10-10). See `codasim/README.md`. |
| `hvacsim/` | **The executable HVAC model** (started 2026-10-26): S12X integer semantics, the packed firmware image read by local address and page, the symbol table and RAM, built on codasim's rules. Modules are added one per firmware function as the HVAC is decompiled. See `hvacsim/README.md` and `../notes/hvac/coda-hvac-decompile-notes.md`. |
| `cell_viewer/` (internal-only here) | Our rebuild of that tool on the `canre`/`python-can` stack, using the corrected cell-to-physical-position mapping. Log replay, `--scan`, PNG rendering and the Tkinter display work; live capture is untested against hardware. The published copy is `../coda-diagnostics/cell_viewer/` in the `coda-diagnostics` submodule; see its `README.md`. |
| `flash_sim/` | **The DLCM reflash stack and its simulators**: UDS / ISO-TP / bus layers (`uds.py`, `isotp.py`, `bus.py`, `busload.py`, `seedkey.py`), the tester side `omitec_sim.py` (used by `flash_cal.py` for the real flash) and the ECU side `gateway_sim.py`, over a host-local virtual CAN bus (`hop_limit=0`, asserted). Moved here from `notes/dlcm/flash_sim/` 2026-10-17 so it can grow to other modules; the images and the on-car reference it reads stay in `notes/dlcm/`. See `flash_sim/README.md`. |

---

## cowork_replay.py
*Source last modified: 2026-02-21 14:44:38*

Cowork-driven CAN replay tool for CODACAN signal discovery. Carries its own copy of the pre-migration `can_replayer` hardware detection and reads logs through `canre.parsers`, so it replays BUSMASTER captures directly. Designed to be run alongside `codacan_capture.py` for autonomous mapping of CODACAN display fields to CAN IDs, byte positions, and scalings.

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

---

## flash_cal.py
*Source last modified: 2026-10-28 20:17:53*

Flash a named DLCM calibration to the Coda: the human-facing front end of the flash tooling (user 2026-10-16). Each name is one complete CAL image with its md5 and a status (`proven` = has run on this car, `candidate` = never has). The headline names and the candidates' criteria are in `notes/dlcm/candidate-criteria.md`. The UDS flash is `flash_sim/omitec_sim.py`'s `OmitecSim`; this script only picks the image and the settings.

- **CAL only.** PROG is never erased or written.
- **Whole image.** The patch set is the image's diff from the stock base. Bytes the car has and the image does not are put back on purpose; the script reports how many bytes change against the on-car reference (`omitec_sim.CAL_ON_CAR`).
- **Checks before anything is sent:** the md5 must match; a `candidate` is refused without `--allow-candidate`; you type the name back to confirm (skip with `--yes`).
- **Defaults are the real-flash settings** (`notes/plans/dlcm_next_incar_session.md` section 2): block delay 217 ms, frame gap 1.1 ms, no ignition poll, no startup delay, SecurityAccess level 0x01.
- **`--transport auto` (default)** uses the one CAN interface present, and refuses, listing them, if there are none or several. Name a brand to choose one.
- **Where the images are:** the candidates in `notes/dlcm/cal_images/` (by headline name), stock `notes/dlcm/coda_dlcm_cal.bin`, C4c `notes/dlcm/artifacts/cal_as_flashed_20260925_envelope_c4c.bin`.
- `c4c-onepedal-156nm` stays on the list only while C4c is on the car; it comes off when C4c is retired.
- After a flash, update `omitec_sim.CAL_ON_CAR` and the lineage in `notes/dlcm/dlcm-cal-flash-campaign.md`.

**Usage:**
```
py -3.12 projects/coda/tools/flash_cal.py --list
py -3.12 projects/coda/tools/flash_cal.py c4c-onepedal-156nm
py -3.12 projects/coda/tools/flash_cal.py 0.13g-brakeblend-156nm --allow-candidate

Options:
  NAME               stock | c4c-onepedal-156nm | illegal-onepedal-156nm | 0.13g-brakeblend-156nm
  --list             list the calibrations (status, md5, bytes vs stock and vs the car) and exit
  --allow-candidate  allow an image that has never run on the car
  --yes              skip the type-the-name confirmation
  --transport        auto (default: the single interface present) | virtual | gs_usb | ixxat | kvaser | pcan | socketcan
  --block-delay-ms   default 217;  --tx-stmin-ms  default 1.1
```

**Test against the simulated gateway** (localhost virtual bus):
```
py -3.12 projects/coda/tools/flash_sim/gateway_sim.py --time-scale 0.02 --verify-bins
py -3.12 projects/coda/tools/flash_cal.py stock --transport virtual --yes
```

---

## hvac_packheat_offset.py
*Source last modified: 2026-10-30 16:39:31*

Read or set the HVAC pack-heat offset live over UDS: calibration byte `0x24C9`, byte 1 of DID `E1AD` (`notes/hvac/coda-hvac-decompile-notes.md` section 8, user request 2026-10-26). Per `notes/hvac/coda-hvac-decompile-notes.md` section 7.6 it is added, in quarter-degrees, to AllowedCellTempMin when the HVAC decides how far to heat the pack. The byte is RAM: a write lasts until the HVAC resets or sleeps. **Not yet run on the car**; running it is the user's call. It does not flash anything.

- **Exchange** (tester `0x750` -> HVAC `0x758`, single frames, no session, no SecurityAccess): `22 E1AC` and `22 E1AD`, then `2E E1AD` with only byte 1 changed, then `22 E1AD` to read it back.
- **Refuses to write** unless `E1AC` reads `9C 09 0A 01` and `E1AD` bytes 0/2/3 read `00 .. 14 14` (the 2026-10-25 flash image's start-up values: a different firmware would have a different E1xx layout). It also refuses on a negative response, a malformed response or no response. It asks you to type `write` first (skip with `--yes`).
- **Scope guard:** only `22 E1AC`, `22 E1AD` and a 4-byte `2E E1AD` can be sent; anything else raises before the bus.
- Uses `flash_sim`'s bus factory and `IsoTpEndpoint`, and finds the dongle as `flash_cal.py` does (`--transport auto`: exactly one interface present). OBD port; the gateway routes `0x750`/`0x758`.

**Usage:**
```
py -3.12 projects/coda/tools/hvac_packheat_offset.py --read
py -3.12 projects/coda/tools/hvac_packheat_offset.py --offset-c 5
py -3.12 projects/coda/tools/hvac_packheat_offset.py --restore
py -3.12 projects/coda/tools/hvac_packheat_offset.py --offset-c 5 --dry-run

Options:
  --read | --offset-c DEGC | --raw N | --restore   (one required; DEGC a multiple of 0.25, -32..+31.75)
  --dry-run          print the frames; open no bus
  --yes              skip the confirmation
  --timeout          per-request timeout, s (default 1.0)
  --transport        auto (default) | virtual | gs_usb | ixxat | kvaser | pcan | socketcan
```

## test_hvac_packheat_offset.py
*Source last modified: 2026-10-30 16:39:31*

Tests for the above, against a fake HVAC on an in-process python-can `virtual` bus (no network). The fake follows the firmware's `22`/`2E` rules as read from the listing, and its RAM comes from the flash image's copy-down (`hvacsim.startup`), so the script's expected values are checked against the image. Covers frame building, the scope guard, write and read back, the frames on the bus equal to the dry run's, `0x7F` negative responses to read and to write, `0x78` response pending, no answer, another firmware's fingerprint, read-only/already-set/declined, and restore.

```
python3.13 projects/coda/tools/test_hvac_packheat_offset.py
```
