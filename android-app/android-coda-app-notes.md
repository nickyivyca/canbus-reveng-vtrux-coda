# Coda Android App — Build Notes

## Phase 1 Complete (2026-03-22) — Green Screen Display, Phone, Replayed Data

### What was built

Full `:coda` app module delivering the green screen display driven by live or replayed B CAN data:

- `CodaSignalDecoder` decodes 9 CAN IDs into typed signal values
- `GreenScreenState` / `jpgKey()` selects the correct JPG from the 36-frame set
- `GreenScreenView` (Compose) loads all 36 JPGs into a bitmap cache on first composition, draws the selected JPG letterboxed on the canvas, and overlays numeric text + notch markers
- `CodaViewModel` ticks at 10 Hz, applies low-pass filters before pushing state to the UI
- `MainActivity` handles USB attach/detach/permission lifecycle and starts `CanLoggingService`

---

### Green Screen Overlay Calibration

All positions measured on the **320×240 source JPG** and stored as fractions. The view scales them to the drawn image rect at runtime.

#### Top bar text boxes

| Element | Left px | Right px | Left frac | Right frac | Y frac |
|---------|---------|----------|-----------|------------|--------|
| Battery % | 14 | 99 | 0.044 | 0.309 | 0.12 |
| Exp Range | 117 | 158 | 0.366 | 0.494 | 0.12 |
| Max Range | 221 | 263 | 0.691 | 0.822 | 0.12 |

- Battery % text: centered in box, font size `imgH * 0.031`
- Exp/Max range text: **right-aligned** to box right edge (number sits left of the "miles" text already in the JPG), font size `imgH * 0.027`

#### Slider notch bars

All slider bars share the same X extent: px 19–113 → fractions 0.059–0.353.

| Bar | Y px | Y frac |
|-----|------|--------|
| Motor torque | 63 | 0.263 |
| Climate power | 112 | 0.467 |
| Aux power | 158 | 0.658 |
| Battery temp | 205 | 0.854 |

Notch: `notchWidthFrac = 0.006`, `notchHeightFrac = 0.065`.

Motor is bidirectional — notch fraction = `0.5 + torqueNm / (2 * MAX_NM)`.
Climate, aux, batt temp are unidirectional 0→1.

---

### Signal Calibration Findings

#### Battery temperature display range
Calibrated against the physical slider bar in the JPG by two-point method:
- px 44 on the bar = 8°C
- px 90 on the bar = 45°C
- Solved: `BATT_TEMP_DISPLAY_MIN_C = -12`, `BATT_TEMP_DISPLAY_MAX_C = 64`

These constants are in `CodaConstants.kt`.

#### Driving range formula
Recalibrated in Phase 2 — see Phase 2 Range Formula section. Current constants: `RANGE_SCALE = 0.62f`, `RANGE_OFFSET = 0f`. Scale is provisional at the low-range end — not yet validated against known GPS distances.

#### Motor torque zero encoding
Raw LE uint16 zero = 0x7D80 (32128), scale 0.1 Nm/count. Deadband: |torque| < 5 Nm → TorqueState.NONE.

---

### Low-Pass Filters

Motor torque, climate power, and aux power are filtered before display to suppress frame-to-frame jitter. Climate was added after first live test confirmed it needed it.

- Time constant τ = 1 second
- α = dt / (τ + dt) = 0.1 / 1.1 ≈ 0.091 at 10 Hz
- Applied in `CodaViewModel` tick (main thread), not in the decoder

Battery temperature is not filtered — it changes slowly by nature.
SoC, range are not filtered — they update infrequently and don't jitter.

---

### Bus Identification — slowturnonwithdefroster2 Log

Three buses in the log: 1, 2, 3.

| Bus | Frame count | Role |
|-----|------------|------|
| 1 | 920,176 | Partial B CAN (missing 0x378, 0x382 etc.) |
| 2 | 247,404 | Unknown (IDs 0x0–0x9, likely diagnostic or C CAN) |
| 3 | 752,128 | **B CAN** — all anchor IDs present (0x276, 0x378, 0x383, 0x2C1, 0x390, 0x391, 0x382) |

B CAN = bus 3 in this capture session. Bus numbers vary by dongle insertion order — always identify by anchor IDs.

Replay command: `can_replayer.py <log> --bus 3 --bitrate 500000`

---

### App Icon

Extracted the ring/circle graphic from `android-app/Coda_Logo.svg.png` (top ~65% of the 1920×1792 PNG, bbox 409–1511 x, 51–1124 y). Cropped square, applied circular alpha mask, scaled to all mipmap densities (48/72/96/144/192 px). App label is "Coda".

---

### USB Behavior on Device

- First dongle attach triggers the Android USB permission dialog — user must tap Allow
- After Allow, `onDeviceReady` fires, pipeline starts, logging service starts
- If the dialog is dismissed/denied, `USB permission denied` is logged and nothing starts — plug and unplug to retry
- The app correctly handles attach/detach events while running

---

### Build Environment (Desktop)

- `local.properties` must exist at `android-app/CanLoggerApps/local.properties` with `sdk.dir=<ANDROID_SDK_DIR>`
- JAVA_HOME must be set to `<ANDROID_STUDIO_JBR>` (JDK 17) — the system default java is 1.8 and will fail
- Gradlew must be invoked via PowerShell with explicit env var: `[System.Environment]::SetEnvironmentVariable('JAVA_HOME', ..., 'Process')`
- ADB device connects over TCP: `<lan-ip>:39271` (port changes each wireless debug session)

See `android-app/notes/canlogger-build-notes.md` for full build infrastructure notes.

---

## Phase 2 — Deploy to Car Head Unit (Complete, 2026-03-22)

**Goal:** App running on the 7-inch head unit display with live CAN data from the car.

### Head Unit Hardware (confirmed 2026-03-22)

Device: **A007 generic Chinese Android head unit** running Zlink (Android Auto / CarPlay bridge software).

| Property | Value |
|----------|-------|
| Model | A007 (A007_C55_HA4_U464-12-EN-D) |
| IP address | <lan-ip> |
| Android version (Settings) | 12 |
| `Build.VERSION.SDK_INT` reported to apps | **29** (spoofed — see below) |
| Build number | A007-userdebug 12 SP1A.210812.016 2023042611123 release-keys |
| Security patch | December 5, 2021 |
| Kernel | 4.14.133+ (Wed Apr 26 11:18:27 CST 2023) |
| Chipset | Unisoc/SPRD (sharkl5pro modem) |
| Connectivity | WiFi only — no USB device port exposed, only USB-A host ports |
| ADB | No wireless debugging in Developer Options; no open TCP port found (scanned 1–9999) |
| APK install method | Sideload via file sync app (SeaDrive) |

**SDK spoofing:** The device reports `Build.VERSION.SDK_INT = 29` to all apps despite running Android 12 (`SP1A.210812.016`). This is a known ROM-level compatibility hack on some generic Chinese head units. Any code that gates behaviour on `Build.VERSION.SDK_INT >= Build.VERSION_CODES.R` (30) will silently skip on this device even though Android 12 APIs are present. See `android-app/notes/canlogger-build-notes.md` for the workaround pattern.

**Debug logging:** App embeds a TCP log server on port 9876 (started in `CodaApplication.onCreate()`). Connect from PC: `py -3.11 -c "import socket,time; s=socket.create_connection(('<lan-ip>',9876),5); s.settimeout(0.5); [...]"`. Crash logs from the previous run are replayed on next startup via `cache/last_crash.txt`.

### Outcome

All steps complete. App is running on the head unit with live CAN data. Green screen display, overlay positions, and aspect ratio confirmed correct on the 7-inch display. Logging is working — files land in `Android/data/com.reverseit.coda/files/CodaLogs/` (see storage notes below). Log session boundaries (key-off → key-on creates new file) implemented and working at a base level; field testing in progress.

### Head Unit — Storage Permission Findings

The A007 ROM is missing both the `isExternalStorageManager()` method AND the `MANAGE_APP_ALL_FILES_ACCESS_PERMISSION` settings activity from its `framework.jar`. The entire `MANAGE_EXTERNAL_STORAGE` permission flow is absent from the firmware.

`WRITE_EXTERNAL_STORAGE` IS granted by the ROM but is ineffective on Android 12 scoped storage enforcement — writes to `/sdcard/CodaLogs/` fail with Permission denied regardless.

**Resolution:** Log to `getExternalFilesDir(null)/CodaLogs/` → `/sdcard/Android/data/com.reverseit.coda/files/CodaLogs/`. No permissions needed. The A007's built-in file manager can browse `Android/data/` (Chinese ROM does not enforce the Android 11+ restriction on that path). Last tested build: `coda-debug (12).apk`.

### Aspect Ratio

`GreenScreenView.kt` changed from letterbox (`ContentScale.Fit`) to stretch-fill (full `size.width` × `size.height`, zero offset). The 15mm black bands on each side of the 15cm screen are gone. Overlay fraction constants are unchanged — they scale correctly with the new full-screen dimensions.

### Range Formula

Calibrated against the green screen physical display (shows 94 expected / 123 max) at ~100% SoC:
- Raw bytes back-calculated: ~152 / ~199
- New scale: **0.62 miles/count**, offset: **0**
- Old formula (1.1 × raw − 19) gave 148/200 — wrong
- Constants in `CodaConstants.kt`: `RANGE_SCALE = 0.62f`, `RANGE_OFFSET = 0f`

Scale is provisional — calibrated at full charge only, needs validation at lower SoC.

---

## Phase 3 — Sleep/Wake Log Lifecycle (In Progress, 2026-03-22)

**Goal:** Each ignition cycle produces a separate log file; logging stops cleanly on key-off.

### Implementation — Option B (screen state proxy)

`ACTION_SCREEN_ON` / `ACTION_SCREEN_OFF` broadcast receiver is registered in `CanLoggingService`. Screen ON starts a new session (new timestamp tag, segment 0); screen OFF flushes and closes.

**Problem found on head unit:** The A007 resumes from suspend after `ACTION_SCREEN_ON` has already fired, so the dynamically-registered receiver misses the event. The service would stay in `screenOn=false` state and never start a new log.

**Fix:** 5-second polling coroutine in `CanLoggingService.onCreate()` compares `PowerManager.isInteractive()` against the tracked `screenOn` state. If they disagree, the service reconciles within 5 seconds — either starting a new session (missed screen-on) or stopping logging (missed screen-off). The receiver and poll are complementary; both can fire safely.

Field testing in progress (will verify new file per key cycle over next few drives).

### Open — CAN-based ignition detection (Option A)

Not yet investigated. If screen-based detection proves unreliable, implement CAN signature detection: run `status_events.py` on the first/last 30 seconds of captures with clean key-on/off cycles to find a consistent wakeup frame pattern. `LogSegmentPolicy` interface in cancore is the right hook for this.

---

## Signal Logic Fixes (2026-03-22)

### Cabin Conditioning Display

**Previous logic**: compared `evapAirOffTemp` vs `returnAirTemp` from 0x391, with no gate. Produced false COOLING when HVAC was completely off.

**Fix**: switched to discrete status bits from 0x276 B2 — `bit3=heating active`, `bit4=AC active`. No fan gate needed; the bits are only set when the respective system is actively running. Confirmed against `coda_20260322_160846_T0.log` (heater-then-AC sequence).

**Root cause of fan gate confusion**: 0x276 B5 was previously documented in `driver-inputs.md` as "blower output." DBC fine sweep (2026-02-26) confirmed it is `PTCHeaterPWM` — it tracked fan knob steps only because PTC demand scales with fan speed during heating. No cabin blower byte is visible on B CAN. Corrected in `driver-inputs.md` (2026-03-22).

### Logger Notification Tap

Added `contentIntent` to `CanLoggingService.buildNotification()` using `getLaunchIntentForPackage()`. Tapping the notification now brings up the green screen. Build 15.

---

## Outstanding Validation Tasks

- [ ] **Charging mode display**: confirm green screen switches to CHARGING image set when plugged in (HVPowermode = 5 from 0x378 B0[7:4])
- [ ] **Range scaling at low SoC**: current scale (0.62 mi/count) calibrated at ~100% SoC. Confirm accuracy at lower SoC where the displayed value will be small

---

## Deferred Change — Log Session Trigger (screen -> power-connected)

**Do this the next time Coda app code is touched — not silently in a session focused on something else.**

`CanLoggingService` currently starts/stops logging on screen on/off. For the Coda head unit this is appropriate (screen on = key on = car powered). However, when the Vtrux app implemented its own trigger, the trigger was decoupled into a `EXTRA_TRIGGER_MODE` extra (`"screen"` for Coda, `"power"` for Vtrux). At that point, Coda's behavior was left unchanged.

If the Coda phone is ever powered from an ignition-switched source rather than always-on 12V, migrating to `"power"` mode (USB charge connect/disconnect) would be cleaner. Validate this change against real vehicle behavior before merging — the screen-on heuristic and the power-connected heuristic must agree on session boundaries. Do not make this change silently; test it deliberately.

---

## Future Scope — Additional Display Screens

Architecture of the display layer must support sliding between screens. The green screen compositor is Screen 0. Future screens (from-scratch Compose layouts, numeric dashboards, etc.) slot in as additional pages without reworking the signal decoder or logging layers.

## Future Scope — Diag CAN DID Reader

Not scoped. A future phase could use Diag CAN (second Innomaker dongle) to issue UDS requests and read live DIDs (cell voltages, fault codes, etc.). The `:cancore` multi-bus pipeline has no architectural blocker for this. Would need a new `DiagService` component and a new UI tab.

## Future Scope — Network Features

- Host a simple HTTP server on the phone's WiFi IP for charging status monitoring.
- Expose a Home Assistant sensor interface when connected to home WiFi.

---

## Phase 4 — LogFileServer (Complete, 2026-05-07)

**Goal:** Expose completed log files over local WiFi so a companion app on a regular phone can pull them, bypassing the slow head-unit SeaDrive upload.

### What was built (Phase 1 of the sync plan)

Server lives in `:cancore` as `LogFileServer.kt` (NanoHTTPD held by composition, not extended — keeps consumer modules from needing NanoHTTPD on their classpath). `CodaApplication.onCreate()` instantiates and starts it alongside `DebugLog.start()`; `VtruxApplication` doesn't touch it, so the server is Coda-only for now even though the class is in cancore.

| Property | Value |
|----------|-------|
| Port | `9877` |
| Bearer token | `BuildConfig.SYNC_TOKEN`, sourced from `local.properties` `sync.token` |
| Served directory | `getExternalFilesDir(null)/CodaLogs/` (same as `CanLoggingService` default for Coda) |
| Active-segment guard | `(name) -> name == CanLoggingService.currentSegmentName`. The companion property is `@Volatile`, set in `openNewSegment()`, cleared in `stopLogging()`. |

Endpoints (all require `Authorization: Bearer <token>`):
- `GET /health` → `{vehicle, freeBytes, totalBytes, fileCount, version}`
- `GET /files` → JSON array of `{name, size, mtime, complete}`
- `GET /files/<name>` → file stream; 409 if active; 404 if missing/unsafe-name
- `DELETE /files/<name>` → 204; 409 if active; 404 if missing/unsafe-name

Filenames are constrained to `[A-Za-z0-9_.-]+\.log` to prevent path traversal.

### Discovery from a phone or laptop on the Coda hotspot

The head unit's hotspot AP IP is the WiFi default gateway from any client's perspective. Verified value when on Coda hotspot: gateway `192.168.43.8`, SSID `Coda`. When the head unit is on home LAN instead, it's reachable at `<lan-ip>:9877` directly. The companion app does not hardcode either — it reads the gateway at sync time.

### Boot trace (visible in DebugLog stream on port 9876)

```
D/App: LogFileServer started on 9877, dir=/storage/emulated/0/Android/data/com.reverseit.coda/files/CodaLogs
D/App: CodaApplication.onCreate complete
```

### Side-effects captured during this phase

- **Project-shared debug keystore** at `CanLoggerApps/debug.keystore` (SeaDrive-synced). Both `:coda` and `:vtrux` configured to sign debug builds with it via `signingConfigs.debug`. Prevents `INSTALL_FAILED_UPDATE_INCOMPATIBLE` when the same APK lineage is built across machines. Documented in `android-tools-reference.md`.
- **Coda manifest gained `WAKE_LOCK` and `CHANGE_NETWORK_STATE`** to match Vtrux. The wakelock acquire in `CanLoggingService.startLogging` had been added to cancore some time ago; Vtrux's manifest was updated then but Coda's wasn't. The first Coda build to hit `startLogging` (this phase's test build) crashed with `SecurityException: WAKE_LOCK`. Fixed.
- **APK dropoff naming**: increment every build, never overwrite. Documented in `android-tools-reference.md`. Reason: SeaDrive may not have finished pulling the previous file when a new one is dropped, and reused names give no way to tell.

### How to verify after a new build

A PowerShell test runner (`notes/artifacts/test_log_file_server.ps1`, a working helper not included in the public repo) exercised the endpoints. It ran with the phone or laptop on the Coda hotspot (or anywhere with line-of-sight to the head unit IP):

```powershell
.\android-app\notes\artifacts\test_log_file_server.ps1                         # auto-discover gateway
.\android-app\notes\artifacts\test_log_file_server.ps1 -ServerHost <lan-ip>  # over LAN
.\android-app\notes\artifacts\test_log_file_server.ps1 -TestDownload           # also pull smallest file
.\android-app\notes\artifacts\test_log_file_server.ps1 -TestDelete             # destructive
```

Output mirrors to `test_output.txt` next to the script.
