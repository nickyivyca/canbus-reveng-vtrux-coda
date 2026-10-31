package com.reverseit.display

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue

/**
 * Holds the fault the pack *entered*, rather than the state it is in now.
 *
 * Why this exists rather than just re-classifying every frame: the signals
 * that identify a fault keep moving after the trip. Measured on the
 * 2026-06-18 00:21 drive-mode trip, the pack asserted EPO with the interlock
 * loop still closed and pushed `AC 10 01` + `F0 00 00` 321 ms later -- but the
 * interlock then opened 19.8 s afterwards. A display that re-classified live
 * would have said "Battery fault", then silently relabelled itself "Interlock
 * opened" twenty seconds in. That is exactly the misreading this is meant to
 * prevent: the event was diagnosed as an interlock fault for months on the
 * strength of the later interlock drop, when the pack's own record said
 * otherwise at the instant it tripped.
 *
 * So: **headline, detail and codes are captured once**, at the transition into
 * the fault state, and held. Evidence rows keep updating, because a change in
 * them after the trip is information -- it just is not a new diagnosis.
 */
enum class LatchPhase { ACTIVE, CLEARED }

data class LatchedFault(
    /** Captured at the instant the fault gate first passed. Never re-evaluated. */
    val verdict: FaultVerdict,
    /** Recomputed every frame -- what the truck looks like right now. */
    val liveEvidence: List<Pair<String, String>>,
    val phase: LatchPhase,
    val startedAtMs: Long,
    val clearedAtMs: Long?,
    val nowMs: Long,
) {
    /** e.g. "started 47s ago" / "lasted 47s, cleared 2m ago". */
    fun timingLine(): String = when (phase) {
        LatchPhase.ACTIVE -> "started ${short(nowMs - startedAtMs)} ago"
        LatchPhase.CLEARED -> {
            val lasted = short((clearedAtMs ?: nowMs) - startedAtMs)
            val since = short(nowMs - (clearedAtMs ?: nowMs))
            "lasted $lasted, cleared $since ago"
        }
    }

    private fun short(ms: Long): String {
        val s = ms / 1000
        return when {
            s < 60 -> "${s}s"
            s < 3600 -> "${s / 60}m ${s % 60}s"
            else -> "${s / 3600}h ${(s % 3600) / 60}m"
        }
    }
}

/**
 * Stateful wrapper over [classify]. Feed it every signal snapshot; it decides
 * when a fault begins and ends and keeps the captured verdict in between.
 */
class FaultLatchState {
    private var captured: FaultVerdict? = null
    private var startedAtMs: Long = 0
    private var clearedAtMs: Long? = null

    fun update(signals: Map<String, Double>, nowMs: Long): LatchedFault? {
        val evidence = faultEvidenceFrom(signals)
        val verdict = classify(evidence)
        val active = verdict.severity != FaultSeverity.NONE

        // A warning must be allowed to become a fault. Alarm level 1 runs
        // ahead of a charge trip by ~10 s, so a latch that captured the
        // warning and refused to look again would sit on "Battery warning"
        // through the trip it was warning about.
        val escalating = captured?.severity == FaultSeverity.WARNING &&
            verdict.severity == FaultSeverity.FAULT

        if (active) {
            if (captured == null || clearedAtMs != null || escalating) {
                // Entering from healthy, from a previously cleared event, or
                // stepping up a tier. A second trip is a new event, not a
                // resumption, and the escalation restarts the clock so the
                // elapsed line times the fault rather than the warning.
                captured = verdict
                startedAtMs = nowMs
                clearedAtMs = null
            }
        } else if (captured != null && clearedAtMs == null && !evidence.epo) {
            // Only declare it over once EPO has dropped. While EPO is up the
            // pack is mid-transition and the classifier can legitimately come
            // back empty for a few hundred milliseconds -- between the EPO edge
            // and the records landing (measured 220-470 ms), or across a 0x460
            // page cycle. Without this, a warning escalating into a fault
            // flashes grey "CLEARED" on its way to red.
            clearedAtMs = nowMs
        }

        val held = captured ?: return null
        return LatchedFault(
            verdict = held,
            // Evidence rows come from a live classify() pass so they track the
            // truck; when the gate has closed, classify() returns no rows, so
            // fall back to the captured set rather than showing an empty card.
            liveEvidence = verdict.evidence.ifEmpty { held.evidence },
            phase = if (clearedAtMs == null) LatchPhase.ACTIVE else LatchPhase.CLEARED,
            startedAtMs = startedAtMs,
            clearedAtMs = clearedAtMs,
            nowMs = nowMs,
        )
    }
}

/**
 * Composable entry point. [nowMs] is passed in rather than read from the clock
 * so the caller controls the recomposition cadence and tests stay deterministic.
 */
@Composable
fun rememberLatchedFault(
    signals: Map<String, Double>,
    nowMs: Long = System.currentTimeMillis(),
): LatchedFault? {
    val state = remember { FaultLatchState() }
    var latest by remember { mutableStateOf<LatchedFault?>(null) }
    latest = state.update(signals, nowMs)
    return latest
}
