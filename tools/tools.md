# Tools Reference

> **Staleness check:** Each section shows a `Source last modified` timestamp in `YYYY-MM-DD HH:MM:SS` format (file mtime). If the `.py` file's mtime is newer than the timestamp shown here, re-read the source before relying on this documentation. When updating a timestamp, always include the full date and time — not just the date.

## CANFrame field names (common mistake)

When writing scripts or scratchpads that touch `CANFrame` objects:

- **`frame.arbitration_id`** — correct. `arb_id` is only a local variable name used inside parsers before being passed as the constructor kwarg `arbitration_id=`; it is not a `CANFrame` attribute.
- **`frame.bus`** — correct. `channel` is a `python-can` concept (hardware channel spec for `can.interface.Bus(channel=...)`); the `CANFrame` dataclass field is `bus`. Never use `frame.channel`.

---

**Vehicle-specific tools** are kept alongside their vehicle's project files, not here:
- Coda: `projects/coda/tools/` — see `projects/coda/tools/README.md`
- Vtrux: `projects/vtrux/tools/` — see `projects/vtrux/tools/README.md`

**Cross-tool investigations and benchmarks** live in `tools/notes/` — see `tools/notes/README.md`.

**Error-report sweep:** `tools/error-report-sweep/` validates canbench's inferred-error rules (pre-fix Innomaker reports, desktop BUSMASTER Kvaser id-`0x000` status frames) against the whole corpus. See the section below and its `README.md`.

---

## distill_dbcs.py
*Source last modified: 2026-11-03 20:51:57*
*Consumed by: the Vtrux live display, `live-display/dbcs/{powertrain,obd}.dbc` in the `:vtrux` app and the Vtrux `:companion` flavour (Android repo `android-canbus-apps`)*

Builds one small DBC per named bus for the live display, holding only the
messages the display subscribes to, pulled from several source DBCs (SPEC at
the top of the file). The generator inhibitor's status page `0x7F1` comes from
its decode DBC in the firmware repo, at the commit pinned in the Android repo's
`notes/protocols/gen-inhibit-status-interface.md`; the tool stops if it is not
given, so `0x7F1` is never dropped silently.

```
git -C <esp-fw clone> show <commit>:gen-inhibit/diag/vtrux-wican-diag.dbc > <tmp>/wican.dbc
py -3.12 tools/distill_dbcs.py --wican-diag-dbc <tmp>/wican.dbc --out <tmp>/dbcs
```

**Optional flags:** `--out DIR` (write there instead of the app assets),
`--without SUBSTR` (skip matching sources: `GMW8762` for GMLAN-free assets,
`wican` to leave out `0x7F1` on purpose).

**The app assets have drifted from this tool** (since 2026-09: `0x460`, added
by hand for the fault display, is not in SPEC, and some comments differ). Do
not let it overwrite them: generate with `--out` and carry over the change.
Its default output folders are the two asset folders in the `android-canbus-apps`
clone, found through `canre.utils.android_repo` (`$ANDROID_APPS_REPO`, default
`~/Git/android-canbus-apps`). It writes LF on every machine.

---

## dbc_parity_generate.py
*Source last modified: 2026-11-03 20:42:41*
*Consumed by: `CanLoggerApps/cancore/src/test/java/com/reverseit/cancore/DbcParityTest.kt` in the `android-canbus-apps` clone*

Generates parity test cases for the Kotlin DBC decoder by running each
Vtrux DBC through cantools and dumping the (payload -> decoded signals)
mapping to a TSV the Kotlin test loads from its classpath. For each
non-multiplexed message, generates N random payloads. For multiplexed
messages, generates N payloads per mux value (with the multiplexer bits
forced to each value in turn). Copies the source DBC files into
`cancore/src/test/resources/dbcs/` so the test has self-contained fixtures.
The default output is the `android-canbus-apps` clone's `:cancore` test
resources (`canre.utils.android_repo`); `--output-dir` overrides it. The TSV is
written LF on every machine.

**Requires:** `pip install cantools` (already a project dep).

**Usage (default: all four Vtrux DBCs, 30 cases each):**
```
py -3.12 tools/dbc_parity_generate.py
```

**Optional flags:**
```
  --dbc PATH        DBC file (repeatable; default: Vtrux set)
  --output-dir DIR  cancore test resources root (default: the cancore module)
  --cases N         Random payloads per message / per mux value (default: 30)
  --seed N          PRNG seed for reproducibility (default: 42)
```

**Output format** (TSV at `cancore/src/test/resources/dbc_parity_cases.tsv`):
```
dbc_basename<TAB>message_id_decimal<TAB>payload_hex<TAB>sig=val;sig=val;...
```
String-valued signals (from DBC value tables) are emitted as quoted strings
and skipped by the Kotlin test (the protocol emits raw scalars per §11/§13;
enum mapping is client-side).

Regenerate any time a Vtrux DBC changes, then run `:cancore:testDebugUnitTest`
to validate parity.

**That instruction has been silently skipped twice, and the failure mode is that
the test still passes.** The fixtures under `cancore/src/test/resources/dbcs/` are
*copies*. Nothing links them back to `projects/vtrux/`, nothing fails when they
drift, and `DbcParityTest` goes on proving that the Kotlin decoder agrees with
cantools — about a definition the project has since withdrawn. Checked 2026-09-25,
the copies predated **both** the 2026-05-12 `0x04C1` byte-layout correction (EPRI
decompile off-by-two: `puVar20[4]` is CAN B2, not B4) and the 2026-08-02 `BO_ 1432`
offset-binary fix. So for months the test validated the decoder against two
definitions already recorded as vendor bugs. Nothing broke downstream only because
the app's live-display assets carry their own separate, correct copies.

To detect the drift without running anything Android:

```bash
for f in epri-pt-bus epri-obd-bus BelInverter-v2 GMW8762_PPEI_GMLAN; do
  cmp -s "projects/vtrux/$f.dbc" \
         "android-app/CanLoggerApps/cancore/src/test/resources/dbcs/$f.dbc" \
    || echo "STALE: $f"
done
```

Silence means the fixtures are current. Do this before trusting a green
`DbcParityTest`, and after any DBC edit.

**Reviewing the regenerated TSV is not a useful check** — the PRNG is seeded and
draws in DBC order, so adding or removing one signal reshuffles every later
message's payloads and the diff is almost total regardless of how small the real
change was. Check instead that the four copies are byte-identical, that the set of
distinct signal names in the TSV changed only as intended, and that the test passes.

---

## slcan_parity_generate.py
*Source last modified: 2026-11-03 20:42:58*
*Consumed by: `CanLoggerApps/cancore/src/test/java/com/reverseit/cancore/SlcanParityTest.kt` in the `android-canbus-apps` clone*

Generates parity expectations for the Kotlin `SlcanReader`, which reads the
LAWICEL/SLCAN ASCII stream the 914 VCU emits over USB CDC serial. Holds a
reference reader in Python; runs it over the 914 capture fixtures, copies those
fixtures (gzipped, whole) into `cancore/src/test/resources/slcan/`, and writes a
TSV of expected counters, a frame digest, and sampled frames.

**Fixtures** come from the 914 notes hub, a sibling workspace
(`../914/notes/artifacts` by default — both live under the same SeaDrive root,
so the relative path holds across machines):

| Fixture | Role |
|---------|------|
| `serial-full-slcan.log.gz` | The one capture with no link damage. Its 1381 checked blocks are an **independent oracle** — the CRCs were computed by the firmware over the bytes it wrote, so a wrong tokenizer cannot make them verify. Declared clean; zero block failures enforced |
| `serial-dualemit-verify.log.gz` | Carries two real corruption events (one Mode 1 byte insertion, one Mode 2 whole-frame loss). The reader must *detect* them, so its counters are asserted exactly |
| `serial-slcan-realistic.log.gz` | 226k frames, begins mid-frame, five corruption events. **Integrity frames are BIG-endian** — it predates the firmware's switch to little-endian, so its block counters say nothing about link health and are recorded for parity only |

**Requires:** stdlib only.

**Usage:**
```
py -3.12 tools/slcan_parity_generate.py
```

**Optional flags:**
```
  --fixture-dir DIR  where the captures live (default: ../914/notes/artifacts)
  --output-dir DIR   cancore test resources root (default: the android-canbus-apps
                     clone's, via canre.utils.android_repo)
  --fixtures ...     override the fixture list
  --samples N        frames sampled from each end (default: 20)
```

**Output format** (TSV at `cancore/src/test/resources/slcan_parity_cases.tsv`):
```
fixture_basename<TAB>key<TAB>value
```
Keys are the counter names, `digest` (FNV-1a 64 over every delivered frame in
order), `expectClean`, and `sample.<index>`.

The generator refuses to write expectations if a fixture declared clean has any
block failure — that means either the reference reader is wrong or the capture
is not what it claims, and neither belongs in a test.

Regenerate after changing either reader, then run `:cancore:testDebugUnitTest`.

---

## slcan_bridge.py
*Source last modified: 2026-09-26*
*Consumed by: the `:p914` Android app (A4b); the `:coda` emulator harness (`--busmaster`); regression tests*

Serves SLCAN over TCP: a 914 VCU stream from a capture file or a live serial port, or (since
2026-09-26) a BUSMASTER log as one stream per bus for the Coda emulator harness. Lets a phone
receive the stream without USB host mode being solved first:

```
py -3.12 tools/slcan_bridge.py --file <capture.log.gz> --loop
adb reverse tcp:9000 tcp:9000        # phone's localhost:9000 now reaches this server
```

Serial mode (`--serial COM3`) is **read-only** — nothing is ever written to the VCU.

**Replay is paced by default** to 6705 B/s in 1024-byte bursts, which is the byte rate and
delivery granularity measured on the car (verification A2, 2026-08-13). Unpaced replay exercises
the parser but misrepresents the consumer: on the real link frames arrive in bursts roughly every
212 ms rather than smoothly, so a display fed an unpaced stream looks better than it will in the
car. `--rate 0` disables pacing.

**Flags:**
```
  --file PATH / --serial PORT   source (mutually exclusive, one required)
  --port N                      TCP listen port (default 9000)
  --rate N                      bytes/sec for file replay; 0 = unpaced (default 6705)
  --chunk N                     bytes per burst (default 1024, the CDC flush size)
  --loop                        replay repeatedly
  --selftest                    serve to loopback, verify bytes and pacing, exit
```

### Busmaster mode — the Coda emulator harness

```
py -3.11 tools/slcan_bridge.py --busmaster <T0.log> <T1.log> ... --vehicle coda
adb reverse tcp:9000 tcp:9000 ; adb reverse tcp:9001 tcp:9001
adb shell setprop debug.coda.slcan 9000,9001 ; adb shell am force-stop com.reverseit.coda
```

The chunks are merged onto one timeline (`canre.utils.merge.merge_files`) and every channel is
named by content (`canre.utils.buses.resolve_files` with the vehicle's anchors from
`influx_upload.VEHICLE_PROFILES`), never by channel number. Each bus gets its own port, base
`--port` plus its position in `--buses` (default: names sorted, so `b_can` 9000, `d_can` 9001).
Replay starts once every port has a client, paced by the log's own timestamps. The app side is
`SlcanBusGroup` (`:cancore`), selected in `:coda` only while the `debug.coda.slcan` property is
set, which needs ADB and so cannot happen on the head unit.

It is **two-way**: SLCAN lines the app writes back up a stream -- its transmitted frames -- are
decoded, printed as `TX <bus> 0x<id> ...` and appended to `--tx-log`.

```
  --busmaster LOG [LOG ...]     chunks of one session (mutually exclusive with --file/--serial)
  --vehicle NAME                bus anchor profile (default coda)
  --buses a,b                   bus names in port order; swap them to test bus identification
  --speed F                     replay speed; 0 = unpaced (default 1.0 -- keep 1.0 for anything
                                the app times, since the app stamps frames with its own clock)
  --drop-id HEX                 leave an ID out, repeatable (e.g. 0x600 = RCU removed)
  --tx-log FILE                 record the app's transmitted frames
  --nmea DBC:MSG:SIG[,SIG]      feed the emulator speed-only GPS (RMC, 1 Hz, `adb emu geo nmea`)
  --nmea-scale F                km/h per signal unit; --adb PATH for the adb executable
  --selftest [--dump DIR]       unpaced loopback check, frame for frame per bus; --dump writes each
                                stream and its expected frames for SlcanBridgeParityTest
```

For the Coda the GPS feed is `--nmea "projects/coda/CODA-D-CAN.dbc:ESC_BrakePressure:WheelSpeed_LR,WheelSpeed_RR" --nmea-scale 0.056786`
(the rear pair; `0x200` is avoided because cantools raises on its undeclared startup sub-frames).
**The position in every sentence is a fixed dummy point (0 N, 0 E).** The app reads speed only.

Verified 2026-09-26 on `coda_20260618_195906_T0+T1`: selftest identical on both buses (643,470
B CAN and 790,214 D CAN frames), and `SlcanBridgeParityTest` decodes the dump identically in
Kotlin.

**Use `--loop` for anything that logs.** Without it the server closes the connection after one
pass, the client reconnects, and `CanLoggingService` starts a *new log session* each time — twelve
files in 25 seconds during bring-up.

**A looped replay injects one artificial bad integrity block per loop boundary**, because the file
restarts mid-block and the block spanning the seam comes up short. Expected; do not read it as
link damage.

**Do not use `--rate 0` when logging.** Unpaced replay delivers faster than the frame flow's
collector can drain, and `tryEmit` drops silently (see `android-app/notes/outstanding-changes.md`
Bug 4). Paced replay logs completely.

---

## can_display_server.py
*Source last modified: 2026-05-10 16:09:24*
*Companion files: `can_display_client.py`, `can_display_bus_identity_vtrux.json`, `can_display_server_requirements.txt`*
*Protocol spec: `android-app/notes/protocols/can-display-protocol.md` (v1)*

Reference implementation of the CAN Display Protocol v1. WebSocket server that
replays a recorded CAN log and streams server-decoded signal values to a
display client. Built so the `:display` Android module and other clients can be
developed and validated without phone hardware.

Supports the full Tier 1 aggregation set (`decimate`, `latest`, `min`, `max`,
`mean`) on tumbling windows, anchor-ID-based bus identification, bearer-token
auth, and protocol takeover semantics (a new authenticated client supersedes
any existing session per protocol §10).

**Requires:** `pip install -r tools/can_display_server_requirements.txt`
(`websockets >= 12.0`, `cantools`).

**Usage:**
```
py -3.12 tools/can_display_server.py [options]

  --log PATH              CAN log to replay (BUSMASTER, candump, SavvyCAN, TRC,
                          Vector ASC; auto-detected) [required]
  --bus-identity PATH     JSON file mapping named buses to anchor-ID lists
                          (see can_display_bus_identity_vtrux.json) [required]
  --dbc PATH              Optional. Overrides the DBC sent by the client in its
                          `config` message; useful for testing without a real
                          client. By default the client's DBC is used.
  --port N                WebSocket listen port (default: 9878 -- distinct from
                          LogFileServer's 9877)
  --token T               Bearer token. Random 16-hex generated and printed at
                          startup if omitted.
  --speed F               Replay speed multiplier (default 1.0; 0 = no delay)
  --loop                  Loop the log when it ends
  --verbose               Log every wire message
  --dump-subscription-summary
                          On client config, log a human-readable subscription
                          summary
```

**Bus identity JSON format:**
```json
[
  {"name": "powertrain", "anchor_ids": ["0x051", "0x592-0x5A2"]},
  {"name": "vehicle",    "anchor_ids": ["0x1E5", "0x500"]},
  {"name": "obd",        "anchor_ids": ["0x040-0x044"]}
]
```
- `anchor_ids` accepts decimal ints, hex-prefixed strings, and `lo-hi` ranges.
- The shipped `can_display_bus_identity_vtrux.json` covers Vtrux PT/Vehicle/OBD
  buses as documented in `projects/vtrux/README.md`.

**Bus identification:** the server pre-scans the first 2 s of the log,
counting anchor-ID matches per channel, and assigns each named bus to the
channel with the highest count above a threshold (3 anchors, or all anchors if
fewer than 3 are configured). Identified buses receive a `bus_identified`
status; unidentified buses with subscriptions receive `bus_silent`.

**Decode:** uses `cantools.database.decode_message()` against the DBC supplied
by the client (or `--dbc` override). Multiplexed messages (protocol §8.5) are
supported: cantools transparently decodes the multiplexer signal first, then
returns only the signals from the matching mux group. Signals from inactive
mux groups are absent on a per-frame basis; the aggregator updates only on
frames where the signal is present (sparse-update semantics). Value-table
(enum) signals decode to their underlying scalar; clients map to strings if
needed.

**Aggregation:** tumbling windows of `1/rate_hz` seconds, per protocol §7.
`decimate` emits every Nth frame where N = round(observed_bus_rate / rate_hz).

**Companion smoke-test client (`can_display_client.py`):** loads a DBC and a
JSON manifest, connects, sends `config`, prints incoming frames. Useful for
end-to-end verification without the Android client.

```
py -3.12 tools/can_display_client.py \
    --url ws://localhost:9878/stream \
    --token <token printed by server> \
    --dbc projects/vtrux/epri-pt-bus.dbc \
    --manifest tools/artifacts/smoke_manifest.json
```

The manifest file contains a single `subscriptions` array matching the
protocol's `config.subscriptions` schema.

**Aggregation primitives unit-test:**
`tools/artifacts/test_can_display_aggregation.py` validates the running
sum/min/max/mean primitives against known sequences. Run with `py -3.12`.

**Unidentified-channel census:**
`tools/artifacts/unidentified_channel_census.py` reports every channel that
`identify_buses` cannot attribute, per vehicle, with frame counts and the share
of its file's traffic. Read-only. Run it before changing anything about anchor
sets or the unattributable-channel rule — a change that only ever removes data
deserves a number attached to it, and this is the number.

**Bus-label drift unit-test:**
`tools/artifacts/test_label_drift.py` covers `influx_sync.label_drift_work` --
the overlap guard (a windowed delete must not be authorised when another chunk
of the session shares the window), convergence (a repaired drift must stop being
reported), and the quiet cases. `stale_points_in_window` is stubbed, so it needs
no database. Run with `python3.13`; all six cases must pass.

---

## influx_sync.py
*Source last modified: 2026-10-30*
*Plan: the internal `influx-sync` plan*

**Changed 2026-10-30 -- two bench-replay copies excluded.** `projects/vtrux/logs/vtrux_20260322_165622_T1.log` and `vtrux_20260403_194203_T2.log` are :vtrux app recordings of desktop replays of `generator-on-then-off.log`, not drives. The rest of both evenings is quarantined in `android-app/notes/artifacts/vtrux_bench_replay_captures/`. These two stay until the gen-inhibit suite stops naming them. Their sessions were deleted from InfluxDB the same day (`tools/artifacts/delete_replay_sessions.py`), so without the exclusion the next `--apply` would upload them again.

**Changed 2026-10-21 — `EXCLUDE_PATHS` takes one file.** The parts-truck Android
sessions were moved to `projects/vtrux/logs/` and renamed `partsdrive_20260801_T*` /
`partsdrive_20260802_T*` (user decision); their old session tags were deleted from
InfluxDB so the renamed files upload once. `vtrux_20260802_123318_T0.log` stays in
`projects/vtrux/logs/` under its capture name because the gen-inhibit firmware replay
suite names it, so it is excluded: it is the same file as `partsdrive_20260802_T0.log`.
`EXCLUDE_PATHS` already matched a file path exactly (`rp == exr`); nothing else changed.

**Changed 2026-10-04 (later) — the two layers disagreed with each other and both
disagreed with the uploader.** Three consumers had their own idea of what the uploader
writes, and each disagreement cost data.

- **L1 condemned every unidentified-channel series as an orphan.** `current_hashes()` is
  built over the *named* buses only, so a `ch<N>` key cannot be in it, and L1's orphan
  test was `(bus, can_id) not in hashes`. Running `--plan --check-existing` on
  2026-10-04 proposed dropping **354 series, of which only 207 were real orphans**: the
  other 147 were `ch<N>` series, 8 of them written minutes earlier by the uploader
  itself, and 70 of them vtrux series holding **161,917 field-values** unrelated to the
  work in hand. L0 had already learned this at its `drift` comparison — the fix there
  normalises the missing hash — and L1 never did.
  L1 now splits the two: a named bus with no definition is `drop_series` as before, and
  `ch<N>` becomes **`review_unidentified_bus`**, which `--apply` prints and does not
  execute. The data is real; what is missing is a bus label, which dropping the series
  does not supply.
- **New `drop_label_window`: series stranded when a file's BUS LABEL changes.** This is
  the one staleness the three sync keys are structurally blind to — file sha1, DBC message
  hashes and the policy hash are functions of the bytes and the encoding, and a bus label
  is a function of neither. Re-uploading writes the frames under the new tag and leaves
  the old tag's points in place, so the same frames are live under two bus names and every
  later `--plan` reports the file as current. The manifest already records the `bus_map`
  that produced each row, so the check costs one extra query and no parsing. It found
  exactly the three tails the `min_anchor_hits` guard had relabelled, with no false
  positives over 2,547 manifest rows:

  | file | label change | stranded |
  |---|---|---|
  | `coda_20260608_095955_T6` | `c_can` -> `ch1` | 211 field-values |
  | `coda_20260722_102259_T6` | `d_can` -> `ch1` | 141 field-values |
  | `coda_20260807_192700_T6` | `b_can`,`d_can` -> `ch1`,`ch2` | 0 (all ids d_can-excluded) |

  **The window is the dangerous part.** The repair deletes the old tag only inside the
  file's own recorded window, which is sound only while no other chunk of the session
  overlaps it. The first version compared the *drifting* files against each other — and
  with one drifting file per session there is nothing to compare against, so the test
  passed vacuously and would have authorised a delete straight over a non-drifting chunk
  sharing the window. It now tests against every file in the session, and an overlap
  downgrades the item to **`report_label_drift`**, which is not executed. Unit-tested
  both ways, because a guard that cannot fire is not a guard.


**Changed 2026-09-12 -- new-message backfill, and a plan summary that can be trusted:**

- **`--backfill-id ID [ID ...]`.** Drift detection compares the per-message hashes a
  file recorded *at upload time*, so a message added to a DBC after the upload is
  never examined and `--plan` reports nothing to do. `0x18EFC000`
  (`VCU_ChargerCmd`) was absent from InfluxDB entirely for this reason. The new
  `backfill_ids` action uploads the named id(s) into sessions that predate the
  definition. It only ADDS points -- it never deletes -- and the id is recorded in
  the manifest afterwards so it is not re-queued.

  Detection stays **explicit**. "Defined in a DBC but never recorded" is not a
  usable discriminator: it also matches every message this vehicle does not send,
  and queued 33,625 false backfills on the first attempt. Automatic discovery would
  need the manifest to record which ids each capture actually contains, which it
  does not.
- **`summarize()` counted file references, not files.** Work items routinely share
  source files, so the byte total multiplied the same file by however many items
  touched it: a redundant plan reported **10.6 TB against a 104 GB corpus**, which
  read as a storage problem rather than "reads the same file 29 times". Both the
  file count and the byte total are now over distinct paths.
- **`OPT_IN_SUBFOLDERS`** gained `big-logs`, `actual-failed-charges` and
  `after-battery-swap-charges`, which had been outside the corpus.

**Changed 2026-08-26 — two bugs that made `reupload_ids` unusable:**

- **Overlapping chunk windows.** A per-id repair deletes the id across each file's
  recorded window before re-writing it, which is only safe while the windows are
  disjoint. **The cause named here was wrong, corrected 2026-09-26:** the Android
  logger does not emit a T0 spanning 24 h — `canre/parsers/busmaster.py` did, by
  testing midnight rollover against the first frame in the file instead of the
  previous one, so a few seconds of out-of-order writes became a whole day. 36 of
  1069 Coda captures were affected, `coda_20260508_191742_T0` among them (6-minute
  header, 24-hour parsed span). Fixed in the parser; see `canre/parsers/parsers.md`.
  The guard below stays as defence in depth. **This was one of three Android
  timestamp defects**, and the only one that produced cross-chunk overlap; the
  other two (a dropped pre-origin block and a backward wall-clock step) are
  written up in `projects/coda/notes/android-log-timestamp-defects.md` and do
  not affect `overlapping_files()`, since both stay inside a single chunk's own
  window. As originally written: the Android
  logger can emit a T0 spanning 24 h with later chunks nested
  inside it (`coda_20260508_191742`: T0 = 24.00 h, T1 = 3.4 min inside it), so
  repairing T0 deleted T1's points as collateral. `overlapping_files()` now detects
  this and routes the affected files to `reupload_file` instead. Comparison is
  strict (`b0 < a1`): consecutive chunks normally *share* a boundary instant, and
  treating that as overlap would send almost every multi-chunk session down the
  whole-file path.
- **`ch<N>` files never converged.** A message on an unidentified channel is stored
  in the manifest with an empty hash, while `current_hashes()` carries only the
  named buses and returns `None` for it. The drift check compared `None != ""` and
  so re-flagged those files on every run, forever, no matter how often they were
  repaired — this was the real cause of the 7 chronically-pending vtrux `ch1`
  sessions and the 3 coda `ch2` fragments, not the manifest bug below. Both sides
  are now normalised before comparing.

> Note: files whose only channel is skipped as unidentified write **0 points**, and
> the manifest is only written when points were written. They therefore stay
> `not_in_manifest` on every plan. The 8 Coda flash/DTC captures are in this state
> permanently and are expected — they are 22-ID UDS traffic that no DBC decodes.

Keeps InfluxDB in agreement with the local logs and the local DBCs, and drives the backfill.
Computes a work list, prints it for review, and executes it. No hand-driven folder uploads.

**Discovery is NON-RECURSIVE.** Roots are scanned one level deep; a subfolder must be named in
`OPT_IN_SUBFOLDERS` to come into scope. `projects/vtrux/logs` alone holds 5 subfolders of
specialised captures (another owner's truck, a single 6.2 GB file, one-off experiment sets) —
295 files / 16.0 GB that recursive discovery would sweep in unasked. `EXCLUDE_PATHS` is a hard
deny-list applied even to explicitly named paths.

**Two diff layers:**

| Layer | Source | Catches | Cost |
|---|---|---|---|
| L0 | `upload_manifest` rows | scale/offset/bit-position changes where the signal name did not change — the **only** layer that can | ~1 s |
| L1 | `SELECT COUNT(*) GROUP BY bus,can_id` | a lying or missing manifest, partial uploads, orphan series, legacy schema | one full-session scan each |

L1 is **opt-in** (`--check-existing`): 212 full-session `COUNT(*)` queries take tens of minutes
against the current database, and the answer is discarded by a wipe-and-rebuild anyway.

L1 alone cannot drive per-file repair — a session's field set is the union across its chunks,
so after repairing 1 of 4 chunks it reports the message as current while three are stale. That
is what the manifest's per-file `msg_hashes` exist for.

**Session tags** come from `detect_capture_sessions()`, which groups by each chunk's real start
time rather than by filename, so `_M{n}` groups that are separate captures stay separate and
one prefix spanning unrelated captures splits.

**Usage:**
```
python3.13 tools/influx_sync.py --plan [--out work.ndjson] [--check-existing]
python3.13 tools/influx_sync.py --apply [--from work.ndjson] [--limit N]
```

**Work-item actions:** `upload_new`, `reupload_file` (encoding/policy/size changed),
`reupload_ids` (per-message repair via recorded window + `--only-id`), `drop_series`,
`rebuild_session`.

**Repair safety:** `reupload_ids` counts the points inside the recorded window *before*
deleting and **aborts** if the count is zero, rather than proceeding. A zero-row delete would
turn the repair into an append — the exact failure the Phase 1.2 slice test hit when a window
was recomputed instead of recorded.

---

## influx_upload.py
*Source last modified: 2026-10-04 17:46:06*

**Changed 2026-10-04 (last) — an unattributable channel is no longer uploaded.**
`identify_buses` step 3 now maps a channel matching no anchor set to `None` instead of to
`ch<N>`, so it is skipped exactly as a churn channel is. `min_frames` and `min_fraction`
went with it — they existed only to decide which *unidentifiable* channels were big enough
to upload anyway, and no caller ever passed either. The churn filter is unaffected; it
compares channels claiming the same bus name and never used them.

The reason is not that such channels are small. `ch<N>` is an admission the bus is unknown,
and the profile `exclude` lists are keyed `(bus_name, can_id)`, so **a bus-scoped exclusion
cannot match `ch<N>`** — an unidentified channel uploaded gateway-rebroadcast copies that
the identical frames would have had excluded under a named bus. The clearest case is five
series on `coda_20260807_192700` under ids `0x275 0x276 0x370 0x383 0x6FA`: all five are
d_can-excluded, so while that channel was labelled `d_can` it correctly wrote nothing, and
it wrote five series the moment it fell to `ch1`.

Cost measured before the change (`tools/artifacts/unidentified_channel_census.py`): 9
channels, 2 Coda (305 frames) and 7 Vtrux (332,082 frames). The Vtrux captures were
quarantined to `projects/vtrux/logs/unidentified-bus/` rather than silently dropped — each
is a disconnect experiment whose bus is unidentifiable *because* the test disconnected the
module emitting the sole `powertrain` anchor.

**This change is invisible to all three staleness keys** — file sha1, DBC message hashes,
policy hash are functions of bytes and encoding, and this is interpretation. Both policy
hashes were verified unchanged (coda `28ffe0f85bdc`, vtrux `0a5448cad23b`). No re-upload is
needed because the change can only *remove* series, so dropping the legacy ones reaches the
same end state — but that drop is the migration, not optional tidying, and it was done by
`projects/coda/notes/artifacts/drop_legacy_ch_series.py` (7 series, 66 values, Coda only).
`is_unidentified_bus` is kept: influx_sync's L1 still needs it to recognise legacy data.

**Changed 2026-10-04 (later) — `ch<N>` has a named producer and recogniser.**
`unidentified_bus_name()` / `is_unidentified_bus()` / `UNIDENTIFIED_BUS_RE` replace an
f-string that three consumers had to guess the shape of; `influx_sync` imports the
predicate rather than re-deriving it. The comment beside them records a third
consequence that is **not** fixed and is a behaviour question, not a defect to patch:
the profile `exclude` lists are keyed `(bus_name, can_id)`, so a bus-scoped exclusion
does not apply to `ch<N>`. A channel demoted to `ch<N>` therefore uploads
gateway-rebroadcast copies that the same frames would have had excluded under a named
bus. Measured: the `coda_20260807_192700` tail wrote nothing while labelled `d_can`
because all five of its ids are d_can-excluded, and five series once it became `ch1`.

**Changed 2026-10-04 — two cross-bus defects, found while verifying an unrelated upload.**
A query scoped to `can_id='0x300'` but **not** to `bus` returned 2,329 ESC-intervention
"armed" points in a session with one real episode. Nothing in that output marked it wrong.

1. **The DBC index has no bus dimension.** `build_id_index()` maps `{frame_id: [db, ...]}`,
   so every loaded DBC is tried against every bus. Coda `c_can` carries its own messages at
   `0x200` and `0x300` — `23 89 83 53 B6 FF AD 13` against `d_can`'s
   `00 80 12 C0 89 18 80 81` — and they were being decoded with the D-CAN DBC and stored
   under D-CAN signal names. Measured over the sessions that carry each id on **both** buses
   at once (so the score cannot be vacuously zero): payload-set overlap **0.000 in both
   directions**, 90–92 sessions per pair. A `c_can 0x200` payload is eight similar small values
   (`15 15 15 16 15 16 16 16`) against the structured D CAN heartbeat it was being
   decoded as; what it actually carries is not established, only that it is not that. Fixed with bus-scoped `exclude` entries, which is the mechanism the
   profile already had; the underlying index is still bus-blind.

2. **A bus label could rest on one stray frame, and nothing could report it.**
   `identify_buses()` warns only when **two** anchor sets match. A channel matching exactly
   one set on exactly one id was indistinguishable from one matching it on all 26 —
   the null-discriminator failure in `AGENTS.md`. `coda_20260608_095955_T6`, a 33 KB tail
   chunk with one channel of 621 B CAN frames, holds no `b_can` anchor (too short for
   `0x48A`/`0x381`) and one id inside `c_can`'s `0x000–0x019` range, so 621 B CAN frames went
   in tagged `c_can` — the source of seven ids that only ever appear on B/D CAN.
   Fixed with `min_anchor_hits` per bus, now part of `policy_hash`.

   **The measurement that said not to add this guard had filtered out the failing case.**
   `anchor_hit_distribution.py` skipped single-channel captures (`if len(ids) < 2: continue`),
   counted a channel as a `c_can` candidate only at `nc >= 10`, and sampled 70 strided files.
   Re-measured over **every channel of every coda log — 2,262 channels in 1,095 files, no
   pre-filtering** (`projects/coda/notes/artifacts/bus_label_min_anchor_audit.py`):
   `b_can` `{1: 36, 2: 1032}`, `d_can` `{1:1, 2:1, 3:19, 4:7, 5:866}`,
   `c_can` `{1: 1, 26: 280}` — perfectly bimodal. Thresholds are set at the observed
   minimum for a genuine channel: `c_can 10, d_can 3, b_can 1`. `b_can` stays at 1 because
   36 real channels carry only one of its two anchors. Regression over the same corpus
   (`bus_label_fix_regression.py`): **exactly 3 channels change**, all `_T6` tail chunks,
   all to `ch<N>`, which still uploads.

**`min_anchor_hits` is omitted from the `policy_hash` blob when unset, not written as
`null`.** Writing the key unconditionally moved Vtrux's hash from `0a5448cad23b` to
`651b7c52ab9b` and would have queued a re-upload of the entire Vtrux corpus for a
Coda-only change.

**Changed 2026-09-29 — Coda's `b_can` anchor set narrowed to audited-exclusive ids.**
It was `{0x1D5, 0x48A, 0x275, 0x381, 0x383}`; three of those (`0x1D5`, `0x275`, `0x383`)
are GWM gateway rebroadcasts present on D CAN too, at an exact 50.00 % frame split. It is
now `{0x48A, 0x381}`. The effect is not a narrow margin but a **tie**: a real D CAN
channel carrying 3 of its 5 exclusive ids scored `d_can: 0.60` and `b_can: 0.60`, decided
only by `d_can` being listed first in the profile — so reordering that list, an edit with
no apparent meaning, would have relabelled those channels `b_can`. Four such channels were
observed in 55 captures. With the narrowed set the same channel matches one set and scores
`b_can: 0`. No stored data was affected (0 of 51 captures had a `b_can` label without
`0x48A` or `0x381` present), so no re-upload is needed.

`identify_buses` now also **prints a warning when a channel matches more than one anchor
set**, since anchor sets are meant to be exclusive and resolving the overlap by fraction
produces a bus label with nothing behind it. It still resolves rather than refusing — one
stray frame should not fail an upload — but it says so. Measured: all 126 channels across
55 multi-channel Coda captures match exactly one set, so the warning should not fire in
normal use; if it does, the anchor table needs re-auditing.
See `projects/coda/notes/artifacts/anchor_exclusivity_audit.py` and the anchor table in
`projects/coda/README.md`.

**Changed 2026-09-28 — `--delete` no longer issues `DROP SERIES`.** It now runs a
time-bounded, verified `DELETE` per session (`clear_session_window`): the window
comes from `upload_manifest`, the delete is chunked to 24 h, and it checks the
window is non-empty first and empty afterwards, raising rather than letting the
caller upload on top of stale points. A missing manifest window also raises —
reading it as "nothing stored" would append the new timestamps beside the old ones.

The outage that prompted this was NOT caused by the delete. The host journal shows
memory pressure beginning 1 min 48 s into a loop of 54 unbounded `SELECT COUNT(*)`
queries, before any delete was issued; 40 minutes of swap thrash followed with no
OOM kill, and the box needed a power cycle. `DROP SERIES` was the next unbounded
statement to land on an already-starved server. **The rule is about unbounded
statements generally, reads included** — this instance has no query-timeout, no
max-concurrent-queries and no memory limit, so nothing server-side stops a heavy
one. `has_points()` is the read half: `SELECT ... LIMIT 1` rather than `COUNT(*)`,
which expands across every field.

**Changed 2026-09-26 (Coda 0x248 / 0x370 bus correction) — the same error as 0x276.**
Both were excluded on `b_can` as "D CAN native". Neither is. In
`codadriveslowturnonwithdefroster2.log` and `DCDCRUNNingwithoutkeyon-then-key-on.log`
both are on B CAN from +0.01 s with D CAN asleep and reach D CAN only when it wakes
(+9.46 s / +41.88 s); frame counts are 2836 on B against 742 on D. The exclusion kept
the gateway copy and dropped the original, so a B-only capture — every charge session —
would see nothing.
`0x370` additionally is **not** a faithful copy — B1 differs in 100 % of 34,919 matched
pairs (a bus tag) — so the D copy cannot stand in; `0x248`'s copies are byte-identical.

**No data was lost to this, unlike the 0x276 case**: neither `0x248` nor `0x370`
currently has any `SG_` signal defined, so both contribute zero points whichever bus is
excluded. The correction is pre-emptive — it matters the moment signals are added to
either, which is pending for `0x370`'s power-state field. `0x276` by contrast had eight
signals and did lose real data.
`0x370` is the GWM "Vehicle Faults" message (factory DTC master list, `U0146`) and
carries the vehicle power-state field. Both exclusions moved to `d_can`. This changes
the profile encoding, so `influx_sync.py --plan` schedules a full `reupload_file` of
every Coda session.

**Changed 2026-08-26 — `--only-id` no longer truncates the manifest.** A manifest row
describes a whole file, but a targeted upload wrote a fresh row claiming the file held
only the repaired message, under a policy hash carrying the `only_ids` restriction.
`influx_sync` then read manifest-says-1-message against data-has-20 and scheduled a
full re-upload of a file that was already current — so every targeted repair guaranteed
a later full re-upload and the repair path never converged. Observed on the Coda 0x1D7
precision fix: 126 repaired sessions all came back wanting 6.2 GB of `reupload_file`,
and the vtrux manifest showed five successive rows each claiming 1-2 messages with a
different policy hash. `fetch_manifest_row()` + `merge_manifest_fields()` now fold a
partial upload into the file's existing row — keeping the previous whole-file bounds,
counts, bus map and untouched message hashes, overlaying the rewritten ones, and
recording the *base* policy hash. If no previous row exists the old behaviour applies
and a warning is printed.

**Changed 2026-08-23 (Coda 0x276 bus correction):** the `coda` profile excluded
0x276 `HVACStatus` on `b_can` as a gateway copy. The AICM is a B CAN module -- it
transmits 0x276 with D CAN asleep, and D CAN receives the rebroadcast -- so the
exclusion kept the copy and dropped the original, blanking PTC heater energy for
every B-only capture. The exclusion now targets `d_can`. This changes the profile
encoding, so `influx_sync.py --plan` schedules a full `reupload_file` of all 262 Coda
sessions (20.5 GB) — there is no cheap targeted path, because `--delete` drops a whole
session regardless of `--only-id`. See `projects/coda/notes/efficiency-calculation.md` Sec.5.

Uploads CAN log data to InfluxDB 1.x for Grafana visualization. Decodes frames against
per-vehicle DBC sets (cantools) and writes signal values to the `signals` measurement.
Optionally writes raw byte values for undecodable frames to the `raw` measurement.

**Changed 2026-08-09 (influx-sync Phase 1 — see the internal `influx-sync` plan):**
- **Default write policy is now `on-change`**, not every frame. A signal is written only
  when its value changes, plus a heartbeat at most every `--heartbeat` seconds. Measured
  3.5x less disk. Use `--write-policy all-frames` for the old behaviour.
- Timestamps are computed in integer nanoseconds. The old
  `int((start_epoch + t) * 1e9)` injected +/-128 ns of float64 noise into every point.
  This is a **correctness** fix (exact `DELETE` time bounds), not a storage one —
  the noise was measured to cost nothing on disk.
- Tag values are now escaped. A `--session` containing spaces previously stored literal
  backslashes in the tag (e.g. `generator\ on\ then\ off`).
- The `influxdb` package is no longer a dependency — `DROP SERIES` goes over raw HTTP
  POST. `--dry-run` no longer requires `requests` either, so it works offline.
- `--only-id 0xNNN [...]` restricts an upload to specific CAN IDs, for targeted repair
  after a DBC message definition changes.
- **Anchoring is session-aware** via `canre/utils/timebase.py`. Laptop BUSMASTER captures
  record wall-clock time of day and some chunk headers state the wrong time
  (`debuglog_M1_T8` claims 12:07:43 for data starting 11:04:39); the anchor is now the
  file's true first-frame instant. 324 of 3,156 files are affected, 294 of them by under
  a second, two by more than 10 minutes. No file already in InfluxDB moves.
- **Header regex relaxed.** BUSMASTER does not zero-pad (`12:2:2025`, `0:1:30`); the old
  pattern rejected 356 of 3,135 headers and fell back to filename/mtime silently.

Each point carries a `bus` tag (e.g. `powertrain`/`vehicle`/`obd` for Vtrux,
`b_can`/`c_can`/`d_can` for Coda) identified from anchor IDs — never from the arbitrary
channel number in the log file.

**Requires:** `pip install cantools requests` (`requests` only for actual writes; `--dry-run`
needs just `cantools`)

**Default connection:** `localhost:8086`, database `canbus-data`, user `claude`.

**Usage:**
```
py -3.11 tools/influx_upload.py <log|folder> [<log2|folder2> ...] --vehicle <name> [options]

  log / folder           One or more log files or folders. Folders are expanded
                         non-recursively to .log/.asc/.trc/.csv files, sorted by name.
  --vehicle, -v          Vehicle name: vtrux | coda  [required]
                         Loads the vehicle's default DBC set and bus anchor IDs.
  --dbc, -d DBC [...]    Extra DBC file(s) appended after the vehicle defaults
  --host                 InfluxDB host (default: localhost)
  --port                 InfluxDB port (default: 8086)
  --database             InfluxDB database name (default: canbus-data)
  --user                 InfluxDB username (default: claude)
  --password             InfluxDB password (default: claude)
  --session              Override session name tag (default: derived from filename)
  --raw                  Also upload raw bytes for frames not decoded by any DBC
  --delete               DROP existing series for vehicle+session before uploading
  --dry-run              Parse and count points but do not write to InfluxDB
  --batch-size N         Points per write batch (default: 5000)
  --write-policy P       on-change (default) | all-frames. on-change writes a signal only
                         when its value changes, plus a heartbeat point. all-frames is the
                         pre-2026-08-09 behaviour (one point per decoded frame).
  --heartbeat SECONDS    Max gap between points for a signal under on-change (default: 1.0).
                         A heartbeat cannot fire without a frame, so for messages slower
                         than this the gap equals the message period.
  --success-log FILE     Append-only file recording successfully uploaded log paths.
                         On re-run, files already listed are skipped automatically.
                         Use with folder uploads so interrupted batches can be resumed.
                         No-op in --dry-run mode.
```

**Vehicle default DBCs:**

| Vehicle | DBCs loaded by default |
|---------|----------------------|
| vtrux | `vtrux-powertrain.dbc`, `BelInverter.dbc`, `GMW8762_PPEI_GMLAN.dbc` |
| coda | `CODA-B-CAN.dbc`, `CODA-D-CAN.dbc`, `CODA-C-CAN-cells.dbc` |

**Data model:**

| Measurement | Tags | Fields | When |
|---|---|---|---|
| `signals` | vehicle, bus, can_id, session | one field per signal name (float) | DBC-decoded frame |
| `raw` | vehicle, bus, can_id, session | b0..b7 (int), dlc (int) | Frame not in any DBC, with --raw |
| `upload_manifest` | vehicle, session, file | see below | one point per file, written after its data lands |

**`upload_manifest`** records what an upload actually wrote, so a later sync run can tell a
changed message (repair one `can_id`) from a changed policy (re-upload the file). Grafana
never queries it.

| Field | Purpose |
|---|---|
| `rel_path` | path relative to the project root, `..` allowed so `../../CANLogs/...` stays portable |
| `log_sha1`, `log_bytes`, `mtime` | source-file identity; sha1 only computed when size/mtime disagree |
| `encoding_ver` | bump invalidates every row and forces full re-upload |
| `policy_hash` | exclusions + write policy + heartbeat + `--raw` + `--only-id` |
| `msg_hashes` | JSON `{"bus\|can_id": hash}` from `canre.dbc.msghash`, only for messages this file wrote |
| `bus_map` | JSON channel -> bus name, as identified for this file |
| `points`, `values` | what was written |
| `t_start_ns`, `t_end_ns` | **observed** bounds, never re-derived — the repair path deletes by these |
| `uploaded_at` | also the point's timestamp; re-uploads append, newest wins via `LAST()` |

The manifest point is written **after** the data, so an interrupted upload leaves no row
claiming the file is done and a re-run replans it.

> The table above previously showed a `signal` tag and a single `value` field. That is the
> **legacy** schema, replaced by one-point-per-frame with signal names as fields (which is
> what keeps series cardinality bounded). Six sessions uploaded under the old schema are
> still live in `canbus-data` and are scheduled for rebuild — see the internal `influx-sync` plan.

**Known limitation — duplicate timestamps:** BUSMASTER logs timestamp at 0.1 ms resolution,
and two frames of the same CAN ID occasionally land on the same tick (measured 2 in 21,669
frames of Vtrux obd `0x044`). InfluxDB overwrites on identical
(series, field, timestamp), so the earlier frame is silently lost. This is independent of
`--write-policy` and predates the 2026-08-09 changes.

**Bus tag values:**

| Vehicle | Bus tag | Anchor IDs used |
|---------|---------|----------------|
| vtrux | `powertrain` | 0x051 |
| vtrux | `vehicle` | 0x1E5, 0x500 |
| vtrux | `obd` | 0x040–0x044 |
| coda | `c_can` | 0x000–0x019 (cell voltages) |
| coda | `d_can` | 0x308, 0x312, 0x325, 0x330, 0x580 |
| coda | `b_can` | 0x1D5, 0x48A, 0x275, 0x381, 0x383 |

Channels that don't match any anchor are tagged `ch<N>`.

**Timestamps:** Anchored by parsing `YYYYMMDD_HHMMSS` from the filename (standard
`can_logger.py` naming). Falls back to file mtime. Frame-relative timestamps are added
to produce nanosecond-precision InfluxDB timestamps.

**Session tag:** Derived from filename: `canlog_20260315_143000_M0_T0.log` → `2026-03-15_M0`.
Override with `--session` if needed.

**Known limitation — validity signal masking:** Many signals have a paired validity bit
(e.g. Coda cell voltages, GMLAN `*_Validity` signals). When validity is low the signal
value is meaningless but is still written to InfluxDB and plotted in Grafana. Two
sub-problems to solve:

1. **DBC encoding:** DBC has no native validity-gating concept. Leading candidate is a
   naming convention (`FooSignal` + `FooSignal_Validity`) so the uploader can
   automatically suppress `FooSignal` points where its paired validity bit is 0.
   Also worth checking whether cantools `invalid` value support causes `decode_message`
   to return `None` for out-of-range values (which the uploader already skips).
2. **Grafana side:** If invalid points do reach the DB, options are an InfluxQL `WHERE`
   clause filtering on a known sentinel value, or a Grafana "Filter by value" transform.
   The cleaner fix is upload-time suppression (sub-problem 1) so invalid points are
   never written.

**Updating after DBC changes:** Use `--delete` to drop the session's data before re-uploading.
Or run directly in InfluxQL:
```sql
DROP SERIES FROM signals WHERE "vehicle"='vtrux' AND "session"='2026-03-15_M0'
```

**Examples:**
```bash
# Basic upload using vehicle defaults
py -3.11 tools/influx_upload.py canlog_20260315_143000_M0_T0.log --vehicle vtrux

# Upload all logs in a folder (non-recursive)
py -3.11 tools/influx_upload.py projects/vtrux/logs/ --vehicle vtrux

# Upload a folder with a success log so interrupted runs can resume
py -3.11 tools/influx_upload.py projects/vtrux/logs/ --vehicle vtrux \
    --success-log projects/vtrux/notes/artifacts/upload_done.txt

# Add an extra DBC on top of the defaults
py -3.11 tools/influx_upload.py <log> --vehicle coda --dbc projects/coda/extra.dbc

# Include raw bytes for frames not in any DBC
py -3.11 tools/influx_upload.py <log> --vehicle vtrux --raw

# Re-upload after DBC changes
py -3.11 tools/influx_upload.py <log> --vehicle vtrux --delete

# Dry run (shows bus detection and point counts, no writes)
py -3.11 tools/influx_upload.py <log> --vehicle vtrux --dry-run
```

---

## uds_interrogator.py
*Source last modified: 2026-03-15*
*API reference: `canre/uds/uds.md`*

Scans a CAN bus for UDS-responding ECUs and fully interrogates each one.
Outputs a JSON report plus a human-readable console summary.

Requires: `pip install can-isotp` (installs as `isotp` module; package name is `can-isotp` not `isotp`)

**Usage:**
```
py -3.12 tools/uds_interrogator.py [options]

  --bitrate N           CAN bitrate in bps (default: 500000)
  --brands BRANDS       Comma-separated dongle brands (default: all detected)
  --scan-range S:E      Hex address range e.g. 0x600:0x7EF (default: 0x600:0x7EF)
  --scan-timeout MS     Per-address timeout ms during scan (default: 50)
  --request-timeout MS  Per-request timeout ms during interrogation (default: 200)
  --module ADDR         Skip scan; interrogate only this address e.g. 0x7E0
  --output FILE         JSON output path (default: auto-named in project root)
  --output-dir DIR      Directory for auto-named output
  --no-kwp              Skip KWP2000 0x18 DTC queries
  --no-dtc              Skip all DTC queries (0x19 and 0x18)
  --verbose / -v        Print per-address and per-module progress
  --debug               Enable debug logging
```

**Scan coverage:** 0x600-0x7EF by default (496 addresses, ~25 s worst case).
Each address is probed with DiagnosticSessionControl default (0x10 0x01).

**Interrogation per module:**
1. Extended session (0x10 0x03)
2. All F1xx ECU identity DIDs via ReadDataByIdentifier (0x22)
3. Service support probes (0x10, 0x19, 0x22, 0x27, etc.)
4. All 10 UDS ReadDTCInformation (0x19) subfunctions
5. KWP2000 ReadDTCByStatus (0x18) for 5 DTC groups
6. Return to default session

**Non-standard response ID detection:** the tool taps all received CAN frames
during each probe and flags ECUs that respond on an ID other than request_id+8.

**JSON report structure (abbreviated):**
```json
{
  "generated_at": "ISO8601",
  "hardware": "ixxat HW379841",
  "bitrate": 500000,
  "scan_range": {"start": "0x600", "end": "0x7EF"},
  "modules_found": 2,
  "modules": [{
    "request_id": "0x7E0", "response_id": "0x7E8",
    "session_extended": true,
    "dids": {"0xF190": {"responded": true, "value": "VIN...", ...}},
    "service_probes": {"0x19": {"supported": true, "nrc": null}},
    "dtc_results": {"0x02_reportDTCByStatusMask": {"responded": true, "dtc_count": 2, ...}},
    "kwp_dtc_results": {"0xFF00_all": {"responded": false, "nrc": "0x11"}}
  }]
}
```

---

## make_graph.py
*Source last modified: 2026-03-12*
*Notes and .gdf format findings: `tools/savvycan-graphing.md`*

Generates SavvyCAN Graph Definition (`.gdf`) files from DBC signals. Replaces the slow
matplotlib path for exploratory graphing — load the output via SavvyCAN right-click →
"Load graph definitions from file".

**Usage:**
```
py -3.12 tools/make_graph.py --dbc PATH [PATH ...] --signal MSG.signal [MSG.signal ...]
                              [--output PATH] [--append] [--stride N] [--line-width N]

  --dbc PATH [...]    DBC file(s) to search for signals. Searched in order; first match wins.
                      Handles extended-ID DBCs that lack the 0x80000000 marker.
  --signal MSG.signal Signal(s) as MessageName.signal_name. Repeatable.
  --output PATH       Output .gdf file (default: graph_output.gdf in CWD)
  --append            Append to existing .gdf; color cycling continues from last existing signal.
  --stride N          Plot every Nth point (default: 1)
  --line-width N      Line width in pixels (default: 1)
```

**Multi-DBC workflow** — use when signals span multiple sources (main DBC, GMLAN, provisional):
```bash
# Step 1: create .gdf with main DBC signals
py -3.12 tools/make_graph.py \
    --dbc projects/vtrux/BelInverter.dbc \
    --signal BELINV_hvBatteryAndCharger.BELINV_hvBatteryVoltage \
             BELINV_hvBatteryAndCharger.BELINV_hvBatteryCurrent \
    --output projects/vtrux/notes/artifacts/my_graph.gdf

# Step 2: append a signal from a second DBC
py -3.12 tools/make_graph.py \
    --dbc projects/vtrux/GMW8762_PPEI_GMLAN.dbc \
    --signal SomeMsg.SomeSignal \
    --output projects/vtrux/notes/artifacts/my_graph.gdf --append
```

**SavvyCAN workflow:**
1. Open log in SavvyCAN (drag-drop or File → Open)
2. Open Graph window
3. Right-click graph area → "Load graph definitions from file" → select `.gdf`

**Color cycling:** 8-color palette (blue, orange, green, red, purple, brown, pink, gray).
`--append` reads the existing file to count signals and continues the cycle correctly.

**BE signal caveat:** Big-endian signals emit a warning with the raw cantools start bit.
SavvyCAN may use a different bit-addressing convention — hand-edit the `.gdf` if needed.

**Notes:**
- DBC files with overlapping signals (e.g. GMW8762 GMLAN) load with `strict=False` — noisy
  "Overwriting message" warnings are suppressed automatically.
- Extended CAN IDs stored without the 0x80000000 marker are fixed automatically on load.
- Save `.gdf` files to `projects/<vehicle>/notes/artifacts/` for reuse across sessions.

---

## can_monitor.py
*Source last modified: 2026-03-09*

Live CAN monitor with vehicle-aware GUI. Auto-detects dongles, sniffs for 5 s to identify which
physical channel is which logical bus (anchor detection), then opens a PyQt5 window showing decoded
signals for the active vehicle mode. Simultaneously writes a BUSMASTER log if `--output` is given.

**Usage:**
```
py -3.12 tools/can_monitor.py --vehicle coda [options]

  --vehicle, -v   Vehicle name: coda | vtrux  [required]
  --bitrate, -b   CAN bitrate in bps (default: 500000)
  --brands        Comma-separated brands to capture from (e.g. ixxat,kvaser)
  --output, -o    Optional BUSMASTER log file for simultaneous capture
  --output-dir,-d Directory for auto-named log file
  --debug         Verbose logging
```

**Vehicle profiles:** `projects/<vehicle>/gui_profile.py` — each exports a `PROFILE` instance
(subclass of `canre.gui.base_profile.VehicleProfile`).

**Mode detection:** `ModeRule` objects declare conditions (ID presence or signal value predicate).
A mode is active if ANY of its rules evaluates True. Modes are evaluated in priority order; the
last mode is the fallback default. Mode switches automatically on every 50 ms tick.

**Coda modes (charging GUI implemented 2026-03-09):**

| Mode | Trigger signals |
|------|----------------|
| charging | HVPowermode=5 OR Chargemode=3 OR HVBattCharging=1 OR CMS messages present (0x27B) |
| idle | B CAN alive (0x383 present) |

**Charging layout signals (all B CAN):**
- Battery Pack: SoC (0x383), PackVoltage/PackCurrent/BattSentChargeLimit (0x275)
- Cell Voltages: min/avg/max mV, spread, cell IDs (0x381 BMSVminVmax) — spread alert > 50 mV
- Pack Temperature: avg/max/min degC (0x382 BMSThermal)
- Charger Input CMS: AC voltage/current/power (0x27B CMSInputValues)
- Charger Output CMS: HV out V/I/P (calc), LV out V/I (0x27C CMSOutputValues)
- Charger Temps CMS: case/PFC/HV1/HV2 degC (0x27A CMSTempStatus)
- BMS Charger Command: current cmd, max voltage (0x050 BMSChargerCmd)
- System Status: HVPowermode, Chargemode, BMSmode, fault severity/code, fault lamp, cable/full flags
- HVAC/Thermal: PTC power, battery fan PWM, radiator fan PWM (0x276), DCDC 14V (0x1D5)

**Dependencies:** `PyQt5`, `cantools`, `python-can` (all already project deps)

**Architecture:** `canbench/live/receiver.py` (hardware), `canbench/live/vehicle_configs.py` (anchor data), both in the can-tools clone (`tools-reference.md`),
`canre/gui/` (framework: `base_profile`, `bus_decoder`, `widgets`, `main_window`).

---

## can_logger.py, can_replayer.py, can_gui.py: in the can-tools git clone, not here
*Source: `nickyivyca/can-tools`; `can_replayer.py` and the adapter detection both tools use (`canbench/live/receiver.py`) last changed in `885e470`, on `main` since `1cd3942` (2026-10-31)*

These live **only** in the can-tools git repo, cloned per machine at `~/Git/can-tools` (path,
`.pth` setup and pull-before-use: `tools-reference.md`, section "can-tools"). The old SeaDrive mirror
here (`tools/can_logger.py`, `can_replayer.py`, `can_logger_admin.bat`, `README-can_logger.md`,
`canbench/` at the root) and `sync_from_can_tools.py` were deleted on 2026-10-31
(the internal `can-tools-git-cutover` plan). Run the tools as
`<python> ~/Git/can-tools/tools/can_replayer.py ...`. The clone's `README.md`,
`tools/README-can_logger.md` and each tool's `--help` are authoritative; the summary below is
for routing only.

**can_logger.py** -- multi-device logger. Auto-detects every connected dongle (ixxat, kvaser,
pcan, gs_usb, socketcan; SocketCAN by kernel driver, each adapter logged with its ids) and writes them all to one candump / SocketCAN `.log` (absolute epoch
timestamps, bus id in the `canN` interface field). Flags: `--output/-o`, `--output-dir/-d`,
`--bitrate/-b`, `--brands`, `--passthrough` (bridge exactly two dongles, logging each frame by
the bus it came from), `--debug`. On Windows, the clone's `tools\can_logger_admin.bat` self-elevates so ixxat
overflow recovery (PnP disable/enable of the one dongle) works.

**can_replayer.py** -- plays a log back through connected hardware at original timing (plan
the internal `can-replay-readers` plan). Reads the format **by content**: BUSMASTER (with
`--session`, every `_T<n>` chunk of a session, chained on their headers) and PEAK TRC 1.0-2.1
through `canbench.parsers`; candump `.log`, Vector `.asc` / `.blf`, CSV and SavvyCAN through
python-can. Flags: `--session`, `--vehicle`, `--bus`, `--raw-channel`, `--adapter BUS=ID`,
`--bitrate/-b`, `--brands`, `--speed/-s` (0 = no delay), `--loop/-l`, `--skip-confirmation`,
`--debug`.
- **Buses by anchors:** `--vehicle coda --bus d_can` picks the bus by its anchor ids. A bare
  `--bus N` is refused for BUSMASTER/TRC input, since a channel number there is dongle order, not
  a bus (AGENTS.md, Data Sources); `--raw-channel` replays a channel number as it is. candump
  input keeps `--bus N` (can_logger's `canN`).
- **Adapters by identity:** every detected adapter is printed with its ids (`serial:<s>`,
  `usb:<port>`, `pcan-id:<n>`, plus the plug-order slot). With one adapter, every bus goes out on
  it; with two or more, pin each bus with `--adapter BUS=ID` (or narrow `--brands` to one), else
  the replayer refuses rather than guess. Only adapters something is sent on are opened. On Linux,
  SocketCAN adapters are picked by kernel driver, never by `canN` name.
- **Never transmitted, counted in the summary:** non-frame records (BUSMASTER `ERR`, TRC `ER` /
  `ST` / `EC` / `EV`), error frames, and frames marked as inferred adapter error reports
  (`can-tools/canbench/parsers/inferred_errors.py`).

**can_gui.py** -- PyQt logger front-end (vehicle profiles, dongle selection, per-bus frames/sec,
candump logging).

**Loopback check:** start `can_logger.py --brands kvaser --output verify.log`, then
`can_replayer.py <capture.log> --brands ixxat`; frame counts should match to within a handful.

---

## status_events.py
*Source last modified: 2026-03-28 12:57:46*

Status event finder with two modes: **auto-discovery** (default) surveys all IDs and auto-selects discrete status signals, or **watch-profile** uses a manually curated signal set. Tracks byte-level and optionally bit-level transitions, filters to quiet signals, detects and excludes rolling counters, and clusters co-occurring transitions into events.

**Usage:**
```
python tools/status_events.py <log> [log ...] [options]

  log                       Log file(s). Pass multiple T-chunk files to merge at runtime.
  --bus N                   Filter to single bus number
  --watch-profile NAME      Use a named vehicle-specific signal set (e.g. "coda-charging")
  --auto                    Auto-discover candidates (default when no --watch-profile)
  --max-transitions N       Quiet-signal threshold (default: 50)
  --gap SECONDS             Cluster gap in seconds (default: 2.0, 0=disable clustering)
  --bits                    Include bit-level transitions
  --output FILE             Write report to file instead of stdout
```

**Modes:**

- **Auto-discovery** (default): Runs `run_survey()` on the log, selects bytes with `unique_count` 2–16 as byte-level candidates. With `--bits`, bytes with `unique_count` 17–256 are also scanned at bit level. Skips extended (29-bit) IDs and constant bytes.
- **Watch-profile**: Selects from `WATCH_PROFILES` dict in the source. Currently available: `coda-charging`. Signal annotations (human-readable labels) are shown in profile mode.

**Analysis pipeline:**

1. **Load** — parses entire log into memory via `parse_file()`
2. **Candidate selection** — from survey or watch-profile
3. **Transition scan** — single pass: tracks byte-level state changes; optionally XOR-decomposes into bit-level transitions; inline counter detection (>80% sequential +1/-1, only for bytes with >4 unique values)
4. **Classification** — each signal tagged QUIET (count <= threshold), NOISY (above), or COUNTER
5. **Clustering** — quiet transitions sorted by time, split into clusters at gaps > `--gap` seconds
6. **Output** — three sections: signal inventory, event clusters, full timeline

**Output sections:**

1. **Signal Inventory** — all candidate signals with transition counts, sorted ascending, tagged QUIET/NOISY/COUNTER
2. **Event Clusters** — groups of co-occurring transitions with time range, transition count, and signal count per cluster. Single-transition clusters marked "(isolated)"
3. **Full Timeline** — flat chronological list of all quiet-signal transitions

**Vehicle-specific config** (top of source file, clearly marked):

- `WATCH_PROFILES` — named signal sets per vehicle/session. Currently: `coda-charging` (B CAN bus 3 + C CAN bus 1 charger/BMS signals)
- `SIGNAL_NOTES` — human-readable labels keyed by `(bus, id, byte)` or `(bus, id)`. Only shown in watch-profile mode.

**Imports:** `canre.parsers.autodetect.parse_file`, `canre.analysis.survey.run_survey`

---

## survey.py
*Source last modified: 2026-02-15 12:39:49*

CLI wrapper around `canre.analysis.survey`. Surveys CAN bus traffic from a log file or directory, reporting an ID inventory with frame counts, frequencies, and byte-level statistics.

**Usage:**
```
python tools/survey.py <path> [options]

  path             Log file or directory of log files
  --bus N          Filter to specific bus number
  --output, -o     Save results to JSON file
```

**Input handling:**
- Single file: parses and surveys directly.
- Directory: detects capture groups (`_M*_T*` or `_T*` pattern), merges grouped files, surveys each group separately. If no groups found, surveys each `.log` individually.

**Output:** Formatted survey table to stdout. With `--output`, saves JSON (directory mode appends group name to filename).

**Imports:** `canre.parsers.parse_file`, `canre.analysis.survey`, `canre.utils.merge`

---

## analyze_id.py
*Source last modified: 2026-05-02 23:28:11*

Deep-dive analysis of a single CAN arbitration ID. Three separate passes: bit-level statistics, rolling counter detection, and checksum detection. Optionally decodes against a DBC file.

**Usage:**
```
python tools/analyze_id.py <log> [log ...] [options]

  log              Log file(s). Pass multiple T-chunk files to merge at runtime.
  --id ID          CAN ID in hex (e.g. 0x123) [required]
  --bus N          Filter to specific bus number
  --dbc FILE       Optional DBC file for signal decoding context
  --start SECS     Start of time window in seconds (relative to capture start)
  --end SECS       End of time window in seconds (relative to capture start)
```

**Output sections:**
1. Per-byte and per-bit statistics (ranges, entropy, toggle rates)
2. Counter detection (sequential +1/-1 patterns with confidence)
3. Checksum detection (XOR, sum, CRC-8 J1850, nibble sum per byte position)
4. DBC signal decode (only with `--dbc`)

**Notes:** `--id` is always parsed as hex regardless of `0x` prefix. All three analysis passes reuse a single in-memory frame list (log loaded once).

---


## compare.py
*Source last modified: 2026-02-15 12:40:04*

Compares two CAN bus captures: IDs unique to each, and byte-level diffs for shared IDs.

**Usage:**
```
python tools/compare.py <log_a> <log_b> [options]

  log_a            First log file
  log_b            Second log file
  --ids-only       Only compare ID presence; skip byte-level diff
  --bus N          Filter to specific bus number
```

---


## extract_timeseries.py
*Source last modified: 2026-03-28 12:58:23*

Extracts a raw signal time series from a CAN log for a specific ID and byte range. Outputs CSV.

**Usage:**
```
python tools/extract_timeseries.py <log> [log ...] [options]

  log              Log file(s). Pass multiple T-chunk files to merge at runtime.
  --id ID          CAN ID in hex (e.g. 0x123) [required]
  --bytes RANGE    Byte index or range, e.g. '2' or '2-3' [required]
  --endian MODE    'big' or 'little' (default: big)
  --signed         Interpret as signed
  --output, -o     Output CSV file (default: stdout)
  --bus N          Filter to specific bus number
```

**Notes:** `--bytes` range is inclusive on both ends. `--id` always parsed as hex.

**Limitation — no DBC mux / validity gating:** This tool extracts raw bytes directly from frames without consulting the DBC. It has no concept of multiplexed messages or validity flags. For multiplexed signals (e.g. `0x200 ESC_FrontWheelSpeeds`, where B0 is a sub-frame selector and wheel speeds are only valid when B0=0x00), the tool will include all frames regardless of mux state, producing spurious values from non-speed sub-frames. Workaround: post-filter the CSV on a known validity byte/value before plotting. **Outstanding feature:** add a `--gate-byte`/`--gate-value` option that reads the DBC mux definition for the target signal and drops frames where the mux signal does not match the expected value.

---

## dbc_skeleton.py
*Source last modified: 2026-02-15 12:40:14*

Generates a skeleton DBC file from observed CAN traffic. One message per observed ID, with DLC from traffic.

**Usage:**
```
python tools/dbc_skeleton.py <log> [options]

  log              Log file path
  --output, -o     Output DBC file (default: skeleton.dbc)
  --bus N          Filter to specific bus number
```

---

## dbc_validate.py
*Source last modified: 2026-02-15 12:40:16*

Validates a DBC file against actual CAN traffic. Reports coverage, undefined IDs, and decode errors.

**Usage:**
```
python tools/dbc_validate.py <dbc> <log> [options]

  dbc              DBC file path
  log              Log file path
  --bus N          Filter to specific bus number
```

---

## merge_logs.py
*Source last modified: 2026-02-15 12:40:21*

Merges chunked CAN log captures. Supports both `_M{bus}_T{chunk}` (BUSMASTER multi-bus) and `_T{chunk}` (timestamp-keyed sessions) naming patterns. Detects capture groups in a directory and either prints a frame count summary or writes merged CSV.

**Usage:**
```
python tools/merge_logs.py <directory> [options]

  directory        Directory containing log file chunks
  --output, -o     Output CSV file (default: print summary only)
  --group          Process only this named capture group
```

**Output format:** CSV with columns: `timestamp, bus, id, extended, dlc, data`. Multiple groups get separate files with group name appended to stem.

---

## list_sessions.py
*Source last modified: 2026-02-16 19:34:14*

Lists and groups CAN log files in a directory by capture session.

**Usage:**
```
python tools/list_sessions.py <path> [options]

  path             Directory containing log files
  --json           Output as JSON instead of human-readable
```

**Output:** Session names with file counts and filename ranges. JSON mode outputs keyed by session name with `file_count` and `files`.

---







## session_compact.py
*Source last modified: 2026-10-31 07:49:02*
*Plan: `Infrastructure/tools/self-compact/plan.md` (moved 2026-10-31). Procedure: AGENTS.md, "Compacting your own context". Tested on Windows and in tmux on madhouse (plan steps 2-3); run it by its full path (see AGENTS.md).*

A terminal Claude Code session compacts its own context, then resumes. It types
`/compact <msg>` into the session's own input (held until the turn ends), and a
detached waiter types the resume message once the transcript records the manual
compaction. Linux: tmux sessions only (`$TMUX_PANE`). Windows: the session's own
console. Target is only the `claude` process the tool runs under. With `--compact-only`
the waiter types nothing after the compaction (user, 2026-10-31: the resume is the
default).

**Usage** (run as the session's own tool call, alone, as the last action of the turn):
```
<python> tools/session_compact.py --compact "<what to keep>" --resume "<next assigned step>" [--check]
<python> tools/session_compact.py --compact "<what to keep>" --compact-only [--check]

  --compact        mandatory; one line of printable ASCII, at most 600 characters
  --resume         same, and must not start with / ! or #; required unless --compact-only
  --compact-only   type nothing after the compaction; excludes --resume
  --check          validate and resolve the target; type nothing
  --timeout        seconds to wait for the compaction (default and maximum 3600)
```

**Output:** JSON with the outcome (`check-ok`, `queued`, `refused` and the reason); exit 0 or 2.
Calls and waiter outcomes (`resumed`, `compacted`, `timeout`, `target-gone`, `error`), each
with its mode, are logged to
`tools/artifacts/session_compact_<hostname>.log.jsonl`. Lock and request files live in
`<temp>/session-compact/`. The waiter records its PID in the lock; a later call clears a lock
whose owner is no longer running (`stale_lock_cleared` in the output), or one older than the
timeout plus 5 minutes.

---

## idle_compact_hook.py
*Source last modified: 2026-10-31 07:55:30*

PreCompact hook, the Linux box only: when Claude Code tries to compact a session that has been idle about 54 minutes, it blocks that once and wakes the session to self-compact with `session_compact.py` (AGENTS.md, "Compacting your own context"). The wake text says the resume is the default and when `--compact-only` may be used instead. If no compaction follows, the next attempt goes through. Installed in madhouse's `~/.claude/settings.json`, not in this folder's settings, because those sync to every machine. State and log are in `/tmp/reverse-it-session-compact/idle-hook/`.

---

## error-report-sweep/ (corpus validation of canbench's inferred-error rules)
*Source last modified: prefix_error_report_sweep.py, marker_check.py, kvaser_id0_survey.py, kvaser_id0_sweep.py: 2026-10-31 00:10:29*

Moved here from `tools/artifacts/error-report-sweep/` on 2026-10-31 (owner: a tools project, not
an artifact). The scripts and `README.md` sit at the top, and their regenerable outputs in
`artifacts/` (`scan.jsonl` ~150 MB). The rules and the evidence for them are in the README.
Corpus sweeps read `CANLogs/`, so run them on the Linux box from the reverse-it root, e.g.
`python3.13 tools/error-report-sweep/marker_check.py kvaser`. The rules themselves live in
`can-tools/canbench/parsers/inferred_errors.py`.

## PEAK-Converter/ (PEAK's trace converter, Windows; not published)
*Source last modified: 2026-10-31 10:02:47 (PEAK's files, unmodified; copied from the bench laptop's Downloads, unzipped from `PEAK-Converter.zip`, SHA-256 `2dd101fd...2de2b9`)*

PEAK-System's free PEAK-Converter, a portable Windows exe (no install), kept here so the bench laptop
can convert bench traces between TRC versions (the internal `can-replay-readers` plan, step 6c open
item). **PEAK's software: not published** -- not into can-tools, not into the public repo; held by
ruling 32 in `git-publish.md` (an explicit deny in `artifacts/publish_diff.py`); also, PEAK hosts it and it is easy to get, so it is not rehosted (owner, 2026-11-01, as with datasheet PDFs). Seven files:
`PEAK-Converter.exe`, `PEAK-Converter.dll`, `PEAK-Converter.exe.config`, `BLF2CSV.exe` (Vector
BLF to CSV), `PEAK-Converter_UserMan_eng.pdf` (the manual), `README.md` (PEAK's own, for
`BLF2CSV.exe`) and `GPL-3.0-or-later.txt` (`BLF2CSV`'s licence). Run it from a copy in `%TEMP%`,
not from SeaDrive. First run 2026-10-31 by the gen-inhibit tester for that step (v3.2.1.686, from a `%TEMP%` copy).
Command line (manual chapter 7):
`PEAK-Converter.exe "<source.trc>" /TF=PCAN /TV=2.1 /TD="<existing dir>" /TN=<base name> /OE`.
`/TD` must exist and must not end in a backslash; without `/TN` the target takes the source's
name. Never pass `/WS` (it shuts Windows down after converting).
