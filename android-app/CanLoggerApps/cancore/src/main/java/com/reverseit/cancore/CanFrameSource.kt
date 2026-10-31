package com.reverseit.cancore

import kotlinx.coroutines.flow.SharedFlow

/**
 * Anything [CanLoggingService] can log from.
 *
 * The service previously took a [CanPipelineManager] directly, which meant a vehicle with a
 * transport other than gs_usb -- the 914, whose VCU speaks SLCAN over USB CDC serial -- could not
 * use the logging path at all without changing the pipeline.
 *
 * This is deliberately the narrowest seam that solves that. The service only ever needed a flow
 * of frames plus two counters for its notification and log header, so widening its property to
 * this interface leaves the gs_usb path completely untouched. `CanPipelineManager` already
 * satisfied this shape and merely declares it now; no behaviour changed for `:coda` or `:vtrux`.
 *
 * The larger refactor that was originally planned -- a transport abstraction *inside*
 * `CanPipelineManager`, so gs_usb and SLCAN became peer device drivers -- was dropped as
 * unjustified. It would have rewritten the multi-dongle path that runs in a truck, in order to
 * serve a vehicle that has exactly one source and no dongles, and that path cannot be unit-tested
 * because it depends on `android.hardware.usb`. This achieves the same end without going near it.
 */
interface CanFrameSource {

    /** Data frames from every active bus, merged. Never carries an error frame. */
    val frames: SharedFlow<CanFrame>

    /**
     * What the log writer records: [frames] plus the adapter's error frames
     * ([CanFrame.isError]), in one stream in timestamp order. Only [CanLoggingService] should
     * collect this. An error frame's `id` is an error-class mask that collides with real message
     * IDs, so keeping them off [frames] means no decoder, bus resolver or contention guard has to
     * remember to skip them -- including ones not written yet.
     *
     * Sources that cannot produce error frames (SLCAN) inherit this default.
     */
    val logFrames: SharedFlow<CanFrame> get() = frames

    /** Sources currently delivering. Drives the "N dongle(s)" / "waiting" notification text. */
    fun activeDeviceCount(): Int

    /** Bus count for the BUSMASTER log header. */
    fun activeBusCount(): Int

    companion object {
        /**
         * Buffer on the flow the log writer reads (Bug 4): 16k frames, about 2 s at Vtrux's
         * ~7,100 fps, so a writer stall of that long loses nothing. Measured on a phone
         * (2026-10-30): no loss from 1.2-7 s stalls at ~2,000 fps.
         */
        const val LOG_BUFFER_FRAMES = 16_384
    }
}
