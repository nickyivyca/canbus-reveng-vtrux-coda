package com.reverseit.p914

import com.reverseit.cancore.BusIdentity

object P914Constants {
    const val VEHICLE_NAME = "p914"

    /**
     * One bus, named `vcu`. The single serial link carries both real 11-bit vehicle traffic and
     * synthetic 29-bit VCU telemetry, but `isExtended` already distinguishes those losslessly, so
     * a second bus name would encode twice what the frame already says.
     *
     * Anchored on the VCU's own telemetry rather than the inverter's 0x001-0x004, because the
     * VCU's frames are the only traffic guaranteed present. The inverter frames stop whenever HV
     * is down -- which is the state of every bench session and most of the flashing workflow --
     * so anchoring there would leave the display refusing to resolve a bus that is plainly alive.
     *
     * Wire ids, with the DBC's 0x80000000 extended marker stripped: `CanFrame.id` never carries
     * it. `BusIdentityResolver` needs `min(3, anchorIds.size)` anchor hits, so three frames from
     * BmsStatus alone settle it inside half a second.
     */
    val BUS_IDENTITIES: List<BusIdentity> = listOf(
        BusIdentity(
            name = "vcu",
            anchorIds = setOf(
                0x1F000000, // BmsStatus
                0x1F000001, // BmsPack
                0x1F000002, // BmsCellSummary
                0x1FFFFFFE, // SchemaId
            ),
        ),
    )

    /**
     * The vehicle CAN bus the VCU relays. Only used for the BUSMASTER log header -- the SLCAN
     * stream itself is already decoded frames, so no bitrate is applied to anything.
     */
    const val BITRATE_KBPS = 500

    /**
     * Replay bridge reached over `adb reverse tcp:9000 tcp:9000`, so the phone dials its own
     * loopback and lands on the laptop running `tools/slcan_bridge.py`.
     */
    const val BRIDGE_HOST = "127.0.0.1"
    const val BRIDGE_PORT = 9000

    /**
     * Logs go to the app-private external directory, which needs no storage permission at all --
     * the system grants the owning app full access. `:vtrux` uses a public `/sdcard` path so
     * other apps can sync it, which costs it MANAGE_EXTERNAL_STORAGE; that trade is not worth
     * making before the transport is proven, so EXTRA_LOG_DIR is deliberately not set and
     * CanLoggingService falls back to `getExternalFilesDir(null)/P914Logs/`.
     *
     * Pull with:
     *   adb pull /sdcard/Android/data/com.reverseit.p914/files/P914Logs/
     */
    val LOG_DIR_OVERRIDE: String? = null
}
