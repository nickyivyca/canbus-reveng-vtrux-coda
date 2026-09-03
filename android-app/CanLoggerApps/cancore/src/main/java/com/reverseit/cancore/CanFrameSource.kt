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

    /** Frames from every active bus, merged. */
    val frames: SharedFlow<CanFrame>

    /** Sources currently delivering. Drives the "N dongle(s)" / "waiting" notification text. */
    fun activeDeviceCount(): Int

    /** Bus count for the BUSMASTER log header. */
    fun activeBusCount(): Int
}
