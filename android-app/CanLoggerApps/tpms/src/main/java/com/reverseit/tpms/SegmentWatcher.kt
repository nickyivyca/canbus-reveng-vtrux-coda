package com.reverseit.tpms

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Detects that a CAN log segment has closed by watching the name of the segment being written
 * change -- to the next segment on a roll, or to null when logging stops.
 *
 * This is how the TPMS module learns about closes **without a hook in the shared logging code**:
 * `CanLoggingService.currentSegmentName` is already published (the log file server uses it), and
 * the service closes a segment's file *before* it changes that name, so a changed name means the
 * previous file is complete. Polled rather than callback-driven, at [periodMs]; a row appearing
 * up to half a second after the close costs nothing.
 *
 * A close missed while the process was not running is picked up by [DriveRowProducer.catchUp].
 */
class SegmentWatcher(
    private val current: () -> String?,
    private val onClosed: (String) -> Unit,
    private val periodMs: Long = 500L,
) {
    private var last: String? = null

    /** One observation. Reports the previous segment if the name has changed since the last call. */
    fun poll() {
        val now = current()
        val prev = last
        last = now
        if (prev != null && prev != now) onClosed(prev)
    }

    fun start(scope: CoroutineScope): Job = scope.launch {
        while (isActive) {
            try {
                poll()
            } catch (e: Exception) {
                TpmsLog.e("TpmsWatch", "segment close handling failed", e)
            }
            delay(periodMs)
        }
    }
}
