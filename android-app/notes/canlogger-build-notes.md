# CanLoggerApps — Build & Infrastructure Notes

## Project Structure

`android-app/CanLoggerApps/` — Gradle multi-module project:
- `:cancore` — shared Android library (gs_usb protocol, pipeline, logging service, GUI framework)
- `:coda` — Coda vehicle app
- `:vtrux` — Vtrux vehicle app

Migrated from PoC at `android-app/CanReaderApp/` (GsUsbFrame.kt, GsUsbDevice.kt).

---

## Phase 1–4 Complete (2026-03-22) — All CanCore Phases Built

All four cancore phases are implemented and working:

### Phase 1 — Multi-Module Scaffold
- Created Gradle multi-module project with `:cancore` (library) and `:coda` (application)
- Migrated gs_usb PoC code into `:cancore`
- Toolchain: AGP 8.3.2, Kotlin 1.9.22, Gradle 8.4, Compose BOM 2024.04.01, JBR JDK 17

### Phase 2 — Multi-Dongle CAN Pipeline

All Innomaker dongles share VID/PID (`0x1D50` / `0x606F`). Key design points that were implemented:

- Each dongle gets its own `GsUsbDevice` coroutine on `Dispatchers.IO`
- Frames from all dongles merge into a single `SharedFlow<CanFrame>` in `CanPipelineManager`
- `busIndex` assigned by connection order (0, 1, 2...) — matches Python logger behavior
- Bitrate is a per-vehicle constructor param (Coda: 500 kbps)
- On detach: that dongle is removed, remaining buses continue uninterrupted
- `CanFrame` data class: `busIndex`, `timestampMs`, `arbitration_id`, `isExtended`, `dlc`, `data`

### Phase 3 — Background Logging Service

`CanLoggingService` is a foreground service (`foregroundServiceType=connectedDevice`).

Log format — replicates Python `can_logger.py` exactly:
```
HH:MM:SS:TTTT  <busIndex+1>  0x<ID>  Rx  d  <dlc>  <byte0> <byte1> ...
```
TTTT = 10 kHz ticks (millisecond remainder × 10). Header block matches existing captures so `canre` tools parse them directly.

Segmentation: rolls on size (50 MB), time (5 min), or vehicle `LogSegmentPolicy`. Storage: prunes oldest files to stay under 2 GB cap. Logs go to `Context.getExternalFilesDir("logs")`.

`LogSegmentPolicy` is a `fun interface` — vehicle app provides implementation, `NoOpSegmentPolicy` is the default.

### Phase 4 — GUI Framework

- `CodaViewModel` subscribes to pipeline frames on `Dispatchers.IO`
- 10 Hz ticker on main thread snapshots decoder state and pushes to `StateFlow<GreenScreenState>`
- Ticker pauses when Activity is backgrounded (`setForeground(false)` on `onStop`)
- Low-pass filters (τ=1s, α≈0.091) applied in ViewModel tick for motor torque, climate power, aux power — not in the decoder

`SignalDecoder` interface: `update(CanFrame)` + `buildState(): T`. Vehicle app provides the implementation.

---

## Key Classes — :cancore

| Class | Role |
|-------|------|
| `GsUsbDevice` | gs_usb protocol driver; bitrate as constructor param |
| `GsUsbFrame` | Raw USB frame; `toCanFrame(busIndex, ts)` converts to pipeline |
| `CanFrame` | Pipeline data class |
| `CanPipelineManager` | N-dongle manager; emits `SharedFlow<CanFrame>` |
| `LogSegmentPolicy` | `fun interface` for vehicle-specific roll triggers |
| `BusmasterWriter` | BUSMASTER format output |
| `CanLoggingService` | Foreground logging service |
| `SignalDecoder` | Interface for vehicle signal decoders |

---

## Build Environment — Desktop

JDK 17 required — system default java is 1.8 and AGP 8.3.2 rejects it.
- JDK 17: `C:\Program Files\Android\Android Studio1\jbr`
- Android SDK: `<ANDROID_SDK_DIR>`

`local.properties` (not checked in, create locally):
```
sdk.dir=<ANDROID_SDK_DIR>
```

Gradlew from bash (no `cd` needed — use `--project-dir`):
```bash
JAVA_HOME="C:/Program Files/Android/Android Studio1/jbr" \
  android-app/CanLoggerApps/gradlew.bat \
  --project-dir android-app/CanLoggerApps \
  :coda:assembleDebug
# or :vtrux:assembleDebug

---

## Build Environment — L-EEHTRBPN2

- JDK 21 (Android Studio bundled JBR): `C:\Program Files\Android\Android Studio\jbr` (no `1` suffix)
- Android SDK: `<ANDROID_SDK_DIR>`
- AGP 8.3.2 accepts JDK 21 — no issues.

`local.properties`:
```
sdk.dir=<ANDROID_SDK_DIR>
```

Gradlew from bash:
```bash
JAVA_HOME="C:/Program Files/Android/Android Studio/jbr" \
  android-app/CanLoggerApps/gradlew.bat \
  --project-dir android-app/CanLoggerApps \
  :vtrux:assembleDebug
# or :coda:assembleDebug
```

**First-build gotcha:** Gradle auto-downloads build-tools 34.0.0 on first run. If a previous failed build left a corrupt install, delete `<ANDROID_SDK_DIR>\build-tools\34.0.0` and the `.temp\` folder, then retry. Or reinstall via Android Studio SDK Manager.
```

APK outputs:
- `coda/build/outputs/apk/debug/coda-debug.apk`
- `vtrux/build/outputs/apk/debug/vtrux-debug.apk`

ADB install:
```powershell
adb -s <transport> install -r vtrux\build\outputs\apk\debug\vtrux-debug.apk
# or for coda:
adb -s <transport> install -r coda\build\outputs\apk\debug\coda-debug.apk
```

**ADB install rule — always use `-r`:** `adb install -r` (reinstall) preserves USB permissions, Magisk superuser grants, and storage permissions. Uninstalling and reinstalling wipes all of these, requiring the user to re-approve every permission and re-grant in Magisk. Only uninstall (`adb uninstall`) when switching build machines, because each machine has a different debug keystore and `-r` will fail with `INSTALL_FAILED_UPDATE_INCOMPATIBLE` if the signing key differs.

Copy to head unit drop folder (increment N from the highest existing number):
```powershell
Copy-Item 'E:\Seafile\Projects\reverse-it\android-app\CanLoggerApps\coda\build\outputs\apk\debug\coda-debug.apk' 'E:\Google Drive\To Seafile\coda-debug (N).apk'
```

Head unit installs the APK from SeaDrive on the car's Android head unit (10.0.0.121). The head unit's file manager can browse `E:\Google Drive\To Seafile\` via the SeaDrive sync folder.

ADB device (phone): connected over TCP at `10.0.0.115:39789` (port changes each wireless debug session — check `canlogger-build-notes.md` for latest).

---

## CAN Log Replay

Using `tools/can_replayer.py` with PEAK PCAN-USB dongle on PC → Innomaker on phone OTG.

`--bus N` filters to a single log channel. `--skip-confirmation` skips the "Press Enter" prompt (required when running non-interactively). Bus numbers vary by dongle insertion order — always identify by anchor IDs, not bus number.

```bash
py -3.11 tools/can_replayer.py <log> --bus N --bitrate 500000 --skip-confirmation
```

**Vtrux PT bus anchor:** `0x051` @ ~100 Hz. Known bus mapping for `generator on then off.log`:
| Bus | Role |
|-----|------|
| 1 | OBD (0x040–0x044) |
| 2 | Vehicle |
| 3 | **Powertrain** — 0x051 present |

Replay Vtrux PT bus: `can_replayer.py "generator on then off.log" --bus 3 --bitrate 500000 --skip-confirmation`

**Verification (2026-03-22):** Replayed 144,540 frames, phone logged 144,271 (0.2% drop — normal). Log landed at `/sdcard/VtruxLogs/vtrux_<session>_T1.log`, parsed correctly by `survey.py`.

Coda B CAN anchor IDs: `0x276, 0x378, 0x383, 0x2C1, 0x390, 0x391, 0x382`.

Known bus mapping for `codadriveslowturnonwithdefroster2.log`:
| Bus | Frames | Role |
|-----|--------|------|
| 1 | 920,176 | Partial B CAN |
| 2 | 247,404 | Unknown (IDs 0x0–0x9) |
| 3 | 752,128 | **B CAN** — all anchors present |

---

## Log Lifecycle — Screen On/Off (updated 2026-03-22)

Log start/stop is tied to screen state as an ignition proxy (Phase 3, Option B):

- **Screen ON** → new session tag, segment 0 opened, logging starts
- **Screen OFF** → current segment flushed and closed
- `ACTION_SCREEN_ON` / `ACTION_SCREEN_OFF` broadcast receiver registered in `CanLoggingService.onCreate()`
- Screen state at service start is checked via `PowerManager.isInteractive()` so logging starts immediately if screen is already on
- Both conditions must be true to log: `pipeline != null` AND `screenOn`

Note: `ACTION_SCREEN_ON/OFF` cannot be registered in the manifest — must be registered dynamically in the service.

**Polling fallback (added 2026-03-22):** On the A007 head unit, the device resumes from suspend *after* `ACTION_SCREEN_ON` has fired, so the registered receiver misses it. A 5-second coroutine in `onCreate` polls `PowerManager.isInteractive()` and reconciles `screenOn` if mismatched. This ensures a new session starts within 5 seconds of wake even if the broadcast was missed. Both the receiver and poll call the same `onScreenOn()`/`onScreenOff()` helpers — safe to fire concurrently.

---

## Log Storage — App-Private Path (updated 2026-03-22)

**History:** Originally used `getExternalFilesDir()`, switched to `Environment.getExternalStoragePublicDirectory("CodaLogs")` for file manager visibility. Switched back to `getExternalFilesDir()` after discovering the A007 ROM cannot support public storage writes.

**Current path:** `getExternalFilesDir(null)/CodaLogs/` → `/sdcard/Android/data/com.reverseit.coda/files/CodaLogs/`

No storage permissions needed — the system grants the owning app full access to its `getExternalFilesDir()` directory automatically.

**Why public storage failed on A007:** The ROM's `framework.jar` is missing both `Environment.isExternalStorageManager()` (API 30+) and the `Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION` settings activity. The entire `MANAGE_EXTERNAL_STORAGE` flow is absent from the firmware. `WRITE_EXTERNAL_STORAGE` is granted but ineffective for `/sdcard/` writes under Android 12 scoped storage enforcement.

**File manager access:** The A007's built-in file manager can browse `Android/data/` (Chinese ROM does not enforce the Android 11+ restriction on that path). On a standard Android 11+ phone, `Android/data/` is not accessible from file managers — use ADB pull instead.

---

## Bugs Fixed (2026-03-22)

### Bug 1: Pipeline null race — logs created but empty

**Root cause:** `startLogging()` was called in `onStartCommand`, which fires before the binder connection is established. At that point `pipeline` is null, so `pipeline?.frames?.collect` returns null and the coroutine never runs. Files were created by `openNewSegment()` but nothing was ever written.

**Fix:** Moved the logging trigger to the `pipeline` property setter. Both `sessionReady` (set in `onStartCommand`) AND `pipeline != null` must be true before `startLogging()` is called. Either can arrive first safely.

### Bug 2: Foreground notification silently dropped

**Root cause:** `startForeground()` is called in `onCreate`. The USB connect → service start happens within ~1 second of app launch, before the `POST_NOTIFICATIONS` permission dialog has been answered. On Android 13+, if `POST_NOTIFICATIONS` is not granted at the time `startForeground()` fires, the notification is silently discarded and never shown again.

Confirmed in logcat: `POST_NOTIFICATIONS granted: true` appeared 1 second *after* `Logging to .../T0.log` — service started before permission was granted.

**Fix:** Added `startForeground(NOTIF_ID, ...)` to `onStartCommand` as well as `onCreate`. Every USB connect triggers `startLoggingService()` → `onStartCommand`, which re-asserts the notification. By that point permission is already granted, so it posts correctly.

**Trigger to see notification after first install:** unplug and replug the Innomaker dongle — that fires `onStartCommand` again with permission in place.

### Bug 3: POST_NOTIFICATIONS not requested at runtime

Android 13+ requires `POST_NOTIFICATIONS` to be requested as a runtime permission even though it's declared in the manifest. Added `ActivityResultContracts.RequestPermission()` launcher in MainActivity, fired in `onCreate` if not already granted.

---

## Android SDK Version Spoofing — Coda Head Unit (2026-03-22)

The Coda target device (A007 generic head unit, `SP1A.210812.016`) reports `Build.VERSION.SDK_INT = 29` to all apps despite running Android 12. This breaks any logic gated on `Build.VERSION.SDK_INT >= Build.VERSION_CODES.R` (30).

**Affected code pattern (broken):**
```kotlin
if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) {
    // never runs on the head unit — SDK_INT = 29 even though OS is Android 12
}
```

**General workaround:** Call Android 11+ APIs directly in a `try/catch(Throwable)`. If the method doesn't exist in the ROM's `framework.jar`, it throws `NoSuchMethodError` (an `Error` subclass — must catch `Throwable`, not `Exception`). Do NOT use `Build.VERSION.SDK_INT` as a gate for API availability on this device.

**Confirmed missing from A007 framework.jar:**
- `Environment.isExternalStorageManager()` — throws `NoSuchMethodError`
- `Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION` — no activity to handle the intent

This means the full `MANAGE_EXTERNAL_STORAGE` permission flow is unavailable on this device. See "Log Storage" section above for the resolution.

Full hardware details in `projects/coda/notes/android-coda-app-notes.md`.

---

## Gotchas

**Unicode in console output:** Python scripts printing to Windows console (cp1252) must not use non-ASCII characters. `can_replayer.py` had a `→` arrow that caused `UnicodeEncodeError` — replaced with `->`.

**USB permission on device:** The Android USB permission dialog fires on first dongle attach. If dismissed/denied, `USB permission denied` is logged and nothing starts. Unplug and replug to retry.

**`local.properties` not synced:** This file is gitignored by convention and not in SeaDrive sync. Must be recreated on each machine.

---

---

## :vtrux App — Architecture (2026-03-22)

`:vtrux` is a pure background logger — no display, no Compose. Verified working via replay test.

**Log path:** `/sdcard/VtruxLogs/` — public SD card, accessible to other apps and sync tools without root. Requires `MANAGE_EXTERNAL_STORAGE` (granted via `appops set com.reverseit.vtrux MANAGE_EXTERNAL_STORAGE allow` for ADB testing; prompted automatically on first app open on device).

**How `EXTRA_LOG_DIR` works in cancore:** `CanLoggingService` accepts an optional `EXTRA_LOG_DIR` string extra. If supplied, `logDir()` uses it directly (public path). If omitted, falls back to `getExternalFilesDir(null)/<VehicleName>Logs/` — backward compatible with Coda (`"coda"` → `"CodaLogs"`).

**USB event architecture — background-only logging:**

Android requires an Activity to receive `USB_DEVICE_ATTACHED` via manifest intent-filter. Rather than bring the main activity to the foreground on dongle insert, a two-component design is used:

- **`UsbLaunchActivity`** (`Theme.NoDisplay`, `noHistory=true`): Registered for `USB_DEVICE_ATTACHED`. Checks/requests USB permission then immediately calls `finish()`. The user never sees it.
- **`VtruxApplication`** registers a permanent process-level `BroadcastReceiver` for:
  - `com.reverseit.vtrux.USB_PERMISSION` — the permission result PendingIntent target (arrives after UsbLaunchActivity is already gone)
  - `ACTION_USB_DEVICE_DETACHED` — removes the device from the pipeline
  - On permission granted: calls `pipeline.addDevice()` then `startForegroundService` + `bindService` for `CanLoggingService`
- **`MainActivity`** (LAUNCHER only, portrait): Just requests storage/notification permissions and hands any already-connected dongles to `VtruxApplication.onDeviceReady()`. No USB receiver registered.

**Icon:** Via 3D chrome logo (`android-app/VIA-3D-Chrome-LOGO.webp`, 2000×464 RGBA). Converted to mipmap PNGs with transparent background via Pillow. Source file kept in `android-app/` for regeneration.

**Orientation:** Portrait (`MainActivity`). `UsbLaunchActivity` has no orientation constraint (irrelevant, never visible).

**No Compose:** `vtrux/build.gradle.kts` does not enable Compose. Depends on `activity-compose` only as a transitive source for `activity-ktx` (provides `registerForActivityResult` on `ComponentActivity`).

---

## Open Questions

- **USB hub hotplug reliability:** Multi-dongle attach/detach ordering with 3 simultaneous dongles not yet exercised. May need debounce or sequential init delay.
- **Log session boundaries in field:** Screen-on/off + 5s polling fallback is implemented; field testing in progress over actual drives. If unreliable, fall back to CAN-based ignition detection (see `projects/coda/notes/android-coda-app-notes.md` Phase 3).
- **Vtrux screen-on/off proxy:** Resolved — Vtrux uses `TRIGGER_POWER` (USB charge connect/disconnect) as the ignition proxy. Phone is powered by an ignition-switched USB-C charger. See Vtrux trigger mode section below.

---

## Power/USB Sequencing Bugs Fixed (2026-04-02)

Symptoms: replaying CAN into the phone after power connect caused overflow on the replay script; notification showed "Logging" even though no frames were flowing (dongle not on CAN bus). Three bugs identified.

### Bug 1: `onTriggerActive()` reset session unconditionally (double-start on every session)

`onServiceConnected()` calls `service.pipeline = pipeline` then immediately `service.notifyPowerState(powered)`. The pipeline setter starts `logJob` (opens T0 file). Then `notifyPowerState(true)` → `onTriggerActive()` cancelled the just-started logJob, reset `sessionTag` to a new timestamp, and opened a NEW T0 file — leaving an orphaned empty T0 from the setter. This happened on every session start.

Fix: added `if (logJob?.isActive == true) return` at the top of `onTriggerActive()`. If already logging, the trigger reconfirmation is a no-op. The session tag and segment index are not disturbed.

### Bug 2: `attemptRootOtgRecovery()` thread not abortable by `stopRescan()`

If the dongle naturally re-enumerated after the recovery thread had already started (e.g., re-enum at t=3s, recovery launched at t=4s), the recovery's `ufp` write would drop the hub upstream and detach the just-opened device. The post-recovery `doRescan()` would then fire into a confused state (rescan was already stopped by `stopRescan()` from the natural re-enum path).

Fix: added `@Volatile private var recoveryAborted = false` to `VtruxApplication`. `startRescan()` clears it; `stopRescan()` sets it. The recovery thread checks `recoveryAborted` after `proc.waitFor()`. If aborted: triggers `startRescan()` (to recover from any ufp disruption to the naturally re-enumerated device) instead of `doRescan()`.

### Bug 3: Notification stuck at "Logging" when dongle detaches (no visibility)

The notification only updated every 500 frames. When all dongles detached, it stayed at the last "X.X MB" value indefinitely. The user couldn't tell from the notification whether any dongle was actually active.

Fix: added `fun notifyBusChange()` to `CanLoggingService`. Called from `VtruxApplication`'s detach receiver on real device detach (`wasActive == true`). Shows "waiting for dongle" when count == 0, or "$N dongle(s)" when non-zero. The re-attach path already updates naturally via the 500-frame interval once frames start flowing.

### Diagnosis notes

If overflow persists after these fixes: pull the DebugLog (`nc <phone-ip> 9876`) while reproducing the issue. Key events to look for:
- `Root OTG recovery: su exited 1/13` — Magisk superuser grant was reset (re-grant in Magisk -> Superuser after each `adb install`)
- `Bus N: device error: Cannot open USB device` — `open()` failed, likely a timing issue or permission loss on re-enumeration
- `Innomaker detached` with no subsequent `gs_usb device=X: started` — device never re-initialized

---

## CAN Terminator — Broken (discovered 2026-04-02)

The 120-ohm CAN terminator resistor used on the bench test bus is broken (exact failure mode unknown). This was discovered at the end of the 2026-04-02 session, after all the power/USB sequencing debug work.

**Significance:** A missing terminator causes CAN bus signal integrity problems that produce overflow on the replay script — the exact same symptom we were debugging. It is unclear whether the bugs fixed in this session (double session-start, recovery race, notification staleness) were actually contributing to the overflow, or whether the broken terminator was the dominant cause all along.

**Status:** All software fixes were applied and installed regardless (they are correct improvements). Testing is blocked until a working terminator is available. Resume testing with a known-good terminator before concluding whether any remaining overflow is a software issue.

---

## Vtrux In-Truck Deployment — Bugs Fixed (2026-03-23)

### Device: OnePlus 7 Pro (HD1901), Android 14, Magisk root

ADB port at time of session: `10.0.0.45:38463` (changes each wireless debug session).

### Bug: Log session trigger wrong (screen instead of power)

`CanLoggingService` originally used screen on/off as the trigger for all apps. Added `EXTRA_TRIGGER_MODE` extra (`"screen"` / `"power"`). Vtrux passes `TRIGGER_POWER` — log starts on `ACTION_POWER_CONNECTED`, stops on `ACTION_POWER_DISCONNECTED`. Coda still uses `TRIGGER_SCREEN` (unchanged).

Initial state is read from the sticky `ACTION_BATTERY_CHANGED` broadcast using `EXTRA_PLUGGED` (more immediate than `BatteryManager.isCharging`). A 2-second delayed recheck coroutine closes the race window where power connected just before the service started.

### Bug: `startLogging()` called twice — `Stream closed` crash

When power connected, `onTriggerActive()` calls `startLogging()`. Then the dongle re-attaches, `onDeviceReady()` calls `startLoggingService()`, which sends another `onStartCommand` and re-delivers the binder. Two things caused double-start:
1. `onStartCommand` also calls `startLogging()` on every delivery
2. The `pipeline` setter also calls `startLogging()`

Fix: guard both call sites with `logJob?.isActive != true`. Also guard `onStartCommand` against resetting `sessionTag`/`segmentIndex` on re-deliveries by wrapping those assignments in `if (!sessionReady)`.

### Bug: `SecurityException` — `FOREGROUND_SERVICE_CONNECTED_DEVICE` on Android 14

Android 14 requires `FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE` + at least one "any of" permission (Bluetooth, USB device permission, WiFi, etc.) at the time `startForeground()` is called. On service restart after crash, USB device permission may not be recognized yet in the new process.

Fix: added `<uses-permission android:name="android.permission.CHANGE_NETWORK_STATE"/>` to `vtrux/AndroidManifest.xml`. This is a normal (install-time) permission that permanently satisfies the "any of" condition.

### Bug: `IllegalArgumentException` — `FLAG_MUTABLE` with implicit `PendingIntent` on Android 14

Android 14 disallows `FLAG_MUTABLE` with an implicit `Intent` (no component). The USB permission `PendingIntent` used `Intent(ACTION_USB_PERMISSION)` which has only an action string.

Fix: added `.setPackage(packageName)` to the intent in both `UsbLaunchActivity.checkAndRequestPermission()` and `VtruxApplication.doRescan()`. This makes the intent package-explicit while keeping it mutable so UsbManager can write `EXTRA_DEVICE` / `EXTRA_PERMISSION_GRANTED` into it.

### Bug: USB dongle not recovering after hub external power switch

**Root cause:** When the ignition-switched hub power source turns on, the hub switches from bus-powered (phone provides 5V) to self-powered (external 12V→5V adapter). During this transition the hub cuts power to one or more downstream ports. The CAN dongle's port does not recover on its own.

**Phone:** OnePlus 7 Pro stays in OTG host mode (`dfp`, `data_role: host`) throughout — OTG mode is not dropped. The issue is entirely within the hub's port power management.

**What doesn't work:**
- `echo host > /sys/class/typec/port0/data_role` — wrong path on this device (node is `otg_default`)
- `echo host > /sys/class/dual_role_usb/otg_default/mode` — writing `host` to mode has no effect
- Hub unbind/rebind (`/sys/bus/usb/drivers/usb/unbind`) — hub re-enumerates Ethernet adapter but not CAN dongle port
- Disabling hub autosuspend + rebind — no change

**What works:** Toggle the phone's USB role from host to device and back:
```sh
echo ufp > /sys/class/dual_role_usb/otg_default/mode   # drop to device mode
# wait for hub devices to disappear (~300-500ms)
echo dfp > /sys/class/dual_role_usb/otg_default/mode   # back to host mode
```
This power-cycles the hub from the phone's side, causing all hub ports to re-enumerate cleanly.

**Relevant sysfs paths (OnePlus 7 Pro):**
- `/sys/class/dual_role_usb/otg_default/mode` — values: `dfp` (host) / `ufp` (device). Requires root.
- `/sys/class/dual_role_usb/otg_default/data_role` — values: `host` / `device` (read-only reflection)
- `/sys/bus/usb/devices/` — enumerate connected USB devices. Hub is typically `2-1` or `1-1` depending on bus assignment after role toggles.
- Hub: Genesys Logic USB3.1 Hub (VID `05e3`, PID `0626`), `maxchild=4`

**Implementation in `VtruxApplication.attemptRootOtgRecovery()`:**
- Runs on a daemon thread via `Runtime.exec(["su", "-c", cmd])`
- Command: switch ufp, poll until hub devices disappear from sysfs (max ~2s at 300ms intervals), switch dfp
- Also tries `/sys/class/typec/*/data_role` with `device`/`host` for other phone models
- Called at rescan attempts 2 and 6 (4s and 12s after real-device detach)
- On success: immediately posts an extra rescan to `rescanHandler`
- Fails gracefully (exit 1 / IOException) on unrooted phones — rescan loop continues as fallback
- Requires Magisk root grant for the vtrux app (Magisk → Superuser → Grant)

### Bug: Phantom detach events resetting rescan counter

The hub emits several USB detach events for transient device IDs (2003, 2004) during the power transition. These phantom devices were triggering `startRescan()`, resetting `rescanAttempts` to 0 and delaying the recovery.

Fix: `CanPipelineManager.removeDevice()` now returns `Boolean` (true = was active and removed, false = unknown/phantom device). `VtruxApplication` only calls `startRescan()` on detach if the device was active (`removed == true`) or if no rescan is currently running (`!rescanActive`). Phantom detaches during an active rescan are ignored.

### OTG Bus Power Cut -- Abandoned (2026-04-01)

**Goal:** When the truck is off (no charger), switch the phone to USB device mode (`ufp`) to cut the 5V OTG bus supply to the hub and CAN dongles, preventing battery drain while parked.

**Approach tried:** Write `ufp` to `/sys/class/dual_role_usb/otg_default/mode` via Magisk root (`su -c`). The write returns exit code 0, but the OnePlus 7 Pro's OTG driver auto-reverts to `dfp` (host) after 3-4 seconds, re-powering the hub. A hold loop that re-asserts `ufp` every 0.8-2 seconds was tried but the VBUS power still cycles visibly.

**Why it doesn't work on the OnePlus 7 Pro (HD1901, Android 14, kernel 4.14.348-openela-perf):**

1. **`dual_role_usb/*/mode` write doesn't stick.** The Qualcomm USB driver's CC pin detection hardware overrides the software role within 3-4 seconds. Even writing every 800ms (faster than the auto-revert) doesn't prevent VBUS toggling -- the hardware VBUS boost appears to be controlled independently of the software mode.

2. **SSUSB controller sysfs is locked down.** The controller at `/sys/devices/platform/soc/a600000.ssusb/` exposes `usb_data_enabled` and `mode` nodes, but the kernel rejects writes even as root with SELinux permissive. The SELinux context (`sysfs_usb_data_enabled`, `vendor_sysfs_usb_device`) has no write policy for the `magisk` domain, and the kernel's `store` callback appears to enforce additional permission checks beyond DAC/MAC.

3. **VBUS regulator is read-only.** The `smb5-vbus` regulator at `/sys/class/regulator/regulator.99/` reports `state=disabled` while the hub is clearly powered, suggesting VBUS is controlled by a lower-level PMIC path not exposed to userspace.

4. **Driver unbind blocked.** Writing to `/sys/bus/platform/drivers/msm-dwc3/unbind` is rejected with `Permission denied` regardless of root or SELinux state.

5. **`sys.usb.config none`** disables the USB stack entirely (killing ADB) but does NOT cut VBUS to the hub.

**Additional issues encountered during the investigation:**
- Writing `ufp` while the charger goes through the USB hub kills both OTG data AND charger detection (chicken-and-egg: phone can't detect power to exit ufp because ufp killed the charger passthrough).
- `POWER_CONNECTED` events during ufp hold were originally suppressed as "hub capacitor discharge" phantoms, but this also suppressed real charger connections. Fixed by removing the suppression and using a 5s settle + `BatteryManager.EXTRA_PLUGGED` read instead.

**Resolution:** OTG bus power management removed from the app entirely (2026-04-01). All `su` calls, ufp/dfp role switching, OTG recovery, and the ufp hold loop have been stripped. The app now only tracks charger state for log start/stop (TRIGGER_POWER mode).

**Intended hardware solution:** A 5V relay on the hub's upstream USB cable, switched by the same ignition-switched 12V source that powers the hub's external supply. When ignition is off, the relay opens and physically disconnects the hub from the phone. This is cheap (~$5), reliable, and eliminates the entire software OTG power management problem.

**What the app does now (post-cleanup):**
- `POWER_CONNECTED` -> immediately set `powered=true`, notify logging service to start
- `POWER_DISCONNECTED` -> 5s debounce (filters PD transients), then `powered=false`, notify service to stop
- USB dongle attach/detach handled normally regardless of power state
- `attemptRootOtgRecovery()` retained for hub recovery only (ufp->wait->dfp toggle at rescan attempts 2 and 6) -- this is NOT for OTG power management, just for un-sticking a hub that drops the dongle after PD renegotiation

---

## Session 2026-04-01 — L-EEHTRBPN2 Setup + Power Sequencing Rewrite

### Build environment (L-EEHTRBPN2)
- Android Studio installed fresh (Meerkat era), JBR JDK 21, SDK path `<ANDROID_SDK_DIR>`
- `local.properties` updated for this machine's username
- First build required Gradle to auto-download build-tools 34.0.0 and platform 34; initial download corrupted due to `FileAlreadyExistsException`, fixed by cleaning `.temp/` folder and retrying
- See "Build Environment -- L-EEHTRBPN2" section above for full details

### ADB on L-EEHTRBPN2
- ADB pairing via PowerShell works: `& '<ANDROID_SDK_DIR>\platform-tools\adb.exe' pair <ip:port> <code>`
- Bash `adb pair` with positional code argument gives "protocol fault" -- use PowerShell for all adb commands on this machine
- mDNS discovery works after pairing (device shows as `adb-<guid>._adb-tls-connect._tcp`)
- If mDNS doesn't find the device, `adb connect <ip:port>` using the port from the Wireless Debugging main screen (not the pairing port)

### Devices
- OnePlus 7 Pro (HD1901): wireless ADB, guid `adb-16e7d2b3-RSkDoo`
- Pixel 8 Pro (husky): USB, serial `41270DLJG00054`
- Both have the vtrux app installed

### VtruxApplication rewrite (2026-04-01)
Complete rewrite of the power state machine. Old code had separate connect/disconnect debounce timers, phantom event suppression, ufp hold loop, and OTG recovery -- all interacting in a tangled state machine that created feedback loops. New code:

1. **POWER_CONNECTED while unpowered** -> immediate transition to POWERED (no debounce). If phantom, POWER_DISCONNECTED follows shortly and the 5s settle handles it.
2. **POWER_DISCONNECTED while powered** -> 5s settle, then read `BatteryManager.EXTRA_PLUGGED` to confirm. Filters PD renegotiation transients.
3. No ufp/dfp role switching (abandoned, see section above).
4. Hub recovery (`attemptRootOtgRecovery`) retained at rescan attempts 2 and 6.

### CanLoggingService fixes (2026-04-01)
- **onDestroy receiver crash**: In TRIGGER_POWER mode, `triggerReceiver` was never registered but `onDestroy` tried to unregister it. Fixed by checking `triggerMode != TRIGGER_SCREEN` before unregister.
- **Notification clobbering**: `onStartCommand` always overwrote the notification with generic "Logging..." even when logging was active with a detailed notification. Fixed by checking `logJob?.isActive` and preserving the detailed format.
- **Notification icon**: Added `ic_notification` drawable (white VIA logo silhouette) for the status bar. `appIconRes()` now prefers `ic_notification` from drawable, falling back to `ic_launcher` from mipmap. Coda is unaffected (no `ic_notification` resource, uses ic_launcher as before).

### App icon
- Vtrux launcher icon updated: VIA chrome logo on orange circle background
- Generated via Pillow from `android-app/VIA-3D-Chrome-LOGO.webp`

### Known issue: PD renegotiation drops dongle
When the charger is plugged or unplugged, USB Power Delivery renegotiation on the phone's USB-C port disrupts the hub, causing the Innomaker dongle to detach for ~10-15 seconds. The dongle eventually recovers on its own (or via root OTG recovery at rescan attempts 2/6). **Workaround for bench testing:** plug in the charger, wait 15 seconds for the dongle to stabilize, then start the CAN replayer. Don't change charger state while replaying.

### Magisk root after reinstall
Reinstalling the app via `adb install` resets the Magisk superuser grant. Must re-grant in Magisk -> Superuser after each install. Without it, `attemptRootOtgRecovery()` fails with `su exited 1` or `su exited 13`.

---

## Session 2026-04-03 — Bench Replay Validation + Power Settle Tuning

### ADB on Desktop

ADB is on the system PATH — use `adb` directly, no full SDK path needed.

**Always use PowerShell, never Git Bash for ADB.** Git Bash mangles `/sdcard/...` device paths into `C:/Program Files/Git/sdcard/...`. Run ADB commands directly from PowerShell or via `powershell -Command "adb ..."`.

**Transport IDs:** After pairing, the OnePlus 7 Pro (guid `16e7d2b3`) shows up as mDNS transport `adb-16e7d2b3-RSkDoo._adb-tls-connect._tcp` (no space variant). If the device shows `offline` after a WiFi drop, run `adb disconnect 10.0.0.124:<port>` then `adb connect 10.0.0.124:<port>` using the current port from Developer Options → Wireless Debugging. The port changes every time wireless debugging is toggled — check the phone screen each session.

```powershell
# Pull a log file
adb -s "adb-16e7d2b3-RSkDoo._adb-tls-connect._tcp" pull /sdcard/VtruxLogs/vtrux_<session>_T0.log E:\path\to\out.log

# Shell command
adb -s "adb-16e7d2b3-RSkDoo._adb-tls-connect._tcp" shell "ls -lh /sdcard/VtruxLogs/"

# Install (always -r, see ADB install rule above)
adb -s "adb-16e7d2b3-RSkDoo._adb-tls-connect._tcp" install -r vtrux\build\outputs\apk\debug\vtrux-debug.apk
```

**Building on Desktop:** System Java is 1.8, which AGP 8.3.2 rejects. Use `build_vtrux.ps1` (in `android-app/CanLoggerApps/`) which sets `JAVA_HOME` to the Android Studio1 JBR before invoking Gradle:
```powershell
powershell -File "android-app/CanLoggerApps/build_vtrux.ps1"
```
APK output: `vtrux/build/outputs/apk/debug/vtrux-debug.apk`

`local.properties` must have `sdk.dir=<ANDROID_SDK_DIR>` (not `<user>`).

### Terminator fixed; TX buffer overflow root-caused

Broken CAN terminator replaced (2026-04-03). Replay test with `generator on then off.log` confirmed:
- Kvaser TX LED solid, Innomaker RX LED blinking at full speed — bus healthy
- Logger accumulating data continuously
- `Send error on frame N: Transmit buffer overflow [Error Code -13]` warnings still appearing

Root cause of TX overflow: **the source log has 3 buses, each at ~59-60% utilization**. The replayer has one Kvaser dongle, so all three buses get merged onto it — ~7,100 combined fps against a ~3,700 fps limit. Overflow is structural in this configuration.

Fix: use `--bus N` to select a single bus. For the PT bus: `--bus 3`.

### Vtrux bus utilization

Measured from `generator on then off.log` (64.2s, truck running):

| Bus | Role | Frames | FPS | Avg DLC | Utilization |
|-----|------|--------|-----|---------|-------------|
| 1 | OBD | 158,954 | 2,475 | 6.4 | ~60% |
| 2 | Vehicle | 152,406 | 2,373 | 6.5 | ~59% |
| 3 | Powertrain | 144,540 | 2,251 | 7.1 | ~59% |

All three buses at roughly 60% of 500 kbps capacity during normal truck operation.

### Replay/logger correspondence confirmed

Pulled `/sdcard/VtruxLogs/vtrux_20260403_194203_T0.log` (50 MB) and compared against source:
- 205 of 260 source IDs present (55 missing are overflow casualties — use `--bus 3` for a lossless PT bus replay)
- T0 duration 251.7s vs source 64.2s: replayer was running `--loop` (~3.9 passes)
- Data ranges in captured frames match source exactly

### Power settle time extended to 5 minutes

`POWER_SETTLE_MS` set to `300_000L` (5 min) in `VtruxApplication`. The GM interior 12V may cycle on and off while the driver is entering or starting the truck. 5 minutes keeps the logger running continuously through those transients and only stops once the truck is clearly off. `POWER_CONNECTED` still cancels the pending stop immediately — no delay on truck start.

During testing this session the value was temporarily set to `60_000L` (1 min). Restored to `300_000L` once the underlying bugs (see below) were confirmed fixed.

### Bug: Notification not updating after power disconnect (notification rate-limiting)

**Symptom:** Logging stopped (file size stopped growing) but notification stayed at "Logging | HH:mm | seg TN | X.X MB" indefinitely instead of switching to "Waiting for power...".

**Root cause:** Android 13+ enforces a hard 5 notifications/second rate limit per package. At ~11,000 fps across 3 buses, `CanLoggingService` was calling `NotificationManager.notify()` every 45ms (~22/s) via the `writer.frameCount % 500 == 0` check. Android was silently dropping most updates — including the critical "Waiting for power..." call from `stopLogging()`.

Confirmed in logcat:
```
E NotificationService: Package enqueue rate is 5.0159864. Shedding 0|com.reverseit.vtrux|1|null|10338
```

**Fix:** Added a timestamp gate to `updateNotification()` in `CanLoggingService` — periodic updates are throttled to at most once every 2 seconds. `stopLogging()` and other state-change calls go directly to `updateNotificationText()`, bypassing the throttle, so they always land.

```kotlin
private var lastNotifUpdateMs = 0L

private fun updateNotification(writer: BusmasterWriter) {
    val now = System.currentTimeMillis()
    if (now - lastNotifUpdateMs < 2_000L) return
    lastNotifUpdateMs = now
    // ... build and post notification
}
```

### Battery optimization exemption

`ACTION_POWER_DISCONNECTED` was not reaching the app while it was in a restricted state (LineageOS aggressive background management). Exempted via ADB:
```powershell
adb -s <transport> shell dumpsys deviceidle whitelist +com.reverseit.vtrux
adb -s <transport> shell cmd appops set com.reverseit.vtrux RUN_ANY_IN_BACKGROUND allow
```
Both commands persist across reboots. After exemption, power broadcasts arrive reliably.
