package com.reverseit.cancore

/**
 * Pure-Kotlin DBC text parser. Produces a [Dbc] suitable for use with
 * [DbcDecoder]. Tolerates DBC sections that are not part of the supported
 * subset (value tables, environment variables, signal groups, attributes
 * other than GenMsgCycleTime) by silently skipping them.
 *
 * Supported directives:
 *   BO_   -- message definition
 *   SG_   -- signal definition, including M and m<N> multiplex annotations
 *   CM_   -- message and signal comments (free text; not interpreted)
 *   BA_   -- attribute values; only `"GenMsgCycleTime"` is captured
 *
 * Anything else (`VAL_`, `BA_DEF_`, `EV_`, `NS_`, etc.) is parsed as best-
 * effort and discarded. Malformed lines within a supported directive throw
 * [DbcParseException].
 */
object DbcParser {

    private val BO_REGEX = Regex(
        """BO_\s+(\d+)\s+(\S+)\s*:\s*(\d+)\s+(\S+)"""
    )
    private val SG_REGEX = Regex(
        """\s*SG_\s+(\S+)\s*(M|m\d+)?\s*:\s*(\d+)\|(\d+)@(\d+)([+-])\s*\(\s*([-+\deE.]+)\s*,\s*([-+\deE.]+)\s*\)\s*\[\s*([-+\deE.]+)\|([-+\deE.]+)\s*\]\s*"([^"]*)"\s*(.*)"""
    )
    private val CM_BO_REGEX = Regex("""CM_\s+BO_\s+(\d+)\s+"((?:[^"\\]|\\.)*)"\s*;""", RegexOption.DOT_MATCHES_ALL)
    private val CM_SG_REGEX = Regex("""CM_\s+SG_\s+(\d+)\s+(\S+)\s+"((?:[^"\\]|\\.)*)"\s*;""", RegexOption.DOT_MATCHES_ALL)
    private val CM_FILE_REGEX = Regex("""CM_\s+"((?:[^"\\]|\\.)*)"\s*;""", RegexOption.DOT_MATCHES_ALL)
    private val BA_CYCLE_REGEX = Regex("""BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+)\s*;""")

    /** DBC extended-ID marker bit. See DBC spec; cantools strips this when
     *  exposing `Message.frame_id`, so we match that behaviour. */
    private const val EXTENDED_ID_MARKER: Long = 0x80000000L

    fun parse(text: String): Dbc {
        val joinedLines = joinContinuations(text)

        val rawMessages = mutableMapOf<Int, MutableMessage>()
        val cycleTimes = mutableMapOf<Int, Int>()
        val messageComments = mutableMapOf<Int, String>()
        val signalComments = mutableMapOf<Pair<Int, String>, String>()
        var fileComment: String? = null

        var current: MutableMessage? = null

        for ((idx, rawLine) in joinedLines.withIndex()) {
            val line = rawLine.trimEnd()
            if (line.isBlank()) {
                current = null
                continue
            }

            // SG_ lines belong to the most recent BO_. The DBC NS_ block
            // contains other tokens that begin with "SG_" (e.g. SG_MUL_VAL_,
            // SGTYPE_); require "SG_" to be followed by whitespace and an
            // identifier character to qualify as a signal definition.
            val trimmed = line.trimStart(' ', '\t')
            if (trimmed.length >= 4 && trimmed.startsWith("SG_") &&
                (trimmed[3] == ' ' || trimmed[3] == '\t')
            ) {
                val msg = current
                    ?: throw DbcParseException("SG_ outside of any BO_ at line ${idx + 1}: $line")
                msg.signals += parseSignal(line, idx + 1)
                continue
            }

            when {
                line.startsWith("BO_") -> {
                    current = parseMessageHeader(line, idx + 1)
                    if (current.frameId in rawMessages) {
                        throw DbcParseException("duplicate BO_ for frame id ${current.frameId} (${current.name}) at line ${idx + 1}")
                    }
                    rawMessages[current.frameId] = current
                }
                line.startsWith("CM_ BO_") -> {
                    CM_BO_REGEX.matchEntire(line)?.let { m ->
                        val id = canonicalId(m.groupValues[1].toLong())
                        messageComments[id] = unescape(m.groupValues[2])
                    }
                }
                line.startsWith("CM_ SG_") -> {
                    CM_SG_REGEX.matchEntire(line)?.let { m ->
                        val id = canonicalId(m.groupValues[1].toLong())
                        signalComments[id to m.groupValues[2]] = unescape(m.groupValues[3])
                    }
                }
                line.startsWith("CM_ \"") -> {
                    CM_FILE_REGEX.matchEntire(line)?.let { m ->
                        fileComment = unescape(m.groupValues[1])
                    }
                }
                line.startsWith("BA_ \"GenMsgCycleTime\"") -> {
                    BA_CYCLE_REGEX.matchEntire(line)?.let { m ->
                        val id = canonicalId(m.groupValues[1].toLong())
                        cycleTimes[id] = m.groupValues[2].toInt()
                    }
                }
                line.startsWith("BO_TX_BU_") -> current = null
                else -> {
                    // Tolerate unsupported sections (VAL_, BA_DEF_, NS_ block, etc.).
                    // Reset current message context if we leave the BO_/SG_ block.
                    if (!line.startsWith(" ") && !line.startsWith("\t")) current = null
                }
            }
        }

        val messages = rawMessages.mapValues { (id, m) ->
            DbcMessage(
                frameId = id,
                name = m.name,
                length = m.length,
                transmitter = m.transmitter,
                signals = m.signals.map { s ->
                    s.copy(comment = signalComments[id to s.name])
                },
                isExtended = m.isExtended,
                cycleTimeMs = cycleTimes[id],
                comment = messageComments[id],
            )
        }
        return Dbc(messages = messages, fileComment = fileComment)
    }

    // --- parsing helpers --------------------------------------------------

    private data class MutableMessage(
        val frameId: Int,
        val name: String,
        val length: Int,
        val transmitter: String,
        val isExtended: Boolean,
        val signals: MutableList<DbcSignal> = mutableListOf(),
    )

    private fun parseMessageHeader(line: String, lineNo: Int): MutableMessage {
        val m = BO_REGEX.find(line)
            ?: throw DbcParseException("malformed BO_ at line $lineNo: $line")
        val rawId = m.groupValues[1].toLong()
        val name = m.groupValues[2]
        val length = m.groupValues[3].toInt()
        val transmitter = m.groupValues[4]
        val isExtended = (rawId and EXTENDED_ID_MARKER) != 0L
        val id = canonicalId(rawId)
        return MutableMessage(id, name, length, transmitter, isExtended)
    }

    private fun parseSignal(line: String, lineNo: Int): DbcSignal {
        val m = SG_REGEX.matchEntire(line.trimStart())
            ?: throw DbcParseException("malformed SG_ at line $lineNo: $line")
        val name = m.groupValues[1]
        val muxToken = m.groupValues[2]
        val startBit = m.groupValues[3].toInt()
        val length = m.groupValues[4].toInt()
        val byteOrderRaw = m.groupValues[5].toInt()
        val sign = m.groupValues[6]
        val scale = m.groupValues[7].toDouble()
        val offset = m.groupValues[8].toDouble()
        val min = m.groupValues[9].toDouble()
        val max = m.groupValues[10].toDouble()
        val unit = m.groupValues[11]

        val mux = when {
            muxToken == "M" -> MuxRole.Multiplexer
            muxToken.startsWith("m") -> MuxRole.Group(muxToken.substring(1).toInt())
            else -> MuxRole.None
        }

        return DbcSignal(
            name = name,
            startBit = startBit,
            length = length,
            byteOrder = if (byteOrderRaw == 1) DbcByteOrder.LITTLE_ENDIAN else DbcByteOrder.BIG_ENDIAN,
            isSigned = sign == "-",
            scale = scale,
            offset = offset,
            min = min,
            max = max,
            unit = unit,
            mux = mux,
        )
    }

    /** Multi-line CM_ entries are continued with a line break inside the
     *  quoted string. Join them so the regexes see one logical line. */
    private fun joinContinuations(text: String): List<String> {
        val out = mutableListOf<String>()
        var buf = StringBuilder()
        var insideQuoted = false
        for (line in text.lineSequence()) {
            if (insideQuoted) {
                buf.append('\n').append(line)
                if (countUnescapedQuotes(line) % 2 == 1) {
                    insideQuoted = false
                    out += buf.toString()
                    buf = StringBuilder()
                }
            } else {
                val q = countUnescapedQuotes(line)
                if (q % 2 == 1) {
                    insideQuoted = true
                    buf.append(line)
                } else {
                    out += line
                }
            }
        }
        if (buf.isNotEmpty()) out += buf.toString()
        return out
    }

    private fun countUnescapedQuotes(s: String): Int {
        var count = 0
        var i = 0
        while (i < s.length) {
            val c = s[i]
            if (c == '\\' && i + 1 < s.length) {
                i += 2
                continue
            }
            if (c == '"') count++
            i++
        }
        return count
    }

    private fun unescape(s: String): String =
        s.replace("\\\"", "\"").replace("\\\\", "\\")

    private fun canonicalId(raw: Long): Int = (raw and EXTENDED_ID_MARKER.inv()).toInt()
}
