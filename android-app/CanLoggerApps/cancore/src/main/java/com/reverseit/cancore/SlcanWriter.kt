package com.reverseit.cancore

/**
 * Encodes frames as LAWICEL/SLCAN lines -- the inverse of [SlcanReader], in the form it parses:
 * `t` + 3 hex id + dlc + 2 hex per byte + CR for 11-bit ids, `T` + 8 hex id for 29-bit ones,
 * uppercase hex.
 *
 * Used by [SlcanBusGroup] to send a transmitted frame back up its stream, where the replay bridge
 * records it. The same text `tools/slcan_bridge.py` writes in the other direction, so a frame
 * survives a trip either way unchanged.
 */
object SlcanWriter {

    private val HEX = "0123456789ABCDEF".toByteArray(Charsets.US_ASCII)

    /**
     * One frame as an SLCAN line, CR included. [dlc] bytes of [data] are written.
     *
     * @throws IllegalArgumentException for an id that does not fit its format or a dlc outside
     *   0..8 -- both are caller bugs, and silently masking them would put a different frame on the
     *   stream than the one asked for.
     */
    fun encode(id: Int, data: ByteArray, isExtended: Boolean = false, dlc: Int = data.size): ByteArray {
        require(dlc in 0..8 && dlc <= data.size) { "dlc $dlc invalid for ${data.size} data bytes" }
        val idDigits = if (isExtended) 8 else 3
        require(if (isExtended) id in 0..0x1FFFFFFF else id in 0..0x7FF) {
            "id 0x%X does not fit a %s frame".format(id, if (isExtended) "29-bit" else "11-bit")
        }
        val out = ByteArray(1 + idDigits + 1 + dlc * 2 + 1)
        var p = 0
        out[p++] = (if (isExtended) 'T' else 't').code.toByte()
        for (shift in (idDigits - 1) downTo 0) out[p++] = HEX[(id ushr (shift * 4)) and 0xF]
        out[p++] = HEX[dlc]
        for (k in 0 until dlc) {
            val b = data[k].toInt() and 0xFF
            out[p++] = HEX[b ushr 4]
            out[p++] = HEX[b and 0xF]
        }
        out[p] = 0x0D
        return out
    }
}
