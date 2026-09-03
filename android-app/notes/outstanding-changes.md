# Android CAN Logger — Outstanding Changes

Newest first, so the numbers do not run in document order. Index:

| # | Status | Affects | Summary |
|---|--------|---------|---------|
| 9 | open, not implemented | **`:vtrux`** | Live-display throttle tile shows TPS as an "APP proxy". The real APP signal exists and is better; tile should switch to `Accelerator_Actual_Position`, scaled 0–70% |
| 8 | open, deferred | `:p914` | USB CDC reads drop bytes; synchronous `bulkTransfer` leaves gaps. Fix is async `UsbRequest` queuing |
| 7 | open (hardware) | any USB-host vehicle | Charge-and-host simultaneously is **hub-dependent**. Silent failure: presents as "no USB device" |
| 6 | open | **`:vtrux`** | SELinux denies the OTG role write on LineageOS 14, so `attemptRootOtgRecovery()` is a dead safety net. `[ -w ]` guard makes it report success |
| 5 | won't fix | `:p914` | Every reconnect starts a new log session. Owner ruling 2026-08-13: acceptable |
| 4 | open | **all apps** | `tryEmit` drops frames silently when a collector falls behind. Latent, not yet field-observed |
| 3 | fixed 2026-07-14 | `:vtrux` | `BusIdentityResolver` latched onto retired bus indices |
| 2 | fixed 2026-05-03 | all apps | No `WakeLock` in `CanLoggingService` |
| 1 | fixed 2026-05-03 | all apps | No debounce in `CanPipelineManager.addDevice()` |

Bugs 4, 6 and 7 were found while bringing up `:p914` but affect the deployed truck app; 6 in
particular means a recovery path that has been assumed working is not.

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

### Set the gauge range to 0–70%, not 0–100%

Not a drop-in equivalence. APP's **confirmed operating range is 0–66%** — verified across the whole InfluxDB corpus (494,053 points, 161 sessions, 2026-02-17 to 2026-08-02): 99.99% of points fall below 65%, and sessions top out at 65.5–66.3%. The VCM never commands more than about two-thirds pedal.

So a tile scaled 0–100 to match TPS's full swing will show a needle that never passes two-thirds. **Scale this tile 0–70%.**

Corollary worth surfacing in the UI if cheap: a reading above ~70% is a fault signature rather than driver input. Only 48 points in the entire corpus exceed 66%, and the ones reaching full scale occur in stationary charging captures where the pedal is at rest — bit errors, not travel. See `projects/vtrux/README.md` (APP section) and `projects/vtrux/notes/artifacts/app_range_corpus.py`.

---

## Bug 8: USB CDC reads drop bytes — synchronous `bulkTransfer` leaves gaps

**Found 2026-08-13** during `:p914` A6 bring-up against the live car. **Deferred by owner decision** — the transport works; this is a quality improvement.

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

**Found 2026-08-13** during `:p914` bring-up. **Not implemented.** Affects `:coda` and `:vtrux` equally.

**Files:** `cancore/.../CanPipelineManager.kt`, `cancore/.../SlcanFrameSource.kt`

Both publish frames with `_frames.tryEmit(frame)` onto a `MutableSharedFlow(extraBufferCapacity = 1024)`. `tryEmit` returns `false` and **discards the frame** when the buffer is full; neither call site checks the return value, so the loss is invisible.

### Evidence

Replaying a capture over TCP unpaced (`slcan_bridge.py --rate 0`, effectively socket speed) produced twelve log sessions totalling ~357 KB where each pass should have written ~880 KB. The same capture paced to the measured car rate logged completely. Nothing reported an error in either case.

### Why it has not bitten in the field

The measured 914 link delivers 6705 B/s in ~1 KB bursts every ~212 ms — orders of magnitude below the buffer. Vtrux runs ~7,100 fps across three buses, which is closer but has not shown loss. So this is a latent hazard rather than an active bug.

### Why it is still worth fixing

The failure is silent, and the whole logging design elsewhere is built so damage is *detectable* — the SLCAN integrity frame exists precisely so lost frames announce themselves. A drop path that reports nothing contradicts that. Options: count failed `tryEmit`s and surface the count alongside the other link-health stats (cheapest, preserves current behaviour), or switch to a suspending `emit` with real backpressure (correct, but blocks the reader thread and changes timing).

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
