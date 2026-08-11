# InfluxDB Sync — Incremental DBC-Aware Uploader Plan

> **NOTE:** This file lives in `tools/plans/influx-sync.md` per CLAUDE.md policy.

**Status:** in progress. Written 2026-08-09.
Phases 1 through 4 complete. The database was wiped and rebuilt from the full corpus on
2026-08-10; only Phase 5 (scheduling) remains.

---

## Goal

An unattended uploader that keeps InfluxDB in agreement with the local logs and the local
DBCs, where **InfluxDB and the DBCs are the only sources of truth**. Notes and success-logs
may inform the diff but must never be required for correctness.

Two capabilities:

1. **Backfill** — upload every local log not yet in InfluxDB.
2. **Repair** — when a DBC message definition changes, re-upload *only that message*,
   not the whole log.

**Starting point (decided 2026-08-09): wipe the existing `signals` data and rebuild.** The
current contents carry two schemas, orphan series, an escaping bug and pre-anchor-fix
timestamps, and represent only 19% of the corpus. Repairing that incrementally would mean
carrying reconciliation machinery for data about to be replaced. Everything below therefore
assumes the database starts empty; the incremental machinery exists to keep it correct
*from then on*, which is the case it was actually designed for.

The diff must be computed by a script and handed straight to the re-uploader as
machine-readable work items. No LLM in the loop between diagnosis and repair.

---

## Measured Baseline

All figures measured 2026-08-09 against `localhost:8086` and the local corpus, not estimated
unless marked. Scripts that produced them are in `tools/artifacts/` (see File Layout).

### InfluxDB

| Property | Value | How measured |
|---|---|---|
| Version | InfluxDB 1.8.10 OSS | `/ping` response header |
| Database | `canbus-data` | `SHOW DATABASES` |
| Retention policy | `autogen`, **infinite**, 7-day shards | `SHOW RETENTION POLICIES` |
| Measurements | `signals` only (`raw` never used at scale) | `SHOW MEASUREMENTS` |
| Disk | **2.585 GB** (`homeassistant` 0.564, `_internal` 0.041) | `/debug/vars` shard `diskBytes` |
| Series | 7,080 | `SHOW SERIES CARDINALITY` |
| Field keys | 696 | `SHOW FIELD KEYS` |
| Sessions | 106 | `SHOW TAG VALUES ... "session"` |
| Field values | **576,328,314** | per-session `SELECT COUNT(*)`, summed |
| Density | **4.49 bytes/value on disk** | 2.585 GB / 576.3M |

### Host

| Property | Value |
|---|---|
| Disk total / used / **free** | 468.7 GB / 30.4 GB / **419.2 GB** |
| Data disk | Samsung SSD 960 PRO 512GB |
| SSD life consumed | 26% |

Capacity is **not** a constraint and is not a design driver. The binding constraints are
query performance (an unscoped `SELECT COUNT(*) FROM signals GROUP BY session` already
resets the connection today) and re-upload wall-clock time.

### Local corpus

| Root | Files | Size |
|---|---|---|
| `projects/vtrux/logs` | 440 | 47.90 GB |
| `projects/coda/logs` | 89 | 2.44 GB |
| `../../CANLogs/VtruxLogs` | 1869 | 32.83 GB |
| `../../CANLogs/CodaLogs` | 758 | 18.50 GB |
| **Total** | **3,156** | **101.67 GB** |

Per the three `upload_success.txt` files, 335 files / 19.33 GB (19.0%) are uploaded.
Those files store **Windows absolute paths** (`<home>\<drive-root>\...`)
and match nothing on a Linux machine — they are not usable as sync state and are superseded
by this design.

### Known defects found while measuring

Defects 1–4 are **data** defects in what is currently stored. All are dissolved by the
Phase 4 wipe-and-rebuild rather than repaired in place; they are recorded here because they
are what made incremental cleanup a bad trade. Defects 5–6 were code defects, fixed in
Phase 1.

1. **Timestamp float noise.** `stream_and_write` computes
   `int((start_epoch + frame.timestamp) * 1_000_000_000)`. Sampled real stored deltas on a
   20 Hz message: `49999872, 50000128, 50000128, 49999872, …` where the true delta is
   `50000000`. Sub-microsecond remainders alternate `872 / 744 / 0`. BUSMASTER's source
   resolution is integer 0.1 ms ticks, so this jitter is pure float64 round-trip error.
2. **Two schemas coexist in `signals`.** 2,364 of 7,080 series still carry the legacy
   `signal` tag + `value` field, from 6 sessions: `codadriveslowturnonwithdefroster2`,
   `generator\ on\ then\ off`, `vtrux_to980`, `vtruxcurrentlimitingtest`,
   `vtruxdrivetrainoverheattest`, `vtruxgeneratoroverheattest`.
   Those 6 sessions hold **214,795,293 values = 37.3% of the entire database**.
3. **All orphan data is inside those 6 sessions.** 39,048,016 values belong to CAN IDs that
   the current `VEHICLE_PROFILES` exclusion rules say must not be uploaded (gateway
   rebroadcast duplicates). Orphan count in every other session is **zero** — the exclusion
   rules were added after those 6 uploads and have been respected since.
4. **Tag-value escaping leak.** Session tag `generator\ on\ then\ off` contains literal
   backslashes. `stream_and_write` deliberately skips line-protocol tag escaping on the
   stated invariant that tag values cannot contain `, =` or spaces; a `--session` override
   with spaces broke that invariant.
5. **`--dry-run` requires a package it never uses.** The dependency check aborts if
   `influxdb` is absent, but dry-run performs no network I/O. Blocks offline validation.
6. **`influxdb` package is nearly dead weight.** Writes already go through `requests`.
   `InfluxDBClient` survives only for two `client.query()` calls (lines 931/936).

### Verified InfluxDB behaviours this design depends on

| Behaviour | Verified how |
|---|---|
| `SELECT COUNT(*) ... GROUP BY bus,can_id` returns a column per field key but **non-null only for fields present in that series** | run against `coda` / `2026-04-26`: 63 groups, correct per-message field sets |
| `DROP SERIES` works over raw HTTP **POST** | no-match predicate, returned clean; GET returns a deprecation warning |
| `DELETE ... WHERE <tag> AND time >= a AND time < b` is accepted and authorized | no-match predicate, returned clean, cardinality unchanged |
| `claude` user is **not** admin | `SHOW SHARDS` and `CREATE DATABASE` both denied |

---

## Design

### Schema — Grafana-visible parts unchanged

`signals` keeps measurement name, tags `vehicle,bus,can_id,session`, and signal-name fields
exactly as they are, so no dashboard needs rebuilding. Session tag **values** are regenerated
per capture by the rebuild — safe because session is not used as a Grafana filter, and the
only breakage would be a variable or saved query pinned to a specific session name.

One new measurement is added. Grafana never queries it.

```
upload_manifest
  tags   : vehicle, session, file          (file = log basename)
  fields : rel_path, log_sha1, log_bytes, mtime,
           encoding_ver, policy_hash,
           msg_hashes      (JSON string, can_id -> 12-hex def hash)
           bus_map         (JSON string, channel -> bus name)
           points, t_start_ns, t_end_ns, uploaded_at
```

~3,156 series at full corpus. Negligible against a projected ~21,000 for `signals`.

### The message definition hash

Per `(bus, can_id)`, hash **only decode-relevant properties** of every signal that would be
written after exclusions: name, start bit, length, byte order, signedness, scale, offset,
min, max, multiplexer ids, is_multiplexer.

Deliberately excluded from the hash: comments, value tables, receiver lists, message name.
Editing a `CM_` must not trigger a re-upload.

Multi-DBC merge order must mirror `decode_frame()` — later DBC wins on signal-name
collision. Measured: 49 of 270 vtrux `(bus,can_id)` definitions and 5 of 181 coda ones are
defined in more than one DBC, so this is not a corner case.

### Three-layer diff

Each layer catches what the cheaper one cannot.

**L0 — manifest.** Two queries total. Pull the whole manifest, walk the local roots,
stat each file. Compare `log_sha1`/`log_bytes`/`mtime`, `msg_hashes` vs the current DBC
hashes, and `policy_hash`/`encoding_ver` vs current. Cheap, but trusts the manifest.
This is the **only** layer that can detect a scale/offset/bit-position change where the
signal name did not change.

**L1 — data-derived.** One `SELECT COUNT(*) FROM signals WHERE vehicle=.. AND session=..
GROUP BY bus,can_id` per session. The non-null column set *is* the uploaded signal set.
Trusts nothing. Detects renames, additions, deletions, orphans, legacy-schema series, and
missing/partial data. If the manifest claims something the data does not have, L1 wins and
escalates.

Already prototyped and working — `influx_dbc_diff_prototype.py` correctly identified real
drift on live sessions (`0x598` `DBL_ESSPwrAvg`→`ess_power`, `0x270`
`BMSFaultCode`→`BMSRedLampReq`, `Cell16`→`Cell20`, the `value` field of legacy sessions,
and 27 orphan series in one session).

**L2 — `--deep`, on demand.** Re-parse the local log with the current DBC and compare
expected per-`can_id` counts against actual. Catches everything, trusts nothing, costs a
full read. For spot-checks and for validating L0's hash logic, not routine runs.

### Repair granularity — (file × can_id)

`derive_session()` maps many files to one session tag. Measured across the corpus:
3,156 files collapse to **313** derived sessions; `2026-07-14` bundles 144 files / 6.3 GB
and `2026-07-26` bundles 133 files / 6.3 GB. (`2026-03-30` bundles 887 files but they are
near-empty.)

So a per-`can_id` `DROP SERIES` would still force re-reading 6.3 GB to rebuild. Instead,
exploit the fact that chunks within a session are **time-disjoint** and that the manifest
records each file's `t_start_ns`/`t_end_ns`:

```sql
DELETE FROM signals
 WHERE "vehicle"='vtrux' AND "session"='2026-07-14' AND "can_id"='0x598'
   AND time >= <t_start_ns> AND time < <t_end_ns>
```

Repair unit becomes one message in one chunk — re-read one ~50 MB file, not 6.3 GB.
`DROP SERIES` is retained only for whole-series removal (orphans, legacy rebuild).

Constraints to respect: `DELETE` accepts tag and time predicates only, never fields —
fine, `can_id` is a tag. Deletes write tombstones; space returns on compaction.

### Work-list format

`influx_sync.py --plan` emits newline-delimited JSON; `--apply` consumes the same format,
so a plan can be reviewed, edited, stored, or scheduled.

```json
{"action":"upload_new","vehicle":"vtrux","session":"2026-07-14",
 "files":["../../CANLogs/VtruxLogs/vtrux_20260714_112312_T6.log"],"reason":"not_in_manifest"}
{"action":"reupload_ids","vehicle":"vtrux","session":"2026-07-14","can_ids":["0x598"],
 "files":[...],"t_start_ns":...,"t_end_ns":...,"reason":"msg_hash_mismatch"}
{"action":"drop_series","vehicle":"coda","session":"...","can_ids":["0x080"],
 "reason":"excluded_by_policy"}
{"action":"rebuild_session","vehicle":"vtrux","session":"vtruxgeneratoroverheattest",
 "reason":"legacy_schema"}
```

`--apply` is idempotent and resumable: the manifest point for a file is written only after
that file's upload completes, so an interrupted run replans correctly.

---

## Uploader changes required

| Change | Why |
|---|---|
| `--only-id 0xNNN [...]` filter | targeted re-upload; skip decode and write for all other IDs |
| Integer timestamp path | fix defect 1 — derive `ts_ns` from integer ticks, never float seconds |
| Escape tag values | fix defect 4 |
| Emit manifest point per file | L0 state, incl. `t_start_ns`/`t_end_ns` |
| Drop `influxdb` import, use raw HTTP POST for `DROP`/`DELETE` | fix defects 5 and 6 |
| Optional `--on-change` write policy | storage/query-volume lever, see below |

---

## Storage levers (measured)

Not needed for capacity — needed to keep Grafana responsive as the corpus grows ~5×.

**Lever A — rebuild the 6 legacy sessions.** Reclaims 214,795,293 values = **37.3%** of
the database, and eliminates 100% of orphan data in one action. Measured, not estimated.

**Lever B — integer timestamps. MEASURED 2026-08-09: NO STORAGE BENEFIT. Hypothesis
refuted.**

Experiment (`tools/artifacts/ts_encoding_experiment.py`): the same decoded log written three
ways into measurement `tsbench`, each anchored to a different empty year so each landed in
its own 7-day shard and `diskBytes` isolated it. Variants A and B held byte-identical values
and differed **only** in timestamp quantization.

| Variant | Shard | diskBytes | Values | B/value | vs A |
|---|---|---|---|---|---|
| A `float_ns` (current bug) | 354 | 7,766,475 | 1,231,653 | 6.31 | 1.000x |
| B `int_ns` (Lever B) | 355 | 7,847,836 | 1,231,653 | 6.37 | **1.010x** |
| C `onchange` + int ts | 356 | 2,200,660 | 258,742 | 8.51 | **0.283x** |

Integer timestamps came out **1% larger** — noise, but decisively not a win.

*Why the hypothesis was wrong:* it assumed removing float noise would make inter-point
deltas constant, unlocking TSM's run-length timestamp encoding. It does not. Real capture
jitter at the 0.1 ms tick level means the deltas were never constant to begin with, so RLE
was never reachable — the float noise was riding on top of jitter that already ruled it out.
TSM's fallback (divide deltas by their GCD, then simple8b-pack) handles both cases about
equally well.

**Keep the change anyway, but for correctness, not storage:** exact, reproducible timestamps
with no float drift, and exact boundaries for the time-bounded `DELETE` that the
(file x can_id) repair unit depends on. It is **not** a Phase 1 gate and does **not** need to
land before the backfill.

Caveat on the numbers: `diskBytes` stabilized post-cache-snapshot but before full compaction
(`compact-full-write-cold-duration` defaults to 4 h), which is why all three sit above the
fully-compacted production figure of 4.49 B/value. All three received identical treatment, so
the comparison holds; only the absolute values are inflated. Test data was dropped afterwards
and `signals` cardinality verified back at exactly 7,080.

**Lever C — write-on-change.** Measured on `vtrux_20260617_193900_T18.log` (52.4 MB):

| Policy | Values | Share |
|---|---|---|
| current (every frame) | 1,231,653 | 100% |
| on-change only | 217,468 | **17.7%** |
| on-change + 1 s heartbeat | 255,606 | **20.8%** |
| decimate to 1 Hz | 46,839 | 3.8% |

Line-protocol *lines* only fall to 42%, so per-point overhead amortizes over fewer fields
and real disk savings land below the 4.8× the value count implies.

**MEASURED 2026-08-09 (variant C of the same experiment): 0.283× disk = 3.5× reduction.**
The predicted mechanism held exactly — bytes/value *rose* 6.31 → 8.51 as fields per point
fell, but total disk still dropped 3.5× because value count fell 4.8×. The earlier ~3×
estimate was slightly conservative.

On-change + 1 s heartbeat is chosen over pure on-change so Grafana's last-value-before-window
stays correct and gaps stay bounded.

Whole messages are near-pure waste today: powertrain `0x400` is 7.1% of all values in that
log with `hsc_bcm_enable`, `hsc_bcm_epo`, `hsc_bcm_mainc_close`, `hsc_bcm_leakage_ena` all
at **0.0% change rate**, each written 21,907 times.

**Projection.** Measured yield is 29.8M values per GB of log. Full corpus at current policy
≈ 3.03B values ≈ **13.6 GB**; with Lever C at the measured 0.283× ≈ **3.9 GB**. Against
419 GB free, either fits comfortably — Lever C is for query performance, not capacity.

Sequencing: **Lever C is the one that must land before the backfill**, since the write policy
is baked into the stored data and is retroactively unfixable without re-uploading. Lever B
(integer timestamps) has no storage effect and can land whenever.

---

## Phases

Each phase ends at a review gate per CLAUDE.md — stop, present findings, write them to
notes, update this file, then continue.

**Phase 0 — decisions.** Settled 2026-08-09; see Decisions below. Two items remain open and
are gated to Phase 5: the InfluxDB index type, and whether the parts truck gets its own tag.

**Phase 1 — uploader fixes. COMPLETE 2026-08-09.**

Shipped in `tools/influx_upload.py`:
- `--write-policy on-change|all-frames` (**default on-change**) + `--heartbeat SECONDS`
- integer-nanosecond timestamps end to end (`derive_start_epoch_ns`, `read_log_start_time_ns`)
- `escape_tag()` applied to all tag values, once per cached prefix
- `influxdb` package dependency removed; `DROP SERIES` via `influx_statement()` raw HTTP POST
- `--dry-run` no longer requires `requests`

*Gate 1 (Lever B measurement) — CLOSED by `ts_encoding_experiment.py`; hypothesis refuted.*

*Gate 2 (on-change loses no information) — PASSED by `tools/artifacts/on_change_equivalence.py`
on three logs. It runs both policies through the real `stream_and_write()` and asserts the
reconstruction property: forward-filling the on-change series reproduces the all-frames
series **exactly** at every timestamp.*

| Log | Lines | Values | Result |
|---|---|---|---|
| `vtruxinterlocktest2.log` (22 MB, static) | 6.1% | 4.5% | PASS |
| `vtrux_20260617_193900_T18.log` (52 MB, driving) | 42.0% | 20.8% | PASS |
| `coda_20260721_202537_T6.log` (42 MB, coda) | 50.8% | 23.7% | PASS |

Two defects were found by the dynamic logs after the static one passed clean, and fixed:

1. **Heartbeat compared in float seconds.** A sample landing exactly one heartbeat later
   evaluated as `0.9999999999 < 1.0` and was skipped to the next frame (6 in 1.2M). Now
   compared in integer ns.
2. **Duplicate timestamps** — *not* a code defect and *not* caused by on-change. BUSMASTER's
   0.1 ms tick resolution puts two frames of one CAN ID on the same tick occasionally
   (measured 2 in 21,669 frames of vtrux obd `0x044`, different payloads). InfluxDB
   overwrites on identical (series, field, timestamp), so the earlier frame is lost under
   **either** policy. The checker now collapses by timestamp to match InfluxDB semantics.
   **Open, out of Phase 1 scope:** a per-series monotonic-ns nudge would preserve both
   frames at ~zero cost. Rate is ~0.009%.

Live end-to-end verification against `localhost`, all cleaned up afterwards
(`signals` cardinality confirmed back at exactly 7,080):
- session tag `phase1 smoke test` stored **without** backslashes (contrast the legacy
  `generator\ on\ then\ off`)
- stored timestamps land on exact 0.1 ms multiples — sub-microsecond remainder `0` on every
  sampled point, vs the pre-fix `872 / 744 / 872 / 0`
- `--delete` then re-upload is idempotent: 12,549 values before and after, proving the raw
  HTTP `DROP SERIES` fires before the re-upload rather than doubling the data

**Phase 1.2 — repair vertical slice. COMPLETE 2026-08-09.**
`tools/artifacts/repair_slice_test.py`, on session `2026-05-05` (4 coda chunks, 120 MB,
uploaded under throwaway tag `zz_slice_test`, dropped afterwards; cardinality confirmed back
at 7,080). Added `--only-id` to the uploader.

| Phase | Result |
|---|---|
| A baseline: 4 chunks, one session tag | 31 series, 1,151,891 values |
| B idempotent repair (same DBC) | **PASS** — deleted 22,796 values from one chunk's 300 s window, re-upload reproduced every series identically |
| C drift repair (overlay adds a signal) | **PASS** — 300 new values inside the subject window, **0** outside, no other series changed, no original signal lost |

Per-(file x can_id) repair works. `--only-id` + time-bounded `DELETE` rewrites exactly one
message in exactly one chunk and leaves the neighbouring chunks in the same session untouched.

Two findings that change the design:

1. **Repair bounds must never be recomputed — they must be recorded.** The first phase-B run
   deleted nothing: the test recomputed the window with the tz-naive default (UTC) while
   `influx_upload` had written the data with its `--tz America/Los_Angeles` default, putting
   the bounds 7 h off the stored points. The DELETE silently matched zero rows and the repair
   degraded into an append. Any config that feeds the anchor (tz, filename parsing, header
   fallback) can drift the same way. **`t_start_ns`/`t_end_ns` in the manifest are therefore
   a correctness requirement, not a convenience.** A repair must also verify its DELETE
   removed a non-zero count before re-uploading, or a silent no-op looks like success.

2. **L1 alone cannot drive per-file repair — the manifest is a prerequisite, not an
   optimization.** This answers the question the slice was designed to settle. After
   repairing 1 of 4 chunks, the session-scoped `SELECT COUNT(*) ... GROUP BY bus,can_id`
   reports the field set as the **union across all chunks**, so `SliceProbe` shows up with
   300 values and a session-scoped diff concludes `0x1D5` now matches the DBC — while three
   chunks are still stale. L1 remains the right tool for detecting drift and for verifying
   the manifest is not lying, but per-file staleness is only knowable from per-file
   `msg_hashes`.

**Phase 1.5 — BUSMASTER anchor correctness. COMPLETE 2026-08-09.**

> **Correction.** An earlier draft of this section claimed wall-clock BUSMASTER logs would
> upload "up to ~24 h wrong" across 348 files / 14.74 GB. **That was wrong.**
> `BusmasterParser.parse_file()` re-bases every file so its first data frame is `t=0`, so the
> raw time base never reaches `frame.timestamp` and the 24 h displacement cannot occur. The
> real defect is smaller and is described below. The survey and classifier built for the wrong
> diagnosis turned out to be exactly what the real fix needed, so both were kept.

**The real defect.** The anchor was the header's *stated* start time, but the true instant of
a file's first frame can differ from it. Two loggers behave differently:

```
Android logger (CANLogs), coda_20260505_192535_T0..T3
  T0  hdr 19:25:35  first 00:00:00  last 00:04:59   <- resets every chunk
  T1  hdr 19:30:35  first 00:00:00  last 00:05:00

Laptop BUSMASTER, debuglog_M1_T8..T10
  T8  hdr 12:07:43  first 11:04:39  last 12:12:43   <- wall clock, HEADER TIME IS WRONG
  T9  hdr 12:12:43  first 12:12:43  last 12:17:43   <- wall clock, header exact
```

- **Relative** files start their data at 0, so the data cannot say what time of day it was and
  the header time is the only source. Unchanged behaviour.
- **Wall-clock** files carry the true time of day in the data, so only the header's **date** is
  needed and a wrong header *time* becomes recoverable.

**Midnight is a non-issue.** BUSMASTER does not wrap the hour: `charge_M0_T52.log` literally
contains `24:01:29:4480` (min and max hour in that file are both 24). Rolling into the next
day falls out of the `floor(first_T / 86400)` term; no rollover counter exists or is needed.

**Classification is per session, never per file.** `debuglog_M1_T8`'s own header disagrees
with its own data and is only decidable because its last timestamp meets `T9`'s first exactly
(`12:12:43:2001` both). Sessions come from `detect_capture_sessions()` — the existing library
function — not from filename parsing.

Shipped:
- `canre/utils/timebase.py` — `TimebaseIndex`, `classify_session()`, `read_data_bounds()`.
  Evidence order: chunks-reset-to-zero (Android) > header/time-of-day agreement by majority >
  chunk continuity carrying a session whose headers are unreliable. Defaults to `relative`,
  i.e. the pre-existing behaviour, so an unrecognised layout is never newly displaced.
  Anchor = the absolute instant of the file's first frame.
- `influx_upload.derive_start_epoch_ns()` takes an optional shared `TimebaseIndex`.
- **Header regex relaxed.** BUSMASTER does not zero-pad (`12:2:2025`, `0:1:30`); the old
  `\d{2}` pattern rejected **356 of 3,135** headers and fell through to the filename/mtime
  fallbacks silently.

**Third defect, found while validating: the header's sub-second field is MILLISECONDS.**
Data-line trailing fields are 10 kHz ticks (0.1 ms), but the header's is not. Across 1,062
headers the value never exceeds **998**; data-line values reach **9999**. Both
`read_log_start_time_ns` and the first draft of `timebase.py` read the header as ticks and
were wrong by 10x sub-second. (`merge.read_chunk_start()` has always read it as milliseconds
and is correct — an earlier note in `utils.md` claiming otherwise has been retracted.)

**Fourth: relative files also need `+ first_T`.** The raw timestamps count from the
logging-start marker, and `parse_file()` discards the gap to the first frame by re-basing to
zero. `vtruxinterlocktest2.log`: header 22:03:23.980, first data line `00:00:23:2276` — its
first frame is 23.2 s later than the anchor said. 279 relative files have a gap >= 1 s, up to
~6.5 min. So both kinds reduce to `base + first_T`; only the base differs.

Measured impact (`tools/artifacts/timebase_impact_check.py`, all 3,156 files, comparing
*effective* anchors including fallbacks):

| | |
|---|---|
| classified wall clock / relative | 324 / 2,832 |
| files whose anchor moved | **912** |
| < 0.1 s / 0.1–1 s | 150 / 208 |
| 1–60 s / 60 s–10 min / > 10 min | 95 / 5 / 42 |

**This does move already-uploaded data: 193 files across 50 of the 106 live sessions.**
Live moves are 21 under 0.1 s, 10 at 0.1–1 s, 28 at 1–60 s, and 2 between 1 and 10 min; the
largest is `2026-03-22` at 389.5 s.

**This turned out not to matter.** The live-data impact was analysed as a constraint on
whether the fix could ship without a rebuild — but Phase 4 wipes everything anyway, so the
constraint is void. What survives is that the anchor is now *correct*, which is true
independently of any rebuild, and that `timebase_impact_check.py` becomes a **regression
guard for after the backfill**, when a silently moving anchor would be a real bug.

Keeping the old relative anchoring was rejected regardless: it would knowingly preserve errors
of up to 6.5 min, which matters for cross-referencing the `homeassistant` database on the same
server (solar and power draw) where absolute alignment is the whole point.

Verified end to end: `212charge_M1_T0.log` (wall clock, header 16:51:57, first data line
16:52:11.2513) stores its first point at 16:52:11.2573 Pacific — the 6 ms being the first
frame that actually decodes. All eight hand-checked cases (wall clock, midnight crossing,
bad header, Android reset, near-midnight relative, long pre-roll) resolve to their true
first-frame instants. Test sessions dropped; cardinality back at 7,080.

Still outstanding: skip the 989 zero-row files with a minimum-frame filter.

**Phase 2 — manifest. COMPLETE 2026-08-10.** (`--only-id` shipped in Phase 1.2.)

Shipped:
- `canre/dbc/msghash.py` — `message_hashes()` over decode-relevant signal properties only,
  with exclusions folded in so the same CAN ID can hash differently per bus (correct: the
  Vtrux gateway makes `0x0C9` genuinely different on `obd` vs `vehicle`). Comments, value
  tables, receiver lists and message names are excluded, so editing a `CM_` never triggers a
  re-upload.
- `stream_and_write()` now returns observed stats — `points`, `values`, `t_start_ns`,
  `t_end_ns`, and the set of `(bus, can_id)` actually written — instead of a bare count.
- `upload_manifest` point per file, written **after** its data lands so an interrupted
  upload leaves no row claiming completion.

Wipe-and-rebuild removed the hard part: there is no pre-existing data to reconcile against,
so every manifest row is written by the upload that created it rather than reconstructed by
archaeology from L1.

**One defect caught in test:** the first implementation stored an *absolute* `rel_path` for
files outside the repo (`<home>/Seafile/CANLogs/...`) — precisely what makes the old
`upload_success.txt` files useless on any other machine. Now `os.path.relpath` against the
project root, so the sibling Android library records as `../../CANLogs/CodaLogs/...`.

*Gate — PASSED* (`tools/artifacts/manifest_l1_agreement.py`, session `2026-05-05`, 4 chunks):

| Check | Result |
|---|---|
| manifest rows / L1 series | 4 / 31 |
| every claimed series present in data, every data series claimed | yes |
| values: manifest vs L1 | 1,151,891 = 1,151,891 |
| per-file windows disjoint and ordered | yes, min gap 7.0 ms over a 980.6 s span |
| claimed hashes vs current DBC | 0 drift |

The value total independently matches the Phase 1.2 slice-test baseline for the same session.
Disjoint windows are the property the repair path depends on — an overlap would let one
chunk's repair silently eat a neighbour's data. Test data dropped; cardinality back at 7,080.

**Phase 3 — `tools/influx_sync.py`. COMPLETE 2026-08-10.**

L0 + L1, `--plan` / `--apply`, work list as NDJSON. Also folds in the three items that were
decided but unimplemented: per-capture session naming (via `detect_capture_sessions()`), the
explicit exclude-path deny-list, and the empty-file filter.

**Discovery is non-recursive by owner decision** — specialised folders opt in explicitly:

| In scope (4 roots, top level) | 2,861 files | 85.7 GB |
|---|---|---|
| Requires opt-in (6 subfolders) | 295 files | 16.0 GB |

Truck 3's truck folder falls out of scope naturally, and is *also* on the hard deny-list so an
explicitly named path cannot bypass it.

**First plan against the empty-manifest state:**

```
manifest rows: 0    sessions live in InfluxDB: 106
discovered 2861 file(s) across 4 root(s), non-recursive
skipped 977 file(s) with no usable data
upload_new   516 items   1884 files   85.67 GB
```

516 sessions projects to ~34,600 series — well inside the `inmem` index's comfort range, and a
third of the 103k the earlier per-capture estimate suggested, because
`detect_capture_sessions()` groups more sensibly than a filename-prefix count.

**Performance defect found and fixed:** the first `--plan` ran the L1 scan unconditionally and
had not finished after 30 minutes — 212 full-session `COUNT(*)` queries, each scanning every
point in its session, and it probed every session against *both* vehicles. L1 is now opt-in
(`--check-existing`) and resolves each session's vehicle in one cheap `SHOW`. **The default
plan now takes 1.06 s.**

*Gate — PASSED.* `--apply --limit` on two small sessions: both pass
`manifest_l1_agreement.py` (values 3,380 = 3,380 and 2,294 = 2,294, zero hash drift, windows
disjoint), and a re-plan drops them from the work list (516 -> 514 sessions, 1884 -> 1880
files), proving idempotence. Test data dropped; cardinality back at 7,080.

**Phase 4 — wipe and rebuild. COMPLETE 2026-08-10.**

`DROP SERIES` on `signals` / `raw` / `upload_manifest`, then `influx_sync.py --apply` over
the full plan. Pre-wipe session list archived to `tools/artifacts/prewipe_sessions.json`;
per-session value counts were already in `influx_storage_audit.json`.

**Result: 516/516 work items, 1,876 files, 85.67 GB read, 0 errors, 0 warnings, ~4.7 h.**

| | Before (19% of corpus) | After (100% of corpus) |
|---|---|---|
| sessions | 106 | **508** |
| series | 7,080 | **19,958** |
| values | 576,328,314 | **349,670,636** |
| points | — | 188,233,471 |
| disk | 2.620 GB | **1.316 GB** |
| bytes/value | 4.49 | 3.76 |

**5.3x the log coverage in half the disk** — the on-change write policy (Lever C) doing what
the 3.5x measurement predicted. Series cardinality landed at 19,958, well under the ~34,600
projection and far under the ~103k the earlier per-capture estimate feared, because
`detect_capture_sessions()` groups more sensibly than a filename-prefix count. Nowhere near
the `inmem` index's ~1M comfort limit.

Host stayed healthy throughout: InfluxDB heap peaked ~548 MB (from 246 MB idle),
`/proc/pressure/memory` held at **0.00** across all windows, `available` never dropped below
6 GB. No throttling needed.

**A blocking defect was caught one minute in and fixed before it reached the data.** The
first Coda file logged `ch2 -> SKIP transient (140134 frames, 100 unique IDs)` — churn
channels have a handful of frames, not 140k. `identify_buses()` had two independent bugs that
cancel out on most files:

- **First-match-wins mislabelled overlapping anchor sets.** `chargepointcharge.log`'s real
  b_can channel also carries ID `0x000`, inside c_can's `0x000-0x019` cell-voltage range, and
  c_can is listed first — so real b_can traffic would have uploaded tagged `c_can`.
- **The blanket 5%-of-busiest filter discarded a real bus.** That file's genuine c_can channel
  is 3.5% of b_can's frame count (cell voltages are bursty, b_can continuous) and was dropped
  entirely.

Fixed by scoring on **fraction of each anchor set present** (b_can 4/5 = 0.80 beats
c_can 1/26 = 0.04; fraction not raw count, since sets range from 1 to 26 ids), and applying
the churn filter **only between channels claiming the same bus name** — competing for the same
*name* is the churn signal, relative volume is not. Verified against both conflicting cases:
Coda keeps `{c_can, b_can}`, and `vtrux_20260503_171127_T0` still drops all 9 duplicate
channels while keeping `powertrain` and `obd`.

Drop decisions are now self-explaining in the log, so `backfill.log` is the audit record:
```
ch12 -> SKIP duplicate of obd (7029 frames, 59 unique IDs, 60% anchor match)
ch20 -> obd  (85596 frames, 60 unique IDs)
```

*Gate — PASSED.* `manifest_l1_agreement.py` on three sessions spanning both vehicles and the
churn case:

| Session | manifest vs L1 | hash drift |
|---|---|---|
| `vtruxinterlocktest2` | 22,325 = 22,325 | 0 |
| `coda_20260505_192535` | 1,151,891 = 1,151,891 | 0 |
| `vtrux_20260503_171127` | 1,106,040 vs 1,106,039 (**+1**) | 0 |

`vtruxinterlocktest2`'s 22,325 independently reproduces the Phase 1 equivalence test's
on-change value count for the same log. The +1 was traced, not waved off: 5 duplicate
`(series, timestamp)` collisions across that session's 13 chunks (`obd 0x044` and `0x0C1`),
the known BUSMASTER 0.1 ms tick-resolution issue documented in Phase 1. InfluxDB overwrites on
identical (series, field, timestamp), so the manifest counts what was *written* and L1 counts
what *survived*. Pre-existing, policy-independent, ~0.0000003% of values.

**8 of 516 sessions produced no data, correctly:** `coda_bms_flash`, `coda_dlcm_flash5`
(+2 copies), `coda_gateway_flash`, `coda_rcu_keyfob_pairing`, `coda_srs_dtc_clear`,
`coda_srs_dtc_read` — UDS/flash captures carrying only `0x7xx` diagnostic traffic, which no
DBC defines. 15 channels across ~8 files fell back to a `ch<N>` bus tag; those are the same
diagnostic captures plus two cable tests.

**Phase 5 — schedule.** Cron on `the Linux box` (holds the full Seafile copy). Add a
capacity/cardinality warning threshold.

---

## File Layout

```
tools/
    influx_upload.py            # modified: --only-id, manifest, int timestamps, no influxdb dep
    influx_sync.py              # NEW: diff engine + planner + applier
    plans/
        influx-sync.md          # THIS PLAN
    artifacts/                  # investigation scratchpads, 2026-08-09
        influx_dbc_diff_prototype.py    # L1 diff proof -- promote into influx_sync.py
        influx_storage_audit.py         # per-session value/orphan/legacy audit
        influx_storage_audit.json       # its output
        upload_volume_strategy.py       # Lever C measurement
        ts_encoding_experiment.py       # Lever B/C disk experiment; --report/--cleanup modes
        ts_encoding_experiment.json     # its shard map + value counts
        on_change_equivalence.py        # Phase 1 gate 2 -- KEEP, re-run on any writer change
```

---

## Decisions (settled 2026-08-09)

1. **Write policy — on-change + 1 s heartbeat.** Measured 20.8% of current value volume.
   Heartbeat bounds gaps to 1 s so Grafana panels at >=1 s intervals behave as today.
2. **Timestamp resolution — 0.1 ms**, the native BUSMASTER tick. Lossless; TSM factors a
   common divisor out of deltas, so it compresses as well as 1 ms would.
3. **Session tagging — per capture, applied uniformly.** Session is not used as a filter in
   Grafana, so grain is free there. With the wipe there is no need to preserve the existing
   106 tag values, so one convention applies everywhere instead of two side by side.
   Granularity is **per capture** (the shared `YYYYMMDD_HHMMSS` prefix across `_T` chunks),
   not per file. Measured cost:

   | Grain | Sessions | Projected `signals` series |
   |---|---|---|
   | current `derive_session()` | 313 | ~20,900 |
   | **per capture (chosen)** | **1,542** | **~103,000** |
   | per file | 3,156 | ~211,000 |

   Note: `session` is a **tag**, not a field — it is what carries this cardinality cost.
   Per-capture is the real recording unit and keeps series ~2x below per-file.
   **Index type resolved 2026-08-09: `inmem`** (read from the `shard` stat tags in
   `/debug/vars` — no admin needed, `SHOW SHARDS` is not the only route). Assessment:

   | | |
   |---|---|
   | Index type | `inmem` (legacy in-memory), engine `tsm1` |
   | Series now, instance-wide | 8,216 (`canbus-data` 7,080 + `homeassistant` 774 + `_internal` 362) |
   | InfluxDB heap | Alloc 239 MB, HeapInUse 246 MB |
   | Projected after backfill | ~103,000 series = ~12.5x current |

   `inmem` holds all series keys in RAM, but InfluxData's own guidance puts the
   `inmem` -> `tsi1` switch around ~1M series per database. ~103k is an order of magnitude
   inside the comfortable range, and `max-series-per-database` defaults to 1,000,000.
   **No index change needed.**

   Host caveat: 15.8 GB RAM, 12.2 GB used, and **swap is 100% consumed** (5,212 / 5,213 MB).
   However `/proc/pressure/memory` reads `0.00` at avg10/avg60/avg300, so the swapped pages
   are cold and there is no active pressure. There is no swap headroom left for a spike.
   The transient risk during the Phase 5 backfill is the **write path** (TSM cache, WAL,
   compaction), not the index. Watch InfluxDB RSS during backfill and throttle
   `--batch-size` if it climbs.
4. **Android backup root — included** in routine auto-upload. 51 GB of the 101 GB corpus
   and almost entirely unuploaded (1 of 1869 Vtrux files).
5. **Log identity — size + mtime**, SHA-1 only on mismatch. Hashing 101 GB per run is
   pointless I/O; a Seafile-perturbed mtime costs one hash, never a bad upload.
6. **`raw` measurement — stays off.** Currently unused; corpus-wide it would dwarf `signals`.
7. **Orphans — report only.** `--plan` reports; deleting requires an explicit flag. Deletion
   is the only irreversible action in the tool and must not be automatic.

---

## Scope: which trucks go in

`vehicle=vtrux` currently mixes **three physically different trucks** — main, parts, and a
fellow owner's. All are Vtruxes, so the DBC and bus anchors are correct for all of them, but
the data is not interchangeable.

**Truck 3's truck is excluded** (owner instruction, 2026-08-09). Additional reason: truck3-is a
third party subject to the privacy scrub table in `git-publish.md`, so his name must never
reach a session tag.

Enforcement is structural: his logs live in `projects/vtrux/logs/truck3-logs/`, and
`influx_upload.py` expands folders **non-recursively**, so a subfolder is never picked up.
Five files were moved there on 2026-08-09 (`truck3-canlog.log`, `keithlog2.log`,
`truck3-truck-3.log`, `truck3-truck4-keyoff-on-off-on.log`, `truck3-6_key_and_export.txt`),
joining the two `candump-2026-08-05_*.log` files already present. All 16 referencing files
were updated; `git-publish.md` was deliberately left alone (its entries are name patterns,
not paths). None of these were ever uploaded — no InfluxDB cleanup needed.

`influx_sync.py` must additionally enforce this as an explicit **exclude-path list**, not
rely on non-recursion alone, so that an explicit file argument cannot bypass it.

Also excluded: `projects/vtrux/logs/truck1log_M0..M3_T0.log` — documented as empty, 590 bytes
(header only). Generalise to a **minimum-frame-count filter** rather than a name rule.

**Parts truck: left as-is** (owner decision, 2026-08-09). Its `vtrux_partstruck_*` sessions
stay under `vehicle=vtrux` alongside the main truck, with no `truck` tag.

This is safe **only because the two trucks have never been logged at the same time.** Their
captures are disjoint in time, so any Grafana time range resolves to exactly one truck and
no panel can average two vehicles together. This is a property of the capture history, not
of the schema — the schema cannot express the distinction at all.

**Tripwire:** the first simultaneous capture of both trucks breaks this. Two trucks' frames
would land in the same `(vehicle, bus, can_id, session)` series and become permanently
indistinguishable. Before any such capture, add a `truck` tag (or split the `vehicle` value)
and backfill it. Note also that the **session tag name is currently the only truck
discriminator** for existing data — `vtrux_partstruck_*` by convention — so that naming
convention must be preserved for any retroactive tagging to be possible.
