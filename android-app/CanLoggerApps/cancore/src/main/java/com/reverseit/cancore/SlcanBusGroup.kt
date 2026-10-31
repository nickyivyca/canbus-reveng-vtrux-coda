package com.reverseit.cancore

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

/**
 * Several SLCAN streams, one per bus, presented as one [CanFrameSource] and [CanTransmitter] --
 * the shape `CanPipelineManager` gives an app over N gs_usb dongles.
 *
 * Built for the Coda emulator harness: `tools/slcan_bridge.py --busmaster` serves each channel of
 * a real log on its own TCP port, and this stands in for the dongles so the app's real frame path
 * (logger, segment rolls, drive rows, bus resolver, transmitter) runs in an AVD, which has no USB
 * host. Nothing here is Coda-specific; the wiring that picks it is.
 *
 * Bus index = stream index. The replayed log's channel numbers are as arbitrary as dongle
 * insertion order, which is the point: the app must still identify buses by content.
 *
 * Two properties are copied from `CanPipelineManager` deliberately:
 * - **Stamp and emit under one lock.** Each stream has its own reader thread; without the lock
 *   one bus could stamp a frame and emit it after another bus emitted a later one. The log writer
 *   takes its time origin from the first frame it writes and relies on this order.
 * - **Transmitted frames come back as an `isTx = true` echo**, as gs_usb echoes them off the bulk
 *   IN endpoint. The contention guard and the log's direction column both depend on that echo, so
 *   a harness without it would test a different transmit path from the car's.
 *
 * Transmitting writes the frame as an SLCAN line ([SlcanWriter]) up that bus's stream, where the
 * bridge records it.
 *
 * **A stream counts as connected only once it has delivered data.** Over `adb reverse` a connect
 * always succeeds on the device side, whether or not anything is listening on the PC, and the
 * stream then ends at once. Counting that as a connection made a stopped bridge look like a bus
 * flapping every [retryMs]. So [activeDeviceCount], [canTransmit] and [onLinkChange] all go by
 * "live" -- connected and has delivered at least one byte.
 *
 * No Android imports, so it is JVM-testable with piped streams.
 */
class SlcanBusGroup(
    private val busCount: Int,
    /**
     * Opens the stream for a bus. Blocking; throws [IOException] when the far end is not there,
     * and the group retries after [retryMs].
     */
    private val connect: (busIndex: Int) -> Link,
    private val retryMs: Long = 2_000L,
    /** The log writer reads this flow too, so it gets the log writer's buffer (Bug 4). */
    extraBufferCapacity: Int = CanFrameSource.LOG_BUFFER_FRAMES,
    private val readBufferBytes: Int = 4096,
    private val clock: () -> Long = { System.currentTimeMillis() },
    /** Called on a reader thread whenever a stream connects or drops; for notification text. */
    private val onLinkChange: (connectedCount: Int) -> Unit = {},
) : CanFrameSource, CanTransmitter {

    /** One connected stream. [close] must unblock a read in progress on [input]. */
    class Link(val input: InputStream, val output: OutputStream, val close: () -> Unit)

    private val _frames = MutableSharedFlow<CanFrame>(extraBufferCapacity = extraBufferCapacity)
    override val frames: SharedFlow<CanFrame> = _frames.asSharedFlow()

    /** `tryEmit` results (Bug 4); see [FlowHealth]. [dropped] stays the harness's own count. */
    private val health = FlowHealth.register(frames, "harness.frames")

    private val stampLock = Any()
    private val links = arrayOfNulls<Link>(busCount)
    private val live = BooleanArray(busCount)   // guarded by links
    private val threads = arrayOfNulls<Thread>(busCount)

    @Volatile
    private var running = false

    /** Frames decoded per bus, current and previous connections together. */
    val received = Array(busCount) { AtomicLong() }

    /** Frames handed to a bus's stream by [transmit]. */
    val transmitted = Array(busCount) { AtomicLong() }

    /**
     * Frames lost because [frames] had no room. `tryEmit` never blocks, so a slow collector drops
     * frames; counted here so that is visible instead of silent. [FlowHealth] counts the same
     * failures as `harness.frames`, for logcat and the notification.
     */
    val dropped = AtomicLong()

    /** Start a reader thread per bus. Each connects, reads until the stream ends, and retries. */
    fun start() {
        check(!running) { "already started" }
        running = true
        for (bus in 0 until busCount) {
            threads[bus] = thread(isDaemon = true, name = "slcan-bus-$bus") { serve(bus) }
        }
    }

    /** Stop every reader and close every stream. */
    fun stop() {
        running = false
        for (bus in 0 until busCount) closeLink(bus)
        threads.forEach { it?.interrupt() }
    }

    /** Wait for the reader threads to finish after [stop]; for tests. */
    fun join(timeoutMs: Long) {
        val deadline = System.currentTimeMillis() + timeoutMs
        threads.forEach { it?.join((deadline - System.currentTimeMillis()).coerceAtLeast(1)) }
    }

    private fun serve(bus: Int) {
        while (running) {
            val link = try {
                connect(bus)
            } catch (e: IOException) {
                null
            }
            if (link != null) {
                synchronized(links) { links[bus] = link }
                pump(bus, link)
                val wasLive = synchronized(links) { live[bus].also { live[bus] = false } }
                closeLink(bus)
                if (wasLive) onLinkChange(connectedCount())
            }
            if (!running) break
            try {
                Thread.sleep(retryMs)
            } catch (e: InterruptedException) {
                break
            }
        }
    }

    /**
     * Read one connection to its end. A fresh [SlcanSource] per connection: a new stream may begin
     * mid-line, and a partial token carried over would splice two unrelated frames.
     */
    private fun pump(bus: Int, link: Link) {
        val source = SlcanSource(bus, readBufferBytes, clock) { received[bus].incrementAndGet(); emit(it) }
        val buf = ByteArray(readBufferBytes)
        while (running) {
            val n = try {
                link.input.read(buf)
            } catch (e: IOException) {
                break
            }
            if (n < 0) break
            if (n > 0) {
                val first = synchronized(links) { !live[bus].also { live[bus] = true } }
                if (first) onLinkChange(connectedCount())
                synchronized(stampLock) { source.feed(buf, 0, n) }
            }
        }
    }

    /** Called with [stampLock] held. */
    private fun emit(frame: CanFrame) {
        if (!health.record(_frames.tryEmit(frame))) dropped.incrementAndGet()
    }

    private fun closeLink(bus: Int) {
        val link = synchronized(links) { links[bus].also { links[bus] = null } } ?: return
        runCatching { link.close() }
    }

    private fun connectedCount() = synchronized(links) { live.count { it } }

    override fun canTransmit(busIndex: Int): Boolean =
        busIndex in 0 until busCount && synchronized(links) { links[busIndex] != null && live[busIndex] }

    /**
     * Write the frame up [busIndex]'s stream, then echo it into [frames] with `isTx = true`.
     * False if the bus has no open stream or the write fails.
     */
    override fun transmit(busIndex: Int, id: Int, data: ByteArray, isExtended: Boolean): Boolean {
        if (busIndex !in 0 until busCount) return false
        val link = synchronized(links) { links[busIndex]?.takeIf { live[busIndex] } } ?: return false
        val line = SlcanWriter.encode(id, data, isExtended)
        try {
            synchronized(link) {
                link.output.write(line)
                link.output.flush()
            }
        } catch (e: IOException) {
            return false
        }
        transmitted[busIndex].incrementAndGet()
        val payload = data.copyOf(8)
        synchronized(stampLock) {
            emit(CanFrame(busIndex, clock(), id, isExtended, data.size, payload, isTx = true))
        }
        return true
    }

    override fun activeDeviceCount(): Int = connectedCount()

    override fun activeBusCount(): Int = busCount
}
