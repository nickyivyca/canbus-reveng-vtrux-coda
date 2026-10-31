package com.reverseit.coda

import com.reverseit.cancore.CanFrame
import com.reverseit.coda.ThermalState.COOLING
import com.reverseit.coda.ThermalState.HEATING
import com.reverseit.coda.ThermalState.NONE
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The green screen's cabin and battery icons from the HVAC mode nibble, `0x276` B2 bits 5:2
 * (`projects/coda/notes/hvac/coda-hvac-decompile-notes.md` section 9.4, step 6d; mapping approved
 * 2026-10-28 in `projects/coda/notes/thermal-indicator-signals.md`).
 */
class HvacModeTest {

    /** Nibble -> (cabin, battery), the approved table. */
    private val table = mapOf(
        0 to (NONE to NONE),
        1 to (NONE to HEATING),
        2 to (HEATING to NONE),
        3 to (NONE to COOLING),
        4 to (COOLING to NONE),
        5 to (HEATING to HEATING),
        6 to (COOLING to COOLING),
        7 to (COOLING to HEATING),
        8 to (HEATING to COOLING),
    )

    @Test
    fun `every nibble maps as approved, whatever the HV-disable and top bits hold`() {
        for ((nib, icons) in table) for (low in 0..3) for (top in 0..3) {
            val b2 = (top shl 6) or (nib shl 2) or low
            assertEquals("B2 0x%02X".format(b2), icons, HvacMode.cabin(b2) to HvacMode.battery(b2))
        }
        for (nib in 9..15) {
            assertEquals(NONE to NONE, HvacMode.cabin(nib shl 2) to HvacMode.battery(nib shl 2))
        }
    }

    @Test
    fun `the B2 values the car actually sends`() {
        // From the corpus (thermal-indicator-signals.md): 0x0D pack cool with the cabin off, which
        // the old bit logic showed as cabin HEATING; 0x21 (nibble 8) cabin heat with pack cool, whose
        // cabin icon it showed as NONE.
        assertEquals(NONE to COOLING, icons(0x0D))
        assertEquals(HEATING to COOLING, icons(0x21))
        assertEquals(HEATING to NONE, icons(0x09))
        assertEquals(COOLING to NONE, icons(0x11))
        assertEquals(NONE to NONE, icons(0x01))
        assertEquals(NONE to COOLING, icons(0x0E))  // nibble 3, HV disabled
    }

    @Test
    fun `the decoder takes the icons from B2 and the compressor flag from 0x410 B6`() {
        val dec = CodaSignalDecoder()
        dec.update(frame(CodaConstants.ID_HVAC_STATUS, 0, 0, 0x21, 0, 0, 0, 0, 200))
        var s = dec.buildState()
        assertEquals(HEATING, s.cabinThermal)
        assertEquals(COOLING, s.batteryThermal)
        assertFalse(s.compressorOn)

        dec.update(frame(CodaConstants.ID_AC_COMPRESSOR_CMD, 0, 0, 0, 0, 0, 0, 50, 45))
        assertTrue(dec.buildState().compressorOn)
        dec.update(frame(CodaConstants.ID_AC_COMPRESSOR_CMD, 0, 0, 0, 0, 0, 0, 0, 45))
        assertFalse(dec.buildState().compressorOn)

        dec.update(frame(CodaConstants.ID_HVAC_STATUS, 0, 0, 0x0D, 0, 0, 0, 0, 200))
        s = dec.buildState()
        assertEquals(NONE, s.cabinThermal)
        assertEquals(COOLING, s.batteryThermal)
    }

    private fun icons(b2: Int) = HvacMode.cabin(b2) to HvacMode.battery(b2)

    private fun frame(id: Int, vararg b: Int) =
        CanFrame(0, 0L, id, false, 8, ByteArray(8) { b[it].toByte() })
}
