package com.reverseit.tpms

/**
 * Implemented by the host app's `Application`, so [GpsSpeedService] -- which Android constructs,
 * not the app -- can reach the one [GpsRateAccumulator] the rest of the TPMS code feeds.
 */
interface TpmsHost {
    val gps: GpsRateAccumulator
}
