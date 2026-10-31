package com.reverseit.cancore

import java.io.BufferedWriter
import java.io.File
import java.io.FileWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Writes CAN frames to a BUSMASTER-format log file.
 *
 * Format matches tools/can_logger.py BUSMASTERWriter so existing canre tools
 * (survey.py, analyze_id.py, etc.) can parse the logs without modification.
 *
 * Timestamps are HH:MM:SS:TTTT, TTTT = 10 kHz ticks (0.1 ms), measured from **the first frame
 * written to this file**, and the header's START DATE AND TIME is that frame's wall-clock time --
 * so header + offset is each frame's absolute time.
 *
 * **Why the origin is the first frame and not the moment the file opened.** Frames are stamped
 * when received and written a little later. When a segment rolls, frames already received but not
 * yet written carry stamps from *before* the new file opened, and measuring from the open time gave
 * them negative offsets (`00:00:00:-160`), which every parser rejects -- a few frames silently lost
 * at every 5-minute boundary. With the origin at the first frame, and the pipeline emitting frames
 * in stamp order ([CanPipelineManager]), no frame can precede the origin.
 *
 * Offsets come from [CanFrame.elapsedNanos] in integer arithmetic: monotonic, so a wall-clock
 * correction mid-file cannot produce a negative or jumping offset, and exact to the tick (the old
 * `Double` path truncated 3.404 s to `4039`).
 *
 * [sessionStartMs] is used only for the header of a file that is closed before any frame arrives.
 */
class BusmasterWriter(
    private val file: File,
    private val numBuses: Int,
    private val bitrateKbps: Int,
    private val sessionStartMs: Long
) {
    private var writer: BufferedWriter? = null
    var bytesWritten: Long = 0L
        private set
    var frameCount: Long = 0L
        private set

    /**
     * Frames that arrived with a monotonic stamp earlier than one already written. The pipeline's
     * stamp-and-emit lock makes this impossible for its own frames, so a non-zero count means some
     * source is emitting out of order -- a defect to find, not a normal condition. Such a frame
     * is written at the previous frame's offset, because the format cannot express a step back.
     */
    var outOfOrderFrames: Long = 0L
        private set

    private var originNanos: Long? = null
    private var lastNanos = Long.MIN_VALUE

    fun open() {
        file.parentFile?.mkdirs()
        writer = BufferedWriter(FileWriter(file, false))
        // The header waits for the first frame, whose time it records.
    }

    fun writeFrame(frame: CanFrame) {
        val w = writer ?: return

        var nanos = frame.elapsedNanos
        if (originNanos == null) {
            originNanos = nanos
            writeHeader(frame.timestampMs)
        }
        if (nanos < lastNanos) {
            outOfOrderFrames++
            nanos = lastNanos
        }
        lastNanos = nanos
        val timeStr = formatOffset(nanos - originNanos!!)

        val channel = frame.busIndex + 1
        val idStr = "0x%X".format(frame.id)
        // An error frame gets type `ERR`, with the error-class mask in the ID column and the
        // payload as received. `ERR` is the token Wireshark's BUSMASTER reader takes as an error
        // frame; what follows it is this project's convention. Readers that accept only `s`/`x`
        // (canre's busmaster.py before 2026-10-28) skip the line rather than count it as data.
        // Plan: android-app/notes/plans/gs-usb-error-frames.md.
        val typeChar = when {
            frame.isError -> TYPE_ERROR
            frame.isExtended -> "x"
            else -> "s"
        }
        val dataStr = frame.data.take(frame.dlc).joinToString(" ") { "%02X".format(it) }

        // The format's own direction column, which canre/parsers/busmaster.py already reads back
        // into CANFrame.is_tx -- so a log containing the app's own injected frames stays readable
        // by every existing offline tool, with our frames distinguishable from the vehicle's.
        val dirStr = if (frame.isTx) "Tx" else "Rx"

        val line = "$timeStr $dirStr $channel $idStr $typeChar ${frame.dlc} $dataStr\n"
        w.write(line)
        bytesWritten += line.length
        frameCount++

        if (frameCount % 1000L == 0L) w.flush()
    }

    fun close() {
        writer?.let {
            if (originNanos == null) writeHeader(sessionStartMs)
            writeFooter()
            it.flush()
            it.close()
        }
        writer = null
    }

    private fun writeHeader(startMs: Long) {
        val w = writer ?: return
        val dateFmt = SimpleDateFormat("dd:MM:yyyy HH:mm:ss:SSS", Locale.US)
        val dateStr = dateFmt.format(Date(startMs))

        val channelLines = (1..numBuses).joinToString("\n") { i ->
            "***CHANNEL $i - Innomaker - ${bitrateKbps * 1000} bps***"
        }

        val header = """
***BUSMASTER Ver 3.2.2***
***PROTOCOL CAN***
***NOTE: PLEASE DO NOT EDIT THIS DOCUMENT***
***[START LOGGING SESSION]***
***START DATE AND TIME $dateStr***
***HEX***
***SYSTEM MODE***
***START CHANNEL BAUD RATE***
$channelLines
***END CHANNEL BAUD RATE***
***START DATABASE FILES***
***END DATABASE FILES***
***<Time><Tx/Rx><Channel><CAN ID><Type><DLC><DataBytes>***

""".trimStart()
        w.write(header)
        w.flush()
        bytesWritten += header.length
    }

    companion object {
        /** Type column of an error-frame line. */
        const val TYPE_ERROR = "ERR"

        /** Non-negative nanoseconds -> `HH:MM:SS:TTTT`, TTTT in 0.1 ms ticks, truncated. */
        fun formatOffset(nanos: Long): String {
            val ticks = nanos / 100_000L
            val h = ticks / 36_000_000L
            val m = (ticks / 600_000L) % 60
            val s = (ticks / 10_000L) % 60
            return "%02d:%02d:%02d:%04d".format(h, m, s, ticks % 10_000L)
        }
    }

    private fun writeFooter() {
        val w = writer ?: return
        val dateFmt = SimpleDateFormat("dd:MM:yyyy HH:mm:ss:SSS", Locale.US)
        val dateStr = dateFmt.format(Date())
        val footer = "***END DATE AND TIME $dateStr***\n***[STOP LOGGING SESSION]***\n"
        w.write(footer)
        bytesWritten += footer.length
    }
}
