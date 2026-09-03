package com.reverseit.p914

import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * Forces the phone's USB data role to host (dfp) via Magisk root, so a self-powered VCU on the
 * OTG port enumerates even while the phone is charging from a powered hub.
 *
 * Why this exists: with a powered hub in the path the phone negotiates power_role=sink and
 * data_role=device, so it never enumerates anything. `supported_modes` says `ufp dfp`, so host is
 * available -- it simply is not selected.
 *
 * ## Differences from `:vtrux`'s `attemptRootOtgRecovery()`, on purpose
 *
 * 1. **No `[ -w ]` guard.** That guard is worse than useless here. `test -w` checks only DAC
 *    permissions, which root bypasses on every file, so it returns true even when SELinux will
 *    refuse the write. It passes, the write is attempted, SELinux denies it, and the script exits
 *    non-zero -- which `:vtrux` logs as "su exited N" and the notes attribute to a lost Magisk
 *    grant. Measured on this device 2026-08-13: `test -w` returns 0 while the write is denied.
 *
 * 2. **Reports what actually happened.** Captures stdout and stderr, and reads the role back
 *    afterwards, so success is observed rather than inferred from an exit code. A role toggle
 *    that silently does nothing is exactly the failure mode being chased here.
 *
 * Fails gracefully without root: [forceHost] returns a Result carrying the error.
 */
object RootOtg {

    private const val TAG = "P914"
    private const val BASE = "/sys/class/dual_role_usb/otg_default"

    data class Result(
        val exitCode: Int,
        val output: String,
        val modeAfter: String?,
        val roleAfter: String?,
    ) {
        /** Host mode is only claimed when the node reads back as such. */
        val isHost: Boolean get() = modeAfter == "dfp" || roleAfter == "host"
    }

    /** Current role, or null if it cannot be read. */
    fun readState(): String? = runSu("cat $BASE/mode $BASE/data_role")
        .takeIf { it.first == 0 }?.second?.trim()?.replace("\n", " / ")

    /**
     * Toggle ufp then dfp. The intermediate ufp step is what re-enumerates a hub that is holding
     * its downstream ports down; going straight to dfp often leaves a stuck hub stuck.
     */
    fun forceHost(): Result {
        val script = listOf(
            "echo '--- before ---'",
            "cat $BASE/mode $BASE/data_role $BASE/power_role 2>&1",
            "echo '--- writing ufp ---'",
            "echo ufp > $BASE/mode 2>&1 || echo \"ufp write FAILED rc=\$?\"",
            "sleep 1",
            "echo '--- writing dfp ---'",
            "echo dfp > $BASE/mode 2>&1 || echo \"dfp write FAILED rc=\$?\"",
            "sleep 2",
            "echo '--- after ---'",
            "cat $BASE/mode $BASE/data_role 2>&1",
            "echo '--- usb devices ---'",
            "ls /sys/bus/usb/devices/ 2>&1",
        ).joinToString("; ")

        val (rc, out) = runSu(script)
        Log.i(TAG, "RootOtg.forceHost rc=$rc\n$out")

        // Read back rather than trusting rc: the writes can fail while the script still exits 0.
        val after = runSu("cat $BASE/mode; cat $BASE/data_role")
        val lines = after.second.trim().lines()
        return Result(
            exitCode = rc,
            output = out.trim(),
            modeAfter = lines.getOrNull(0)?.trim(),
            roleAfter = lines.getOrNull(1)?.trim(),
        )
    }

    /** Runs [cmd] under `su -c`, returning (exitCode, stdout+stderr). */
    private fun runSu(cmd: String): Pair<Int, String> = try {
        val proc = Runtime.getRuntime().exec(arrayOf("su", "-c", cmd))
        val out = StringBuilder()
        BufferedReader(InputStreamReader(proc.inputStream)).use { r ->
            r.forEachLine { out.appendLine(it) }
        }
        BufferedReader(InputStreamReader(proc.errorStream)).use { r ->
            r.forEachLine { out.appendLine("stderr: $it") }
        }
        proc.waitFor() to out.toString()
    } catch (e: Exception) {
        // No su binary, or the Magisk prompt was denied.
        -1 to "su unavailable: ${e.message}"
    }
}
