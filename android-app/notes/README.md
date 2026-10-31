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

## Indirect TPMS (Coda)

Wheel-speed tyre-pressure monitoring, replacing the dead Coda-proprietary sensors. **UI and
scaffolding complete 2026-09-21; detection algorithm owned by a separate workstream and not yet
landed.** Also the app's first CAN *transmit* path, which is built and tested but disabled with
no registered slots.

- App implementation (settings page, handoff seam, transmit mechanism and interlocks):
  `../android-coda-tpms-implementation.md`
- Method, feasibility and validation: `../../projects/coda/notes/indirect-tpms-feasibility.md`
- Algorithm and storage plan: `../../projects/coda/notes/plans/tpms_app_algorithm.md`
- **Next app-side work, in progress:** `plans/coda-tpms-gps.md` — GPS capture, persistent store,
  drive rows and the detector, all needed before the in-car GPS bringup + first calibration.

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
| `canlogger-build-notes.md` | CanLoggerApps build notes: all four `:cancore` phases complete, module architecture, BUSMASTER format (with `ERR` lines and the notification's drop counts, 2026-10-30), build environment (Desktop), CAN log replay, gotchas. Includes content from the original `plans/shared-can-core.md`. |
| `evap-bug.md` | EVAP indicator bug (diagnosed 2026-07-19, **implemented 2026-07-21; not yet verified by replay or on the truck**). `vcm_evap_active` was mapped to `0x649` B0 bit 7, which is not the evap flag — wrong in 6/17 logged purge sessions. Correct signal is B4 bit 7 (17/17). Project DBC already fixed; app asset DBC + `LiveDisplayScreen.kt` changes are specified with a replay regression test. Also adds the PENDING state that the UI spec called for but v1 never implemented. |
| `outstanding-changes.md` | Bugs and changes across the apps, newest first, with an index table at the top giving each entry's status. Fifteen entries as of 2026-10-30. Bug 4 (silent `tryEmit` drops) and Bug 11 (CAN error frames logged as standard frames `0x004`/`0x00C`) fixed 2026-10-30 in the 1.1 release builds; Change 15 moves car and phone loads to release builds. Open: Bug 12 (gs_usb read loop), Change 13 (TRC 2.1), Change 14 (Coda GPS/TPMS CPU cost), Bug 10 (`:p914` road-log frame loss, Bug 8 the current theory), Change 9. |

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `plans/` | Plan files. `private-git-migration.md` — **planning, nothing cut over** (written 2026-10-30 by the Infrastructure session). Moving the Android apps from Seafile into the private repo `github.com/nickyivyca/android-canbus-apps`: secrets stay in Seafile, pre-cutover build changes, cutover day, the `reverse-it` side and the public export. `tryemit-drops.md` — **done 2026-10-30; Steps 0-4 (bench experiments 2026-10-29; fix chosen, phone run and fix implemented 2026-10-30). The fix is in the 1.1 release builds, with Bug 11's and Change 15 (release builds).** Bug 4: measure where `tryEmit` drops frames and how much headroom there is, on the gs_usb bench with the emulator artificially slowed, before choosing a fix. `gs-usb-error-frames.md` — **done 2026-10-30; the fix is in the 1.1 release builds. Step 6 (phone run) passed 2026-10-30. Steps 0-5 done 2026-10-28 (the the Linux box SocketCAN rig is up; Innomaker passthrough into the AVD works and reproduces the bug; the fix and its tests are in; on a real fault matrix the fixed app decodes the Innomaker's error reports as the Linux kernel driver does; on the OnePlus 7T too).** Bug 11: log CAN error frames as error frames in all gs_usb apps (regular mode kept), the rig with real fault injection, and an emulator USB passthrough experiment. `coda-tpms-fragment-store.md` — **done; build 29 (dropped 2026-09-26) was never installed, and build 30 (dropped 2026-09-28) carries it plus the spec 8a changes.** The Coda TPMS store as immutable fragments (SeaDrive uploads once), per-minute partial rows replacing the GPS snapshot store, and a recursive `/tree` on the file server. `coda-slcan-harness-0x600.md` — **in progress.** The Coda emulator harness (real logs replayed into the AVD over SLCAN, one stream per bus), then the `0x600` lamp-hold prototype. `coda-tpms-gps.md` — **in progress.** Coda indirect-TPMS: GPS capture (rates only), persistent calibration store, per-log drive rows and the detector port, ready for the in-car GPS bringup + first calibration. `vtrux-fault-display.md` — **in progress.** Fault reporting for the live display: replay rig, the measured fault-mode discriminators, the latched-cause classifier, and the remaining work. Written as a handoff. `companion-file-sync.md` — server in `:cancore` + phone companion app to auto-pull Coda logs over the head unit's hotspot. `vtrux-live-display.md` — live decoded-signal streaming from the Vtrux logger phone (or test server) to a display app, deployable on the same logger phone, a separate phone, or a future tablet head unit. `914-app.md` — the `:p914` display + logger app (see below). |
| `protocols/` | Wire protocol specs. `can-display-protocol.md` — WebSocket protocol for the live display feature. |
| `artifacts/` | Generated data files. See `artifacts/README.md`. |
