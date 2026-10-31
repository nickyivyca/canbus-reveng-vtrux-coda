package com.reverseit.cancore

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.onSubscription
import java.util.IdentityHashMap
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

/**
 * Frames lost on the way to the collectors (Bug 4, `notes/outstanding-changes.md`; plan
 * `notes/plans/tryemit-drops.md`): what `tryEmit` drops, and the adapter's own overflow reports.
 *
 * Always on, in every build: each frame flow registers itself and reports each `tryEmit` result
 * (one atomic increment per frame), [count] counts other loss events, and [start]'s reporter writes
 * them to its sink; [summary] is the short form for the logging notification. Collectors wrapped
 * with [watched] add per-collector backlog, lag and gap measurements, and honour a one-shot stall
 * ([requestStall]) -- only once [enabled] is set, which the apps do in debuggable builds only.
 *
 * No Android imports: output goes through [start]'s sink.
 */
object FlowHealth {

    /** Collector measurements and the stall hook. Set before the collectors subscribe. */
    @Volatile
    var enabled = false

    class Emitter(val name: String) {
        val emitted = AtomicLong()
        val failed = AtomicLong()

        /** Record one `tryEmit` result; returns it so call sites can keep their own logic. */
        fun record(ok: Boolean): Boolean {
            if (ok) emitted.incrementAndGet() else failed.incrementAndGet()
            return ok
        }
    }

    class Collector(val name: String, private val emitter: Emitter?) {
        private var baseline = 0L
        private var collected = 0L
        private var lastNs = 0L
        @Volatile var collectedTotal = 0L; private set
        @Volatile var backlogMax = 0L; private set
        @Volatile var lagMaxMs = 0.0; private set
        @Volatile var gapMaxMs = 0.0; private set
        @Volatile var backlogMaxAll = 0L; private set
        @Volatile var lagMaxMsAll = 0.0; private set
        @Volatile var gapMaxMsAll = 0.0; private set

        internal fun subscribed() {
            baseline = emitter?.emitted?.get() ?: 0L
            collected = 0L
            lastNs = 0L
        }

        internal fun collected(frame: CanFrame) {
            val now = System.nanoTime()
            collected++
            collectedTotal++
            if (emitter != null) {
                val backlog = emitter.emitted.get() - baseline - collected
                if (backlog > backlogMax) backlogMax = backlog
                if (backlog > backlogMaxAll) backlogMaxAll = backlog
            }
            val lag = (now - frame.elapsedNanos) / 1e6
            if (lag > lagMaxMs) lagMaxMs = lag
            if (lag > lagMaxMsAll) lagMaxMsAll = lag
            if (lastNs != 0L) {
                val gap = (now - lastNs) / 1e6
                if (gap > gapMaxMs) gapMaxMs = gap
                if (gap > gapMaxMsAll) gapMaxMsAll = gap
            }
            stalls.remove(name)?.let { ms ->
                sink("stall $name ${ms}ms begin")
                Thread.sleep(ms)
            }
            lastNs = System.nanoTime()
        }

        internal fun resetWindow() {
            backlogMax = 0L; lagMaxMs = 0.0; gapMaxMs = 0.0
        }

        internal fun emitterName() = emitter?.name
    }

    /** A loss-event counter fed by [count]. */
    class Counter(val name: String) {
        val n = AtomicLong()
    }

    private val counters = ConcurrentHashMap<String, Counter>()

    /** Count one loss event under [name], e.g. a frame the adapter flagged as overflowed. */
    fun count(name: String) {
        counters.getOrPut(name) { Counter(name) }.n.incrementAndGet()
    }

    private val emitters = IdentityHashMap<SharedFlow<*>, Emitter>()
    private val allEmitters = ConcurrentHashMap<String, Emitter>()
    private val collectors = ConcurrentHashMap<String, Collector>()
    private val stalls = ConcurrentHashMap<String, Long>()
    @Volatile private var sink: (String) -> Unit = {}
    private var reporter: Thread? = null

    /** Register the flow [flow] (the public one collectors see) under [name]. */
    fun register(flow: SharedFlow<*>, name: String): Emitter {
        val e = Emitter(name)
        synchronized(emitters) { emitters[flow] = e }
        allEmitters[name] = e
        return e
    }

    /** Make the collector named [name] sleep [ms] once, on its next frame (debug only). */
    fun requestStall(name: String, ms: Long) {
        if (enabled) stalls[name] = ms
    }

    /**
     * Report every [periodMs] through [out], once anything has been emitted. Later calls replace
     * the sink but keep the first period.
     */
    @Synchronized
    fun start(out: (String) -> Unit, periodMs: Long = 2_000L) {
        sink = out
        if (reporter != null) return
        reporter = thread(isDaemon = true, name = "flow-health") {
            while (true) {
                Thread.sleep(periodMs)
                report()
            }
        }
    }

    /** One report line per emitter and per collector; window maxima reset afterwards. */
    fun report() {
        for (e in allEmitters.values) {
            if (e.emitted.get() == 0L && e.failed.get() == 0L) continue
            sink("flow=${e.name} emitted=${e.emitted.get()} failed=${e.failed.get()}")
        }
        for (c in counters.values) sink("counter=${c.name} n=${c.n.get()}")
        for (c in collectors.values) {
            if (c.collectedTotal == 0L) continue
            sink("collector=${c.name} flow=${c.emitterName()} collected=${c.collectedTotal} " +
                "backlogMax=${c.backlogMax} lagMaxMs=${"%.1f".format(c.lagMaxMs)} " +
                "gapMaxMs=${"%.1f".format(c.gapMaxMs)} all: backlogMax=${c.backlogMaxAll} " +
                "lagMaxMs=${"%.1f".format(c.lagMaxMsAll)} gapMaxMs=${"%.1f".format(c.gapMaxMsAll)}")
            c.resetWindow()
        }
    }

    /**
     * One line for a notification: `drops 0`, or every non-zero count by name, e.g.
     * `drops pipe.log=12 gs_usb.overflowFlag=3`. Shown as `drops 0` rather than left out, so a
     * build that counts is distinguishable from one that does not.
     */
    fun summary(): String {
        val parts = allEmitters.values.mapNotNull { e -> e.failed.get().takeIf { it > 0 }?.let { "${e.name}=$it" } } +
            counters.values.mapNotNull { c -> c.n.get().takeIf { it > 0 }?.let { "${c.name}=$it" } }
        return if (parts.isEmpty()) "drops 0" else parts.sorted().joinToString(" ", prefix = "drops ")
    }

    /** Forget every flow, counter and collector; for tests, which share this object. */
    internal fun resetForTest() {
        synchronized(emitters) { emitters.clear() }
        allEmitters.clear(); counters.clear(); collectors.clear(); stalls.clear()
        enabled = false
    }

    internal fun collectorNamed(name: String): Collector? = collectors[name]

    internal fun emitterOf(flow: SharedFlow<*>): Emitter? = synchronized(emitters) { emitters[flow] }

    internal fun collector(name: String, flow: SharedFlow<*>): Collector =
        Collector(name, emitterOf(flow)).also { collectors[name] = it }
}

/**
 * This flow, measured as the collector [name] (see [FlowHealth]). Unchanged unless
 * [FlowHealth.enabled].
 */
fun SharedFlow<CanFrame>.watched(name: String): Flow<CanFrame> {
    if (!FlowHealth.enabled) return this
    val c = FlowHealth.collector(name, this)
    return onSubscription { c.subscribed() }.onEach { c.collected(it) }
}
