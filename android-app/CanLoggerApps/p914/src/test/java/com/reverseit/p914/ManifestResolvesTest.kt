package com.reverseit.p914

import com.reverseit.cancore.DbcParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Every `message_id` in the shipped manifest must resolve to a message in the shipped DBC, using
 * the same [DbcParser] the app decodes with.
 *
 * This is not a duplicate of `notes/artifacts/p914_manifest_verify.py`. That script re-implements
 * the id convention in Python; this one asks the production parser, so the two agree only if the
 * convention really is what the app applies at runtime.
 *
 * The failure it guards against is silent by construction. `LocalCanDataSource` matches
 * `sub.messageId` against `CanFrame.id`, and an id that matches nothing produces no error and no
 * log line -- the subscription simply never fires and the panel it feeds never updates. A DBC
 * `BO_` number for a 29-bit message carries the 0x80000000 extended marker; the wire id does not.
 * The first version of the manifest used the marked numbers, so all four of its 29-bit
 * subscriptions were dead, and it passed review, passed the Python validator, and would have
 * built and installed and shown a permanently blank screen (caught 2026-08-15).
 *
 * `:vtrux` had the answer the whole time: its manifest subscribes to five 29-bit BelInverter and
 * DCDC messages by wire id (`BO_ 2566903475` in `powertrain.dbc` is `419419827` there), and has
 * since its charge panel was built. So this is a regression test for contradicting a working
 * precedent, not for exploring an untried case.
 *
 * Reading the assets off disk rather than through `AssetManager` keeps this a plain JVM test.
 * `message_id` is pulled with a regex rather than `org.json`, because the JVM unit-test classpath
 * has only Android's stub `JSONObject`, which returns defaults instead of parsing.
 */
class ManifestResolvesTest {

    private val assets = File("src/main/assets/live-display")
    private val manifestText = File(assets, "manifest.json").readText()
    private val dbcText = File(assets, "dbcs/vcu.dbc").readText()

    /** Matches `"message_id": 520093696`, ignoring the `_note` prose around it. */
    private val messageIds: List<Long> =
        Regex(""""message_id"\s*:\s*(\d+)""").findAll(manifestText)
            .map { it.groupValues[1].toLong() }
            .toList()

    @Test
    fun `every manifest message id resolves through DbcParser`() {
        val dbc = DbcParser.parse(dbcText)
        assertTrue("no message_id found in the manifest", messageIds.isNotEmpty())
        for (id in messageIds) {
            assertTrue(
                "message_id $id (0x%X) is not in vcu.dbc as DbcParser sees it. If this is a "
                    .format(id) +
                    "29-bit id, check it is the WIRE id and not the raw BO_ number: DbcParser " +
                    "strips the 0x80000000 extended marker and CanFrame.id never carries it.",
                dbc.messages.containsKey(id.toInt()),
            )
        }
    }

    @Test
    fun `no manifest id carries the DBC extended marker`() {
        for (id in messageIds) {
            assertEquals(
                "message_id $id carries the 0x80000000 extended marker; use %d instead"
                    .format(id and 0x7FFFFFFFL),
                0L,
                id and 0x80000000L,
            )
        }
    }

    /**
     * The ids the display's own code reaches for, checked independently of the manifest so that
     * "the manifest is self-consistent but subscribes to the wrong things" is still a failure.
     */
    @Test
    fun `the four bus anchors exist in the DBC`() {
        val dbc = DbcParser.parse(dbcText)
        val anchors = P914Constants.BUS_IDENTITIES.single().anchorIds
        assertEquals(4, anchors.size)
        for (a in anchors) {
            assertTrue(
                "anchor 0x%08X is not a message in vcu.dbc".format(a),
                dbc.messages.containsKey(a),
            )
        }
    }

    /**
     * The opmode value table has to be readable from the DBC text, because the screen renders
     * opmode from it rather than from a hardcoded list. If `VAL_` formatting ever changes, the
     * display would silently fall back to showing raw numbers.
     */
    @Test
    fun `the opmode value table is readable and covers the modes the firmware defines`() {
        val line = dbcText.lineSequence().firstOrNull { it.startsWith("VAL_ 2 InvOpmode ") }
        assertTrue("vcu.dbc has no VAL_ table for InvOpmode", line != null)
        val table = Regex("""(-?\d+)\s+"([^"]*)"""").findAll(line!!)
            .associate { it.groupValues[1].toInt() to it.groupValues[2] }
        assertEquals("Off", table[0])
        assertEquals("Run", table[1])
        assertEquals(7, table.size)
    }

    /**
     * The DBC the app ships must carry the stamp the schema check compares against.
     *
     * Deliberately does NOT pin the version. An earlier draft asserted major == 3 and duly broke
     * on the first legitimate bump to 4.0, which is noise rather than a finding -- the version is
     * the generator's business, and a test that has to be edited every time it changes trains you
     * to edit it without reading it. What must hold is that a stamp exists, parses, and agrees
     * with the raw text; the parser itself is pinned against fixed fixtures in SchemaCheckTest.
     */
    @Test
    fun `the shipped DBC is stamped and the stamp parses`() {
        val stamp = SchemaCheck.parseStamp(DbcParser.parse(dbcText).fileComment)
        assertTrue("vcu.dbc carries no SCHEMA_HASH= stamp", stamp != null)
        assertTrue("stamp major looks unset: ${stamp!!.major}", stamp.major >= 1)
        assertTrue(
            "the parsed hash does not appear in the DBC text as written",
            dbcText.contains("SCHEMA_HASH=0x%08X".format(stamp.hash)),
        )
    }
}
