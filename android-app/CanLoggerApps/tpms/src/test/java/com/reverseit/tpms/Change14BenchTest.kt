package com.reverseit.tpms

import com.reverseit.cancore.CanFrame
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.security.MessageDigest

/**
 * Host timings for `outstanding-changes.md` Change 14 (GPS/TPMS CPU cost on the head unit): the
 * drive-row path ([WheelRatioExtractor.readFrames], [WheelRatioExtractor.extractSegment],
 * [WheelRatioExtractor.temperatures]) and the live path ([GpsRateAccumulator.observe]) on real
 * segments. Prints wall time and bytes allocated per run, and a SHA-256 of each output.
 *
 * **The digests are the equivalence check for a performance change:** run once before it with
 * `TPMS_BENCH_FP` naming a file that does not exist (the digests are written there), then after it
 * with the same file (they are compared and the test fails on any difference).
 *
 * Skipped unless `TPMS_CODA_LOGS` and `TPMS_BENCH` are set. `TPMS_BENCH` is a comma-separated list
 * of segment names without `.log`, or `default` for the list below.
 */
class Change14BenchTest {

    private val defaults = listOf(
        "coda_20260807_192700_T2", "coda_20260926_181156_T1", "coda_20261002_175334_T2",
        "coda_20261025_222333_T1",
    )

    // By reflection: unit tests compile against android.jar, which has no java.lang.management.
    private val mx = Class.forName("java.lang.management.ManagementFactory").getMethod("getThreadMXBean").invoke(null)
    private val allocatedBytes = Class.forName("com.sun.management.ThreadMXBean")
        .getMethod("getThreadAllocatedBytes", Long::class.javaPrimitiveType)
    private fun allocated() = allocatedBytes.invoke(mx, Thread.currentThread().id) as Long

    private class Run(val ms: Double, val bytes: Long)

    private fun <T> measure(block: () -> T): Pair<T, Run> {
        val a0 = allocated(); val t0 = System.nanoTime()
        val r = block()
        return r to Run((System.nanoTime() - t0) / 1e6, allocated() - a0)
    }

    private fun segments(): List<File>? {
        val dir = System.getenv("TPMS_CODA_LOGS")
        val which = System.getenv("TPMS_BENCH")
        if (dir.isNullOrEmpty() || which.isNullOrEmpty()) return null
        val names = if (which == "default") defaults else which.split(',').map { it.trim() }
        return names.map { File(dir, "$it.log") }
    }

    private fun sha(s: String): String =
        MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    /** Every field of [WheelRatioExtractor.Frames], in a fixed order, doubles as raw bits. */
    private fun digest(f: WheelRatioExtractor.Frames): String {
        val sb = StringBuilder()
        fun rows(tag: String, rows: List<WheelRatioExtractor.Row>) {
            sb.append(tag).append(rows.size).append('\n')
            for (r in rows) sb.append(r.t.toRawBits()).append(' ').append(r.bus).append(' ')
                .append(r.a.toRawBits()).append(' ').append(r.b.toRawBits()).append(' ')
                .append(r.c.toRawBits()).append('\n')
        }
        rows("front", f.front); rows("rear", f.rear); rows("steer", f.steer); rows("torque", f.torque)
        sb.append("start ").append(f.startTs).append('\n')
        for (id in f.temps.keys.sorted()) {
            sb.append("temp ").append(id).append('\n')
            for (x in f.temps.getValue(id)) sb.append(x.bus).append(' ').append(x.bytes.joinToString(",")).append('\n')
        }
        sb.append("esc ").append(f.escFaultFrames).append(" stuck ").append(f.stuckWheelFrames)
            .append(" reject ").append(f.busRejection).append('\n')
        return sha(sb.toString())
    }

    /** The frames as the app's pipeline would hand them to [GpsRateAccumulator.observe]. */
    private fun frames(file: File): List<CanFrame> {
        val out = ArrayList<CanFrame>(1_100_000)
        file.bufferedReader().useLines { lines ->
            for (line in lines) {
                val tok = line.trim().split(Regex("\\s+"))
                if (tok.size < 6 || !tok[3].startsWith("0x") || tok[4] !in setOf("s", "x")) continue
                val ts = tok[0].split(':')
                if (ts.size != 4) continue
                val sec = (ts[0].toIntOrNull() ?: continue) * 3600L + (ts[1].toIntOrNull() ?: continue) * 60L +
                    (ts[2].toIntOrNull() ?: continue)
                val ticks = ts[3].toIntOrNull() ?: continue
                val bus = tok[2].toIntOrNull() ?: continue
                val dlc = tok[5].toIntOrNull() ?: continue
                val data = ByteArray(8) { i -> (tok.getOrNull(6 + i)?.toIntOrNull(16) ?: 0).toByte() }
                val ns = sec * 1_000_000_000L + ticks * 100_000L
                out += CanFrame(bus - 1, ns / 1_000_000, tok[3].substring(2).toInt(16), tok[4] == "x", dlc,
                    data, isTx = tok[1] == "Tx", elapsedNanos = ns)
            }
        }
        return out
    }

    /**
     * One pass of the live path over a segment, with a fix at every whole second whose speed is the
     * last `0x208` rear pair seen (any bus): deterministic, which is all the digest needs.
     */
    private fun live(name: String, fs: List<CanFrame>): String {
        val acc = GpsRateAccumulator { name }
        acc.setActive(true)
        var nextFix = Long.MIN_VALUE
        var rearKmh = Double.NaN
        for (f in fs) {
            acc.observe(f)
            if (f.id == WheelRatioExtractor.ID_REAR && f.dlc >= 8) {
                val d = IntArray(8) { f.data[it].toInt() and 0xFF }
                rearKmh = (WheelRatioExtractor.wheel(d, 6) + WheelRatioExtractor.wheel(d, 4)) / 2.0 /
                    WheelRatioExtractor.COUNTS_PER_KMH
            }
            if (f.elapsedNanos >= nextFix) {
                if (nextFix != Long.MIN_VALUE && !rearKmh.isNaN()) {
                    acc.onFix(GpsRateAccumulator.Fix(f.elapsedNanos, (rearKmh / 3.6).toFloat(), 0.3f, null, null))
                }
                nextFix = (f.elapsedNanos / 1_000_000_000L + 1) * 1_000_000_000L
            }
        }
        acc.closeSegment(name)
        return acc.take(name)?.toString() ?: "null"
    }

    @Test
    fun `drive row and live path timings`() {
        val files = segments()
        assumeTrue("TPMS_CODA_LOGS / TPMS_BENCH not set", files != null)
        val digests = LinkedHashMap<String, String>()
        println("segment                      MB  | readFrames ms  MB alloc | extract+temps ms | observe ns/frame  B/frame  frames")
        for (file in files!!) {
            val name = file.nameWithoutExtension
            repeat(2) { WheelRatioExtractor.readFrames(file) }          // warm-up
            val reads = (1..3).map { measure { WheelRatioExtractor.readFrames(file) } }
            val fr = reads.last().first
            val read = reads.map { it.second }.minBy { it.ms }
            digests["$name.frames"] = digest(fr)

            val ext = (1..3).map {
                measure {
                    val c = WheelRatioExtractor.fastSteerRaw(fr).let { if (it.isEmpty()) null else WheelRatioExtractor.median(it) }
                    WheelRatioExtractor.extractSegment(fr, c) to WheelRatioExtractor.temperatures(fr)
                }
            }.map { it.second }.minBy { it.ms }

            val fs = frames(file)
            repeat(2) { live(file.name, fs) }
            val runs = (1..3).map { measure { live(file.name, fs) } }
            digests["$name.live"] = sha(runs.last().first)
            val obs = runs.map { it.second }.minBy { it.ms }

            println("%-26s %5.1f | %10.0f %10.0f | %16.1f | %16.0f %8.1f %8d".format(
                name, file.length() / 1e6, read.ms, read.bytes / 1e6, ext.ms,
                obs.ms * 1e6 / fs.size, obs.bytes.toDouble() / fs.size, fs.size))
        }

        val fpPath = System.getenv("TPMS_BENCH_FP") ?: return
        val fp = File(fpPath)
        val text = digests.entries.joinToString("\n") { "${it.key} ${it.value}" } + "\n"
        if (!fp.exists()) {
            fp.writeText(text)
            println("digests written to $fp")
        } else {
            assertEquals("outputs differ from $fp", fp.readText(), text)
            println("digests match $fp")
        }
    }
}
