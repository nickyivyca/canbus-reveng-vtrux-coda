package com.reverseit.cancore

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

/** [SlcanWriter] produces what [SlcanReader] parses, byte for byte, in both id formats. */
class SlcanWriterTest {

    private fun decode(line: ByteArray): List<CanFrame> {
        val out = ArrayList<CanFrame>()
        SlcanReader(clock = { 0L }) { out.add(it) }.feed(line)
        return out
    }

    @Test
    fun standardFrameText() {
        val line = SlcanWriter.encode(0x600, byteArrayOf(0x13, 1, 1, 7, 0, 0x2A, 0x10, 0x4A))
        assertEquals("t600813010107002A104A\r", String(line, Charsets.US_ASCII))
    }

    @Test
    fun extendedFrameText() {
        val line = SlcanWriter.encode(0x18DAF110, byteArrayOf(0x02, 0x3E), isExtended = true)
        assertEquals("T18DAF1102023E\r", String(line, Charsets.US_ASCII))
    }

    @Test
    fun roundTripsThroughReaderForEveryDlc() {
        for (dlc in 0..8) {
            val data = ByteArray(dlc) { (0xF0 + it).toByte() }
            for ((id, ext) in listOf(0x7FF to false, 0x001 to false, 0x1FFFFFFE to true, 0 to true)) {
                val frames = decode(SlcanWriter.encode(id, data, ext))
                assertEquals("dlc $dlc id $id", 1, frames.size)
                val f = frames[0]
                assertEquals(id, f.id)
                assertEquals(ext, f.isExtended)
                assertEquals(dlc, f.dlc)
                assertArrayEquals(data, f.data.copyOf(dlc))
            }
        }
    }

    @Test
    fun dlcBelowDataSizeWritesOnlyDlcBytes() {
        val line = SlcanWriter.encode(0x123, ByteArray(8) { 0x55 }, dlc = 2)
        assertEquals("t12325555\r", String(line, Charsets.US_ASCII))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsElevenBitIdOutOfRange() {
        SlcanWriter.encode(0x800, ByteArray(0))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsDlcAboveEight() {
        SlcanWriter.encode(0x100, ByteArray(9))
    }
}
