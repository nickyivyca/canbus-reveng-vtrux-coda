package com.reverseit.tpms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The `0x200`/`0x208` byte decodes shared by the extractor and the live GPS pairing. */
class WheelDecodeTest {

    private fun frame(vararg b: Int) = b.copyOf(8)

    @Test
    fun `wheel is the 14-bit count above 0xC000`() {
        val d = frame(0, 0, 0, 0, 0xC5, 0x80, 0xC0, 0x01)
        assertEquals(0x0580, WheelRatioExtractor.wheel(d, 4))
        assertEquals(1, WheelRatioExtractor.wheel(d, 6))
    }

    @Test
    fun `an all-ones wheel word is a dead channel`() {
        assertTrue(WheelRatioExtractor.stuckWheel(frame(0, 0, 0, 0, 0xFF, 0xFF, 0xC5, 0x80)))
        assertTrue(WheelRatioExtractor.stuckWheel(frame(0, 0, 0, 0, 0xC5, 0x80, 0xFF, 0xFF)))
        assertFalse(WheelRatioExtractor.stuckWheel(frame(0, 0, 0, 0, 0xFF, 0xFE, 0xC5, 0x80)))
    }

    @Test
    fun `brake pressure is 12 bits and an invalid reading counts as braking`() {
        // Valid (bit 4 of d[2]) with zero pressure: brakes off.
        assertEquals(0.0, WheelRatioExtractor.brake(frame(0, 0, 0x10, 0x00)), 0.0)
        assertEquals(0x234.toDouble(), WheelRatioExtractor.brake(frame(0, 0, 0x12, 0x34)), 0.0)
        // Invalid: the old raw16 - 4096 read this as negative, i.e. brakes OFF. Now it fails the
        // `<= 0` gate by the smallest margin, whatever the pressure bits say.
        assertEquals(1.0, WheelRatioExtractor.brake(frame(0, 0, 0x00, 0x00)), 0.0)
        assertEquals(1.0, WheelRatioExtractor.brake(frame(0, 0, 0x03, 0x21)), 0.0)
    }
}
