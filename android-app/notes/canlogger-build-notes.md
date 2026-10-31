# CanLoggerApps — Build & Infrastructure Notes

## Project Structure

`android-app/CanLoggerApps/` — Gradle multi-module project:
- `:cancore` — shared Android library (gs_usb protocol, pipeline, logging service, GUI framework)
- `:coda` — Coda vehicle app
- `:vtrux` — Vtrux vehicle app
- `:p914` — Porsche 914 EV app (logger; display is future work)

### `:p914` — architecture (2026-08-13)

The only vehicle app with **no gs_usb dongle and no `CanPipelineManager`**. The VCU emits SLCAN
(LAWICEL ASCII) over its USB CDC serial port, so the app's source is a byte stream rather than a
USB device.

- `SlcanFrameSource` (in `:cancore`) implements `CanFrameSource`, the three-member seam
  `CanLoggingService` actually needs. That is why the seam exists — the gs_usb path is untouched.
- **Trigger:** log while the source is attached. Uses the service's existing `TRIGGER_POWER` mode,
  where the service is passive and acts only on `notifyPowerState()`, so stream-connected and
  stream-disconnected are pushed straight in. Nothing reads the charger; no `:cancore` change.
- **Logs:** `getExternalFilesDir(null)/P914Logs/` — no storage permission needed. Pull with
  `adb pull /sdcard/Android/data/com.reverseit.p914/files/P914Logs/`.
- **No Compose.** `MainActivity` is a bring-up readout built in code — status, frame counts, block
  health and the frame digest. The real display is a separate module (Track B).
- `MainActivity` accepts `--ez autoconnect true` so a bring-up run is scriptable from adb without
  simulating taps.
- Icon: the Porsche crest (`android-app/porsche-crest.png`) fitted onto transparent square
  mipmaps via Pillow.

#### Classes in `:p914`

| Class | Role |
|-------|------|
| `P914Application` | Owns the source and the service binding. Two transports (TCP replay, USB CDC) behind one pump loop, both ending as an `InputStream` |
| `UsbCdcSerial` | Hand-rolled CDC-ACM over `UsbDeviceConnection`. Exposes an `InputStream` |
| `RootOtg` | Forces USB host mode via Magisk. **Does not work on this ROM** — see below |
| `MainActivity` | Bring-up readout, transport buttons, `FLAG_KEEP_SCREEN_ON` |
| `MbedFlasher` | Writes firmware to the mbed mass-storage volume over SAF — see "Flashing the VCU from the phone" |
| `FlashActivity` | Flashing UI and the adb entry point. Exported; its own task |
| `P914Constants` | Vehicle name, bridge host/port, log dir override |

#### Why CDC-ACM is hand-rolled, not `usb-serial-for-android`

The library is published on JitPack, which would mean adding a repository to shared build config
under `FAIL_ON_PROJECT_REPOS`; `GsUsbDevice` is existing precedent for raw `UsbDeviceConnection`
work in this project; and CDC-ACM needs only two control transfers before the bulk endpoint is a
plain byte stream. It would also have needed a custom `ProbeTable` entry regardless, since
`0d28:0204` is not a USB-serial chip.

**The design decision that made it cheap:** `UsbCdcSerial` exposes an `InputStream`, so
`SlcanFrameSource.pump()` consumes it exactly as it consumes the replay bridge's TCP socket. No
new parsing, and the decode path on the car is bit-for-bit the one verified over TCP first.

Two control transfers, both on the **control** interface's id:

```
SET_LINE_CODING       0x21 0x20  data: dwDTERate LE32, bCharFormat, bParityType, bDataBits
SET_CONTROL_LINE_STATE 0x21 0x22  wValue 0x03 (DTR|RTS), no data
```

Baud **must** be 460800: the mbed interface MCU passes it through to the target UART, so a wrong
rate yields pure garbage rather than an error. `SET_LINE_CODING` returning 7 (bytes accepted) is
the success signal. Interfaces are found **by class, not index**, so a firmware change that
reorders them cannot silently bind the wrong one.

#### Three things that bite on the USB path

1. **Read on a dedicated thread.** `bulkTransfer` is a single synchronous URB and USB bulk has no
   flow control, so anything arriving while the parser is busy is dropped by the host controller.
   Reading and parsing on one thread measured ~2x the loss. Queue-full is *counted* (`overruns`),
   never silently dropped.
2. **`bulkTransfer` returns -1 for both a timeout and a detached device.** Treating every -1 as
   "idle, keep going" means an unplug spins forever and a replug is never noticed. Needs
   `ACTION_USB_DEVICE_DETACHED` plus an idle-count backstop — measured on the car, the backstop
   fired 33 ms *before* the broadcast, so both earn their place.
3. **Device-absent is transient, not terminal.** Clearing the "keep trying" flag when the device
   is not found kills the retry loop on the very first post-detach attempt.

#### USB permission must be persistent

`requestPermission()` alone gives a **one-shot** grant, so every replug re-prompts. The
**"use by default for this USB device"** checkbox only appears when the app declares a matching
`<usb-device>` filter in a `USB_DEVICE_ATTACHED` intent-filter — that is the whole difference, and
it is visible in the dialog itself. `res/xml/usb_device_filter.xml` (VID 3368 / PID 516) plus the
intent-filter and `launchMode="singleTask"` on `MainActivity` gives a persistent grant and makes
plugging the VCU in launch the app. Confirmed on the car.

#### `RootOtg` does not work on this ROM

Kept because it is the natural place for the fix if the SELinux policy is ever added, and because
its output is diagnostic. `/sys/class/dual_role_usb/otg_default/mode` is writable by neither the
shell's nor the app's `su` under LineageOS 14 — see `outstanding-changes.md` Bug 6. It reports the
role read back rather than trusting an exit code, which is exactly what `:vtrux`'s version fails
to do.

Bring-up over TCP (no USB host mode needed):
```
py -3.12 tools/slcan_bridge.py --file <capture> --loop     # laptop
adb reverse tcp:9000 tcp:9000
adb shell am start -n com.reverseit.p914/.MainActivity --ez autoconnect true
```

**Staying awake.** `MainActivity` sets `FLAG_KEEP_SCREEN_ON` — during bring-up the screen is the
only readout, and in the car this is a dash display that should never sleep. That is separate
from the `PARTIAL_WAKE_LOCK` `CanLoggingService` holds while logging, which keeps the CPU
servicing USB bulk transfers and stops Android enabling USB autosuspend. Different failure modes;
both wanted. Battery-optimisation exemptions applied as for `:vtrux`:

```
adb shell dumpsys deviceidle whitelist +com.reverseit.p914
adb shell cmd appops set com.reverseit.p914 RUN_ANY_IN_BACKGROUND allow
```

### The VCU as a USB device (measured 2026-08-13, OnePlus 7T in host mode)

```
vid:pid  0d28:0204   product "MBED CMSIS-DAP"   manufacturer "MBED"
bDeviceClass 02, 4 interfaces:
  intf 0  class=08 sub=06 proto=50   mass storage   <- claimed by usb-storage
  intf 1  class=02 sub=02 proto=01   CDC control    <- unclaimed
  intf 2  class=0a sub=00 proto=00   CDC data       <- unclaimed
  intf 3  class=03 sub=00 proto=00   HID            <- claimed by usbhid
```

What this settles:

- **The CDC interfaces are unclaimed**, so the app can claim interfaces 1 and 2 without fighting a
  kernel driver. `claimInterface(force = true)` is used anyway, since another ROM could bind
  `cdc-acm` and then reads would silently return nothing.
- **The MSD interface being claimed by `usb-storage` is harmless** to the serial path — different
  interface. The earlier worry that Android mounting the mbed would interfere is unfounded.
- **That MSD interface is also the firmware-loading route.** The mbed presents its flash-by-copy
  volume there: dropping a `.bin` on it programs the target. Built and working — see
  "Flashing the VCU from the phone" below.

**Host mode is hub-dependent** — see `outstanding-changes.md` Bugs 6 and 7. With the bench hub
powered, the phone sat at `ufp`/device and enumerated nothing; with hub power removed it holds
`dfp`/host reliably. The root role-forcing path does not work on this ROM.

Migrated from PoC at `android-app/CanReaderApp/` (GsUsbFrame.kt, GsUsbDevice.kt).

### Flashing the VCU from the phone (built and proven on the car, 2026-08-13)

The point: with the phone in the car and the laptop not, the VCU used to be unflashable without
carrying a laptop out to it. Now firmware and app development can happen in the same sitting.

**The operator is an assistant session over wifi adb, not a person tapping buttons.** That framing
drove the design — the primary interface is the command line, and everything the screen prints also
goes to logcat under `P914`, so a headless run is fully observable without `uiautomator`:

```
adb push fw.bin /sdcard/Android/data/com.reverseit.p914/files/Firmware/
adb shell am start -n com.reverseit.p914/.FlashActivity -e image fw.bin --ez go true
adb logcat -s P914
```

The UI cannot be removed even so: **a SAF permission cannot be granted from a shell**, so the
one-time volume grant has to come from the document picker. The screen exists mainly to host that,
with manual selection and a confirm dialog as the by-hand fallback.

| Class | Role |
|-------|------|
| `MbedFlasher` | Volume identification, delete/write/readback-verify, `FAIL.TXT` reporting. No UI, no reset |
| `FlashActivity` | Intent and manual entry points, the SAF grant, the on-screen log |
| `P914Application.flashAndReset()` | Owns the ordering: stop pump, flash, settle, BREAK, restart |
| `UsbCdcSerial.sendBreak()` | The reset |

#### Ordering is the whole game

The sequence is stop pump → write → **wait** → reset, and it is spread across three classes, which
is why `flashAndReset()` exists to own it rather than letting the UI sequence it. The hub's
`914/notes/artifacts/README.md` records why: the LPC1768 does not auto-reset after programming
here, and a reset sent too early leaves the target halted with no serial output — indistinguishable
from a bricked board.

The settle wait is **8 s and untuned**, because there is nothing to tune against: the interface MCU
reports neither the start nor the end of programming. Chosen on the reasoning that waiting too long
costs seconds and waiting too little costs a target that looks bricked.

The pump is stopped first for two reasons: the reset ends the stream anyway, and the break needs
the CDC control interface, which a live session holds claimed.

#### Verifying a flash — readback is not enough

A readback proves the FAT write landed and nothing was silently discarded. It says **nothing** about
whether the target was programmed. Worse, writing a byte-identical image cannot distinguish the two
at all: an unprogrammed target looks exactly the same afterwards.

What settles it is flashing a *different* build and watching the stream change character. Measured:

| Image | frames | csv |
|-------|--------|-----|
| `fw-dualemit-verify.bin` | 262 fps | climbing 2/s |
| `fw-slcan-only.bin` | 262 fps | **0** |

`csv` frozen at zero with the frame rate unchanged is proof the target is running different code.
Both directions were flashed from the phone and the car was left on dual-emit.

#### The reset: CDC SEND_BREAK works from Android

`SEND_BREAK` (`0x21 0x23`) as a control transfer — assert continuous (`wValue 0xFFFF`), hold 500 ms,
clear (`wValue 0`) — mirrors `send_break()` in the hub's `vcu_serial.py` at the USB level.
**Verified on the car**, so the phone can reset the VCU with no power cycle and no button press,
which matters because the reset button is not reachable with the car assembled.

Failure to *clear* the break is reported distinctly: it would leave the target held in reset, which
looks exactly like a board that died during flashing.

#### Two guards, because this component is exported

`am start` from a shell cannot launch a non-exported component, so adb-driving this required
`exported="true"`. Two things keep that from being a hole:

1. **Names, not paths.** An intent supplies a filename resolved only inside the app's own external
   files dir, with a canonical-path check rejecting anything that escapes it. A caller can flash
   nothing it did not already put where only this app can write.
2. **`MBED.HTM` before anything destructive.** A SAF tree is just a folder the user picked, and the
   picker will happily offer internal storage or an unrelated USB stick. `MBED.HTM` is the mbed
   interface firmware's own signature file, so its presence is a positive identification rather
   than a guess from a volume name or UUID.

#### `am start` silently doing nothing — taskAffinity vs singleTask

`FlashActivity` originally shared the default task affinity with `MainActivity`, which is
`singleTask`. An external launch (adb is uid 2000, so the start needs NEW_TASK semantics) got folded
into that existing task and **the extras were delivered to `MainActivity` instead**. `am start`
reports "intent has been delivered to currently running top-most instance" and no flash happens.
Adding `FLAG_ACTIVITY_NEW_TASK` did not help.

Fixed with `android:taskAffinity="com.reverseit.p914.flash"` plus `launchMode="singleTop"`, so it
gets its own task and a repeat launch routes to `onNewIntent`. Intent extras are stripped once
acted on, so a redelivered intent cannot re-flash the car off a stale command.

#### Open question

**Whether the persisted SAF grant survives a physical replug of the VCU is untested** — it could not
be checked remotely. The volume's fsUuid is `0000-0000`, baked into the mbed's FAT image, so the
tree URI *should* be stable across remounts, but that is reasoning rather than evidence. If it does
not hold, the one-time picker tap becomes a per-replug tap.

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

Log format (BUSMASTER, `BusmasterWriter`), following the header's column line
`***<Time><Tx/Rx><Channel><CAN ID><Type><DLC><DataBytes>***`:
```
HH:MM:SS:TTTT Rx <busIndex+1> 0x<ID> s|x <dlc> <byte0> <byte1> ...
HH:MM:SS:TTTT Rx <busIndex+1> 0x<mask> ERR 8 <byte0> ... <byte7>
```
TTTT = 10 kHz ticks (millisecond remainder × 10). `s` / `x` = standard / extended ID; `Tx` marks
the app's own transmitted frames (gs_usb echo). Header block matches existing captures so
`canre` tools parse them directly. (This section showed a different column order until
2026-10-30; the line above is what the writer produces.)

**`ERR` lines (since the 2026-10-30 builds, Bug 11):** a CAN error frame from the adapter is
logged with type `ERR`, the SocketCAN error-class mask in the ID column (`0x4` controller,
`0x8` protocol, `0x20` ACK, combined, e.g. `0xC`) and the 8-byte payload as received, e.g.
`Rx 1 0xC ERR 8 00 30 02 00 00 00 6D FF`. Before those builds the same frames were written as
ordinary standard frames `0x004` / `0x00C`. `canre/parsers/busmaster.py` skips `ERR` lines unless
`include_errors=True`. Why the `ERR` token: `plans/gs-usb-error-frames.md` decisions table. An
Innomaker reports its error state on a 1 s tick, so the lines count seconds in an error state,
not errors (plan Step 5).

**Drop counts (since the 2026-10-30 builds, Bug 4):** the notification ends with
`drops 0`, or with each non-zero count, e.g. `drops pipe.log=412`. Names: `pipe.log` (frames
the log writer lost, gs_usb), `pipe.frames` (live display, bus resolver, GPS; gs_usb),
`slcan.frames` (`:p914`), `harness.frames` (Coda SLCAN harness), `gs_usb.overflowFlag` (frames
the adapter flagged as overflowed, Bug 12). The same counts go to logcat every 10 s, tag
`TryEmit`. The log itself carries no drop record (Change 13). The log writer's flows buffer
16,384 frames (`CanFrameSource.LOG_BUFFER_FRAMES`). Debug builds of `:coda` also log collector
backlog measurements and accept the `com.reverseit.cancore.DEBUG_STALL` broadcast; release
builds do not (`FlowHealth.kt`).

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
| `SlcanReader` | Incremental LAWICEL/SLCAN ASCII reader (914 VCU over USB CDC serial). Holds a partial token across `feed()` calls, absorbs CRLF as one terminator so interleaved CSV records do not read as bare-CR acks, excludes the integrity frame from its own block, and CRCs the bytes as received. Covered by `SlcanParityTest` |
| `SlcanSource` | Drives `SlcanReader` from an `InputStream` (serial port or TCP). Blocking `pump()` plus a `slcanFrames()` cold-flow wrapper. No Android imports, so the whole path is JVM-testable |
| `CanFrameSource` | The three members `CanLoggingService` actually needs from a source: `frames`, `activeDeviceCount()`, `activeBusCount()`. `CanPipelineManager` implements it; widening the service's property to this interface let a non-gs_usb vehicle use the logging path without touching the multi-dongle code |
| `SlcanFrameSource` | `CanFrameSource` over an SLCAN byte stream. One stream, one bus. Starts a fresh reader per `pump()`, because a reconnected stream can begin mid-frame and a carried-over partial token would splice two unrelated frames |
| `LogFileServer` | NanoHTTPD server for the companion: `/health`, `/files` (log-root `.log`, flat -- what the companion pulls then DELETEs), `/tree` (recursive, read-only, `.log`/`.jsonl`/`.json`, since 2026-09-26), `GET /files/<path>` with canonical-path containment, DELETE log-root `.log` only, and `PUT /files/<putDir>/<name>.jsonl` (create-only, Coda `tpms` only, since 2026-09-27; `/health` version 3). Covered by `LogFileServerTest` (real HTTP on the JVM) |
| `SlcanWriter` | Encodes a frame as an SLCAN `t`/`T` line, the inverse of `SlcanReader`. Covered by `SlcanWriterTest` |
| `SlcanBusGroup` | N SLCAN streams (one per bus) as one `CanFrameSource` + `CanTransmitter` -- the Coda emulator harness's stand-in for N dongles. Stamps and emits under one lock, as `CanPipelineManager` does; `transmit()` writes the line up that bus's stream and emits an `isTx` echo, as gs_usb does; reconnects a dropped stream; counts drops. Covered by `SlcanBusGroupTest` and, with a bridge dump, `SlcanBridgeParityTest` |

---

## Build Environment — Desktop

JDK 17 required — system default java is 1.8 and AGP 8.3.2 rejects it.
- JDK 17: `<ANDROID_STUDIO_JBR>`
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

## Build Environment — the bench PC

- JDK 21 (Android Studio bundled JBR): `<ANDROID_STUDIO_JBR>` (no `1` suffix)
- Android SDK: `%LOCALAPPDATA%\Android\Sdk`
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

**First-build gotcha:** Gradle auto-downloads build-tools 34.0.0 on first run. If a previous failed build left a corrupt install, delete `%LOCALAPPDATA%\Android\Sdk\build-tools\34.0.0` and the `.temp\` folder, then retry. Or reinstall via Android Studio SDK Manager.
```

### `JAVA_HOME` is not optional here — the system JDK breaks the build

Found 2026-08-13. The system default JDK on this machine is **Eclipse Adoptium 25.0.2**, and
Kotlin 1.9.22's `JavaVersion.parse` cannot read that version string. Building without `JAVA_HOME`
pointed at the bundled JBR fails while *compiling the build script itself*:

```
java.lang.IllegalArgumentException: 25.0.2
```

Two things make this harder to recognise than it should be:

- **It is latent.** Gradle caches the compiled build script, so an unchanged tree keeps building
  on the stale cache. It surfaces only when something invalidates that cache — editing any
  `build.gradle.kts` will do it — so the failure looks like it was caused by whatever innocuous
  edit you just made, in a file with nothing to do with the error.
- **The message names no file, no module and no task**, so it reads like a corrupt Gradle cache
  rather than a toolchain mismatch.

The fix is the `JAVA_HOME` prefix already shown above — always pass it. In PowerShell:

```powershell
$env:JAVA_HOME = "<ANDROID_STUDIO_JBR>"
```

**Deliberately not fixed by pinning `org.gradle.java.home` in `gradle.properties`.** That file
syncs across machines via SeaDrive and is shared by all four app modules, so a machine-specific
absolute path there would break the build on Desktop rather than fix it here. Setting it
per-invocation keeps the workaround local to the machine that needs it. Whether to pin it anyway
is the owner's call and has not been decided.

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
Copy-Item '<repo>\android-app\CanLoggerApps\coda\build\outputs\apk\debug\coda-debug.apk' 'E:\Google Drive\To Seafile\coda-debug (N).apk'
```

Head unit installs the APK from SeaDrive on the car's Android head unit (<lan-ip>). The head unit's file manager can browse `E:\Google Drive\To Seafile\` via the SeaDrive sync folder.

ADB device (phone): connected over TCP at `<lan-ip>:39789` (port changes each wireless debug session — check `canlogger-build-notes.md` for latest).

---

## CAN Log Replay

Using `tools/can_replayer.py` (now run from the can-tools git clone, `~/Git/can-tools/tools/can_replayer.py`; reverse-it's copy was deleted 2026-10-31) with PEAK PCAN-USB dongle on PC → Innomaker on phone OTG.

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

**`build/` directories ARE synced, and they carry absolute paths (found 2026-08-13):** SeaDrive syncs the Gradle `build/` folders between machines, and AGP caches machine-specific absolute paths inside them. Building on a second machine then fails in dexing with:

```
Execution failed for DexingNoClasspathTransform: ...\cancore\build\intermediates\runtime_library_classes_dir\...
  > this and base files have different roots: <repo-root>\NotGit\reverse-it\... and <repo>
```

Nothing is wrong with the source. Delete the affected `build/` directories (`cancore/`, `coda/`, `vtrux/`) and rebuild — about 30 s. Worth suspecting first whenever a build fails right after switching machines, since the error names a path that does not exist on the current one.

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

### Device: OnePlus 7T (HD1901), Android 14, Magisk root

ADB port at time of session: `<lan-ip>:38463` (changes each wireless debug session).

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

**Phone:** OnePlus 7T stays in OTG host mode (`dfp`, `data_role: host`) throughout — OTG mode is not dropped. The issue is entirely within the hub's port power management.

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

**Relevant sysfs paths (OnePlus 7T):**
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

**Approach tried:** Write `ufp` to `/sys/class/dual_role_usb/otg_default/mode` via Magisk root (`su -c`). The write returns exit code 0, but the OnePlus 7T's OTG driver auto-reverts to `dfp` (host) after 3-4 seconds, re-powering the hub. A hold loop that re-asserts `ufp` every 0.8-2 seconds was tried but the VBUS power still cycles visibly.

**Why it doesn't work on the OnePlus 7T (HD1901, Android 14, kernel 4.14.348-openela-perf):**

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

## Session 2026-04-01 — the bench PC Setup + Power Sequencing Rewrite

### Build environment (the bench PC)
- Android Studio installed fresh (Meerkat era), JBR JDK 21, SDK path `%LOCALAPPDATA%\Android\Sdk`
- `local.properties` updated for this machine's username
- First build required Gradle to auto-download build-tools 34.0.0 and platform 34; initial download corrupted due to `FileAlreadyExistsException`, fixed by cleaning `.temp/` folder and retrying
- See "Build Environment -- the bench PC" section above for full details

### ADB on the bench PC
- ADB pairing via PowerShell works: `& '%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe' pair <ip:port> <code>`
- Bash `adb pair` with positional code argument gives "protocol fault" -- use PowerShell for all adb commands on this machine
- mDNS discovery works after pairing (device shows as `adb-<guid>._adb-tls-connect._tcp`)
- If mDNS doesn't find the device, `adb connect <ip:port>` using the port from the Wireless Debugging main screen (not the pairing port)

### Devices
- OnePlus 7T (HD1901): wireless ADB, guid `adb-16e7d2b3-RSkDoo`
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

**Transport IDs:** After pairing, the OnePlus 7T (guid `16e7d2b3`) shows up as mDNS transport `adb-16e7d2b3-RSkDoo._adb-tls-connect._tcp` (no space variant). If the device shows `offline` after a WiFi drop, run `adb disconnect <lan-ip>:<port>` then `adb connect <lan-ip>:<port>` using the current port from Developer Options → Wireless Debugging. The port changes every time wireless debugging is toggled — check the phone screen each session.

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

`local.properties` must have `sdk.dir=<ANDROID_SDK_DIR>

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
