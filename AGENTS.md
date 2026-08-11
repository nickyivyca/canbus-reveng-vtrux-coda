# Claude Code Project Instructions

## Project Overview
Vehicle-agnostic CAN bus reverse engineering framework. The `canre/` Python package provides parsers and analysis modules; `tools/` has CLI entry points; `projects/` holds per-vehicle data, notes, and DBC files. 


## File Storage Rules

- Per-vehicle notes go in: `./projects/<vehicle>/notes/`
- Primary DBC files go in: `./projects/<vehicle>/` (alongside the vehicle's overview `.md`)
- **Project Data artifacts** (CSVs, JSONs, extracted timeseries, survey outputs, event cluster dumps, utility scripts) go in: `./projects/<vehicle>/notes/artifacts/`
- **Cross-vehicle shared topics** go in: `./notes/<topic>/` — use this for components shared across multiple vehicles (e.g. `./notes/Heater/` for the HV PTC heater used by both Coda and Vtrux). Do NOT duplicate shared findings into per-vehicle notes.
- **Android apps**: Android app development lives in `./android-app/` - this contains both common code shared between the two apps, and the vehicle-specific apps themselves.

| What | Where | Read when... |
|------|-------|-------------|
| Parser API (CANFrame, BaseParser, format detection) | `canre/parsers/parsers.md` | Working with log files or adding a parser |
| Analysis API (survey, bitstats, counters, correlation, diff, timeseries, transitions) | `canre/analysis/analysis.md` | Doing data analysis or understanding output dicts |
| DBC API (builder, skeleton generation, validation) | `canre/dbc/dbc.md` | Building or validating DBC files |
| Utilities (streaming I/O, log merging, session grouping) | `canre/utils/utils.md` | Working with multi-file captures or session discovery |
| CLI tools (survey, analyze_id, compare, can_logger, can_replayer, status_events, etc.) | `tools/tools.md` | Running or modifying any tool |
| Vtrux-specific analysis tools (charge failure analysis, session analysis) | `projects/vtrux/tools/README.md` | Doing Vtrux-specific analysis (charging, fault events, etc.) |
| Vtrux vehicle overview, known signals, DBC status | `projects/vtrux/vtrux.md` | Working on Vtrux |
| Coda vehicle overview, CAN topology, module inventory, DBC status | `projects/coda/coda.md` | Working on Coda |
| Vehicle notes folder | `projects/<vehicle>/notes/` | Looking for detailed notes on a specific topic for a certain vehicle
| Primary Vehicle logs folder | `projects/<vehicle>/logs/` | Looking for a log with a specific role or name
| Secondary Vehicle Logs folder | `../../CANLogs/<vehicle>Logs/` | Looking for a log that was automatically captured and backed up by Android based logger apps
| Cross-vehicle shared topics (e.g. HV PTC heater) | `notes/<topic>/` | Working on hardware shared between Coda and Vtrux |
| Per-machine Python executable (hostname → py command) | `python-executables-reference.md` | Before running any Python — check hostname here first |
| Per-machine external tool paths (Ghidra, JDK, project dirs) | `tools-reference.md` | Setting up Ghidra runners or any external tool script |
| Ghidra environment: modified SuperH4 SLEIGH, archived workspaces, headless scripts, restore script | `ghidra/README.md` | Any Ghidra/decompile work, or bringing Ghidra up on a new machine |

## Development Rules

### Session Startup

#### Check for stale local user folder auto-memory
At the start of each session, check whether anything exists in the local Claude auto-memory folder for this project. The SeaDrive root path varies by machine (e.g. the user profile path differs between computers), so resolve the correct local path before checking: it will be under `~/.claude/projects/<encoded-project-path>/memory/` where the encoded path corresponds to this project's absolute path on the current machine. If files are found there, review them with the user: determine whether the content is still relevant and should be restored into the appropriate project folder, or can be deleted to avoid confusion.

### Session Pause

To pause the session for a fixed duration, use the `session_pause.sh` script at the project root — do NOT chain ScheduleWakeup calls:

```bash
bash session_pause.sh <seconds>
```

Run it with `run_in_background: true`. When it completes you will be notified and can proceed.

### Local Execution
**Maximize local computation**: Use Python scripts (see Python Rules) to process large log files and produce summarized outputs. Never try to read raw multi-MB/GB log files directly into context.


### Python Rules

#### Python Executable

**The first time Python is called in a session**, determine which Python executable to use:

1. Run `hostname` to get the current machine name.
2. Look up the hostname in `./python-executables-reference.md`.
   - **Found**: use the executable listed in the table for this machine. Never deviate from it unless the user explicitly says otherwise.
   - **Not found**: probe for Python ≥3.10 in this order: `py -3.13`, `py -3.12`, `py -3.11`, `py -3.10`, then full paths under common install locations. Pick the highest version found. Confirm the version with `<exe> --version`, then **add a new row** to `python-executables-reference.md` (hostname, executable command, version, any relevant notes like "default python is 3.9" or "python3 opens MS Store"). From then on use that executable for the session.

This applies to all `python` invocations: running tools, executing scripts, and inline `-c` snippets. Never use a bare `python` or `python3` command on Windows without first checking this table — those aliases frequently resolve to the wrong version or trigger the Microsoft Store redirect.

#### Dependencies
- Python 3.10+
- `cantools` (`pip install cantools`)
- `python-can` (`pip install python-can`) — for `can_logger.py` and `can_replayer.py`
- All analysis is pure Python stdlib

Any additional dependencies specific to a tool or project must be captured in a `requirements.txt` files in the same folder as its relevant tool.

#### Code Style
- **Never use non-ASCII Unicode characters in code strings or any value that will be passed through Python's stdout/print on Windows.** The Windows console (cp1252) silently rejects characters like `→`, `≈`, `×`, `≥`, `≤`, `±`, etc., causing `UnicodeEncodeError`. Use ASCII alternatives: `->` for arrows, `~=` or `approx` for approximately-equal, `x` or `*` for multiply, `>=`/`<=` for comparisons, `+/-` for plus-minus. This applies to string literals passed to `print()`, written to files opened without explicit `encoding=`, or used in f-strings.

#### Prefer existing tools and libraries over custom scripts
The `tools/` and `canre/` folders have capable CLI tools and libraries that handle most analysis tasks, and Vehicle-specific tools live in `projects/<vehicle>/tools/` — check there first for vehicle-specific tasks (e.g. charge failure analysis for Vtrux). **Always try the existing tools first.** Run them on the relevant logs, examine the output, and only write a new script if the tools genuinely cannot answer the question, or if using the libraries in a way that does not exist in a tool yet. Do NOT write large bespoke analysis scripts when piping together existing tool runs would suffice. A 20-line script that post-processes tool output is almost always better than a 500-line standalone analyzer.

### Data Artifacts
Generated data files (CSVs, JSONs, survey outputs, event cluster text dumps, one-off scripts) MUST go in an artifacts folder in the relevant location (`./projects/<vehicle>/notes/artifacts/`, `tools/artifacts/`, etc), NOT loose in `notes/` and NOT to the system temp directory (`%TEMP%`, `/tmp`, `tempfile.mkstemp()`, etc.). The `notes/` directory should contain only `.md` analysis write-ups, `README.md`, `plans/`, and `artifacts/`. When a tool writes output to a file, always direct it to the relevant `artifacts/` subfolder.

#### Inline Execution vs Scratchpad Scripts

Use a scratchpad script in the relevant `artifacts/` folder for any analysis that is multi-step, reuses data across phases, or would be useful to re-run. Scratchpad scripts should be named relevant to the relevant investigation (e.g. `cell_voltage_spread.py`, `charge_failure_precursor.py`) and not just `scratchpad.py`. Scratchpads are per-investigation, not permanent fixtures.

Inline execution is appropriate for simple one-off lookups (e.g. reading a single signal value, checking a frame count). Inline execution does not require approval when built correctly — but can trigger approval if built wrong (see rules below), which is to be avoided. If an inline execution is denied by the user, it is likely not because the execution was going to do the wrong thing, but because the approval was required, and the response should be:
1. Write a note in the below list about what aspect of the inline execution was the reason approval was required, such that it can be avoided in the future
2. Proceed with either writing the script to a scratchpad or adjusting the inline call based on the rules

##### File Discovery Commands

**Use Bash `find`/`ls` over PowerShell for file searches.** Bash read-only commands are auto-allowed and never require approval. The PowerShell tool (`Get-ChildItem`, `Where-Object`) always requires approval even for read-only operations.

**Never run `find` rooted at the filesystem or user-profile root** (`find /`, `find C:/Users/<user>/`, `find ~`, etc.). It scans SeaDrive caches, OneDrive, `AppData`, `Program Files`, and the Windows folder — slow, wasteful, and reaches outside the project. Scope every `find` to the project folder by default. If you genuinely need to search a location outside the project (e.g. a per-machine deploy folder), first check the relevant reference doc (`android-app/android-tools-reference.md`, `tools-reference.md`, `python-executables-reference.md`); if it's not documented, **ask the user** rather than searching. When a `find` outside the project is unavoidable, target a single named directory with `-maxdepth 2` and prune heavy folders.

##### Inline Python Execution Rules
1. No `#` comments allowed — the `#` character can trigger a quote-tracking desync in the permission flow, causing the tool call to be flagged for approval. Comments are also unnecessary in ephemeral scripts that are never stored or read. (Comments are still welcome in scratchpads written to artifacts)
2. **Never use `cd` for files within the project folder.** The Bash tool's persistent working directory is already the project root — use paths relative to the project root or absolute paths. `cd` is only acceptable when acting on files genuinely outside the project folder. Combining `cd` with `&&` and output redirection triggers a manual approval prompt even for harmless commands:

   ```bash
   # Good — run directly from project root
   py -3.12 tools/survey.py "projects/vtrux/logs/foo.log" > "projects/vtrux/notes/artifacts/out.txt" 2>&1

   # Bad — triggers approval prompt
   cd "C:\...\reverse-it" && py -3.12 tools/survey.py ... > out.txt 2>&1
   ```

##### Scratchpad Scripts Rules

**Scratchpad sys.path bootstrap (required):** Every scratchpad must begin with `sys.path.insert(0, ".")` so `canre` is importable. Scripts are always invoked via the Bash tool from the project root, so `"."` reliably resolves to the project root where `canre/` lives.

```python
import sys
sys.path.insert(0, ".")
```

Then import with `from canre.parsers import parse_file` — there is no `canre.parsers.parsers` submodule and no `parse_log` function.

**Scratchpad location:** Scratchpad files MUST live in the `artifacts/` folder nearest to the work being done (e.g. `./projects/<vehicle>/notes/artifacts/scratchpad.py`, `./tools/artifacts/scratchpad.py`, `./android/artifacts/scratchpad.py`, etc.). Never create one in a root folder or anywhere outside an `artifacts/` directory.

**Scratchpad naming and lifecycle:** Name the file after what is being investigated  rather than using a generic `scratchpad.py`. At the start of a session, if a `scratchpad.py` or other exploratory script exists and is not relevant to the current work, either delete it or leave it alone — do NOT reuse it for unrelated analysis. Only reuse an existing scratchpad file if continuing the same investigation it was written for.

**Scratchpad strategy:** For complex investigations, write scratchpads with a 'phase' architecture, such that when new phases are added, old phases can be disabled or run again, depending on if they need to feed data directly into the next phase. 



## Documentation

### Maintaining Reference Docs
**File listing documentation:** Every directory that contains project files **must have an `.md` file describing its contents** — either a dedicated `README.md` or an overview file like `coda.md` (which may contain more than just a file map). A new session should be able to understand what a folder contains and how its files relate by reading that one `.md` file, without having to open individual files. When you create a new directory or move files between directories, update (or create) the relevant `.md` file. Parent directories should reference their children's `.md` files in a file layout section so the documentation chain is navigable top-down.
**Timestamps:** In the `./tools/` and `./canre` folders, each md file contains a timestamp for each file. This must be updated each time a tool or library file is updated.

### Use of Memory

Memory MUST be saved in the project directory (this folder), NOT in the local user `~/.claude/` folder. This includes Claude Code's built-in auto-memory system, which writes to `~/.claude/projects/.../memory/` — **do not write to it**. This project is on a SeaDrive remote drive that syncs across multiple computers. Anything saved to the local user profile will be lost when switching machines.

Memories can be written to `./.claude/memory`, but this may **only** be used while working within a step of a plan. At the conclusion of each plan step, when notes are written out, relevant memory **must** be either moved into the relevant notes file or deleted, such that no stale information is left in memory.

### Plans and Plan Files

#### Plan Files — NEVER use `~/.claude/plans/`
Plan files MUST be stored inside this repository folder, NOT in `~/.claude/plans/` (local user folder) or any other local user folder. The local user profile does not sync across machines and plans stored there will be lost. Plan files are stored in the relevant project's plans folder (`./projects/<vehicle>/notes/plans/`, `tools/plans/`, etc). When using /plan, the first step (step 0) of a /plan based plan must be to write the plan to the relevant project local plans folder.

#### Plan Step Gate Rule — Stop and Review Before Advancing

**After completing each step of a plan, STOP and present findings to the user before starting the next step.** Do not automatically chain steps together. This review checkpoint serves two purposes:

1. **Verification:** The user confirms the findings and any assumptions are correct and the interpretation makes sense before analysis builds on them.
2. **Writing to notes:** The completed phase's findings are written into the notes file at this checkpoint — not at the end of all work. This ensures findings are recorded incrementally, the plan file stays up-to-date, and in case of unexpected shutdown, reduces data loss.

**How to implement the gate:**
- Ask the user: "Ready to proceed to Step N?" or "Any corrections before I continue?"
- Only after explicit user approval, do the following:
  - write the phase findings into the relevant notes file
  - clear out any relevant memory (per above memory notes, memory must be cleared between each plan step, so that memory does not become stale or conflicting)
  - update the plan file to note that that step of the plan has been completed

This rule applies to any multi-phase plan (investigation, refactor, feature implementation, etc.). Do NOT interpret "implement the plan" as permission to run all phases without stopping.

### Notes Rules

**No unreviewed conclusions or assumptions are to be inserted when writing to files**:
Before writing any interpretation, hypothesis, or signal-role assignment into a file — including inline table cells, DBC comments, and notes — present it to the user in the conversation first and get explicit approval. Hypotheses and tentative claims *are* allowed in files, but they must be framed as hypotheses and the user must have seen and approved them as such before they are written. **The file write is the gate; the conversation is the proposal space.** If a file write would include any claim not already reviewed in the current conversation, stop, surface the claim, and wait for explicit approval before proceeding. 

**Examples of what requires approval before writing:**
- Expanding `gfd` to "ground fault detect" in a signal name or comment (hypothesis: `gfd` = ground fault detector)
- Noting `bcm_fgd` as "fuel gauge delta" in a table cell (hypothesis: `fgd` = fuel gauge delta) — the specific case that prompted this rule
- Any signal role, unit, or interpretation that was not explicitly discussed and approved in the current conversation

## Data Analysis Rules

### Data Sources

Two sources are published with this repo; a third (a local InfluxDB holding
the decoded corpus) is part of the maintainer's setup only.

| Source | Authoritative for |
|--------|-------------------|
| CAN logs (`projects/<vehicle>/logs/`, `../../CANLogs/<vehicle>Logs/`) | raw frames, timing, undecoded bytes, IDs no DBC defines |
| DBC files (`projects/<vehicle>/*.dbc`) | signal encoding — scale, offset, bit layout, endianness |
| InfluxDB (local, maintainer setup) | the whole corpus decoded against the DBCs |

**Prefer the decoded corpus for any question answerable from DBC-encoded
signals** rather than reparsing gigabytes of logs. Parse raw logs when you need
undecoded bytes, frame timing, IDs absent from every DBC, or a signal whose
encoding you are still working out.

**Source-of-truth order:** DBC > vehicle overview (`<Vehicle>.md`) > notes files. If the DBC
and a notes file disagree on scaling or encoding, **do not guess — stop and prompt the
user**, stating what each says and which signal is in conflict.

**Silent-failure invariants** — violating any of these produces plausible, wrong answers:

- **Never identify a bus by its channel number.** It varies per capture with dongle
  insertion order. Identify by message content using the vehicle's anchor IDs.
- **`_M{N}` numbers are separate capture sessions, NOT different buses of one session.**
- **BUSMASTER data-line timestamps are 10 kHz ticks (0.1 ms), not ms** — but the
  `START DATE AND TIME` header's sub-second field *is* ms. Confusing them is a 10x error.
- **InfluxDB point counts are not frame counts.** The write policy is on-change plus a 1 s
  heartbeat: values forward-fill exactly, but rate and inter-frame timing are not preserved.
  Use raw logs for anything rate-dependent.
- **Only confirmed signals belong in a DBC** as `SG_` entries; hypotheses get `BO_` stubs
  and `CM_` comments only.
- **Decode with `cantools`, never hand-rolled bit extraction**, for any signal in a DBC.

### Correlation Methodology

#### Full-log vs windowed correlation

Pearson r on the full log is a powerful first-pass tool, but it has a critical blind spot: multi-byte signals where the MSB byte occasionally steps by ±1 produce sudden 256-count jumps in the reconstructed value. These jumps dwarf the actual analog variation and collapse the full-log r to near zero, hiding a true high-correlation signal. Discovered 2026-03-02 on 0x430 B0-B1 BE (r≈0.99 within stable windows; r≈0 full-log due to B0 stepping between 12 and 13).

**Mitigation:** whenever running a correlation sweep, also run the same sweep on short time windows where the MSB is stable (e.g. 30-120 second slices with no B-step events). Running both together is low-cost and catches what either alone misses. Delta correlation (frame-to-frame differences) is an alternative that is inherently immune to MSB steps and can be run as a third pass if windowed correlation still misses candidates.

#### Scan completeness and byte-pair decomposition

**A more thorough scan that takes longer to run is more time-efficient than a fast scan that produces misleading or incomplete results.** A false negative sends the investigation down the wrong path and requires re-running the scan anyway, at the cost of all the time spent on wrong conclusions in between. Run the complete set of signal widths the first time.

A correlation scan is only valid if it tests all of the following:

- **8-bit (byte):** each byte independently
- **16-bit LE and BE:** all adjacent byte pairs in both endiannesses
- **12-bit byte-aligned:** `(B0[3:0]<<8)|B1` (Motorola) and `B0|(B1[3:0]<<8)` (Intel) — a 12-bit value in two bytes where the upper byte contributes only 4 bits
- **12-bit nibble-split:** two values packed into three bytes — `signal_A = (B0<<4)|(B1>>4)`, `signal_B = ((B1&0x0F)<<8)|B2`. The middle byte is split between both signals; per-byte and 16-bit pair scans are completely blind to this layout. Confirmed on Vtrux A123 BMS (0x420, 0x440) but the pattern is not hardware-specific.

Conversely, when a byte scan returns a signal with only a few (3-6) unique coarse values that partially correlates with a reference, do not conclude it is a low-resolution stepped setpoint — suspect it is the nibble carrying the MSBs of a 12-bit nibble-split value and test the full reconstruction. Discovered 2026-03-28: bcm_dis_max/bcm_chg_max and bcm_vbus_pos/bcm_vbus_neg were all missed by byte/pair scans across five investigation phases. See `projects/vtrux/notes/current-limits-investigation.md` Phase 6.

### Graphing

**Generated PNG graphs are for human reading only.** Do not use the Read tool to load and interpret plot images. If analysis conclusions are needed, process the raw data directly in a scratchpad script and print the relevant numbers.
