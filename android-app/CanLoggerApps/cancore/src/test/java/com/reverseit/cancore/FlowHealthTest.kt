package com.reverseit.cancore

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.onSubscription
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.ByteArrayInputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Bug 4: a stalled collector makes `tryEmit` fail, [FlowHealth] counts every failure in every
 * build, and the log writer's flows hold [CanFrameSource.LOG_BUFFER_FRAMES] frames before any is
 * lost. With measurements on (debug builds), the collector's backlog high-water mark reaches the
 * buffer.
 */
class FlowHealthTest {

    @Before
    fun reset() {
        FlowHealth.resetForTest()
    }

    @After
    fun off() {
        FlowHealth.resetForTest()
    }

    private fun frame(i: Int) = CanFrame(0, 0L, 0x123, false, 8, ByteArray(8) { i.toByte() })

    /** A collector that took one frame and is stalled until [release] counts down. */
    private class Stalled(val job: Job, val got: AtomicInteger, val release: CountDownLatch)

    /**
     * Start a collector on [flow], wait until [subscribed] returns, send its first frame with
     * [emitFirst], and return once that frame has arrived and the collector has stalled on it.
     */
    private suspend fun CoroutineScope.stall(
        flow: Flow<CanFrame>,
        subscribed: suspend () -> Unit,
        emitFirst: () -> Unit,
    ): Stalled {
        val firstSeen = CountDownLatch(1)
        val release = CountDownLatch(1)
        val got = AtomicInteger()
        val job = launch(Dispatchers.IO) {
            flow.collect {
                if (got.incrementAndGet() == 1) {
                    firstSeen.countDown()
                    release.await()
                }
            }
        }
        withTimeout(5_000) { subscribed() }
        emitFirst()
        assertTrue(firstSeen.await(5, TimeUnit.SECONDS))
        return Stalled(job, got, release)
    }

    @Test
    fun `a stalled collector's drops are all counted and the rest all arrive`() = runBlocking {
        FlowHealth.enabled = true
        val buffer = 16
        val mutable = MutableSharedFlow<CanFrame>(extraBufferCapacity = buffer)
        val shared = mutable.asSharedFlow()
        val health = FlowHealth.register(shared, "test.frames")
        // Frame 0 reaches the collector, which then stalls; 16 more fit the buffer, the rest fail.
        val s = stall(shared.watched("test-collector"), { mutable.subscriptionCount.first { it == 1 } }) {
            health.record(mutable.tryEmit(frame(0)))
        }
        val n = 200
        repeat(n) { health.record(mutable.tryEmit(frame(it + 1))) }
        s.release.countDown()
        withTimeout(5_000) { while (s.got.get() < 1 + buffer) delay(5) }
        delay(50)
        s.job.cancel()

        assertEquals((n - buffer).toLong(), health.failed.get())
        assertEquals((1 + buffer).toLong(), health.emitted.get())
        assertEquals(1 + buffer, s.got.get())
        assertEquals((buffer - 1).toLong(), FlowHealth.collectorNamed("test-collector")!!.backlogMaxAll)
    }

    @Test
    fun `with measurements off (release builds) every failed tryEmit is still counted`() = runBlocking {
        val buffer = 16
        val mutable = MutableSharedFlow<CanFrame>(extraBufferCapacity = buffer)
        val shared = mutable.asSharedFlow()
        val health = FlowHealth.register(shared, "test.frames")
        val watched = shared.watched("test-collector")
        assertSame(shared, watched)
        assertNull(FlowHealth.collectorNamed("test-collector"))

        val s = stall(watched, { mutable.subscriptionCount.first { it == 1 } }) {
            health.record(mutable.tryEmit(frame(0)))
        }
        repeat(100) { health.record(mutable.tryEmit(frame(it + 1))) }
        s.release.countDown()
        s.job.cancel()

        assertEquals(84L, health.failed.get())
        assertEquals("drops test.frames=84", FlowHealth.summary())
    }

    @Test
    fun `summary reads drops 0 until something is lost, then names each non-zero count`() {
        val health = FlowHealth.register(MutableSharedFlow<CanFrame>().asSharedFlow(), "pipe.log")
        FlowHealth.register(MutableSharedFlow<CanFrame>().asSharedFlow(), "pipe.frames").record(true)
        health.record(true)
        assertEquals("drops 0", FlowHealth.summary())

        FlowHealth.count("gs_usb.overflowFlag")
        assertEquals("drops gs_usb.overflowFlag=1", FlowHealth.summary())

        health.record(false)
        health.record(false)
        assertEquals("drops gs_usb.overflowFlag=1 pipe.log=2", FlowHealth.summary())
    }

    @Test
    fun `gs_usb logFrames holds LOG_BUFFER_FRAMES for a stalled log writer`() = runBlocking {
        val p = CanPipelineManager()
        try {
            val subscribed = CountDownLatch(1)
            val flow = p.logFrames.onSubscription { subscribed.countDown() }
            val s = stall(flow, { subscribed.await() }) { p.emit(frame(0)) }
            val extra = 100
            repeat(CanFrameSource.LOG_BUFFER_FRAMES + extra) { p.emit(frame(it + 1)) }
            s.release.countDown()
            s.job.cancel()
            assertEquals("drops pipe.log=$extra", FlowHealth.summary())
        } finally {
            p.shutdown()
        }
    }

    @Test
    fun `SLCAN source holds LOG_BUFFER_FRAMES for a stalled log writer`() = runBlocking {
        val src = SlcanFrameSource(clock = { 0L })
        val subscribed = CountDownLatch(1)
        val flow = src.frames.onSubscription { subscribed.countDown() }
        val n = CanFrameSource.LOG_BUFFER_FRAMES + 1 + 100
        val stream = "t1238AABBCCDD00112233\r".repeat(n).toByteArray()
        // The pump's first frame is the one the collector stalls on; the rest go into the buffer.
        var pumped: Thread? = null
        val s = stall(flow, { subscribed.await() }) {
            pumped = Thread { src.pump(ByteArrayInputStream(stream)) }.also { it.start() }
        }
        pumped!!.join(10_000)
        s.release.countDown()
        s.job.cancel()
        assertEquals(n.toLong(), src.stats.frames)
        assertEquals("drops slcan.frames=100", FlowHealth.summary())
    }
}
