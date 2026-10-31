# SavvyCAN Graphing Workflow

## Overview

`make_graph.py` generates `.gdf` (SavvyCAN Graph Definition File) files from DBC signals,
replacing the slow per-session GUI workflow. Load the output via SavvyCAN right-click →
"Load graph definitions from file".

See `tools.md` for full `make_graph.py` CLI reference.

---

## Confirmed .gdf Format (Corrected)

23 comma-separated fields per line. **Field 5 is signed/unsigned, NOT endianness.**
Endianness is encoded in the sign of the start bit.

```
Z,{id_hex},ffffffff,{start_bit},{data_len},{signed},{bias},{scale},{stride},-1,{R},{G},{B},{label},128,128,128,0,N,0,{line_width},{msg_name},{signal_label}
```

| Field | Name | Correct interpretation |
|-------|------|----------------------|
| 3 | start_bit | **Positive** = LE (Intel LSB position). **Negative** = BE (= -(Motorola MSB position)) |
| 5 | signed | `Y` = signed, `N` = unsigned. **NOT endianness.** |

**Evidence:**
- SavvyCAN export of `GeneratorRPM` (`48|8@1+` = LE unsigned) → `start=48, N`. My tool had
  `Y` (treated as LE flag), SavvyCAN had `N` — signal was overflowing to negative because
  `Y` caused SavvyCAN to treat the uint8 as signed.
- `cell graph (1).gdf` BE signals: `start=-7` and `start=-23` = `-(cantools Motorola start)`.
- `chargegraph2.gdf` LE signed signals (hvBatteryCurrent): `Y`.

**Previous incorrect belief** (from original plan): field 5 = Y/LE, N/BE. Wrong.

---

## make_graph.py — Key Implementation Notes

### Multi-DBC support
`--dbc` accepts multiple paths; searched in order, first match wins. Use `--append` to
add signals across multiple tool runs — color cycling continues from the last signal
already in the file (reads existing file to count lines).

### Duplicate message names
Some DBCs (GMLAN) have duplicate message names. Use `0xABC.Signal_Name` syntax to look
up by frame ID instead of name. Example: `0x3E9.Vehicle_Speed_Average_Driven`.

### Extended CAN IDs
DBC files that store 29-bit IDs without the `0x80000000` marker (e.g. BelInverter.dbc)
are fixed automatically on load via regex pre-processing before passing to cantools.

### Noisy DBCs
DBCs with overlapping/duplicate signals (e.g. GMW8762 GMLAN) loaded with `strict=False`;
"Overwriting message" warnings suppressed via `redirect_stdout/stderr`.

### cantools field mapping (corrected)

| cantools attribute | .gdf field | Notes |
|---|---|---|
| `message.frame_id` | field 1 | `{:x}` lowercase hex |
| `signal.start` if LE, else `-signal.start` | field 3 | Sign encodes endianness |
| `signal.length` | field 4 | |
| `signal.is_signed` → `Y`/`N` | field 5 | Signed/unsigned, NOT endianness |
| `signal.offset` | field 6 (bias) | |
| `signal.scale` | field 7 | |

---

## Existing .gdf Files

| File | Contents |
|------|----------|
| `projects/vtrux/notes/artifacts/speeds.gdf` | Engine RPM, vehicle speed, generator RPM, traction motor RPM |

---

## Dual-Bus Issue and Filtered Logs

SavvyCAN graphs all frames matching an ID regardless of bus. For IDs that exist on
multiple buses (e.g. 0x0C9 Engine_Speed — VCM-spoofed on one GMLAN bus, real OBD values
on the other), this produces a noisy trace and degrades render performance.

**Solution:** pre-filter the log to the correct bus and only the IDs needed, then load
the small filtered log into SavvyCAN alongside the `.gdf`.

**Plan for `tools/filter_log.py`:** see the internal `filter_log` plan.

---

## Part 2 (Not Yet Started): Automated SavvyCAN Launch — `tools/open_in_savvycan.py`

### Context

SavvyCAN has **no documented CLI arguments** and **no IPC interface** — file loading is
entirely GUI-driven. Automation requires launching the process and then driving the GUI.

### Approach

Two-step automation using `pywinauto` (Windows GUI automation library, `pip install pywinauto`):

1. **Launch SavvyCAN.exe** — pass the log file as `argv[1]`. Many Qt apps handle a single
   file argument natively even without documentation; worth trying first. If Qt ignores it,
   fall back to automating `File → Open Capture File` via the GUI.
2. **Load the `.gdf`** — once the main window is visible, use pywinauto to trigger
   the right-click context menu in the graph window: "Load graph definitions from file".

### CLI Interface

```
python tools/open_in_savvycan.py --log <log_file> --gdf <gdf_file> [--savvycan PATH]
```

**Options:**
- `--log PATH` — log file to open in SavvyCAN
- `--gdf PATH` — `.gdf` graph definition file to load
- `--savvycan PATH` — path to SavvyCAN.exe (default: auto-detect at `tools/SavvyCAN-Windows_x64/SavvyCAN.exe`)

### SavvyCAN Window Flow

```
SavvyCAN.exe launches
  └─> Main window = Log Message Viewer (frame list)
        └─> User opens Graph window (separate child window) from here
              └─> Right-click in Graph window → "Load graph definitions from file"
```

### Implementation Plan

```python
# Pseudocode
exe = find_savvycan_exe()                        # glob tools/SavvyCAN-Windows_x64/SavvyCAN.exe
proc = subprocess.Popen([exe, str(log_path)])    # argv[1] = log file (Qt may handle it)
app = pywinauto.Application(backend='uia').connect(process=proc.pid, timeout=15)

# Step 1: Wait for main window (Log Message Viewer)
main_win = app.window(title_re='SavvyCAN.*')
main_win.wait('visible', timeout=15)

# Step 2: If Qt didn't auto-load the log, use File > Open from main window
# (detect by checking if frame list is populated)

# Step 3: Open the Graph window from the main window
# (likely via menu item, e.g. "Windows > Graph" or toolbar button)
main_win.menu_select('...')  # TBD from discovery step

# Step 4: Find the Graph window (separate top-level or child window)
graph_win = app.window(title_re='.*[Gg]raph.*')
graph_win.wait('visible', timeout=10)

# Step 5: Right-click in graph area → "Load graph definitions from file"
graph_win.right_click_input()
# Select menu item, handle file open dialog
# Type gdf_path + Enter
```

### Key Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Qt5 app is not fully accessible via UIA | Also try `backend='win32'`; fall back to `pyautogui` coordinate-based clicks |
| Graph window may not be open by default | After main window loads, look for a "Graph" menu or toolbar button to open it |
| File dialog may vary by Windows version | Use `pywinauto.keyboard.send_keys` to type path + Enter |
| Log file arg ignored by Qt | Automate File → Open as fallback path |

### Discovery Step

Before writing the full automation, run a discovery script to identify:
- SavvyCAN's actual window title and Qt class name
- Whether argv[1] opens the log file
- Control names/hierarchy for the graph right-click menu

```bash
python tools/open_in_savvycan.py --discover
```
This prints the window tree (using `app.print_control_identifiers()`) so we can
find the correct control path for the .gdf load menu item.

### New Dependencies

- `pywinauto` — `pip install pywinauto` (Windows only)

### Files to Create/Modify

| File | Action |
|------|--------|
| `tools/open_in_savvycan.py` | Create — launch SavvyCAN + load log + load .gdf |
| `tools/tools.md` | Add entry |
