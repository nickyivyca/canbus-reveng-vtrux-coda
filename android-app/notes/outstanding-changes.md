# Android CAN Logger — Outstanding Changes

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
