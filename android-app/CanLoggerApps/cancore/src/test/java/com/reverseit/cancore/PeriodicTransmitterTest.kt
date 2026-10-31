package com.reverseit.cancore

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Tests for the interlocks in [PeriodicTransmitter]. These matter more than most unit tests in this
 * project: every one of them is the difference between a frame reaching a vehicle bus and not, and
 * the hardware path they guard cannot be exercised off the car.
 */
class PeriodicTransmitterTest {

    private companion object {
        const val ALLOWED = 0x600
        const val FORBIDDEN = 0x200
        const val PERIOD = 525L
    }

    /** Records what was asked of it; reports a transmit path on bus 0 only. */
    private class FakeTransmitter(
        var busWithPath: Int? = 0,
        var acceptSends: Boolean = true,
    ) : CanTransmitter {
        val sent = mutableListOf<Triple<Int, Int, ByteArray>>()
        override fun canTransmit(busIndex: Int) = busIndex == busWithPath
        override fun transmit(busIndex: Int, id: Int, data: ByteArray, isExtended: Boolean): Boolean {
            if (!acceptSends) return false
            sent += Triple(busIndex, id, data)
            return true
        }
    }

    private fun rx(id: Int, atMs: Long, isTx: Boolean = false, busIndex: Int = 0) = CanFrame(
        busIndex = busIndex, timestampMs = atMs, id = id, isExtended = false,
        dlc = 8, data = ByteArray(8), isTx = isTx,
    )

    private fun newTx(t: CanTransmitter) = PeriodicTransmitter(t, allowedIds = setOf(ALLOWED))

    private fun PeriodicTransmitter.registerHold(
        bus: () -> Int? = { 0 },
        payload: () -> ByteArray? = { ByteArray(8) },
    ) = register("hold", ALLOWED, PERIOD, bus, payload)

    // --- gate ---------------------------------------------------------------

    @Test
    fun `does not transmit until enabled`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake)
        tx.registerHold()

        tx.tick(1_000)
        assertEquals(0, fake.sent.size)
        assertEquals(PeriodicTransmitter.SlotState.GATED, tx.states()["hold"])

        tx.enabled = true
        tx.tick(1_000)
        assertEquals(1, fake.sent.size)
        assertEquals(PeriodicTransmitter.SlotState.ACTIVE, tx.states()["hold"])
    }

    @Test
    fun `disabling stops transmission without losing the slot`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()
        tx.tick(0)
        assertEquals(1, fake.sent.size)

        tx.enabled = false
        tx.tick(PERIOD)
        tx.tick(2 * PERIOD)
        assertEquals(1, fake.sent.size)

        tx.enabled = true
        tx.tick(3 * PERIOD)
        assertEquals(2, fake.sent.size)
    }

    // --- allowlist ----------------------------------------------------------

    @Test(expected = IllegalArgumentException::class)
    fun `rejects an ID outside the allowlist at registration`() {
        newTx(FakeTransmitter()).register("bad", FORBIDDEN, PERIOD, { 0 }, { ByteArray(8) })
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects a period below the rate floor`() {
        newTx(FakeTransmitter()).register(
            "fast", ALLOWED, PeriodicTransmitter.MIN_PERIOD_MS - 1, { 0 }, { ByteArray(8) },
        )
    }

    // --- bus resolution -----------------------------------------------------

    @Test
    fun `waits for the bus resolver instead of guessing an index`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        var resolved: Int? = null
        tx.registerHold(bus = { resolved })

        tx.tick(0)
        assertEquals(0, fake.sent.size)
        assertEquals(PeriodicTransmitter.SlotState.BUS_UNRESOLVED, tx.states()["hold"])

        resolved = 0
        tx.tick(PERIOD)
        assertEquals(1, fake.sent.size)
        assertEquals(0, fake.sent[0].first)
    }

    @Test
    fun `does not transmit on a bus with no transmit path`() {
        val fake = FakeTransmitter(busWithPath = 1)
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold(bus = { 0 })

        tx.tick(0)
        assertEquals(0, fake.sent.size)
        assertEquals(PeriodicTransmitter.SlotState.NO_TRANSMIT_PATH, tx.states()["hold"])
    }

    // --- contention guard ---------------------------------------------------

    @Test
    fun `suppresses a slot while another node is sending the same ID`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()

        tx.observe(rx(ALLOWED, atMs = 1_000))
        tx.tick(1_100)
        assertEquals(0, fake.sent.size)
        assertEquals(PeriodicTransmitter.SlotState.CONTENDED, tx.states()["hold"])

        // ...and resumes once the other node has been quiet for the whole window.
        val clear = 1_000 + PeriodicTransmitter.DEFAULT_CONTENTION_WINDOW_MS
        assertFalse(tx.isContended(0, ALLOWED, clear))
        tx.tick(clear)
        assertEquals(1, fake.sent.size)
    }

    @Test
    fun `contention is per bus, so a gateway rebroadcast does not suppress the source bus`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold(bus = { 0 })

        tx.tick(0)
        assertEquals(1, fake.sent.size)

        // The Coda's GWM copies 0x600 between buses. A frame we injected on bus 0 reappears on
        // bus 1 off the wire, so it carries isTx = false and is indistinguishable from a foreign
        // transmitter. Keyed on ID alone it would suppress our own slot; keyed on (bus, id) it
        // only marks bus 1 as occupied.
        tx.observe(rx(ALLOWED, atMs = 10, busIndex = 1))
        assertTrue(tx.isContended(1, ALLOWED, 100))
        assertFalse(tx.isContended(0, ALLOWED, 100))

        tx.tick(PERIOD)
        assertEquals(2, fake.sent.size)
        assertEquals(PeriodicTransmitter.SlotState.ACTIVE, tx.states()["hold"])
    }

    @Test
    fun `our own echo does not trigger the contention guard`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()

        tx.tick(0)
        assertEquals(1, fake.sent.size)

        // gs_usb echoes the transmitted frame back on the IN endpoint. Counting it as a foreign
        // transmitter would wedge the slot CONTENDED one period after it started.
        tx.observe(rx(ALLOWED, atMs = 5, isTx = true))
        tx.tick(PERIOD)
        assertEquals(2, fake.sent.size)
        assertEquals(PeriodicTransmitter.SlotState.ACTIVE, tx.states()["hold"])
    }

    @Test
    fun `ignores foreign traffic on IDs it never sends`() {
        val tx = newTx(FakeTransmitter())
        tx.observe(rx(FORBIDDEN, atMs = 1_000))
        assertFalse(tx.isContended(0, FORBIDDEN, 1_100))
    }

    // --- payload / idle -----------------------------------------------------

    @Test
    fun `a null payload skips the tick but keeps the schedule`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        var asserting = false
        tx.registerHold(payload = { if (asserting) ByteArray(8) else null })

        tx.tick(0)
        assertEquals(0, fake.sent.size)
        assertEquals(PeriodicTransmitter.SlotState.IDLE, tx.states()["hold"])

        asserting = true
        tx.tick(PERIOD)
        assertEquals(1, fake.sent.size)
    }

    // --- scheduling ---------------------------------------------------------

    @Test
    fun `transmits once per period, not once per tick`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()

        // Poll every 50 ms across 10 periods; expect exactly 10 frames.
        var t = 0L
        while (t < 10 * PERIOD) {
            tx.tick(t)
            t += 50
        }
        assertEquals(10, fake.sent.size)
    }

    @Test
    fun `sleepMs never busy-loops and never overshoots the rate floor`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()
        tx.tick(0)

        assertTrue(tx.sleepMs(0) >= PeriodicTransmitter.MIN_SLEEP_MS)
        assertTrue(tx.sleepMs(0) <= PeriodicTransmitter.MIN_PERIOD_MS)
        // Already overdue -- must still return a bounded poll, never 0 or negative.
        assertEquals(PeriodicTransmitter.MIN_SLEEP_MS, tx.sleepMs(10 * PERIOD))
    }

    // --- failure backoff ----------------------------------------------------

    @Test
    fun `disables a slot after repeated send failures`() {
        val fake = FakeTransmitter(acceptSends = false)
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()

        var t = 0L
        repeat(PeriodicTransmitter.MAX_CONSECUTIVE_FAILURES) {
            tx.tick(t)
            t += PERIOD
        }
        assertEquals(PeriodicTransmitter.SlotState.FAILED, tx.states()["hold"])

        // Stays failed even once the transport recovers -- a dead endpoint is not retried forever.
        fake.acceptSends = true
        tx.tick(t + PERIOD)
        assertEquals(0, fake.sent.size)
    }

    @Test
    fun `a successful send resets the failure count`() {
        val fake = FakeTransmitter(acceptSends = false)
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()

        var t = 0L
        repeat(PeriodicTransmitter.MAX_CONSECUTIVE_FAILURES - 1) {
            tx.tick(t)
            t += PERIOD
        }
        assertEquals(PeriodicTransmitter.SlotState.SEND_REJECTED, tx.states()["hold"])
        fake.acceptSends = true
        tx.tick(t); t += PERIOD
        assertEquals(PeriodicTransmitter.SlotState.ACTIVE, tx.states()["hold"])

        // The success above reset the counter, so a further MAX-1 failures still must not reach
        // FAILED -- the slot is still retrying rather than permanently disabled.
        fake.acceptSends = false
        repeat(PeriodicTransmitter.MAX_CONSECUTIVE_FAILURES - 1) {
            tx.tick(t)
            t += PERIOD
        }
        assertEquals(PeriodicTransmitter.SlotState.SEND_REJECTED, tx.states()["hold"])
    }

    // --- frame encoding -----------------------------------------------------

    @Test
    fun `transmit frames carry a non-RX echo cookie and round-trip as isTx`() {
        val frame = GsUsbFrame.forTransmit(ALLOWED, byteArrayOf(1, 2, 3))
        assertTrue(frame.isEcho)
        assertEquals(3, frame.dlc)
        assertEquals(ALLOWED, frame.arbitrationId)
        assertFalse(frame.isExtended)
        // Tail is zero-padded to the fixed 8-byte wire layout.
        assertEquals(8, frame.data.size)
        assertEquals(0.toByte(), frame.data[7])

        val round = GsUsbFrame.fromBytes(GsUsbFrame.toBytes(frame))
        assertEquals(frame, round)
        assertTrue(round.toCanFrame(busIndex = 0, timestampMs = 1).isTx)

        val received = GsUsbFrame(
            GsUsbFrame.ECHO_ID_RX, ALLOWED, 8, 0, 0, ByteArray(8),
        )
        assertFalse(received.isEcho)
        assertFalse(received.toCanFrame(busIndex = 0, timestampMs = 1).isTx)
    }

    @Test
    fun `an unexpected echo_id is kept as received, never marked TX`() {
        // Fail-safe direction. A TX-marked frame is written as "Tx" and skipped entirely by
        // tools/influx_upload.py, so misclassifying a received frame as ours would silently remove
        // it from the corpus. Only our own cookie may mark a frame TX.
        val odd = GsUsbFrame(echoId = 7, rawCanId = ALLOWED, dlc = 8, channel = 0, flags = 0,
            data = ByteArray(8))
        assertFalse(odd.isEcho)
        assertFalse(odd.toCanFrame(busIndex = 0, timestampMs = 1).isTx)
    }

    /**
     * A loop that oversleeps every time (as `delay()` does, by a few ms) must not stretch the
     * period: scheduled from the late tick, the `0x600` slot ran at ~531 ms in the emulator harness
     * against the RCU's 523-525 ms.
     */
    @Test
    fun `oversleeping loop does not stretch the period`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()
        val sendTimes = ArrayList<Long>()
        var t = 0L
        while (sendTimes.size < 20) {
            if (tx.tick(t) == 1) sendTimes.add(t)
            t += tx.sleepMs(t) + 7
        }
        val mean = (sendTimes.last() - sendTimes.first()) / 19.0
        assertTrue("mean period $mean", mean < PERIOD + 2)
    }

    @Test
    fun `a slot resuming after a long block restarts rather than bursting`() {
        val fake = FakeTransmitter()
        val tx = newTx(fake).apply { enabled = true }
        tx.registerHold()
        assertEquals(1, tx.tick(0))
        tx.enabled = false
        for (t in 25L..10_000L step 25) tx.tick(t)
        tx.enabled = true
        var sent = 0
        for (t in 10_025L..10_500L step 25) sent += tx.tick(t)
        assertEquals(1, sent)
    }

    /** A registered but disabled slot is the car's normal state; it must not keep the loop busy. */
    @Test
    fun `disabled with a registered slot sleeps the idle interval`() {
        val tx = newTx(FakeTransmitter())
        tx.registerHold()
        tx.tick(0)
        assertEquals(PeriodicTransmitter.IDLE_SLEEP_MS, tx.sleepMs(0))
        tx.enabled = true
        assertTrue(tx.sleepMs(0) <= PeriodicTransmitter.MIN_PERIOD_MS)
    }
}
