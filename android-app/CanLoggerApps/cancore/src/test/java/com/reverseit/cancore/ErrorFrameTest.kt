package com.reverseit.cancore

import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Bug 11: gs_usb error frames were logged as standard data frames `0x004` / `0x00C`, because
 * [GsUsbFrame.arbitrationId] masks off bit 29 (`CAN_ERR_FLAG`) and nothing else looked at it.
 * Plan: android-app/notes/plans/gs-usb-error-frames.md, Step 4.
 *
 * Payloads are real, not invented:
 * - Coda form error, `CANLogs/CodaLogs/` (projects/coda/README.md, anchor section):
 *   `00 00 02 00 00 00 00 1A`.
 * - Vtrux stuff error, `projects/vtrux/logs/partsdrive_20260801_T0.log`: `00 00 04 00 00 00 00 01`.
 * - Error-passive form error from the the Linux box rig through the AVD, 2026-10-28:
 *   `00 30 02 00 00 00 00 FF`.
 */
class ErrorFrameTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private companion object {
        val CODA_FORM = bytes(0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x1A)
        val VTRUX_STUFF = bytes(0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x01)
        val RIG_PASSIVE = bytes(0x00, 0x30, 0x02, 0x00, 0x00, 0x00, 0x00, 0xFF)

        fun bytes(vararg b: Int) = ByteArray(b.size) { b[it].toByte() }

        /** A received frame exactly as the adapter puts it on the bulk IN endpoint. */
        fun wire(rawCanId: Int, data: ByteArray, dlc: Int = 8): ByteArray =
            ByteBuffer.allocate(GsUsbFrame.FRAME_SIZE).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(GsUsbFrame.ECHO_ID_RX).putInt(rawCanId)
                .put(dlc.toByte()).put(0).put(0).put(0).put(data).array()
    }

    // --- layer 1: decode -----------------------------------------------------

    @Test
    fun `controller plus protocol error frame decodes as an error`() {
        for (payload in listOf(CODA_FORM, VTRUX_STUFF, RIG_PASSIVE)) {
            val f = GsUsbFrame.fromBytes(wire(0x2000000C, payload))
            assertTrue(f.isError)
            assertEquals(0x00C, f.arbitrationId)
            assertFalse(f.isExtended)
            val c = f.toCanFrame(busIndex = 1, timestampMs = 0L, elapsedNanos = 0L)
            assertTrue(c.isError)
            assertEquals(0x00C, c.id)
            assertTrue(payload.contentEquals(c.data))
        }
    }

    @Test
    fun `controller-only error frame decodes as an error`() {
        val f = GsUsbFrame.fromBytes(wire(0x20000004, bytes(0, 0, 0, 0, 0, 0, 0, 1)))
        assertTrue(f.isError)
        assertEquals(0x004, f.arbitrationId)
    }

    /** The case the old code could not express: a real message whose ID is 0x004. */
    @Test
    fun `data frame with id 0x004 stays a data frame`() {
        val f = GsUsbFrame.fromBytes(wire(0x004, CODA_FORM))
        assertFalse(f.isError)
        assertFalse(f.toCanFrame(0, 0L, 0L).isError)
        assertEquals(0x004, f.arbitrationId)
    }

    /** Bit 28 is part of a 29-bit ID; only bit 29 marks an error. */
    @Test
    fun `extended frame with the top id bit set is not an error`() {
        val f = GsUsbFrame.fromBytes(wire(0x9FFFFFFF.toInt(), CODA_FORM))
        assertFalse(f.isError)
        assertTrue(f.isExtended)
        assertEquals(0x1FFFFFFF, f.arbitrationId)
    }

    // --- layer 2: format -----------------------------------------------------

    private fun errFrame(nanos: Long, data: ByteArray = CODA_FORM, id: Int = 0x00C) =
        CanFrame(busIndex = 0, timestampMs = 1_000L, id = id, isExtended = false, dlc = 8,
            data = data, elapsedNanos = nanos, isError = true)

    private fun dataFrame(nanos: Long, id: Int = 0x200) =
        CanFrame(busIndex = 0, timestampMs = 1_000L, id = id, isExtended = false, dlc = 8,
            data = ByteArray(8), elapsedNanos = nanos)

    private fun writeLines(frames: List<CanFrame>): List<String> {
        val f = File(tmp.root, "e.log")
        val w = BusmasterWriter(f, numBuses = 1, bitrateKbps = 500, sessionStartMs = 1_000L)
        w.open()
        frames.forEach { w.writeFrame(it) }
        w.close()
        return f.readLines().filter { it.isNotBlank() && !it.startsWith("***") }
    }

    /**
     * The exact line. The Python round trip (android-app/notes/artifacts/err_line_roundtrip.py)
     * parses this same string, so a change here must change it there.
     */
    @Test
    fun `error frame is written as an ERR line`() {
        val lines = writeLines(listOf(dataFrame(0L), errFrame(1_000_000L)))
        assertEquals("00:00:00:0000 Rx 1 0x200 s 8 00 00 00 00 00 00 00 00", lines[0])
        assertEquals("00:00:00:0010 Rx 1 0xC ERR 8 00 00 02 00 00 00 00 1A", lines[1])
    }

    @Test
    fun `an error frame first sets the file's time origin`() {
        val lines = writeLines(listOf(errFrame(5_000_000L), dataFrame(6_000_000L)))
        assertEquals("00:00:00:0000 Rx 1 0xC ERR 8 00 00 02 00 00 00 00 1A", lines[0])
        assertEquals("00:00:00:0010 Rx 1 0x200 s 8 00 00 00 00 00 00 00 00", lines[1])
    }

    /** Replaying a log must not turn the adapter's error report back into message 0x00C. */
    @Test
    fun `the replay reader skips ERR lines and still reads data lines`() {
        assertNull(BusmasterReader.parseLine("00:00:00:0010 Rx 1 0xC ERR 8 00 00 02 00 00 00 00 1A"))
        val p = BusmasterReader.parseLine("00:00:00:0000 Rx 1 0x200 s 8 00 00 00 00 00 00 00 00")
        assertEquals(0x200, p?.frame?.id)
    }

    // --- layer 3: in-app readers ---------------------------------------------

    @Test
    fun `pipeline keeps error frames off frames but puts them on logFrames`() = runBlocking {
        val p = CanPipelineManager()
        try {
            val data = async(start = CoroutineStart.UNDISPATCHED) { p.frames.take(1).toList() }
            val log = async(start = CoroutineStart.UNDISPATCHED) { p.logFrames.take(2).toList() }
            val e = errFrame(1L)
            val d = dataFrame(2L)
            p.emit(e)
            p.emit(d)
            assertEquals(listOf(d), data.await())
            assertEquals(listOf(e, d), log.await())
        } finally {
            p.shutdown()
        }
    }

    @Test
    fun `error frames move no anchor count in the bus resolver`() {
        val r = BusIdentityResolver(
            listOf(BusIdentity("c_can", setOf(0x00C, 0x00D, 0x00E))),
            decisionWindowMs = 0L,
        )
        for (t in 0L until 50L) {
            r.observe(errFrame(t).copy(timestampMs = t * 100L, id = 0x00C))
        }
        assertTrue(r.assignments.value.isEmpty())
        for (t in 50L until 60L) {
            for (id in listOf(0x00C, 0x00D, 0x00E)) r.observe(dataFrame(t, id).copy(timestampMs = t * 600L))
        }
        assertEquals(mapOf("c_can" to 0), r.assignments.value)
    }

    @Test
    fun `error frames do not trip the transmitter's contention guard`() {
        val tx = PeriodicTransmitter(object : CanTransmitter {
            override fun canTransmit(busIndex: Int) = true
            override fun transmit(busIndex: Int, id: Int, data: ByteArray, isExtended: Boolean) = true
        }, allowedIds = setOf(0x600))
        tx.observe(errFrame(0L, id = 0x600).copy(timestampMs = 1_000L))
        assertFalse(tx.isContended(0, 0x600, nowMs = 1_010L))
        tx.observe(dataFrame(0L, id = 0x600).copy(timestampMs = 1_000L))
        assertTrue(tx.isContended(0, 0x600, nowMs = 1_010L))
    }
}
