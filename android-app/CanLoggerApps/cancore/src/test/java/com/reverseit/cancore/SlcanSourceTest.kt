package com.reverseit.cancore

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.zip.GZIPInputStream
import kotlin.concurrent.thread

/**
 * A4a and A5a: [SlcanSource] over a real socket, and a full round trip through the BUSMASTER
 * writer and reader.
 *
 * The oracle is A1's frame digest. If a capture pushed through a TCP socket and reassembled by
 * [SlcanSource] produces the same digest as the same capture fed in one buffer, the transport
 * added nothing and lost nothing.
 *
 * The socket is doing real work here that the A1 chunk-invariance test does not: TCP segments the
 * stream on its own terms, `read()` returns short, and the connection closes mid-stream at the
 * end. Those are stream-lifecycle behaviours rather than parsing ones.
 */
class SlcanSourceTest {

    private val fixture = "serial-full-slcan.log.gz"

    // ---------------------------------------------------------------- A4a

    @Test
    fun pumpOverLoopbackSocketMatchesInProcessDigest() {
        val data = readFixture(fixture)

        val direct = SlcanSource(clock = { 0L }) { }
        direct.feed(data)

        val received = ArrayList<CanFrame>(direct.stats.frames.toInt())
        val viaSocket = serveAndPump(data) { SlcanSource(clock = { 0L }) { received.add(it) } }

        assertEquals("digest over the socket must equal the in-process digest",
            direct.digest, viaSocket.digest)
        assertEquals(direct.stats.frames, viaSocket.stats.frames)
        assertEquals(direct.stats.integrity, viaSocket.stats.integrity)
        assertEquals(direct.stats.csv, viaSocket.stats.csv)
        assertEquals(direct.stats.malformed, viaSocket.stats.malformed)
        assertEquals(direct.stats.blocksChecked, viaSocket.stats.blocksChecked)
        assertEquals(direct.stats.frames, received.size.toLong())

        // This fixture is the one recorded as having no link damage; the socket must not
        // manufacture any.
        assertEquals(0L, viaSocket.stats.blocksCrcBad)
        assertEquals(0L, viaSocket.stats.blocksCountBad)
    }

    @Test
    fun flowDeliversTheSameFramesAsPump() {
        val data = readFixture(fixture)

        val pumped = ArrayList<CanFrame>()
        SlcanSource(clock = { 0L }) { pumped.add(it) }.pump(ByteArrayInputStream(data))

        val flowed = runBlocking {
            slcanFrames(ByteArrayInputStream(data)).toList()
        }

        assertEquals(pumped.size, flowed.size)
        assertTrue("flow must deliver frames", flowed.isNotEmpty())
        for (i in pumped.indices) {
            assertEquals("frame $i id", pumped[i].id, flowed[i].id)
            assertEquals("frame $i extended", pumped[i].isExtended, flowed[i].isExtended)
            assertEquals("frame $i dlc", pumped[i].dlc, flowed[i].dlc)
            assertTrue("frame $i data",
                pumped[i].data.copyOf(pumped[i].dlc).contentEquals(flowed[i].data.copyOf(flowed[i].dlc)))
        }
    }

    @Test
    fun tinyReadsDoNotChangeTheResult() {
        val data = readFixture(fixture)
        val whole = SlcanSource(clock = { 0L }) { }
        whole.feed(data)

        // One byte per read is the pathological case a socket or USB stack can produce.
        val dribbled = SlcanSource(readBufferBytes = 1, clock = { 0L }) { }
        dribbled.pump(ByteArrayInputStream(data))

        assertEquals(whole.digest, dribbled.digest)
        assertEquals(whole.stats.frames, dribbled.stats.frames)
        assertEquals(whole.stats.blocksCrcBad, dribbled.stats.blocksCrcBad)
    }

    // ---------------------------------------------------------------- A5a

    /**
     * The logging path end to end, through the real writer and the real reader.
     *
     * This matters more for the 914 than for the vehicles `BusmasterWriter` was built against:
     * 79% of this stream is 29-bit extended IDs, where `:coda` and `:vtrux` are almost entirely
     * 11-bit. The `x` type column was therefore barely exercised before now.
     */
    @Test
    fun busmasterRoundTripPreservesEveryFrame() {
        val data = readFixture(fixture)

        val original = ArrayList<CanFrame>()
        var t = 1_700_000_000_000L
        SlcanSource(clock = { t += 1; t }) { original.add(it) }.pump(ByteArrayInputStream(data))
        assertTrue("fixture should yield frames", original.size > 1000)

        val extended = original.count { it.isExtended }
        assertTrue("fixture should be mostly extended IDs, got $extended of ${original.size}",
            extended > original.size / 2)

        val out = File("build/tmp/slcan-roundtrip.log")
        out.parentFile?.mkdirs()
        val writer = BusmasterWriter(out, numBuses = 1, bitrateKbps = 500,
            sessionStartMs = 1_700_000_000_000L)
        writer.open()
        original.forEach { writer.writeFrame(it) }
        writer.close()

        val parsed = out.readLines().mapNotNull { BusmasterReader.parseLine(it) }
        assertEquals("every written frame must parse back", original.size, parsed.size)

        for (i in original.indices) {
            val a = original[i]
            val b = parsed[i].frame
            assertEquals("frame $i id", a.id, b.id)
            assertEquals("frame $i extended", a.isExtended, b.isExtended)
            assertEquals("frame $i dlc", a.dlc, b.dlc)
            assertTrue("frame $i data",
                a.data.copyOf(a.dlc).contentEquals(b.data.copyOf(b.dlc)))
        }
        out.delete()
    }

    // ---------------------------------------------------------------- A3 seam

    /**
     * [SlcanFrameSource] must present the same shape [CanLoggingService] consumes, so a vehicle
     * with no gs_usb dongle can use the logging path without the pipeline being touched.
     */
    @Test
    fun slcanFrameSourceSatisfiesTheLoggingSeam() {
        val data = readFixture(fixture)
        val src = SlcanFrameSource(clock = { 0L })

        // Consumed through the CanFrameSource interface only -- the same way the service sees it.
        val seam: CanFrameSource = src
        assertEquals("no stream yet", 0, seam.activeDeviceCount())
        assertEquals(1, seam.activeBusCount())

        val collected = java.util.Collections.synchronizedList(ArrayList<CanFrame>())
        val scope = CoroutineScope(Dispatchers.Default)
        val job = scope.launch { seam.frames.collect { collected.add(it) } }
        Thread.sleep(200)          // let the collector subscribe before frames start flowing
        src.pump(ByteArrayInputStream(data))
        Thread.sleep(300)          // let the last emissions drain
        job.cancel()

        assertEquals("stream ended", 0, seam.activeDeviceCount())
        assertTrue("frames should have been decoded", src.stats.frames > 1000)
        assertEquals("declared-clean fixture", 0L, src.stats.blocksCrcBad)
        assertTrue("collector should have received frames, got ${collected.size}",
            collected.isNotEmpty())
    }

    // ---------------------------------------------------------------- helpers

    /** Serve [data] over a loopback socket and pump it through a fresh source. */
    private fun serveAndPump(data: ByteArray, make: () -> SlcanSource): SlcanSource {
        val server = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
        val writer = thread(start = true) {
            server.accept().use { s ->
                // Chunked deliberately: a single sendall would let TCP coalesce it into a shape
                // that never crosses a frame boundary awkwardly.
                var off = 0
                val out = s.getOutputStream()
                while (off < data.size) {
                    val n = minOf(1024, data.size - off)
                    out.write(data, off, n)
                    out.flush()
                    off += n
                }
            }
        }
        val source = make()
        Socket("127.0.0.1", server.localPort).use { client ->
            source.pump(client.getInputStream())
        }
        writer.join(30_000)
        server.close()
        return source
    }

    private fun readFixture(basename: String): ByteArray {
        val stream = javaClass.getResourceAsStream("/slcan/$basename")
            ?: throw IllegalStateException("missing fixture /slcan/$basename")
        val out = ByteArrayOutputStream()
        GZIPInputStream(stream).use { gz ->
            val buf = ByteArray(1 shl 16)
            while (true) {
                val n = gz.read(buf)
                if (n < 0) break
                out.write(buf, 0, n)
            }
        }
        return out.toByteArray()
    }
}
