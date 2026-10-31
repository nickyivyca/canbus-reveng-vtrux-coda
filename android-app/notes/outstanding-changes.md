# Android CAN Logger — Outstanding Changes

Newest first, so the numbers do not run in document order. Index:

| # | Status | Affects | Summary |
|---|--------|---------|---------|
| 15 | done 2026-10-30: 1.1 (versionCode 2) release builds; `:vtrux` and `:p914` installed on the OnePlus 7T; Coda 1.2 (versionCode 3, with HVAC 6d and Change 14) dropped as `coda-release (33).apk`, superseding (32); head-unit install pending; `:companion` release-signed too, not yet installed | **all apps** | Car and phone loads move from debug to release builds, signed with the project `debug.keystore` so they install over the current debug installs without losing data or permissions |
| 14 | done 2026-10-30: tweaks 1-3 in Coda 1.2 with HVAC 6d; rework deferred, investigation closed | **`:coda`** (`:tpms`) | The head unit has felt laggier since the GPS/TPMS feature. The segment re-parse is ~2x faster with ~9x less garbage; the live path ~3x cheaper. The emulator did not reproduce a GPS-specific slowdown with historical builds; the head unit's own GPS stack was not tested |
| 13 | open, not planned (owner wants to cut over eventually, 2026-10-30) | **all apps** | Move the Android loggers from BUSMASTER to PEAK TRC 2.1, which has standard records for events, adapter overrun and bus state. Until then drops are not recorded in the log (Bug 4) |
| 12 | open; overflow-flag count in the 2026-10-30 builds (1.1) with Bug 4's fix; queued reads not needed for now (phone run 2026-10-30) | **gs_usb apps** (`:cancore`) | `GsUsbDevice` reads one frame per synchronous `bulkTransfer`; in the AVD the adapter discards frames above that ceiling and the app never checked its overflow flag |
| 11 | fixed 2026-10-30 (plan `gs-usb-error-frames.md`, done); in the 1.1 release builds, not yet installed on the vehicles | **all gs_usb apps** (`:cancore`) | CAN error frames are logged as ordinary standard frames `0x004` / `0x00C`, because the `0x1FFFFFFF` mask drops `CAN_ERR_FLAG`. Normal mode kept (decided 2026-10-28) |
| 10 | open, TBD | `:p914` | Road logs lose 25-40% of frames (~10% parked, screen off) and carry corrupted ones; integrity frames are not logged, so a log cannot be checked afterwards. Diagnosis and fix are open |
| 9 | open, not implemented | **`:vtrux`** | Live-display throttle tile shows TPS as an "APP proxy". The real APP signal exists and is better; tile should switch to `Accelerator_Actual_Position`, scaled 0–70%. Replace-or-both waits on a corpus check for ECM override, held until Bug 4 is done |
| 8 | open, deferred | `:p914` | USB CDC reads drop bytes; synchronous `bulkTransfer` leaves gaps. Fix is async `UsbRequest` queuing. **Current theory for the road-log loss in #10** |
| 7 | not an issue in practice; moot after the Android Auto tablet install (owner, 2026-10-29) | any USB-host vehicle | Charge-and-host simultaneously is **hub-dependent**. Silent failure: presents as "no USB device" |
| 6 | not an issue in practice; moot after the Android Auto tablet install (owner, 2026-10-29) | **`:vtrux`** | SELinux denies the OTG role write on LineageOS 14, so `attemptRootOtgRecovery()` is a dead safety net. `[ -w ]` guard makes it report success |
| 5 | won't fix | `:p914` | Every reconnect starts a new log session. Owner ruling 2026-08-13: acceptable |
| 4 | fixed 2026-10-30 (plan `tryemit-drops.md`, done); in the 1.1 release builds, not yet installed on the vehicles | **all apps** | `tryEmit` drops frames silently when a collector falls behind. Latent, not yet field-observed. Fix: 16k log-writer buffer, drop counts to logcat and the notification |
| 3 | fixed 2026-07-14 | `:vtrux` | `BusIdentityResolver` latched onto retired bus indices |
| 2 | fixed 2026-05-03 | all apps | No `WakeLock` in `CanLoggingService` |
| 1 | fixed 2026-05-03 | all apps | No debounce in `CanPipelineManager.addDevice()` |

Bugs 4, 6 and 7 were found while bringing up `:p914` but affect the deployed truck app; 6 in
particular means a recovery path that has been assumed working is not.

---

## Change 15: release builds for car and phone loads

**Raised and approved 2026-10-30** (owner), during Bug 4 Step 3. **Done in code 2026-10-30**
with the Bug 4 / Bug 11 close-out; the first release build has not been installed on any vehicle
yet. Affects `:coda`, `:vtrux` and `:p914`, and `:companion` (added later the same day).

Every APK on the vehicles has been a debug build: the deploy steps (`canlogger-build-notes.md`,
`../android-tools-reference.md`) only ever install `*-debug.apk`, the release build type has no
signing config so its APK is unsigned and cannot be installed, and `SlcanHarness.kt` notes "the
car runs debug builds too". Found because Bug 4's fix keeps its collector measurements and stall
hook to debug builds (gated on `FLAG_DEBUGGABLE`), which would have put them on the head unit.

- **Signing:** release builds signed with the project `debug.keystore`. Same signature, so a
  release APK installs over the current debug install with `install -r` and keeps the logs, the
  TPMS store, USB and storage permissions and Magisk grants. A new key would force an uninstall,
  which deletes `getExternalFilesDir` (CodaLogs and the TPMS store).
- **All three apps** get the release config; car and phone loads are `assembleRelease`, Coda's
  dropoff file becomes `coda-release (N).apk`. Debug builds stay for the AVD and the bench.
- **Nothing else depends on the build type:** no `BuildConfig.DEBUG` checks, `SYNC_TOKEN` is set
  for every build type, minify is off, no vehicle workflow uses `run-as`. On a release build the
  Bug 4 drop counts still run; the collector measurements and stall hook do not.
- **Done at the close-out (2026-10-30):** the release config in all three modules, version 1.1
  (versionCode 2), the three release APKs built and checked (signer cert `88:F3:FF...`, the
  project keystore's; no `debuggable` flag). Build steps and checks in
  `../android-tools-reference.md` "Car and phone loads are release builds"; Coda's dropoff file
  is `coda-release (N).apk`, numbered on from the debug builds (the first is 32). The release
  install over a debug install was tried in the AVD in Step 3: the debuggable flag went, the
  app's data and location permission stayed.
- **Installed 2026-10-30:** `:vtrux` and `:p914` 1.1 release builds on the OnePlus 7T over adb
  (`install -r` over the 1.0 debug builds; the debuggable flag went, notification permission and
  the all-files storage app-op stayed). Coda's went to the dropoff as `coda-release (32).apk`
  (the Linux box `rclone copyto`, checksum matched in Drive).
- **Coda 1.2 (versionCode 3) dropped 2026-10-30** as `coda-release (33).apk` (md5
  `25ecdf0cc658b8138a4b54a16730cb9b`, matched in Drive): 1.1 plus HVAC step 6d and Change 14's
  tweaks; same signer cert, no `debuggable` flag. Unit tests before the build: `:cancore` 79,
  `:tpms` 135, `:coda` 4, all pass. It supersedes (32), which was never installed.
- **`:companion` added 2026-10-30** (owner: "companion should also move to release builds"):
  its `release` build type got the same signing config. Both flavours' release APKs built and
  checked (signer cert `88:F3:FF...`, no `debuggable` flag). Version left at 1 / `1.0`. Not
  installed on any phone yet.
- **Still to do:** install `coda-release (33).apk` on the head unit (owner).

---

## Change 14: GPS/TPMS CPU cost on the Coda head unit

**Raised 2026-10-30** by the owner: since the GPS feature went in, the head unit feels more laggy.
Not horrible. **Done 2026-10-30: tweaks 1-3 in Coda 1.2 (`coda-release (33).apk`); investigation closed, the
rework deferred** (owner: "let's just move forward without investigating or improving this
further"). Results below. (Investigation brief, owner: measure in the emulator whether
the changes below improve performance, and say if the phone is needed.) Wanted: easy tweaks that
change nothing else, and a rework considered separately. **Ships in the next Coda release build
together with HVAC step 6d** (`projects/coda/notes/hvac/coda-hvac-decompile-notes.md` section 9.4); no release build
for the HVAC change alone (owner, 2026-10-30).

### What the code did before the tweaks (read 2026-10-30; nothing measured on the head unit)

- **`GpsSpeedService`** asks for GPS fixes as fast as the receiver gives them
  (`requestLocationUpdates(GPS_PROVIDER, 0L, 0f)`), usually 1 Hz, plus the satellite count. Each fix
  copies five numbers. Light in the app; the receiver's own driver runs in the system, which the app
  cannot see.
- **Live path:** `GpsRateAccumulator.observe` runs on every CAN frame from the `app-observers`
  collector. Most frames are rejected at once, but `id in WheelRatioExtractor.D_CAN_ANCHORS` (a
  `Set<Int>`) boxes the ID on every frame, a small allocation thousands of times a second. The
  per-sample work for the four signal IDs (steering centre median, windows) is small.
- **Drive rows (`DriveRowProducer`):** on every segment close (5 min or 50 MB),
  `WheelRatioExtractor.readFrames` re-reads and re-parses the whole segment. A typical segment is
  about 1 million lines and 52 MB (`coda_20260807_192700_T2.log`: 1,019,476 lines, of which 354,166,
  35%, carry an ID the parser keeps). `tokenize` splits **every** line into substrings before the ID
  is checked, roughly 15 short-lived objects per line, about 15 million per segment. It runs on a
  `MIN_PRIORITY` thread.
- **`rebuildCentre`** re-reads **all** earlier segments of the session when a segment arrives out of
  sequence, e.g. after the app restarts mid-drive; `catchUp` at start processes segments that closed
  while the app was not running.
- The GPS status reaches the UI as a `StateFlow` updated about twice a second; the main dashboard
  already recomposes far more often, so this is not expected to matter.

**Hypothesis (not measured):** the segment re-parse is the main cost: a CPU and garbage-collection
burst every ~5 minutes, worse after a restart mid-drive. To tell: is the lag constant, or hitches
every few minutes? Constant lag would point instead at the GPS receiver's system-side cost.

### Easy tweaks (results unchanged)

1. In `readFrames`, read the ID field before tokenizing and skip lines with no wanted ID; parse the
   kept lines without per-token substrings. The parity tests (`WheelRatioParityTest`,
   `ExtractorProc3ReferenceTest`) confirm the output is unchanged. Time it on the host on a real
   segment before and after.
2. In `GpsRateAccumulator.observe`, test the anchor IDs without boxing (a `when` or a sorted
   `IntArray`).

### Rework (a design change, not a tweak)

Build the drive rows from the frames as they arrive (the live path already sees every one), instead
of re-reading the closed file. Removes the re-parse and the session rebuild. **Deferred** (owner,
2026-10-30): the lag the owner describes is constant, not bursty (see Results).

### Results (2026-10-30)

**The owner's description of the lag:** constant, not bursty. Going into the Settings app to force
stop an app was considerably slower after the GPS feature.

**Tweaks made** (all three kept, owner 2026-10-30; output identical to before on every check):
1. `WheelRatioExtractor.readFrames` splits each line into token positions, not substrings, and
   parses the ID, timestamp and bytes from those ranges (an exact port of `toIntOrNull`); the ID
   sets are `when` tests. Lines are still split before the ID is checked, but no objects are made.
2. `GpsRateAccumulator.observe` tests anchors with `WheelRatioExtractor.isAnchor` (no boxing).
3. `SteeringCentre` is a Fenwick tree over the 16-bit raw range, so the median the live path asks
   for on every wheel sample costs ~16 steps instead of a `TreeMap` walk that grew with the
   session. It holds a fixed 65,536-count table, ~0.5 MB per instance (three instances), against a
   few KB before. `SteeringCentreTest` checks it against a sorted-list median after every add.

**Host timings per segment** (`tpms/src/test/.../Change14BenchTest.kt`, env-gated; four real
segments; output digests identical before and after):

| | Before | After |
|---|---|---|
| `readFrames` | 480-680 ms, 0.8-1.1 GB allocated | 280-390 ms, 92-119 MB allocated |
| live path (`observe`) per frame | 56-206 ns, ~40 B | 34-38 ns |
| extract + temperatures | 12-60 ms | unchanged |

**Emulator** (AVD, 4 cores capped at 2 by `CPUQuota=200%`, `coda_20261025_222333` T0-T2 at 1x
over the SLCAN harness, release builds; `artifacts/change14_emulator.py`,
`artifacts/change14_20261030/`): the burst at each segment close went from ~15 s of `tpms-rows`
CPU over 16 s to 5-6 s over ~5 s. Throughout, the app used ~86% of one core, ~45% of it in the
coroutine pool that reads, decodes and logs every frame; GC 11-12% of a core in both builds.
A thread-dump profile of that pool (60 dumps, 18 caught it running): 7 in the log writer's
formatting (`BusmasterWriter`), 6 in handing frames between threads, 0 in GPS/TPMS code. Not
pursued (owner, 2026-10-30).

**Before and after GPS, historical builds** (`artifacts/gps_lag_ab.py`,
`artifacts/gps_lag_20261030/`): Drive builds `coda-debug (22)` (last without GPS) and
`(23)` (first with GPS; identities checked by md5 against Seafile history) and `coda-release (32)`,
in the same capped AVD with real traffic (the Innomaker passed through, the IXXAT replaying the
drive bus of the same drive), a 1 Hz emulator GPS feed, and Settings' app-info page opened 14
times per run with `am start -W`. Two runs each, in mirrored order:

| | Settings cold, median | Settings hot, median | Coda CPU | `system_server` |
|---|---|---|---|---|
| no Coda | 2.5-2.8 s | -- | -- | 3-4% of a core |
| build 22, no GPS | 4.4-4.5 s | 1.09-1.10 s | 105-110% of a core | 7.6-8.5% |
| build 23, GPS | 4.3 s | 1.09 s | ~107% | 9.1% |
| release (32), GPS | 4.3-4.7 s | 1.12-1.23 s | 95-103% | 9.8-10.1% |

- **No GPS-specific slowdown reproduced in the emulator.** Coda itself, in every build, makes a cold
  Settings launch here ~1.7x slower (about 2.6 s to 4.4 s), and uses about a core.
- GPS added ~1-2% of a core across `system_server` and Google Play services, and no measurable
  launch time.
- `GpsSpeedService` has asked for fixes at the maximum rate (`0L, 0f`) and registered the
  satellite-status callback in every version since its first (2026-09-24; Seafile history,
  `artifacts/gps_lag_20261030/history_window1/`). Build 23 also changed five `:cancore` files on the
  logging path.
- Not valid: the four runs without location (the USB grant was never given, the app logged
  nothing). Excluded: the second build 23 run (faster launches, but 1.5x larger app logs from the
  same traffic, unexplained; its logs were deleted by the script).
- **Not tested:** the head unit's own GPS receiver and driver. The emulator's GPS is simulated, so
  a cost there cannot show up in these runs. The head unit was not measured.

---

## Change 13: move the Android loggers from BUSMASTER to PEAK TRC 2.1

**Raised 2026-10-30** at the Bug 4 review. **Open, not planned.** The owner wants to cut over
eventually rather than invent a BUSMASTER extension or a sidecar file.

### Why

BUSMASTER has no record for anything but frames: its only other lines are the `***…***` header and
footer. Bug 4 needs somewhere to record frames dropped in the app, and Bug 12 the adapter's
overflow. A free-text `***` line between frames is skipped by `canre` and `BusmasterReader.kt`, but
Wireshark's BUSMASTER grammar (`wiretap/busmaster_parser.lemon`) accepts free text only in the
header block, so a mid-file one is a syntax error that ends its read (from the grammar, not
tested). A per-log sidecar file was considered and declined (owner, 2026-10-30).

### What TRC 2.1 offers

From PEAK's `PEAK_CAN_TRC_File_Format.pdf` (2025-08-04 edition), version 2.1:
- `EV`: a timestamped user-defined text event, for one bus or for all (`-`). Drops would be e.g.
  `1334.224 EV 1 dropped 1234 frames, log buffer full`.
- `ST`: hardware status, a 4-byte code: `0x2` OVERRUN (controller read too late), `0x8`
  BUSWARNING, `0x40000` BUSPASSIVE, `0x10` BUSOFF. The adapter's overflow flag maps to OVERRUN.
- `EC`: error counter values (RX, TX); `ER`: an error frame in PEAK's 5-byte layout (type,
  direction, position in the bit stream, ...).
- `;` comment lines, a `$COLUMNS` header, a bus column `B` (1-16), 1 µs time offsets.
- python-can reads 1.x-2.1 (it skips `ST`/`EC`/`ER`/`EV` lines, logging at info) and writes 2.1.

Other formats looked at (2026-10-30): Vector BLF (binary; has overrun, text and marker objects),
ASAM MF4 (binary; an "acquisition interrupt" event means data lost), Vector ASC (`//` comments,
chip status, `ErrorFrame`; no overrun record found), candump (no event records).

### Cost

- The writers in all apps (`BusmasterWriter.kt`) and the app's own reader (`BusmasterReader.kt`).
- `canre/parsers/peak_trc.py` reads only an older layout, not 2.1's `$COLUMNS` form.
- `influx_sync` / `influx_upload`, `harness_log_check.py` and the timebase code to check.
- The BUSMASTER corpus stays, so every tool reads both formats from then on.
- Bug 11's `ERR` lines carry the SocketCAN error frame; TRC's `ER` is PEAK's own layout, so the
  mapping is not one-to-one. Either the rest goes in an `EV` line or the `ERR` decision is
  revisited.
- Not checked: whether Wireshark reads TRC.

### Until then

Bug 4's drop counts and Bug 12's overflow count go to logcat and the notification only. Logs
written meanwhile carry no mark of their drops, and stay that way (the backup uploads each file
once).

---

## Bug 12: gs_usb reads one frame per synchronous `bulkTransfer`; adapter overflow is neither prevented nor recorded

**Found 2026-10-29** on the bench (plan `plans/tryemit-drops.md` Step 1; Bug 4 finding 1). **Open.**
The overflow-flag count ships with Bug 4's fix; whether to fix the read loop is decided after
Bug 4's phone run (its Step 4), owner 2026-10-30. Affects `:coda` and `:vtrux`.

**Files:** `cancore/.../GsUsbDevice.kt` (`readFrames`), `cancore/.../CanPipelineManager.kt`

`GsUsbDevice.readFrames` issues one synchronous 20-byte `bulkTransfer` per frame, the pattern
Bug 8 describes for USB CDC, so the read rate has a ceiling of about one frame per USB round trip.
The adapter marks a frame with `GS_CAN_FLAG_OVERFLOW` (`GsUsbFrame.flags & 0x01`) after it has had
to discard frames; the app parsed `flags` but never checked the bit. (The kernel driver turns the
same bit into a `CAN_ERR_CRTL_RX_OVERFLOW` error frame and counts it in `rx_over_errors`.)

### Evidence

In the AVD with the Innomaker passed through, the log lost 22% at 100% bus load and 2.6–4.8% at
75%, with zero failed `tryEmit`s and the overflow flag never set; the kernel driver received every
frame at the same loads. Details in Bug 4, "Measured on the bench". **Caveat:** the AVD's USB
passthrough runs on the emulator's CPU, so this may not happen on a phone.

**On a phone (2026-10-30, OnePlus 7T; Bug 4, "Measured on a phone"):** no loss up to 95% bus load
(3,843 fps); on a fully saturated bus (~4,015 fps) 0.5% and 1.3% in two runs, all before `tryEmit`,
with the overflow flag never set. So the read loop's ceiling on this phone is just under a
saturated 500k bus of 8-byte frames, well above Vtrux's ~2,400 fps per adapter.

### Fix

- **Ships with Bug 4:** count frames with the overflow flag set (`gs_usb.overflowFlag`), reported with Bug 4's drop counts. In code 2026-10-30.
- **Queued reads (async `UsbRequest`, as Bug 8's fix): not needed for now** (owner, 2026-10-30, on
  the phone results). Reopen if a slower phone or a busier bus shows loss before `tryEmit`.

---

## Bug 11: CAN error frames are logged as ordinary standard frames `0x004` / `0x00C`

**Found 2026-10-21** by the gen-inhibit reviewer session, while measuring the truck's real
CAN error-frame rate from the logs. **Fixed 2026-10-30, plan `plans/gs-usb-error-frames.md`
(done); in the 1.1 release builds of `:coda` and `:vtrux`, not yet installed on the vehicles.**

**Files:** `cancore/.../GsUsbFrame.kt` (`arbitrationId`, `toCanFrame`), `cancore/.../GsUsbDevice.kt`
(start mode, `computeBittiming`)

### What the code does

`GsUsbFrame.arbitrationId` is `rawCanId and 0x1FFFFFFF`. The class decodes bit 31 (EFF) and
bit 30 (RTR) but never looks at bit 29, which gs_usb uses as `CAN_ERR_FLAG`. An error frame
from the adapter therefore goes through `toCanFrame()` like any received frame. It is written
to the BUSMASTER file as a standard frame whose ID is the SocketCAN error-class bitmask
(`0x004` = controller, `0x00C` = controller + protocol), DLC 8. Nothing in the file marks it
as an error frame.

### What is in the logs

Census of standard IDs below `0x400` (internal-only script, phase `census`):

| Where | `0x004` DLC 8 | `0x00C` DLC 8 |
|---|---|---|
| `CANLogs/VtruxLogs/` (2,031 files) | 18,206 frames in 260 files | 22,655 frames in 246 files |
| `projects/vtrux/logs/`, 61 Innomaker-header files | 2,084 in 48 files | 1,271 in 48 files |

Neither ID is defined in any Vtrux DBC. The Kvaser-header (laptop) files in
`projects/vtrux/logs/` have none in this form. Coda logs, which come through the same
`:cancore` path, carry them too: the 2026-10-09 anchor audit found `0x00C` on B and D CAN and
`0x004` on B CAN, before they were understood to be error reports (`projects/coda/README.md`,
anchor section). They have not been counted with this census script.

The payloads match the SocketCAN error-frame layout (`linux/can/error.h`):
- `data[2]` is the protocol error type: `0x04` stuff, `0x02` form.
- `data[3] = 0x08` is the CRC-sequence location.
- `data[6]` is the transmit error counter and `data[7]` the receive error counter. The REC
  reaches `0x19`.

### A `0x00C` is not attached to every error

Checked on 2026-09-06 against the laptop gen-inhibit runner (python-can + Kvaser), which logged
its error frames with timestamps (`runs/truck_real3.errors.csv`, `runs/truck_passive2.errors.csv`
in the internal-only gen-inhibit bench artifacts).

**Every laptop error frame that the Android capture covered is in the Android log.**
- That is 11 of 11: all 9 of `truck_real3`, and 2 of `truck_passive2`. Its other 2 fell before
  the Android chunk began.
- They match within ±9 ms at a constant clock offset of 5.026 s.
- **6 of the 11 appear only as `0x004` reports.** Each is a pair, REC 0 -> 1 then 1 -> 0,
  with no `0x00C`.

So counting `0x00C` frames undercounts error frames. Any analysis has to count **rises of the
error counters** (REC or TEC above the previous report on the same channel) instead.

### The adapter is started in normal mode, not listen-only

`GsUsbDevice` sends `MODE=START` with flags `0`, so the Innomaker is a normal bus participant:
it ACKs frames and takes part in error signalling. Bit timing comes from `computeBittiming()`:
- SJW fixed at 1 tq;
- `propSeg` 1;
- `phaseSeg2` = total tq / 8.

**Decided 2026-10-28 (user): all Android apps stay in normal (regular) mode**, not listen-only,
so Coda and Vtrux behave the same although Vtrux never transmits. Coda's `PeriodicTransmitter`
(TPMS `0x600`) needs normal mode anyway.

**The logger may be causing the errors it records (user, 2026-10-21, a hypothesis, not
shown).** The idea is that the errors arise on the logger's receive side, for example from a
ground loop or a USB/hub problem in how it is hooked up. Because it runs in normal mode, any error it detects is
signalled on the bus as an error flag, so other nodes see it too. That would fit the laptop
seeing the same errors on 2026-09-06.

On the main truck, the errors disappear from 2026-07-14 10:28 to 2026-07-26, a period when the
logger was hooked up differently. That covers about 15 h of powertrain traffic with 3 events,
and the logger received both buses throughout. As a result, the truck's real error-frame rate is
unconfirmed. Details are in the gen-inhibit truck-test notes (internal-only),
*Update 2026-10-21*.

### Consequences

- Any tool reading these logs sees two extra standard IDs. Unless it knows they are error
  reports, it treats them as messages, including in ID histograms and bus identification.
- A real message on ID `0x004` or `0x00C` would be indistinguishable from these reports in an
  Android log.

### Fix (done 2026-10-30)

Plan: `plans/gs-usb-error-frames.md`. Decided 2026-10-28 (user): error frames are kept in the
log, written as a BUSMASTER line with type token `ERR` (e.g.
`Rx 1 0x00C ERR 8 00 00 02 00 00 00 00 1A`); the plan's decisions table has why.

The fix changes what future logs contain. The historical corpus stays as described above.

Bench result 2026-10-28 (plan Step 5): the fixed app and the Linux kernel's `gs_usb` driver
decode the Innomaker's error reports identically. The same run found that the Innomaker reports
its error state once a second at most (a hypothesis tested by 10 of 10 predictions; see the
plan). If the truck's adapter behaves the same, the counts in the table above are seconds in an
error state, not errors; that is inference, not checked on the truck.

Phone result 2026-10-30 (plan Step 6): the same matrix on the OnePlus 7T with the Innomaker on
OTG passed, with the same error classes per phase as the kernel driver; the adapter never set its
receive-overflow bit.

### Seen on the bench, not part of this bug: queued `0x600` frames go out in a burst (`:coda`)

In the Step 5 bench run (plan `plans/gs-usb-error-frames.md`), while the Innomaker's `0x600`
lamp frames could not be sent (no other node to ACK them, or a bus fault), the app kept queuing
one every 525 ms. When the fault cleared they all went out back to back: 16 in about 8 ms after
10 s without ACK, 26 in about 13 ms after 15 s of bus errors. The Linux kernel driver queued 16
the same way, so it is not unique to the app. On the car that would put a burst of stale lamp
frames on B CAN after any disturbance that stops the head unit's frames going out. What the IPK
makes of it is unknown. An observation for the TPMS lamp work, not yet a change request.

---

## Bug 10: `:p914` road logs lose 25-40% of frames, and nothing in the log can say which survivors are damaged

**Found 2026-09-28** on the first road drives. **Open, TBD** -- both how to diagnose it and how
to fix it are outstanding. Full analysis in the 914 hub, `914/notes/drive-logs.md`.

**Files:** `p914/.../UsbCdcSerial.kt` (read path), `cancore/.../SlcanReader.kt` (integrity frame
handling), `cancore/.../CanLoggingService.kt` / `BusmasterWriter.kt` (what reaches the log)

### Symptom

| Session | Phone | Fast tier (design 10 Hz) | Frames delivered |
|---|---|---|---|
| `p914_20260818_212356` (stationary) | OnePlus 7T | 9.94 Hz | ~99.5% |
| `p914_20260928_124016` | P8 Pro | 6.7 Hz | ~68% |
| `p914_20260928_182527` | P8 Pro | 7.4 Hz | ~74% |
| `p914_20260930_123707` | OnePlus 7T | 6.1 Hz | ~61% |
| `p914_20261009_181812` (parked, charging, screen off, 6.2 h) | OnePlus 7T | 1.80 Hz (design 2 Hz while charging) | ~90%, flat for 6 h |

Established in the hub note: the VCU emits the stream intact (a laptop capture of the same
firmware has a continuous integrity sequence); motor load does not drive the loss; the rate
changes with time within a session, differently per phone (on 2026-09-30 it stepped from ~90% to
~55% about 150 s in, with the car parked); it never stops outright (longest gap 279 ms); and the
lost frames come in small runs, most often 3 consecutive frames.

### Integrity frames are not logged

`SlcanReader` consumes `0x1FFFFFFF` in `handleIntegrity()` and never passes it to `onFrame`, so
no `:p914` log contains one. The reader's CRC verdicts reach only logcat (tag `P914`); the log has
no way to say which blocks were damaged. Corrupted frames that still parse as well-formed SLCAN are
logged as real data -- junk IDs, wrong-DLC frames, and one-frame wild values (an inverter "Off"
frame mid-drive, `InvDcVoltage` 4789 V). How to fix this is **TBD**: e.g. write the integrity
frames into the BUSMASTER file so a reader can re-check blocks, or drop or mark frames from a
block whose CRC fails. Not decided.

### Current theory: the phone collects too late (Bug 8 is part of it) -- updated 2026-10-10

Full reasoning and evidence in `914/notes/drive-logs.md`, "Where the data is lost". Summary:

- **Not the app's buffers**: 16 KB reads on a dedicated thread, a 64-deep queue, no overruns.
- **USB does not drop data on the host.** Bulk IN is host-initiated, so data the phone has not
  asked for waits on the device -- the mbed interface MCU bridging the VCU's 460800-baud UART to
  CDC. With no flow control on that UART, data is lost when the bridge's buffer fills. (Bug 8's
  "discarded by the host controller" is the wrong place; the consequence for the app is the same.)
- *Hypothesis:* the holes are the bridge losing whole 64-byte packets because the phone is late.
  Hole sizes match the 64-byte quantum; the same bridge read by a laptop lost 0.0188% of frames on
  2026-08-09; burst starts are lost most; the rate follows phone state, not the car.
- How the phone is late is open: turnaround between synchronous reads (Bug 8), or the phone's USB
  controller polling the device only occasionally. Holes sit at the phone's receive-clump
  boundaries 3-10x more often than chance but mostly inside clumps -- not decisive, because frames
  are stamped at parse time and a clump can hold several reads.

### Diagnosis -- open

Candidate steps, none decided:

- Pull the `P914` logcat counters (`blocksCrcBad`, `blocksCountBad`, `malformed`) across a drive,
  to see whether the reader is rejecting damaged data or the data never arrives.
- Note phone state during a logged drive (screen on/off, app in foreground, other apps) and
  line it up against delivery per 10 s window (`914/notes/artifacts/drive_log_loss.py`).
- A laptop capture in the car while driving, to separate the phone from the cable and the
  in-car environment.
- Implement Bug 8's fix (async `UsbRequest`, two or three queued) and compare delivery.
- Log each USB read in the reader thread (completion time, bytes, time until the next read is
  queued), which makes the clump-boundary test decisive.
- VCU side: make the output less bursty (pace the slow-tier frames across the cycle, or a lower
  baud rate) so the bridge's buffer rides out a late phone.

---

## Change 9: live-display throttle tile should use `Accelerator_Actual_Position`, not TPS

**Found 2026-08-14.** **Not implemented — owner deferred pending a decision on whether to show both.** Not a defect; the tile works. It is showing the weaker of two available signals.

**File:** `vtrux/src/main/assets/live-display/manifest.json` (currently lines 91–93)

```json
"signals": ["Throttle_Position"],
"_note": "0x3D1 VCM-commanded throttle, best APP proxy on GMLAN"
```

### Why it is there

The tile was built when the project believed no accelerator pedal magnitude existed on CAN, so TPS was genuinely the best available stand-in. That belief came from the deprecated GMLAN DBC extraction, which omitted the APP magnitude signals and merged 0x0F1 brake-pedal signals into 0x0C9. The DBC has since been regenerated and does define them; the notes were corrected 2026-08-14 but this manifest was not. The `_note` string is now inaccurate.

### What to use instead

`Accelerator_Actual_Position` — `0x0C9` `Engine_General_Status_1`, **OBD bus**. Present across the corpus: 494k points over 64 sessions, full 0–99.6% range. (`Accelerator_Effective_Position`, 0x1C3, is also populated if a second signal is wanted.)

### Why it is better

Measured on session `vtrux_20260724_211556`, 994 paired 10 s samples:

| Pair | r |
|---|---|
| APP vs `Engine_Speed` | 0.968 |
| APP vs `Throttle_Position` | 0.708 |

More visibly for a live display: **with the engine off, APP reads 0.0 while TPS sits at ~29.4%.** The current tile therefore shows roughly a third of throttle on a stationary truck with the engine stopped, which is the main user-facing symptom.

TPS is the throttle *body* position, which the ECM modulates on its own for idle control and torque management. APP is the demand going into the ECM — the analog voltage the VCM generates via the APP GEN MOD, echoed back onto CAN.

### Open decision

Whether to replace the tile or show both. Both is defensible — APP vs TPS divergence is exactly what you would watch to spot the ECM overriding the VCM's request — but it costs a tile slot. If replaced, delete the now-wrong `_note` rather than carrying it over.

**Pending investigation (owner, 2026-10-29):** whether the ECM ever actually overrides the VCM's
request is unchecked. Look for it in the full data set before deciding replace-or-both. On hold
until Bug 4 is wrapped up.

### Set the gauge range to 0–70%, not 0–100%

Not a drop-in equivalence. APP's **confirmed operating range is 0–66%** — verified across the whole InfluxDB corpus (494,053 points, 161 sessions, 2026-02-17 to 2026-08-02): 99.99% of points fall below 65%, and sessions top out at 65.5–66.3%. The VCM never commands more than about two-thirds pedal.

So a tile scaled 0–100 to match TPS's full swing will show a needle that never passes two-thirds. **Scale this tile 0–70%.**

Corollary worth surfacing in the UI if cheap: a reading above ~70% is a fault signature rather than driver input. Only 48 points in the entire corpus exceed 66%, and the ones reaching full scale occur in stationary charging captures where the pedal is at rest — bit errors, not travel. See `projects/vtrux/README.md` (APP section) and `projects/vtrux/notes/artifacts/app_range_corpus.py`.

---

## Bug 8: USB CDC reads drop bytes — synchronous `bulkTransfer` leaves gaps

**Found 2026-08-13** during `:p914` A6 bring-up against the live car. **Deferred by owner decision** — the transport works; this is a quality improvement.

**Update 2026-09-30:** current theory for the 25-40% frame loss on the first road drives -- see Bug 10.

**Correction 2026-10-10:** the Cause below says data is "discarded by the host controller". Bulk IN
is host-initiated, so unread data waits on the device (the mbed interface MCU) and is lost when
its buffer overflows. The remedy is unchanged -- keep a read always queued. See Bug 10.

**File:** `p914/.../UsbCdcSerial.kt`

### Symptom

Integrity blocks fail at roughly **0.4–0.7% steady state** (1.0% including a startup burst) against **0.2–0.4%** for the same VCU stream read by the laptop over the same USB CDC link.

In all 13 measurement samples `crcBad == cntBad` **exactly**. Blocks come up short rather than arriving damaged, so this is dropped bytes, not bit errors.

### Cause

Android's `UsbDeviceConnection.bulkTransfer()` is a single synchronous URB. USB bulk has no flow control at this layer, so anything the device sends while no transfer is queued is discarded by the host controller.

The first implementation read and parsed on one thread, which was much worse (~0.6% steady plus a large early burst). Moving to a dedicated reader thread with a bounded queue cut it roughly in half — but it cannot eliminate it, because a gap remains between `bulkTransfer` returning and being called again. No queue overruns were ever logged, confirming the loss is upstream of the app's buffer.

### Fix

Use asynchronous `UsbRequest` with two or three requests queued in rotation, so a transfer is *always* outstanding:

```kotlin
val req = UsbRequest().apply { initialize(connection, readEndpoint) }
req.queue(buffer)                    // repeat for N buffers
val done = connection.requestWait()  // returns the completed request; re-queue immediately
```

### Also unseparated

The phone writes the BUSMASTER log at ~14 KB/s and runs the frame flow collection while reading; the laptop was doing nothing but reading. Some of the difference may be load rather than the read design, and the two were not separated.

### Startup burst

8 of the 20 failures land in the first 10 seconds (4.9%, against ~0.5% after). Not explained. Ruled out: a target reset from asserting DTR/RTS — frame rate is a flat 262/s from second zero with no stall or ramp.

## Bug 6: `attemptRootOtgRecovery()` cannot work on LineageOS 14 — SELinux denies the role write

**Found 2026-08-13** during `:p914` USB bring-up, on the **same OnePlus 7T the truck uses**. **Not fixed.**

**File:** `vtrux/.../VtruxApplication.kt` → `attemptRootOtgRecovery()`

### What is actually happening

`/sys/class/dual_role_usb/otg_default/mode` is labelled `u:object_r:vendor_sysfs_usbpd_device:s0`. SELinux is Enforcing. Root in the magisk domain can **read** the node but **not write** it, and `setenforce` is itself denied. Measured from both the adb shell's `su` and from an app's `su` with the Magisk grant explicitly given — `:p914` was granted and the writes still failed:

```
--- writing ufp ---   ufp write FAILED rc=1
--- writing dfp ---   dfp write FAILED rc=1
```

So the role toggle does nothing on this ROM, from any context available to us.

### The `[ -w ]` guard makes it invisible

```sh
[ -w "$f" ] && echo ufp > "$f"
```

`test -w` checks only DAC permissions, which **root bypasses on every file**. Measured on this device: `test -w` returns 0 while the write is denied. So the guard passes, the write is attempted, SELinux refuses it, and the script exits non-zero.

`canlogger-build-notes.md` attributes "su exited 1/13" to a reset Magisk superuser grant. On this ROM that diagnosis is wrong — it happens with root correctly granted. Any future OTG code should **read the role back** and treat that as the success condition, never the exit code.

### How bad is it

It is a **dead safety net, not a broken primary path.** Normal operation does not use it: with a hub that negotiates properly the phone holds `dfp`/host while charging, which is why the truck works. The recovery only runs when a hub drops a dongle and needs un-sticking — precisely when it will now silently fail.

### Options

- A Magisk module adding `allow magisk vendor_sysfs_usbpd_device file { open write }`. Persistent, and fixes vtrux at the same time. (`magiskpolicy --live` does the same but dies at reboot.)
- Drop the recovery entirely and rely on hub choice plus the rescan loop, matching the 2026-04-01 decision to solve OTG power in hardware rather than software.

---

## Bug 7: charge-and-host simultaneously is hub-dependent

**Found 2026-08-13.** Not a code bug — recorded so it is not re-diagnosed as one.

The truck's setup (**Genesys Logic USB3.1 hub, VID `05e3` PID `0626`**) sustains USB host *and* phone charging together. A different powered hub on the 914 bench did not: the phone settled at `ufp` / `data_role=device` / `power_role=sink`, enumerated nothing at all, and only entered host mode briefly after a physical replug before reverting. The owner confirmed the phone was not charging during that host-mode window.

With **hub power removed entirely** the phone holds `dfp`/host reliably and the VCU enumerates. So the phone is capable; the hub decides.

**Implication for the 914 install:** the phone must both host the VCU and charge, or it will flatten on a drive. Use the hub model known to work, and verify `mode`/`data_role` on any new hub before trusting it — the failure is silent, presenting as "no USB device" rather than an error.

## Bug 4: `tryEmit` drops frames silently when a collector falls behind

**Found 2026-08-13** during `:p914` bring-up. **Fixed 2026-10-30 (plan `plans/tryemit-drops.md`, done; "Implemented" below); in the 1.1 release builds of all three apps, not yet installed on the vehicles.** Measured on the bench 2026-10-29, fix chosen 2026-10-30. Affects all apps.

**Files:** `cancore/.../CanPipelineManager.kt`, `cancore/.../SlcanFrameSource.kt`

Both publish frames with `_frames.tryEmit(frame)` onto a `MutableSharedFlow(extraBufferCapacity = 1024)`. `tryEmit` returns `false` and **discards the frame** when the buffer is full; neither call site checks the return value, so the loss is invisible.

### Evidence

Replaying a capture over TCP unpaced (`slcan_bridge.py --rate 0`, effectively socket speed) produced twelve log sessions totalling ~357 KB where each pass should have written ~880 KB. The same capture paced to the measured car rate logged completely. Nothing reported an error in either case.

### Measured on the bench (2026-10-29)

Plan `plans/tryemit-drops.md` Step 1, on the Linux box: IXXAT flooding sequence-numbered frames
into the Innomaker, Coda debug build in the AVD with the Innomaker passed through, plus the Coda
SLCAN harness replaying `coda_20260618_195906`. Raw results in
`artifacts/tryemit_20261029/`; the instrumented build counts every failed `tryEmit` per flow and how
far each collector falls behind. Reviewed by the owner 2026-10-29.

1. **In the AVD, gs_usb loss happens before `tryEmit`, not in it.** The kernel's `gs_usb` driver
   received every frame at every load (242,704 of 242,704 at 4,045 fps). The app lost 22% of the log
   at 100% bus load and 2.6–4.8% at 75%, none at 50% or below (Bug 11 build and instrumented build
   alike), and in every instrumented run `tryEmit` failed **zero** times on both flows, collectors never fell more than 62 frames behind,
   and the adapter never set its overflow flag (`GS_CAN_FLAG_OVERFLOW`, which the app did not check
   before). `GsUsbDevice.readFrames` does one synchronous 20-byte `bulkTransfer` per frame (the
   Bug 8 pattern), so the read loop sets a ceiling and the adapter discards the excess without
   saying so. **Caveat:** in the AVD the USB passthrough runs on the emulator's CPU, so capping the
   CPU throttles the USB path itself (loss rose to 45–97% under CPU quotas, still with zero `tryEmit`
   failures). A phone's USB controller is hardware; whether a phone shows the same loss is Step 4's
   question.
2. **When a collector does stall, the counter is exact and the headroom is 1024 frames / rate.** A
   debug hook made one collector sleep once, at 50% load (2,022 fps, predicted headroom ~506 ms).
   Stalling the log writer: no loss at 100–450 ms; 193, 607 and 1,421 frames lost at 600, 800 and
   1,200 ms against ~190, 594 and 1,403 predicted; frames missing from the log equal the failed
   `tryEmit` count exactly (2,221). Stalling the display-side collectors (`viewmodel`,
   `app-observers`) lost ~2,200 frames from the `frames` flow and **none** from the log, as Bug 11's
   separate `logFrames` flow intends.
3. **The SLCAN harness does hit the `tryEmit` limit**, and its slowest collector is the log writer
   (the harness has one flow, so the slowest collector gates everything). Unpaced (~89k fps):
   1,258,179 of 1,433,713 frames failed; logged + failed = total exactly. At 3x speed (~7.2k fps,
   about Vtrux's rate) nothing was lost, but the log writer fell up to 748 of 1024 frames behind
   (105 ms). 5x lost 2.5%. 3x with the CPU capped at 2 cores' worth lost 36%; on a 1-core AVD, 2,199
   frames, 1,744 of them during app start.
4. **Hypotheses (not measured on a phone):**
   - At Vtrux's ~7,100 fps the buffer is about 140 ms of slack, and the bench used up to 73% of it on
     a fast host, so a slower phone will probably drop log frames to `tryEmit`.
   - App start is the weakest moment (most of the 1-core loss fell there).
   - On gs_usb, the per-frame synchronous read may be a larger, silent loss than `tryEmit` for
     Vtrux's ~2.4k fps per dongle.

Side observations, not Bug 4: under a 50% CPU quota Coda crashed at start
(`ForegroundServiceDidNotStartInTimeException` from `GpsSpeedService`, then an ANR); and
`tools/harness_log_check.py` misaligns once frames are dropped, so the emitted count equals the
logged count is the reliable check there.

### Measured on a phone (2026-10-30)

Plan Step 4's measurement half, run before Step 3 (owner, 2026-10-30): the OnePlus 7T (LineageOS 21,
Android 14) with the Innomaker on OTG, the same IXXAT flood, Coda debug build with the counters, 60 s
per run. Raw results in `artifacts/tryemit_20261030_phone/`. Reviewed by the owner 2026-10-30.

| Load (fps) | Lost | `tryEmit` failed | Overflow flag | Log writer, furthest behind |
|---|---|---|---|---|
| 25% (1,011) | 0 | 0 | 0 | 16 frames / 16 ms |
| 50% (2,023) | 0 | 0 | 0 | 80 / 33 ms |
| 75% (3,034) | 0 | 0 | 0 | 142 / 46 ms |
| 85% (3,438), 90% (3,641), 95% (3,843) | 0 | 0 | 0 | ~200 / ~52 ms |
| 100% (4,016), run 1 | 0.51%, all in the first 2 s | 0 | 0 | 130 / 106 ms |
| 100% (4,015), run 2 | 1.28%, ~50/s throughout | 0 | 0 | 194 / 48 ms |

- **Phone vs emulator:** the phone loses frames before `tryEmit` only on a fully saturated bus, and
  never sets the overflow flag; the AVD's 22% (100%) and 2.6–4.8% (75%) were mostly the emulator.
  So finding 1's loss is real but sits at the very top of the range on this phone (Bug 12).
- **Stalls, 1024 buffer:** log-writer stalls at 50% lost 203, 603 and 1,420 frames at 600, 800 and
  1,200 ms (AVD 193/607/1,421), and nothing at 100–450 ms. 63 more single frames were lost around the
  stalls while the writer caught up; all counted (2,289 missing = 2,289 failed).
- **Stalls, 16k buffer (the chosen fix, built early):** no loss at 1.2, 4 and 7 s; 3,885 at 10 s,
  against ~3,840 predicted (10 s x 2,023 fps − 16,384); missing = failed exactly.
- **A faster log writer is not needed on this phone:** it kept within ~200 frames (~52 ms) at every
  load up to 95%.
- Finding 4's hypotheses are not settled by this phone: the gs_usb test is one bus at up to
  4,000 fps, not Vtrux's ~7,100 fps across three adapters.

Bench notes: the first 25/50/75% runs were invalid. Each run's screen-off/on cycle left the
phone's secure lock screen up, which blanks the display after 10 s whatever the screen timeout; the
re-runs held the screen on with `dumpsys battery set ac 1` and `svc power stayon true` (both undone
afterwards). In two of those runs Coda crashed at the screen-off (`IOException: Stream closed`:
`CanLoggingService.stopLogging` closes the writer while the log-writer collector is mid-write).
Owner, 2026-10-30: not a real-world concern, since Vtrux holds the screen on, Coda's display is
always on and `:p914` does not stop logging.

### Why it has not bitten in the field

The measured 914 link delivers 6705 B/s in ~1 KB bursts every ~212 ms — orders of magnitude below the buffer. Vtrux runs ~7,100 fps across three buses, which is closer but has not shown loss. So this is a latent hazard rather than an active bug.

### Why it is still worth fixing

The failure is silent, and the whole logging design elsewhere is built so damage is *detectable* — the SLCAN integrity frame exists precisely so lost frames announce themselves. A drop path that reports nothing contradicts that. Options: count failed `tryEmit`s and surface the count alongside the other link-health stats (cheapest, preserves current behaviour), or switch to a suspending `emit` with real backpressure (correct, but blocks the reader thread and changes timing).

### Fix (decided 2026-10-30, owner)

- **Larger buffer for the log writer:** 16,384 frames instead of 1024 on the flow the log writer
  reads, about 2 s at Vtrux's ~7,100 fps and roughly 1–2 MB. On gs_usb that is `logFrames` only; on
  the SLCAN paths the log writer shares one flow with the display, so it is that flow. This absorbs
  stalls, not a sustained rate above what the writer can keep up with.
- **Count and surface:** a failed-`tryEmit` count per flow, always on, and Bug 12's overflow-flag
  count, reported to logcat periodically and shown in the notification. `:p914` reports too, so
  Bug 10 can be checked for `tryEmit` loss from logcat (owner, 2026-10-30). The per-collector
  measurements and the stall hook stay in debug builds only.
- **Not recorded in the log** until the move to TRC (Change 13); no sidecar file.
- **Not chosen:** backpressure (a suspending `emit`). On gs_usb it blocks the read thread and moves
  the loss into the adapter, where Bug 12 shows nothing counts it. **Held:** a faster log writer,
  only if the phone run (plan Step 4) shows the writer cannot keep up.

### Implemented (2026-10-30, plan Step 3)

- **Buffer:** `CanFrameSource.LOG_BUFFER_FRAMES = 16_384`, used by `CanPipelineManager`'s `logFrames`
  and as the default for `SlcanFrameSource` and `SlcanBusGroup`. `CanPipelineManager.frames` stays
  at 1024.
- **Counts:** `FlowHealth` (`:cancore`) counts every `tryEmit` result per flow (`pipe.log`,
  `pipe.frames`, `slcan.frames`, `harness.frames`) and the adapter's overflow flag
  (`gs_usb.overflowFlag`, Bug 12). `CanLoggingService.onCreate` starts its reporter in every app and
  build: logcat tag `TryEmit` every 10 s. The notification ends with `FlowHealth.summary()`:
  `drops 0`, or each non-zero count by name, e.g. `drops pipe.log=12`.
- **Debug-only, unchanged:** collector measurements (`watched()`), the 2 s report and the
  `DEBUG_STALL` hook, in Coda only, gated on `FLAG_DEBUGGABLE`. That gate is right only once the
  vehicles run release builds (Change 15).
- **Removed:** the per-read USB timing (`gs_usb.bulkIn`), bench-only.
- **Tests:** `FlowHealthTest` (5): counting with measurements off, the notification summary, and
  the 16k buffer on the gs_usb and SLCAN paths. Putting the SLCAN buffer back to 1024 fails its test.
- **AVD check** (Coda SLCAN harness, `coda_20260618_195906` T0+T1 unpaced, 1,433,713 frames; raw
  results in `artifacts/tryemit_20261030_step3/`): logged + counted drops = 1,433,713 exactly in
  every run, with the emitted count equal to the frames in the app's log (release 347,266 and
  344,453; debug 219,936). Release reported every 10 s with no collector lines; debug every 2 s
  with them, the log writer peaking at exactly 16,384 frames behind. The notification went from
  `drops 0` to `drops harness.frames=188306` and `412558` during the flood. The gs_usb notification
  was not checked live (no Innomaker on the host); it uses the same code and its buffer has a JVM
  test.

---

## Bug 5: every reconnect starts a new log session

**Found 2026-08-13** during `:p914` bring-up. **Not implemented.** Design question, not a defect.

**File:** `cancore/.../CanLoggingService.kt`

`onTriggerActive()` resets `sessionTag` and opens a new `T0` file whenever the trigger goes inactive then active again. For `:vtrux` that is right — the trigger is ignition, and a new drive deserves a new session. For `:p914` the trigger is "the SLCAN source is attached", so a momentary USB dropout mid-drive would split one drive across many files.

Observed directly: twelve files in 25 seconds while the replay bridge closed the stream after each pass. With a continuous stream, one session was written, so the logging path itself is sound.

**Open:** whether a short reconnect (say under 30 s) should resume the existing session rather than start a new one, and whether that should be per-vehicle policy. Note the counter-argument — a resumed session hides the gap, and the BUSMASTER format has no way to mark a discontinuity, so a reader would see a clean timeline across a real dropout.

**Owner ruling 2026-08-13: acceptable as-is, revisit only if it becomes a nuisance in practice.** Confirmed live on the 914 during the A6 replug test — a detach/reattach produced two files (530 KB, then 332 KB). Given the counter-argument above, splitting is arguably the safer default anyway: a new file is an honest marker that the stream was interrupted.

## Bug 1: No debounce in `CanPipelineManager.addDevice()` causes permanent "stuck waiting for dongle" state

**Fixed 2026-05-03** — `delay(OPEN_DEBOUNCE_MS)` (4000ms) added as first line of the coroutine in `addDevice()`. `WAKE_LOCK` permission added to vtrux `AndroidManifest.xml`.

**File:** `cancore/src/main/java/com/reverseit/cancore/CanPipelineManager.kt`

### Trigger conditions
- Hub already connected to phone (OTG VBUS-powered), both dongles pre-installed in hub, then 12V applied to hub
- Confirmed also reproducible when screen goes to sleep while dongle is active (see Bug 2)

### Root cause
When the hub transitions from bus-powered (phone's OTG VBUS 5V) to self-powered (vehicle 12V), it
power-cycles its downstream ports. The downstream devices re-enumerate and Android fires
`ACTION_USB_DEVICE_ATTACHED` during this transitional window (typically 0.2–0.6s after
`POWER_CONNECTED`). `addDevice()` immediately calls `gsDevice.open()` with no delay.

`open()` sends `GS_CAN_MODE_RESET` as its first control transfer. The hub's 12V supply isn't stable
yet, so the device can't respond. `controlTransfer()` times out after 1000ms. `ctrl()` only logs a
warning — it does not throw — so subsequent steps (HOST_FORMAT, DEVICE_CONFIG, etc.) also fire and
also fail. Android detects the failed USB communication and fires `ACTION_USB_DEVICE_DETACHED`.

The failure corrupts the USB endpoint state on the device. When the hub completes its transition
(~4s after `POWER_CONNECTED`), the device cannot respond to re-enumeration. Android never fires
another `ACTION_USB_DEVICE_ATTACHED`. The 90-second rescan (45 × 2s) finds nothing and gives up.
App stays in "waiting for dongle" indefinitely.

### Why V3.4.3 + V3.3 fails but V3.3 alone works
V3.4.3 (newer hardware revision) re-enumerates at ~0.2s after `POWER_CONNECTED`, and its presence
causes the hub to present V3.3 in parallel at ~0.6s. Without V3.4.3, V3.3 alone re-enumerates at
~4s — by which time the hub transition is complete and the ctrl transfer succeeds. This is why
single-dongle operation with normal plug sequencing is reliable.

### Evidence
From internal debug log (collected 2026-04-25, previous session):
```
11:27:10.278  POWER_CONNECTED
11:27:10.491  USB attached: USB2CAN V3.4.3   (+0.2s — transition in progress)
11:27:10.703  USB attached: USB2CAN V3.3     (+0.4s — transition in progress)
11:27:11.587  Innomaker detached: 1007       (ctrl timeout ~1s after attach)
11:27:11.591  Innomaker detached: 1008
11:27:13+     Rescan: no devices, 45 attempts, gave up
```

1-dongle success (same log):
```
11:26:20.236  POWER_CONNECTED
11:26:24.349  USB attached: USB2CAN V3.3     (+4.1s — transition already complete)
              → open() succeeded, logged for 6 seconds before next power event
```

### Proposed fix
Add `delay(OPEN_DEBOUNCE_MS)` as the first line of the coroutine in `addDevice()`, before calling
`gsDevice.open()`. `delay()` is a coroutine cancellation point: if the device detaches during the
delay window, `removeDevice()` cancels the job cleanly, and the subsequent `ATTACHED` event starts a
fresh `addDevice()` with its own delay. Nothing corrupts the device's USB state during the wait.

```kotlin
// In CanPipelineManager:
companion object {
    private const val TAG = "CanCore"
    private const val OPEN_DEBOUNCE_MS = 4_000L
}

// In addDevice():
val job = scope.launch {
    delay(OPEN_DEBOUNCE_MS)
    try {
        gsDevice.open()
        ...
```

Delay value rationale: the hub's power-source transition takes ~4s to complete (observed from
1-dongle success case where V3.3 appeared at t+4.1s and worked immediately). A 4s delay puts
`open()` at t+4.2–4.6s for V3.4.3/V3.3 respectively — just past the stability point.

The `GS_CAN_MODE_RESET` step in `open()` is intentional and must be preserved — it puts the device
into a known state in case it was left in `MODE=START` by a previous session. The fix is to not call
`open()` until the device is stable, not to skip the reset.

---

## Bug 2: No `WakeLock` in `CanLoggingService` — screen sleep can kill USB logging

**Fixed 2026-05-03** — `PARTIAL_WAKE_LOCK` acquired in `startLogging()`, released in `stopLogging()`.

**File:** `cancore/src/main/java/com/reverseit/cancore/CanLoggingService.kt`

### Root cause
`CanLoggingService` holds no `PARTIAL_WAKE_LOCK`. When the screen goes off, Android can enable USB
autosuspend on downstream devices. This suspends the dongle, Android fires
`ACTION_USB_DEVICE_DETACHED` + `ACTION_USB_DEVICE_ATTACHED` on wake, and the new `ATTACHED` event
triggers `addDevice()` → `open()` during the USB resume transition — the same ctrl-transfer-too-early
failure as Bug 1.

Additionally, without a wake lock the CPU can enter idle states that prevent the USB host controller
from servicing bulk transfer interrupts reliably, causing degraded frame rates even when the device
doesn't fully detach.

### Evidence
- Session `vtrux_20260425_165909`: T2 chunk (starts 17:09:09) has only 1:06 of data before dongle
  drops. Gap runs from 17:10:15 to session end at 17:15:06 (4:51 of silence while "logging"
  indicator was still showing in the notification bar). Timing is consistent with a ~1-minute screen
  timeout triggering USB suspend.
- Session `vtrux_20260425_110221`: 51KB file (~empty). Morning charge gap at 10:37–11:02 similarly
  unlogged.
- `grep -r WakeLock android-app/CanLoggerApps` returns no matches — confirmed no wake lock anywhere
  in the codebase.

### Proposed fix
Acquire a `PARTIAL_WAKE_LOCK` when logging starts, release it when logging stops.

```kotlin
// In CanLoggingService:
private var wakeLock: PowerManager.WakeLock? = null

// In startLogging() (or wherever the log job starts):
val pm = getSystemService(POWER_SERVICE) as PowerManager
wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CanLoggingService::logging")
wakeLock?.acquire()

// In stopLogging() (and onDestroy()):
wakeLock?.release()
wakeLock = null
```

`PARTIAL_WAKE_LOCK` keeps the CPU running without keeping the screen on. It is sufficient to
prevent USB autosuspend and keep the bulk transfer loop serviced. The `PowerManager` import is
already in `CanLoggingService.kt`.

---

## Interaction between Bug 1 and Bug 2

Bug 2 creates the same precondition as Bug 1: `ACTION_USB_DEVICE_ATTACHED` fires on a device that
is coming out of a transitional state (USB resume instead of hub power-source transition). The
debounce from Bug 1's fix covers this case too — by the time `open()` runs, the device will have
fully resumed from USB suspend. Fixing Bug 2 (wake lock) makes the trigger far less likely to occur;
fixing Bug 1 (debounce) makes the app resilient when it does.

Both fixes are independent and additive. The wake lock should be implemented regardless of the
debounce, since degraded frame rates from CPU idling are also undesirable.

---

## Bug 3: `BusIdentityResolver` latches onto retired bus indices — live display stuck on "Waiting for buses"

**Fixed 2026-07-14** — verified live on the truck mid-charge: banner went from
`Waiting for buses: obd, powertrain` to `Streaming: obd, powertrain`, and the OBD gauges
(engine coolant, ethanol %) populated for the first time.

**File:** `cancore/src/main/java/com/reverseit/cancore/BusIdentity.kt`

### Symptom
The live display sat permanently on `Waiting for buses: obd, powertrain` while the logger wrote
perfectly good data to disk. Battery gauges showed *stale* values (frozen at whatever was on the
bus at the moment identification was lost); the OBD gauges were blank.

The split is the diagnostic tell: **the logger does not care about bus identification** — it writes
every frame regardless — so a resolver failure hides completely in the logs and only ever shows up
on the display.

### Root cause
`CanPipelineManager` **retires bus indices**: `nextBusIndex++` per `addDevice()`, and an index is
never reused. A dongle that re-enumerates (USB hub hiccup, root OTG role toggle, truck power cycle)
therefore returns under a **new** `busIndex`. In the failing session the live log was writing
channels 5 and 6 — the indices had churned well past 0/1.

`BusIdentityResolver` keys its anchor-hit `counts` by `busIndex`, and nothing ever removed the
counts for a dead index. `forget()` explicitly left them, on the reasoning that they would "decay
naturally" — they don't; nothing decays them. Since those counts accumulated over the whole prior
session, they **outweigh** the freshly re-enumerated index in `decide()`'s descending sort, so the
bus name re-latched onto the dead index. `observe()` then returned `null` for every real frame
forever, and `LocalCanDataSource` never left `Handshaking`.

Worse, once a name latched to an index that never produces another frame, nothing could un-latch it:
the `bus_lost` watchdog only forgets buses it saw go *live*, and `decide()` stopped running entirely
once all three names were assigned (`_assignments.size < identities.size` gate).

### Fix
- Resolver tracks `lastSeenMsByBus` (busIndex -> wall ms of most recent frame).
- New `evictDeadBuses()` drops the counts **and** any latched name for any index silent longer than
  `staleBusMs` (5 s, matching `LocalCanDataSource`'s bus_lost threshold), letting the live index win
  the next `decide()`. It runs even when every name is assigned — that is exactly the wedged state.
- `forget()` now clears the stale index's counts as well, so the watchdog path can't re-latch either.
- `decide()` is rate-limited to once per 500 ms (`DECIDE_INTERVAL_MS`) since `observe()` runs on
  every frame at multi-kHz.

### Note for future work
The rate-limit counter must **not** be initialised to `Long.MIN_VALUE` — `nowMs - lastDecideMs`
overflows to a negative value and wedges the gate shut permanently, so `decide()` never runs and
*nothing* is ever identified. Initialise to `0L`. (Hit and fixed during this session; symptom is a
completely blank display rather than a stale one.)

### Not the cause
Power sequencing was the initial suspect and was investigated and **exonerated** — the display taps
`pipeline.frames` directly and never consults trigger/power state. Left as-is.

The OBD anchors (`0x040`-`0x044`) were the second suspect, on the theory that a sleeping engine ECU
silences them during a charge. Measured against the live charge log: **false** — `0x041` and `0x042`
run at 100 Hz while charging (51k anchor hits). The anchors are fine and need no change.
