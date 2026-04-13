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
    val data: ByteArray      // always 8 bytes on the wire; only dlc bytes are valid
) {
    fun dataHex(): String = data.take(dlc).joinToString(" ") { "%02X".format(it) }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is CanFrame) return false
        return busIndex == other.busIndex && timestampMs == other.timestampMs &&
            id == other.id && dlc == other.dlc && data.contentEquals(other.data)
    }

    override fun hashCode(): Int {
        var result = busIndex
        result = 31 * result + id
        result = 31 * result + dlc
        result = 31 * result + data.contentHashCode()
        return result
    }
}
