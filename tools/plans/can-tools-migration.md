# can-tools Migration & GUI Plan

Separate the CAN **runtime/logger/GUI** stack out of `reverse-it` into a standalone
git repo (`can-tools`) that becomes a submodule of the public `canbus-reveng-vtrux-coda`
repo, then build a distributable PyQt GUI logger on top of it. The RE/analysis
framework stays in `reverse-it`.

**Status:** Phase 1 **COMPLETE** and pushed (2026-07-02). Phase 2 in progress.
**Build machine:** `the bench PC` → Python `py -3.12` (per `python-executables-reference.md`).

### Phase 1 outcome (2026-07-02)
- `can-tools` @ `bed9632` pushed: `canbench/{live,logio}`, reworked `can_logger`/`can_replayer` (candump), scaffolding, `tests/test_smoke_virtual.py` (hardware-free virtual-bus test).
- Public `canbus-reveng-vtrux-coda` @ `27d3365` pushed: runtime/GUI files + `canre/{live,gui}` removed; `can-tools` submodule added (→ `bed9632`); `canre/` is analysis-only.
- reverse-it: `canbench/` mirrored at root; `canre/live` removed (`canre/gui` kept for Phase-3 `can_monitor`); **12** `canre.live` consumers repointed to `canbench.live`; private `sync_from_can_tools.py` added.
- **Dual-path bootstrap** on the 3 published live-hardware analysis tools (`uds_interrogator`, `vtrux_uds_probe`, `vtrux_dtc_interrogation`) so `canbench` resolves from the submodule (public) or root (reverse-it).
- Verified functionally (virtual bus) across all 3 canbench copies: detect + CANBusLogger recv loop + logio round-trip all PASS.
- **Deferred:** BUSMASTER read shim (replaying the historical BUSMASTER corpus from the new tool is not possible until added). candump ` R` suffix (canplayer interop) untested. Public narrative README left untouched.

---

## Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Default log format | **candump / SocketCAN `.log`** | python-can native read+write → can-tools needs **no** `canre.parsers`. Epoch timestamps remove the filename-anchoring hack. Greppable, multi-bus via iface field. All other formats still *readable* by `canre` for analysis. |
| Windows packaging | **PyInstaller `--onedir`, zipped** | No per-launch temp extraction, reliable UAC elevation (ixxat reset), clean libusb/Qt DLL loading. Recipient needs no Python; only vendor CAN drivers for their dongle (gs_usb/virtual need none). |
| Package name | **`canbench`** | `cantools` is the pip DBC lib. Avoids a `canre` name-clash when can-tools is a submodule of the public repo (which already has its own `canre/`). |
| Historical BUSMASTER replay | **Not yet** | Phase 2 needs (loopback/test) are met by candump. Old-corpus replay still works from reverse-it's existing tools. Add a ~40-line read-only BUSMASTER shim later if wanted. |
| Sync script | **Private, reverse-it only** | Only the maintainer syncs. `sync_to_reverseit.py` never committed to the can-tools git repo. |
| Live signal decode in GUI | **Phase 3** | Phase 2 GUI shows traffic rate (frames/sec) only — no DBC/`cantools` dependency. |

---

## Architecture

`canbench` is the standalone runtime package. The **only** migrated `canre` code is the
hardware layer (`canre/live/` → `canbench/live/`); everything else in `canbench` is new or
python-can-native. No dependency on `canre` in either direction.

### can-tools repo layout (`<git-root>\can-tools`, authoritative)
```
can-tools/
├── canbench/
│   ├── __init__.py
│   ├── live/                   # receiver.py, vehicle_configs.py  (migrated from canre/live/)
│   ├── gui/                    # PyQt: main window, vehicle+dongle selectors, rate monitor   [Phase 2]
│   ├── logio.py                # python-can candump write/read wrappers                        [Phase 1]
│   ├── passthrough.py          # two-dongle bridge                                             [Phase 2]
│   └── profiles.py             # vehicle-profile .ini loader                                   [Phase 2]
├── tools/
│   ├── can_logger.py           # candump writer; --passthrough flag (Phase 2)
│   ├── can_replayer.py         # python-can LogReader + MessageSync
│   ├── can_logger_admin.bat    # self-elevating launcher (ixxat reset)
│   └── can_gui.py              # GUI launcher (Windows primary)                                [Phase 2]
├── packaging/                  # PyInstaller .spec + build script + UAC manifest              [Phase 2]
├── tests/                      # run against virtual/udp bus, no hardware                      [Phase 2]
├── requirements.txt
├── README.md
└── .gitignore
```

### Import resolution across the three locations
- **can-tools repo (dev + exe):** `canbench` at repo root; tools run from root / via `-m`; PyInstaller bundles `canbench`.
- **reverse-it (mirror):** `canbench/` sits at reverse-it root beside `canre/`. Runtime tools import `canbench.live`; analysis tools import `canre.*`. Both resolve from root (existing `sys.path.insert(0,".")` convention).
- **public repo (submodule):** submodule at `can-tools/`; its `tools/` run with `canbench` as a sibling — resolves naturally. Public repo's analysis tools keep importing `canre.*` unchanged.

---

## Phase 1 — Migration + submodule stitch  (execute now, gate at end)

Order per maintainer: **reverse-it first → public git → submodule → verify → checkpoint.**

### 1.1 Build out the can-tools git repo
- Create `canbench/__init__.py`, `canbench/live/` (copy `receiver.py`, `vehicle_configs.py`; fix internal import `canre.live.vehicle_configs` → `canbench.live.vehicle_configs`).
- Add `canbench/logio.py`: thin wrappers over python-can `Logger`/`CanutilsLogWriter` (write candump) and `LogReader`/`MessageSync` (read+replay). Filename convention `canlog_YYYYMMDD_HHMMSS.log` retained.
- Migrate + rework `tools/can_logger.py`: replace inline `BUSMASTERWriter` with `logio` candump writer. (Passthrough flag deferred to Phase 2.)
- Migrate + rework `tools/can_replayer.py`: swap `canre.parsers` for `logio`/python-can reader.
- Migrate `tools/can_logger_admin.bat`, `tools/README-can_logger.md` (update format references).
- Add `requirements.txt` (python-can[...], pyusb/libusb-package for gs_usb, PyInstaller — GUI deps added Phase 2), `README.md`, `.gitignore` (`__pycache__`, `build/`, `dist/`, `*.spec` output).
- Commit + push to `github.com/nickyivyca/can-tools.git`.

### 1.2 Refactor reverse-it (mirror)
- Add `canbench/` at reverse-it root (mirror of the git repo).
- Remove `canre/live/` from reverse-it (now `canbench/live/`).
- Update reverse-it imports `canre.live` → `canbench.live` in: `tools/can_monitor.py` (Phase-3, stays here), and replace `tools/can_logger.py` / `tools/can_replayer.py` with the reworked mirrored versions.
- Add private `sync_to_reverseit.py` (manifest-driven copy from `C:\Users\...\Git\can-tools`; **not** committed to git). Manifest = `canbench/**`, `tools/can_logger.py`, `tools/can_replayer.py`, `tools/can_logger_admin.bat`, `tools/README-can_logger.md`.
- Update `tools/tools.md` + `canre/` docs for the moved files / new format.

### 1.3 Refactor public repo (`canbus-reveng-vtrux-coda`)
- Remove now-submoduled files: `tools/can_logger.py`, `tools/can_replayer.py`, `tools/can_logger_admin.bat`, `tools/README-can_logger.md`, `canre/live/`.
- **can_monitor.py + canre/gui/** (Phase-3 live-decode): remove from the public repo for now; they return reworked via the submodule in Phase 3. *(Flag for confirmation — this drops already-published content.)*
- Update `.gitmodules` + `tools/tools.md` + `README.md` + `git-publish.md` to reflect the submodule and that runtime tools are no longer synced from reverse-it.

### 1.4 Stitch submodule
- `git submodule add https://github.com/nickyivyca/can-tools.git can-tools` in the public repo; commit.

### 1.5 Verify paths resolve
- reverse-it: `py -3.12` import smoke test — `canbench.live` importable, `can_logger`/`can_replayer` run `--help`, `can_monitor` imports.
- can-tools repo: standalone `can_logger --help`, `can_replayer --help`, loopback/virtual-bus write→read round-trip of a candump file.
- public repo: submodule present; analysis tools still import `canre.*`; no dangling `canre.live` refs (grep).

### 1.6 GATE — checkpoint with maintainer
Present results; get explicit approval before closing Phase 1. Then Phase 2.

---

## Phase 2 — Underlying code + proto GUI  (after Phase 1 gate)

**Proto GUI (first deliverable to iterate on):**
- Vehicle-profile selector (from `.ini`; default profiles Vtrux/Coda → `VtruxLogs`/`CodaLogs` beside the exe).
- Dongle/interface selector: real dongles (ixxat/kvaser/pcan/gs_usb on Windows; socketcan on Linux) + localhost virtual/udp bus.
- Per-dongle live traffic readout: **frames/sec**, total frames, last-seen — one row per detected dongle/bus.
- Start/Stop passive logging → candump into the profile's folder.
- No decode (Phase 3).

**Underlying code:**
- `canbench/profiles.py` — `.ini` loader (no ini → default Vtrux/Coda paths relative to exe/cwd).
- `canbench/passthrough.py` — two-dongle bridge; forward frames between bus A/B, log only frames sourced on each bus. Also exposed as `can_logger --passthrough`.
- Localhost network CAN: python-can `udp_multicast` (cross-process, test suites) + `virtual` (in-process unit tests).
- `tests/` against the virtual/udp bus (no hardware).

**Packaging:** `packaging/` PyInstaller `--onedir` spec + build script + UAC manifest (run-as-admin for ixxat reset). Linux: CLI entry only, not packaged.

**Iterate:** once the proto GUI opens, refine layout/behavior with the maintainer.

---

## Phase 3 — NOT IMPLEMENTED (scope notes only)

- Bring the prototyped desktop live-**decode** GUI (`canre/gui/` framework + `can_monitor.py`) into `canbench` as a decode view; vehicle profiles expand to carry DBC/decode config.
- **Modular / private distribution:** build+privately-send an exe containing GMLAN decode config while the public repo excludes it. Profiles/plugins must be loadable from an external (non-committed) path so proprietary GMLAN data never lands in the public repo.
- Revisit the historical-BUSMASTER-read shim if old-corpus replay from the new tool is wanted.

---

## Open items / risks
- **Dropping published Phase-3 files** (`can_monitor.py`, `canre/gui/`) from the public repo — confirm before executing 1.3.
- **Publish pipeline change:** `git-publish.md` must note runtime tools now come via the submodule, not the reverse-it sync.
- **gs_usb libusb bootstrap** must survive PyInstaller bundling (verify `libusb_package` DLL is collected) — Phase 2 packaging risk.
- **ixxat admin reset** path uses PowerShell `Disable/Enable-PnpDevice` — verify it still works from the bundled onedir exe under UAC — Phase 2 risk.
