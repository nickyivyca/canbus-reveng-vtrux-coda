# PEAK TRC error records: what PEAK's tools actually write

Written 2026-10-31 from step 6c of the internal `can-replay-readers` plan and its open item "a
PEAK-written TRC 2.x with `ER`/`ST`/`EC` records". It covers what PEAK's trace spec says about
the non-frame records (`ER`, `ST`, `EC`, 1.x `Error` / `Warng`), what PCAN-Basic 5.0 and
PEAK-Converter 3.2 really write, and where the two disagree. The reader these findings apply to
is can-tools' `canbench/parsers/peak_trc.py` (documented in can-tools' `canbench/parsers/parsers.md`).

Sources:

- PEAK's spec, `tools/artifacts/trc-reader/PEAK_CAN_TRC_File_Format.pdf`, a local copy of the
  [PDF PEAK publishes](https://www.peak-system.com/produktcd/Pdf/English/PEAK_CAN_TRC_File_Format.pdf).
- The bench traces the gen-inhibit tester recorded on the ESP bench's PCAN-USB FD on the bench laptop:
  `tools/artifacts/reader-bench-captures/` (the tester's folders, read-only here).
- Read-backs: `tools/artifacts/reader-bench-readback/`.
- Web research, 2026-10-31 (links below).

## Which PEAK tool writes which version

- PCAN-Basic writes TRC **1.1 on a classic channel** and **2.0 on an FD channel**. This is
  measured on 5.0.0.1115, and the PEAK-Converter manual says the same.
- PCAN-View 4/5 writes 2.0.
- Only PCAN-Explorer 6 writes 2.1, and PCAN-Explorer 7 writes 3.0. Both are paid, and the owner
  declined them (2026-10-31).
- PEAK-Converter 3.2.1.686 is free and portable, and is kept in `tools/PEAK-Converter/` (held,
  see `tools/tools.md`). It writes any version from 1.0 to 3.0.
- **Public files** (GitHub code search, 2026-10-31): 45 distinct PEAK-written TRC files were
  found, from PCAN-View 4.0-5.3, PCAN-Explorer 5 and 6.0-6.8, and PEAK-Converter 2.2/3.0.
  - canbench reads the same frames from each as python-can, with intervals within 0.2 us.
  - The only files containing `ER`/`EC` were copies of the spec's examples.
  - Real PCAN-View 5.x captures carry `ST` lines.
  - No public file had real error frames or counter records, which is why the bench made its own.

## The bench traces

**Classic channel, 6c** (`reader-bench_20261031T0116/`, P0 + C0-C5):

- TRC 1.1, containing `Error` lines and `Warng FFFFFFFF` lines (BUSHEAVY 08, BUSOFF 18).
- There is no BUSPASSIVE line and no return-to-OK line.
- canbench reads 12/12 traces the same as python-can's rows from the same PCAN.

**FD channel, rerun** (`reader-bench-fd_20261031T0952/`):

- Setup: p0_single, with the PCAN opened as an FD channel at 80 MHz, nominal 500k.
- TRC 2.0, `$COLUMNS=N,O,T,I,d,L,D`: 1,002 `DT`, 8,585 `ER` (type 02: 8,309, type 04: 276),
  4 `ST`, 64 `EC`.
- canbench: PASS. Rx frames are identical to python-can's rows, apart from 2 extra python-can
  rows with id 0x001, DLC 4, all zero, which are not in the trace (unexplained).
- The 276 python-can error rows equal the 276 type-04 `ER` records in order. Over FD,
  python-can delivered none of the type-02 records.
- python-can's direction byte is 00 where the trace has 01. In the classic run, both had 01.
- `ST` lines: `00 00 00 08`, `00 04 00 08` (passive) and `00 00 00 00` (OK). The 1.1 trace had
  neither the passive nor the OK state.

**PEAK-Converter outputs** (each source's `converted/` folder; `converted_readback.txt`):

- canbench reads 5/5 outputs with frames identical to the source and one event out for each
  event in.
- The converter maps:
  - 1.1 `Error` type n to `ER`, with the type as byte 0;
  - 1.1 `Error 0000` to `EC`, keeping all 4 bytes;
  - `Warng` to `ST`, with the same bytes.
- **Native 2.0 `EC` (4 bytes) to 2.1 / 1.1: only the first 2 bytes are kept**, in all 64 records.
  See below.
- It leaves `$STARTTIME` unchanged. Its 2.0 output writes a lowercase `l` in `$COLUMNS`.

## `EC`: the spec says 2 bytes, PCAN-Basic writes 4

**The spec** describes `EC` as 2 bytes, RX then TX, in three places:

- its "Error Counter Change" section (p. 15): "Error Counter Change entries have 2 data bytes.
  Data Byte 0: RX Error Counter ... Data Byte 1: TX Error Counter";
- its 2.0 column description;
- its 2.0, 2.1 and 3.0 examples (`EC  Rx  02 02`).

The 1.x `Error` record has no counter-change form. Its type is 1, 2, 4 or 8, followed by 4 bytes:
direction, position, RX, TX.

**PCAN-Basic's API** documents its error-frame message
([PCAN-Basic docs, "Error Frames"](https://www.peak-system.com/documentation/API/PCAN-Basic.Net/html/d8b8c576-cc90-4757-a914-4a503f9553d1.htm)).
The fields come from SJA1000 registers:

| Field | Register | Meaning |
|---|---|---|
| ID | ECC bits 6-7 | 0: "Only updated error counter values"; 1 bit, 2 form, 4 stuff, 8 other |
| DATA[0] | ECC bit 5 (DIR) | 0 error during transmission, 1 during reception |
| DATA[1] | ECC bits 0-4 | bit-stream position (2-28) |
| DATA[2] | RXERR | receive error counter |
| DATA[3] | TXERR | transmit error counter |

**What PCAN-Basic 5.0.0.1115 writes** for a counter decrease is that 4-byte body:

- in 1.1: `Error  0000  4  00 00 7F 00`, with type 0, which the trace spec does not list;
- in native 2.0: `EC  Rx  01 00 7F 00`, a 4-byte record where the spec defines 2 bytes.

**The bench data agrees with the API layout:**

- In C4 (1.1), byte 3 falls while byte 2 holds: `00 00 11 27`, `11 26`, `11 25`. Byte 3 is TX.
- In the other 1.1 runs, byte 2 falls with byte 3 at 00 (`7F`, `7E`, `7D`). Byte 2 is RX.
- In the FD trace, the last `ER` before the counter records reads RX 0x88, TX 0. The `EC`s then
  run byte 2 = 7F, 7E, ... down to 02, with byte 3 = 00.

**Hypothesis (owner reviewed 2026-10-31):** PCAN-Basic's trace writer copies the API's ID-0
error-frame message straight into the file without reformatting it to the spec's `EC` layout. The
4-byte layout itself (direction, position, RX, TX) is documented by PEAK's API, and the counter
movement confirms it. That the writer is the cause is inferred from the shapes; PEAK states it
nowhere we found.

- Byte 0 is 00 in the 1.1 traces and 01 in the FD 2.0 trace. In a counter-only message the
  direction bit may carry no meaning. Unexplained.
- **PEAK-Converter follows the spec.** Given PCAN-Basic's 4-byte `EC`, it keeps bytes 0-1, which
  are direction and position, and drops the counters. Given 1.1 `Error 0000`, it keeps all 4 bytes
  and so writes a non-spec `EC` itself. Its manual (1.0.3, 2026-06-17) does not describe `EC` data,
  and its error-frame table lists only types 1/2/4/8.
- **Precedent:** PCAN-Basic's trace output of error frames in 2.0 has had bugs before:
  - Windows 4.5.4 (2021-04-28): "Error frames were not written correctly into trace files using
    trace file format 2.0"
    ([version history](https://www.peak-system.com/support/software-information/development-kits/pcan-basic/));
  - Linux 4.9.0 (2024-10-21): "error frames data were formatted using TRC_v1.1 instead of
    TRC_v2.0"
    ([Linux version history](https://www.peak-system.com/support/software-information/development-kits/pcan-basic-linux/)).

  No public report of the 4-byte `EC` was found.

**For a reader:**

- To get counters from `EC`, take bytes 0/1 when it is 2 bytes long (spec) and bytes 2/3 when it
  is 4 bytes long (PCAN-Basic).
- A 2-byte `EC` produced by PEAK-Converter from PCAN-Basic's 2.0 holds direction and position, not
  counters. That is a lossy conversion, and the reader cannot detect it.
- canbench reports `EC` bytes as written and does not decode counters.

**For a writer** (the Android loggers' TRC work, Change 13): writing `EC` to the spec, as 2 bytes
RX then TX, is the only form PEAK-Converter handles correctly.

## `$STARTTIME`: 14 h off in PCAN-Basic 5.0.0

Both the 1.1 and the 2.0 traces from PCAN-Basic 5.0.0.1115, on a machine at UTC-7, carry
`$STARTTIME` = local time minus 7 h (UTC minus 14 h), in whole seconds. The `Start time:` comment
line has the correct local time to the millisecond. PEAK-Converter leaves the value unchanged.

PCAN-Basic **5.0.1 (2026-03-31)** lists the fix "The conversion of the STARTTIME value in
generated PCAN trace files did not take time zones into account"
([version history](https://www.peak-system.com/support/software-information/development-kits/pcan-basic/)).
**Hypothesis (owner reviewed 2026-10-31):** this is the bug we measured. That is unconfirmed until
a 5.0.1 trace is read. Recorded in can-tools' `parsers.md`.

## Third-party readers

- python-can's TRC reader
  ([`can/io/trc.py`](https://python-can.readthedocs.io/en/main/_modules/can/io/trc.html)) drops
  `ER`/`EC`/`ST`/`Error` lines in 1.1 and 2.x with an info log, and its writer refuses error
  frames, so it is no reference for these records.
- A community 1.x analyser
  ([pcan-view-trace-error-analyzer](https://github.com/matthiasbock/pcan-view-trace-error-analyzer/blob/master/analyze.py))
  reads `Error` lines with byte 2 as RX and byte 3 as TX, the same as the API layout.
