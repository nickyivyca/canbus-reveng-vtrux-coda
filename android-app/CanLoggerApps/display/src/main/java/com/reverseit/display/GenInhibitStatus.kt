package com.reverseit.display

/**
 * Whether the Vtrux generator inhibitor is inhibiting, read from its `0x7F1`
 * WICAN_Diag_Status page. The live display shows EVAP `INHIBIT` while this is
 * true. The interface -- fields, rule, freshness, version, and what to do when
 * the layout changes -- is `notes/protocols/gen-inhibit-status-interface.md`;
 * the layout itself belongs to the inhibitor (its schema doc and decode DBC,
 * pinned there).
 *
 * Every doubt resolves to "not inhibiting": an absent inhibitor, a stale page
 * and an unknown schema version all leave EVAP showing the evap state.
 */
object GenInhibitStatus {

    const val SCHEMA_VER = "diag_schema_ver"
    const val MODE = "diag_mode"
    const val FLAGS = "diag_flags"

    /** The only layout version the app was checked against. */
    const val ACCEPTED_SCHEMA = 8

    /** `0x7F1` repeats about every 1.2 s, best-effort; older than this is no inhibit. */
    const val FRESH_MS = 3_000L

    const val MODE_INHIBIT = 3

    private const val BIT_DISABLED = 0
    private const val BIT_SHUTDOWN_SUPPRESSED = 4
    private const val BIT_INHIBIT_LIVE = 5
    private const val BIT_KEY_ON = 6
    private const val BIT_ABORT_LATCHED = 7

    /**
     * [values] and [seenAtMs] are the display's latest value and arrival time
     * per signal; [nowMs] is on the same clock as [seenAtMs].
     */
    fun inhibiting(values: Map<String, Double>, seenAtMs: Map<String, Long>, nowMs: Long): Boolean {
        for (name in listOf(SCHEMA_VER, MODE, FLAGS)) {
            val seen = seenAtMs[name] ?: return false
            if (values[name] == null || nowMs - seen > FRESH_MS) return false
        }
        return inhibiting(
            schemaVer = values.getValue(SCHEMA_VER).toInt(),
            mode = values.getValue(MODE).toInt(),
            flags = values.getValue(FLAGS).toInt(),
        )
    }

    /**
     * The firmware's own condition for sending a real inhibit frame: mode
     * INHIBIT, `inhibit_live` and `key_on` set, `disabled`,
     * `shutdown_suppressed` and `abort_latched` clear. `inhibit_live` alone
     * stays set while armed but silent (key-off, shutdown suppression), and
     * PASSIVE sets it too, so no single term is enough.
     */
    fun inhibiting(schemaVer: Int, mode: Int, flags: Int): Boolean {
        fun bit(n: Int) = (flags shr n) and 1 == 1
        return schemaVer == ACCEPTED_SCHEMA &&
            mode == MODE_INHIBIT &&
            bit(BIT_INHIBIT_LIVE) &&
            bit(BIT_KEY_ON) &&
            !bit(BIT_SHUTDOWN_SUPPRESSED) &&
            !bit(BIT_ABORT_LATCHED) &&
            !bit(BIT_DISABLED)
    }
}
