package com.reverseit.p914

/**
 * Compares the schema the VCU broadcasts against the schema the loaded DBC was generated from.
 *
 * Both halves of the comparison come from the firmware repo's `generate_914_dbc.py`: it writes
 * `SCHEMA_HASH` into `src/schema_id.h`, which is compiled into the VCU and broadcast on
 * `SchemaId` (0x1FFFFFFE), and it stamps the same value into the DBC's `CM_` file comment. So a
 * mismatch means the two artefacts came from different runs of the generator -- in practice, a
 * DBC copy that was not regenerated alongside the firmware.
 *
 * The policy is not invented here. It is stated in the `SchemaId` message comment in the DBC
 * itself and this only implements it:
 *
 *   > hash equal, proceed; hash differs but major equal, additive change, keep decoding known
 *   > signals and log once; major differs, stop and quarantine, because decoding with the wrong
 *   > major yields plausible wrong numbers rather than an error.
 *
 * Pure and Android-free, so the table of cases is exercisable as a plain JVM unit test rather
 * than only by plugging a car in.
 */
object SchemaCheck {

    /** How long a missing beacon is treated as "too early to say" rather than "absent". */
    const val BEACON_GRACE_MS = 10_000L

    /** `914 EV telemetry schema 3.0, SCHEMA_HASH=0x489360E3. ...` */
    private val STAMP_REGEX = Regex(
        """schema\s+(\d+)\.(\d+),\s*SCHEMA_HASH=0x([0-9A-Fa-f]{8})""",
        RegexOption.IGNORE_CASE,
    )

    /** What the loaded DBC says it was generated from. */
    data class Stamp(val major: Int, val minor: Int, val hash: Long)

    /** What the VCU says it is running. */
    data class Broadcast(val major: Int, val minor: Int, val hash: Long)

    sealed class Verdict {
        /**
         * The DBC carries no `SCHEMA_HASH=` stamp, so there is nothing to compare against. A build
         * problem, not a car problem -- and deliberately distinct from [NeverSeen], which is the
         * mirror-image failure. Confusing the two sends the reader to the wrong repo.
         */
        object DbcUnstamped : Verdict()

        /** No beacon yet, but not long enough to mean anything. Every plug-in passes through here. */
        object NotYetSeen : Verdict()

        /** No beacon for [BEACON_GRACE_MS]. Ten missed beacons is information. */
        object NeverSeen : Verdict()

        data class Match(val major: Int, val minor: Int) : Verdict()

        /** Additive change. Known signals still decode correctly. */
        data class MinorDiffers(val expected: Stamp, val observed: Broadcast) : Verdict()

        /** Wrong major. Decoding would yield plausible wrong numbers, so it must not happen. */
        data class Quarantine(val expected: Stamp, val observed: Broadcast) : Verdict()
    }

    /**
     * Pull the stamp out of a DBC's `CM_ "..."` file comment.
     *
     * Takes the already-parsed comment rather than the DBC text, so this agrees with
     * `DbcParser` by construction instead of by a second regex that could drift from it.
     */
    fun parseStamp(fileComment: String?): Stamp? {
        val m = STAMP_REGEX.find(fileComment ?: return null) ?: return null
        return Stamp(
            major = m.groupValues[1].toInt(),
            minor = m.groupValues[2].toInt(),
            // Unsigned 32-bit: 0xFFFFFFFF overflows Int, so parse as Long throughout.
            hash = m.groupValues[3].toLong(16),
        )
    }

    /**
     * Read a broadcast out of the flat signal map, or null if the beacon has not arrived.
     *
     * All three signals ride in one frame, so they cannot be partially present in a decoded
     * frame -- but the map merges across subscriptions, so requiring all three is still the
     * honest test.
     */
    fun readBroadcast(signals: Map<String, Double>): Broadcast? {
        val major = signals["SchemaMajor"] ?: return null
        val minor = signals["SchemaMinor"] ?: return null
        val hash = signals["SchemaHash"] ?: return null
        return Broadcast(major.toInt(), minor.toInt(), hash.toLong())
    }

    fun evaluate(stamp: Stamp?, observed: Broadcast?, elapsedMs: Long): Verdict {
        if (stamp == null) return Verdict.DbcUnstamped
        if (observed == null) {
            return if (elapsedMs < BEACON_GRACE_MS) Verdict.NotYetSeen else Verdict.NeverSeen
        }
        // Hash first, then major -- the DBC's rules are written in that order and a matching hash
        // settles the question outright. A differing major with a matching hash is not reachable
        // (the major is one of the inputs to the digest) but if it ever were, the hash is the
        // stronger evidence.
        if (observed.hash == stamp.hash) return Verdict.Match(observed.major, observed.minor)
        if (observed.major != stamp.major) return Verdict.Quarantine(stamp, observed)
        return Verdict.MinorDiffers(stamp, observed)
    }

    /** Short text for the integrity band. */
    fun bandText(v: Verdict): String = when (v) {
        is Verdict.DbcUnstamped -> "DBC UNSTAMPED"
        is Verdict.NotYetSeen -> "SCHEMA ?"
        is Verdict.NeverSeen -> "SCHEMA UNKNOWN"
        is Verdict.Match -> "SCHEMA ${v.major}.${v.minor} ok"
        is Verdict.MinorDiffers -> "SCHEMA ${v.observed.major}.${v.observed.minor} +"
        is Verdict.Quarantine -> "SCHEMA ${v.observed.major}.${v.observed.minor} QUARANTINE"
    }

    /** One line explaining a non-nominal verdict, for the blanked region and for logcat. */
    fun detail(v: Verdict): String = when (v) {
        is Verdict.DbcUnstamped ->
            "The bundled vcu.dbc carries no SCHEMA_HASH= stamp, so the broadcast cannot be " +
                "checked. Regenerate it with generate_914_dbc.py."
        is Verdict.NotYetSeen -> "Waiting for the 1 Hz SchemaId beacon."
        is Verdict.NeverSeen ->
            "No SchemaId beacon in ${BEACON_GRACE_MS / 1000} s. Either the VCU predates the " +
                "schema broadcast or SLCAN_MODE is off. The loaded DBC is unverifiable."
        is Verdict.Match -> "Schema matches the bundled DBC."
        is Verdict.MinorDiffers ->
            "VCU is on %d.%d (hash 0x%08X); the bundled DBC is %d.%d (hash 0x%08X). Same major, "
                .format(
                    v.observed.major, v.observed.minor, v.observed.hash,
                    v.expected.major, v.expected.minor, v.expected.hash,
                ) + "so this is an additive change and known signals still decode correctly."
        is Verdict.Quarantine ->
            ("VCU is on schema %d.%d (hash 0x%08X); the bundled DBC is %d.%d (hash 0x%08X). " +
                "The major version differs, so decoding would produce plausible wrong numbers " +
                "rather than an error. Regenerate vcu.dbc from the firmware that is on the car.")
                .format(
                    v.observed.major, v.observed.minor, v.observed.hash,
                    v.expected.major, v.expected.minor, v.expected.hash,
                )
    }
}
