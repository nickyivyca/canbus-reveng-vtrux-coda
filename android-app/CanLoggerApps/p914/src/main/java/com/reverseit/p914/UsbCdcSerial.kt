package com.reverseit.p914

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.util.Log
import java.io.IOException
import java.io.InputStream

/**
 * Minimal USB CDC-ACM reader for the 914 VCU's mbed interface MCU.
 *
 * Hand-rolled rather than pulling in `usb-serial-for-android`, for three reasons: the library is
 * published on JitPack, which would mean adding a repository to shared build config under
 * `FAIL_ON_PROJECT_REPOS`; `GsUsbDevice` is existing precedent for raw `UsbDeviceConnection` work
 * in this project; and CDC-ACM needs only two control transfers before the bulk endpoint becomes
 * a plain byte stream.
 *
 * Measured device layout (OnePlus 7T in host mode, 2026-08-13):
 *
 *     0d28:0204  "MBED CMSIS-DAP"  bDeviceClass 02, 4 interfaces
 *       intf 0  08/06/50  mass storage  <- claimed by usb-storage, irrelevant to us
 *       intf 1  02/02/01  CDC control   <- unclaimed
 *       intf 2  0a/00/00  CDC data      <- unclaimed
 *       intf 3  03/00/00  HID           <- claimed by usbhid, irrelevant to us
 *
 * Interfaces are located by class rather than by index, so a firmware change that reorders them
 * does not silently bind the wrong one.
 *
 * [inputStream] hands back a plain [InputStream], which is the point: `SlcanFrameSource.pump()`
 * consumes it exactly as it consumes the replay bridge's TCP socket, so the decode path used here
 * is the one already verified end to end over TCP.
 */
class UsbCdcSerial private constructor(
    private val connection: UsbDeviceConnection,
    private val controlInterface: UsbInterface,
    private val dataInterface: UsbInterface,
    private val readEndpoint: UsbEndpoint,
) {

    companion object {
        private const val TAG = "P914"

        const val VID_MBED = 0x0D28
        const val PID_MBED = 0x0204

        // CDC-ACM class requests (USB CDC 1.1, section 6.2)
        private const val REQTYPE_HOST_TO_DEVICE_CLASS_INTERFACE = 0x21
        private const val SET_LINE_CODING = 0x20
        private const val SET_CONTROL_LINE_STATE = 0x22
        private const val SEND_BREAK = 0x23
        private const val DTR_RTS = 0x03

        /** `wValue` for SEND_BREAK meaning "hold the break until told otherwise". */
        private const val BREAK_CONTINUOUS = 0xFFFF

        /**
         * How long to hold the break. Matches `send_break()` in the hub's `vcu_serial.py`, which
         * is the procedure this reproduces -- no reason to differ from the one known to work.
         */
        const val BREAK_HOLD_MS = 500L

        private const val CONTROL_TIMEOUT_MS = 2_000

        /** The VCU's console rate -- `platform.stdio-baud-rate` in `mbed_app.json5`. */
        const val BAUD = 460_800

        fun find(manager: UsbManager): UsbDevice? =
            manager.deviceList.values.firstOrNull {
                it.vendorId == VID_MBED && it.productId == PID_MBED
            }

        /**
         * Claim the CDC interfaces and configure the line. Returns null if the device cannot be
         * opened or has no CDC data interface.
         *
         * Caller must already hold USB permission for [device].
         */
        fun open(manager: UsbManager, device: UsbDevice): UsbCdcSerial? {
            var control: UsbInterface? = null
            var data: UsbInterface? = null
            for (i in 0 until device.interfaceCount) {
                val intf = device.getInterface(i)
                when (intf.interfaceClass) {
                    UsbConstants.USB_CLASS_COMM -> if (control == null) control = intf
                    UsbConstants.USB_CLASS_CDC_DATA -> if (data == null) data = intf
                }
            }
            if (control == null || data == null) {
                Log.e(TAG, "no CDC interfaces: control=$control data=$data")
                return null
            }

            var readEp: UsbEndpoint? = null
            for (i in 0 until data.endpointCount) {
                val ep = data.getEndpoint(i)
                if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK &&
                    ep.direction == UsbConstants.USB_DIR_IN
                ) {
                    readEp = ep
                }
            }
            if (readEp == null) {
                Log.e(TAG, "CDC data interface has no bulk IN endpoint")
                return null
            }

            val conn = manager.openDevice(device) ?: run {
                Log.e(TAG, "openDevice returned null -- permission not held?")
                return null
            }

            // force=true so a kernel driver would be detached. Measured as unclaimed on this
            // device, but a different ROM could bind cdc-acm and then the read would silently
            // return nothing.
            if (!conn.claimInterface(control, true) || !conn.claimInterface(data, true)) {
                Log.e(TAG, "claimInterface failed")
                conn.close()
                return null
            }

            // SET_LINE_CODING: dwDTERate LE32, bCharFormat (0 = 1 stop), bParityType (0 = none),
            // bDataBits. The mbed interface MCU passes this through to the target UART, so it
            // must match the firmware's console rate or the stream is garbage.
            val lineCoding = byteArrayOf(
                (BAUD and 0xFF).toByte(),
                ((BAUD shr 8) and 0xFF).toByte(),
                ((BAUD shr 16) and 0xFF).toByte(),
                ((BAUD shr 24) and 0xFF).toByte(),
                0, 0, 8,
            )
            val lc = conn.controlTransfer(
                REQTYPE_HOST_TO_DEVICE_CLASS_INTERFACE, SET_LINE_CODING, 0,
                control.id, lineCoding, lineCoding.size, CONTROL_TIMEOUT_MS,
            )
            val cls = conn.controlTransfer(
                REQTYPE_HOST_TO_DEVICE_CLASS_INTERFACE, SET_CONTROL_LINE_STATE, DTR_RTS,
                control.id, null, 0, CONTROL_TIMEOUT_MS,
            )
            Log.i(TAG, "CDC open: setLineCoding=$lc setControlLineState=$cls baud=$BAUD")
            if (lc < 0) {
                // Not fatal on every device, but on this one a failed line coding means the
                // target UART rate is wrong and every byte will be corrupt -- better to fail
                // loudly than to hand back a stream of garbage that looks like link damage.
                Log.e(TAG, "SET_LINE_CODING failed ($lc) -- refusing to open")
                conn.releaseInterface(control)
                conn.releaseInterface(data)
                conn.close()
                return null
            }
            return UsbCdcSerial(conn, control, data, readEp).also { it.startReader() }
        }

        /**
         * Reset the LPC1768 target by asserting a serial break.
         *
         * The mbed interface firmware turns a break on its CDC port into a target reset, which is
         * why no power cycle or button press is needed to restart the car's VCU -- the reset button
         * is not reachable with the car assembled, so this is the only reset available in practice.
         *
         * Standalone rather than an instance method because the caller has just finished flashing
         * and has no session open: the pump must be stopped before a flash anyway (the target is
         * about to be reset, so its stream is ending regardless), and holding a claimed interface
         * across that would only add a state to get wrong.
         *
         * Mirrors `send_break()` in the hub's `vcu_serial.py`: assert continuous break, hold, clear.
         * Returns null on success, or a description of what failed.
         */
        fun sendBreak(manager: UsbManager, device: UsbDevice): String? {
            var control: UsbInterface? = null
            for (i in 0 until device.interfaceCount) {
                val intf = device.getInterface(i)
                if (intf.interfaceClass == UsbConstants.USB_CLASS_COMM) { control = intf; break }
            }
            if (control == null) return "no CDC control interface"

            val conn = manager.openDevice(device) ?: return "openDevice failed -- permission?"
            try {
                if (!conn.claimInterface(control, true)) return "claimInterface failed"
                val set = conn.controlTransfer(
                    REQTYPE_HOST_TO_DEVICE_CLASS_INTERFACE, SEND_BREAK, BREAK_CONTINUOUS,
                    control.id, null, 0, CONTROL_TIMEOUT_MS,
                )
                if (set < 0) return "SEND_BREAK (assert) rejected ($set)"
                Thread.sleep(BREAK_HOLD_MS)
                val clear = conn.controlTransfer(
                    REQTYPE_HOST_TO_DEVICE_CLASS_INTERFACE, SEND_BREAK, 0,
                    control.id, null, 0, CONTROL_TIMEOUT_MS,
                )
                // A failure to *clear* is worth reporting: the line would be left in break and the
                // target held in reset, which looks exactly like a board that died during flashing.
                if (clear < 0) return "SEND_BREAK (clear) rejected ($clear) -- target may be held in reset"
                Log.i(TAG, "break sent -- target reset")
                return null
            } finally {
                runCatching { conn.releaseInterface(control) }
                runCatching { conn.close() }
            }
        }
    }

    @Volatile private var closed = false
    @Volatile var overruns = 0L; private set

    private val queue = java.util.concurrent.ArrayBlockingQueue<ByteArray>(QUEUE_DEPTH)
    private var readerThread: Thread? = null

    /**
     * Dedicated reader thread, so a bulk transfer is essentially always in flight.
     *
     * This is not premature optimisation -- it fixes measured data loss. The first implementation
     * read and parsed on the same thread, and every byte the VCU sent while the parser was busy
     * had nowhere to go: USB bulk has no flow control at this layer, and Android's `bulkTransfer`
     * is a single synchronous URB, so data arriving with no transfer queued is dropped by the host
     * controller. Measured on the car: ~0.6% of integrity blocks failed, against ~0.2% for the
     * same stream read by the laptop, with short frame counts confirming loss rather than
     * corruption.
     *
     * Decoupling read from parse costs one thread and a bounded queue. Queue-full is counted in
     * [overruns] rather than silently discarded -- an invisible drop is the thing being fixed.
     */
    private fun startReader() {
        readerThread = kotlin.concurrent.thread(start = true, isDaemon = true, name = "usb-cdc-read") {
            val buf = ByteArray(READ_BUFFER)
            var idleReads = 0
            while (!closed) {
                val n = connection.bulkTransfer(readEndpoint, buf, buf.size, READ_TIMEOUT_MS)
                // -1 covers both timeout and error, and bulkTransfer cannot distinguish them.
                // A timeout is normal -- the VCU emits in ~1 KB bursts every ~212 ms, so idle
                // gaps are expected and must not be read as end-of-stream.
                //
                // But a *detached* device also returns -1, forever. Treating the two the same
                // means an unplug spins here indefinitely: the stream never ends, pump() never
                // returns, and the reconnect logic never runs. Measured exactly that way on
                // 2026-08-13 -- a replug was never noticed and the log simply stopped growing.
                //
                // So a run of idle reads far longer than any legitimate gap is taken as gone.
                // ACTION_USB_DEVICE_DETACHED closes us faster in the normal case; this is the
                // backstop for when that broadcast is missed, which the Vtrux notes record
                // happening on this hardware.
                if (n <= 0) {
                    if (++idleReads >= IDLE_READS_BEFORE_GONE) {
                        Log.w(TAG, "no data for ${IDLE_READS_BEFORE_GONE * READ_TIMEOUT_MS}ms -- treating device as gone")
                        closed = true
                        break
                    }
                    continue
                }
                idleReads = 0
                if (!queue.offer(buf.copyOf(n))) {
                    overruns++
                    Log.w(TAG, "read queue full, dropped $n bytes (overruns=$overruns)")
                }
            }
        }
    }

    /** Blocking byte stream draining the reader thread's queue. */
    fun inputStream(): InputStream = object : InputStream() {
        private var chunk: ByteArray? = null
        private var pos = 0

        override fun read(): Int {
            val one = ByteArray(1)
            val n = read(one, 0, 1)
            return if (n <= 0) -1 else one[0].toInt() and 0xFF
        }

        override fun read(b: ByteArray, off: Int, count: Int): Int {
            var c = chunk
            while (c == null || pos >= c.size) {
                if (closed && queue.isEmpty()) return -1
                c = queue.poll(200, java.util.concurrent.TimeUnit.MILLISECONDS)
                pos = 0
                chunk = c
            }
            val n = minOf(count, c.size - pos)
            System.arraycopy(c, pos, b, off, n)
            pos += n
            return n
        }

        override fun close() {
            this@UsbCdcSerial.close()
        }
    }

    fun close() {
        if (closed) return
        closed = true
        runCatching { connection.releaseInterface(controlInterface) }
        runCatching { connection.releaseInterface(dataInterface) }
        runCatching { connection.close() }
        Log.i(TAG, "CDC closed")
    }
}

private const val READ_TIMEOUT_MS = 500

/** One bulk read. Generous vs the ~1 KB the VCU flushes per burst, so a burst lands in one go. */
private const val READ_BUFFER = 16 * 1024

/** ~1 MB of slack at this link's 6.7 KB/s -- seconds of headroom if the parser stalls. */
private const val QUEUE_DEPTH = 64

/**
 * Consecutive empty reads before the device is presumed gone. 20 x 500 ms = 10 s, far longer
 * than the ~212 ms the VCU ever goes quiet, so a live-but-idle link is never mistaken for a
 * detached one.
 */
private const val IDLE_READS_BEFORE_GONE = 20
