package com.reverseit.tpms

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The detector against the executable spec: `run()` in `tpms_app_prototype.py`, replayed over the
 * prototype's corpus epoch file (154 real drives, Feb-Sep 2026) under a grid of settings.
 *
 * Fixture: `src/test/resources/detector_parity/`, written by
 * `android-app/notes/artifacts/tpms_detector_parity.py`. Regenerate it whenever the corpus CSV or
 * the prototype changes.
 *
 * Requires, per settings case: the same events (drive and kind) in the same order, the same final
 * state and baseline size, and every per-drive DEL and corner figure to 1e-9 psi.
 */
class TpmsDetectorParityTest {

    private fun resource(name: String): String =
        javaClass.getResource("/detector_parity/$name")!!.readText()

    private val rows: List<JSONObject> = resource("epoch.jsonl").lines()
        .filter { it.isNotBlank() }.map { JSONObject(it) }.filter { it.optString("type") == "drive" }

    private val expected = JSONObject(resource("expected.json"))

    @Test
    fun `fixture is the whole corpus file`() {
        assertEquals(expected.getInt("drives"), rows.size)
        assertTrue("corpus shrank to ${rows.size} drives", rows.size >= 150)
    }

    @Test
    fun `every settings case matches the prototype`() {
        val cases = expected.getJSONArray("cases")
        assertTrue(cases.length() >= 20)
        for (i in 0 until cases.length()) check(cases.getJSONObject(i))
    }

    @Test
    fun `default settings report the known corpus story`() {
        // Spec section 3, corpus replay: baseline in Feb, LF advise then warn, the un-announced
        // 2026-07-01 fill detected as STALE.
        val r = TpmsDetector().run(TpmsDetector().drives(rows))
        assertEquals(listOf("baseline", "advise", "warn", "stale"), r.events.map { it.kind })
        assertEquals("20260702", r.events.last().ts.take(8))
        assertEquals(TpmsState.STALE, r.state)
    }

    private fun check(case: JSONObject) {
        val name = case.getString("name")
        val s = case.getJSONObject("settings")
        val settings = TpmsSettings(
            learnDrives = s.getInt("learnDrives"),
            learnMinSamples = s.getLong("learnMinSamples"),
            windowDrives = s.getInt("windowDrives"),
            minSamples = s.getInt("minSamples"),
            warnPsi = s.getDouble("warnPsi"),
            advisePsi = s.getDouble("advisePsi"),
            warnClearPsi = s.getDouble("warnClearPsi"),
            adviseClearPsi = s.getDouble("adviseClearPsi"),
            confirmDrives = s.getInt("confirmDrives"),
            stepPsi = s.getDouble("stepPsi"),
            stepWindow = s.getInt("stepWindow"),
            fastWarnPsi = s.getDouble("fastWarnPsi"),
            fastMinSamples = s.getLong("fastMinSamples"),
        )
        val det = TpmsDetector(settings)
        val drives = det.drives(rows)
        assertEquals("$name: every corpus row is its own session", rows.size, drives.size)
        val r = det.run(drives)

        val ev = case.getJSONArray("events")
        val want = (0 until ev.length()).map { ev.getJSONObject(it).let { e -> e.getString("ts") to e.getString("kind") } }
        assertEquals("$name events", want, r.events.map { it.ts to it.kind })
        assertEquals("$name level", case.getString("level").uppercase(), r.state.name)
        assertEquals("$name baseline drives", case.getInt("baseline_drives"), r.baseline.drives)

        val h = case.getJSONArray("history")
        assertEquals("$name history length", h.length(), r.history.size)
        for (j in 0 until h.length()) {
            val e = h.getJSONObject(j)
            val got = r.history[j]
            assertEquals("$name history[$j] ts", e.getString("ts"), got.ts)
            assertEquals("$name history[$j] DEL", e.getDouble("del"), got.delPsi, 1e-9)
            val dev = e.getJSONObject("dev")
            for (c in Corner.entries) {
                assertEquals("$name history[$j] ${c.name}", dev.getDouble(c.name), got.dev.getValue(c), 1e-9)
            }
        }
    }
}
