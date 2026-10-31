package com.reverseit.cancore

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import java.io.InputStream

/**
 * A [CanFrameSource] fed by an SLCAN byte stream -- the 914 VCU over USB CDC serial, or the
 * replay bridge over TCP. Hands [CanLoggingService] the same shape `CanPipelineManager` does, so
 * the logging path works unchanged for a vehicle with no gs_usb dongle.
 *
 * One stream, one bus. The 914's single serial port carries both real 11-bit vehicle traffic and
 * synthetic 29-bit VCU telemetry, but that distinction is already carried losslessly by
 * `isExtended` on every frame and by the DBC's extended marker -- it is a presentation concern,
 * not a transport one, so it is not modelled as two buses here.
 *
 * No Android imports, so this is exercisable in a plain JVM test.
 */
class SlcanFrameSource(
    private val busIndex: Int = 0,
    private val readBufferBytes: Int = 4096,
    /** The log writer reads this flow too, so it gets the log writer's buffer (Bug 4). */
    extraBufferCapacity: Int = CanFrameSource.LOG_BUFFER_FRAMES,
    private val clock: () -> Long = { System.currentTimeMillis() },
) : CanFrameSource {

    private val _frames = MutableSharedFlow<CanFrame>(extraBufferCapacity = extraBufferCapacity)
    override val frames: SharedFlow<CanFrame> = _frames.asSharedFlow()

    /** `tryEmit` results, always counted (Bug 4); see [FlowHealth]. */
    private val health = FlowHealth.register(frames, "slcan.frames")

    @Volatile
    private var streaming = false

    private var source = newSource()

    /** Link health from the underlying reader: frames, damage, and integrity block results. */
    @Volatile
    var stats: SlcanReader.Stats = source.stats
        private set

    /**
     * FNV-1a 64 over every frame delivered by the current stream. Comparable directly against the
     * parity fixtures, which is what makes an on-device run checkable against the JVM run rather
     * than merely plausible.
     */
    val digest: Long get() = source.digest

    override fun activeDeviceCount(): Int = if (streaming) 1 else 0

    override fun activeBusCount(): Int = 1

    private fun newSource() = SlcanSource(busIndex, readBufferBytes, clock) { health.record(_frames.tryEmit(it)) }

    /**
     * Read [input] until it ends, publishing frames as they decode. Blocks, so call it on an IO
     * dispatcher or a dedicated thread.
     *
     * Each call starts a fresh reader: a reconnected stream may begin mid-frame, and carrying the
     * previous partial token across would splice two unrelated frames together. Returns the byte
     * count consumed.
     */
    fun pump(input: InputStream): Long {
        source = newSource()
        stats = source.stats
        streaming = true
        try {
            return source.pump(input)
        } finally {
            streaming = false
        }
    }
}
