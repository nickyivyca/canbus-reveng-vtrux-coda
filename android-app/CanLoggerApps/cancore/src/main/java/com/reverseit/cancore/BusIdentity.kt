package com.reverseit.cancore

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Logical bus name + the CAN message IDs that uniquely identify it.
 *
 * Physical CAN bus indices (the `busIndex` carried on every [CanFrame])
 * are arbitrary: which dongle gets bus 0 vs bus 1 depends on insertion
 * order. To keep subscriptions vehicle-agnostic, the protocol talks in
 * named buses (`"vehicle"`, `"obd"`, `"powertrain"`); the resolver maps
 * physical index to name by watching which anchor IDs show up where.
 */
data class BusIdentity(
    val name: String,
    /** Single IDs only -- ranges should be pre-expanded by the caller. */
    val anchorIds: Set<Int>,
)

/**
 * Watches incoming frames and decides which physical bus index maps to
 * which named bus.
 *
 * Call [observe] for every incoming frame. After [decisionWindowMs] from
 * the first frame, [assignments] holds the resolution. Decisions latch:
 * once a name is assigned to a bus index, it stays assigned for the life
 * of this resolver.
 *
 * Threshold rule: a bus is assigned the [BusIdentity] with the highest
 * anchor-ID count >= `min(3, anchorIds.size)` matches, provided that
 * name has not already been claimed by another bus. Same rule as the
 * Python test server's `identify_buses` (`tools/can_display_server.py`).
 */
class BusIdentityResolver(
    private val identities: List<BusIdentity>,
    private val decisionWindowMs: Long = 2_000,
    private val absoluteThreshold: Int = 3,
) {
    private val anchorIndex: Map<Int, Set<String>> = buildMap {
        for (id in identities) {
            for (anchor in id.anchorIds) {
                put(anchor, (get(anchor) ?: emptySet()) + id.name)
            }
        }
    }

    // busIndex -> identityName -> count
    private val counts: MutableMap<Int, MutableMap<String, Int>> = HashMap()
    private var firstFrameWallMs: Long = -1L

    private val _assignments = MutableStateFlow<Map<String, Int>>(emptyMap())
    /** Current bus_name -> busIndex assignments. */
    val assignments: StateFlow<Map<String, Int>> = _assignments.asStateFlow()

    private val _reasons = MutableStateFlow<Map<String, String>>(emptyMap())
    val reasons: StateFlow<Map<String, String>> = _reasons.asStateFlow()

    /**
     * Returns the named bus this frame belongs to, or null if the bus is
     * not yet identified. Also drives the resolver's internal decision
     * (after `decisionWindowMs`, latching the current best guess).
     */
    fun observe(frame: CanFrame): String? {
        val anchorOwners = anchorIndex[frame.id]
        if (anchorOwners != null) {
            val perBus = counts.getOrPut(frame.busIndex) { HashMap() }
            for (name in anchorOwners) {
                perBus[name] = (perBus[name] ?: 0) + 1
            }
        }
        if (firstFrameWallMs < 0) firstFrameWallMs = frame.timestampMs
        // Re-evaluate on every frame past the initial window while any bus
        // name is still unclaimed. PT-bus anchors on Vtrux are mostly 1-2 Hz
        // VCM rebroadcasts; a fixed 2s window can miss them on cold start
        // even though the channel is healthy. Already-assigned names latch
        // and are not reconsidered (see decide()).
        if (frame.timestampMs - firstFrameWallMs >= decisionWindowMs &&
            _assignments.value.size < identities.size
        ) {
            decide()
        }
        return _assignments.value.entries.firstOrNull { it.value == frame.busIndex }?.key
    }

    /**
     * Drops the assignment for [busName] so a fresh `busIndex` (e.g. a
     * re-enumerated USB dongle after a truck power cycle) can claim it on
     * subsequent frames. Counts on the now-stale `busIndex` are left as-is:
     * they're keyed by an int that won't receive any more frames, so they
     * decay naturally and don't interfere with the new claim.
     */
    fun forget(busName: String) {
        val current = _assignments.value
        if (busName !in current) return
        _assignments.value = current - busName
        _reasons.value = _reasons.value - busName
    }

    private fun decide() {
        val assignments = HashMap(_assignments.value)
        val reasons = HashMap(_reasons.value)
        // Buses already claimed by latched names are off-limits to new claims.
        val claimedBuses = HashSet(assignments.values)
        for (id in identities) {
            if (id.name in assignments) continue
            val threshold = minOf(absoluteThreshold, id.anchorIds.size)
            // Candidates: (count, busIndex) pairs above threshold and unclaimed.
            val candidates = counts.mapNotNull { (busIndex, perBus) ->
                val c = perBus[id.name] ?: 0
                if (c >= threshold && busIndex !in claimedBuses) c to busIndex else null
            }.sortedByDescending { it.first }
            if (candidates.isNotEmpty()) {
                val (count, busIndex) = candidates[0]
                assignments[id.name] = busIndex
                claimedBuses += busIndex
                reasons[id.name] =
                    "matched $count/${id.anchorIds.size} anchors on bus $busIndex"
            } else {
                reasons[id.name] = "no channel matched >= $threshold anchors"
            }
        }
        _assignments.value = assignments
        _reasons.value = reasons
    }
}
