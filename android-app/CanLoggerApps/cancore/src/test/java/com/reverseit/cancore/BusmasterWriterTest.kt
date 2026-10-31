package com.reverseit.cancore

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Log timing. The defect these pin: at every segment roll, frames received before the new file
 * opened were written with negative offsets (`00:00:00:-160`) that every parser rejects.
 */
class BusmasterWriterTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private fun frame(wallMs: Long, nanos: Long, id: Int = 0x200) =
        CanFrame(busIndex = 0, timestampMs = wallMs, id = id, isExtended = false, dlc = 8,
            data = ByteArray(8), elapsedNanos = nanos)

    private fun write(startMs: Long, frames: List<CanFrame>): Pair<File, BusmasterWriter> {
        val f = File(tmp.root, "t.log")
        val w = BusmasterWriter(f, numBuses = 1, bitrateKbps = 500, sessionStartMs = startMs)
        w.open()
        frames.forEach { w.writeFrame(it) }
        w.close()
        return f to w
    }

    private fun dataLines(f: File) = f.readLines().filter { it.isNotBlank() && !it.startsWith("***") }

    @Test
    fun `frames received before the file opened are not written with negative time`() {
        // The segment opened at wall 10_000, but these were received 16 ms and 6 ms earlier and
        // were still queued -- exactly the roll case.
        val (f, w) = write(startMs = 10_000, frames = listOf(
            frame(9_984, 1_000_000_000L),
            frame(9_994, 1_010_000_000L),
            frame(10_020, 1_036_000_000L),
        ))
        val times = dataLines(f).map { it.substringBefore(' ') }
        assertEquals(listOf("00:00:00:0000", "00:00:00:0100", "00:00:00:0360"), times)
        assertFalse(times.any { '-' in it })
        assertEquals(0, w.outOfOrderFrames)
    }

    @Test
    fun `header start time is the first frame's wall time`() {
        val (f, _) = write(startMs = 10_000, frames = listOf(frame(1_758_700_000_123, 5L)))
        val expected = SimpleDateFormat("dd:MM:yyyy HH:mm:ss:SSS", Locale.US).format(Date(1_758_700_000_123))
        assertTrue(f.readLines().contains("***START DATE AND TIME $expected***"))
    }

    @Test
    fun `a wall-clock step mid-file does not move the offsets`() {
        // Clock synced backwards by an hour between the two frames; the monotonic stamps are 20 ms apart.
        val (f, _) = write(startMs = 0, frames = listOf(
            frame(7_200_000, 50_000_000L),
            frame(3_600_020, 70_000_000L),
        ))
        assertEquals(listOf("00:00:00:0000", "00:00:00:0200"), dataLines(f).map { it.substringBefore(' ') })
    }

    @Test
    fun `offsets are exact to the tick`() {
        // 3.404 s: the old Double path wrote 4039 here.
        assertEquals("00:00:03:4040", BusmasterWriter.formatOffset(3_404_000_000L))
        assertEquals("00:00:01:2345", BusmasterWriter.formatOffset(1_234_567_890L))
        assertEquals("01:02:03:0004", BusmasterWriter.formatOffset(((3600L + 120 + 3) * 10_000 + 4) * 100_000L))
    }

    @Test
    fun `an out-of-order frame is counted, not written as a step back`() {
        val (f, w) = write(startMs = 0, frames = listOf(
            frame(0, 100_000_000L), frame(0, 150_000_000L), frame(0, 140_000_000L)))
        assertEquals(1, w.outOfOrderFrames)
        assertEquals(listOf("00:00:00:0000", "00:00:00:0500", "00:00:00:0500"),
            dataLines(f).map { it.substringBefore(' ') })
    }

    @Test
    fun `a file closed with no frames still has a header`() {
        val (f, _) = write(startMs = 1_758_700_000_000, frames = emptyList())
        assertTrue(f.readLines().any { it.startsWith("***START DATE AND TIME") })
        assertTrue(dataLines(f).isEmpty())
    }

    @Test
    fun `written lines parse back with the offsets they were given`() {
        val (f, _) = write(startMs = 0, frames = listOf(frame(0, 0L), frame(0, 2_500_300_000L)))
        val parsed = dataLines(f).map { BusmasterReader.parseLine(it)!! }
        assertEquals(listOf(0L, 2500L), parsed.map { it.relativeMs })
    }
}
