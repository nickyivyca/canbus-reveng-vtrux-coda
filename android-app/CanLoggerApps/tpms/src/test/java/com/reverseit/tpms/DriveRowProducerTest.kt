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
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.random.Random

/**
 * [DriveRowProducer] and the parts of [WheelRatioExtractor] that the real-capture parity test
 * cannot pin down on its own, on small synthetic logs.
 */
class DriveRowProducerTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val logDir by lazy { File(tmp.root, "CodaLogs").apply { mkdirs() } }

    // --- synthetic logs ------------------------------------------------------------------------

    /**
     * A BUSMASTER log in CanLoggingService's format: [seconds] of 100 Hz frames of all four IDs,
     * wheels at [kmh] (LF scaled by [lfScale]), steering raw [steerRaw], brakes off, zero torque.
     *
     * D CAN is channel [dBus], identified by [anchors] at 10 Hz. [gatewayLfScale] non-null adds the
     * gateway's copy of the four IDs on the other channel, written *first* in each group so file
     * order and frame counts cannot favour D CAN, with its own LF scale so a mix-up shows.
     */
    private fun writeLog(
        name: String, seconds: Int, kmh: Double, steerRaw: Int,
        lfScale: Double = 1.0, extraLines: List<String> = emptyList(), torqueNm: Double = 0.0,
        dBus: Int = 1, anchors: List<Int> = listOf(0x308, 0x312), gatewayLfScale: Double? = null,
        withTorque: Boolean = true,
    ): File {
        val tq = Math.round((torqueNm + 3212.8) / 0.1).toInt()
        val sb = StringBuilder()
        sb.append("***BUSMASTER Ver 3.2.2***\n***PROTOCOL CAN***\n")
        sb.append("***START DATE AND TIME 18:06:2026 19:59:06:701***\n***HEX***\n")
        extraLines.forEach { sb.append(it).append('\n') }
        val counts = Math.round(kmh * WheelRatioExtractor.COUNTS_PER_KMH).toInt()
        val lf = 0xC000 + Math.round(counts * lfScale).toInt()
        val w = 0xC000 + counts
        for (k in 0 until seconds * 100) {
            val ticks = 10_000L + k * 100L              // start 1 s in, 10 ms apart
            val ts = ts(ticks)
            fun four(bus: Int, lfWord: Int) {
                sb.append("$ts Rx $bus 0x200 s 8 00 00 00 00 ${hex16(w)} ${hex16(lfWord)}\n")
                sb.append("$ts Rx $bus 0x208 s 8 00 00 10 00 ${hex16(w)} ${hex16(w)}\n")
                sb.append("$ts Rx $bus 0x80 s 8 00 00 ${hex16(steerRaw)} 00 00 00 00\n")
                if (withTorque) sb.append("$ts Rx $bus 0x1C0 s 8 %02X %02X 00 00 00 00 00 00\n"
                    .format(tq and 0xFF, (tq shr 8) and 0xFF))
            }
            gatewayLfScale?.let { four(3 - dBus, 0xC000 + Math.round(counts * it).toInt()) }
            four(dBus, lf)
            if (k % 10 == 0) anchors.forEach { a -> sb.append("$ts Rx $dBus 0x%X s 8 00 00 00 00 00 00 00 00\n".format(a)) }
            if (k % 100 == 0) {
                // 1 Hz B CAN temperatures: FrontInlet 22, RearInlet 23, Cell_T_avg 30,
                // OPAir 25 with every other frame the 0x80 sentinel, EvapAirOff 18.
                val op = if ((k / 100) % 2 == 0) "99" else "80"
                sb.append("$ts Rx 2 0x390 s 8 96 97 00 00 00 00 00 00\n")
                sb.append("$ts Rx 2 0x382 s 8 9E 00 00 00 00 00 00 00\n")
                sb.append("$ts Rx 2 0x391 s 8 00 00 00 $op 00 92 00 00\n")
            }
        }
        sb.append("***END DATE AND TIME 18:06:2026 20:04:06:715***\n")
        return File(logDir, name).apply { writeText(sb.toString()) }
    }

    private fun ts(ticks: Long): String {
        val s = ticks / 10_000
        return "%02d:%02d:%02d:%04d".format(s / 3600, (s / 60) % 60, s % 60, ticks % 10_000)
    }

    private fun hex16(v: Int) = "%02X %02X".format((v shr 8) and 0xFF, v and 0xFF)

    private class Harness(val producer: DriveRowProducer, val rows: MutableList<JSONObject>,
                          val exec: java.util.concurrent.ExecutorService) {
        fun drain() { exec.shutdown(); assertTrue(exec.awaitTermination(60, TimeUnit.SECONDS)) }
    }

    private fun harness(recorded: Set<String> = emptySet(), active: String? = null,
                        epochSetAtMs: Long? = null): Harness {
        val rows = mutableListOf<JSONObject>()
        val exec = Executors.newSingleThreadExecutor()
        val p = DriveRowProducer(logDir, { rows.add(it) }, { recorded }, { active },
            epochSetAtMs = { epochSetAtMs }, executor = exec,
            log = { m, e -> println(m); e?.printStackTrace() })
        return Harness(p, rows, exec)
    }

    // --- extractor -----------------------------------------------------------------------------

    @Test
    fun `a straight steady drive yields every sample after the first steady window, and the ratio`() {
        val f = writeLog("coda_20260618_195906_T0.log", 20, 80.0, 20000, lfScale = 1.002)
        val res = WheelRatioExtractor.extractSegment(WheelRatioExtractor.readFrames(f), 20000.0)
        // 2000 samples; the 1 s trailing window (100 samples) is not full for the first 99.
        assertEquals(2000 - 99, res.n)
        val counts = Math.round(80.0 * WheelRatioExtractor.COUNTS_PER_KMH).toDouble()
        val lf = Math.round(counts * 1.002).toDouble()
        assertEquals(lf / counts, res.ratios.getValue("LFRF").mean, 1e-12)
        assertEquals((lf + counts) / (2 * counts), res.ratios.getValue("DEL").mean, 1e-12)
        assertEquals(1.0, res.ratios.getValue("LRRR").mean, 0.0)
        assertEquals("20260618T195906", WheelRatioExtractor.readFrames(f).startTs)
    }

    @Test
    fun `negative-tick lines written before a roll are skipped, as the Python parser skips them`() {
        val bad = "00:00:00:-160 Rx 1 0x200 s 8 00 00 00 00 FF FF FF FF"
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, extraLines = listOf(bad))
        val frames = WheelRatioExtractor.readFrames(f)
        assertEquals(300, frames.front.size)
        assertEquals(0.0, frames.front.first().t, 0.0)   // origin is the first *valid* line
    }

    // --- void: the owner's "ESC sensors problematic -> drive void" rule -------------------------

    private fun voidOf(vararg extra: String): List<String> {
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, extraLines = extra.toList())
        return WheelRatioExtractor.readFrames(f).voidReasons
    }

    @Test
    fun `routine non-zero sub-frames on a healthy car do not void`() {
        // A healthy car sends 0x1E/0x1C at ESC power-up and 0x20 in short bursts. Voiding on
        // "not 0" would void every drive in the corpus.
        assertEquals(emptyList<String>(), voidOf(
            "00:00:01:0001 Rx 1 0x200 s 8 1C 00 00 00 C5 80 C5 80",
            "00:00:01:0002 Rx 1 0x200 s 8 1E 00 00 00 C5 80 C5 80",
            "00:00:01:0003 Rx 1 0x200 s 8 20 00 00 00 C2 00 C2 00"))
    }

    @Test
    fun `an ABSFault sub-frame on the ESC bus voids the segment`() {
        assertEquals(listOf(WheelRatioExtractor.VOID_ESC_FAULT),
            voidOf("00:00:01:0001 Rx 1 0x200 s 8 14 00 00 00 C5 80 C5 80"))
    }

    @Test
    fun `0x14 on a bus without 0x208 is the C CAN message, not an ESC fault`() {
        // C CAN has its own ID 0x200 with B0 spanning ~0x07-0x1B. The ESC bus is found by content.
        assertEquals(emptyList<String>(),
            voidOf("00:00:01:0001 Rx 3 0x200 s 8 14 00 00 00 12 34 56 78"))
    }

    @Test
    fun `a dead wheel word voids the segment`() {
        assertEquals(listOf(WheelRatioExtractor.VOID_WHEEL_STUCK),
            voidOf("00:00:01:0001 Rx 1 0x208 s 8 00 00 10 00 FF FF C5 80"))
    }

    @Test
    fun `the row records the void reasons and null when there are none`() {
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000)
        val res = WheelRatioExtractor.extractSegment(WheelRatioExtractor.readFrames(f), 20000.0)
        val clean = DriveRowProducer.driveRow(f.name, "20260618T195906", res, 0)
        assertTrue(clean.isNull("void"))
        val bad = DriveRowProducer.driveRow(f.name, "20260618T195906", res, 0,
            void = listOf(WheelRatioExtractor.VOID_ESC_FAULT))
        assertEquals(WheelRatioExtractor.VOID_ESC_FAULT, bad.getJSONArray("void").getString(0))
    }

    @Test
    fun `interp matches numpy on repeated abscissae and at both ends`() {
        val xp = doubleArrayOf(1.0, 2.0, 2.0, 3.0)
        val fp = doubleArrayOf(10.0, 20.0, 30.0, 40.0)
        assertEquals(10.0, WheelRatioExtractor.interpAt(0.0, xp, fp), 0.0)
        assertEquals(30.0, WheelRatioExtractor.interpAt(2.0, xp, fp), 0.0)   // last of the ties
        assertEquals(35.0, WheelRatioExtractor.interpAt(2.5, xp, fp), 0.0)
        assertEquals(40.0, WheelRatioExtractor.interpAt(9.0, xp, fp), 0.0)
    }

    @Test
    fun `steering centre histogram median equals the sorted-array median`() {
        val rnd = Random(3)
        for (size in listOf(1, 2, 7, 100, 101)) {
            val c = SteeringCentre()
            val v = IntArray(size) { 19_990 + rnd.nextInt(20) }
            v.forEach { c.add(it) }
            assertEquals(WheelRatioExtractor.median(DoubleArray(size) { v[it].toDouble() }), c.median()!!, 0.0)
        }
    }

    @Test
    fun `temperature byte positions and scaling agree with the B CAN DBC`() {
        // Gradle runs JVM tests with the module directory as the working directory.
        val dbc = com.reverseit.cancore.DbcParser.parse(File("../../../projects/coda/CODA-B-CAN.dbc").readText())
        val rnd = Random(5)
        for (ch in WheelRatioExtractor.TEMP_CHANNELS) {
            val sig = dbc.messages.getValue(ch.id).signalsByName.getValue(ch.name)
            repeat(50) {
                val data = ByteArray(8) { rnd.nextInt(256).toByte() }
                val raw = data[ch.byte].toInt() and 0xFF
                assertEquals(ch.name, com.reverseit.cancore.DbcDecoder.decodeOne(sig, data), raw - 128.0, 0.0)
            }
        }
    }

    @Test
    fun `temperatures are whole-segment medians with the sentinel excluded and counted`() {
        val f = writeLog("coda_20260618_195906_T0.log", 10, 10.0, 20000)   // n = 0 on the ratios
        val t = WheelRatioExtractor.temperatures(WheelRatioExtractor.readFrames(f))
        assertEquals(22.0, t.getValue("FrontInletAirTemp").median!!, 0.0)
        assertEquals(23.0, t.getValue("RearInletAirTemp").median!!, 0.0)
        assertEquals(30.0, t.getValue("Cell_T_avg").median!!, 0.0)
        assertEquals(18.0, t.getValue("EvapAirOffTemp").median!!, 0.0)
        val op = t.getValue("OPAirTemp")
        assertEquals(25.0, op.median!!, 0.0)
        assertEquals(10, op.n)
        assertEquals(0.5, op.validFrac!!, 0.0)
    }

    @Test
    fun `implausible temperatures are excluded and counted like sentinels`() {
        // Cell_T_avg: the DBC's 0x33 (-77 C) and 0x00, plus an undocumented 0xFF (+127 C).
        val lines = listOf("33", "00", "FF", "9E").map { "00:00:00:0500 Rx 2 0x382 s 8 $it 00 00 00 00 00 00 00" }
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, extraLines = lines)
        val cell = WheelRatioExtractor.temperatures(WheelRatioExtractor.readFrames(f)).getValue("Cell_T_avg")
        assertEquals(3 + 4, cell.n)                            // 3 generated at 1 Hz + 4 above
        assertEquals(30.0, cell.median!!, 0.0)
        assertEquals(4.0 / 7.0, cell.validFrac!!, 1e-12)
    }

    @Test
    fun `temperature frames do not move the ratio time origin`() {
        val early = "00:00:00:0500 Rx 2 0x390 s 8 96 97 00 00 00 00 00 00"
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, extraLines = listOf(early))
        assertEquals(0.0, WheelRatioExtractor.readFrames(f).front.first().t, 0.0)
    }

    // --- bus identity: D CAN by anchors (spec section 1) -------------------------------------

    @Test
    fun `the ratios come from D CAN, not the gateway's copy, whatever the order and counts`() {
        // The gateway's copy is written first on every line and has a different LF, so a
        // frame-count or first-seen pick would read it. The anchors say channel 1.
        val f = writeLog("coda_20260618_195906_T0.log", 20, 80.0, 20000, lfScale = 1.002, gatewayLfScale = 1.010)
        val frames = WheelRatioExtractor.readFrames(f)
        assertNull(frames.busRejection)
        assertTrue(frames.front.all { it.bus == 1 } && frames.steer.all { it.bus == 1 })
        val res = WheelRatioExtractor.extractSegment(frames, 20000.0)
        val counts = Math.round(80.0 * WheelRatioExtractor.COUNTS_PER_KMH).toDouble()
        assertEquals(Math.round(counts * 1.002) / counts, res.ratios.getValue("LFRF").mean, 1e-12)
        assertEquals(2000 - 99, res.n)                         // one copy, not both
    }

    @Test
    fun `D CAN is found on whichever channel carries the anchors`() {
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, dBus = 2, gatewayLfScale = 1.010)
        val frames = WheelRatioExtractor.readFrames(f)
        assertTrue(frames.front.isNotEmpty() && frames.front.all { it.bus == 2 })
    }

    @Test
    fun `no anchors means no rows, and the reason is stated`() {
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, anchors = emptyList(), gatewayLfScale = 1.0)
        val frames = WheelRatioExtractor.readFrames(f)
        assertTrue(frames.front.isEmpty() && frames.rear.isEmpty() && frames.steer.isEmpty())
        assertEquals(WheelRatioExtractor.REJECT_NO_D_CAN, frames.busRejection!!.code)
        assertEquals(0, WheelRatioExtractor.extractSegment(frames, 20000.0).n)
    }

    @Test
    fun `one anchor id is not enough to decide a bus`() {
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, anchors = listOf(0x308))
        assertEquals(WheelRatioExtractor.REJECT_NO_D_CAN, WheelRatioExtractor.readFrames(f).busRejection!!.code)
    }

    @Test
    fun `a stray anchor frame on the other channel is noise, not ambiguity`() {
        val stray = "00:00:01:0005 Rx 2 0x325 s 8 00 00 00 00 00 00 00 00"
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, gatewayLfScale = 1.0, extraLines = listOf(stray))
        val frames = WheelRatioExtractor.readFrames(f)
        assertNull(frames.busRejection)
        assertTrue(frames.front.all { it.bus == 1 })
    }

    @Test
    fun `anchors on two channels are refused, not chosen between`() {
        val rival = listOf("00:00:01:0005 Rx 2 0x325 s 8 00 00 00 00 00 00 00 00",
            "00:00:01:0006 Rx 2 0x330 s 8 00 00 00 00 00 00 00 00")
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, gatewayLfScale = 1.0, extraLines = rival)
        val frames = WheelRatioExtractor.readFrames(f)
        assertEquals(WheelRatioExtractor.REJECT_AMBIGUOUS, frames.busRejection!!.code)
        assertTrue(frames.front.isEmpty())
    }

    @Test
    fun `D CAN without one of the four signal ids is refused`() {
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, withTorque = false)
        val r = WheelRatioExtractor.readFrames(f).busRejection!!
        assertEquals(WheelRatioExtractor.REJECT_INCOMPLETE, r.code)
        assertTrue(r.why, "0x1C0" in r.why)
    }

    @Test
    fun `a rejected segment still gets a row, saying why, and it is not a void`() {
        val f = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000, anchors = emptyList())
        val h = harness()
        h.producer.onSegmentClosed(f)
        h.drain()
        val row = h.rows.single()
        assertEquals(0, row.getInt("n"))
        assertTrue(row.isNull("void"))                        // a void would condemn the session
        assertEquals(WheelRatioExtractor.REJECT_NO_D_CAN, row.getJSONObject("reject").getString("code"))
        assertTrue(row.getJSONObject("reject").getString("why").isNotEmpty())
    }

    // --- producer ------------------------------------------------------------------------------

    @Test
    fun `segments of one session are centred on the running session median`() {
        val t0 = writeLog("coda_20260618_195906_T0.log", 10, 80.0, 20000)
        val t1 = writeLog("coda_20260618_195906_T1.log", 10, 80.0, 20010)
        val h = harness()
        h.producer.onSegmentClosed(t0)
        h.producer.onSegmentClosed(t1)
        h.drain()
        assertEquals(2, h.rows.size)
        assertEquals(20000.0, h.rows[0].getDouble("steer_centre"), 0.0)
        assertEquals(1000, h.rows[0].getLong("steer_n"))
        // 1000 samples at 20000 and 1000 at 20010: the median is their midpoint.
        assertEquals(20005.0, h.rows[1].getDouble("steer_centre"), 0.0)
        assertEquals(2000, h.rows[1].getLong("steer_n"))
        assertEquals("fast", h.rows[1].getString("steer_centre_src"))     // all at 80 km/h
        assertEquals(2000, h.rows[1].getLong("steer_n_fast"))
        // The centre is 0.5 deg off each segment's own straight-ahead -- inside the 2 deg mask.
        assertTrue(h.rows[1].getInt("n") > 0)
    }

    @Test
    fun `manoeuvring with the wheel turned does not drag the centre once there is fast driving`() {
        // The recovered 2026-09-24 case: slow with the wheel well off centre, then highway straight.
        val t0 = writeLog("coda_20260924_004341_T0.log", 10, 30.0, 22000)
        val t1 = writeLog("coda_20260924_004341_T1.log", 10, 80.0, 20000)
        val h = harness()
        h.producer.onSegmentClosed(t0)
        h.producer.onSegmentClosed(t1)
        h.drain()
        // No fast samples yet: the all-samples fallback, tagged so analysis can tell.
        assertEquals("all", h.rows[0].getString("steer_centre_src"))
        assertEquals(0, h.rows[0].getLong("steer_n_fast"))
        // The all-samples median would be 21000, 200 deg off straight, and reject everything.
        assertEquals("fast", h.rows[1].getString("steer_centre_src"))
        assertEquals(20000.0, h.rows[1].getDouble("steer_centre"), 0.0)
        assertTrue(h.rows[1].getInt("n") > 0)
    }

    @Test
    fun `a segment arriving out of sequence rebuilds the centre from the earlier segments`() {
        writeLog("coda_20260618_195906_T0.log", 10, 80.0, 20000)
        writeLog("coda_20260618_195906_T1.log", 10, 80.0, 20000)
        val t2 = writeLog("coda_20260618_195906_T2.log", 10, 80.0, 20000)
        val h = harness()
        h.producer.onSegmentClosed(t2)                      // process restarted mid-session
        h.drain()
        assertEquals(3000, h.rows.single().getLong("steer_n"))
        assertEquals(3000, h.rows.single().getLong("steer_n_fast"))
    }

    @Test
    fun `a segment with no qualifying samples still gets a row`() {
        val f = writeLog("coda_20260618_195906_T0.log", 10, 10.0, 20000)   // below 25 km/h
        val h = harness()
        h.producer.onSegmentClosed(f)
        h.drain()
        val row = h.rows.single()
        assertEquals(0, row.getInt("n"))
        assertTrue(row.isNull("ratios"))
        assertTrue(row.isNull("kmh_med"))
        assertTrue(row.isNull("gps"))
        // Temperatures do not depend on the ratio filters, so an n = 0 row still has them.
        assertEquals(22.0, row.getJSONObject("temps").getJSONObject("FrontInletAirTemp").getDouble("median"), 0.0)
        assertEquals("coda_20260618_195906_T0.log", row.getString("log"))
        assertEquals("20260618T195906", row.getString("ts"))
    }

    @Test
    fun `row shape matches the prototype's drive_record plus the steering and void fields`() {
        val f = writeLog("coda_20260618_195906_T0.log", 10, 80.0, 20000)
        val h = harness()
        h.producer.onSegmentClosed(f)
        h.drain()
        val row = h.rows.single()
        assertEquals(setOf("type", "schema", "proc", "partial", "ts", "log", "n", "dur_s", "kmh_med", "steer_centre",
            "steer_centre_src", "steer_n", "steer_n_fast", "ratios", "torque_abs_mean", "torque_abs_sd",
            "band_kmh", "ratio_bands", "temps", "gps", "void", "reject"), row.keySet())
        assertTrue(row.isNull("reject"))
        assertEquals("drive", row.getString("type"))
        assertEquals(2, row.getInt("schema"))
        assertFalse(row.getBoolean("partial"))
        assertEquals(WheelRatioExtractor.RATIO_NAMES.toSet(), row.getJSONObject("ratios").keySet())
        assertEquals(row.getInt("n") / 100.0, row.getDouble("dur_s"), 0.05)
    }

    @Test
    fun `catch-up fills only segments newer than the newest recorded, skipping the live one`() {
        writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000)
        writeLog("coda_20260618_195906_T1.log", 3, 80.0, 20000)
        writeLog("coda_20260618_195906_T2.log", 3, 80.0, 20000)
        writeLog("coda_20260619_080000_T0.log", 3, 80.0, 20000)
        writeLog("coda_20260619_080000_T1.log", 3, 80.0, 20000)   // still being written
        val h = harness(recorded = setOf("coda_20260618_195906_T0.log"),
            active = "coda_20260619_080000_T1.log")
        h.producer.catchUp()
        h.drain()
        assertEquals(listOf("coda_20260618_195906_T1.log", "coda_20260618_195906_T2.log",
            "coda_20260619_080000_T0.log"), h.rows.map { it.getString("log") })
    }

    @Test
    fun `catch-up does nothing on a first install, and never duplicates a live close`() {
        val t0 = writeLog("coda_20260618_195906_T0.log", 3, 80.0, 20000)
        val first = harness()
        first.producer.catchUp()
        first.drain()
        assertTrue(first.rows.isEmpty())

        val t1 = writeLog("coda_20260618_195906_T1.log", 3, 80.0, 20000)
        val h = harness(recorded = setOf(t0.name))
        h.producer.catchUp()
        h.producer.onSegmentClosed(t1)                      // the same segment, reported live too
        h.drain()
        assertEquals(listOf(t1.name), h.rows.map { it.getString("log") })
    }

    @Test
    fun `catch-up on an epoch with no rows yet takes segments written after the SET`() {
        // Build 23's first day: SET, then every segment ended without a live close.
        val set = 1_000_000_000_000L
        writeLog("coda_20260926_154640_T0.log", 3, 80.0, 20000).setLastModified(set - 120_000)
        writeLog("coda_20260926_154817_T0.log", 3, 80.0, 20000).setLastModified(set + 200_000)
        writeLog("coda_20260926_154817_T1.log", 3, 80.0, 20000).setLastModified(set + 400_000)
        writeLog("coda_20260926_155726_T0.log", 3, 80.0, 20000).setLastModified(set + 700_000)
        val h = harness(active = "coda_20260926_155726_T0.log", epochSetAtMs = set)
        h.producer.catchUp()
        h.drain()
        // The pre-SET session is not backfilled; the live segment is left to its own close.
        assertEquals(listOf("coda_20260926_154817_T0.log", "coda_20260926_154817_T1.log"),
            h.rows.map { it.getString("log") })
    }

    @Test
    fun `cruising torque over 20 Nm is excluded from every contrast under proc 3`() {
        // 30 Nm: under v24's wide 40 Nm cap, over proc 3's 20 Nm cap on every contrast.
        val f = writeLog("coda_20260926_155726_T0.log", 10, 80.0, 20000, torqueNm = 30.0)
        val h = harness()
        h.producer.onSegmentClosed(f)
        h.drain()
        val row = h.rows.single()
        assertEquals(3, row.getInt("proc"))
        assertEquals(0, row.getInt("n"))
        assertTrue(row.isNull("ratios"))

        // The same samples under the v24 rules: the wide contrasts keep them and only F/R loses them.
        val v24 = WheelRatioExtractor.extractSegment(WheelRatioExtractor.readFrames(f), 20000.0,
            WheelRatioExtractor.Filters.V24)
        assertTrue(v24.n > 0)
        for (k in listOf("DEL", "LR_", "LFRF", "LRRR")) assertEquals(k, v24.n, v24.ratios.getValue(k).n)
        assertEquals(0, v24.ratios.getValue("FR").n)
        assertEquals(30.0, v24.torqueAbsMean!!, 0.05)
    }

    @Test
    fun `under 20 Nm every ratio has the full count`() {
        val f = writeLog("coda_20260926_155726_T0.log", 10, 80.0, 20000, torqueNm = 10.0)
        val h = harness()
        h.producer.onSegmentClosed(f)
        h.drain()
        val row = h.rows.single()
        assertEquals(row.getInt("n"), row.getJSONObject("ratios").getJSONObject("FR").getInt("n"))
    }

    @Test
    fun `segment names order numerically, not lexically`() {
        val a = DriveRowProducer.SegmentName.parse("coda_20260618_195906_T2.log")
        val b = DriveRowProducer.SegmentName.parse("coda_20260618_195906_T10.log")
        assertNotNull(a); assertNotNull(b)
        assertTrue(a!! < b!!)
        assertEquals("20260618T195906", a.sessionTs)
    }
}
