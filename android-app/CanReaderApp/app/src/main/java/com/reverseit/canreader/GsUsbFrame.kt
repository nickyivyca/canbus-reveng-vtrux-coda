package com.reverseit.canreader

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * A single CAN frame as encoded by the gs_usb protocol (20 bytes, little-endian).
 *
 * Wire layout:
 *   u32 echo_id      -- 0xFFFFFFFF for received frames
 *   u32 can_id       -- bit31=EFF, bit30=RTR, bits28:0=arbitration ID
 *   u8  can_dlc      -- data length code (0-8)
 *   u8  channel      -- CAN channel index
 *   u8  flags
 *   u8  reserved
 *   u8[8] data
 */
data class GsUsbFrame(
    val echoId: Int,
    val rawCanId: Int,
    val dlc: Int,
    val channel: Int,
    val flags: Int,
    val data: ByteArray
) {
    val arbitrationId: Int get() = rawCanId and 0x1FFFFFFF
    val isExtended: Boolean get() = (rawCanId and 0x80000000.toInt()) != 0
    val isRtr: Boolean get() = (rawCanId and 0x40000000) != 0

    fun dataHex(): String = data.take(dlc).joinToString(" ") { "%02X".format(it) }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is GsUsbFrame) return false
        return echoId == other.echoId && rawCanId == other.rawCanId &&
            dlc == other.dlc && channel == other.channel &&
            flags == other.flags && data.contentEquals(other.data)
    }

    override fun hashCode(): Int {
        var result = echoId
        result = 31 * result + rawCanId
        result = 31 * result + dlc
        result = 31 * result + data.contentHashCode()
        return result
    }

    companion object {
        const val FRAME_SIZE = 20

        fun fromBytes(buf: ByteArray): GsUsbFrame {
            val bb = ByteBuffer.wrap(buf).order(ByteOrder.LITTLE_ENDIAN)
            val echoId = bb.int
            val rawCanId = bb.int
            val dlc = bb.get().toInt() and 0xFF
            val channel = bb.get().toInt() and 0xFF
            val flags = bb.get().toInt() and 0xFF
            bb.get() // reserved
            val data = ByteArray(8)
            bb.get(data)
            return GsUsbFrame(echoId, rawCanId, dlc, channel, flags, data)
        }

        fun toBytes(frame: GsUsbFrame): ByteArray {
            val bb = ByteBuffer.allocate(FRAME_SIZE).order(ByteOrder.LITTLE_ENDIAN)
            bb.putInt(frame.echoId)
            bb.putInt(frame.rawCanId)
            bb.put(frame.dlc.toByte())
            bb.put(frame.channel.toByte())
            bb.put(frame.flags.toByte())
            bb.put(0) // reserved
            bb.put(frame.data)
            return bb.array()
        }
    }
}
