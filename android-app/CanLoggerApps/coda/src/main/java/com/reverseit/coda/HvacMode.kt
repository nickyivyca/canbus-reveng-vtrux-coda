package com.reverseit.coda

/**
 * The HVAC's own mode, from `0x276` HVACStatus B2, for the green screen's cabin and battery icons.
 *
 * B2 = `(0x3DF3 & 3) << 6 | mode nibble << 2 | HVACHVDisableStatus`. The nibble (HVAC RAM `0x37C4`)
 * is the HVAC's mode chart: its cabin superstate (none / heat / cool) crossed with its pack heat
 * and pack cool demands. Keying the icons on it, rather than on coolant temperatures, stops the
 * battery icon flipping between heating and cooling while the HVAC's mode holds still.
 *
 * Mapping approved 2026-10-28: `projects/coda/notes/thermal-indicator-signals.md`. Cabin heat with
 * the compressor running (demist) stays HEATING, as on the original green screen.
 */
object HvacMode {

    fun nibble(b2: Int): Int = (b2 ushr 2) and 0x0F

    fun cabin(b2: Int): ThermalState = when (nibble(b2)) {
        2, 5, 8 -> ThermalState.HEATING
        4, 6, 7 -> ThermalState.COOLING
        else    -> ThermalState.NONE
    }

    fun battery(b2: Int): ThermalState = when (nibble(b2)) {
        1, 5, 7 -> ThermalState.HEATING
        3, 6, 8 -> ThermalState.COOLING
        else    -> ThermalState.NONE
    }
}
