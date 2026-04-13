package com.reverseit.cancore

/**
 * Vehicle-specific hook for deciding when to start a new log segment.
 * The shared size/time limits are applied by CanLoggingService independently of this policy.
 * This interface is for vehicle-specific triggers (e.g. key cycle detection).
 *
 * Return true to request that the current log segment be closed and a new one started.
 */
fun interface LogSegmentPolicy {
    fun shouldRoll(frame: CanFrame): Boolean
}

/** Never rolls on a vehicle-specific trigger; relies on shared size/time limits only. */
object NoOpSegmentPolicy : LogSegmentPolicy {
    override fun shouldRoll(frame: CanFrame) = false
}
