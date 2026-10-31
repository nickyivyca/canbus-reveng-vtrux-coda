# error-report-sweep

Scripts at the top, regenerable outputs in `artifacts/`. Run from the reverse-it root on
the Linux box (each script's docstring). Moved from `tools/artifacts/` 2026-10-31.

Step 1 of the internal `can-replay-readers` plan: validating a rule that marks pre-Bug-11 gs_usb
error reports (written by old Android builds as plain standard frames, id = SocketCAN
error-class mask, DLC 8) without catching real frames that share the id, such as Coda C CAN
`0x004` / `0x00C` cell voltages.

| File | What it is |
|---|---|
| `prefix_error_report_sweep.py` | the sweep; phases `scan`, `report`, `check`, `controls`, `masks` (docstring) |
| `artifacts/scan.jsonl` | `scan` output: one JSON row per capture (regenerable, ~150 MB) |
| `artifacts/scan.log` | `scan` progress log |
| `artifacts/report.txt` | `report` output: per (vehicle, bus, id) rule outcomes, false-positive streams, 1 s tick test, samples |
| `artifacts/masks.txt` | `masks` output: Innomaker id streams that never fail the layout test, set against desktop-adapter traffic; tick test on the three mask ids; C CAN cases |
| `marker_check.py` | step 3 check of canbench's implementation of the rule (`canbench/parsers/inferred_errors.py`, can-tools clone); phases `bench`, `corpus`, and `kvaser` for step 4c (docstring) |
| `kvaser_id0_survey.py` | counts short (DLC < 8) standard-id `0x000` frames per capture, by header adapter, with payloads and where in the capture they fall; raised at step 4 by two Coda captures where they made a B CAN channel ambiguous (docstring) |
| `artifacts/kvaser_id0_survey.txt` | `kvaser_id0_survey.py` output (2026-10-30, 3,643 captures) |
| `kvaser_id0_sweep.py` | step 4c: validates a marking rule for those frames (Kvaser header, standard id `0x000`, DLC 4, count or flags payload form); phases `scan`, `report` (docstring) |
| `artifacts/kvaser_id0_scan.jsonl` | `scan` output: one row per capture (regenerable) |
| `artifacts/kvaser_id0_scan.log` | `scan` progress log |
| `artifacts/kvaser_id0_report.txt` | `report` output |
| `artifacts/marker_check_corpus.txt` | `corpus` output: 714 / 714 captures agree with the rule's prediction from `scan.jsonl`, 53,958 frames |
| `artifacts/marker_check_kvaser.txt` | `kvaser` output (step 4c): 209 / 209 Kvaser-header captures agree with `kvaser_id0_scan.jsonl`, 68,116 frames |
| `artifacts/marker_check_corpus_4c.txt` | `corpus` rerun after the Kvaser rule was added: Innomaker marks unchanged on all 714; the 2 differences are Kvaser-rule marks (note at its end) |

## The rule (approved by the owner, 2026-10-30)

A frame is marked an **inferred** error report -- flagged distinctly from a written `ERR`
line -- only when all of these hold; anything else stays data:

1. **Capture gate:** the header names an Innomaker adapter and the file has no `ERR` lines
   (written before the Bug 11 fix).
2. **Id gate:** the id is `0x004`, `0x00C` or `0x024` -- the masks the Innomaker was measured to
   emit. Others are added only from a measurement (bus-off `0x040` has never been seen).
3. **Payload gate:** the payload fits the `linux/can/error.h` layout (a byte whose class bit is
   clear is zero; controller, protocol and location bytes carry only legal codes), **or** it
   is all zero and **no frame of that id on that channel in that capture fails the layout
   test** (refined 2026-10-30, owner: decided per capture and channel, not per bus, so it needs
   no bus label and no assumption about which buses carry the id). Otherwise an all-zero frame
   stays data and is counted. On the corpus this gives the same result as the first, per-bus
   wording: Coda C CAN channels always carry failing `0x004` frames, the other buses never do.
   The Android session's `--decoys` bench run (real all-zero and cell-like `0x004` data on a
   B CAN-looking channel) is the test of the difference.

## Implemented in canbench (2026-10-30)

`canbench/parsers/inferred_errors.py` in the can-tools clone carries the rule unchanged;
`parse_file(path, mark_inferred_errors=True)` sets `CANFrame.inferred_error` and drops nothing.
Checked by `marker_check.py`: exact on the Android session's two pre-fix bench runs (build 31,
`android-app/notes/artifacts/fault_matrix_20261030_prefix31*`: 15 + 14 and 18 + 12 reports
marked, all 378 decoys left as data), and 714 / 714 corpus captures agree with this sweep's
own prediction.

## Evidence (sweep run 2026-10-30, the Linux box)

- **Scope:** 3,643 captures (Coda and Vtrux; `CANLogs/` + `projects/<vehicle>/logs/`,
  non-recursive). Channels labelled by anchors with >= 2 distinct anchors of one bus and none
  of any other; Coda against the audited sets, Vtrux against **unaudited** provisional sets.
  55 Coda and 24 Vtrux channels did not resolve.
- **Orthogonal check:** the scan's hand split agrees with `canre.parsers.parse_file` frame for
  frame on 11 of 12 sampled captures; the twelfth (`coda_20201228_000045_T0`) differs by one.
- **Positive controls:** every known error frame in the fault-matrix bench runs passes the
  layout test: 28 (AVD app), 29 (phone app), 29 (kernel gs_usb reference), 15,900 (IXXAT).
- **Why the id gate:** without it the layout test passes large native streams of sparse
  payloads, e.g. Coda B CAN `0x07D` (12.3 M frames), Vtrux `0x0F9`, `0x232`.
- **Coda C CAN:** of ~1.08 M `0x004` / `0x00C` frames, exactly **1** passes, and it is a real
  error report: `00 30 02 00 00 00 00 F9` among cell frames in `coda_20260824_123642_T2`. No
  all-zero frame on either id.
- **Coda B / D CAN:** all 97 B CAN (39 layout, 58 all-zero `0x004`) and 5 D CAN reports pass.
- **Vtrux powertrain + OBD:** ~53,700 `0x004` / `0x00C` / `0x024` frames, none failing.
- **1 s tick: not usable in field logs.** The bench's 1 s reporting tick does not show in the
  corpus: median gaps between reports are 0-15 ms and under 5 % of the >= 0.9 s gaps fall on an
  integer second, except Vtrux `0x024` and Coda D CAN `0x00C`. The cause is not investigated.

## Kvaser id-0x000 status frames (step 4c, 2026-10-30)

Desktop BUSMASTER 3.2.2 captures from Kvaser adapters carry standard id `0x000`, DLC 4 frames
in two forms: **count** `00 00 NN 00` (NN mostly 00-0F; between consecutive frames on a
channel, NN most often drops by 1) and **flags** `00|20 xx 00 00`. **Hypothesis, not
confirmed:** adapter error-counter and error-state events written as data frames. This is
separate from the Innomaker Bug 11.

**Rule** (`canbench/parsers/inferred_errors.py`): the header names a Kvaser for the frame's
channel; standard id `0x000`; DLC 4; count or flags form.

**Evidence** (`kvaser_id0_sweep.py`, 3,643 captures; 209 with a Kvaser header: Coda 22,
Vtrux 187; channels labelled with `0x000` removed from every anchor set):

- **Hits:** 68,116 frames: Vtrux OBD 60,964 (count form), powertrain 7,120 flags + 21 count,
  gm_unfiltered 6, Coda B CAN 5. **None on C CAN.** All 395,720 DLC-8 `0x000` frames are on
  C CAN.
- **Not caught:** the desktop replays recorded by Android (Innomaker header, now quarantined in
  `android-app/notes/artifacts/vtrux_bench_replay_captures/`) and 1 DLC-0 frame.
- **Resolver:** with `0x000` kept as a C CAN anchor and marked frames left out, ambiguous
  captures go from 7 to 5, all of them the merged replay. So `0x000` stays a C CAN anchor.
- **No positive control:** no desktop BUSMASTER + Kvaser run with known errors exists.
- **Implementation:** canbench `inferred_errors.py` (can-tools `abe5627`); `marker_check.py
  kvaser` gives 209 / 209 captures and 68,116 frames exact.
