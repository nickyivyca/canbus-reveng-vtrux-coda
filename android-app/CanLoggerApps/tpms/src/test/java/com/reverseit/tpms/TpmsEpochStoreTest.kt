package com.reverseit.tpms

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.TimeZone

/**
 * The fragment store against `FragmentStore` in `projects/coda/notes/artifacts/tpms_app_prototype.py`
 * (phases 5, 6 and 7), plus the app-side parts the prototype does not have: the in-memory index,
 * the bounded startup read and its fall-back, and the consolidation counter surviving a restart.
 */
class TpmsEpochStoreTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val utc: TimeZone = TimeZone.getTimeZone("UTC")
    private var now = MS_20260301_090000
    private val dir get() = File(tmp.root, "tpms")
    private fun store(fullEvery: Int = TpmsEpochStore.FULL_EVERY_ROWS, d: File = dir) =
        TpmsEpochStore(d, { now }, utc, fullEveryRows = fullEvery)

    private fun entry(atMs: Long, rf: Float = 42f, ambient: Float = 15f) =
        TpmsCalibrationEntry.of(
            psi = mapOf(Corner.LF to 42f, Corner.RF to rf, Corner.LR to 42f, Corner.RR to 42f),
            ambientC = ambient,
            setAtMs = atMs,
        )

    private fun drive(log: String, n: Long, gps: JSONObject? = null) = JSONObject()
        .put("type", "drive").put("schema", 2).put("ts", "20260301T100000")
        .put("log", log).put("n", n).put("gps", gps ?: JSONObject.NULL)

    private fun gps(fixes: Long) = JSONObject().put("schema", 2).put("source", "snapshot").put("fixes", fixes)

    private fun partial(log: String, fixes: Long?) =
        DriveRowProducer.partialRow(log, "20260301T100000", fixes?.let { gps(it) })

    private fun names() = dir.list()!!.filter { it.endsWith(".jsonl") }.sorted()
    private fun lines(name: String) = File(dir, name).readLines().filter { it.isNotBlank() }.map { JSONObject(it) }
    private fun only(log: String, st: TpmsEpochStore = store()) = st.current()!!.drives.single { it.getString("log") == log }

    // --- epoch operations (prototype phase 5) ---------------------------------------------------

    @Test
    fun `set writes a full fragment whose first record is the calibration`() {
        val st = store()
        val f = st.set(entry(MS_20260301_090000))
        assertEquals("tpms_20260301T090000_000000_full.jsonl", f.name)
        val recs = lines(f.name)
        assertEquals(1, recs.size)
        assertEquals("calibration", recs[0].getString("type"))
        assertEquals(2, recs[0].getInt("schema"))
        assertEquals("20260301T090000", recs[0].getString("ts"))
        assertEquals(15.0, recs[0].getDouble("temp_c"), 0.0)
        assertEquals(setOf("LF", "RF", "LR", "RR"), recs[0].getJSONObject("psi").keySet())
        assertEquals(listOf("20260301T090000"), st.epochs())
    }

    @Test
    fun `a completed row is its own fragment led by the calibration`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        val f = st.addDrive(drive("coda_20260302_080000_T0.log", 2000))
        assertEquals("tpms_20260301T090000_000001.jsonl", f.name)
        val recs = lines(f.name)
        assertEquals(listOf("calibration", "drive"), recs.map { it.getString("type") })
        assertFalse(recs[1].getBoolean("partial"))
        assertEquals(1, st.current()!!.drives.size)
    }

    @Test
    fun `accidental set then undo resumes the first epoch with its history intact`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        repeat(40) { st.addDrive(drive("coda_20260302_0800%02d_T0.log".format(it), 2000)) }

        now += DAY
        st.set(entry(MS_20260301_090000 + DAY, ambient = 20f))
        assertEquals(2, st.epochs().size)
        val target = st.undoTarget()
        assertNotNull(target)
        assertEquals(MS_20260301_090000, target!!.setAtMs)

        val before = names()
        assertTrue(st.undo())
        assertEquals(1, st.epochs().size)
        val cur = st.current()!!
        assertEquals(MS_20260301_090000, cur.calibration.setAtMs)
        assertEquals(40, cur.drives.size)
        // A tombstone, not a delete: every file is still there, plus the void.
        assertTrue(names().containsAll(before))
        val void = names().last { it.startsWith("tpms_20260302T090000_") }
        val recs = lines(void)
        assertEquals("calibration", recs[0].getString("type"))
        assertEquals("20260302T090000", recs.single { it.getString("type") == "epoch_void" }.getString("epoch"))
        // And a fresh reader of the folder agrees.
        assertEquals(listOf("20260301T090000"), store().epochs())
    }

    @Test
    fun `amend corrects the values without moving the epoch or touching earlier fragments`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.addDrive(drive("coda_20260302_080000_T0.log", 2000))
        val snapshot = names().associateWith { File(dir, it).readText() }

        now = MS_20260301_090000 + 30 * DAY
        assertTrue(st.amend(mapOf(Corner.RF to 41f), ambientC = 16f))

        val cal = st.current()!!.calibration
        assertEquals(41f, cal.rfPsi, 0f)
        assertEquals(42f, cal.lfPsi, 0f)          // corners not named keep their values
        assertEquals(16f, cal.ambientC, 0f)
        assertEquals(MS_20260301_090000, cal.setAtMs)
        assertEquals(1, st.current()!!.drives.size)
        snapshot.forEach { (n, text) -> assertEquals(n, text, File(dir, n).readText()) }
        val newest = names().last()
        assertTrue(newest, newest.endsWith("_full.jsonl"))
        assertEquals(listOf("calibration", "calibration_amend", "drive"), lines(newest).map { it.getString("type") })
        assertEquals(41f, store().current()!!.calibration.rfPsi, 0f)
    }

    @Test
    fun `last amend wins, even two in the same second`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.amend(mapOf(Corner.RF to 41f), 15f)
        st.amend(mapOf(Corner.RF to 40.5f), 15f)
        assertEquals(40.5f, st.current()!!.calibration.rfPsi, 0f)
        assertEquals(40.5f, store().current()!!.calibration.rfPsi, 0f)
    }

    @Test
    fun `undo is unavailable once a qualifying drive lands in the new epoch`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.set(entry(MS_20260301_090000 + DAY))
        st.addDrive(drive("coda_20260302_080000_T0.log", 800))
        assertNull(st.undoTarget())
        assertFalse(st.undo())
        assertEquals(2, st.epochs().size)
    }

    @Test
    fun `undo is unavailable with only one epoch`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        assertNull(st.undoTarget())
        assertFalse(st.undo())
    }

    // --- per-segment rows, pooled per session --------------------------------------------------

    @Test
    fun `segments of one session pool to a qualifying drive for undo`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.set(entry(MS_20260301_090000 + DAY))
        // No single 5-minute row reaches 800, but the session does.
        (0..2).forEach { st.addDrive(drive("coda_20260302_080000_T$it.log", 300)) }
        assertNull(st.undoTarget())
    }

    @Test
    fun `the same samples spread over different sessions do not qualify`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.set(entry(MS_20260301_090000 + DAY))
        (0..2).forEach { st.addDrive(drive("coda_20260302_08000${it}_T0.log", 300)) }
        assertNotNull(st.undoTarget())
    }

    @Test
    fun `partial rows never keep undo closed`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.set(entry(MS_20260301_090000 + DAY))
        repeat(5) { st.checkpoint(partial("coda_20260302_080000_T0.log", 100L * it)) }
        assertNotNull(st.undoTarget())
    }

    @Test
    fun `session key strips only the segment suffix`() {
        assertEquals("coda_20260322_185934", TpmsEpochStore.sessionOf("coda_20260322_185934_T12.log"))
        assertEquals("oddname.log", TpmsEpochStore.sessionOf("oddname.log"))
    }

    // --- precalibration ------------------------------------------------------------------------

    @Test
    fun `a row before the first set is written, under a precalibration first record`() {
        val st = store()
        val f = st.addDrive(drive("coda_20260228_080000_T0.log", 2000))
        assertEquals("tpms_00000000T000000_000000_full.jsonl", f.name)
        assertEquals("precalibration", lines(f.name).first().getString("type"))
        assertNull(st.current())
        st.addDrive(drive("coda_20260228_080000_T1.log", 2000))
        assertEquals(2, st.precalibrationRows().size)
        assertEquals(2, store().precalibrationRows().size)
    }

    @Test
    fun `after the first set drives go to the epoch and precalibration is never an epoch`() {
        val st = store()
        st.addDrive(drive("coda_20260228_080000_T0.log", 2000))
        st.set(entry(MS_20260301_090000))
        val f = st.addDrive(drive("coda_20260302_080000_T0.log", 100))
        assertTrue(f.name.startsWith("tpms_20260301T090000_"))
        assertEquals(1, st.precalibrationRows().size)
        assertEquals(listOf("20260301T090000"), st.epochs())
        assertNull(st.undoTarget())
        assertEquals(1, store().precalibrationRows().size)
    }

    @Test
    fun `a file's role comes from its first record, not its name`() {
        dir.mkdirs()
        // Sorts last by name, but is not a calibration.
        File(dir, "tpms_20991231T235959_000000.jsonl").writeText("""{"type":"precalibration","schema":2,"ts":"x"}""" + "\n")
        File(dir, "tpms_20991231T235958_000000.jsonl").writeText("not json\n")
        val st = store()
        st.set(entry(MS_20260301_090000))
        assertEquals(listOf("20260301T090000"), st.epochs())
    }

    // --- names, clocks, values -----------------------------------------------------------------

    @Test
    fun `a set with the clock behind the newest epoch still becomes active`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        // Head unit booted with an unsynced clock.
        val f = st.set(entry(MS_20260301_090000 - 400 * DAY))
        assertEquals("tpms_20260301T090001_000000_full.jsonl", f.name)
        // The name is the ordering key; the record keeps the clock's time and says what the name is.
        val rec = lines(f.name).first()
        assertEquals("20250125T090000", rec.getString("ts"))
        assertEquals("20260301T090001", rec.getString("name_ts"))
        assertEquals(MS_20260301_090000 - 400 * DAY, st.current()!!.calibration.setAtMs)
        assertEquals(MS_20260301_090000 - 400 * DAY, store().current()!!.calibration.setAtMs)
    }

    @Test
    fun `name_ts is written only when the name had to move`() {
        val f = store().set(entry(MS_20260301_090000))
        assertFalse(lines(f.name).first().has("name_ts"))
    }

    @Test
    fun `two sets in the same second make two epochs, the second active`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        val b = st.set(entry(MS_20260301_090000 + 300, rf = 40f))
        for (s in listOf(st, store())) {
            assertEquals(listOf("20260301T090000", "20260301T090001"), s.epochs())
            assertEquals(40f, s.current()!!.calibration.rfPsi, 0f)
            // ts stays the true press time; only the ordering key (and identity) moved.
            assertEquals(MS_20260301_090000, s.current()!!.calibration.setAtMs)
        }
        assertTrue(b.name.startsWith("tpms_20260301T090001_"))
        val rec = lines(b.name).first()
        assertEquals("20260301T090000", rec.getString("ts"))
        assertEquals("20260301T090001", rec.getString("name_ts"))
    }

    @Test
    fun `amend with no epoch changes nothing`() {
        val st = store()
        assertFalse(st.amend(mapOf(Corner.RF to 41f), 15f))
        assertFalse(dir.exists() && names().isNotEmpty())
    }

    @Test
    fun `values are written as the decimals entered`() {
        val st = store()
        val f = st.set(entry(MS_20260301_090000, rf = 41.9f, ambient = 17.5f))
        val text = File(dir, f.name).readLines().first()
        assertTrue(text, text.contains("\"RF\":41.9"))
        assertTrue(text, text.contains("\"temp_c\":17.5"))
        assertEquals(41.9f, st.current()!!.calibration.rfPsi, 0f)
    }

    // --- fragments (prototype phase 7) ---------------------------------------------------------

    @Test
    fun `every fragment carries its calibration and stands alone`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.addDrive(drive("coda_20260302_080000_T0.log", 2000))
        st.checkpoint(partial("coda_20260302_080000_T1.log", 5))
        for (name in names()) {
            val alone = File(tmp.root, "alone_$name").apply { mkdirs() }
            File(dir, name).copyTo(File(alone, name))
            val cur = store(d = alone).current()
            assertNotNull(name, cur)
            assertEquals(name, MS_20260301_090000, cur!!.calibration.setAtMs)
        }
    }

    @Test
    fun `a re-upload named with (1) is a non-event`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.addDrive(drive("coda_20260302_080000_T0.log", 2000))
        val before = store().current()!!
        names().forEach { n -> File(dir, n).copyTo(File(dir, n.removeSuffix(".jsonl") + " (1).jsonl")) }
        val after = store().current()!!
        assertEquals(listOf("20260301T090000"), store().epochs())
        assertEquals(before.drives.map { it.toString() }, after.drives.map { it.toString() })
    }

    @Test
    fun `partials carry GPS only and the one with most fixes wins`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        val log = "coda_20260302_080000_T0.log"
        st.checkpoint(partial(log, 10))
        st.checkpoint(partial(log, 50))
        st.checkpoint(partial(log, 30))       // fewer fixes, later seq: loses
        val row = only(log)
        assertTrue(row.getBoolean("partial"))
        assertEquals(0, row.getInt("n"))
        assertTrue(row.isNull("ratios"))
        assertEquals(50, row.getJSONObject("gps").getInt("fixes"))
        assertEquals(50, only(log, store()).getJSONObject("gps").getInt("fixes"))
    }

    @Test
    fun `a completed row beats every partial and keeps its own GPS`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        val log = "coda_20260302_080000_T0.log"
        st.checkpoint(partial(log, 50))
        st.addDrive(drive(log, 1200, gps(60).put("source", "close")))
        st.checkpoint(partial(log, 70))       // a late checkpoint cannot displace it
        val row = only(log)
        assertFalse(row.getBoolean("partial"))
        assertEquals(1200, row.getInt("n"))
        assertEquals("close", row.getJSONObject("gps").getString("source"))
        assertEquals(60, row.getJSONObject("gps").getInt("fixes"))
    }

    @Test
    fun `a GPS-less winner inherits the best partial's block, tagged partial`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        val log = "coda_20260302_080000_T0.log"
        st.checkpoint(partial(log, 20))
        st.checkpoint(partial(log, 40))
        st.addDrive(drive(log, 1200))        // catch-up after a kill: no live block
        for (s in listOf(st, store(), store().also { it.load(fullScan = true) })) {
            val row = only(log, s)
            assertFalse(row.getBoolean("partial"))
            assertEquals(1200, row.getInt("n"))
            assertEquals(40, row.getJSONObject("gps").getInt("fixes"))
            assertEquals("partial", row.getJSONObject("gps").getString("source"))
        }
        assertEquals(setOf(log), st.recordedLogs())
    }

    @Test
    fun `a rejected row (no D CAN) keeps its reject and still inherits the partials' GPS`() {
        // A reject row is completed with n 0, so it outranks every partial -- which must not cost
        // the GPS block (algorithm session, 2026-09-27). The failure would read as "rejected
        // segments have no GPS", which is easy to accept as expected.
        val st = store()
        st.set(entry(MS_20260301_090000))
        val log = "coda_20260302_080000_T0.log"
        st.checkpoint(partial(log, 30))
        st.addDrive(drive(log, 0).put("ratios", JSONObject.NULL)
            .put("reject", JSONObject().put("code", "no_d_can").put("why", "no channel carries 2 anchors")))
        for (s in listOf(st, store(), store().also { it.load(fullScan = true) })) {
            val row = only(log, s)
            assertFalse(row.getBoolean("partial"))
            assertEquals("no_d_can", row.getJSONObject("reject").getString("code"))
            assertEquals(30, row.getJSONObject("gps").getInt("fixes"))
            assertEquals("partial", row.getJSONObject("gps").getString("source"))
        }
    }

    @Test
    fun `inheritance picks the best block whatever order the fragments are read in`() {
        dir.mkdirs()
        val cal = """{"type":"calibration","schema":2,"ts":"20260301T090000","psi":{"LF":42,"RF":42,"LR":42,"RR":42},"temp_c":15}"""
        val log = "coda_20260302_080000_T0.log"
        fun frag(name: String, row: JSONObject) = File(dir, name).writeText(cal + "\n" + row + "\n")
        // Names deliberately out of step with content: the best partial sorts first.
        frag("tpms_20260301T090000_000000.jsonl", partial(log, 90).put("partial", true))
        frag("tpms_20260301T090000_000001.jsonl", drive(log, 1200).put("partial", false))
        frag("tpms_20260301T090000_000002.jsonl", partial(log, 10).put("partial", true))
        assertEquals(90, only(log).getJSONObject("gps").getInt("fixes"))
    }

    @Test
    fun `storedGps gives catch-up the partial's block, and partial-only logs are not recorded`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        val log = "coda_20260302_080000_T0.log"
        assertNull(st.storedGps(log))
        st.checkpoint(partial(log, 33))
        assertEquals(emptySet<String>(), st.recordedLogs())
        val g = st.storedGps(log)!!
        assertEquals(33, g.getInt("fixes"))
        assertEquals("partial", g.getString("source"))
    }

    @Test
    fun `losing early partials costs no GPS, because later ones are supersets`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        val log = "coda_20260302_080000_T0.log"
        val early = (1..3).map { st.checkpoint(partial(log, 10L * it)).name }
        st.checkpoint(partial(log, 40))
        early.forEach { File(dir, it).delete() }
        assertEquals(40, only(log, store()).getJSONObject("gps").getInt("fixes"))
    }

    @Test
    fun `losing a completed-row fragment loses that row -- the accepted cost of R = 0`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        val log = "coda_20260302_080000_T0.log"
        st.checkpoint(partial(log, 40))
        val close = st.addDrive(drive(log, 1200, gps(45)))
        assertTrue(File(dir, close.name).delete())
        val row = only(log, store())
        // Back to the last partial: n and ratios regenerable from the log, GPS as of the checkpoint.
        assertTrue(row.getBoolean("partial"))
        assertEquals(40, row.getJSONObject("gps").getInt("fixes"))
    }

    @Test
    fun `consolidation counts completed rows, not fragments`() {
        val st = store(fullEvery = 4)
        st.set(entry(MS_20260301_090000))                                   // 000000_full
        repeat(9) {
            st.checkpoint(partial("coda_20260302_0800%02d_T0.log".format(it), 5))
            st.addDrive(drive("coda_20260302_0800%02d_T0.log".format(it), 900))
        }
        val fulls = names().filter { it.endsWith("_full.jsonl") }
        // Completed rows 4 and 8 trigger a full; nine partials in between trigger nothing.
        assertEquals(3, fulls.size)
        assertEquals(8, lines(fulls.last()).count { it.getString("type") == "drive" && !it.getBoolean("partial") })
        assertEquals(9, store().current()!!.drives.size)
    }

    @Test
    fun `the consolidation counter survives a restart`() {
        store(fullEvery = 4).apply {
            set(entry(MS_20260301_090000))
            repeat(2) { addDrive(drive("coda_20260302_08000${it}_T0.log", 900)) }
        }
        val st = store(fullEvery = 4)
        assertFalse(st.addDrive(drive("coda_20260302_080002_T0.log", 900)).name.endsWith("_full.jsonl"))
        assertTrue(st.addDrive(drive("coda_20260302_080003_T0.log", 900)).name.endsWith("_full.jsonl"))
    }

    @Test
    fun `fragments are never modified once written`() {
        val st = store(fullEvery = 3)
        st.set(entry(MS_20260301_090000))
        val seen = HashMap<String, String>()
        repeat(7) {
            st.checkpoint(partial("coda_20260302_0800%02d_T0.log".format(it), 5))
            st.addDrive(drive("coda_20260302_0800%02d_T0.log".format(it), 900))
            if (it == 3) st.amend(mapOf(Corner.RF to 41f), 15f)
            names().forEach { n ->
                val text = File(dir, n).readText()
                seen.putIfAbsent(n, text)
                assertEquals(n, seen[n], text)
            }
        }
    }

    @Test
    fun `tmp files are ignored and bad lines are dropped, not raised`() {
        val st = store()
        st.set(entry(MS_20260301_090000))
        st.addDrive(drive("coda_20260302_080000_T0.log", 2000))
        File(dir, "tpms_20260301T090000_000009.jsonl.tmp").writeText("""{"type":"calibration","schema":2,"ts":"20990101T000000"}""")
        File(dir, "tpms_20260301T090000_000001.jsonl").appendText("""{"type":"drive","log":"coda_2026""" + "\n")
        val cur = store().current()!!
        assertEquals("20260301T090000", cur.key)
        assertEquals(1, cur.drives.size)
        assertEquals(1, cur.skippedLines)
    }

    // --- legacy files (schema 1) ---------------------------------------------------------------

    @Test
    fun `a legacy append-only file is read as a fragment and migrated by the first write`() {
        dir.mkdirs()
        File(dir, "tpms_20260301T090000.jsonl").writeText(
            """{"type": "calibration", "schema": 1, "ts": "20260301T090000", "psi": {"LF": 42.0, "RF": 42.0, "LR": 42.0, "RR": 42.0}, "temp_c": 15.0, "note": "real calibration"}""" + "\n" +
            """{"type": "drive", "schema": 1, "ts": "20260322T185934", "log": "coda_20260322_185934_T0.log", "n": 1523, "dur_s": 15.2, "kmh_med": 61.3, "ratios": {"DEL": {"mean": 1.0012, "sd": 0.0003}}, "temps": null, "gps": {"fixes": 12}}""" + "\n" +
            """{"type": "calibration_amend", "schema": 1, "ts": "20260921T231500", "note": "RF typo", "psi": {"LF": 42.0, "RF": 41.0, "LR": 42.0, "RR": 42.0}}""" + "\n" +
            """{"type": "drive", "schema": 1, "log": "coda_2026"""       // frozen mid-append
        )
        val st = store()
        val cur = st.current()!!
        assertEquals(1, cur.drives.size)
        assertEquals(41f, cur.calibration.rfPsi, 0f)
        assertEquals(15f, cur.calibration.ambientC, 0f)      // amend without temp_c keeps it
        assertEquals(MS_20260301_090000, cur.calibration.setAtMs)

        val f = st.addDrive(drive("coda_20260323_080000_T0.log", 900))
        assertEquals("tpms_20260301T090000_000000_full.jsonl", f.name)
        val recs = lines(f.name)
        assertEquals("calibration", recs[0].getString("type"))
        assertEquals(listOf("coda_20260322_185934_T0.log", "coda_20260323_080000_T0.log"),
            recs.filter { it.getString("type") == "drive" }.map { it.getString("log") }.sorted())
        // The _full alone is the whole epoch -- the file the server will actually have.
        val alone = File(tmp.root, "alone").apply { mkdirs() }
        File(dir, f.name).copyTo(File(alone, f.name))
        val a = store(d = alone).current()!!
        assertEquals(2, a.drives.size)
        assertEquals(41f, a.calibration.rfPsi, 0f)
    }

    // --- the app's bounded read ----------------------------------------------------------------

    @Test
    fun `the bounded read skips what a newer full covers and agrees with the full scan`() {
        val st = store(fullEvery = 4)
        st.set(entry(MS_20260301_090000))
        repeat(10) {
            st.checkpoint(partial("coda_20260302_0800%02d_T0.log".format(it), 5))
            st.addDrive(drive("coda_20260302_0800%02d_T0.log".format(it), 900, gps(it.toLong()).takeIf { _ -> it % 2 == 0 }))
        }
        spreadMtimes()
        val bounded = store()
        val b = bounded.current()!!
        val stats = bounded.lastLoad!!
        assertTrue(stats.toString(), stats.skipped > 0)
        assertFalse(stats.fullScan)
        val full = store().also { it.load(fullScan = true) }.current()!!
        assertEquals(full.drives.map { it.toString() }, b.drives.map { it.toString() })
        assertEquals(full.calibration, b.calibration)
    }

    @Test
    fun `a fragment placed by hand behind the newest full forces a full scan`() {
        val st = store(fullEvery = 2)
        st.set(entry(MS_20260301_090000))
        repeat(4) { st.addDrive(drive("coda_20260302_08000${it}_T0.log", 900)) }
        spreadMtimes()
        // Seqs are contiguous, so a hand-placed canonical name behind the newest _full lands on an
        // existing one -- e.g. a rebuild from the migration tool. Its mtime is what gives it away.
        val name = "tpms_20260301T090000_000001.jsonl"
        val cal = lines(name).first()
        File(dir, name).writeText(cal.toString() + "\n" +
            drive("coda_20260301_070000_T0.log", 900).put("partial", false) + "\n")
        val s = store()
        assertTrue(s.lastLoad.toString(), s.current()!!.drives.any { it.getString("log") == "coda_20260301_070000_T0.log" })
        assertTrue(s.lastLoad!!.fullScan)
    }

    /** Fragments written in one test land within the same second; spread them out as real ones are. */
    private fun spreadMtimes() {
        val files = names().map { File(dir, it) }
        val base = System.currentTimeMillis() - 1_000_000L
        files.forEachIndexed { i, f -> f.setLastModified(base + i * 1000L) }
    }

    private companion object {
        const val MS_20260301_090000 = 1772355600000L    // 2026-03-01T09:00:00Z
        const val DAY = 86_400_000L
    }
}
