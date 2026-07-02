# Android CAN PoC -- Notes

**Goal:** Receive CAN messages from an Innomaker USB-to-CAN adapter on an Android phone and
verify them in logcat. PEAK CAN dongle (on PC) transmits; Innomaker (on phone via USB OTG)
receives.

**Approach:** Implement the gs_usb protocol in userspace using Android's `android.hardware.usb`
host API (no root, no kernel driver required).

**Phone IP:** <lan-ip>

**ADB command:** always use full path `<ANDROID_SDK_DIR>/platform-tools/adb.exe`
-- the PATH `adb` resolves to an old 1.0.32 install and does not support `adb pair`.

---

## Phase 1 -- Environment Audit & ADB Setup (COMPLETE 2026-03-21)

### Android Studio & SDK

- **Android Studio:** Iguana 2023.2.1, build `AI-232.10300.40.2321.11567975` (March 2024).
  Current stable is Meerkat 2024.3.1 -- about 2 major versions behind. Not blocking for PoC
  since we build from command-line Gradle; update recommended but deferred.
- **SDK platforms:** android-31, 32, 33, 34. API 34 is sufficient for target.
- **Build tools:** 30.0.2, 30.0.3, 32.0.0, 32.1.0-rc1, 33.0.1, 34.0.0. Latest (34.0.0) present.
- **Platform-tools (adb):** was 1.0.32 (ancient, no `adb pair`). Updated via Android Studio SDK
  Manager to **37.0.0** (1.0.41). Now at `<ANDROID_SDK_DIR>\platform-tools\`.
- **cmdline-tools:** not installed. Not needed for PoC.

### ADB Wireless

- Phone uses Android 11+ wireless debugging (not the legacy `adb tcpip 5555` method).
- Paired via `adb pair <lan-ip>:39289 <code>` -- guid `adb-<device-guid>`.
- Connected via `adb connect <lan-ip>:42879` -- device shows as `<lan-ip>:42879 device`.
- `adb logcat` streams successfully. Wireless ADB is the primary workflow going forward.
- Note: the wireless debugging port (42879) is assigned dynamically by Android; if it changes
  after a reboot, re-pair or just reconnect to the new port shown on the Wireless Debugging screen.

---

## Phase 2 -- Base Android Project & APK Deploy (COMPLETE 2026-03-21)

### Project setup

- Package: `com.reverseit.canreader` (all lowercase -- avoided mixed-case to prevent Android
  tooling issues)
- Kotlin, min SDK 21, target SDK 34, AGP 8.3.2, Gradle 8.4
- Gradle wrapper bootstrapped using the Gradle 8.4 binary cached in
  `~/.gradle/wrapper/dists/gradle-8.4-bin/`
- JDK used: Android Studio's bundled JBR at
  `<ANDROID_STUDIO_JBR>` (OpenJDK 17.0.9)
- `gradle.properties` requires `android.useAndroidX=true` -- Gradle will refuse to build
  without it when AndroidX deps are present.
- Build commands always need explicit env vars (no system-wide JAVA_HOME or ANDROID_HOME):
  ```
  JAVA_HOME="<ANDROID_STUDIO_JBR>"
  ANDROID_HOME="<ANDROID_SDK_DIR>"
  CanReaderApp/gradlew.bat assembleDebug --project-dir CanReaderApp/
  ```

### Verified

- APK built successfully, installed via `adb install -r`, launched via `adb shell am start`.
- Logcat confirmed:
  ```
  03-21 12:01:53.540  7161  7161 I CanReader: CAN Reader started
  ```

---

## Phase 3 -- gs_usb Userspace Library & CAN Reception (COMPLETE 2026-03-21)

### Innomaker USB descriptor (confirmed via `dumpsys usb`)

- **VID:** 0x1D50 (7504 decimal), **PID:** 0x606F (24687 decimal)
- **Product name:** USB2CAN V3.3, **Manufacturer:** InnoMaker
- **Interface 0** (gs_usb, class=255/255/255): used for CAN data
  - Bulk IN:  endpoint address 0x81, max packet 64 bytes
  - Bulk OUT: endpoint address 0x02, max packet 64 bytes
- **Interface 1** (DFU, class=254/1/1): firmware update -- ignored
- Also present on hub: ASIX AX88179A ethernet adapter (VID=0xB95 PID=0x1790) -- unrelated

### gs_usb protocol sequence (implemented in GsUsbDevice.kt)

Control bmRequestType: `0x41` (vendor|interface|OUT), `0xC1` (vendor|interface|IN)

| Step | Direction | Request code | Payload |
|------|-----------|--------------|---------|
| 1 | OUT | `0` HOST_FORMAT | 4 bytes: `0x0000BEEF` LE |
| 2 | IN  | `5` DEVICE_CONFIG | 12 bytes: byte[3]=icount (channels-1) |
| 3 | IN  | `4` BT_CONST | 40 bytes: u32 feature, u32 fclk_hz, ... |
| 4 | OUT | `1` BITTIMING | 20 bytes: prop_seg, phase_seg1, phase_seg2, sjw, brp (all u32 LE) |
| 5 | OUT | `2` MODE | 8 bytes: u32 mode (1=START), u32 flags |
| 6 | Bulk IN loop | -- | 20-byte frames (see GsUsbFrame.kt) |

Frame wire layout (little-endian, 20 bytes):
```
u32 echo_id      -- 0xFFFFFFFF for RX frames
u32 can_id       -- bit31=EFF, bit30=RTR, bits28:0=arbitration ID
u8  can_dlc      -- data length (0-8)
u8  channel
u8  flags
u8  reserved
u8[8] data
```

### Bittiming computation

Queries `fclk` from BT_CONST, then finds `brp` such that
`fclk / (brp * bitrate)` is an integer in [4, 25], targeting 87.5% sample point.
Falls back to hardcoded `brp=6, prop=1, seg1=12, seg2=2, sjw=1` (correct for 48 MHz / 500 kbps).

### Implementation structure

**`GsUsbFrame.kt`** -- data class + 20-byte LE serialization. `fromBytes()` for RX, `toBytes()`
for future TX. `dataHex()` helper for logging. Note: `data` is always 8 bytes on the wire;
only `dlc` bytes are valid.

**`GsUsbDevice.kt`** -- full gs_usb protocol. Key design points:
- Always claims interface 0 (gs_usb), never interface 1 (DFU)
- Endpoint discovery is dynamic (loops `iface.endpointCount`) rather than hardcoded addresses,
  so it will work even if the firmware reorders endpoints
- `open()` runs the full 5-step init sequence synchronously -- must be called from a background
  thread (IO dispatcher)
- `readFrames(onFrame)` is a blocking loop; returns when `close()` sets `running=false` or the
  thread is interrupted
- `close()` sends `MODE=RESET` before releasing the interface, which cleanly stops the CAN channel
  so the device doesn't stay in an active state after the app exits
- `computeBittiming()` queries fclk from BT_CONST and finds an exact-integer brp; falls back to
  hardcoded values if no exact match (the fallback is correct for 48 MHz candleLight)

**`MainActivity.kt`** -- USB lifecycle. Flow:
1. `onCreate` registers a `BroadcastReceiver` for three actions: our custom permission action,
   `USB_DEVICE_ATTACHED`, and `USB_DEVICE_DETACHED`
2. Checks if Innomaker is already connected on startup via `usbManager.deviceList`
3. If found (or on attach event): calls `usbManager.hasPermission()` -- if already granted,
   opens immediately; otherwise calls `usbManager.requestPermission()` with a `PendingIntent`
4. On permission grant broadcast: calls `openCanDevice()` which launches a coroutine on
   `Dispatchers.IO` to run `GsUsbDevice.open()` then `readFrames()`
5. On detach: calls `gsUsbDevice.close()` to stop the read loop and release the interface

**`res/xml/usb_device_filter.xml`** -- declares VID/PID (decimal: 7504/24687). This does two
things: (1) Android automatically shows the permission popup when the device is plugged in, and
(2) the manifest `USB_DEVICE_ATTACHED` intent causes Android to launch/resume the app on plug-in
(so no manual launch needed in normal use).

### Files written

- `app/src/main/res/xml/usb_device_filter.xml` -- VID/PID filter, triggers permission popup on attach
- `app/src/main/AndroidManifest.xml` -- added `usb.host` feature + `USB_DEVICE_ATTACHED` intent
- `app/src/main/java/com/reverseit/canreader/GsUsbFrame.kt` -- frame data class + serialization
- `app/src/main/java/com/reverseit/canreader/GsUsbDevice.kt` -- full gs_usb protocol impl
- `app/src/main/java/com/reverseit/canreader/MainActivity.kt` -- USB lifecycle + coroutine read loop

### Gotchas encountered

**Android 13+ receiver registration (API 33+):**
`registerReceiver` requires `RECEIVER_EXPORTED` or `RECEIVER_NOT_EXPORTED` when the filter
includes a custom (non-system) action. Our `ACTION_USB_PERMISSION` broadcast is sent by
`UsbManager` from outside the app process, so `RECEIVER_EXPORTED` is correct. Fixed by using
`ContextCompat.registerReceiver(..., ContextCompat.RECEIVER_EXPORTED)`. Without this the app
crashes immediately on launch with a `SecurityException`.

**Stale permission dialog:**
If the app crashes before the user grants the USB permission popup, the pending permission
request is lost. On relaunch the app will call `requestPermission()` again and show a fresh
dialog. The user must re-grant -- the grant from a crashed session is not retained.

**ADB shell quoting on Windows:**
Running `adb shell` with complex arguments via bash on Windows fails due to path interpretation
(`/c/Users/...` treated as Windows paths). Use `powershell -Command "& 'adb.exe' shell '...'"`
instead -- single-quote the shell command string in PowerShell to prevent expansion.

### PEAK transmit test (2026-03-21)

- Transmitted 10 frames from PEAK PCAN_USBBUS1 at 500 kbps using `python-can` 4.4.2 (py -3.11).
- Script: `android-app/notes/artifacts/peak_tx_test.py` (working helper, not in public repo)
- All 10 frames received correctly in logcat:
  ```
  I CanReader: CAN RX: id=0x123 dlc=8 data=[01 02 03 00 AA BB CC DD]
  I CanReader: CAN RX: id=0x123 dlc=8 data=[01 02 03 01 AA BB CC DD]
  ... (10 total, counter byte increments correctly)
  ```
- Frame timing: ~200 ms interval, received within ~1 ms of transmission. No dropped frames.

### Device clock / bittiming (confirmed)

- Innomaker USB2CAN V3.3 clock: **48 MHz** (candleLight firmware)
- Computed bittiming for 500 kbps: brp=4, prop=1, seg1=19, seg2=3, sjw=1
  (48MHz / (4 * 24) = 500 kbps exactly, ~87.5% sample point)

---

## Decisions & Constants

- **Bitrate:** 500 kbps hardcoded for PoC; single constant to change later.
- **Language:** Kotlin.
- **Concurrency:** Kotlin coroutines, `Dispatchers.IO` for USB bulk reads.
- **Min SDK:** 21 (Android 5.0).
- **Innomaker VID/PID:** 0x1D50 / 0x606F -- confirmed via `dumpsys usb` (2026-03-21).

## File Layout

```
android-app/
  notes/
    android-can-poc.md              <- this file
    artifacts/
      README.md
      peak_tx_test.py               <- PEAK transmit test (py -3.11, python-can 4.4.2)
  CanReaderApp/                     <- Android project root
    gradle/
      libs.versions.toml            <- version catalog (AGP 8.3.2, Kotlin 1.9.22, coroutines 1.7.3)
    gradle.properties               <- android.useAndroidX=true (required)
    settings.gradle.kts
    build.gradle.kts
    gradlew.bat                     <- build: JAVA_HOME=... ANDROID_HOME=... gradlew.bat assembleDebug
    app/
      build.gradle.kts
      src/main/
        AndroidManifest.xml         <- usb.host feature + USB_DEVICE_ATTACHED intent filter
        res/xml/
          usb_device_filter.xml     <- VID=7504 PID=24687 (Innomaker, decimal)
        java/com/reverseit/canreader/
          GsUsbFrame.kt             <- 20-byte frame data class, fromBytes/toBytes
          GsUsbDevice.kt            <- gs_usb protocol: init sequence + blocking read loop
          MainActivity.kt           <- USB lifecycle, BroadcastReceiver, coroutine dispatch
```
