package com.reverseit.cancore

/**
 * A decoded CAN frame from any bus, tagged with the bus index assigned at session start.
 * busIndex is 0-based (bus 0 = first dongle connected, etc.) -- matches Python logger convention.
 */
data class CanFrame(
    val busIndex: Int,
    val timestampMs: Long,   // wall-clock ms at time of receipt
    val id: Int,             // arbitration ID (11 or 29 bit)
    val isExtended: Boolean,
    val dlc: Int,
    val data: ByteArray,     // always 8 bytes on the wire; only dlc bytes are valid
    /**
     * True for a frame *this app* put on the wire, false for one received from the vehicle.
     *
     * gs_usb echoes every transmitted frame back on the bulk IN endpoint, so without this flag an
     * injected frame is indistinguishable from a vehicle broadcast of the same ID. That is not a
     * cosmetic problem: [PeriodicTransmitter]'s contention guard suppresses a slot when another
     * node is seen transmitting the same ID, and it would suppress on its own echo forever.
     *
     * Defaulted so every existing construction site is unaffected. Round-trips through the
     * BUSMASTER `<Tx/Rx>` column, which `canre/parsers/busmaster.py` already reads into
     * `CANFrame.is_tx`.
     */
    val isTx: Boolean = false,
    /**
     * Monotonic receipt time (`System.nanoTime()`), for measuring intervals: log timestamps are
     * computed from this, not from [timestampMs]. The wall clock can step (the head unit syncs
     * its clock after boot) and has only millisecond resolution; this does neither.
     *
     * Excluded from [equals]/[hashCode]: it is when *this copy* was stamped, not part of the
     * frame's content. Defaulted so construction sites that do not care stay unchanged.
     */
    val elapsedNanos: Long = System.nanoTime(),
    /**
     * True for an error frame the adapter reported (see [GsUsbFrame.isError]), not a message from
     * the bus. [id] is then the SocketCAN error-class mask, which collides with real IDs `0x004`,
     * `0x00C` etc., so anything reading [id] as a message ID must skip these. [CanFrameSource.frames]
     * never carries them; only [CanFrameSource.logFrames] does, for the log writer.
     *
     * Defaulted so every existing construction site is unaffected.
     */
    val isError: Boolean = false,
) {
    fun dataHex(): String = data.take(dlc).joinToString(" ") { "%02X".format(it) }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is CanFrame) return false
        return busIndex == other.busIndex && timestampMs == other.timestampMs &&
            id == other.id && dlc == other.dlc && isTx == other.isTx &&
            isError == other.isError && data.contentEquals(other.data)
    }

    override fun hashCode(): Int {
        var result = busIndex
        result = 31 * result + id
        result = 31 * result + dlc
        result = 31 * result + data.contentHashCode()
        result = 31 * result + isTx.hashCode()
        result = 31 * result + isError.hashCode()
        return result
    }
}
