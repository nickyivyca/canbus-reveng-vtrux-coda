# Android Emulator (AVD) Bringup — 7-inch Head Unit Simulation

Bringup notes for running the `:coda` app on an Android Virtual Device that approximates the
A007 head unit's 7-inch display. Established 2026-07-23 on Desktop.

Purpose: a layout-and-logic rig for the Coda app's display layer (page compositing, pager
behaviour, Compose layout) without needing the car or the head unit. It is **not** a substitute
for on-device testing — see [Limitations](#limitations).

---

## AVD Configuration

| Property | Value |
|----------|-------|
| AVD name | `7_WSVGA_Tablet_API_31` |
| Device profile | 7" WSVGA (Tablet) |
| Resolution | 1024 x 600 |
| Density | 160 dpi (mdpi) — so 1024 x 600 **dp** of layout space |
| System image | API 31 (Android 12), `google_apis`, **x86_64** |
| RAM / VM heap | 2048 MB / 256 MB (emulator forces heap up to its 512 MB minimum) |
| Internal storage | 6 GB |
| Cameras | none |
| Device frame | disabled (`showDeviceFrame = no`, `skin.path = _no_skin`) |
| Initial orientation | landscape |
| `hw.mainKeys` | **`yes`** — see [Nav bar](#nav-bar-hwmainkeys) |
| `hw.gpu.mode` | `host` |

API 31 was chosen to match the head unit's actual OS (Android 12). x86_64 is required: the host
is Intel x86_64, and the emulator has no arm64 translation layer on Windows, so `arm64-v8a`
images cannot run at all. The app has no NDK/JNI code and ships no `.so` files, so the ABI
difference from the ARM head unit is irrelevant to app behaviour.

### AVD location — not the default path

`ANDROID_SDK_HOME=C:\Android` is set in the user environment on Desktop, which relocates
the Android home directory. The AVD therefore lives at:

```
C:\Android\.android\avd\7_WSVGA_Tablet_API_31.avd\
```

**not** `~/.android/avd/`, which is empty. Any tooling that assumes the default path will not
find the AVD. See `android-app/android-tools-reference.md` for the per-machine value.

---

## Launching

```powershell
$env:ANDROID_SDK_HOME = 'C:\Android'
Start-Process -FilePath '<ANDROID_SDK_DIR>\emulator\emulator.exe' `
  -ArgumentList '-avd','7_WSVGA_Tablet_API_31'
```

Add `-no-snapshot-load` to force a cold boot (required after changing any `config.ini` value
that maps to a boot property — see [Nav bar](#nav-bar-hwmainkeys)).

**Do not launch the emulator from a backgrounded Bash tool task.** Its lifetime gets bound to
that task, and when the task ends the emulator receives an exit request and shuts down
(`received exit request from parent process`). Use `Start-Process` so it runs detached.

---

## Emulator version requirement

**Emulator 32.1.14.0 could not boot this AVD. Emulator 36.6.11.0 boots it fine.**

Symptom on 32.1.14 with `hw.gpu.mode = host`: `emulator.exe` and `qemu-system-x86_64.exe` both
start and stay resident, but the guest never boots. Diagnostic signature:

- qemu accumulates ~1 second of CPU time total and then stops — 0.016 s over a 30 s sample,
  with zero working-set growth.
- No console port 5554 and no adb port 5555 are ever opened (qemu listens only on ephemeral
  gRPC ports when launched from Android Studio).
- `adb devices` is empty; Android Studio also cannot see the device.
- `-verbose` output stops after four lines, the last two being:
  ```
  WARNING | Please update the emulator to one that supports the feature(s): Vulkan
  WARNING | Failed to process .ini file ...\quickbootChoice.ini for reading.
  ```

This is a hang *before the guest vCPU starts*, which is why it looks so unlike a slow boot.

The hypervisor was never the problem. `emulator-check accel` returns 0 and the verbose log
confirms `WHPX (10.0.19045) is installed and usable` / `Windows Hypervisor Platform accelerator
is operational`. `emulator-check` also emits a "Please disable Hyper-V" line alongside the
success message — that advisory is misleading here and can be ignored; WHPX works with Hyper-V
enabled.

### Evidence and its limits

| Emulator | GPU mode | Vulkan feature | Result |
|----------|----------|----------------|--------|
| 32.1.14.0 | `host` | default (enabled) | Hangs before guest boot |
| 32.1.14.0 | `swiftshader_indirect` | disabled via `-feature -Vulkan` | Boots |
| 36.6.11.0 | `host` | default (enabled) | Boots, ~21 s CPU in first 20 s wall |

The two overrides were applied together on 32.1.14, so **it was not isolated whether GPU host
mode or the Vulkan feature flag was the trigger** on the old emulator. It does not matter in
practice — 36.6.11 with stock `hw.gpu.mode = host` works, which is the configuration in use.
If a future machine is stuck on an old emulator, the known-good workaround is:

```
-gpu swiftshader_indirect -feature -Vulkan
```

at the cost of software rendering (bad for judging animation and fling/snap behaviour).

Updating is done through Android Studio: **SDK Manager -> SDK Tools -> Android Emulator**.
There is no `cmdline-tools` package installed on Desktop, so `sdkmanager` is not available
for headless package management — the SDK contains only the deprecated `tools/bin/sdkmanager.bat`,
which fails on JDK 17 with `NoClassDefFoundError: javax/xml/bind/annotation/XmlSchema` because
JAXB was removed from the JDK in Java 11. Install "Android SDK Command-line Tools (latest)" from
the same SDK Manager screen if headless SDK management is wanted.

---

## Nav bar (`hw.mainKeys`)

The stock 7" WSVGA profile sets `hw.mainKeys = no`, which gives the guest a software navigation
bar. That bar consumes the bottom strip of the panel, so the app receives roughly 1024 x 560
instead of the full 1024 x 600 — enough to invalidate any layout calibrated against it.

Set in `config.ini`:

```
hw.mainKeys = yes
```

This maps to the `qemu.hw.mainkeys` boot property, so **it only takes effect on a cold boot** —
a quick-boot snapshot restore carries the old value along with the rest of the saved state.
Launch once with `-no-snapshot-load` after changing it; the snapshot saved on that run then
carries the new setting.

Verification quirk: after the change, `adb shell getprop qemu.hw.mainkeys` returns *empty*, not
`1`. Recent emulators only set that property to `0` to force the software bar and omit it
otherwise. Confirm visually via `adb exec-out screencap -p` instead — the app should reach the
bottom edge of the frame.

---

## Installing and running the app

Build (see `android-app/android-tools-reference.md` for the JAVA_HOME requirement):

```bash
cd "<repo-root>/NotGit/reverse-it" && ANDROID_HOME="<ANDROID_SDK_DIR>" \
JAVA_HOME="C:/Program Files/Android/Android Studio1/jbr" \
PATH="C:/Program Files/Android/Android Studio1/jbr/bin:$PATH" \
android-app/CanLoggerApps/gradlew.bat -p android-app/CanLoggerApps :coda:assembleDebug --console=plain
```

Install and launch:

```bash
ADB="<ANDROID_SDK_DIR>/platform-tools/adb.exe"
"$ADB" install -r android-app/CanLoggerApps/coda/build/outputs/apk/debug/coda-debug.apk
"$ADB" shell am start -n com.reverseit.coda/.MainActivity
```

Screenshot:

```bash
"$ADB" exec-out screencap -p > <path>/shot.png
```

### One-time storage permission grant

On first launch the app immediately bounces to the system "All files access" settings page and
the green screen is never reached. This is expected: `MainActivity.onCreate` calls
`Environment.isExternalStorageManager()`, which on a genuine API 31 image exists and returns
false, so the app opens the settings intent. (On the real A007 head unit that method is absent
from `framework.jar` entirely, which is why this is emulator-only behaviour.)

Grant it once per AVD:

```bash
"$ADB" shell appops set --uid com.reverseit.coda MANAGE_EXTERNAL_STORAGE allow
```

The grant survives cold boots and app reinstalls; it is lost only on a data wipe. After granting,
logcat shows `isExternalStorageManager() = true` / `storage manager not needed`.

`<uses-feature android:name="android.hardware.usb.host" />` in the Coda manifest has no
`android:required="false"`, so it defaults to required. This does **not** block emulator
deployment — `adb install` ignores `uses-feature`, which is only enforced by app stores.

---

## USB CAN in the emulator — not possible

The Android emulator has no USB host passthrough. `UsbManager.deviceList` is always empty inside
an AVD and there is no exposed QEMU flag to bind a host USB device into the guest, so the
Innomaker gs_usb dongle can never appear as a `UsbDevice`. `tools/can_replayer.py` does not help
either — it puts frames on a physical bus, which requires a physical dongle on the guest side.

Consequence: with the current code the app runs in the emulator but shows **default state only**
(SoC 0%, ranges 0, `DNNN` background, notches at their zero positions). That is sufficient for
layout work but not for verifying decode or display logic against real values.

Feeding real data in requires a code change, currently unimplemented:

- `CodaViewModel.attach(pipeline: CanPipelineManager)` only ever touches `pipeline.frames`, so
  narrowing the parameter to `Flow<CanFrame>` decouples it from USB.
- A debug-only replay source that emits `CanFrame`s at recorded inter-frame timing, fed from a
  log pushed to the app's external files dir with `adb push`. `:cancore` already has
  `BusmasterWriter.kt`; a matching reader makes any existing capture directly replayable.
- `MainActivity.onCreate` picks the replay source when the USB scan finds nothing.

An alternative is a network feed from the PC (the emulator reaches the host at `10.0.2.2`),
reusing `RemoteCanDataSource` + `tools/can_display_server.py`. That path carries *decoded
signals* rather than raw frames, though, and `CodaSignalDecoder` consumes raw frames — so it
would need either a raw-frame server mode or routing Coda through the decoded-signal
abstraction.

---

## Limitations

The emulator does not reproduce the A007 head unit's ROM-level quirks, all of which have
previously caused real bugs (see `android-app/android-coda-app-notes.md` Phase 2):

- `Build.VERSION.SDK_INT` spoofed to 29 while running Android 12
- `isExternalStorageManager()` and the `MANAGE_EXTERNAL_STORAGE` settings activity missing from
  `framework.jar`
- scoped-storage behaviour and the writable log path
- USB host and dongle lifecycle
- the head unit's real screen density

**The head unit's actual resolution and density are not recorded anywhere.** The AVD assumes
1024 x 600 mdpi. This matters for any from-scratch Compose layout, because Compose lays out in
dp: 1024 x 600 at mdpi gives 1024 x 600 dp, but the same panel at hdpi would give only about
683 x 400 dp. The existing green screen is immune (all overlay positions are fractions of the
canvas) but new screens will not be. Since the A007 has no ADB, the cheapest way to get ground
truth is to log `resources.displayMetrics` from `CodaApplication` and read it back over the
app's existing debug log server on port 9876.

Treat the emulator as a layout-and-logic rig. Anything touching storage, permissions, USB, or
display metrics still needs a build dropped on the real head unit to confirm.
