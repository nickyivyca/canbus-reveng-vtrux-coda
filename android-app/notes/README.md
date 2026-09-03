# Android App Notes

Notes for the `android-app/CanLoggerApps/` multi-module Android project.

## Live Display (Vtrux)

Streaming decoded CAN signals from the Vtrux logger phone to an in-truck display, either embedded in the logger app or on a separate companion phone over the truck hotspot. Shipped 2026-05-12 (all 7 phases complete).

- Plan + per-phase outcomes: `plans/vtrux-live-display.md`
- Wire protocol (CAN Display Protocol v1): `protocols/can-display-protocol.md`
- Server (logger phone): `cancore/.../DisplayServer.kt`
- Client: `cancore/.../RemoteCanDataSource.kt` (companion) / `cancore/.../LocalCanDataSource.kt` (embedded)
- UI: `:display` module, Vtrux launcher is `vtrux/.../LiveDisplayActivity.kt`
- Test server (log replay): `tools/can_display_server.py`

## 914 App (`:p914`)

Display + logger for the Porsche 914 EV conversion. **Track A (comms + logging) complete and
working on the car, 2026-08-13. Track B (display) not started.** The app also flashes VCU
firmware over adb, so the car can be reflashed with no laptop present.

Two deliverables: **A -- comms/SLCAN bringup** and **B -- display implementation and layout
specs**. The transport is the novel part: the 914 has no gs_usb dongle, so the app reads SLCAN
(LAWICEL ASCII) from the VCU's USB CDC serial port. The SLCAN reader lives in `:cancore` as a peer
of gs_usb; only the CDC transport is vehicle-specific.

- Plan and full results: `plans/914-app.md`
- Module architecture and USB gotchas: `canlogger-build-notes.md`
- Vehicle overview + DBC: `projects/914/README.md`
- Replay harness: `tools/slcan_bridge.py` (see `tools/tools.md`)

| File | Contents |
|------|----------|
| `android-can-poc.md` | PoC notes (gs_usb protocol, Innomaker on Android, PEAK replay setup). The PoC lives at `android-app/CanReaderApp/`. |
| `avd-emulator-bringup.md` | Android Emulator bringup for the 7-inch head unit simulation (`7_WSVGA_Tablet_API_31`, 1024x600 mdpi, API 31 x86_64). Emulator version requirement (32.1.14 hangs before guest boot, 36.6.11 works), `hw.mainKeys` nav-bar fix, one-time storage-permission grant, non-default AVD path, and why USB CAN cannot be emulated. |
| `canlogger-build-notes.md` | CanLoggerApps build notes: all four `:cancore` phases complete, module architecture, BUSMASTER format, build environment (Desktop), CAN log replay, gotchas. Includes content from the original `plans/shared-can-core.md`. |
| `evap-bug.md` | EVAP indicator bug (diagnosed 2026-07-19, **not implemented**). `vcm_evap_active` was mapped to `0x649` B0 bit 7, which is not the evap flag — wrong in 6/17 logged purge sessions. Correct signal is B4 bit 7 (17/17). Project DBC already fixed; app asset DBC + `LiveDisplayScreen.kt` changes are specified with a replay regression test. Also adds the PENDING state that the UI spec called for but v1 never implemented. |
| `outstanding-changes.md` | Two bugs pending implementation: (1) no debounce in `CanPipelineManager.addDevice()` before `open()` causes permanent "stuck waiting for dongle" on hub power-source transitions; (2) no `WakeLock` in `CanLoggingService` allows USB autosuspend on screen-off. Both proposed fixes documented with evidence and code. |

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `plans/` | Plan files. `companion-file-sync.md` — server in `:cancore` + phone companion app to auto-pull Coda logs over the head unit's hotspot. `vtrux-live-display.md` — live decoded-signal streaming from the Vtrux logger phone (or test server) to a display app, deployable on the same logger phone, a separate phone, or a future tablet head unit. `914-app.md` — the `:p914` display + logger app (see below). |
| `protocols/` | Wire protocol specs. `can-display-protocol.md` — WebSocket protocol for the live display feature. |
| `artifacts/` | Generated data files. See `artifacts/README.md`. |
