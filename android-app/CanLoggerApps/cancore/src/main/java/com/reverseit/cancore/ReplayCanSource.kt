package com.reverseit.cancore

import android.util.Log
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.isActive
import java.io.File

/**
 * Replays a BUSMASTER log as a [Flow] of [CanFrame], paced to the timing
 * recorded in the file.
 *
 * This exists because the Android emulator has no USB host passthrough --
 * `UsbManager.deviceList` is always empty inside an AVD, so a gs_usb dongle can
 * never appear and the normal [CanPipelineManager] path produces nothing. A
 * replay source lets the display layer be exercised against real captured data
 * on an emulator, or on a device with no dongle attached.
 *
 * The flow is cold: collecting it opens the file, cancelling the collection
 * closes it. Frames are stamped with wall-clock time at emission, matching what
 * a live dongle would produce, so downstream consumers cannot tell the
 * difference.
 *
 * @param file        BUSMASTER log to replay.
 * @param loop        Restart from the top at EOF. Keeps a short demo log alive
 *                    indefinitely rather than freezing the UI on the last value.
 * @param speed       Playback rate multiplier; 2.0 replays twice as fast.
 * @param anchorIds   If non-empty, only the bus carrying the most of these IDs
 *                    is replayed. Bus/channel numbers depend on dongle insertion
 *                    order and are never stable across sessions, so the bus of
 *                    interest must be identified by its content.
 */
class ReplayCanSource(
    private val file: File,
    private val loop: Boolean = true,
    private val speed: Double = 1.0,
    private val anchorIds: Set<Int> = emptySet(),
) {
    companion object {
        private const val TAG = "CanReplay"

        /** Sleeps shorter than this are not worth a suspension point. */
        private const val MIN_SLEEP_MS = 2L

        /**
         * A gap longer than this in the source log is collapsed. Captures often
         * contain long idle stretches (key-off, charging waits); replaying them
         * verbatim would look like a hung app.
         */
        private const val MAX_GAP_MS = 2_000L
    }

    /** Bus selected by [anchorIds], or null when replaying every bus. */
    var selectedBus: Int? = null
        private set

    fun frames(): Flow<CanFrame> = flow {
        if (!file.exists()) {
            Log.w(TAG, "replay file does not exist: ${file.absolutePath}")
            return@flow
        }

        selectedBus = if (anchorIds.isEmpty()) null else {
            val buses = BusmasterReader.surveyBuses(file)
            val pick = BusmasterReader.selectBusByAnchors(buses, anchorIds)
            Log.i(TAG, "buses in ${file.name}: " +
                buses.entries.joinToString { "${it.key}(${it.value.size} ids)" } +
                " -> replaying bus ${pick ?: "ALL"}")
            pick
        }

        var pass = 0
        do {
            pass++
            emitOnePass()
            if (loop) Log.i(TAG, "replay pass $pass complete, looping")
        } while (loop && currentCoroutineContext().isActive)
    }

    private suspend fun kotlinx.coroutines.flow.FlowCollector<CanFrame>.emitOnePass() {
        val wallStart = System.currentTimeMillis()
        var firstRelMs = -1L
        // Accumulated ms removed from the timeline by collapsing idle gaps.
        var skewMs = 0L
        var previousRelMs = -1L
        var count = 0L

        file.bufferedReader().use { reader ->
            while (currentCoroutineContext().isActive) {
                val line = reader.readLine() ?: break
                val parsed = BusmasterReader.parseLine(line) ?: continue
                val bus = selectedBus
                if (bus != null && parsed.frame.busIndex != bus) continue

                if (firstRelMs < 0) firstRelMs = parsed.relativeMs
                if (previousRelMs >= 0) {
                    val gap = parsed.relativeMs - previousRelMs
                    if (gap > MAX_GAP_MS) skewMs += gap - MAX_GAP_MS
                }
                previousRelMs = parsed.relativeMs

                val logicalMs = parsed.relativeMs - firstRelMs - skewMs
                val targetMs = wallStart + (logicalMs / speed).toLong()
                val now = System.currentTimeMillis()
                val sleep = targetMs - now
                if (sleep >= MIN_SLEEP_MS) delay(sleep)

                emit(parsed.frame.copy(timestampMs = System.currentTimeMillis(), elapsedNanos = System.nanoTime()))
                count++
            }
        }
        Log.i(TAG, "replayed $count frames from ${file.name}")
    }
}
