package com.reverseit.cancore

import android.util.Log
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException

/**
 * Local HTTP server exposing the log directory to a companion app on the same WiFi -- the finished
 * log segments, and read-only, everything else in the directory tree of a served type.
 *
 * Endpoints (all require `Authorization: Bearer <token>` header):
 *   GET    /health             -> JSON {vehicle, freeBytes, totalBytes, fileCount, version}
 *   GET    /files              -> JSON [{name, size, mtime, complete}]  log root, `.log` only, flat
 *   GET    /tree               -> JSON [{path, size, mtime, complete}]  recursive, every served type
 *   GET    /files/<path>       -> binary file stream; 409 if active segment
 *   PUT    /files/<sub>/<name> -> 201; only when [putDir] is set, and only a new `.jsonl` there
 *   DELETE /files/<name>       -> 204 on success; 409 if active segment; 404 if missing
 *
 * **PUT exists so corrected data can go back to the car and still be used** (owner, 2026-09-27;
 * TPMS spec section 4, "Transport"). A drive row re-derived offline goes back as a new fragment
 * that supersedes the old one in the store's dedupe; nothing is overwritten or deleted. It is the
 * first route that writes to the device, so it is narrow:
 *  - only into [putDir] (Coda: `tpms`), flat -- a name, no deeper path -- and only `.jsonl`;
 *    every other path is 403, and with no [putDir] (the other apps) PUT is 404;
 *  - **create-only**: an existing name is 409. The store is immutable fragments, so there is no
 *    legitimate overwrite, and refusing one means a mistaken push cannot destroy a fragment the
 *    sync has not uploaded yet;
 *  - `Content-Length` required and at most [MAX_PUT_BYTES]; every non-blank line must be a JSON
 *    object, since a line the store cannot parse would be dropped silently;
 *  - atomic: written to `<name>.tmp`, fsynced, renamed, as the store's own writes are, so neither
 *    the store nor SeaDrive can see a partial file. Then [onPut] tells the app to re-read.
 *
 * *Create-only is check-then-rename, not an atomic link: the store picks a new name the same way,
 * so a collision needs both to choose one name in the same instant. minSdk 21 has no
 * `java.nio.file` move-without-replace.*
 *
 * **Reading is broad; deleting and the old listing stay narrow.** Since 2026-09-26 `GET /tree`
 * lists recursively over [SERVED_EXTENSIONS] (so `CodaLogs/tpms/` and `CodaLogs/diag/` can be read
 * and verified remotely) and `GET /files/<path>` accepts sub-paths. Two things deliberately did not
 * change:
 *
 *  - **`/files` lists exactly what it did** -- log root, `.log`, non-recursive. The companion
 *    already installed pulls whatever `/files` lists and then DELETEs it. Had `/files` become
 *    recursive, every TPMS fragment would be listed, the DELETE refused, the name never added to the
 *    companion's synced index, and every fragment re-downloaded on every sync, indefinitely.
 *  - **DELETE stays log-root only, `.log` only, non-recursive** ([SAFE_LOG_NAME], which matches no
 *    `/`). The TPMS store is the one record the CAN logs cannot regenerate, so the server refuses to
 *    delete it whatever any client does; the protection does not depend on a client behaving.
 *
 * Sub-paths are resolved by [resolveServed]: empty, `.` and `..` segments are refused, the result
 * is canonicalised, and it must lie under [dir]. Anything else is a 404.
 *
 * The currently-active log segment (the file being written by [CanLoggingService]) is listed with
 * `complete=false`, and GET and DELETE on it return 409. Files still being written by the TPMS store
 * are `.tmp` and not a served type, so they are never listed.
 *
 * NanoHTTPD binds to 0.0.0.0 by default, so the server is reachable on every interface — including
 * the head unit's hotspot AP interface, which is what the companion app talks to.
 *
 * NanoHTTPD is held as a private member rather than a supertype so consumer modules of cancore
 * don't need NanoHTTPD on their compile classpath to instantiate this class.
 */
class LogFileServer(
    private val dir: File,
    private val port: Int,
    private val token: String,
    private val vehicleName: String,
    /** The one subdirectory of [dir] that PUT may add files to, or null for no PUT at all. */
    private val putDir: String? = null,
    /** Called with each file a PUT placed, after the rename. */
    private val onPut: (File) -> Unit = {},
    private val isActiveSegment: (String) -> Boolean
) {

    companion object {
        private const val TAG = "LogFileServer"
        private const val VERSION = 3

        /** Largest PUT body. A `_full` fragment of a long epoch is well under 1 MB. */
        const val MAX_PUT_BYTES = 8L * 1024 * 1024

        /** A name PUT accepts inside [putDir]: one path segment, `.jsonl`. */
        private val SAFE_PUT_NAME = Regex("^[A-Za-z0-9][A-Za-z0-9_.-]*\\.jsonl$")

        /** File types `/tree` lists and `GET /files/<path>` serves. `.tmp` is deliberately absent. */
        val SERVED_EXTENSIONS = setOf("log", "jsonl", "json")

        /**
         * The only names DELETE accepts: a `.log` in the log root. The character class matches no
         * `/`, so nothing in a subdirectory -- the TPMS store above all -- can be deleted through
         * this server.
         */
        private val SAFE_LOG_NAME = Regex("^[A-Za-z0-9_.-]+\\.log$")

        /**
         * [path] (relative, `/`-separated, already URL-decoded) as a served file under [root], or
         * null. Refuses empty, `.` and `..` segments and backslashes, requires a served extension,
         * then canonicalises and asserts the result lies under [root] -- so neither a crafted path
         * nor a symlink can reach outside it.
         */
        fun resolveServed(root: File, path: String): File? {
            if (path.isEmpty() || '\\' in path || '\u0000' in path) return null
            val segments = path.split('/')
            if (segments.any { it.isEmpty() || it == "." || it == ".." }) return null
            if (segments.last().substringAfterLast('.', "").lowercase() !in SERVED_EXTENSIONS) return null
            return try {
                val base = root.canonicalFile
                val f = File(base, segments.joinToString(File.separator)).canonicalFile
                if (f.path.startsWith(base.path + File.separator) && f.isFile) f else null
            } catch (_: IOException) {
                null
            }
        }

        /** Every served file under [root], as `/`-separated paths relative to it, sorted. */
        fun servedTree(root: File): List<Pair<String, File>> {
            val base = try { root.canonicalFile } catch (_: IOException) { return emptyList() }
            return base.walkTopDown()
                .filter { it.isFile }
                .mapNotNull { f ->
                    val rel = f.relativeTo(base).invariantSeparatorsPath
                    resolveServed(base, rel)?.let { rel to f }
                }
                .sortedBy { it.first }
                .toList()
        }
    }

    private val server = object : NanoHTTPD(port) {
        override fun serve(session: IHTTPSession): Response = handle(session)
    }

    private fun handle(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        return try {
            if (!checkAuth(session)) return text(NanoHTTPD.Response.Status.UNAUTHORIZED, "unauthorized")
            val uri = session.uri.trimEnd('/')
            when {
                session.method == NanoHTTPD.Method.GET && uri == "/health"     -> handleHealth()
                session.method == NanoHTTPD.Method.GET && uri == "/files"      -> handleList()
                session.method == NanoHTTPD.Method.GET && uri == "/tree"       -> handleTree()
                session.method == NanoHTTPD.Method.GET && uri.startsWith("/files/")    -> handleGet(uri.removePrefix("/files/"))
                // Connection: close, so a refusal sent before the body was read cannot leave that
                // body in the stream to be parsed as the next request.
                session.method == NanoHTTPD.Method.PUT && uri.startsWith("/files/") && putDir != null ->
                    handlePut(uri.removePrefix("/files/"), session).also { it.addHeader("Connection", "close") }
                session.method == NanoHTTPD.Method.DELETE && uri.startsWith("/files/") -> handleDelete(uri.removePrefix("/files/"))
                else -> text(NanoHTTPD.Response.Status.NOT_FOUND, "not found")
            }
        } catch (e: Exception) {
            Log.e(TAG, "serve error: ${e.message}", e)
            text(NanoHTTPD.Response.Status.INTERNAL_ERROR, "server error: ${e.message}")
        }
    }

    private fun checkAuth(session: NanoHTTPD.IHTTPSession): Boolean {
        val header = session.headers["authorization"] ?: return false
        return header == "Bearer $token"
    }

    private fun rootLogs(): Array<File> {
        dir.mkdirs()
        return dir.listFiles { f -> f.isFile && f.name.endsWith(".log") } ?: emptyArray()
    }

    private fun handleHealth(): NanoHTTPD.Response {
        val obj = JSONObject().apply {
            put("vehicle", vehicleName)
            put("freeBytes", dir.usableSpace)
            put("totalBytes", dir.totalSpace)
            put("fileCount", rootLogs().size)
            put("version", VERSION)
        }
        return json(NanoHTTPD.Response.Status.OK, obj.toString())
    }

    /** The log root's `.log` files only, non-recursive: what the pull-then-DELETE companion syncs. */
    private fun handleList(): NanoHTTPD.Response {
        val arr = JSONArray()
        rootLogs().sortedBy { it.name }.forEach { f ->
            arr.put(JSONObject().apply {
                put("name", f.name)
                put("size", f.length())
                put("mtime", f.lastModified())
                put("complete", !isActiveSegment(f.name))
            })
        }
        return json(NanoHTTPD.Response.Status.OK, arr.toString())
    }

    private fun handleTree(): NanoHTTPD.Response {
        dir.mkdirs()
        val arr = JSONArray()
        servedTree(dir).forEach { (path, f) ->
            arr.put(JSONObject().apply {
                put("path", path)
                put("size", f.length())
                put("mtime", f.lastModified())
                put("complete", !isActiveSegment(path))
            })
        }
        return json(NanoHTTPD.Response.Status.OK, arr.toString())
    }

    private fun handleGet(path: String): NanoHTTPD.Response {
        val file = resolveServed(dir, path) ?: return text(NanoHTTPD.Response.Status.NOT_FOUND, "not found")
        if (isActiveSegment(path)) return text(NanoHTTPD.Response.Status.CONFLICT, "active segment")
        val r = NanoHTTPD.newFixedLengthResponse(
            NanoHTTPD.Response.Status.OK,
            "application/octet-stream",
            file.inputStream(),
            file.length()
        )
        r.addHeader("Content-Disposition", "attachment; filename=\"${file.name.replace("\"", "")}\"")
        return r
    }

    private fun handlePut(path: String, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val sub = putDir ?: return text(NanoHTTPD.Response.Status.NOT_FOUND, "not found")
        val name = path.removePrefix("$sub/")
        if (name == path || !SAFE_PUT_NAME.matches(name)) {
            return text(NanoHTTPD.Response.Status.FORBIDDEN, "PUT accepts only $sub/<name>.jsonl")
        }
        val len = session.headers["content-length"]?.toLongOrNull()
            ?: return text(NanoHTTPD.Response.Status.LENGTH_REQUIRED, "Content-Length required")
        if (len !in 1..MAX_PUT_BYTES) {
            return text(NanoHTTPD.Response.Status.PAYLOAD_TOO_LARGE, "body must be 1..$MAX_PUT_BYTES bytes")
        }
        val body = ByteArray(len.toInt())
        var got = 0
        val input = session.inputStream
        while (got < body.size) {
            val r = input.read(body, got, body.size - got)
            if (r < 0) return text(NanoHTTPD.Response.Status.BAD_REQUEST, "body shorter than Content-Length")
            got += r
        }
        val bad = String(body, Charsets.UTF_8).lines().withIndex().firstOrNull { (_, line) ->
            line.isNotBlank() && try { JSONObject(line); false } catch (_: Exception) { true }
        }
        if (bad != null) {
            return text(NanoHTTPD.Response.Status.BAD_REQUEST, "line ${bad.index + 1} is not a JSON object")
        }
        val folder = File(dir, sub)
        synchronized(this) {
            folder.mkdirs()
            val target = File(folder, name)
            // Containment, as for GET: the folder itself could be a link somewhere else.
            val base = dir.canonicalFile
            if (!target.canonicalFile.path.startsWith(base.path + File.separator)) {
                return text(NanoHTTPD.Response.Status.FORBIDDEN, "outside the served root")
            }
            if (target.exists()) return text(NanoHTTPD.Response.Status.CONFLICT, "exists; PUT never replaces")
            val tmp = File(folder, "$name.tmp")
            java.io.FileOutputStream(tmp).use { out ->
                out.write(body)
                out.fd.sync()
            }
            if (target.exists() || !tmp.renameTo(target)) {
                tmp.delete()
                return text(NanoHTTPD.Response.Status.CONFLICT, "could not place $name")
            }
            Log.i(TAG, "PUT $sub/$name (${body.size} bytes)")
            onPut(target)
        }
        return text(NanoHTTPD.Response.Status.CREATED, "")
    }

    private fun handleDelete(name: String): NanoHTTPD.Response {
        if (!SAFE_LOG_NAME.matches(name)) return text(NanoHTTPD.Response.Status.NOT_FOUND, "not found")
        val file = File(dir, name)
        if (!file.isFile) return text(NanoHTTPD.Response.Status.NOT_FOUND, "not found")
        if (isActiveSegment(name)) return text(NanoHTTPD.Response.Status.CONFLICT, "active segment")
        return if (file.delete()) {
            Log.i(TAG, "deleted ${file.name}")
            text(NanoHTTPD.Response.Status.NO_CONTENT, "")
        } else {
            text(NanoHTTPD.Response.Status.INTERNAL_ERROR, "delete failed")
        }
    }

    private fun json(status: NanoHTTPD.Response.IStatus, body: String) =
        NanoHTTPD.newFixedLengthResponse(status, "application/json", body)

    private fun text(status: NanoHTTPD.Response.IStatus, body: String) =
        NanoHTTPD.newFixedLengthResponse(status, "text/plain", body)

    fun startServer() {
        try {
            server.start(NanoHTTPD.SOCKET_READ_TIMEOUT, true)
            Log.i(TAG, "Listening on port $port, dir=${dir.absolutePath}")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start server: ${e.message}", e)
        }
    }

    fun stopServer() {
        server.stop()
    }
}
