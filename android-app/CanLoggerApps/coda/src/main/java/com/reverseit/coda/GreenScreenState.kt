package com.reverseit.coda

data class GreenScreenState(
    val mode: DisplayMode       = DisplayMode.DRIVING,
    val cabinThermal: ThermalState  = ThermalState.NONE,
    val motorTorque: TorqueState    = TorqueState.NONE,
    val batteryThermal: ThermalState = ThermalState.NONE,

    // Numeric text overlays
    val socPercent: Float       = 0f,   // 0-100 %
    val expRangeMiles: Float    = 0f,
    val maxRangeMiles: Float    = 0f,

    // Notch position inputs (physical units, normalized to 0-1 in the view)
    val motorTorqueNm: Float    = 0f,   // signed Nm; bidirectional slider
    val climatePowerKw: Float   = 0f,
    val auxPowerW: Float        = 0f,
    val battTempC: Float        = 0f,
)

enum class DisplayMode    { CHARGING, DRIVING }
enum class ThermalState   { COOLING, NONE, HEATING }
enum class TorqueState    { NEGATIVE, NONE, POSITIVE }

/** Build the asset filename for the 4-character JPG key. */
fun GreenScreenState.jpgKey(): String {
    val m = if (mode == DisplayMode.CHARGING) "C" else "D"
    val cabin = when (cabinThermal) {
        ThermalState.COOLING -> "B"
        ThermalState.NONE    -> "N"
        ThermalState.HEATING -> "R"
    }
    // Charging mode always has no motor torque
    val motor = if (mode == DisplayMode.CHARGING) "N" else when (motorTorque) {
        TorqueState.NEGATIVE -> "G"
        TorqueState.NONE     -> "N"
        TorqueState.POSITIVE -> "R"
    }
    val batt = when (batteryThermal) {
        ThermalState.COOLING -> "B"
        ThermalState.NONE    -> "N"
        ThermalState.HEATING -> "R"
    }
    return "$m$cabin$motor$batt"
}
