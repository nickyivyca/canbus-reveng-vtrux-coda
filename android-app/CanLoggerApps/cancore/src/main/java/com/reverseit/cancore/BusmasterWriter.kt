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
 * Timestamps are relative seconds from [sessionStartMs], formatted as HH:MM:SS:TTTT
 * where TTTT = 10 kHz ticks (0.1 ms resolution).
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

    fun open() {
        file.parentFile?.mkdirs()
        writer = BufferedWriter(FileWriter(file, false))
        writeHeader()
    }

    fun writeFrame(frame: CanFrame) {
        val w = writer ?: return

        val elapsedSec = (frame.timestampMs - sessionStartMs) / 1000.0
        val h = (elapsedSec / 3600).toInt()
        val m = ((elapsedSec % 3600) / 60).toInt()
        val s = (elapsedSec % 60).toInt()
        val ticks = ((elapsedSec % 1.0) * 10000).toInt()
        val timeStr = "%02d:%02d:%02d:%04d".format(h, m, s, ticks)

        val channel = frame.busIndex + 1
        val idStr = "0x%X".format(frame.id)
        val typeChar = if (frame.isExtended) "x" else "s"
        val dataStr = frame.data.take(frame.dlc).joinToString(" ") { "%02X".format(it) }

        val line = "$timeStr Rx $channel $idStr $typeChar ${frame.dlc} $dataStr\n"
        w.write(line)
        bytesWritten += line.length
        frameCount++

        if (frameCount % 1000L == 0L) w.flush()
    }

    fun close() {
        writer?.let {
            writeFooter()
            it.flush()
            it.close()
        }
        writer = null
    }

    private fun writeHeader() {
        val w = writer ?: return
        val dateFmt = SimpleDateFormat("dd:MM:yyyy HH:mm:ss:SSS", Locale.US)
        val dateStr = dateFmt.format(Date(sessionStartMs))

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

    private fun writeFooter() {
        val w = writer ?: return
        val dateFmt = SimpleDateFormat("dd:MM:yyyy HH:mm:ss:SSS", Locale.US)
        val dateStr = dateFmt.format(Date())
        val footer = "***END DATE AND TIME $dateStr***\n***[STOP LOGGING SESSION]***\n"
        w.write(footer)
        bytesWritten += footer.length
    }
}
