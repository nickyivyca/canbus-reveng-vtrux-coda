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

### After hours of uptime the system server can crash-loop (seen 2026-09-26)

At ~5 h uptime and load ~9, `adb install` failed with "Can't find service: package", then "Cannot
access system provider: 'settings' before system providers are installed", while
`sys.boot_completed` still read 1. `adb reboot`, then wait for `sys.boot_completed` 1 plus ~20 s,
fixed it. Installed apps and their files survive.

### Injected GPS fixes carry time since 1970, not since boot (found 2026-09-26)

`adb emu geo nmea` (and the earlier `geo fix`) produce fixes whose `elapsedRealtimeNanos` is wall
time since the epoch -- `dumpsys location` showed `et=+20723d...` with 1671 s of uptime. Anything
that pairs a fix with other data by time sees it decades in the future. The app now guards against
it (`GpsRateAccumulator.fixTimeNanos`). Read only the `et=` and `vel=` fields of `dumpsys location`
if you check this: the full line has coordinates, and the AVD may still hold a position from an
earlier `geo fix`.

`adb reverse` also has a trap: a connect to a reversed port **always succeeds on the device**, even
with nothing listening on the PC, and the stream then ends immediately.

### Two adb traps when staging files for the app (found 2026-09-26)

- **Git Bash rewrites device paths.** `adb shell ls /sdcard/...` from Git Bash becomes
  `C:/Program Files/Git/sdcard/...`. Prefix commands with `export MSYS_NO_PATHCONV=1`.
- **A file or folder the shell creates under the app's external files dir is not writable by the
  app** (it is owned by uid 2000, and the app gets `EACCES`). Reading works, so logs pushed into
  `CodaLogs/` are fine; a TPMS epoch file must be created by the app (press SET on page 3). The
  shell can then append to the app-owned file. `run-as` cannot reach `/sdcard/Android/data`.
  Never `mkdir` `CodaLogs/tpms` from the shell: the app then cannot create files in it.

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

## USB CAN in the emulator — not possible (Windows; superseded on Linux)

**Superseded on the Linux box 2026-10-28:** a real Innomaker can be passed through to the
AVD on a Linux host -- see [USB passthrough on the Linux box](#usb-passthrough-on-the Linux box-linux).
What follows was written on Desktop (Windows) and was not re-tested there.

The Android emulator has no USB host passthrough. `UsbManager.deviceList` is always empty inside
an AVD and there is no exposed QEMU flag to bind a host USB device into the guest, so the
Innomaker gs_usb dongle can never appear as a `UsbDevice`. The shared replayer (`tools/can_replayer.py` in the can-tools git clone) does not help
either — it puts frames on a physical bus, which requires a physical dongle on the guest side.

Consequence: with the current code the app runs in the emulator but shows **default state only**
(SoC 0%, ranges 0, `DNNN` background, notches at their zero positions). That is sufficient for
layout work but not for verifying decode or display logic against real values.

**Superseded 2026-09-26: real CAN traffic now reaches the app in the AVD through the SLCAN
harness** -- `tools/slcan_bridge.py --busmaster` plus `debug.coda.slcan`; see `tools/tools.md`
and `android-app/android-coda-tpms-implementation.md` § Emulator harness. What follows is the
earlier analysis, kept for the record.

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

## the Linux box (Linux) bringup

Set up 2026-10-18. User-local install, no sudo:

| Component | Location | Version |
|-----------|----------|---------|
| Android Studio | `<home>/android-studio` | 2026.2.1.8 (rabbit1) |
| Android SDK | `<home>/Android/Sdk` | cmdline-tools 23.0, platform-tools 37.0.1 |
| Emulator | `~/Android/Sdk/emulator/emulator` | 37.2.12 |
| Gradle JDK | `<home>/jdk-21` | Temurin 21.0.12 |
| AVD | `~/.android/avd/7_WSVGA_Tablet_API_31.avd` | API 31, google_apis, x86_64 |

`cmdline-tools;latest` is installed here, unlike Desktop, so `sdkmanager` and `avdmanager`
are available. Package list installed:

```bash
export JAVA_HOME=$HOME/android-studio/jbr
~/Android/Sdk/cmdline-tools/latest/bin/sdkmanager --sdk_root=$HOME/Android/Sdk \
  "platform-tools" "emulator" "platforms;android-31" "platforms;android-34" \
  "build-tools;34.0.0" "system-images;android-31;google_apis;x86_64"
```

KVM is available and usable (`emulator -accel-check` prints `KVM (version 12) is installed and
usable`). The user does not need to be in the `kvm` group: `/dev/kvm` carries a `user:<user>:rw-`
ACL.

### AVD creation

```bash
export JAVA_HOME=$HOME/android-studio/jbr
echo no | ~/Android/Sdk/cmdline-tools/latest/bin/avdmanager create avd \
  -n 7_WSVGA_Tablet_API_31 \
  -k "system-images;android-31;google_apis;x86_64" \
  -d "7in WSVGA (Tablet)"
```

Then edit `~/.android/avd/7_WSVGA_Tablet_API_31.avd/config.ini` to match the Desktop AVD:
`hw.mainKeys=yes`, `hw.gpu.enabled=yes`, `hw.gpu.mode=host`, `hw.ramSize=2048`,
`vm.heapSize=256M`, `disk.dataPartition.size=6G`, `hw.camera.back=none`,
`showDeviceFrame=no`, `skin.path=_no_skin`, `skin.name=1024x600`,
`hw.initialOrientation=landscape`. Resolution/density come from the stock profile as
1024x600 @ 160 dpi. The AVD directory is the default `~/.android/avd/` because
`ANDROID_SDK_HOME` is unset on this machine.

### Launching

GUI (once a desktop session is available):

```bash
~/Android/Sdk/emulator/emulator -avd 7_WSVGA_Tablet_API_31
```

or `studio` for the IDE. To test boot headlessly:

```bash
ANDROID_SDK_ROOT=$HOME/Android/Sdk ANDROID_HOME=$HOME/Android/Sdk \
  $HOME/Android/Sdk/emulator/emulator -avd 7_WSVGA_Tablet_API_31 \
  -no-window -no-audio -no-snapshot-load -gpu swiftshader_indirect -no-boot-anim
```

Use the background-process tool (or `nohup`/detach) rather than a foreground Bash call, so the
emulator's lifetime is not tied to the command. A cold boot took ~40 s. `adb emu kill` performs a
clean shutdown and leaves the snapshot saved for the next launch.

### Build, install, run

Gradle 8.4 / AGP 8.3.2 need Java 17-21, **not** the Studio JBR (Java 25). The tree now has a Unix
`gradlew` script alongside `gradlew.bat`.

```bash
ANDROID_HOME="$HOME/Android/Sdk" JAVA_HOME="$HOME/jdk-21" \
PATH="$HOME/jdk-21/bin:$PATH" \
android-app/CanLoggerApps/gradlew -p android-app/CanLoggerApps :coda:assembleDebug --console=plain

ADB=$HOME/Android/Sdk/platform-tools/adb
$ADB install -r android-app/CanLoggerApps/coda/build/outputs/apk/debug/coda-debug.apk
$ADB shell appops set --uid com.reverseit.coda MANAGE_EXTERNAL_STORAGE allow
$ADB shell pm grant com.reverseit.coda android.permission.ACCESS_FINE_LOCATION
$ADB shell pm grant com.reverseit.coda android.permission.ACCESS_COARSE_LOCATION
$ADB shell am start -n com.reverseit.coda/.MainActivity
```

Note `POST_NOTIFICATIONS` cannot be granted on an API 31 image (the permission does not exist
there; it was added in API 33).

Verified 2026-10-18: cold boot succeeded, `wm size` reported `1024x600`, `wm density` 160,
the app installed and `MainActivity` was the resumed activity, and logcat showed
`isExternalStorageManager() = true` / `storage manager not needed`.

## USB passthrough on the Linux box (Linux)

Measured 2026-10-28 (plan `plans/gs-usb-error-frames.md` Step 2). The unfixed Vtrux debug
build in `7_WSVGA_Tablet_API_31` opened the Innomaker through `UsbManager` and logged frames
sent by the IXXAT on the same bus: `0x123` x200 and `0x124` x1200 complete and in sequence, an
extended `0x18FF0001`, and after one 250 kbit burst the Bug 11 line
`Rx 1 0xC s 8 00 30 02 00 00 00 00 FF` -- an error report logged as a data frame. So the app's
real gs_usb code can be put in front of real bus faults on the desk. The rig (`canctl`, the
IXXAT, the udev rule) is in `tools-reference.md`, *the Linux box SocketCAN rig*.

1. **Release the adapter from the host:** `sudo -n /usr/local/sbin/canctl gs_usb unbind`
   (`can0` disappears). `canctl gs_usb bind` gives it back once the emulator has exited.
2. **Launch** (detached, as above) with the passthrough options appended:

   ```bash
   ANDROID_SDK_ROOT=$HOME/Android/Sdk ANDROID_HOME=$HOME/Android/Sdk \
     $HOME/Android/Sdk/emulator/emulator -avd 7_WSVGA_Tablet_API_31 \
     -no-window -no-audio -no-snapshot -writable-system -gpu swiftshader_indirect -no-boot-anim \
     -qemu -device qemu-xhci,id=xhci -device usb-host,bus=xhci.0,vendorid=0x1d50,productid=0x606f
   ```

   Emulator 37.2.12's QEMU has libusb host support built in (`hw/usb/host-libusb.c`); the
   guest kernel enumerates the adapter at boot (`/sys/bus/usb/devices/1-1`, `USB2CAN V3.4.3`).
   Only this form was tested; the shorter `-usb -device usb-host,...` was not.
3. **The image does not declare USB host support**, and without the feature
   `UsbManager.deviceList` stays empty although the kernel sees the device. Done once,
   2026-10-28: `adb root`, `adb remount`, reboot; write
   `/vendor/etc/permissions/android.hardware.usb.host.xml` containing
   `<permissions><feature name="android.hardware.usb.host" /></permissions>`; reboot. Then
   `pm list features` shows `android.hardware.usb.host` and `dumpsys usb` lists the adapter under
   `host_manager`. The file lives in the AVD's writable-system overlay, so **every passthrough
   launch needs `-writable-system`**; without it the AVD boots its original image.
4. **The guest kernel's own `gs_usb` driver claims interface 0 first.** The app takes it over
   because `GsUsbDevice` calls `claimInterface(iface, true)`, as on a phone with that driver.
5. **USB permission** is a system dialog. Headless, find the controls with
   `adb shell uiautomator dump` and tap them with `adb shell input tap`; ticking
   "Always open Vtrux when USB2CAN V3.4.3 is connected" before OK keeps the grant.
6. **`BusmasterWriter` flushes every 1000 frames**, so a short test shows only the header in
   the file. Send more than 1000 frames, or read the file after the segment closes.

7. **Coda reads its USB permission as denied, even after OK** (found 2026-10-28, plan Step 5).
   `coda/MainActivity` requests it with a `FLAG_IMMUTABLE` `PendingIntent`, so on this API 31
   image the system cannot attach `EXTRA_PERMISSION_GRANTED` and the receiver logs
   "USB permission denied". The grant itself is recorded: `am force-stop` and restart Coda, and
   it opens the adapter through `hasPermission`. Vtrux uses `FLAG_MUTABLE` and is not affected.
   Treated as an emulator trap, not a bug: the head unit runs a mix of Android versions and has
   not shown it (owner, 2026-10-28).
8. **Coda logs only while the screen is on** (screen trigger). `svc power stayon true` and
   `input keyevent KEYCODE_WAKEUP` before a run; `input keyevent KEYCODE_SLEEP` afterwards closes
   the segment and flushes it. `artifacts/gs_usb_fault_matrix.py run --mode app` does both.

This replaces the phone's USB stack and timing with QEMU's, so "USB host and dongle
lifecycle" under Limitations below still needs the real device.

## Limitations

The emulator does not reproduce the A007 head unit's ROM-level quirks, all of which have
previously caused real bugs (see `android-app/android-coda-app-notes.md` Phase 2):

- `Build.VERSION.SDK_INT` spoofed to 29 while running Android 12
- `isExternalStorageManager()` and the `MANAGE_EXTERNAL_STORAGE` settings activity missing from
  `framework.jar`
- scoped-storage behaviour and the writable log path
- USB host and dongle lifecycle
- the head unit's real screen density

**Measured 2026-09-26** (the app's hardware report, `CodaLogs/diag/hardware_20260926T181152.json`):
the head unit is **1024 x 600 px at 240 dpi, i.e. 682 x 360 dp** for the app. Run the AVD with
`adb shell wm density 240` to see what the car sees; set it back to 160 afterwards. What follows
was written before this was known. The AVD assumes
1024 x 600 mdpi. This matters for any from-scratch Compose layout, because Compose lays out in
dp: 1024 x 600 at mdpi gives 1024 x 600 dp, but the same panel at hdpi would give only about
683 x 400 dp. The existing green screen is immune (all overlay positions are fractions of the
canvas) but new screens will not be. Since the A007 has no ADB, the cheapest way to get ground
truth is to log `resources.displayMetrics` from `CodaApplication` and read it back over the
app's existing debug log server on port 9876.

Treat the emulator as a layout-and-logic rig. Anything touching storage, permissions, USB, or
display metrics still needs a build dropped on the real head unit to confirm.
