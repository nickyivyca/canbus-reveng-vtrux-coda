package com.reverseit.cancore

/**
 * Schedules periodic CAN transmissions, and holds every interlock that stands between a feature
 * asking to transmit and a frame actually reaching a vehicle bus.
 *
 * This is the first component in the app that can influence a car rather than observe one, so the
 * safety rules live here rather than in the feature that calls it -- one place to audit, and
 * reachable from a plain JVM test because nothing in this file imports Android.
 *
 * The interlocks, in the order they are applied:
 *
 *  1. **Disabled by default.** [enabled] starts false. Registering a slot does not transmit.
 *  2. **ID allowlist.** [allowedIds] is fixed at construction from vehicle constants. An ID outside
 *     it is rejected at [register] time, so a mistake fails loudly at wiring time instead of
 *     quietly spraying a drivetrain bus at runtime.
 *  3. **Bus resolved by identity, never by index.** A slot names its bus with a `() -> Int?`
 *     supplied by the caller -- in practice a [BusIdentityResolver] lookup. Until that returns a
 *     bus index, the slot does not transmit. Dongle insertion order decides physical indices, so a
 *     hardcoded 0 would eventually transmit a Coda B CAN frame onto D CAN or a different vehicle.
 *  4. **Contention guard.** If another node has been seen transmitting the same ID *on the same
 *     bus* within [contentionWindowMs], the slot is suppressed. Two nodes sending the same ID both
 *     win arbitration and then collide in the data field: the frame is destroyed on the wire, both
 *     retransmit, and both walk their transmit error counters toward bus-off. Nobody wins and the
 *     consumer sees neither value. Suppressing is always the right answer, and it lets this code
 *     ship safely before any donor module is physically removed.
 *
 *     **Per bus, not per ID.** Contention is a property of a single wire -- two nodes on different
 *     buses cannot collide. Keying on ID alone would also break on any vehicle with a gateway: a
 *     frame injected on one bus and rebroadcast by the gateway onto another arrives there off the
 *     wire, so it carries `isTx = false` and is indistinguishable from a foreign transmitter. On
 *     the Coda, `0x600` is gatewayed D CAN -> B CAN, so an ID-keyed guard would suppress a D CAN
 *     slot because of the gateway's copy of that slot's own output.
 *  5. **Rate floor.** [MIN_PERIOD_MS] caps how fast a slot can be scheduled.
 *  6. **Failure backoff.** [MAX_CONSECUTIVE_FAILURES] consecutive rejected sends disables the slot
 *     and records why, rather than hammering a dead endpoint every period forever.
 *
 * A slot's payload provider returning null skips that tick without unregistering -- that is how a
 * feature stops asserting something while keeping its schedule.
 *
 * Time is passed in rather than read, and [tick] does the work, so a test drives the whole
 * schedule with a fake clock and a recording [CanTransmitter]. [runLoop] is the thin production
 * wrapper around it.
 */
class PeriodicTransmitter(
    private val transmitter: CanTransmitter,
    /** IDs this transmitter will ever send. Anything else is rejected at [register]. */
    private val allowedIds: Set<Int>,
    private val contentionWindowMs: Long = DEFAULT_CONTENTION_WINDOW_MS,
) {

    companion object {
        /** Ceiling on transmit rate: 20 Hz. Well above any hold-alive frame this app needs. */
        const val MIN_PERIOD_MS = 50L

        /**
         * How long after hearing another node send an ID we keep refusing to send it ourselves.
         * Generous relative to the ~525 ms cadence of the frame this was built for: the cost of
         * over-suppressing is a feature that does not work, and the cost of under-suppressing is
         * two modules driving each other to bus-off.
         */
        const val DEFAULT_CONTENTION_WINDOW_MS = 5_000L

        const val MAX_CONSECUTIVE_FAILURES = 10

        /** Floor on [sleepMs], so a permanently blocked slot polls rather than spins. */
        const val MIN_SLEEP_MS = 10L

        /**
         * [sleepMs] when nothing is registered, or when [enabled] is false. The transmitter is
         * constructed at app start and is normally idle, so the idle case is the common one and
         * must not cost a fast wakeup on a head unit that runs for hours. Disabled counts as idle:
         * a registered slot that is never served stays permanently overdue, and without this the
         * loop polled it every [MIN_SLEEP_MS] -- 100 wakeups a second on the car, where the Coda
         * lamp slot is registered but disabled. Enabling therefore takes effect within a second.
         */
        const val IDLE_SLEEP_MS = 1_000L
    }

    /** Why a slot is not transmitting right now. Surfaced to the UI; not used for control flow. */
    enum class SlotState {
        /** Transmitting on schedule. */
        ACTIVE,

        /** [enabled] is false. */
        GATED,

        /** The bus resolver has not yet identified the target bus. */
        BUS_UNRESOLVED,

        /** No open device with a transmit path on the resolved bus. */
        NO_TRANSMIT_PATH,

        /** Another node was heard sending this ID. See the contention guard. */
        CONTENDED,

        /** The payload provider returned null -- the feature chose not to assert. */
        IDLE,

        /** The transport rejected the last send. Retried until [MAX_CONSECUTIVE_FAILURES]. */
        SEND_REJECTED,

        /** Disabled after [MAX_CONSECUTIVE_FAILURES] rejected sends. */
        FAILED,
    }

    private class Slot(
        val id: Int,
        val periodMs: Long,
        val busIndex: () -> Int?,
        val payload: () -> ByteArray?,
    ) {
        var nextDueMs = 0L
        var consecutiveFailures = 0
        var state = SlotState.GATED
        var sent = 0L
    }

    private val slots = LinkedHashMap<String, Slot>()

    /** (busIndex, id) -> wall-clock ms of the last such frame *received* from another node. */
    private val lastForeignTxMs = HashMap<Pair<Int, Int>, Long>()

    /**
     * Master gate. False until something deliberately turns transmission on; setting it false stops
     * every slot immediately without losing their registrations.
     */
    @Volatile
    var enabled: Boolean = false

    /** Per-slot state for display. Keys match [register]. */
    fun states(): Map<String, SlotState> = synchronized(slots) {
        slots.entries.associate { (k, v) -> k to v.state }
    }

    /** Frames sent per slot since registration. */
    fun sentCounts(): Map<String, Long> = synchronized(slots) {
        slots.entries.associate { (k, v) -> k to v.sent }
    }

    /**
     * Register a periodic transmission under [key], replacing any slot already at that key.
     *
     * @param busIndex resolves the physical bus at each tick, returning null while unknown. Pass a
     *   [BusIdentityResolver] lookup, never a constant.
     * @param payload called at each due tick; null skips this tick.
     *
     * @throws IllegalArgumentException if [id] is outside the allowlist or [periodMs] is below
     *   [MIN_PERIOD_MS]. Both are wiring mistakes and should fail at startup.
     */
    fun register(
        key: String,
        id: Int,
        periodMs: Long,
        busIndex: () -> Int?,
        payload: () -> ByteArray?,
    ) {
        require(id in allowedIds) {
            "CAN ID 0x%X is not in this transmitter's allowlist %s".format(
                id, allowedIds.joinToString(prefix = "[", postfix = "]") { "0x%X".format(it) }
            )
        }
        require(periodMs >= MIN_PERIOD_MS) { "period ${periodMs}ms is below MIN_PERIOD_MS" }
        synchronized(slots) { slots[key] = Slot(id, periodMs, busIndex, payload) }
    }

    fun unregister(key: String) {
        synchronized(slots) { slots.remove(key) }
    }

    /**
     * Feed every received frame here so the contention guard can see other nodes.
     *
     * Frames with `isTx = true` are ignored: those are our own echoes coming back off the bulk IN
     * endpoint, and counting them would make every slot suppress itself one period after it started.
     * Error frames are ignored too: their id is an error-class mask, not another node's message.
     */
    fun observe(frame: CanFrame) {
        if (frame.isTx || frame.isError) return
        if (frame.id !in allowedIds) return
        synchronized(lastForeignTxMs) {
            lastForeignTxMs[frame.busIndex to frame.id] = frame.timestampMs
        }
    }

    /**
     * True if another node has been heard sending [id] *on [busIndex]* recently enough to make
     * transmitting there unsafe.
     */
    fun isContended(busIndex: Int, id: Int, nowMs: Long): Boolean {
        val last = synchronized(lastForeignTxMs) { lastForeignTxMs[busIndex to id] } ?: return false
        return nowMs - last < contentionWindowMs
    }

    /**
     * Transmit every slot due at [nowMs]. Returns the number of frames handed to the transport.
     *
     * Each slot's state is updated whether or not it transmitted, so the UI can say why nothing is
     * happening.
     */
    fun tick(nowMs: Long): Int {
        val due = synchronized(slots) { slots.values.toList() }
        var sentNow = 0
        for (slot in due) {
            if (slot.state == SlotState.FAILED) continue
            if (!enabled) { slot.state = SlotState.GATED; continue }
            if (nowMs < slot.nextDueMs) continue

            val bus = slot.busIndex()
            if (bus == null) { slot.state = SlotState.BUS_UNRESOLVED; continue }
            if (!transmitter.canTransmit(bus)) { slot.state = SlotState.NO_TRANSMIT_PATH; continue }
            if (isContended(bus, slot.id, nowMs)) { slot.state = SlotState.CONTENDED; continue }

            val data = slot.payload()
            if (data == null) {
                slot.state = SlotState.IDLE
                slot.nextDueMs = nextDue(slot, nowMs)
                continue
            }

            val ok = transmitter.transmit(bus, slot.id, data)
            slot.nextDueMs = nextDue(slot, nowMs)
            if (ok) {
                slot.consecutiveFailures = 0
                slot.state = SlotState.ACTIVE
                slot.sent++
                sentNow++
            } else {
                slot.state =
                    if (++slot.consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) SlotState.FAILED
                    else SlotState.SEND_REJECTED
            }
        }
        return sentNow
    }

    /**
     * The slot's next due time after serving it at [nowMs]: one period after the time it was
     * *due*, not after [nowMs]. Scheduling from `nowMs` let every tick's lateness accumulate -- the
     * `0x600` slot ran at ~531 ms in the emulator harness against the RCU's 523-525 ms. A slot
     * more than a period behind (first send, or resuming after an interlock) restarts from [nowMs]
     * instead of bursting to catch up.
     */
    private fun nextDue(slot: Slot, nowMs: Long): Long {
        val anchored = slot.nextDueMs + slot.periodMs
        return if (slot.nextDueMs == 0L || anchored <= nowMs) nowMs + slot.periodMs else anchored
    }

    /**
     * How long [runLoop] should sleep after ticking at [nowMs]: until the next slot is due, bounded
     * by [MIN_SLEEP_MS] and [MIN_PERIOD_MS].
     *
     * The lower bound is not cosmetic. A slot blocked by an interlock never advances its due time,
     * so it is permanently overdue, and an unbounded "time until due" would return zero and spin
     * the loop at whatever rate the CPU allows for as long as the block lasts -- which for the
     * default-disabled case is the app's entire lifetime. [MIN_SLEEP_MS] keeps that at a bounded
     * poll while still re-evaluating fast enough that enabling a slot feels immediate.
     */
    fun sleepMs(nowMs: Long): Long {
        if (!enabled) return IDLE_SLEEP_MS
        val next = synchronized(slots) {
            slots.values.filter { it.state != SlotState.FAILED }.minOfOrNull { it.nextDueMs }
        } ?: return IDLE_SLEEP_MS
        return (next - nowMs).coerceIn(MIN_SLEEP_MS, MIN_PERIOD_MS)
    }

    /**
     * Production loop: tick, sleep, repeat until the coroutine is cancelled. Run it on an IO
     * dispatcher -- [CanTransmitter.transmit] blocks on a USB bulk transfer.
     */
    suspend fun runLoop(
        clock: () -> Long = { System.currentTimeMillis() },
        sleep: suspend (Long) -> Unit,
    ) {
        while (true) {
            val now = clock()
            tick(now)
            sleep(sleepMs(now))
        }
    }
}
