# Android App Notes

Notes for the `android-app/CanLoggerApps/` multi-module Android project.

## Live Display (Vtrux)

Streaming decoded CAN signals from the Vtrux logger phone to an in-truck display, either embedded in the logger app or on a separate companion phone over the truck hotspot. Shipped 2026-05-12 (all 7 phases complete).

- Wire protocol (CAN Display Protocol v1): `protocols/can-display-protocol.md`
- Server (logger phone): `cancore/.../DisplayServer.kt`
- Client: `cancore/.../RemoteCanDataSource.kt` (companion) / `cancore/.../LocalCanDataSource.kt` (embedded)
- UI: `:display` module, Vtrux launcher is `vtrux/.../LiveDisplayActivity.kt`
- Test server (log replay): `tools/can_display_server.py`

| File | Contents |
|------|----------|
| `android-can-poc.md` | PoC notes (gs_usb protocol, Innomaker on Android, PEAK replay setup). The PoC lives at `android-app/CanReaderApp/`. |
| `canlogger-build-notes.md` | CanLoggerApps build notes: all four `:cancore` phases complete, module architecture, BUSMASTER format, build environment (Desktop), CAN log replay, gotchas. Consolidates the earlier shared-can-core design notes. |
| `outstanding-changes.md` | Two bugs pending implementation: (1) no debounce in `CanPipelineManager.addDevice()` before `open()` causes permanent "stuck waiting for dongle" on hub power-source transitions; (2) no `WakeLock` in `CanLoggingService` allows USB autosuspend on screen-off. Both proposed fixes documented with evidence and code. |

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `protocols/` | Wire protocol specs. `can-display-protocol.md` — WebSocket protocol for the live display feature. |

> Internal planning files (`plans/`) and generated artifacts (`artifacts/`) are working files and are not included in the public repository.
