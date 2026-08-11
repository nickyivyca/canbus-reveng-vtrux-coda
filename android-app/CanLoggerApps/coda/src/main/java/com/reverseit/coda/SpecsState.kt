package com.reverseit.coda

/**
 * Everything page 2 renders.
 *
 * Every field is nullable and defaults to null, meaning "not seen on the bus".
 * That distinction matters: a real 0 A and a missing message must not look the
 * same, and several of these IDs are only broadcast during a charging session.
 * The UI degrades a null to a blank marker rather than drawing a zero.
 */
data class SpecsState(
    // --- Battery (always shown) ---
    val cellVMinV: Double? = null,
    val cellVMaxV: Double? = null,
    val cellVMinId: Int? = null,
    val cellVMaxId: Int? = null,
    val cellTMinC: Double? = null,
    val cellTMaxC: Double? = null,
    val packCurrentA: Double? = null,
    val dischargeLimitA: Double? = null,
    val chargeLimitA: Double? = null,

    /** True only when 0x270 B0 is exactly the known RED-lamp value. */
    val coldFault: Boolean = false,

    // --- Accessory loads (always shown) ---
    val acCompressorKw: Double? = null,
    val acCompressorMaxKw: Double? = null,
    val ptcHeaterKw: Double? = null,
    val dcdcW: Double? = null,

    // --- Drive mode ---
    val motorTorqueNm: Double? = null,
    /** Raw 0x241 bytes selected by [CodaConstants.MCM_THERMAL_BYTES], as degC. */
    val drivetrainTempsC: List<Double?> = emptyList(),

    // --- Charge mode ---
    /**
     * Drives the mode column. Sourced from 0x378 HVPowermode, exactly as page 1
     * does, so the two pages can never disagree about what the car is doing.
     */
    val isCharging: Boolean = false,
    val chargeMode: Int? = null,
    val acInputVoltage: Double? = null,
    val acInputCurrentA: Double? = null,
    val hvOutputVoltage: Double? = null,
    val hvOutputCurrentA: Double? = null,
    val evseMaxCurrentA: Double? = null,
    val chargerTempsC: List<Double?> = emptyList(),
) {
    /** AC input power, W. Null unless both halves are present. */
    val acInputW: Double?
        get() {
            val v = acInputVoltage ?: return null
            val i = acInputCurrentA ?: return null
            return v * i
        }

    /**
     * The car's own AC current ceiling at the present input voltage, in amps.
     * Compared against [evseMaxCurrentA]; the lower of the two is what actually
     * limits the session.
     */
    val carLimitA: Double?
        get() {
            val v = acInputVoltage ?: return null
            if (v < 50.0) return null
            return CodaConstants.ONBOARD_CHARGER_MAX_W / v
        }
}

/** 0x378 B0[3:0], per VAL_ 888 Chargemode in CODA-B-CAN.dbc. */
fun chargeModeLabel(value: Int?): String? = when (value) {
    1 -> "NO PROX"
    2 -> "PLUGGED IN"
    3 -> "CHARGING"
    4 -> "CHARGE COMPLETE"
    5 -> "MAINTENANCE CHARGE"
    else -> null
}
