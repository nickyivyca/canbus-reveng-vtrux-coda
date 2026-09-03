package com.reverseit.cancore

/**
 * Incremental reader for the LAWICEL/SLCAN ASCII stream the 914 VCU emits over its USB CDC
 * serial port.
 *
 * Fed arbitrary-sized chunks, because USB bulk reads land wherever they land. The reader holds
 * a partial token across [feed] calls, so the same stream split any way at all produces the
 * same frames -- which is the property that makes the USB path safe, and the one worth testing
 * before any of it runs on a phone.
 *
 * Wire format, from `Slcan.cpp` in the `914-control` firmware:
 *
 *   - `t` + 3 hex id + 1 hex dlc + 2 hex per data byte + CR   (standard, 11-bit)
 *   - `T` + 8 hex id + 1 hex dlc + 2 hex per data byte + CR   (extended, 29-bit)
 *   - `r` / `R` are the same without data (remote frames). The VCU never emits one; they exist
 *     on the host-to-bus path, so they are accepted rather than treated as damage.
 *   - Hex digits are emitted uppercase but parsed either way.
 *
 * Three things about this stream are not obvious and each one is a bug if missed:
 *
 * 1. **CSV records share the stream.** In dual-emit builds the firmware writes both
 *    representations of the same scan with no framing between them. Frames end CR; CSV records
 *    end LF, which the mbed console translates to CRLF. Treating CR and LF as independent
 *    terminators invents an empty token after every CSV record and reports it as a bare-CR
 *    acknowledgement that never happened -- so CRLF is absorbed as a single terminator.
 *
 * 2. **The integrity frame is excluded from its own block.** It reports the block before it and
 *    is written directly rather than through `slcan_emit()`, so it neither accumulates into the
 *    CRC nor counts towards the frame total. A reader that counts it is off by one on every
 *    block.
 *
 * 3. **The CRC covers the ASCII bytes as received, terminator included** -- not a
 *    re-serialisation of the parsed values. Re-encoding would mask exactly the corruption the
 *    CRC exists to find.
 *
 * The first block is never checked. A capture can begin mid-block, so its frame count and CRC
 * are incomplete through no fault of the reader.
 */
class SlcanReader(
    private val busIndex: Int = 0,
    private val clock: () -> Long = { System.currentTimeMillis() },
    private val onFrame: (CanFrame) -> Unit,
) {

    companion object {
        /** The VCU's integrity frame, on an extended id. */
        const val SEQ_ID = 0x1FFFFFFF

        /**
         * Longest legal token. A frame is at most 26 characters (`T` + 8 id + 1 dlc + 16 data);
         * CSV records in the dual-emit captures reach 1260. 4096 leaves headroom without letting
         * a stream that never terminates grow without bound.
         */
        const val MAX_TOKEN = 4096

        private const val FNV_OFFSET = -0x340d631b7bdddcdbL // 0xCBF29CE484222325
        private const val FNV_PRIME = 0x100000001B3L

        private fun hexVal(c: Int): Int = when (c) {
            in 0x30..0x39 -> c - 0x30          // 0-9
            in 0x41..0x46 -> c - 0x41 + 10     // A-F
            in 0x61..0x66 -> c - 0x61 + 10     // a-f
            else -> -1
        }
    }

    /** Running tallies. Read after feeding; not reset by [feed]. */
    class Stats {
        var frames = 0L           // data frames delivered, integrity frames excluded
        var integrity = 0L        // integrity frames seen
        var csv = 0L              // CSV records, from dual-emit builds
        var acks = 0L             // bare-CR acknowledgements
        var malformed = 0L        // tokens that are neither a well-formed frame nor CSV
        var oversize = 0L         // tokens discarded for exceeding MAX_TOKEN
        var blocksChecked = 0L    // blocks closed by an integrity frame, after the first
        var blocksCrcBad = 0L
        var blocksCountBad = 0L
    }

    val stats = Stats()

    private val token = ByteArray(MAX_TOKEN + 1)
    private var tokenLen = 0
    private var discarding = false

    private var crc = 0xFFFF
    private var blockCount = 0
    private var synced = false

    private var digestState = FNV_OFFSET

    /** FNV-1a 64 over every delivered frame in order. Compact stand-in for frame-by-frame diff. */
    val digest: Long get() = digestState

    @JvmOverloads
    fun feed(data: ByteArray, offset: Int = 0, length: Int = data.size - offset) {
        var i = offset
        val end = offset + length
        while (i < end) {
            val b = data[i].toInt() and 0xFF
            if (b == 0x0D || b == 0x0A) {
                // Absorb CRLF as one terminator -- see note 1 in the class doc.
                val step = if (b == 0x0D && i + 1 < end && data[i + 1].toInt() == 0x0A) 2 else 1
                if (discarding) {
                    discarding = false
                } else {
                    handleToken(step)
                }
                tokenLen = 0
                i += step
                continue
            }
            if (!discarding) {
                token[tokenLen++] = b.toByte()
                if (tokenLen > MAX_TOKEN) {
                    stats.oversize++
                    discarding = true
                    tokenLen = 0
                }
            }
            i++
        }
    }

    private fun handleToken(termLen: Int) {
        if (tokenLen == 0) {
            // Once CRLF is absorbed, only a lone CR yields an empty token.
            if (termLen == 1) stats.acks++
            return
        }
        val kind = token[0].toInt() and 0xFF
        val idLen = when (kind) {
            'T'.code, 'R'.code -> 8
            't'.code, 'r'.code -> 3
            else -> {
                classifyNonFrame()
                return
            }
        }
        val remote = kind == 'r'.code || kind == 'R'.code
        if (tokenLen < 1 + idLen + 1) {
            classifyNonFrame()
            return
        }

        var id = 0
        for (k in 1..idLen) {
            val v = hexVal(token[k].toInt() and 0xFF)
            if (v < 0) {
                classifyNonFrame()
                return
            }
            id = (id shl 4) or v
        }
        val dlc = hexVal(token[1 + idLen].toInt() and 0xFF)
        if (dlc < 0 || dlc > 8) {
            classifyNonFrame()
            return
        }

        val bodyLen = tokenLen - (2 + idLen)
        val expected = if (remote) 0 else dlc * 2
        if (bodyLen != expected) {
            classifyNonFrame()
            return
        }

        // CanFrame carries a full 8 bytes; only the first dlc are meaningful.
        val payload = ByteArray(8)
        var p = 2 + idLen
        for (k in 0 until (if (remote) 0 else dlc)) {
            val hi = hexVal(token[p].toInt() and 0xFF)
            val lo = hexVal(token[p + 1].toInt() and 0xFF)
            if (hi < 0 || lo < 0) {
                classifyNonFrame()
                return
            }
            payload[k] = ((hi shl 4) or lo).toByte()
            p += 2
        }

        val extended = idLen == 8
        if (extended && id == SEQ_ID) {
            handleIntegrity(payload)
            return
        }

        // CRC the bytes as received, terminator included -- see note 3.
        for (k in 0 until tokenLen) crcByte(token[k].toInt() and 0xFF)
        crcByte(0x0D)
        blockCount++

        stats.frames++
        // Remote frames carry no data, so the digest mixes dlc as a value but no bytes.
        mixDigest(id, extended, dlc, payload, if (remote) 0 else dlc)
        onFrame(CanFrame(busIndex, clock(), id, extended, dlc, payload))
    }

    /**
     * A token that is not a well-formed frame. Comma-bearing tokens are the interleaved CSV
     * records; anything else is damage. A corrupted frame can in principle carry a comma and be
     * miscounted as CSV, which is why the block frame count, not this tally, is what says a
     * frame went missing.
     */
    private fun classifyNonFrame() {
        for (k in 0 until tokenLen) {
            if (token[k].toInt() == ','.code) {
                stats.csv++
                return
            }
        }
        stats.malformed++
    }

    private fun handleIntegrity(payload: ByteArray) {
        stats.integrity++
        val declaredCount = (payload[2].toInt() and 0xFF) or ((payload[3].toInt() and 0xFF) shl 8)
        val declaredCrc = (payload[4].toInt() and 0xFF) or ((payload[5].toInt() and 0xFF) shl 8)
        if (synced) {
            stats.blocksChecked++
            if (declaredCrc != crc) stats.blocksCrcBad++
            if (declaredCount != blockCount) stats.blocksCountBad++
        }
        synced = true
        crc = 0xFFFF
        blockCount = 0
    }

    /** CCITT-FALSE, polynomial 0x1021, MSB first. Matches `crc_byte()` in `Slcan.cpp`. */
    private fun crcByte(b: Int) {
        crc = crc xor (b shl 8)
        repeat(8) {
            crc = if (crc and 0x8000 != 0) ((crc shl 1) xor 0x1021) and 0xFFFF
            else (crc shl 1) and 0xFFFF
        }
    }

    private fun mixDigest(id: Int, extended: Boolean, dlc: Int, payload: ByteArray, dataLen: Int) {
        var d = digestState
        d = (d xor ((id ushr 24) and 0xFF).toLong()) * FNV_PRIME
        d = (d xor ((id ushr 16) and 0xFF).toLong()) * FNV_PRIME
        d = (d xor ((id ushr 8) and 0xFF).toLong()) * FNV_PRIME
        d = (d xor (id and 0xFF).toLong()) * FNV_PRIME
        d = (d xor (if (extended) 1L else 0L)) * FNV_PRIME
        d = (d xor dlc.toLong()) * FNV_PRIME
        for (k in 0 until dataLen) {
            d = (d xor (payload[k].toLong() and 0xFF)) * FNV_PRIME
        }
        digestState = d
    }
}
