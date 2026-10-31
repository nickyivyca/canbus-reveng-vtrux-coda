package com.reverseit.cancore

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * A single CAN frame as encoded by the gs_usb protocol (20 bytes, little-endian).
 *
 * Wire layout:
 *   u32 echo_id      -- 0xFFFFFFFF for received frames
 *   u32 can_id       -- bit31=EFF, bit30=RTR, bit29=ERR, bits28:0=arbitration ID
 *                       (for an error frame, bits28:0 are the error-class mask)
 *   u8  can_dlc      -- data length code (0-8)
 *   u8  channel      -- CAN channel index (from device, not our busIndex)
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

    /**
     * True for an error frame the adapter generated, not a frame received from the bus. gs_usb
     * uses the SocketCAN layout (`linux/can/error.h`): [arbitrationId] is then the error-class
     * mask (`0x004` controller, `0x008` protocol, ...) and [data] carries the details -- `data[1]`
     * controller status, `data[2]` protocol error type, `data[6]`/`data[7]` the TX/RX error
     * counters. Until 2026-10-28 this bit was masked off and error frames were logged as standard
     * data frames `0x004` / `0x00C` (Bug 11).
     */
    val isError: Boolean get() = (rawCanId and CAN_ERR_FLAG) != 0

    /**
     * True when the device is echoing back a frame *this app* transmitted. gs_usb sets echo_id to
     * 0xFFFFFFFF for genuine received frames and returns the host-chosen cookie for its own
     * echoes, so this is the only thing separating our injection from a vehicle broadcast.
     *
     * **Matches our cookie exactly rather than "anything that isn't RX", because that is the
     * fail-safe direction on both consumers of this flag.** A frame marked TX is written to the log
     * with `Tx` in the direction column, and `tools/influx_upload.py` skips every TX frame -- so a
     * received frame misclassified as TX silently disappears from the InfluxDB corpus while the log
     * file still looks healthy. With an exact match, a frame bearing some unexpected echo_id is
     * kept as RX: the logger retains the data, and [PeriodicTransmitter]'s contention guard treats
     * it as a foreign transmitter and suppresses rather than transmits. Both wrong answers are
     * safe. Under "!= RX" the logger's wrong answer was silent data loss.
     */
    val isEcho: Boolean get() = echoId == ECHO_ID_TX

    fun toCanFrame(busIndex: Int, timestampMs: Long, elapsedNanos: Long = System.nanoTime()) = CanFrame(
        busIndex = busIndex,
        timestampMs = timestampMs,
        id = arbitrationId,
        isExtended = isExtended,
        dlc = dlc,
        data = data.copyOf(),
        isTx = isEcho,
        elapsedNanos = elapsedNanos,
        isError = isError,
    )

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

        /** can_id bit 29: an error frame (SocketCAN `CAN_ERR_FLAG`). */
        const val CAN_ERR_FLAG = 0x20000000

        /** gs_usb echo_id for a frame genuinely received from the bus (0xFFFFFFFF). */
        const val ECHO_ID_RX = -1

        /**
         * Cookie used on every frame this app transmits. gs_usb only requires that it differ from
         * [ECHO_ID_RX]; it is returned verbatim on the echo. A single constant is enough because
         * nothing here correlates individual echoes back to their send call -- the echo is used
         * only to mark the frame as ours.
         */
        const val ECHO_ID_TX = 0

        /**
         * Build a frame for transmission. `data` may be shorter than 8 bytes; the wire format is
         * fixed-length and the tail is zero-padded, with [dlc] carrying the real length.
         */
        fun forTransmit(
            id: Int,
            data: ByteArray,
            isExtended: Boolean = false,
            dlc: Int = data.size,
            channel: Int = 0,
        ): GsUsbFrame {
            require(dlc in 0..8) { "dlc out of range: $dlc" }
            require(data.size >= dlc) { "payload shorter than dlc: ${data.size} < $dlc" }
            val padded = ByteArray(8)
            data.copyInto(padded, endIndex = dlc)
            val rawId = (id and 0x1FFFFFFF) or if (isExtended) 0x80000000.toInt() else 0
            return GsUsbFrame(ECHO_ID_TX, rawId, dlc, channel, flags = 0, data = padded)
        }

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
