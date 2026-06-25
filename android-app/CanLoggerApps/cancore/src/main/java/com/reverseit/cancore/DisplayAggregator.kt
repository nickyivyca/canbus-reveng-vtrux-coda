package com.reverseit.cancore

import com.reverseit.cancore.SubscriptionManifest.Aggregation

/**
 * Tier 1 aggregation primitives from CAN Display Protocol v1 §7.
 *
 * Tumbling-window: at each emit boundary, the running state is flushed
 * and reset. `decimate` is the exception -- it counts incoming frames
 * regardless of time and emits every Nth one.
 *
 * Identical math to `tools/can_display_server.py` (`_agg_*`), kept in sync
 * so the local data source produces the same numbers as the WebSocket
 * server for the same input stream.
 */
class SignalAggregator(val mode: Aggregation, val decimateN: Int = 1) {

    private var sum: Double = 0.0
    private var count: Int = 0
    private var value: Double? = null
    private var seenInCycle: Int = 0

    fun update(v: Double) {
        when (mode) {
            Aggregation.MEAN -> { sum += v; count += 1 }
            Aggregation.MIN -> value = value?.let { kotlin.math.min(it, v) } ?: v
            Aggregation.MAX -> value = value?.let { kotlin.math.max(it, v) } ?: v
            Aggregation.LATEST -> value = v
            Aggregation.DECIMATE -> { value = v; seenInCycle += 1 }
        }
    }

    /** True when DECIMATE mode is due to emit this cycle. */
    fun decimateDue(): Boolean = mode == Aggregation.DECIMATE && seenInCycle >= decimateN

    /** Returns the current emit value, or null if nothing has been seen
     *  in this window (e.g. an empty mean). Resets the running state. */
    fun flush(): Double? {
        val out: Double? = when (mode) {
            Aggregation.MEAN -> if (count > 0) sum / count else null
            Aggregation.MIN, Aggregation.MAX, Aggregation.LATEST,
            Aggregation.DECIMATE -> value
        }
        sum = 0.0
        count = 0
        value = null
        seenInCycle = 0
        return out
    }
}
