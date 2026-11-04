package com.reverseit.cancore

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * CM_ comments. The defect this pins: the quoted-string pattern recursed once per character and
 * overflowed the stack on a 1,579-character signal comment in the Vtrux powertrain.dbc.
 */
class DbcCommentTest {

    private val longText = "x".repeat(50_000)

    private fun dbc(vararg comments: String) = listOf(
        "VERSION \"\"",
        "",
        "BO_ 2033 Status: 8 WICAN",
        " SG_ Mode : 16|8@1+ (1,0) [0|255] \"\" Vector__XXX",
        "",
        *comments,
    ).joinToString("\n") + "\n"

    @Test
    fun `50k-character comments parse on all three comment forms`() {
        val parsed = DbcParser.parse(dbc(
            "CM_ \"$longText\";",
            "CM_ BO_ 2033 \"$longText\";",
            "CM_ SG_ 2033 Mode \"$longText\";",
        ))
        val msg = parsed.messages.getValue(2033)
        assertEquals(longText, parsed.fileComment)
        assertEquals(longText, msg.comment)
        assertEquals(longText, msg.signalsByName.getValue("Mode").comment)
    }

    @Test
    fun `escaped quotes and backslashes survive in a long comment`() {
        val parsed = DbcParser.parse(dbc("CM_ SG_ 2033 Mode \"a \\\"b\\\" \\\\ $longText\";"))
        assertEquals("a \"b\" \\ $longText", parsed.messages.getValue(2033).signalsByName.getValue("Mode").comment)
    }
}
