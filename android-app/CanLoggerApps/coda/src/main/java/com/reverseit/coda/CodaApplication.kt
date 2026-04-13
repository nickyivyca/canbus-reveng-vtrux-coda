package com.reverseit.coda

import android.app.Application
import com.reverseit.cancore.CanPipelineManager
import java.io.File

class CodaApplication : Application() {
    val pipeline = CanPipelineManager()

    override fun onCreate() {
        super.onCreate()
        DebugLog.start()

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
