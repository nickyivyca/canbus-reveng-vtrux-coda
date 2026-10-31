package com.reverseit.tpms

import android.util.Log

/**
 * Logging for this module. Defaults to `android.util.Log`; the host app points [sink] at its own
 * logger (the Coda app's `DebugLog`, which also streams to the debug server). Kept as a sink rather
 * than a dependency because this module must not depend on any app.
 */
object TpmsLog {
    @Volatile
    var sink: (tag: String, msg: String, error: Throwable?) -> Unit = { tag, msg, e ->
        if (e == null) Log.d(tag, msg) else Log.e(tag, msg, e)
    }

    fun d(tag: String, msg: String) = sink(tag, msg, null)
    fun e(tag: String, msg: String, error: Throwable? = null) = sink(tag, msg, error)
}
