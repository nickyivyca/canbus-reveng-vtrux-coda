# Android logger timestamp defects, and the frames canre was silently dropping

**Established 2026-09-27**, with the `Coda steering angle` and `Coda wheel speed TPMS`
sessions. Started from a note in `canre/parsers/parsers.md` saying the parser could now
emit "a small negative timestamp, observed down to about -4 s", and ended with 4.8 million
recovered frames and 55 captures repaired on disk.

## The shape of it

`busmaster._DATA_RE` anchored the timestamp on `^(\d{1,2}:\d{2}:\d{2}:\d{4})`, which cannot
match a minus sign. The Android logger emits negative components — `00:00:-2:-3130`,
`00:-1:-26:-150`, `00:00:00:-050` — so `parse_file` fell through its `if not m: continue`
and the line was gone. No warning, no counter, no residue.

Swept over 3,674 files and 2,379,078,040 data-like lines:

| | lines |
|---|---|
| accepted by the shipped regex | 2,374,250,217 |
| **dropped, negative component** | **4,827,795** (0.203 %) |
| dropped, hour field > 2 digits | 1 |
| dropped, other | 27 |

1,715 files lost frames. The loss is not evenly spread — most files lose a handful and a
few lose most of themselves:

| loss | files |
|---|---|
| under 0.1 % | 1,555 |
| 0.1 – 1 % | 117 |
| 1 – 5 % | 18 |
| 5 – 20 % | 10 |
| **over 20 %** | **15** |

Worst: `coda_20260701_191203_T0` at 67.6 %, `coda_20260627_132627_T0` at 55.4 %,
`coda_20260624_193420_T0` at 44.3 % (447,123 lines). Every one of those had been analysed
and uploaded with a third to two thirds of its frames missing, all from the start of the
capture.

The two rejected classes that are **not** defects: the single line with a 5-digit hour is
`50224:01:46:2870` (5.7 years) and the other 27 are files whose last line is truncated
mid-record by an unclean close. Both should stay rejected. The hour field is deliberately
left at two digits — BUSMASTER does not wrap at midnight (`charge_M0_T52.log` contains
`24:01:29:4480`), so two digits covers any real capture.

## Two defects, not one

They are independent. A capture can have either, both or neither, and **several captures
with a clock rewind drop no lines at all** — `coda_20260330_122815_T0` has a 219.6 s rewind
and zero negative stamps. Fixing the regex alone would have left the rewind in place,
invisible.

`BusmasterWriter.kt` documents both in its own class comment as behaviours it replaced
(file mtime 2026-09-24 22:00).

### Short form — pre-open backlog

**1,627 files, 321 sessions.** The origin used to be the file-open time, so frames received
before the open but written after it went negative. Always a contiguous block starting at
line 1; worst magnitude -7.02 s. The class comment calls it "a few frames silently lost at
every 5-minute boundary".

**These stamps are already correct relative to the header.** The whole repair is to stop
discarding them. Confirmed at a chunk boundary: `coda_20260508_191742` T0's last `0x080` is
`t=299.9920 B6=21` and T1's first is `t=-0.0020 B6=22`, one counter step apart, with T1's
header 300.004 s after T0's — a 0.010 s join, exactly one `0x080` period at 100 Hz.

Still occurring on 2026-09-25 captures, so the deployed build predates the writer fix.
The owner confirms the Vtrux logger app was updated recently and its current logs are stale.

### Long form — backward wall-clock step

**55 files, 54 sessions, 57 distinct events**, last seen 2026-09-18. Offsets used to come
from wall clock; mid-file the phone's clock stepped back by 8 to 216 s, so every frame
written after the step carries a stamp low by that amount. The file then holds two blocks
whose stamped ranges **overlap**: `coda_20260508_191742_T0` is a prefix at 3.97..21.40
followed by the main stream at -2.31..299.99.

That a backward clock step is the mechanism rather than a genuine silence is **hypothesis
attributed to the writer's own comment** (it names the wall-clock path as the reason for
moving to monotonic `elapsedNanos`); a stepped NTP correction fits and has not been
verified against old code or phone logs.

That **no time passed at the junction** is not hypothesis. `0x080` B6 is a free-running
message counter at 100 Hz, and it advances by 1–2 across every junction, with 5–18 frames
of any id between the bracketing `0x080` frames. A real gap of this size would advance it
by hundreds. The step also appears on **every channel of a capture at the same instant**,
which is what a device-wide clock event looks like and not what a per-dongle artefact does.

Two junctions first looked like real gaps and are not: `coda_20260822_143801_T0` shows an
88.35 s backward stamp with a counter delta of 10–11, where a true 88 s gap needs 131 mod
256. It is a clock step plus a ~0.1 s frame-loss burst. **All 57 events are clock steps.**

**Which block is mis-stamped.** The counter proves adjacency but is invariant under a
constant offset, so it cannot say which side is anchored correctly. The chunk boundary
settles it, by the same `0x080` join above: the post-step block is correctly placed against
the header and the **prefix** is what moves, by `-step`. A repaired T0 then spans 319.7 s
inside a nominal 300 s chunk, which is consistent rather than contradictory — T0's header
is on the pre-step clock and T1's on the post-step clock, so 323.7 true seconds display as
300.004.

## What was repaired, and how

`artifacts/repair_clock_steps.py` moves one of the two blocks by the step, cumulatively
where a file has more than one. Because `t_before - step == t_after` by construction the
blocks then meet exactly, so **a repaired file becomes monotonic per channel in file order**
and the stamped ranges stop overlapping. Verified after the fact: 0 of 55 still contain a
backward step, frame counts and payload streams are unchanged.

**Which block moves is not a fixed rule, and getting it wrong is invisible in the file
itself.** The two choices differ by a constant offset in absolute time, and the header
cannot arbitrate because it is written at the first frame and so records whatever the clock
read at that moment. The neighbouring chunks can arbitrate, since their headers sit on one
clock or the other:

| | anchor | applies to |
|---|---|---|
| **Rule A** | post-step block; shift the pre-step block **down** | a later chunk exists — its header is already on the post-step clock, so this keeps the session continuous | 
| **Rule B** | pre-step block; shift the post-step block **up** | no later chunk — the only anchor is this file's own header, which is on the pre-step clock |

Rule B is the physically correct repair for a file considered alone. Rule A is preferred
whenever a later chunk exists, trading per-file header fidelity for session continuity,
which is what corpus analysis actually needs.

`artifacts/clockstep_session_join.py` measured this rather than assuming it, by asking
whether chunk N's last frame still meets chunk N+1's first under each rule. **Rule A joins
to within 0.004 s for 45 files and rule B would miss by the full step; rule B joins for the
files that are the last chunk of their session.** Two are ties and six are undecidable —
five single-chunk sessions and `coda_20260721_192435_T0`, whose session has a genuine
~230 s discontinuity that neither rule closes. The structural rule and the measurement agree
on every decidable case. Final split: **48 rule A, 7 rule B**, all seven a last-or-only chunk.

Originals are kept beside the repaired files; see the `pre-clockstep-repair/` folder in each
log root. The header is deliberately untouched, so only the timestamp field of pre-junction
data lines differs and every other byte is identical. Corrected stamps are written in the
logger's own signed convention, which canre now parses; re-basing to make them non-negative
would mean rewriting the header time and putting `canre/utils/timebase.py`'s per-session
classification at risk for no benefit.

Junctions are found **per channel**, because a two-dongle capture writes both channels
interleaved and one clock event would otherwise be counted twice. The channel number is used
only to keep the two dongles' streams apart, never to name a bus.

Each file is verified before it is installed, and the run refuses to install anything if any
file fails: identical line count, differing lines differing only in the timestamp field,
unchanged per-channel frame counts, no remaining backward step, an unchanged `0x080` payload
stream, exactly the anchored block left byte-identical while every other block moves, and
each former junction now continuous.

**Two of those checks were wrong before they were right, and both failures are instructive.**
The first asserted `span == span_before - total_step`. The span *grows* — the original
minimum was usually the post-step block's own negative start, and moving the prefix below it
extends the file backwards — so it failed all 55 files. That is the safe direction, and it
says nothing. The second used min/max as a proxy for "the anchored block did not move";
that is only a proxy, and it flagged the two files that genuinely needed rule B as errors
rather than as a different case. Asserting the block identity per line instead is exact.

The verifier is itself tested by deliberately breaking the repair: a half-size shift is
caught as a leftover backward step, a double-size shift as a 23.72 s junction gap.

## The repaired logs require the fixed parser — a coupling worth knowing about

Shifting a block moves part of the file below its header, so the signed convention appears
in captures that previously had none. Across the 55 repaired files the negative-stamped line
count went from **4,758,083 to 7,832,549**, and **19 files went from zero to some** —
`coda_20260810_094349_T0` from 0 to 195,945, `coda_20260918_191654_T0` from 38,340 to
470,653.

So a pre-2026-09-27 checkout of `canre` reading the repaired corpus drops *more* than it did
before the repair, silently. The parser fix and the log repair are not independent and must
not be separated: shipping the repair without the parser change would be a straight
regression. The `.orig` copies are the fallback for an older toolchain.

Raised by the `Coda wheel speed TPMS` session from the consumer side, which is where it was
visible and where I was not looking.

## The re-upload this needs, and why `influx_sync --plan` understates it

**`--plan` does not see the recovered frames.** It decides from the file's sha1, the DBC
message hashes and the policy hash. The 1,680 files that only gained lines from the regex
fix are byte-identical to what was uploaded, so nothing in the manifest changed and the plan
proposes no work for them. Only the 55 repaired captures show up, because their bytes did
change — the first `--plan` after the repair offered 51 `reupload_file` items and 16
`upload_new`, and that is not the whole job.

Two populations, needing different treatment:

| | files | sessions | lines recovered | treatment |
|---|---|---|---|---|
| **A** timestamps MOVED | 55 | 54 | 4,758,083 | `--delete` then re-upload the WHOLE session |
| **B** points only ADDED | 1,680 | 325 | 69,712 | plain re-upload, no delete |

**A needs the delete and `reupload_file` does not do one.** `influx_sync`'s `reupload_file`
calls `influx_upload.py` without `--delete`, so it overwrites points at matching timestamps
and cannot remove the old ones — and in these captures the timestamps *moved*, by up to
216 s. Without a delete the pre-repair points stay behind as ghosts alongside the corrected
ones. This is the same trap as the 2026-09-27 signal rename: a re-upload cannot remove what
the new parse no longer writes.

`influx_upload.py --delete` drops the series for `vehicle + session`, not for one file, so
each affected session must be re-uploaded in full rather than chunk by chunk. A
whole-vehicle `DROP SERIES` was refused by the sandbox as a mass delete on 2026-09-27;
54 per-session drops are the narrower form.

**98.6 % of the recovered frames are in population A**, so the 54 sessions carry nearly all
the value and B is a long tail worth doing but not urgent.

## The re-upload, as executed (2026-09-28/29)

**Done: 379 of 379 items, zero failures, 328.8 min.** 54 population-A sessions, then all
325 of population B. 350 invocations recorded a peak; none was terminated, none exited
non-zero, and the pre-invocation health gate never tripped. Server heap after the run was
0.40 GiB, the same order as the 0.23 GiB it started at.

Driven by `artifacts/run_repair_reupload.py`, which reads the plan, orders each population
smallest-first, splits a session into several `influx_upload.py` invocations when it exceeds
the current group limit, and records every completed item to
`artifacts/repair_reupload_done.ndjson` so an interrupted run resumes instead of repeating.

### The recovered frames are in InfluxDB — checked independently

The runner's own success report is not evidence that the *point of the exercise* landed, so
this was confirmed from the other end. In `coda_20260901_174433_T0.log` (a B-only file,
18,333 recovered lines) the first line the old regex accepted is at `0.0000 s` and the first
line the new one accepts is at `-7.0199 s`. That 7.02 s head of the capture exists only
because of the fix. Querying exactly that window: **17 `Cell69` points, against 14 in the
following 7 s** — comparable density, in a span that previously held nothing.

**Why the recovered frames are not before the anchor.** `timebase.anchor_ns` returns the
absolute instant of the file's *first frame*, and the parser rebases that frame to t=0. So
recovering earlier lines moves the anchor earlier by exactly the recovered span, and the
recovered frames occupy `anchor` to `anchor + 7.02 s`. A query of the window *before* the
anchor is correctly empty and does not mean the data is missing.

The same algebra is why population B adds points without moving any: a pre-existing frame at
raw `T_x` lands at `base + T_new + (T_x - T_new)` = `base + T_x`, independent of where the
first frame moved to.

### Memory: the linear law was wrong, and by how much

| invocation size | mean peak server heap |
|---|---|
| < 0.01 GB (n=50) | 0.26 GiB |
| > 1.0 GB (n=13) | 0.52 GiB |

Measured range: 0.0001-1.883 GB in, 0.23-0.90 GiB out — peak rises 3.8x across a 14,000x
range of input size, which is flat for planning purposes. Uploads are on-change, so points
queued scale with signal *changes*, not file bytes.

This retires the `peak = 0.055 + 11.04 x GB` relation that earlier drove a predicted 42 GiB
for population B on a 15.8 GB host. It predicted ~21 GiB for the largest invocation of this
run; that invocation cost **0.42 GiB**. The relation was an artefact of heap ratcheting
across a smallest-first ordering, and the settle-wait before each invocation removed the
mechanism. Do not reinstate a gate built on it.

A rise from 0.23 to ~0.68 GiB does occur over roughly the first 120 invocations and then
stops; it is a rise to a plateau, not a trend. Sampling it mid-rise reads as an unbounded
climb and is not one.

### Splitting large sessions

Five sessions exceeded the group limit and were split, all verified file-complete
afterwards by `verify_session_complete`: 2.17 GB/46 files, 2.17/49, 2.19/42, 2.34/46, and
the 3.82 GB/88-file largest capture in the corpus as three groups. That last one's two
1.88 GB halves peaked at 0.58 and 0.42 GiB — the second lower than the first, so a split
does not ratchet.

The group limit is adaptive (`1.5x` the largest invocation that stayed under 3 GiB, capped
at 1.9 GB). It walked 0.77 -> 1.90 GB as large invocations succeeded, so far fewer sessions
split than their sizes alone suggest.

### 48 sessions are in both populations

A session lands in A if any of its files was clock-step repaired, and contributes to B for
any *other* file that merely gained lines. **48 of the 54 A sessions also appear in B**, so
the two populations are not disjoint and the per-population session counts cannot be added.
The B entry for such a session re-uploads files the A whole-session re-upload already
covered; this is harmless, because a re-upload without `--delete` overwrites at identical
timestamps, but it is redundant work and it means 379 items cover 331 distinct sessions.

This overlap is also why anything keyed on the session name alone is wrong here — a
size lookup keyed that way let the smaller B entry overwrite the A size and understated
every backfilled measurement until it was keyed on `(population, session)`.

## Sorting: what changed, and what did not

AGENTS.md requires sorting each `(bus, id)` series before computing gaps, rates or ordering.
On the 55 unrepaired captures that advice **inverted** — file order was the true order and
sorting interleaved two different moments frame by frame. After the repair the rule is
simply correct again, which is the main reason the repair was done on disk rather than
papered over in a consumer.

Separately, `merge_files` feeds `heapq.merge`, which assumes sorted inputs, and a
multi-channel BUSMASTER file is not sorted as a whole even when each channel is. That is
ordinary interleave and the residual is small: over 844 Coda captures showing any backwards
step, the largest single step is **8 ms median, 48 ms p99**, and exactly one file exceeds
0.1 s. The docstring's promise of "sorted by timestamp" was wrong and has been corrected;
the behaviour has not changed.

**A number to be careful with.** An earlier count of "896 of 1,087 Coda captures contain a
backward step" was measured on the merged multi-channel stream and made the problem look
systemic. Per channel it is **5 of 249 sampled (2.0 %)**, and all five are clock-step files.

## Scale of the correction, from a consumer

A consumer session re-swept its corpus against the repaired files and separated the two
effects. Its figures are still in the proposal stage with the owner and are deliberately
**not** recorded here or in that session's own notes; ask for them rather than assuming this
section is complete.

What can be stated from measurements made in this session: **98.6 % of the 4,827,795
recovered lines are in the 55 repaired files** (4,758,083 against 69,712 spread over the
other 1,680), so the repaired captures carry almost all of the change and the parser fix
alone is a very thin tail. Two captures that had been losing 217,335 and 400,030 lines --
`coda_20260619_193709_T0` and `coda_20260627_132627_T0` -- are the largest single recoveries
in the corpus.

**Two questions, two verifiers.** Verifying a repair against the originals asks "was anything
lost", and that is the right question -- but it structurally cannot see what a *different*
reader does with the result. The old-parser regression above was invisible to every check in
this folder, all of which compare a repaired file to its own backup, and was obvious from the
consumer side. The second question is not a stricter version of the first and no amount of
care on the first reaches it.

**An exact-zero downstream delta is not evidence that a repair did nothing.** A capture whose
step falls outside whatever population a consumer is measuring scores exactly zero while the
repair has plainly run. This is why the repair is verified here by identity, monotonicity and
counter continuity rather than by any downstream measurement.

## Files changed

| file | change |
|---|---|
| `canre/parsers/busmaster.py` | `_DATA_RE` accepts signed components; `_parse_timestamp` unchanged |
| `canre/utils/timebase.py` | same, so `read_data_bounds` sees a pre-origin first frame |
| `tools/artifacts/timebase_anchor_check.py`, `busmaster_timebase_survey.py` | same pattern |
| `canre/utils/merge.py` | docstring: output is merged, not guaranteed sorted |
| `data-sources.md`, `tools/tools.md`, `canre/parsers/parsers.md` | corrected |

`_parse_timestamp` needed no change: summing the signed components reproduces the original
offset exactly. Verified by round-tripping 4,010 values through a reimplementation of the
Kotlin formatter — 0 mismatches, while the shipped regex rejected 1,312 of them.

## Scripts

All in `artifacts/`:

| script | does |
|---|---|
| `negative_timestamp_survey.py` | per-file first/min/max and inversion counts |
| `dropped_line_survey.py` | how many lines the shipped regex discards, and why |
| `clockstep_classify.py` | short form vs long form vs clean, corpus-wide |
| `clockstep_verify.py` | per-channel junction verdicts via the `0x080` counter |
| `repair_clock_steps.py` | the on-disk repair, with backup and verification |
| `clockstep_session_join.py` | which block is the anchor, measured by chunk-to-chunk continuity |
| `build_repair_reupload_plan.py` | splits the corpus into populations A and B; read-only |
| `run_repair_reupload.py` | executes the plan: splitting, health gates, verification, resumable history |

## Related

- `key-cycle-detection.md` — the phantom dropout events this class of bug produced
- `canre/parsers/parsers.md` — parser-level detail
