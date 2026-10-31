"""Integer-microsecond discrete-event scheduler (plan R5).

Everything that happens in a run is an event on one clock:
  - frame arrivals from a log, at their (shifted) timestamps    ORDER_RX
  - DLCM tasks, periodic with a declared phase                   ORDER_TASK (+ offset)
  - frame publication by the DLCM                                ORDER_TX
  - actuator, plant and sensor steps at their own dt_us           ORDER_ACT / PLANT / SENSOR

Events at the same instant run in (order, registration) sequence, so a run is
deterministic and the ordering assumptions are written down here instead of
being implied by loop structure. In particular a frame that arrives at exactly a
task's instant is visible to that task (RX before TASK), which is the behaviour
of an RX interrupt that completes before a task release at the same time.
Whether the real DLCM has that phase is NOT known; task `phase_us` is a declared
parameter for exactly that reason.

No floats in time. A period that is not a whole number of microseconds is an
error, not a rounding.
"""

import heapq
import itertools

ORDER_RX = 0
ORDER_TASK = 100
ORDER_TX = 200
ORDER_ACT = 300
ORDER_PLANT = 310
ORDER_SENSOR = 320


class Clock:
    def __init__(self, t0_us=0):
        self.t_us = int(t0_us)
        self._heap = []
        self._seq = itertools.count()
        self.tasks = []                 # (name, period_us, phase_us, order) for describe()

    def at(self, t_us, fn, order=ORDER_TASK):
        """One-shot: fn(t_us) at t_us."""
        if int(t_us) != t_us:
            raise ValueError("non-integer time %r" % (t_us,))
        heapq.heappush(self._heap, (int(t_us), order, next(self._seq), fn))

    def every(self, period_us, fn, phase_us=0, order=ORDER_TASK, name="", start_us=None):
        """Periodic: fn(t_us) at phase_us + k*period_us, from start_us (default now)."""
        if int(period_us) != period_us or period_us <= 0:
            raise ValueError("period must be a positive integer of us, got %r" % (period_us,))
        start = self.t_us if start_us is None else int(start_us)
        k = -(-(start - phase_us) // period_us)          # first k with t >= start
        t = phase_us + k * period_us
        self.tasks.append((name or getattr(fn, "__name__", "?"), period_us, phase_us, order))

        def tick(now, _fn=fn):
            _fn(now)
            self.at(now + period_us, tick, order)
        self.at(t, tick, order)

    def feed(self, rows, fn, shift_us=0, order=ORDER_RX):
        """Frame arrivals: rows is a SORTED list of (t_us, payload); fn(t_us, payload)
        runs at t_us + shift_us. Scheduled lazily, one pending event per stream."""
        it = iter(rows)

        def nxt():
            for t, p in it:
                t2 = t + shift_us
                if t2 >= self.t_us:
                    self.at(t2, lambda now, _p=p: (fn(now, _p), nxt()), order)
                    return
        nxt()

    def run_until(self, t_end_us):
        h = self._heap
        while h and h[0][0] <= t_end_us:
            t, _, _, fn = heapq.heappop(h)
            if t < self.t_us:
                raise RuntimeError("event in the past: %d < %d" % (t, self.t_us))
            self.t_us = t
            fn(t)
        self.t_us = max(self.t_us, int(t_end_us))

    def describe(self):
        return "\n".join("task %-28s period %6d us  phase %6d us  order %d" % row
                         for row in self.tasks)
