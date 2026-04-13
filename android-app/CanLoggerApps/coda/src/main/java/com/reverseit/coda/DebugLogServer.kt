package com.reverseit.coda

import android.util.Log
import java.io.PrintWriter
import java.net.ServerSocket
import java.net.Socket
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.LinkedBlockingQueue

object DebugLog {
    private const val TAG = "DebugLog"
    private const val PORT = 9876
    private const val QUEUE_CAPACITY = 2000

    private val queue = LinkedBlockingQueue<String>(QUEUE_CAPACITY)
    @Volatile private var started = false

    fun start() {
        if (started) return
        started = true
        Thread(::serverLoop, "DebugLogServer").apply { isDaemon = true; start() }
    }

    fun log(tag: String, msg: String) {
        Log.d(tag, msg)
        val line = "${timestamp()} D/$tag: $msg\n"
        queue.offer(line) // drops silently if full
    }

    fun w(tag: String, msg: String) {
        Log.w(tag, msg)
        val line = "${timestamp()} W/$tag: $msg\n"
        queue.offer(line)
    }

    fun e(tag: String, msg: String, tr: Throwable? = null) {
        Log.e(tag, msg, tr)
        val sb = StringBuilder("${timestamp()} E/$tag: $msg\n")
        var t: Throwable? = tr
        var depth = 0
        while (t != null && depth < 8) {
            sb.append("  caused by ${t.javaClass.name}: ${t.message}\n")
            t.stackTrace.take(10).forEach { sb.append("    at $it\n") }
            t = t.cause
            depth++
        }
        queue.offer(sb.toString())
    }

    private fun timestamp(): String =
        SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(Date())

    private fun serverLoop() {
        while (true) {
            try {
                ServerSocket(PORT).use { server ->
                    Log.i(TAG, "Listening on port $PORT")
                    while (true) {
                        val client: Socket = server.accept()
                        Log.i(TAG, "Debug client connected: ${client.inetAddress}")
                        serveClient(client)
                        Log.i(TAG, "Debug client disconnected")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Server error, restarting: ${e.message}")
                Thread.sleep(2000)
            }
        }
    }

    private fun serveClient(socket: Socket) {
        try {
            socket.use {
                val writer = PrintWriter(socket.getOutputStream(), true)
                writer.print("=== Coda CAN debug log ===\n")
                // Drain any queued lines first, then block on new ones
                while (!socket.isClosed) {
                    val line = queue.poll(5, java.util.concurrent.TimeUnit.SECONDS) ?: continue
                    writer.print(line)
                    if (writer.checkError()) break
                }
            }
        } catch (_: Exception) {}
    }
}
