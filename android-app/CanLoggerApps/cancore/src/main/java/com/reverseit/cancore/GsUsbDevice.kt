package com.reverseit.cancore

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.util.Log
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Userspace implementation of the gs_usb protocol for the Innomaker USB2CAN.
 *
 * Protocol reference: linux/drivers/net/can/usb/gs_usb.c
 *
 * Sequence to start receiving:
 *   1. controlTransfer OUT HOST_FORMAT  -- tell device we are little-endian
 *   2. controlTransfer IN  DEVICE_CONFIG -- read number of channels
 *   3. controlTransfer IN  BT_CONST     -- read clock frequency
 *   4. controlTransfer OUT BITTIMING    -- set bitrate
 *   5. controlTransfer OUT MODE=START   -- enable CAN channel
 *   6. bulkTransfer IN (loop)           -- receive 20-byte frames
 *
 * Transmission uses the bulk OUT endpoint of the same interface and needs no extra negotiation --
 * MODE=START with flags 0 is normal (non-listen-only) mode, so the channel is already able to
 * transmit. See [send].
 */
class GsUsbDevice(
    private val usbManager: UsbManager,
    private val device: UsbDevice,
    private val bitrateKbps: Int = 500
) {
    companion object {
        const val VENDOR_ID  = 7504   // 0x1D50  Innomaker
        const val PRODUCT_ID = 24687  // 0x606F  USB2CAN

        private const val TAG = "CanCore"

        // gs_usb control request codes
        private const val GS_USB_BREQ_HOST_FORMAT: Byte = 0
        private const val GS_USB_BREQ_BITTIMING: Byte   = 1
        private const val GS_USB_BREQ_MODE: Byte        = 2
        private const val GS_USB_BREQ_BT_CONST: Byte    = 4
        private const val GS_USB_BREQ_DEVICE_CONFIG: Byte = 5

        private const val CTRL_OUT = 0x41  // vendor | interface | host-to-device
        private const val CTRL_IN  = 0xC1  // vendor | interface | device-to-host

        private const val GS_CAN_MODE_RESET = 0
        private const val GS_CAN_MODE_START = 1

        private const val CTRL_TIMEOUT_MS = 1000
        private const val BULK_TIMEOUT_MS = 1000
    }

    private var connection: UsbDeviceConnection? = null
    private var usbIface: UsbInterface? = null
    private var epIn: UsbEndpoint? = null
    private var epOut: UsbEndpoint? = null

    @Volatile private var running = false

    /**
     * Serialises [send] against itself and against [close]. The read loop uses a different
     * endpoint and is deliberately not covered: holding this lock across the blocking bulk IN
     * transfer would stall every transmission for up to BULK_TIMEOUT_MS.
     */
    private val txLock = Any()

    /** True once a bulk OUT endpoint has been found and the channel started. */
    val canTransmit: Boolean get() = running && epOut != null

    /**
     * Open the device, negotiate protocol, and start the CAN channel.
     * Must be called from a background thread (blocking USB control transfers).
     */
    fun open() {
        val iface = device.getInterface(0)
        val conn = usbManager.openDevice(device)
            ?: throw IOException("Cannot open USB device -- permission missing?")

        if (!conn.claimInterface(iface, true)) {
            conn.close()
            throw IOException("Cannot claim gs_usb interface 0")
        }

        var inEp: UsbEndpoint? = null
        var outEp: UsbEndpoint? = null
        for (i in 0 until iface.endpointCount) {
            val ep = iface.getEndpoint(i)
            if (ep.type != UsbConstants.USB_ENDPOINT_XFER_BULK) continue
            when (ep.direction) {
                UsbConstants.USB_DIR_IN  -> inEp = ep
                UsbConstants.USB_DIR_OUT -> outEp = ep
            }
        }
        inEp ?: throw IOException("No bulk IN endpoint on interface 0")
        // A missing OUT endpoint is NOT fatal: receiving is the app's primary job and has worked
        // on every dongle so far. Transmission simply reports itself unavailable -- see
        // [canTransmit] -- so a firmware without it degrades to the read-only behaviour the app
        // had before TX existed, rather than refusing to log.
        if (outEp == null) Log.w(TAG, "gs_usb device=${device.deviceId}: no bulk OUT endpoint, transmit unavailable")

        connection = conn
        usbIface   = iface
        epIn       = inEp
        epOut      = outEp

        // 0. MODE=RESET: put device in known state before configuring (matches Linux gs_usb driver)
        ctrl(conn, CTRL_OUT, GS_USB_BREQ_MODE,
            ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(GS_CAN_MODE_RESET).putInt(0).array())

        // 1. HOST_FORMAT: little-endian magic
        ctrl(conn, CTRL_OUT, GS_USB_BREQ_HOST_FORMAT,
            ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(0x0000BEEF).array())

        // 2. DEVICE_CONFIG: number of channels
        val devCfg = ByteArray(12)
        ctrl(conn, CTRL_IN, GS_USB_BREQ_DEVICE_CONFIG, devCfg)
        val nChannels = (devCfg[3].toInt() and 0xFF) + 1
        Log.i(TAG, "gs_usb device=${device.deviceId}: $nChannels channel(s)")

        // 3. BT_CONST: get clock frequency
        val btConst = ByteArray(40)
        ctrl(conn, CTRL_IN, GS_USB_BREQ_BT_CONST, btConst)
        val fclk = ByteBuffer.wrap(btConst).order(ByteOrder.LITTLE_ENDIAN)
            .let { bb -> bb.int; bb.int.toLong() and 0xFFFFFFFFL }
        Log.i(TAG, "gs_usb device=${device.deviceId}: fclk=$fclk Hz")

        // 4. BITTIMING: compute and set
        val bitrateBps = bitrateKbps * 1000
        val bt = computeBittiming(fclk, bitrateBps)
        Log.i(TAG, "gs_usb: bittiming brp=${bt.brp} prop=${bt.propSeg} seg1=${bt.phaseSeg1} seg2=${bt.phaseSeg2}")
        ctrl(conn, CTRL_OUT, GS_USB_BREQ_BITTIMING,
            ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(bt.propSeg).putInt(bt.phaseSeg1).putInt(bt.phaseSeg2)
                .putInt(bt.sjw).putInt(bt.brp).array())

        // 5. MODE=START
        ctrl(conn, CTRL_OUT, GS_USB_BREQ_MODE,
            ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(GS_CAN_MODE_START).putInt(0).array())
        Log.i(TAG, "gs_usb device=${device.deviceId}: started at $bitrateKbps kbps")

        running = true
    }

    /**
     * Blocking read loop. Calls [onFrame] for every received frame.
     * Returns when [close] is called or the USB connection is lost.
     */
    fun readFrames(onFrame: (GsUsbFrame) -> Unit) {
        val conn = connection ?: return
        val ep   = epIn      ?: return
        val buf  = ByteArray(GsUsbFrame.FRAME_SIZE)

        while (running && !Thread.currentThread().isInterrupted) {
            val len = conn.bulkTransfer(ep, buf, buf.size, BULK_TIMEOUT_MS)
            when {
                len == GsUsbFrame.FRAME_SIZE -> onFrame(GsUsbFrame.fromBytes(buf))
                len < 0 -> { /* timeout -- keep looping */ }
                else -> Log.w(TAG, "Unexpected frame length: $len")
            }
        }
    }

    /**
     * Put one frame on the wire. Returns true if the device accepted the full 20-byte packet.
     *
     * Blocking, so call it off the main thread. Safe to call concurrently with [readFrames], which
     * uses the other endpoint.
     *
     * A transmitted frame is echoed back by the device on the bulk IN endpoint with our echo
     * cookie, so it reappears through [readFrames] as a [CanFrame] with `isTx = true`. That echo,
     * not this return value, is the evidence the frame actually reached the bus: true here only
     * means the USB write succeeded.
     */
    fun send(id: Int, data: ByteArray, isExtended: Boolean = false, dlc: Int = data.size): Boolean {
        val frame = GsUsbFrame.forTransmit(id, data, isExtended, dlc)
        val bytes = GsUsbFrame.toBytes(frame)
        synchronized(txLock) {
            if (!running) return false
            val conn = connection ?: return false
            val ep = epOut ?: return false
            val n = conn.bulkTransfer(ep, bytes, bytes.size, BULK_TIMEOUT_MS)
            if (n != bytes.size) {
                Log.w(TAG, "gs_usb device=${device.deviceId}: send id=0x%X returned %d".format(id, n))
                return false
            }
            return true
        }
    }

    fun close() {
        running = false
        synchronized(txLock) { epOut = null }
        val conn = connection ?: return
        try {
            ctrl(conn, CTRL_OUT, GS_USB_BREQ_MODE,
                ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
                    .putInt(GS_CAN_MODE_RESET).putInt(0).array())
        } catch (_: Exception) {}
        usbIface?.let { conn.releaseInterface(it) }
        conn.close()
        connection = null
        Log.i(TAG, "gs_usb device=${device.deviceId}: closed")
    }

    private fun ctrl(conn: UsbDeviceConnection, reqType: Int, req: Byte, buf: ByteArray) {
        val n = conn.controlTransfer(reqType, req.toInt() and 0xFF, 0, 0, buf, buf.size, CTRL_TIMEOUT_MS)
        if (n < 0) Log.w(TAG, "controlTransfer req=$req returned $n")
    }

    private data class Bittiming(val propSeg: Int, val phaseSeg1: Int, val phaseSeg2: Int, val sjw: Int, val brp: Int)

    private fun computeBittiming(fclk: Long, bitrate: Int): Bittiming {
        for (brp in 1..64) {
            val denom = brp.toLong() * bitrate
            if (fclk % denom != 0L) continue
            val totalTq = (fclk / denom).toInt()
            if (totalTq < 4 || totalTq > 25) continue
            val phaseSeg2 = maxOf(1, totalTq / 8)
            val tseg1 = totalTq - 1 - phaseSeg2
            if (tseg1 < 2) continue
            val propSeg = 1
            val phaseSeg1 = tseg1 - propSeg
            if (phaseSeg1 < 1) continue
            return Bittiming(propSeg, phaseSeg1, phaseSeg2, sjw = 1, brp)
        }
        Log.w(TAG, "computeBittiming: no exact match, using fallback for 48MHz/500kbps")
        return Bittiming(propSeg = 1, phaseSeg1 = 12, phaseSeg2 = 2, sjw = 1, brp = 6)
    }
}
