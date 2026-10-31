package com.reverseit.cancore

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.onSubscription
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.PipedInputStream
import java.io.PipedOutputStream
import java.util.Collections
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

/**
 * [SlcanBusGroup]: the harness's stand-in for N gs_usb dongles. Each test plays the bridge's part
 * with piped streams -- one pair per bus per connection.
 */
class SlcanBusGroupTest {

    /** The bridge's end of one connection: what it writes to the app, and what the app wrote back. */
    private class FakePort {
        val toApp = PipedOutputStream()
        private val appIn = PipedInputStream(toApp, 1 shl 20)
        val fromApp = ByteArrayOutputStream()   // synchronized internally
        val link = SlcanBusGroup.Link(appIn, fromApp) { appIn.close(); toApp.close() }
        fun send(text: String) { toApp.write(text.toByteArray(Charsets.US_ASCII)); toApp.flush() }
        fun received() = String(fromApp.toByteArray(), Charsets.US_ASCII)
    }

    /** Per bus, the connections the "bridge" will accept, in order. Empty -> connection refused. */
    private val pending = Array(2) { LinkedBlockingQueue<FakePort>() }
    private val frames: MutableList<CanFrame> = Collections.synchronizedList(ArrayList())
    private val scope = CoroutineScope(Dispatchers.Default)
    private var group: SlcanBusGroup? = null

    private fun start(clock: () -> Long = { System.currentTimeMillis() }, buffer: Int = 1024,
                      onLink: (Int) -> Unit = {}): SlcanBusGroup {
        val g = SlcanBusGroup(
            busCount = 2,
            connect = { bus -> pending[bus].poll()?.link ?: throw IOException("refused") },
            retryMs = 20,
            extraBufferCapacity = buffer,
            clock = clock,
            onLinkChange = onLink,
        )
        val subscribed = CompletableDeferred<Unit>()
        scope.launch { g.frames.onSubscription { subscribed.complete(Unit) }.collect { frames.add(it) } }
        runBlocking { withTimeout(5_000) { subscribed.await() } }
        group = g
        g.start()
        return g
    }

    @After
    fun tearDown() {
        group?.stop()
        group?.join(2_000)
        scope.cancel()
    }

    private fun waitFor(timeoutMs: Long = 5_000, what: String, cond: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (!cond()) {
            if (System.currentTimeMillis() > deadline) throw AssertionError("timed out waiting for $what")
            Thread.sleep(5)
        }
    }

    @Test
    fun framesCarryTheirStreamIndexAsBus() {
        val p0 = FakePort().also { pending[0].add(it) }
        val p1 = FakePort().also { pending[1].add(it) }
        val g = start()
        waitFor(what = "both streams opened") { pending[0].isEmpty() && pending[1].isEmpty() }
        assertEquals("connected before any data", 0, g.activeDeviceCount())
        p0.send("t1008AABBCCDD00112233\r")
        p1.send("t2002BEEF\r")
        waitFor(what = "two frames") { frames.size == 2 }
        assertEquals(2, g.activeDeviceCount())
        val byId = frames.associateBy { it.id }
        assertEquals(0, byId.getValue(0x100).busIndex)
        assertEquals(1, byId.getValue(0x200).busIndex)
        assertEquals(2, byId.getValue(0x200).dlc)
        assertFalse(byId.getValue(0x100).isTx)
        assertEquals(2, g.activeBusCount())
        assertEquals(1L, g.received[0].get())
    }

    /**
     * The log writer needs frames to leave [SlcanBusGroup.frames] in timestamp order. Two buses
     * streaming at once, a clock that ticks on every call: any frame stamped on one thread and
     * emitted after the other thread's later stamp shows up as a decrease.
     */
    @Test
    fun emissionOrderIsStampOrderAcrossBuses() {
        val p0 = FakePort().also { pending[0].add(it) }
        val p1 = FakePort().also { pending[1].add(it) }
        val tick = AtomicLong()
        val g = start(clock = { tick.incrementAndGet() }, buffer = 100_000)
        waitFor(what = "both streams opened") { pending[0].isEmpty() && pending[1].isEmpty() }
        val n = 5_000
        val writers = listOf(p0, p1).mapIndexed { bus, p ->
            thread {
                val sb = StringBuilder()
                for (i in 0 until n) {
                    sb.append("t%03X2%04X\r".format(0x100 + bus, i))
                    if (i % 50 == 49) { p.send(sb.toString()); sb.setLength(0) }
                }
                p.send(sb.toString())
            }
        }
        writers.forEach { it.join() }
        waitFor(what = "all frames") { frames.size == 2 * n }
        val snapshot = synchronized(frames) { frames.toList() }
        for (i in 1 until snapshot.size) {
            assertTrue("frame $i stamped before frame ${i - 1}",
                snapshot[i].timestampMs > snapshot[i - 1].timestampMs)
            assertTrue(snapshot[i].elapsedNanos >= snapshot[i - 1].elapsedNanos)
        }
        assertEquals(0L, g.dropped.get())
    }

    @Test
    fun transmitWritesTheLineUpItsOwnBusAndEchoes() {
        val p0 = FakePort().also { pending[0].add(it) }
        val p1 = FakePort().also { pending[1].add(it) }
        val g = start()
        waitFor(what = "both streams opened") { pending[0].isEmpty() && pending[1].isEmpty() }
        assertFalse("transmit path before the stream has delivered anything", g.canTransmit(1))
        p0.send("t1001AA\r")
        p1.send("t2001BB\r")
        waitFor(what = "both live and their frames delivered") { g.activeDeviceCount() == 2 && frames.size == 2 }
        frames.clear()
        val payload = byteArrayOf(0x13, 1, 1, 7, 0, 0x2A, 0x10, 0x4A)
        assertTrue(g.canTransmit(1))
        assertTrue(g.transmit(1, 0x600, payload))
        assertEquals("t600813010107002A104A\r", p1.received())
        assertEquals("", p0.received())
        waitFor(what = "echo") { frames.any { it.isTx } }
        assertEquals(1, frames.size)
        val echo = frames[0]
        assertTrue(echo.isTx)
        assertEquals(1, echo.busIndex)
        assertEquals(0x600, echo.id)
        assertEquals(8, echo.dlc)
        assertEquals(1L, g.transmitted[1].get())
        assertFalse(g.transmit(2, 0x600, payload))
    }

    @Test
    fun streamEndDropsTheLinkAndItReconnects() {
        val first = FakePort().also { pending[0].add(it) }
        val links = Collections.synchronizedList(ArrayList<Int>())
        val g = start(onLink = { links.add(it) })
        first.send("t1001AA\r")
        waitFor(what = "bus 0 connected") { g.canTransmit(0) }
        assertFalse(g.canTransmit(1))
        assertEquals(1, g.activeDeviceCount())
        first.toApp.close()
        waitFor(what = "bus 0 dropped") { !g.canTransmit(0) }
        assertFalse(g.transmit(0, 0x600, ByteArray(8)))

        val second = FakePort().also { pending[0].add(it) }
        second.send("t3001FF\r")
        waitFor(what = "frame after reconnect") { frames.any { it.id == 0x300 } }
        assertTrue(g.canTransmit(0))
        assertEquals(listOf(1, 0, 1), links.toList())
    }

    /**
     * What `adb reverse` does with no bridge behind it: every connect succeeds and the stream ends
     * at once. That must not read as a bus coming and going.
     */
    @Test
    fun streamsThatEndWithoutDataAreNotConnections() {
        val links = Collections.synchronizedList(ArrayList<Int>())
        repeat(5) { pending[0].add(FakePort().also { it.toApp.close() }) }
        val g = start(onLink = { links.add(it) })
        waitFor(what = "empty streams consumed") { pending[0].isEmpty() }
        Thread.sleep(100)
        assertEquals(emptyList<Int>(), links.toList())
        assertEquals(0, g.activeDeviceCount())
        assertFalse(g.canTransmit(0))
    }

    /**
     * The reason the echo exists: the contention guard must not mistake our own frame for another
     * node's. Driven through [PeriodicTransmitter] exactly as the app wires it.
     */
    @Test
    fun ownEchoDoesNotTripTheContentionGuard() {
        val port = FakePort().also { pending[0].add(it) }
        val g = start()
        port.send("t1001AA\r")
        waitFor(what = "bus 0 connected") { g.canTransmit(0) }
        val tx = PeriodicTransmitter(g, allowedIds = setOf(0x600))
        scope.launch { g.frames.collect { tx.observe(it) } }
        tx.register("lamp", 0x600, 525, busIndex = { 0 }, payload = { ByteArray(8) })
        tx.enabled = true
        assertEquals(1, tx.tick(1_000))
        waitFor(what = "echo") { frames.any { it.isTx } }
        Thread.sleep(50)   // let the observer see the echo too
        assertEquals(1, tx.tick(1_525))
        assertEquals(PeriodicTransmitter.SlotState.ACTIVE, tx.states()["lamp"])
    }
}
