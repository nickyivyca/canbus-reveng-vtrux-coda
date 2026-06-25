package com.reverseit.cancore

import android.util.Log
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Local HTTP server exposing finished log files to a companion app on the same WiFi.
 *
 * Endpoints (all require `Authorization: Bearer <token>` header):
 *   GET    /health             -> JSON {vehicle, freeBytes, totalBytes, fileCount, version}
 *   GET    /files              -> JSON [{name, size, mtime, complete}]
 *   GET    /files/<name>       -> binary file stream; 409 if active segment
 *   DELETE /files/<name>       -> 204 on success; 409 if active segment; 404 if missing
 *
 * The currently-active log segment (the file being written by [CanLoggingService]) is listed
 * with `complete=false`, but GET and DELETE on it return 409. This keeps the client side simple:
 * it sees every file, decides what to fetch, and can never disturb the live writer.
 *
 * Filenames are restricted to `[A-Za-z0-9_.-]+\.log` to prevent path traversal. Anything else
 * returns 404.
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
    private val isActiveSegment: (String) -> Boolean
) {

    companion object {
        private const val TAG = "LogFileServer"
        private const val VERSION = 1
        private val SAFE_NAME = Regex("^[A-Za-z0-9_.-]+\\.log$")
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
                session.method == NanoHTTPD.Method.GET && uri.startsWith("/files/")    -> handleGet(uri.removePrefix("/files/"))
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

    private fun handleHealth(): NanoHTTPD.Response {
        dir.mkdirs()
        val files = dir.listFiles { f -> f.isFile && f.name.endsWith(".log") } ?: emptyArray()
        val obj = JSONObject().apply {
            put("vehicle", vehicleName)
            put("freeBytes", dir.usableSpace)
            put("totalBytes", dir.totalSpace)
            put("fileCount", files.size)
            put("version", VERSION)
        }
        return json(NanoHTTPD.Response.Status.OK, obj.toString())
    }

    private fun handleList(): NanoHTTPD.Response {
        dir.mkdirs()
        val files = dir.listFiles { f -> f.isFile && f.name.endsWith(".log") } ?: emptyArray()
        val arr = JSONArray()
        files.sortedBy { it.name }.forEach { f ->
            arr.put(JSONObject().apply {
                put("name", f.name)
                put("size", f.length())
                put("mtime", f.lastModified())
                put("complete", !isActiveSegment(f.name))
            })
        }
        return json(NanoHTTPD.Response.Status.OK, arr.toString())
    }

    private fun handleGet(name: String): NanoHTTPD.Response {
        if (!SAFE_NAME.matches(name)) return text(NanoHTTPD.Response.Status.NOT_FOUND, "not found")
        val file = File(dir, name)
        if (!file.isFile) return text(NanoHTTPD.Response.Status.NOT_FOUND, "not found")
        if (isActiveSegment(name)) return text(NanoHTTPD.Response.Status.CONFLICT, "active segment")
        val r = NanoHTTPD.newFixedLengthResponse(
            NanoHTTPD.Response.Status.OK,
            "application/octet-stream",
            file.inputStream(),
            file.length()
        )
        r.addHeader("Content-Disposition", "attachment; filename=\"$name\"")
        return r
    }

    private fun handleDelete(name: String): NanoHTTPD.Response {
        if (!SAFE_NAME.matches(name)) return text(NanoHTTPD.Response.Status.NOT_FOUND, "not found")
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
