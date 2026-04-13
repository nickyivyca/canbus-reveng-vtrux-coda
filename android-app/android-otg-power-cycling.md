# Android OTG Power Cycling — Ongoing Issue

**Status:** Unresolved as of 2026-03-30. Multiple attempts made; dongle still cycles on/off
when external truck power is absent.

---

## What the symptom looks like

After external power (truck ignition) is removed, the Innomaker CAN dongle repeatedly:
- Loses USB connection (hub loses VBUS)
- Regains USB connection (hub VBUS restored)
- Repeats on a short cycle (~3-5s)

The notification may or may not cycle between "Waiting for power..." and "Logging..." depending
on which fix was active, but the physical dongle cycling is always present.

---

## What we've tried (in order) and why each failed

### Attempt 1: Debounce in CanLoggingService

Added `POWER_LOST_DEBOUNCE_MS`/`POWER_RESTORED_DEBOUNCE_MS` timers inside CanLoggingService to
filter PD renegotiation glitches. Root problem: CanLoggingService and VtruxApplication were BOTH
independently debouncing the same `POWER_CONNECTED`/`POWER_DISCONNECTED` broadcasts, racing each
other. The service-side timers fired at different times from the app-side timers, causing
start/stop oscillation in the logging state.

### Attempt 2: `externalOtgPowerDown` flag in CanLoggingService

Added a flag that VtruxApplication set on the service to suppress power events during the ufp
hold loop. Still failed because there were two independent state machines reacting to the same
events, with flag propagation happening asynchronously over the binder. The root architectural
conflict remained.

### Attempt 3: Remove power event handling from CanLoggingService entirely

Stripped all `POWER_CONNECTED`/`POWER_DISCONNECTED` handling out of CanLoggingService for
TRIGGER_POWER mode. Added `notifyPowerState(active: Boolean)` — VtruxApplication calls it
directly. CanLoggingService is now passive. This was the right architectural fix, but cycling
persisted. The problem is therefore entirely within VtruxApplication's own power state machine,
not the service interaction.

### Attempt 4: Replace Handler loop with single daemon thread

`otgPowerDownRunnable` was posting a new callback every 2s AND spawning a new `Thread` via
`switchOtgRole()` each time. If the su call took longer than 2s, a second thread started before
the first finished — concurrent writes to the sysfs role node caused kernel PD timeouts and brief
dfp glitches. Fixed with a single `otg-power-down` daemon thread that loops internally:
write ufp (blocking) → sleep 2s → check flag → repeat. Cycling still present.

---

## What we still don't know

1. **Whether the ufp write is actually succeeding.** We have not seen logcat during a cycling
   episode. We don't know if "OTG role -> ufp" is appearing every 2s as expected.

2. **Which event or code path is switching back to dfp.** The cycling means SOMETHING is
   restoring the hub's VBUS. Candidates:
   - Kernel OTG auto-revert to dfp winning over our 2s loop (timing issue)
   - `onExternalPowerRestored()` being called spuriously (POWER_CONNECTED leaking through)
   - `attemptRootOtgRecovery()` being called during `otgPowerDown=true` (wrong guard)
   - A race where `otgPowerDown` is set to `true` AFTER a POWER_CONNECTED event is already
     queued on the main thread handler (the event fires, `otgPowerDown` is still false, the
     handler posts `powerRestoredRunnable`, then `otgPowerDown` goes true, then 3s later
     `onExternalPowerRestored()` fires)

3. **Whether the hub is actually de-powering.** If the hub has enough cap charge to keep running
   briefly after ufp, it might enumerate the dongle during the sleep window, triggering a
   POWER_CONNECTED from the hub acting as a charger.

4. **The exact sequence of events during cycling.** Without logcat we're guessing.

---

## Why the current approach is fundamentally fragile

VtruxApplication's power state management is not a coherent state machine — it is a collection
of interacting timers, flags, and callbacks that evolved incrementally:

- `powerLostScheduled` guards the 5s timer from resetting
- `otgPowerDown` guards POWER_CONNECTED handling and detach handling
- `otgPowerDownThread` holds the ufp loop
- `otgRestoredAtMs` guards `attemptRootOtgRecovery()` from firing too soon after restore
- `powerRestoredRunnable` / `powerLostRunnable` run on the main thread Handler
- `attemptRootOtgRecovery()` spawns yet another Thread and does its own ufp→wait→dfp cycle

There are implicit ordering dependencies between these (e.g. `otgPowerDown` must be true before
the ufp daemon thread fires, so that a simultaneous POWER_CONNECTED doesn't trigger restore).
Some of these dependencies hold by construction; others are races.

`attemptRootOtgRecovery()` is particularly problematic: it does its own ufp→dfp cycle internally,
independently of `onExternalPowerLost()`'s ufp loop. If called at the wrong moment (e.g. during
the settling period after power loss), it fights the power-down loop. Its guard
(`!otgPowerDown && sinceRestore > 10s`) may not be sufficient.

---

## What a full state machine review requires

### Step 1: Get logcat during a cycling episode

Before making any more code changes, capture actual log output. The cycling takes a few seconds
to manifest. ADB logcat filtered to tags `VtruxApp` / `CanCore` during the power-off → cycling
window will show which exact events are firing and whether the ufp writes are landing.

Specifically, look for:
- Is `OTG role -> ufp` appearing every 2s?
- Is `POWER_CONNECTED during OTG power-down -- ignored` appearing, or is POWER_CONNECTED
  getting through WITHOUT the "during OTG power-down" tag?
- Is `onExternalPowerRestored()` being called during the cycling?
- Is `Root OTG recovery` appearing during the cycling?

### Step 2: Draw the explicit state machine

There are really four states VtruxApplication needs to manage:

| State | Meaning |
|-------|---------|
| `POWERED_UP` | External power present, hub running, possibly logging |
| `DEBOUNCING_LOST` | POWER_DISCONNECTED seen, 5s timer pending, waiting to confirm |
| `POWERED_DOWN` | Confirmed power absent, ufp hold loop running, no hub |
| `DEBOUNCING_RESTORED` | POWER_CONNECTED seen during POWERED_DOWN, 3s timer pending |

Every event (POWER_CONNECTED, POWER_DISCONNECTED, timer fire, device attach/detach) should be
listed with its effect in EVERY state. Any event that has no defined effect in a given state
must explicitly be discarded (not silently ignored by flag checks scattered across the code).

### Step 3: Audit every dfp-switching path

Every place that switches to dfp (restores VBUS) must be enumerable:
- `onExternalPowerRestored()` → `attemptRootOtgRecovery()` (does ufp→wait→dfp internally)
- `doRescan()` → `attemptRootOtgRecovery()` at attempts 2 and 6
- `switchOtgRoleBlocking(toHost=true)` — currently not called anywhere directly

For each: can it be reached from `POWERED_DOWN` state? If yes, why is the guard insufficient?

### Step 4: Consider whether `attemptRootOtgRecovery()` should be part of the state machine

Currently it's an out-of-band operation called from multiple places. It does a complete
ufp→dfp cycle and has its own internal timing. This overlaps with the state machine's own
ufp hold loop. The interaction is underspecified. It may be cleaner to eliminate it entirely
and replace it with an explicit state transition: after confirming power is restored (3s
debounce), do a clean ufp (stop hub), wait, dfp (start hub), then start rescan.

---

## Next session checklist

1. Get logcat during cycling (connect ADB while power is off, watch `VtruxApp` tag)
2. Identify the exact event that triggers dfp restore during power-down
3. Rewrite VtruxApplication power state as an explicit state machine with enumerated
   transitions — not a set of interacting flags and timers
