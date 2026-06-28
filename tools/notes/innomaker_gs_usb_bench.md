# Innomaker USB2CAN (gs_usb) bench findings

Back-to-back bench test of the **Innomaker USB2CAN** (gs_usb / candleLight
firmware) against a **Kvaser Leaf Light v2** (trusted reference), wired
CAN-H/CAN-L together with a single 120R terminator, both at **500 kbit/s** on
the bench PC. Goal: confirm the Innomaker can carry live full-rate vehicle
traffic without dropping frames.

Harness: `tools/artifacts/innomaker_bench.py` (`sanity` / `rx` / `tx` / `all`,
plus a `speed` arg: `1.0` = real-time, `0` = flood/as-fast-as-possible). Raw
output in `tools/artifacts/innomaker_flood_rx_v3.txt`,
`innomaker_bench_results.txt`, etc. Setup/driver details: the device needs no vendor driver on Windows (WinUSB auto-binds via WCID descriptors).

## Stimulus

`projects/vtrux/logs/debuglog_M0_T0.log` — single bus, **628,075 frames**,
270.4 s, **2,323 fps average** (~5% are 29-bit extended IDs). This is one of the
captures that historically overran the ixxat buffers.

## Theoretical 500k bus ceiling for this frame mix

Computed from the log's actual DLC distribution (classic CAN, 11-bit frames):

| Stuffing assumption | avg bits/frame | 500k bus max |
|---|---|---|
| no stuffing (upper bound) | 103.2 | ~4,846 fps |
| worst-case stuffing (lower bound) | 125.2 | ~3,993 fps |

So a saturated 500k bus for this traffic sits in the **~3,990–4,850 fps** band.

## Results

### Real-time replay (speed 1.0) — reproduces the live vehicle rate

| Direction | TX sent | RX received | Drops | Send errors | Integrity | Kept real-time |
|---|---|---|---|---|---|---|
| Kvaser TX -> **Innomaker RX** | 628,075 | 628,075 | **0** | - | 0 missing / 0 extra | yes |
| **Innomaker TX** -> Kvaser RX | 628,075 | 628,075 | **0** | 0 | 0 missing / 0 extra | yes |

Zero loss both directions on the exact workload that overran the ixxat.
(Because Python `time.sleep` can't honor sub-ms gaps, dense bursts were
replayed back-to-back, i.e. *faster* than the recorded spacing, and still
landed with zero loss.)

### Flood / saturation (speed 0)

| Direction | TX sent | TX errors | achieved | RX received | Drops |
|---|---|---|---|---|---|
| **Innomaker TX** -> Kvaser RX | 628,075 | 0 | **4,489 fps** | 628,075 | **0** |
| Kvaser TX -> **Innomaker RX** (valid run) | 628,075 | 0 | **4,212 fps** | 627,658 | **417 (0.066%)** |

- **Innomaker TX** cleanly saturates the bus (4,489 fps, in the theoretical
  band) with zero send-errors and zero loss on the Kvaser RX side. gs_usb
  `send()` blocks until the frame is queued in the MCU, so it self-paces to bus
  rate and never overflows.
- **Innomaker RX** at *sustained* saturation (4,212 fps) drops a small
  fraction: **417 / 628,075 = 0.066%**. The gs_usb backend reads one frame per
  USB bulk transfer, which is the mechanism behind the rare drops once the bus
  has no idle gaps to let the host catch up.

## Ruling out the Kvaser as the limiting factor

The flood RX test only stresses the Innomaker RX if the Kvaser TX actually
saturates the bus. Two earlier attempts did **not**, and are recorded so the
trap is not repeated:

| TX send mode | Kvaser behaviour | achieved | Verdict |
|---|---|---|---|
| non-blocking, no retry | TX queue overflows: **562,631 send-errors**, only ~65k frames actually sent in bursts | 4,231 fps of *attempts* | invalid — Kvaser-limited, chaotic |
| blocking `send(timeout=1.0)` | `canWriteWait` waits for each frame to transmit (a USB round-trip per frame) | **988 fps** | invalid — Kvaser-serialized |
| **non-blocking + tight retry (no sleep)** | TX queue stays full, bus drains at line rate; any `sleep` here hits Windows' ~1 ms timer and re-caps at ~1,000 fps, so the retry must spin | **4,212 fps** | **valid — bus-saturated** |

The valid run's 4,212 fps lands inside the 3,990–4,850 fps theoretical ceiling,
so the bus was saturated and the **Kvaser was not the limiter**. The 0.066% RX
loss is therefore a genuine Innomaker RX characteristic at sustained
saturation. (The "11% drop" seen in the first, overflowing attempt was an
artifact of the Kvaser TX churn, not real RX loss — the valid run shows 0.066%.)

## Conclusion

- **At real vehicle rates** (2,323 fps average, with the idle gaps a real bus
  has): **zero loss**, both TX and RX. The Innomaker is suitable for live
  full-rate 500k vehicle logging.
- **At sustained full 500k saturation** (no idle gaps — harsher than a real
  vehicle bus): Innomaker **TX is loss-free**; Innomaker **RX drops ~0.066%**.
  Expect occasional RX drops only under sustained saturation.

## End-to-end functional check (coda-diagnostics)

The `coda-diagnostics` submodule was given gs_usb support.
Verified on the same bench by running `playback/coda_fake_car.py` on the Kvaser
(simulated Coda, BMS DTCs `P1B1D`/`P1B1E`) while `read_dtcs_coda.py` ran over the
auto-detected Innomaker: it read back both BMS DTCs via a multi-frame ISO-TP
exchange, confirming gs_usb TX+RX (incl. flow-control) work for real UDS
traffic. Validation harness: `tools/artifacts/coda_gs_usb_test.py`.
