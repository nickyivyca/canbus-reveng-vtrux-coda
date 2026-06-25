package com.reverseit.cancore

/**
 * Pure decode of CAN frame bytes against a [DbcMessage]. Implements the
 * decode operation set from CAN Display Protocol v1 §8 exactly, including
 * §8.5 multiplex handling: the multiplexer signal is decoded first and
 * signals belonging to other mux groups are omitted from the result.
 *
 * Cross-tested against `cantools.database.decode_message()` via the
 * `DbcParityTest` harness. Any divergence between this decoder and cantools
 * on a non-multiplexed message indicates a bug in this file (or, in
 * principle, in the protocol §8 spec -- but the spec was written to match
 * cantools, so the cantools result is the ground truth).
 */
object DbcDecoder {

    /**
     * Decode a frame's [data] against [message]. Returns a map from signal
     * name to physical value. For multiplexed messages, only signals in the
     * mux group matching the decoded multiplexer value are included.
     */
    fun decode(message: DbcMessage, data: ByteArray): Map<String, Double> {
        if (data.size < message.length) {
            throw IllegalArgumentException(
                "frame ${message.name} requires ${message.length} bytes, got ${data.size}"
            )
        }

        val out = LinkedHashMap<String, Double>()
        val muxer = message.multiplexer
        val activeMux: Int? = muxer?.let { decodeOne(it, data).toInt() }

        for (signal in message.signals) {
            val include = when (val role = signal.mux) {
                MuxRole.None -> true
                MuxRole.Multiplexer -> true
                is MuxRole.Group -> activeMux == role.value
            }
            if (!include) continue
            out[signal.name] = decodeOne(signal, data)
        }
        return out
    }

    /** Decode a single signal to its physical value. Public for tests. */
    fun decodeOne(signal: DbcSignal, data: ByteArray): Double {
        val raw = extractBits(signal, data)
        val numeric: Double = if (signal.isSigned) {
            applyTwosComplement(raw, signal.length).toDouble()
        } else {
            // For lengths < 64 the extracted Long is already in [0, 2^length-1].
            // For length == 64, the high bit may be set, which makes the Long
            // value negative under signed interpretation; route through ULong
            // so the double comes out positive in [0, 2^64).
            if (signal.length == 64) raw.toULong().toDouble() else raw.toDouble()
        }
        return numeric * signal.scale + signal.offset
    }

    /** Extract the unsigned integer value from the bit field. */
    private fun extractBits(signal: DbcSignal, data: ByteArray): Long {
        return when (signal.byteOrder) {
            DbcByteOrder.LITTLE_ENDIAN -> extractIntel(signal, data)
            DbcByteOrder.BIG_ENDIAN -> extractMotorola(signal, data)
        }
    }

    /**
     * Intel (little-endian) extraction:
     *   raw_u64 = byte[0] | (byte[1] << 8) | ... | (byte[7] << 56)
     *   value   = (raw_u64 >> start_bit) & ((1 << length) - 1)
     * Protocol §8.1.
     */
    private fun extractIntel(signal: DbcSignal, data: ByteArray): Long {
        // Build the LE 64-bit word from whatever bytes are present (data may be
        // shorter than 8; missing bytes are zero).
        var raw = 0L
        val byteCount = minOf(data.size, 8)
        for (i in 0 until byteCount) {
            raw = raw or ((data[i].toLong() and 0xFFL) shl (i * 8))
        }
        val mask = if (signal.length == 64) -1L else (1L shl signal.length) - 1L
        return (raw ushr signal.startBit) and mask
    }

    /**
     * Motorola (big-endian) extraction. Mirrors cantools and protocol §8.1.
     * Starts at [startBit] (MSB of the signal in DBC "Big-Endian" bit
     * numbering), walks bits towards bit 0 of the current byte, then jumps
     * to bit 7 of the next byte.
     */
    private fun extractMotorola(signal: DbcSignal, data: ByteArray): Long {
        var bitPos = signal.startBit
        var result = 0L
        for (i in 0 until signal.length) {
            val byteIdx = bitPos ushr 3
            val bitInByte = bitPos and 7
            val bit = ((data[byteIdx].toInt() ushr bitInByte) and 1).toLong()
            result = result or (bit shl (signal.length - 1 - i))
            bitPos = if (bitInByte == 0) bitPos + 15 else bitPos - 1
        }
        return result
    }

    private fun applyTwosComplement(value: Long, length: Int): Long {
        if (length == 0 || length > 64) return value
        val signBit = 1L shl (length - 1)
        if ((value and signBit) == 0L) return value
        val mask = if (length == 64) -1L else (1L shl length) - 1L
        return value - (mask + 1L)
    }
}
