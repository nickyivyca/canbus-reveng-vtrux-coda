package com.reverseit.tpms

import com.reverseit.cancore.CanFrame
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * [GpsRateAccumulator]'s live D CAN rule on a real two-channel capture: every frame of
 * `coda_20260926_155726_T0` is fed through [GpsRateAccumulator.observe] in file order, and the
 * channel it reads as D CAN is sampled after each frame. The withdrawn count-based pick changed
 * hands 11,468 times on `0x200` in one such segment (spec section 1); the anchor rule should settle
 * once, within the first few frames, on the channel [WheelRatioExtractor.readFrames] pins, and never
 * move.
 *
 * Skipped unless `TPMS_CODA_LOGS` points at the `CodaLogs` folder.
 */
class GpsBusSelectionRealLogTest {

    @Test
    fun `the live rule settles once on the extractor's D CAN channel and holds it`() {
        val dir = System.getenv("TPMS_CODA_LOGS")
        assumeTrue("TPMS_CODA_LOGS not set", !dir.isNullOrEmpty())
        val log = File(dir, "coda_20260926_155726_T0.log")
        val pinned = WheelRatioExtractor.readFrames(log).front.first().bus    // BUSMASTER channel, 1-based

        val acc = GpsRateAccumulator { log.name }
        var frames = 0L; var decidedAt = -1L; var changes = 0; var last: Int? = null
        log.bufferedReader().useLines { lines ->
            for (line in lines) {
                val tok = line.trim().split(Regex("\\s+"))
                if (tok.size < 6 || !tok[3].startsWith("0x")) continue
                val bus = tok[2].toIntOrNull() ?: continue
                val dlc = tok[5].toIntOrNull() ?: continue
                val data = ByteArray(8) { i -> tok.getOrNull(6 + i)?.toIntOrNull(16)?.toByte() ?: 0 }
                acc.observe(CanFrame(busIndex = bus - 1, timestampMs = 0, id = tok[3].substring(2).toInt(16),
                    isExtended = false, dlc = dlc, data = data, elapsedNanos = frames))
                frames++
                val now = acc.dCanBus
                if (now != last) { changes++; last = now; if (decidedAt < 0 && now != null) decidedAt = frames }
            }
        }
        println("frames %d, decided after %d, changes %d, D CAN index %s (extractor channel %d)"
            .format(frames, decidedAt, changes, last, pinned))
        assertEquals(pinned - 1, last)
        assertEquals("decided once and never moved", 1, changes)
        assertTrue("decided after $decidedAt frames", decidedAt in 1..200)
    }
}
