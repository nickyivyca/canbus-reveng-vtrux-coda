package com.reverseit.cancore

import org.json.JSONArray
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.HttpURLConnection
import java.net.ServerSocket
import java.net.URL
import java.net.URLEncoder

/**
 * The file server over real HTTP: `/tree` and sub-path GET reach the TPMS store and diagnostics,
 * while `/files` and DELETE stay exactly as narrow as before -- the installed companion pulls and
 * then deletes whatever `/files` lists -- and PUT adds new `.jsonl` fragments to the store only.
 */
class LogFileServerTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var root: File
    private lateinit var server: LogFileServer
    private var port = 0

    @Before
    fun start() {
        root = File(tmp.root, "CodaLogs").apply { mkdirs() }
        File(root, "coda_20260926_150000_T0.log").writeText("closed")
        File(root, "coda_20260926_150000_T1.log").writeText("open")
        File(root, "notes.txt").writeText("not served")
        File(root, "tpms").mkdirs()
        File(root, "tpms/tpms_20260926T154945_000000_full.jsonl").writeText("{\"type\":\"calibration\"}\n")
        File(root, "tpms/tpms_20260926T154945 (1).jsonl").writeText("{\"type\":\"calibration\"}\n")
        File(root, "tpms/tpms_20260926T154945_000001.jsonl.tmp").writeText("half")
        File(root, "tpms/stray.log").writeText("a log in a subfolder")
        File(root, "diag").mkdirs()
        File(root, "diag/hardware_20260926.json").writeText("{}")
        File(tmp.root, "secret.log").writeText("outside the served root")
        port = ServerSocket(0).use { it.localPort }
        server = LogFileServer(root, port, TOKEN, "coda", putDir = "tpms", onPut = { put.add(it.name) }) {
            it == "coda_20260926_150000_T1.log"
        }
        server.startServer()
    }

    /** Names [LogFileServer]'s onPut reported. */
    private val put = mutableListOf<String>()

    @After
    fun stop() = server.stopServer()

    private fun call(method: String, path: String, token: String? = TOKEN, body: ByteArray? = null): Pair<Int, ByteArray> {
        val c = URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection
        c.requestMethod = method
        token?.let { c.setRequestProperty("Authorization", "Bearer $it") }
        if (body != null) {
            c.doOutput = true
            c.setFixedLengthStreamingMode(body.size)
            c.outputStream.use { it.write(body) }
        }
        val code = c.responseCode
        val body = (if (code < 400) c.inputStream else c.errorStream)?.use { it.readBytes() } ?: ByteArray(0)
        return code to body
    }

    private fun get(path: String) = call("GET", path)
    private fun enc(name: String) = URLEncoder.encode(name, "UTF-8").replace("+", "%20")

    @Test
    fun `files lists exactly what it did -- root logs only`() {
        val (code, body) = get("/files")
        assertEquals(200, code)
        val arr = JSONArray(String(body))
        val names = (0 until arr.length()).map { arr.getJSONObject(it).getString("name") }
        assertEquals(listOf("coda_20260926_150000_T0.log", "coda_20260926_150000_T1.log"), names)
    }

    @Test
    fun `tree lists every served file recursively, and nothing else`() {
        val (code, body) = get("/tree")
        assertEquals(200, code)
        val arr = JSONArray(String(body))
        val entries = (0 until arr.length()).map { arr.getJSONObject(it) }
        assertEquals(listOf(
            "coda_20260926_150000_T0.log",
            "coda_20260926_150000_T1.log",
            "diag/hardware_20260926.json",
            "tpms/stray.log",
            "tpms/tpms_20260926T154945 (1).jsonl",
            "tpms/tpms_20260926T154945_000000_full.jsonl",
        ), entries.map { it.getString("path") })
        val open = entries.single { it.getString("path") == "coda_20260926_150000_T1.log" }
        assertEquals(false, open.getBoolean("complete"))
    }

    @Test
    fun `sub-path GET serves the store, including a re-upload name`() {
        val (c1, b1) = get("/files/tpms/tpms_20260926T154945_000000_full.jsonl")
        assertEquals(200, c1)
        assertArrayEquals(File(root, "tpms/tpms_20260926T154945_000000_full.jsonl").readBytes(), b1)
        assertEquals(200, get("/files/tpms/" + enc("tpms_20260926T154945 (1).jsonl")).first)
        assertEquals(200, get("/files/diag/hardware_20260926.json").first)
    }

    @Test
    fun `unserved types, tmp files and the active segment are refused`() {
        assertEquals(404, get("/files/notes.txt").first)
        assertEquals(404, get("/files/tpms/tpms_20260926T154945_000001.jsonl.tmp").first)
        assertEquals(409, get("/files/coda_20260926_150000_T1.log").first)
    }

    @Test
    fun `nothing outside the root is reachable`() {
        for (p in listOf("/files/../secret.log", "/files/tpms/../../secret.log", "/files/%2e%2e/secret.log",
                "/files/tpms/%2e%2e/%2e%2e/secret.log", "/files/./coda_20260926_150000_T0.log",
                "/files//coda_20260926_150000_T0.log", "/files/tpms%5c..%5c..%5csecret.log")) {
            assertEquals(p, 404, get(p).first)
        }
    }

    @Test
    fun `delete stays log-root only -- the store cannot be deleted through the server`() {
        val frag = File(root, "tpms/tpms_20260926T154945_000000_full.jsonl")
        assertEquals(404, call("DELETE", "/files/tpms/tpms_20260926T154945_000000_full.jsonl").first)
        assertEquals(404, call("DELETE", "/files/tpms/stray.log").first)
        assertEquals(404, call("DELETE", "/files/diag/hardware_20260926.json").first)
        assertTrue(frag.isFile)
        assertTrue(File(root, "tpms/stray.log").isFile)
        assertEquals(409, call("DELETE", "/files/coda_20260926_150000_T1.log").first)
        assertEquals(204, call("DELETE", "/files/coda_20260926_150000_T0.log").first)
        assertTrue(!File(root, "coda_20260926_150000_T0.log").exists())
    }

    @Test
    fun `every endpoint needs the token`() {
        for (p in listOf("/health", "/files", "/tree", "/files/tpms/tpms_20260926T154945_000000_full.jsonl")) {
            assertEquals(p, 401, call("GET", p, token = null).first)
            assertEquals(p, 401, call("GET", p, token = "wrong").first)
        }
    }

    @Test
    fun `resolveServed refuses empty, dot and dot-dot segments`() {
        for (p in listOf("", "/", "tpms/", "tpms//x.jsonl", "./x.log", "tpms/./x.jsonl", "..", "../secret.log",
                "tpms/../../secret.log", "tpms\\..\\..\\secret.log")) {
            assertNull(p, LogFileServer.resolveServed(root, p))
        }
        assertEquals(File(root, "tpms/stray.log").canonicalFile, LogFileServer.resolveServed(root, "tpms/stray.log"))
    }

    // --- PUT: corrected fragments back to the car ---------------------------------------------

    private val fragment = ("{\"type\":\"calibration\",\"ts\":\"20260926T154945\"}\n" +
        "{\"type\":\"drive\",\"log\":\"coda_20260926_155726_T0.log\",\"proc\":3}\n").toByteArray()

    private fun put(path: String, body: ByteArray = fragment, token: String? = TOKEN) =
        call("PUT", path, token, body).first

    @Test
    fun `put places a new fragment in the store, whole, and says so`() {
        assertEquals(201, put("/files/tpms/tpms_20260926T154945_000007.jsonl"))
        val f = File(root, "tpms/tpms_20260926T154945_000007.jsonl")
        assertArrayEquals(fragment, f.readBytes())
        assertTrue(File(root, "tpms").listFiles()!!.none { it.name == "tpms_20260926T154945_000007.jsonl.tmp" })
        assertEquals(listOf(f.name), put)
        assertEquals(200, get("/files/tpms/tpms_20260926T154945_000007.jsonl").first)
    }

    @Test
    fun `put never replaces a fragment`() {
        val existing = File(root, "tpms/tpms_20260926T154945_000000_full.jsonl")
        val before = existing.readBytes()
        assertEquals(409, put("/files/tpms/tpms_20260926T154945_000000_full.jsonl"))
        assertArrayEquals(before, existing.readBytes())
        assertTrue(put.isEmpty())
    }

    @Test
    fun `put writes nowhere but a jsonl name directly in the store`() {
        for (p in listOf("/files/coda_20260926_150000_T9.log", "/files/x.jsonl", "/files/diag/x.jsonl",
                "/files/tpms/x.log", "/files/tpms/x.json", "/files/tpms/sub/x.jsonl", "/files/tpms/../x.jsonl",
                "/files/tpms/%2e%2e/x.jsonl", "/files/tpms/.jsonl", "/files/tpms/..jsonl",
                "/files/tpms/x.jsonl.tmp", "/files/tpms%5cx.jsonl")) {
            assertEquals(p, 403, put(p))
        }
        assertTrue(put.isEmpty())
        assertEquals(setOf("tpms", "diag", "coda_20260926_150000_T0.log", "coda_20260926_150000_T1.log", "notes.txt"),
            root.list()!!.toSet())
    }

    @Test
    fun `put refuses a body the store could not read, and needs the token`() {
        assertEquals(400, put("/files/tpms/a.jsonl", "{\"type\":\"drive\"}\nnot json\n".toByteArray()))
        assertEquals(400, put("/files/tpms/b.jsonl", "[1, 2]\n".toByteArray()))
        assertEquals(401, put("/files/tpms/c.jsonl", token = null))
        assertEquals(401, put("/files/tpms/c.jsonl", token = "wrong"))
        assertTrue(File(root, "tpms").list()!!.none { it.startsWith("a.") || it.startsWith("b.") || it.startsWith("c.") })
        assertTrue(put.isEmpty())
    }

    @Test
    fun `put is refused outright by a server with no store`() {
        val p2 = ServerSocket(0).use { it.localPort }
        val plain = LogFileServer(root, p2, TOKEN, "vtrux") { false }
        plain.startServer()
        try {
            val c = URL("http://127.0.0.1:$p2/files/tpms/x.jsonl").openConnection() as HttpURLConnection
            c.requestMethod = "PUT"
            c.setRequestProperty("Authorization", "Bearer $TOKEN")
            c.doOutput = true
            c.setFixedLengthStreamingMode(fragment.size)
            c.outputStream.use { it.write(fragment) }
            assertEquals(404, c.responseCode)
        } finally {
            plain.stopServer()
        }
        assertTrue(!File(root, "tpms/x.jsonl").exists())
    }

    private companion object {
        const val TOKEN = "t0ken"
    }
}
