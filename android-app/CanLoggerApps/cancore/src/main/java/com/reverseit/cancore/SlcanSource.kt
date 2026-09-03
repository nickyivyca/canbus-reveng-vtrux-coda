package com.reverseit.cancore

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.currentCoroutineContext
import java.io.IOException
import java.io.InputStream

/**
 * Drives [SlcanReader] from a byte stream: a USB CDC serial port on the car, or a TCP socket from
 * the replay bridge (`tools/slcan_bridge.py`).
 *
 * Deliberately standalone. It does not implement any shared transport interface, because none
 * exists yet and inventing one here would mean touching `CanPipelineManager`, which both `:coda`
 * and `:vtrux` depend on. Wiring this into the pipeline is a separate, reviewable step.
 *
 * No Android imports, so the whole path is exercisable in a plain JVM unit test.
 *
 * A note on read sizes: [pump] passes whatever the stream hands back straight to the reader
 * without waiting for a frame boundary, because [SlcanReader] holds partial tokens across calls.
 * That is the property the parity test pins down, and it is what makes an arbitrary USB bulk read
 * or TCP segment boundary a non-event.
 */
class SlcanSource(
    busIndex: Int = 0,
    private val readBufferBytes: Int = 4096,
    clock: () -> Long = { System.currentTimeMillis() },
    onFrame: (CanFrame) -> Unit,
) {

    private val reader = SlcanReader(busIndex, clock, onFrame)

    /** Running tallies from the underlying reader -- frames, CSV records, damage, block checks. */
    val stats: SlcanReader.Stats get() = reader.stats

    /** FNV-1a 64 over every frame delivered so far. Comparable with the parity fixtures. */
    val digest: Long get() = reader.digest

    /**
     * Feed bytes directly, for callers that own their own read loop -- the flow builder below,
     * and tests that want to control chunking.
     */
    fun feed(data: ByteArray, offset: Int = 0, length: Int = data.size - offset) =
        reader.feed(data, offset, length)

    /**
     * Read [input] until it ends, feeding everything to the reader. Blocks.
     *
     * Returns the number of bytes consumed. Closing the stream from another thread is the way to
     * stop it; the resulting [IOException] is treated as end-of-stream rather than an error,
     * because a dongle being unplugged or a socket closing is ordinary operation, not a fault.
     */
    fun pump(input: InputStream): Long {
        val buf = ByteArray(readBufferBytes)
        var total = 0L
        while (true) {
            val n = try {
                input.read(buf)
            } catch (e: IOException) {
                break
            }
            if (n < 0) break
            if (n > 0) {
                reader.feed(buf, 0, n)
                total += n
            }
        }
        return total
    }
}

/**
 * Cold flow of frames decoded from [input]. Collecting starts the read; cancelling the collection
 * stops it, though a blocked `read()` only unblocks once the caller closes the stream.
 *
 * [onStats] receives the reader after the stream ends, so a caller can report link health without
 * the source having to own a logging dependency.
 */
fun slcanFrames(
    input: InputStream,
    busIndex: Int = 0,
    readBufferBytes: Int = 4096,
    onStats: (SlcanReader.Stats) -> Unit = {},
): Flow<CanFrame> = flow {
    val pending = ArrayDeque<CanFrame>()
    val source = SlcanSource(busIndex, readBufferBytes) { pending.addLast(it) }
    val buf = ByteArray(readBufferBytes)
    while (currentCoroutineContext().isActive) {
        val n = try {
            input.read(buf)
        } catch (e: IOException) {
            break
        }
        if (n < 0) break
        if (n > 0) {
            source.feed(buf, 0, n)
            while (pending.isNotEmpty()) emit(pending.removeFirst())
        }
    }
    onStats(source.stats)
}.flowOn(Dispatchers.IO)
