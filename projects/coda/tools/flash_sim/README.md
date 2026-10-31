# Coda DLCM flash simulators

Two endpoint simulators that speak the Coda DLCM UDS reflash protocol to each
other over a CAN bus. Built to let us develop and validate a laptop-driven
flasher **without** the real Omitec scanner or the real car in the loop, and
without the Omitec's slow ~54-minute cadence.

- **`gateway_sim.py`** — the ECU side. Pretends to be the vehicle Gateway/DLCM:
  reassembles the tester's ISO-TP requests on `0x7E0`, answers on `0x7E8`
  exactly as the real DLCM did, and imposes the real ECU delays.
- **`omitec_sim.py`** — the tester side. Drives the full flash sequence
  (session, security, erase, download, verify) over the real `coda_dlcm_prog.bin`
  and `coda_dlcm_cal.bin`, and can patch CAL bytes in flight.

Both connect through a shared transport. By default that is a **localhost
virtual bus** (python-can's `udp_multicast` backend — no hardware, no admin
rights); the same code drives a real dongle with `--transport ixxat|kvaser|…`.

## Files

| File | What |
|------|------|
| `isotp.py` | Minimal ISO-TP (ISO 15765-2) transport over any python-can `Bus`: SF / FF+CF / flow control. One `IsoTpEndpoint` both sends and receives full UDS payloads, and hands non-reflash frames to an `oob_handler`. |
| `uds.py` | UDS service-ID and NRC constants + small helpers (`describe`, `is_response_pending`, …). |
| `bus.py` | Bus factory: `virtual` (udp_multicast) or a real dongle brand via `canbench.live.receiver`. Shared `--transport/--channel/--port/--bitrate` args. |
| `timing.py` | The measured DLCM timing profile (see below), in one place. |
| `oob.py` | Out-of-band responder: answers the Omitec's ignition/keepalive poll (`0x710`→`0x718`) and handles functional broadcasts, so a real Omitec keeps the flash alive. See "Out-of-band traffic" below. |
| `gateway_sim.py` | ECU/DLCM simulator (main). |
| `omitec_sim.py` | Omitec tester simulator (main). |
| `seedkey.py` | DLCM SecurityAccess seed -> key: a 48-round LFSR (taps 4/11/20/29) keyed by a per-level constant. `0xCAF77776` for levels 01/02 (the flash-time handshake), `0x9D89EA36` for 03/04. Reproduces all 13 captured pairs; run it directly for the self-test. |
| `busload.py` | Bus-load governor. Meters every frame we transmit so the flash leaves headroom for real vehicle traffic. |
| `traffic_gen.py` | Synthetic periodic D CAN traffic at a requested utilisation, so the governor can be tested under load. |

## Quick start (localhost virtual bus)

Two terminals, from the repo root. Start the gateway first.

```bash
# terminal 1 — the ECU. --time-scale compresses the multi-second erase delays.
py -3.12 projects/coda/tools/flash_sim/gateway_sim.py --time-scale 0.02 --verify-bins

# terminal 2 — the tester. --max-blocks makes a quick smoke test.
py -3.12 projects/coda/tools/flash_sim/omitec_sim.py --max-blocks 20
```

For a full run (transfers the entire PROG + CAL), drop `--max-blocks`. With
`--verify-bins` the gateway checks each received segment byte-exact against the
real `.bin` files. A validated full run reports:

```
gw: VERIFY OK: segment 0x80040000 byte-exact vs coda_dlcm_prog.bin (1834496 bytes)
gw: VERIFY OK: segment 0xA0020000 byte-exact vs coda_dlcm_cal.bin  (114688 bytes)
```

**One gateway at a time.** Both endpoints share the multicast group, so two
running gateways both answer every request and desync the tester. Use a distinct
`--port` per concurrent test, and stop the gateway when done.

## Flashing a named CAL image to the car

The human-facing flash is `../flash_cal.py`: it chooses a named
complete CAL image and the real-flash settings, and drives `OmitecSim` from this
folder unchanged except for its `whole_image` option. `OmitecSim(whole_image=name)`
makes the base-coverage check report how many bytes change against the on-car
reference instead of refusing, because a complete image is meant to put back any
byte the car has and the image does not.

## Patching CAL in flight

`omitec_sim.py` can modify flash bytes by address before sending — the same
patch model as `../../notes/dlcm/dlcm_flash_proxy.py`, but originated by the tester rather
than a man-in-the-middle. This is the on-ramp to flashing a modified binary
directly from a laptop.

```bash
py -3.12 .../omitec_sim.py --segments cal \
    --patch 0xA0021532=05,00 --patch 0xA0021B6E=05,00
```

The DLCM flash script's modifications are folded in as the named preset
`--preset vcurve-lash-5` (matching `../../notes/dlcm/dlcm_flash_proxy.py` DEFAULT_PATCHES):

```bash
py -3.12 .../omitec_sim.py --preset vcurve-lash-5     # full patched flash
```

Against `--verify-bins`, the gateway lists every differing byte, confirming the
patch lands at exactly the intended flash addresses (`0xA0021532`, `0xA0021B6E`:
`0x01 -> 0x05`) with no other byte changed, and PROG byte-exact.

## Verifying the man-in-the-middle proxy sim-to-sim

`../../notes/dlcm/dlcm_flash_proxy.py` is the real-hardware MITM: it bridges the Omitec and the
Gateway on two physical dongles and patches CAL in flight. It can be exercised
end-to-end with **no hardware** by running both sims and bridging them with the
proxy's `virtual` transport (validated 2026-07-21):

```bash
# terminal 1 -- the ECU, on its own multicast group
py -3.12 projects/coda/tools/flash_sim/gateway_sim.py \
    --transport virtual --channel 239.0.0.2 --port 43113 --time-scale 0.05 --verify-bins

# terminal 2 -- the proxy, bridging the two segments (default patches = vcurve-lash-5)
py -3.12 projects/coda/notes/dlcm/dlcm_flash_proxy.py --transport virtual

# terminal 3 -- the tester, on the other multicast group
py -3.12 projects/coda/tools/flash_sim/omitec_sim.py \
    --transport virtual --channel 239.0.0.1 --port 43113 --startup-delay 2
```

The proxy's two virtual segments are separate buses (Omitec `239.0.0.1`, Gateway
`239.0.0.2`); the sims join the matching group. A full patched run reports PROG
byte-exact and CAL differing at exactly `0xA0021532`/`0xA0021B6E` (`0x01->0x05`),
and the proxy logs its patch hits plus `downloads=2 (matching=1)` (CAL covers the
patch region, PROG does not).

**Why a separate echo-suppressor is needed on the virtual transport.** python-can's
`udp_multicast` backend does **not** honor `receive_own_messages`: a socket always
receives its own transmitted frames (multicast loopback). The sims tolerate this
because they filter by arbitration ID, but the proxy forwards *every* frame, so
each frame it emits echoes back on the same socket and gets re-forwarded to the
other segment -- an infinite bridge loop / broadcast storm (the ECU even sees its
own responses come back, and ISO-TP desyncs into garbage). The proxy's
`EchoSuppressor` records each frame it sends onto a segment and drops the
byte-identical loopback when it reads that segment. It engages **only** on the
virtual transport; real dongles honor `receive_own_messages`, so nothing changes
on the hardware path. This loopback is a virtual-bus artifact only -- it does not
occur on two real physical buses. (udp_multicast isolation itself is fine:
verified cross-process that it separates by both port and group.)

## Protocol and timing (grounded in the real capture)

Everything the simulators do on the **happy path** is taken from
`../../notes/dlcm/coda_dlcm_flash6.log`, a complete 54m27s passive capture of a real Omitec
reflash. Because CAN is a shared broadcast bus, that single passive tap captured
**both** sides of the two-node conversation in full; direction is unambiguous
(request SIDs only on `0x7E0`, response SIDs + flow control only on `0x7E8`,
proven by ISO-TP flow-control reciprocity). The extraction script is
`../../notes/dlcm/artifacts/flash_timing_profile.py`.

Flash sequence (per segment: PROG at `0x80040000`, then CAL at `0xA0020000`):
DiagSession → identification reads → programming session → SecurityAccess
(seed/key) → RoutineControl `0xFF00` erase → RequestDownload → TransferData
loop (252 data bytes/block) → RequestTransferExit → RoutineControl `0xFF01`
verify.

Measured ECU timing reproduced by `gateway_sim.py`:

| Event | Real value | Notes |
|-------|-----------|-------|
| TransferData block accept (`36`→`76`) | ~7.4 ms mean (p99 16 ms) | the ECU is fast |
| RequestDownload (`34`→`74`) | ~7 ms | maxBlockLength `0x00FF` |
| PROG erase routine (`31 01 FF00 02`) | 36.5 s, 6 × `0x78` responsePending ~10.4 s apart | the slow step |
| CAL erase (`31 01 FF00 03`) | 2.7 s | |
| verify (`31 01 FF01`) | 2.4 s | |

**Key finding:** the real log's ~217 ms per-block cadence is the *Omitec's* own
pacing, not the DLCM (which accepts a block in ~8 ms). `omitec_sim.py` defaults
to `--block-delay-ms 0` (flash as fast as the ECU allows); set `--block-delay-ms
217` to reproduce the real Omitec's slow cadence.

## Out-of-band traffic (beyond the `0x7E0`/`0x7E8` reflash)

A real Omitec does more than the reprogramming dialog: it continuously polls
vehicle state and probes other modules. If the gateway does not answer the
essential polls, a real Omitec treats the vehicle as absent / ignition-off and
aborts before or during the flash. Everything below is from the same capture
(extractor: `../../notes/dlcm/artifacts/out_of_band_traffic.py`).

| ID(s) | Traffic | Gateway sim behavior |
|-------|---------|----------------------|
| `0x710`→`0x718` | **Ignition / keepalive poll, entire session** (t=0…3258 s): req `22 64 01` (ReadDataByIdentifier DID `0x6401`), resp `62 64 01 <state>` (`03`=running, `00`=off). | **Answered** by `oob.py` (`--ignition 0x03`). This is the critical one. |
| `0x7DF` | Functional broadcast `10 82` / `11 81` — sub-function bit `0x80` = **suppressPositiveResponse**, so no reply expected. | Recognized and **ignored** (no response). |
| `0x734`, `0x758`, `0x7ED` | Other modules the Omitec probed pre-flash (their responses landed on the shared bus). Mostly negative responses; not the DLCM. | **Not emulated.** The CAN controller still ACKs these at the link layer, so an unanswered probe just times out on the Omitec (as if the module were absent) — it does **not** cause bus-off. |
| `0x591`, `0x592`, `0x603` | Late-session (post-flash) other-module chatter. | Not emulated. |

### Post-flash ignition power-cycle (finalization)

Validated against the real Omitec on 2026-07-20: after the last segment verify,
the Omitec finalizes by driving the ignition DID `0x6401` (read from the gateway
module, `0x710`/`0x718` -- **not** the DLCM) through a power-cycle:

```
OFF (0x00) -> ON (0x03) -> OFF (0x00) -> ON (0x03) -> "re-flash complete"
```

It sends **nothing but ignition polls** during this phase (no version read-back,
no checksum routine), and the poll is byte-identical whether it wants OFF or ON,
so the ECU side is blind to the current step. `gateway_sim.py` therefore plays
this as a **timed sequence** (`FINALIZATION_SEQUENCE`), armed only once a real
download has completed (`>=1` TransferExit) and flashing has been idle for
`--finalize-grace` seconds, holding each state `--finalize-dwell` seconds (default
15 s, comfortably longer than the Omitec's observed ~10 s per-step wait --
over-holding just makes it wait, under-holding makes it miss a step), then
latching ON. Disable with `--no-auto-finalize`. `--ignition-file <path>` (re-read
each poll) overrides the whole thing for manual control/recovery.

The `coda_fake_car.py` vehicle simulator in `../../coda-diagnostics/playback/`
independently confirms the `0x710`→`0x718` ignition responder and emulates the
other modules (ABS `0x784`, BMS `0x722`, airbag `0x7C4`, HVAC `0x750`, AC
`0x7C7`) for the DTC-reading workflow. If a real-Omitec flash test (step 2)
shows the DLCM flash needs any of those modules present, add a responder to
`oob.py`'s `MODULE_RESPONDERS` table (or reuse `coda_fake_car.py`'s encoders).

`omitec_sim.py` reproduces the ignition poll itself (`--ignition-poll-interval`,
on its own bus socket) so the sim-to-sim run exercises the gateway's out-of-band
path. It also honors `suppressPositiveResponse` on `0x7E0` sub-function services.

### PCAN bus-off caution (real-dongle runs only)

The reason the out-of-band handling matters showed up as an apparent "PCAN bug"
(see `canbench/live/pcan-busoff-recovery.md` in the can-tools git clone, `tools-reference.md` "can-tools"): transmitting UDS
requests onto a bus where **nothing ACKs** (e.g. the proxy not forwarding, or no
ECU/simulator connected) latches a PCAN adapter into bus-off after ~32 frames.
With `gateway_sim.py` connected and answering, every frame is ACKed and the
polls are satisfied, so this does not occur. When driving a real Omitec against
the gateway sim over a PCAN dongle, open the bus with `auto_reset=True` per that
note.

## What is NOT grounded (designed, not observed)

A passive capture only shows how the ECU reacted to what the Omitec actually
did. The **error/negative paths** in `gateway_sim.py` — wrong block-sequence
counter, wrong key, out-of-range address, unsupported service — are designed
from the UDS spec, not observed. Validating them against the real ECU's actual
behavior is the purpose of the later step: flashing `gateway_sim.py` with the
real Omitec. Likewise the DLCM's seed→key algorithm is unknown; for sim-to-sim
the gateway returns the captured seed and accepts the captured key.

## Transports

| `--transport` | Meaning |
|---------------|---------|
| `virtual` (default) | localhost `udp_multicast`; `--channel` = group IP (default `239.0.0.1`), `--port` (default `43113`) |
| `ixxat` / `kvaser` / `pcan` / `socketcan` / `gs_usb` | real dongle, channel auto-detected via `canbench.live.receiver`; `--bitrate` (default 500000) |

## Roadmap (this folder is step 1)

1. **[done]** Sim-to-sim over the localhost virtual bus: `omitec_sim.py` flashes
   `gateway_sim.py` byte-exact, with realistic ECU timing.
2. **[done 2026-07-20]** Flashed `gateway_sim.py` with the **real Omitec** over a
   PCAN dongle, end to end: full handshake, seed/key match (`7c876e19`->`2726966f`),
   PROG + CAL transferred and **verified byte-exact** (~27 min PROG download at the
   Omitec's ~4.4 blocks/s), and the post-flash ignition power-cycle -> "re-flash
   complete". Two real bugs found and fixed here: the erase-routine `responsePending`
   P2 timing (first pending must be immediate, not after the pending interval) and
   the missing bus terminator (unterminated bench bus = 100% error frames). The
   only diagnostic traffic the Omitec sent post-flash was the ignition poll.
3. **[done 2026-07-20]** Validated `omitec_sim.py` by flashing the real-Omitec-
   validated `gateway_sim.py`: full 7,736-block flash, both segments byte-exact,
   realistic 36.5 s erase tolerated, finalization observed. Full flash in ~2.6 min
   (67.5 blocks/s) vs the real Omitec's ~28 min -- previewing step 4.
4. **[sim-validated 2026-07-20]** DLCM CAL patches folded in as
   `--preset vcurve-lash-5`; a full patched flash against `gateway_sim.py`
   verified PROG byte-exact and CAL changed at exactly `0xA0021532`/`0xA0021B6E`
   (`0x01->0x05`) with no other byte touched. **Remaining:** point
   `omitec_sim.py --transport pcan --preset vcurve-lash-5` at the real DLCM for
   the laptop-direct flash (do the Omitec reconfirm run first).
5. **[sim-validated 2026-07-21]** The MITM proxy (`../../notes/dlcm/dlcm_flash_proxy.py`) was
   verified sim-to-sim over the new `--transport virtual` mode: `omitec_sim.py`
   -> proxy -> `gateway_sim.py`, full 7,736-block patched flash, PROG byte-exact
   and CAL patched at exactly the two addresses with no other byte changed. Found
   and fixed a virtual-transport frame-storm loop (udp_multicast loopback; see
   above).
6. **[done 2026-07-21]** Ran the proxy MITM between the **real Omitec and the real
   DLCM** (`--omitec-brand pcan --gateway-brand kvaser`, default `vcurve-lash-5`
   patches) for the live in-flight patched reflash of the actual vehicle ECU.
   Result: PROG (`0x80040000`, 7280 blocks) forwarded byte-exact and correctly
   detected as outside the patch region; CAL (`0xA0020000`, 456 blocks) patched in
   flight -- `0xA0021532` and `0xA0021B6E` `0x01->0x05` (`applied=4`,
   `downloads=2 matching=1`), landing near the start of the CAL stream
   (block_seq `0x16`/`0x1C`). Bridge stayed clean the whole ~30-min transfer
   (`rx==tx` both directions, `echo=0`, zero bus errors through completion). The
   Omitec reported success and ran its post-flash ignition power-cycle
   (`OFF->ON->OFF->ON`) with **no DTCs**. (The Kvaser `canReadWait` hardware
   errors in the proxy log after 22:08 are post-completion link-loss once the
   bench bus was powered down -- ~14 min after the flash finished, counts long
   frozen; benign.) Log: `../../notes/dlcm/artifacts/proxy_real_flash_20260721.log`.
   **Cycle timing (real Omitec):** ~15 min local pre-parse (little bus traffic)
   + ~28 min PROG transfer + ~2 min CAL = ~45 min total.

**Seed guard (real-hardware safety):** `omitec_sim.py` only knows the key
(`2726966f`) for the captured seed (`7c876e19`), which the real DLCM returned
every session. If the ECU hands back any other seed it **aborts before any
erase/download** (`SAFETY ABORT`, ECU untouched) rather than send a wrong key --
the DLCM seed->key algorithm is not implemented. Override with
`--allow-unknown-seed` (unsafe). The gateway's returned seed can be changed for
testing with `gateway_sim.py --seed <hex>`.


## Security access is no longer a blocker

`omitec_sim.py` used to hold one captured (seed, key) pair and abort on any other
seed, because the DLCM's algorithm was unknown. It is now implemented in
`seedkey.py` and the flasher computes the key for whatever seed the ECU offers.
The captured pair is retained as a regression check: if the computed key ever
disagrees with it for that seed, the run aborts before any erase or download.

`--security-level` picks the requestSeed subfunction (default `0x01`, the
programming-session level a flash needs).

**Never exercised on the car.** Every live unlock so far was level 03/04 in an
extended session. `../../notes/dlcm/artifacts/dlcm_unlock_probe.py` is the cheap way to settle
level 01/02: session, seed, compute, key, report, back to the default session --
no erase, no download, no write.

## Bus-load throttling

The Omitec runs at 4.6 TransferData blocks/s and uses ~8 % of the bus, but 92 %
of that cadence is the tool idling (160.7 ms between blocks, plus 1.10 ms between
consecutive frames although the ECU's flow control asks for STmin=0). Our own
tester has no reason to idle, and unthrottled it would take essentially the whole
bus. Ordinary D CAN traffic on this vehicle measures **32-39 %** utilisation, and
the flash shares that segment.

So every transmitted frame is metered through `busload.py`:

```
--bus-ceiling   max TOTAL utilisation, ours + everyone else's   (default 0.70)
--bus-max-own   hard cap on OUR share even on a silent bus      (default 0.45)
--bus-window    averaging window in seconds                     (default 0.5)
--bus-ceiling 0 disables throttling entirely
```

The budget is `min(max_own, ceiling - observed_foreign)`. Foreign traffic is
anything we did not transmit, the ECU's own replies included: we cannot throttle
those, but they occupy the bus, so they count against the ceiling rather than
against our share.

At the default ceiling with 35 % vehicle traffic this yields ~33.5 blocks/s, i.e.
**about 4 minutes for a full PROG+CAL flash** against the Omitec's 54-80.

Tests: `../../notes/dlcm/artifacts/busload_governor_test.py` (virtual clock, exact) and
`../../notes/dlcm/artifacts/flash_throttle_integration_test.py` (end to end, real sockets).

### The virtual bus tops out around a third of a real CAN bus

Measured 2026-09-20: a bare python-can `udp_multicast` `recv()` loop drains
**1313 frames/s**. A real 500 kbps bus carries ~3600 8-byte frames/s, and 35 %
of it is 1268 frames/s -- so a simulator process is already at its ceiling doing
nothing but receiving, with nothing left for ISO-TP reassembly, dispatch or its
own transmissions.

Consequently **the sims cannot run a flash against a realistically busy bus**,
with or without throttling (verified: identical failure with `--bus-ceiling 0`).
The integration test therefore exercises the governor's adaptive branch by
lowering the *ceiling* rather than raising the load, which reaches the same
arithmetic at a frame rate this transport can carry; the high-load cases live in
the virtual-clock test, which no transport bounds. This is a limitation of the
bench, not of the flasher, and it does not apply to real silicon.

One related trap: **do not enlarge the receive buffer here.**
`projects/vtrux/tools/interposer/bus.py` does, correctly -- it forwards every
frame and must not miss one. These simulators filter almost everything out and
can fall behind, and the right kernel behaviour for them is to drop what they
were never going to read. `bus.py` explains the asymmetry at the call site.
