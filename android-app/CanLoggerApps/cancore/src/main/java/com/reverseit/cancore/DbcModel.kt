package com.reverseit.cancore

/**
 * Typed in-memory DBC model.
 *
 * Only the subset used by the CAN Display Protocol v1 server is retained:
 * messages, signals (including multiplex annotations per protocol §8.5),
 * GenMsgCycleTime cycle hints, and message/signal comments. Value tables,
 * environment variables, signal groups, and other DBC features are parsed
 * and discarded.
 *
 * See android-app/notes/protocols/can-display-protocol.md §8 for the decode
 * operation set this model is designed to support.
 */
data class Dbc(
    val messages: Map<Int, DbcMessage>,
    val fileComment: String? = null,
)

data class DbcMessage(
    val frameId: Int,
    val name: String,
    val length: Int,
    val transmitter: String,
    val signals: List<DbcSignal>,
    val isExtended: Boolean,
    val cycleTimeMs: Int? = null,
    val comment: String? = null,
) {
    /** Signals indexed by name for O(1) lookup. */
    val signalsByName: Map<String, DbcSignal> by lazy { signals.associateBy { it.name } }

    /** The multiplexer signal, or null if this message is not multiplexed. */
    val multiplexer: DbcSignal? by lazy { signals.firstOrNull { it.mux is MuxRole.Multiplexer } }
}

data class DbcSignal(
    val name: String,
    val startBit: Int,
    val length: Int,
    val byteOrder: DbcByteOrder,
    val isSigned: Boolean,
    val scale: Double,
    val offset: Double,
    val min: Double,
    val max: Double,
    val unit: String,
    val mux: MuxRole = MuxRole.None,
    val comment: String? = null,
)

enum class DbcByteOrder { LITTLE_ENDIAN, BIG_ENDIAN }

sealed class MuxRole {
    object None : MuxRole()
    object Multiplexer : MuxRole()
    data class Group(val value: Int) : MuxRole()
}

/**
 * Thrown by DbcParser when the input is malformed or references an
 * unsupported DBC feature on a path that the protocol cannot route around.
 * The message names the feature and DBC location so callers can map it to a
 * protocol `dbc_parse_error` or `dbc_unsupported_feature` reply.
 */
class DbcParseException(message: String, cause: Throwable? = null) : RuntimeException(message, cause)
