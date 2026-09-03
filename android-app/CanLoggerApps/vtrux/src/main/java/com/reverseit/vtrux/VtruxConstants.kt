package com.reverseit.vtrux

import com.reverseit.cancore.BusIdentity

object VtruxConstants {
    const val VEHICLE_NAME   = "vtrux"
    const val BITRATE_KBPS   = 500

    /**
     * Absolute path on the SD card for log files.
     * Public storage (not app-specific) so files are accessible to other apps
     * (e.g. file managers, Seafile sync) without root or special tools.
     * Requires MANAGE_EXTERNAL_STORAGE on Android 11+ (declared in :cancore manifest).
     */
    const val LOG_DIR = "/sdcard/VtruxLogs"

    /**
     * Bus-identification anchor IDs, taken from `projects/vtrux/README.md`.
     * The same set the Python test server uses
     * (`tools/can_display_bus_identity_vtrux.json`) -- keep in sync.
     *
     * Physical CAN dongle insertion order is arbitrary, so the logger
     * identifies each bus by which anchor IDs it carries rather than by
     * channel number.
     */
    val BUS_IDENTITIES: List<BusIdentity> = listOf(
        BusIdentity(
            name = "powertrain",
            anchorIds = (setOf(0x051) + (0x592..0x5A2).toSet() + (0x639..0x64B).toSet()),
        ),
        BusIdentity(
            name = "vehicle",
            anchorIds = setOf(0x1E5, 0x500, 0x514, 0x778, 0x780, 0x785, 0x788) +
                (0x52A..0x530).toSet(),
        ),
        BusIdentity(
            name = "obd",
            anchorIds = (0x040..0x044).toSet(),
        ),
    )
}
