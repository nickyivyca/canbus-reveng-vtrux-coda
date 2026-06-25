package com.reverseit.coda

import android.app.Application
import com.reverseit.cancore.BuildConfig
import com.reverseit.cancore.CanLoggingService
import com.reverseit.cancore.CanPipelineManager
import com.reverseit.cancore.LogFileServer
import java.io.File

class CodaApplication : Application() {
    val pipeline = CanPipelineManager()
    private var fileServer: LogFileServer? = null

    override fun onCreate() {
        super.onCreate()
        DebugLog.start()

        // Local file server — companion phone pulls completed log files over the head unit's
        // hotspot. Listens on every interface; the AP interface is what the phone reaches.
        // Log dir mirrors CanLoggingService default for "coda".
        val logDir = File(getExternalFilesDir(null), "CodaLogs")
        fileServer = LogFileServer(
            dir = logDir,
            port = 9877,
            token = BuildConfig.SYNC_TOKEN,
            vehicleName = "coda",
            isActiveSegment = { name -> CanLoggingService.currentSegmentName == name }
        ).also { it.startServer() }
        DebugLog.log("App", "LogFileServer started on 9877, dir=${logDir.absolutePath}")

        // Replay any crash log from the previous run before setting up the new handler
        val crashFile = File(cacheDir, "last_crash.txt")
        if (crashFile.exists()) {
            DebugLog.log("CRASH", "--- crash from previous run ---")
            crashFile.forEachLine { DebugLog.log("CRASH", it) }
            DebugLog.log("CRASH", "--- end of previous crash ---")
            crashFile.delete()
        }

        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            // Write to file first — survives process death
            try {
                val sb = StringBuilder("Thread: ${thread.name}\n")
                var t: Throwable? = throwable
                var depth = 0
                while (t != null && depth < 8) {
                    sb.append("caused by ${t.javaClass.name}: ${t.message}\n")
                    t.stackTrace.take(20).forEach { sb.append("  at $it\n") }
                    t = t.cause
                    depth++
                }
                crashFile.writeText(sb.toString())
            } catch (_: Exception) {}
            DebugLog.e("CRASH", "Uncaught on ${thread.name}", throwable)
            Thread.sleep(300)
            defaultHandler?.uncaughtException(thread, throwable)
        }

        DebugLog.log("App", "CodaApplication.onCreate complete")
    }

    override fun onTerminate() {
        pipeline.shutdown()
        super.onTerminate()
    }
}
