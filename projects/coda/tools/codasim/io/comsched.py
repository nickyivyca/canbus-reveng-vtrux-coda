"""The COM stack's receive-poll schedule: when a received frame reaches the 10 ms torque task (worklog 6H.74).

Traced in the firmware (coda_dlcm_prog.bin), read here from its own tables:

  - The COM task 0x80068D3C (OS ready bit 0x200, above the torque task's 0x100) runs every 5 ms. It calls the TX
    main 0x80068B5C, then the RX main 0x80068B0A.
  - RX main polls each RX record on a countdown (0x80068072, mode 1): the mailbox is read and unpacked into the COM
    shadow only on the calls where the countdown reaches 0. The countdown starts at the record's period (+6, u16,
    in COM calls) at RX start (0x80067D66), so a record with divider n is polled on calls c = 0 mod n.
  - TX main sends a record on a countdown that starts at its offset (+8) and reloads with its period (+6)
    (0x80067F4A, 0x80068156): 0x308 / 0x312 on calls 3, 5, 7, ...; 0x212 on 3, 7, 11, ...; 0x08C on 3, 203, ...
  - The torque task copies the COM shadow into its own buffers at its start (ComRxCopy, called at 0x8007C29A) and
    packs its output at its end (0x80080C14 -> 0x800685C4 / 0x80068C6A); TX main sends it at the next burst.

So, with the 10 ms TX bursts on the odd calls, a divider-n frame is caught by the first poll on a call c = 0 mod n
at or after its arrival. The torque task that runs after the next burst (5 ms later) uses it, and its output goes
out at the burst after that.

In codasim's frame (io/inputs: each tick runs ALIGN_US = 5 ms before the burst it publishes in), the even calls fall
on the tick instants. The tick that matches that torque task is the poll instant + RX_CONSUME_US (10 ms).

Arrivals are compared with the TRUE poll instants (anchor burst + k x 5 ms, on the logger clock); only the delivery
instant is then rounded onto codasim's fixed tick grid. The grid's phase comes from the capture's first 0x308 and the
logger and DLCM clocks drift (about -4 ms per 300 s), while ESC 0x208 is nearly phase-locked to the bursts. Rounding the
polls first put whole stretches of 0x208 frames on the wrong side of the poll: 22 % of deliveries were off by 10-20 ms
on coda_20261004_165539_T0 (found by the lash session, rx_poll_timing_check.py phase 4; fixed 2026-10-14).

Measured against the logs through this module (notes/dlcm/artifacts/regen_limit_scatter.py phase 8, after the
rounding fix below):
  - 0x208: 0x212 |err| while pressure moves 0.93 -> 0.16 Nm (exact 37 -> 91 %), better than any constant shift
    (best 0.32 Nm);
  - 0x312 M_MIN with the 0x1C0 substitute: 0.143 -> 0.043 Nm (derate-B rows 2.01 -> 0.40).
INFERRED, not read from the OS alarm table: the torque task runs right after the burst instance's COM run. The
priorities and the measured latency both say so.
ASSUMED: RX and TX countdowns start on the same COM call. The 0x208 result, phase anchored on 0x212, supports it.

The phase of a divider-n poll comes from the logged TX burst of a record whose period is a multiple of n (0x308 for
n = 2, 0x212 for n = 4, 0x08C for n = 20). It is re-anchored at every such frame, so logger clock drift and DLCM
restarts (the counters restart) stay local.
"""

import numpy as np

CALL_US = 5000                 # COM main period
RX_CONSUME_US = 10000          # poll instant -> codasim tick of the torque task that uses it
RX_REC, TX_REC = 52, 40        # record strides (dlcm_can_table_inventory.py)

# Logged frames standing in for an M-CAN record: the 0x1C0 HV words stand in for 0x20B (io/inputs
# SUBSTITUTE_20B_FEEDS), so they take 0x20B's poll.
RX_RECORD_OF = {0x1C0: 0x20B}
# DECLARED ESTIMATE: 0x20B reaches the DLCM ~2 ms after 0x209, the frame that 0x1C0 relays. Applied as an arrival
# offset to the substitute only. 0x20B is never logged. Re-fitted after the rounding fix (regen_limit_scatter.py
# phase 8): the M_MIN error is flat from 1 to 2 ms (0.042 / 0.043 Nm), worse at 0 ms (0.048) and 4 ms (0.051).
ARRIVAL_OFFSET_US = {0x1C0: 2000}


class ComSchedule:
    def __init__(self, img, sym):
        cfg = sym.addr("ComConfig")
        rx_tab, tx_tab = img.u32(cfg), img.u32(cfg + 4)
        self.rx, self.tx = {}, {}
        for i in range(img.u8(cfg + 0x10)):
            a = rx_tab + RX_REC * i
            self.rx[img.u32(a)] = dict(div=img.u16(a + 6), mode=img.u8(a + 0xC))
        for i in range(img.u8(cfg + 0x11)):
            a = tx_tab + TX_REC * i
            self.tx[img.u32(a)] = dict(period=img.u16(a + 6), offset=img.u16(a + 8))

    def rx_divider(self, can_id):
        rid = RX_RECORD_OF.get(can_id, can_id)
        rec = self.rx.get(rid)
        if rec is None:
            raise KeyError("0x%03X: no COM RX record" % rid)
        if rec["mode"] != 1:
            raise NotImplementedError("0x%03X: RX mode %d is not the polled countdown" % (rid, rec["mode"]))
        return rec["div"]

    def anchors(self, n):
        """TX ids whose bursts fix the phase of a divider-n poll, shortest period first."""
        return sorted((r["period"], i) for i, r in self.tx.items() if r["period"] % n == 0 and r["period"] > 0)

    def poll_instants(self, n, anchor_id, anchor_t, phase_us, t_lo, t_hi):
        """Sorted TRUE poll instants (logger clock, not rounded) of a divider-n record, from the logged bursts of
        anchor_id. phase_us is unused (kept for callers); the tick grid is applied to the delivery, in deliver()."""
        ta = np.asarray(anchor_t, np.int64)
        if not len(ta):
            raise ValueError("no 0x%03X frames to anchor a divider-%d poll" % (anchor_id, n))
        k = (-self.tx[anchor_id]["offset"]) % n               # calls from the anchor's burst to the next poll
        step = n * CALL_US
        starts = ta + k * CALL_US
        out = []
        for i, s in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else t_hi + step
            out.append(np.arange(s, max(end, s + 1), step))
        first = starts[0]
        nb = max(0, int((first - t_lo) // step) + 1)
        out.append(first - step * np.arange(1, nb + 1))
        return np.unique(np.concatenate(out))

    @staticmethod
    def deliver(times, polls, offset_us=0, phase_us=None):
        """Delivery instant (true poll + RX_CONSUME_US) of each arrival, rounded onto the tick grid at phase_us if given
        (io/inputs gives it; polls already on the grid need none); -1 where no poll follows."""
        j = np.searchsorted(polls, np.asarray(times, np.int64) + offset_us, "left")
        ok = j < len(polls)
        d = polls[np.minimum(j, len(polls) - 1)] + RX_CONSUME_US
        if phase_us is not None:
            d = phase_us + np.round((d - phase_us) / 10000.0).astype(np.int64) * 10000
        return np.where(ok, d, -1)
