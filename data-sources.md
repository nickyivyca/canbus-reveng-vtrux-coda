# Data Sources

Where the project's data lives, what each source is authoritative for, and how to pull from
it. Read the relevant section **before** pulling data, not after.

The operative invariants are in `AGENTS.md` under **Data Sources** and are always loaded.
This file is the detail behind them.

| Source | Authoritative for | Section |
|---|---|---|
| CAN log files | raw frames, timing, undecoded bytes, IDs no DBC defines | [1](#1-can-log-files) |
| DBC files | signal encoding — scale, offset, bit layout, endianness | [2](#2-dbc-files) |
| InfluxDB | the whole corpus decoded against the DBCs, for querying | [3](#3-influxdb) |

---

## 1. CAN Log Files

### Format

Primary format is **BUSMASTER**; the framework auto-detects SavvyCAN, candump and PEAK TRC
as well. The user never specifies a format — `canre.parsers.detect_format()` handles it.

**Timestamp fields use two different units, which look identical.** Data lines are
`HH:MM:SS:TTTT` where `TTTT` is **10 kHz ticks (0.1 ms)**. The
`***START DATE AND TIME***` header's trailing field is **milliseconds**. Measured across
1,062 headers the header value never exceeds 998, while data-line values reach 9999. Reading
either as the other is a silent 10x error.

`parse_file()` re-bases every file so its **first data frame is `t=0`**. The raw time base
never reaches `frame.timestamp`, so absolute placement comes from the anchor — see
`canre/utils/timebase.py`, which resolves the true instant of the first frame per capture
session. Two loggers behave differently: the Android logger resets timestamps every chunk,
laptop BUSMASTER captures write wall-clock time of day and some chunk headers state the
wrong time.

### Naming

Captures use `_M{N}_T{chunk}`:

- **`M` numbers are separate capture sessions, NOT different CAN buses of one session.**
  Do not assume `M0` and `M1` are simultaneous multi-bus captures — they are independent.
- `T` is a time-ordered chunk within a session, though **T order is not always time order**;
  use `detect_capture_sessions()` rather than sorting by name.
- The `vtrux_YYYYMMDD_HHMMSS_T{n}` form comes from the Android logger app.

### Bus channel numbers are arbitrary

The channel number assigned to each physical CAN bus varies across sessions with dongle
insertion order. **Never use a bus number to identify a bus.** Identify by message content,
using the anchor IDs in the vehicle overview (`vtrux.md`, `coda.md`) — the same sets
`influx_upload.VEHICLE_PROFILES` uses.

Android T0 chunks additionally exhibit **bus-number churn**: one physical bus is re-numbered
across many transient channels during USB enumeration. `vtrux_20260503_171127_T0` shows 11
channels where there are really 2 buses. `identify_buses()` resolves this by scoring each
channel on the *fraction* of an anchor set present, then keeping only the highest-frame-count
claimant of each bus name. Do not reimplement this by hand.

### Locations — two roots

1. **Primary:** `./projects/<vehicle>/logs/` — logs placed here deliberately as part of
   analysis work, or captured with the Python tools and a USB dongle.
2. **Secondary:** `../../CANLogs/<vehicle>Logs/` — Android auto-backup. SeaDrive's Android
   backup can only sync to a top-level library, not to a subfolder of this project, so these
   land in a sibling `CANLogs/` library next to `NotGit/`.

Check the primary location first unless the user says otherwise. If a backup log turns out to
be significant (a specific fault or test), **ask the user** whether to move it to the primary
folder with a descriptive name.

### Subfolders are out of scope by default

`projects/<vehicle>/logs/` subfolders hold specialised captures and are **not** swept up by
`influx_sync.py` — discovery is non-recursive, and a subfolder must be named in
`OPT_IN_SUBFOLDERS` to come into scope. As of 2026-08-10 that is 295 files / 16.0 GB across
`other-logs`, `after-battery-swap-charges`, `actual-failed-charges`, `big-logs`,
`coda/logs/data`, and `truck3-logs`.

`truck3-logs/` is additionally on a hard deny-list. It is a fellow owner's truck — a
different physical vehicle from the main and parts trucks — and he is a third party covered
by the privacy scrub in `git-publish.md`, so his name must never reach a session tag.

---

## 2. DBC Files

### Source-of-truth hierarchy

For any signal property (scale, offset, byte position, endianness, units, range) — especially
when writing plotters, correlation sweeps, or analysis code:

1. **DBC file** (`projects/<vehicle>/*.dbc`) — highest authority. Use its scale, offset and
   byte layout exactly as defined.
2. **Vehicle overview** (`projects/<vehicle>/<Vehicle>.md`) — second. Confirmed findings
   promoted here supersede lower-level notes.
3. **Notes files** (`projects/<vehicle>/notes/*.md`) — working notes, provisional until
   promoted.

**Conflict rule:** if the DBC and a notes file disagree on scaling or encoding for the same
signal, **do not guess — stop and prompt the user** before writing any code that uses the
value. State what the DBC says, what the notes say, and which signal/byte is in conflict.

### Use cantools, never hand-rolled extraction

Parse with `cantools.db.load_file(dbc_path)`; read `signal.scale`, `signal.offset`,
`signal.length`, `signal.byte_order`, `signal.is_signed`. Do not hand-parse DBC text.

Decode with `db.decode_message(arb_id, data)`. Only hand-roll extraction for signals with no
DBC entry. Hand-rolled Motorola/nibble-split decoders are a recurring source of silent bugs
(wrong bit progression, off-by-one byte indexing) that yield plausible-looking garbage.

### Only confirmed signals belong in a DBC

A signal is confirmed when its role and encoding have been validated against ground truth —
physical measurement, correlation with a known reference, or a deliberate
disconnect/interlock test. Hypotheses, rejected candidates and unconfirmed roles do not
belong as `SG_` entries. `BO_` stubs and `CM_` comments are always allowed at any confidence.

| Confidence | Allowed |
|---|---|
| Confirmed role + confirmed scale | full `SG_` entry |
| Confirmed role + unconfirmed scale | `SG_` entry, but `CM_ SG_` must state the scale is unconfirmed |
| Confirmed message name, no bit mapping | `BO_` stub only |
| Unconfirmed role (hypothesis, rejected, medium-confidence) | `BO_` stub only |

The message name is the searchable keyword linking a DBC entry to the vehicle notes.
Confirmation evidence (methodology, test conditions, correlated reference) belongs in the
notes, not in the DBC comment.

> **Outstanding task:** reformat vehicle notes to use tables keyed by message name, so every
> `BO_` entry has a searchable row, and clean up DBC descriptions.

### A DBC edit invalidates uploaded data

Changing a message's signal encoding makes InfluxDB stale for that message. `influx_sync.py`
detects this via per-message definition hashes (`canre/dbc/msghash.py`) and repairs just that
message. Editing a `CM_` comment, value table or message *name* deliberately does **not**
trigger a re-upload — only decode-relevant properties are hashed.

---

## 3. InfluxDB

Holds the entire in-scope corpus decoded against the current DBCs. For any question
answerable purely from DBC-encoded signals, **query this instead of re-parsing logs** — a
question that would mean reading gigabytes becomes one query.

### Connection

| Setting | Value |
|---|---|
| Host | `localhost:8086` (LAN only) |
| Database | `canbus-data` |
| User / password | `claude` / `claude` (read + write; **not** admin) |
| Retention | `autogen`, infinite, 7-day shards |

Grafana reads this database. The `homeassistant` database on the same server holds solar,
power and temperature history — useful for cross-referencing vehicle behaviour against house
data, which is why absolute timestamp accuracy matters.

```bash
curl -s -G "http://localhost:8086/query" -u claude:claude \
  --data-urlencode "db=canbus-data" \
  --data-urlencode "q=SELECT ... FROM signals WHERE vehicle='vtrux' AND session='...'"
```

`/debug/vars` gives per-database disk usage, series counts and heap without admin rights —
better than InfluxQL for anything operational.

### Schema

| Measurement | Tags | Fields |
|---|---|---|
| `signals` | `vehicle`, `bus`, `can_id`, `session` | one field per signal name (float) |
| `upload_manifest` | `vehicle`, `session`, `file` | sync bookkeeping — see `tools/tools.md` |

**Signal names are fields, not tags.** Query one signal with `SELECT "Signal_Name"`, never
`WHERE signal='...'`. This keeps cardinality bounded and lets a query scan a single series
per CAN ID. (A legacy `signal`-tag schema existed before 2026-08-10 and is gone.)

Bus tag values: `powertrain` / `vehicle` / `obd` for Vtrux, `b_can` / `c_can` / `d_can` for
Coda; `ch<N>` where no anchor matched (diagnostic and flash captures). Session tags are
per capture, from `detect_capture_sessions()`.

**Beware unscoped aggregates.** `SELECT COUNT(*) FROM signals GROUP BY session` scans the
whole database and will reset the connection. Always scope by `vehicle` and `session`.

### Write policy — what is *not* preserved

Points are written **on change, plus a heartbeat at most every 1 s** — a signal is stored
when its value differs from the last stored value, not every frame. Measured 3.5x less disk
than every-frame.

- **Values are exact.** Forward-filling (`fill(previous)`, `LAST()`) reproduces the
  every-frame series identically at every original timestamp. Verified on three logs.
- **Frame counts and inter-frame timing are NOT preserved.** Never infer message rate, duty
  cycle, or bus load from point counts. Use the raw logs for anything rate-dependent.
- Gaps longer than 1 s mean the *message* is slower than 1 s — a heartbeat cannot fire
  without a frame.

### Keeping it fresh

If new logs have been captured or a DBC edited since the last upload, run the planner first —
it takes about a second:

```bash
py tools/influx_sync.py --plan          # what is missing or drifted
py tools/influx_sync.py --apply         # upload only that
```

Do **not** upload by hand with `influx_upload.py` for routine work; the sync tool handles
session naming, exclusions, the empty-file filter and manifest bookkeeping. Use
`influx_upload.py` directly only for one-off or out-of-scope files.

`--check-existing` adds the data-derived audit (orphan series, legacy schema) but costs one
full-session scan per session — minutes, not seconds.

### What is not in there

- Frames no DBC defines (unless uploaded with `--raw`, which is off by default)
- UDS/flash/diagnostic captures — only `0x7xx` request/response traffic, nothing to decode
- Opt-in subfolders and Truck 3's truck (see §1)

### Current state (2026-08-10)

508 sessions · 19,958 series · 349,670,636 values · 188,233,471 points · 1.316 GB on disk,
from 1,876 files / 85.67 GB of logs.

---

## Related docs

| Doc | Covers |
|---|---|
| `tools/tools.md` | `influx_sync.py`, `influx_upload.py`, all CLI tools |
| `tools/plans/influx-sync.md` | why the upload pipeline works the way it does; measurements behind every decision |
| `canre/parsers/parsers.md` | parser API, format detection |
| `canre/utils/utils.md` | session grouping, log merging, time-base resolution |
| `canre/dbc/dbc.md` | DBC builder, validator, message hashing |
| `projects/<vehicle>/<vehicle>.md` | per-vehicle bus anchors, topology, DBC status |
