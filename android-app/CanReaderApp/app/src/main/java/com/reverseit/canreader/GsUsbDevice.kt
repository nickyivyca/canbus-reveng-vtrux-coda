package com.reverseit.canreader

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
 */
class GsUsbDevice(private val usbManager: UsbManager, private val device: UsbDevice) {

    companion object {
        const val VENDOR_ID = 7504    // 0x1D50
        const val PRODUCT_ID = 24687  // 0x606F

        private const val TAG = "CanReader"

        // gs_usb control request codes
        private const val GS_USB_BREQ_HOST_FORMAT: Byte = 0
        private const val GS_USB_BREQ_BITTIMING: Byte = 1
        private const val GS_USB_BREQ_MODE: Byte = 2
        private const val GS_USB_BREQ_BT_CONST: Byte = 4
        private const val GS_USB_BREQ_DEVICE_CONFIG: Byte = 5

        // bmRequestType values
        private const val CTRL_OUT = 0x41  // vendor | interface | host-to-device
        private const val CTRL_IN  = 0xC1  // vendor | interface | device-to-host

        // gs_device_mode.mode values
        private const val GS_CAN_MODE_RESET = 0
        private const val GS_CAN_MODE_START = 1

        private const val CTRL_TIMEOUT_MS = 1000
        private const val BULK_TIMEOUT_MS = 1000

        const val BITRATE_BPS = 500_000
    }

    private var connection: UsbDeviceConnection? = null
    private var usbIface: UsbInterface? = null
    private var epIn: UsbEndpoint? = null
    private var epOut: UsbEndpoint? = null

    @Volatile
    private var running = false

    /**
     * Open the device, negotiate protocol, and start the CAN channel at [BITRATE_BPS].
     * Must be called from a background thread (blocking USB control transfers).
     */
    fun open() {
        // Interface 0 is the gs_usb data interface; interface 1 is DFU (skip it)
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
            if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK) {
                if (ep.direction == UsbConstants.USB_DIR_IN) inEp = ep else outEp = ep
            }
        }
        inEp  ?: throw IOException("No bulk IN endpoint on interface 0")
        outEp ?: throw IOException("No bulk OUT endpoint on interface 0")

        connection = conn
        usbIface  = iface
        epIn      = inEp
        epOut     = outEp

        // 1. HOST_FORMAT: tell device we use little-endian (magic = 0x0000BEEF)
        val hostFmt = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN)
            .putInt(0x0000BEEF).array()
        ctrl(conn, CTRL_OUT, GS_USB_BREQ_HOST_FORMAT, hostFmt)

        // 2. DEVICE_CONFIG: read number of channels (byte 3 = icount, channels = icount+1)
        val devCfg = ByteArray(12)
        ctrl(conn, CTRL_IN, GS_USB_BREQ_DEVICE_CONFIG, devCfg)
        val nChannels = (devCfg[3].toInt() and 0xFF) + 1
        Log.i(TAG, "gs_usb: device has $nChannels channel(s)")

        // 3. BT_CONST: get CAN clock frequency (u32 feature, u32 fclk, ...)
        val btConst = ByteArray(40)
        ctrl(conn, CTRL_IN, GS_USB_BREQ_BT_CONST, btConst)
        val btBB = ByteBuffer.wrap(btConst).order(ByteOrder.LITTLE_ENDIAN)
        val feature = btBB.int
        val fclk = btBB.int.toLong() and 0xFFFFFFFFL
        Log.i(TAG, "gs_usb: fclk=$fclk Hz  feature=0x%08X".format(feature))

        // 4. BITTIMING: compute and set for desired bitrate
        val bt = computeBittiming(fclk, BITRATE_BPS)
        Log.i(TAG, "gs_usb: bittiming brp=${bt.brp} prop=${bt.propSeg} seg1=${bt.phaseSeg1} seg2=${bt.phaseSeg2} sjw=${bt.sjw}")
        val btBuf = ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN)
            .putInt(bt.propSeg)
            .putInt(bt.phaseSeg1)
            .putInt(bt.phaseSeg2)
            .putInt(bt.sjw)
            .putInt(bt.brp)
            .array()
        ctrl(conn, CTRL_OUT, GS_USB_BREQ_BITTIMING, btBuf)

        // 5. MODE=START: enable the CAN channel
        val modeBuf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
            .putInt(GS_CAN_MODE_START)
            .putInt(0)
            .array()
        ctrl(conn, CTRL_OUT, GS_USB_BREQ_MODE, modeBuf)
        Log.i(TAG, "gs_usb: CAN channel 0 started at ${BITRATE_BPS / 1000} kbps")

        running = true
    }

    /**
     * Blocking read loop. Calls [onFrame] for every received frame on the calling thread.
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
     * Stop the CAN channel and release the USB interface.
     */
    fun close() {
        running = false
        val conn = connection ?: return
        try {
            val resetBuf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(GS_CAN_MODE_RESET).putInt(0).array()
            ctrl(conn, CTRL_OUT, GS_USB_BREQ_MODE, resetBuf)
        } catch (_: Exception) {}
        usbIface?.let { conn.releaseInterface(it) }
        conn.close()
        connection = null
        Log.i(TAG, "gs_usb: device closed")
    }

    // --- helpers ---

    private fun ctrl(conn: UsbDeviceConnection, reqType: Int, req: Byte, buf: ByteArray) {
        val n = conn.controlTransfer(reqType, req.toInt() and 0xFF, 0, 0, buf, buf.size, CTRL_TIMEOUT_MS)
        if (n < 0) Log.w(TAG, "controlTransfer req=$req returned $n")
    }

    private data class Bittiming(
        val propSeg: Int, val phaseSeg1: Int, val phaseSeg2: Int, val sjw: Int, val brp: Int
    )

    /**
     * Compute CAN bittiming for [bitrate] given the device clock [fclk].
     * Targets an 87.5% sample point (standard for automotive CAN).
     * Falls back to hardcoded values for 48 MHz / 500 kbps if no exact match is found.
     */
    private fun computeBittiming(fclk: Long, bitrate: Int): Bittiming {
        // bit_time_tq = fclk / (brp * bitrate)
        // total_tq = 1 (sync) + prop_seg + phase_seg1 + phase_seg2
        // sample point = (1 + prop_seg + phase_seg1) / total_tq ~= 0.875
        for (brp in 1..64) {
            val denom = brp.toLong() * bitrate
            if (fclk % denom != 0L) continue
            val totalTq = (fclk / denom).toInt()
            if (totalTq < 4 || totalTq > 25) continue

            // phase_seg2 at 12.5% of total (rounded, minimum 1)
            val phaseSeg2 = maxOf(1, totalTq / 8)
            val tseg1 = totalTq - 1 - phaseSeg2  // prop_seg + phase_seg1
            if (tseg1 < 2) continue
            val propSeg = 1
            val phaseSeg1 = tseg1 - propSeg
            if (phaseSeg1 < 1) continue

            return Bittiming(propSeg, phaseSeg1, phaseSeg2, sjw = 1, brp)
        }
        Log.w(TAG, "computeBittiming: no exact match for fclk=$fclk bitrate=$bitrate, using fallback")
        return Bittiming(propSeg = 1, phaseSeg1 = 12, phaseSeg2 = 2, sjw = 1, brp = 6)
    }
}
