package com.reverseit.cancore

import java.io.File

/**
 * Parses BUSMASTER-format log lines back into [CanFrame]s.
 *
 * Inverse of [BusmasterWriter], so any log this project has captured -- from the
 * Python `can_logger.py` or from `CanLoggingService` -- can be replayed directly
 * without a conversion step on the PC.
 *
 * Line format (see BusmasterWriter.writeFrame):
 *
 *     HH:MM:SS:TTTT Rx <channel> 0x<ID> <s|x> <dlc> <B0> <B1> ...
 *
 * where TTTT is 10 kHz ticks (0.1 ms), NOT milliseconds, and <channel> is
 * 1-based while [CanFrame.busIndex] is 0-based.
 *
 * Header/footer lines (`***...***`) and blanks return null rather than throwing:
 * a replay should tolerate a truncated or hand-edited log. So do error-frame lines
 * (type `ERR`) and any other type but `s`/`x`.
 */
object BusmasterReader {

    /** Relative offset of a parsed frame, in ms from the start of the session. */
    data class Parsed(val relativeMs: Long, val frame: CanFrame)

    /**
     * Parse one log line. Returns null for headers, blanks, and anything that
     * does not match the frame layout.
     *
     * [timestampMs] is stamped onto the resulting [CanFrame]; callers replaying
     * in real time should pass their own wall-clock value rather than the
     * session-relative one.
     */
    fun parseLine(line: String, timestampMs: Long = 0L): Parsed? {
        val trimmed = line.trim()
        if (trimmed.isEmpty() || trimmed.startsWith("***")) return null

        val parts = trimmed.split(Regex("\\s+"))
        // time, dir, channel, id, type, dlc  == 6 fields before any data byte
        if (parts.size < 6) return null

        val relativeMs = parseTimestampMs(parts[0]) ?: return null

        // parts[1] is Rx/Tx -- both are replayed; direction is not modelled on CanFrame.
        val channel = parts[2].toIntOrNull() ?: return null
        val idText = parts[3]
        val id = if (idText.startsWith("0x") || idText.startsWith("0X")) {
            idText.substring(2).toIntOrNull(16)
        } else {
            idText.toIntOrNull(16)
        } ?: return null

        // Only data frames are replayed. Anything else -- an `ERR` error-frame line above all --
        // is skipped: its ID column is an error-class mask, and reading it as a standard frame
        // would replay the adapter's error report as message 0x004 / 0x00C (Bug 11 in reverse).
        val type = parts[4]
        if (!type.equals("s", ignoreCase = true) && !type.equals("x", ignoreCase = true)) return null
        val isExtended = type.equals("x", ignoreCase = true)
        val dlc = parts[5].toIntOrNull() ?: return null
        if (dlc !in 0..8) return null

        // The wire always carries 8 bytes; only dlc of them are meaningful.
        val data = ByteArray(8)
        val available = minOf(dlc, parts.size - 6)
        for (i in 0 until available) {
            val b = parts[6 + i].toIntOrNull(16) ?: return null
            data[i] = b.toByte()
        }

        return Parsed(
            relativeMs = relativeMs,
            frame = CanFrame(
                busIndex = (channel - 1).coerceAtLeast(0),
                timestampMs = timestampMs,
                id = id,
                isExtended = isExtended,
                dlc = dlc,
                data = data,
            ),
        )
    }

    /**
     * `HH:MM:SS:TTTT` -> milliseconds. TTTT is 10 kHz ticks (0.1 ms), so it is
     * divided by 10 to reach ms -- treating it as milliseconds directly is the
     * classic mistake with this format and yields timings 10x too long.
     */
    private fun parseTimestampMs(field: String): Long? {
        val p = field.split(":")
        if (p.size != 4) return null
        val h = p[0].toLongOrNull() ?: return null
        val m = p[1].toLongOrNull() ?: return null
        val s = p[2].toLongOrNull() ?: return null
        val ticks = p[3].toLongOrNull() ?: return null
        return ((h * 3600 + m * 60 + s) * 1000) + (ticks / 10)
    }

    /**
     * Scan the head of a log and report which CAN IDs appear on each bus.
     * Used to pick the bus of interest by content rather than by channel number
     * -- channel numbers depend on dongle insertion order and are not stable
     * across capture sessions.
     */
    fun surveyBuses(file: File, maxLines: Int = 200_000): Map<Int, Set<Int>> {
        val result = mutableMapOf<Int, MutableSet<Int>>()
        var n = 0
        file.bufferedReader().use { r ->
            while (n < maxLines) {
                val line = r.readLine() ?: break
                n++
                val p = parseLine(line) ?: continue
                result.getOrPut(p.frame.busIndex) { mutableSetOf() }.add(p.frame.id)
            }
        }
        return result
    }

    /**
     * Pick the bus carrying the most of [anchorIds]. Returns null when the log
     * has no buses, or when no bus contains any anchor (in which case the caller
     * should replay every bus rather than guess).
     */
    fun selectBusByAnchors(buses: Map<Int, Set<Int>>, anchorIds: Set<Int>): Int? {
        if (buses.isEmpty() || anchorIds.isEmpty()) return null
        val best = buses.maxByOrNull { (_, ids) -> ids.count { it in anchorIds } } ?: return null
        val hits = best.value.count { it in anchorIds }
        return if (hits > 0) best.key else null
    }
}
