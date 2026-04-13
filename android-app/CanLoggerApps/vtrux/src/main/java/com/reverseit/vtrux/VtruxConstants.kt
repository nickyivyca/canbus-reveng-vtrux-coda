package com.reverseit.vtrux

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
}
