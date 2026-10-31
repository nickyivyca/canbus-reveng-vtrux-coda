package com.reverseit.coda

import com.reverseit.cancore.CanFrame
import com.reverseit.cancore.SignalDecoder
import com.reverseit.coda.CodaConstants.BATT_TEMP_DISPLAY_MAX_C
import com.reverseit.coda.CodaConstants.BATT_TEMP_DISPLAY_MIN_C
import com.reverseit.coda.CodaConstants.AUX_POWER_DISPLAY_MAX_W
import com.reverseit.coda.CodaConstants.CLIMATE_POWER_DISPLAY_MAX_KW
import com.reverseit.coda.CodaConstants.MOTOR_TORQUE_DEADBAND_NM
import com.reverseit.coda.CodaConstants.MOTOR_TORQUE_DISPLAY_MAX_NM
import com.reverseit.coda.CodaConstants.MOTOR_TORQUE_SCALE
import com.reverseit.coda.CodaConstants.MOTOR_TORQUE_ZERO_RAW

/**
 * Decodes B CAN frames into Coda display state.
 *
 * All signal IDs, byte positions, and scales come from CODA-B-CAN.dbc and projects/coda/README.md.
 * Call [update] on every incoming frame (IO thread). Call [buildState] at 10 Hz (main thread).
 *
 * Thread safety: update() and buildState() may be called from different threads.
 * Each raw field is a plain Int/Float and reads/writes are individually atomic on JVM,
 * so no locking is needed for this display-only use case (a stale read of a single
 * field by one tick is acceptable).
 */
class CodaSignalDecoder : SignalDecoder {

    // 0x378 BattPowermode: B0[7:4] = HVPowermode nibble
    @Volatile private var hvPowermode: Int = 4   // default = HV On Drive

    // 0x1C0 MCM telemetry: B0-B1 LE uint16 motor torque
    @Volatile private var motorTorqueRaw: Int = MOTOR_TORQUE_ZERO_RAW

    // 0x276 HVACStatus: B0=PTC kW*10, B1=ACCM kW*10, B2=HVAC flags
    @Volatile private var ptcPowerRaw:  Int = 0
    @Volatile private var accmPowerRaw: Int = 0
    @Volatile private var hvacFlags:    Int = 0   // B2: HVAC mode nibble in bits 5:2, see HvacMode

    // 0x391 HVACAirState: B4=ReturnAirTemp, B5=EvapAirOffTemp (raw, T=raw-128)
    @Volatile private var returnAirRaw:  Int = 128
    @Volatile private var evapAirOffRaw: Int = 128

    // 0x383 BMSBattStatus: B0-B1 BE uint16, SoC = raw/10 %
    @Volatile private var socRaw: Int = 0

    // 0x2C1 BMSDrivingRange: B1=ExpRange, B3=MaxRange (raw bytes)
    @Volatile private var expRangeRaw: Int = 0
    @Volatile private var maxRangeRaw: Int = 0

    // 0x382 BMSThermal: B0=AvgCellTemp (raw-128 degC)
    @Volatile private var battTempRaw: Int = 128

    // 0x1D5 DCDCStatus1: B3=Voltage14V, B6&0x7F=Current14V
    @Volatile private var voltage14vRaw:  Int = 0
    @Volatile private var current14vRaw:  Int = 0

    // ---- Page 2 (specs screen) ----
    // Null means "message not seen yet". Several of these IDs only exist during a
    // charging session, so a missing value must stay distinguishable from a real 0.

    // 0x275 BMSDriveLimits
    @Volatile private var dischargeLimitRaw: Int? = null
    @Volatile private var chargeLimitRaw:    Int? = null
    @Volatile private var packCurrentRaw:    Int? = null

    // 0x381 BMSVminVmax (all BE uint16, 1 mV/bit)
    @Volatile private var cellVMaxMv: Int? = null
    @Volatile private var cellVMinMv: Int? = null
    @Volatile private var cellVMaxId: Int? = null
    @Volatile private var cellVMinId: Int? = null

    // 0x382 BMSThermal: B1=Cell_T_max, B2=Cell_T_min (raw-128 degC)
    @Volatile private var cellTMaxRaw: Int? = null
    @Volatile private var cellTMinRaw: Int? = null

    // 0x270 / 0x271 fault state
    @Volatile private var bmsFaultB0:  Int? = null

    // 0x378 B0[3:0] Chargemode enum
    @Volatile private var chargeMode: Int? = null

    // 0x439 / 0x410 AC compressor
    @Volatile private var compressorKwRaw:    Int? = null
    @Volatile private var compressorMaxKwRaw: Int? = null
    // 0x410 B6 target_compressor_speed (x60 rpm): non-zero = compressor commanded on
    @Volatile private var compressorTargetRaw: Int = 0

    // 0x241 MCM_Thermal -- whole payload; byte roles are unconfirmed so the
    // selection happens at display time via CodaConstants.MCM_THERMAL_BYTES.
    @Volatile private var mcmThermal: ByteArray? = null

    // Charger AC input / HV output. CMM and CMS each report their own values,
    // not totals, so the two must be summed.
    @Volatile private var cmmAcVoltRaw: Int? = null
    @Volatile private var cmmAcAmpRaw:  Int? = null
    @Volatile private var cmsAcVoltRaw: Int? = null
    @Volatile private var cmsAcAmpRaw:  Int? = null
    @Volatile private var cmmHvVoltRaw: Int? = null
    @Volatile private var cmmHvAmpRaw:  Int? = null
    @Volatile private var cmsHvVoltRaw: Int? = null
    @Volatile private var cmsHvAmpRaw:  Int? = null

    // 0x27A CMSTempStatus -- four /32 BE uint16 temps
    @Volatile private var chargerTempRaw: IntArray? = null

    // 0x050 B5-6 EVSEMaxCurrent (J1772 pilot offer). Charge-only.
    @Volatile private var evseMaxAmpRaw: Int? = null

    override fun update(frame: CanFrame) {
        val d = frame.data
        when (frame.id) {
            CodaConstants.ID_BATT_POWERMODE -> {
                if (d.size >= 1) {
                    hvPowermode = (d[0].toInt() and 0xFF) ushr 4
                    chargeMode  = d[0].toInt() and 0x0F
                }
            }
            CodaConstants.ID_MCM_TELEMETRY -> {
                if (d.size >= 2)
                    motorTorqueRaw = (d[0].toInt() and 0xFF) or ((d[1].toInt() and 0xFF) shl 8)
            }
            CodaConstants.ID_HVAC_STATUS -> {
                if (d.size >= 8) {
                    ptcPowerRaw  = d[0].toInt() and 0xFF
                    accmPowerRaw = d[1].toInt() and 0xFF
                    hvacFlags    = d[2].toInt() and 0xFF
                }
            }
            CodaConstants.ID_HVAC_AIR_STATE -> {
                if (d.size >= 6) {
                    returnAirRaw  = d[4].toInt() and 0xFF
                    evapAirOffRaw = d[5].toInt() and 0xFF
                }
            }
            CodaConstants.ID_BMS_BATT_STATUS -> {
                if (d.size >= 2)
                    socRaw = ((d[0].toInt() and 0xFF) shl 8) or (d[1].toInt() and 0xFF)
            }
            CodaConstants.ID_BMS_DRIVING_RANGE -> {
                if (d.size >= 4) {
                    expRangeRaw = d[1].toInt() and 0xFF
                    maxRangeRaw = d[3].toInt() and 0xFF
                }
            }
            CodaConstants.ID_BMS_THERMAL -> {
                if (d.size >= 1)
                    battTempRaw = d[0].toInt() and 0xFF
                if (d.size >= 3) {
                    cellTMaxRaw = d[1].toInt() and 0xFF
                    cellTMinRaw = d[2].toInt() and 0xFF
                }
            }
            CodaConstants.ID_DCDC_STATUS1 -> {
                if (d.size >= 7) {
                    voltage14vRaw = d[3].toInt() and 0xFF
                    current14vRaw = d[6].toInt() and CodaConstants.CURRENT_14V_MASK
                }
            }

            // ---- Page 2 ----

            CodaConstants.ID_BMS_DRIVE_LIMITS -> {
                if (d.size >= 4) {
                    dischargeLimitRaw = d[0].toInt() and 0xFF
                    chargeLimitRaw    = d[1].toInt() and 0xFF
                    packCurrentRaw    = be16(d, 2)
                }
            }
            CodaConstants.ID_BMS_VMIN_VMAX -> {
                if (d.size >= 8) {
                    cellVMaxMv = be16(d, 2)
                    cellVMinMv = be16(d, 4)
                    cellVMaxId = d[6].toInt() and 0xFF
                    cellVMinId = d[7].toInt() and 0xFF
                }
            }
            CodaConstants.ID_BMS_FAULT_STATUS -> {
                if (d.size >= 1) bmsFaultB0 = d[0].toInt() and 0xFF
            }
            CodaConstants.ID_AC_COMPRESSOR_STS -> {
                if (d.size >= 3) compressorKwRaw = d[2].toInt() and 0xFF
            }
            CodaConstants.ID_AC_COMPRESSOR_CMD -> {
                if (d.size >= 8) {
                    compressorTargetRaw = d[6].toInt() and 0xFF
                    compressorMaxKwRaw  = d[7].toInt() and 0xFF
                }
            }
            CodaConstants.ID_MCM_THERMAL -> {
                if (d.size >= 8) mcmThermal = d.copyOf()
            }
            CodaConstants.ID_CMM_INPUT -> {
                if (d.size >= 4) { cmmAcVoltRaw = be16(d, 0); cmmAcAmpRaw = be16(d, 2) }
            }
            CodaConstants.ID_CMS_INPUT -> {
                if (d.size >= 4) { cmsAcVoltRaw = be16(d, 0); cmsAcAmpRaw = be16(d, 2) }
            }
            CodaConstants.ID_CMM_OUTPUT -> {
                if (d.size >= 4) { cmmHvVoltRaw = be16(d, 0); cmmHvAmpRaw = be16(d, 2) }
            }
            CodaConstants.ID_CMS_OUTPUT -> {
                if (d.size >= 4) { cmsHvVoltRaw = be16(d, 0); cmsHvAmpRaw = be16(d, 2) }
            }
            CodaConstants.ID_CMS_TEMPS -> {
                if (d.size >= 8)
                    chargerTempRaw = intArrayOf(be16(d, 0), be16(d, 2), be16(d, 4), be16(d, 6))
            }
            CodaConstants.ID_BMS_CHARGER_CMD -> {
                if (d.size >= 7) evseMaxAmpRaw = be16(d, 5)
            }
        }
    }

    /** Big-endian (Motorola) uint16 at byte offset [i]. All Coda DBCs are @0+. */
    private fun be16(d: ByteArray, i: Int): Int =
        ((d[i].toInt() and 0xFF) shl 8) or (d[i + 1].toInt() and 0xFF)

    /** Build a [GreenScreenState] from current signal values. Called at 10 Hz. */
    fun buildState(): GreenScreenState {
        val mode = if (hvPowermode == CodaConstants.HVPOWERMODE_CHARGE)
            DisplayMode.CHARGING else DisplayMode.DRIVING

        // Motor torque: decode from LE uint16 with zero at 0x7D80
        val torqueNm = (motorTorqueRaw - MOTOR_TORQUE_ZERO_RAW) * MOTOR_TORQUE_SCALE
        val motorState = when {
            torqueNm < -MOTOR_TORQUE_DEADBAND_NM -> TorqueState.NEGATIVE
            torqueNm >  MOTOR_TORQUE_DEADBAND_NM -> TorqueState.POSITIVE
            else -> TorqueState.NONE
        }

        // Cabin and battery thermal: the HVAC's own mode nibble in 0x276 B2 (see HvacMode).
        val cabinThermal   = HvacMode.cabin(hvacFlags)
        val batteryThermal = HvacMode.battery(hvacFlags)

        val socPct       = socRaw / 10f
        val expRangeMi   = expRangeRaw * CodaConstants.RANGE_SCALE + CodaConstants.RANGE_OFFSET
        val maxRangeMi   = maxRangeRaw * CodaConstants.RANGE_SCALE + CodaConstants.RANGE_OFFSET
        val climatePower = (ptcPowerRaw + accmPowerRaw) * CodaConstants.POWER_KW_SCALE
        val auxPowerW    = voltage14vRaw * CodaConstants.VOLTAGE_14V_SCALE *
                           current14vRaw * CodaConstants.CURRENT_14V_SCALE
        val battTempC    = (battTempRaw - CodaConstants.TEMP_RAW_OFFSET).toFloat()

        return GreenScreenState(
            mode            = mode,
            cabinThermal    = cabinThermal,
            motorTorque     = motorState,
            batteryThermal  = batteryThermal,
            socPercent      = socPct,
            expRangeMiles   = expRangeMi,
            maxRangeMiles   = maxRangeMi,
            motorTorqueNm   = torqueNm,
            climatePowerKw  = climatePower,
            auxPowerW       = auxPowerW,
            battTempC       = battTempC,
            compressorOn    = compressorTargetRaw > 0,
        )
    }

    /** Build the page-2 [SpecsState] from current signal values. Called at 10 Hz. */
    fun buildSpecsState(): SpecsState {
        val c = CodaConstants

        // CMM and CMS each report their own measurement, never a total, so the two
        // charger modules are summed. Voltage is shared across both, so take
        // whichever module is reporting rather than adding them.
        val acVolt = listOfNotNull(cmmAcVoltRaw, cmsAcVoltRaw)
            .maxOrNull()?.let { it * c.CHARGER_SCALE.toDouble() }
        val acAmp = sumOrNull(cmmAcAmpRaw, cmsAcAmpRaw)?.let { it * c.CHARGER_SCALE.toDouble() }
        val hvVolt = listOfNotNull(cmmHvVoltRaw, cmsHvVoltRaw)
            .maxOrNull()?.let { it * c.CHARGER_SCALE.toDouble() }
        val hvAmp = sumOrNull(cmmHvAmpRaw, cmsHvAmpRaw)?.let { it * c.CHARGER_SCALE.toDouble() }

        val thermal = mcmThermal
        val drivetrain = c.MCM_THERMAL_BYTES.map { idx ->
            thermal?.getOrNull(idx)?.let {
                (it.toInt() and 0xFF) + c.MCM_THERMAL_OFFSET_C.toDouble()
            }
        }

        val aux = voltage14vRaw * c.VOLTAGE_14V_SCALE * current14vRaw * c.CURRENT_14V_SCALE

        return SpecsState(
            cellVMinV = cellVMinMv?.let { it * c.CELL_MV_TO_V.toDouble() },
            cellVMaxV = cellVMaxMv?.let { it * c.CELL_MV_TO_V.toDouble() },
            cellVMinId = cellVMinId,
            cellVMaxId = cellVMaxId,
            cellTMinC = cellTMinRaw?.let { (it - c.TEMP_RAW_OFFSET).toDouble() },
            cellTMaxC = cellTMaxRaw?.let { (it - c.TEMP_RAW_OFFSET).toDouble() },
            packCurrentA = packCurrentRaw?.let {
                (it - c.PACK_CURRENT_ZERO) * c.PACK_CURRENT_SCALE.toDouble()
            },
            dischargeLimitA = dischargeLimitRaw?.let { it * c.LIMIT_AMPS_SCALE.toDouble() },
            chargeLimitA = chargeLimitRaw?.let { it * c.LIMIT_AMPS_SCALE.toDouble() },

            coldFault = bmsFaultB0 == c.COLD_FAULT_B0,

            acCompressorKw = compressorKwRaw?.let { it * c.POWER_KW_SCALE.toDouble() },
            acCompressorMaxKw = compressorMaxKwRaw?.let { it * c.POWER_KW_SCALE.toDouble() },
            ptcHeaterKw = (ptcPowerRaw * c.POWER_KW_SCALE).toDouble(),
            dcdcW = aux.toDouble(),

            motorTorqueNm = ((motorTorqueRaw - c.MOTOR_TORQUE_ZERO_RAW) *
                c.MOTOR_TORQUE_SCALE).toDouble(),
            drivetrainTempsC = drivetrain,

            isCharging = hvPowermode == c.HVPOWERMODE_CHARGE,
            chargeMode = chargeMode,
            acInputVoltage = acVolt,
            acInputCurrentA = acAmp,
            hvOutputVoltage = hvVolt,
            hvOutputCurrentA = hvAmp,
            evseMaxCurrentA = evseMaxAmpRaw?.let { it * c.EVSE_AMPS_SCALE.toDouble() },
            chargerTempsC = chargerTempRaw?.map { it * c.CHARGER_SCALE.toDouble() } ?: emptyList(),
        )
    }

    /** Sum of whichever charger modules have reported; null when neither has. */
    private fun sumOrNull(a: Int?, b: Int?): Int? =
        if (a == null && b == null) null else (a ?: 0) + (b ?: 0)

    // SignalDecoder bridge (for cancore generic interface)
    override fun snapshot(): Map<String, Float> {
        val s = buildState()
        return mapOf(
            "soc"     to s.socPercent,
            "exp_rng" to s.expRangeMiles,
            "max_rng" to s.maxRangeMiles,
            "torque"  to s.motorTorqueNm,
            "climate" to s.climatePowerKw,
            "aux_w"   to s.auxPowerW,
            "batt_t"  to s.battTempC,
        )
    }
}
