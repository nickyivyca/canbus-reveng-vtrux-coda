# Coda BMS ECU — Firmware Decompile Notes

> ## SAFETY — `10 03` ON THE BMS DROPS THE HV CONTACTORS
>
> Observed on the car 2026-09-24 by the in-car session. Entering the **extended
> diagnostic session** on this module is by itself a **vehicle state change**: the HV
> contactors open. It recovers fully on a key cycle, and the user accepted it for that
> test, but nobody should repeat it unaware.
>
> The lesson generalises and is worth carrying to other modules: **"read-only" scoped by
> UDS service is the wrong boundary.** The probe that caused this had a unit-tested
> allow-list that refused all nine write-capable services before transmission, and the car
> still reconfigured itself. Session control is not an observation.

## Binary Provenance

| Item | Value |
|------|-------|
| Source log | `projects/coda/logs/flash/coda_bms_flash.log` |
| Capture date | 2026-04-25 |
| Tool | Omitec scanner, BUSMASTER 500 kbps |
| Extracted binary | `projects/coda/notes/artifacts/coda_bms.bin` |
| Binary size | 249,856 bytes (0x3D000) |
| Extractor script | `projects/coda/notes/artifacts/extract_bms_firmware.py` |

## UDS Flash Session Summary

- **Tester**: 0x722 (Omitec scanner)
- **ECU**: 0x72A (BMS)
- **Session**: DiagnosticSessionControl → Programming (0x02)
- **SecurityAccess**: Level 0x03/0x04, seed/key challenge — **algorithm now solved**, see
  "SecurityAccess: SOLVED" below
- **Observed pair**: seed `4B BF 7E 4B` → key `35 2D 85 E2`
- **RequestDownload**: address 0x00000000, size 0x3D000, dataFormatIdentifier 0x00 (declares no compression/encryption)
- **Transfer**: 1116 blocks × up to 224 data bytes = 249,856 bytes exact
- **TransferExit response**: `77 00 FF C2 9F`

Block counter wraps at 0xFF. Last block is sequence counter 0x5C (1116 mod 256 = 92 = 0x5C) with 96 data bytes. Zero-byte discrepancy between declared size and extracted data.

## Encryption Finding

The binary is **encrypted**. Despite the UDS RequestDownload declaring `dataFormatIdentifier=0x00` (no compression, no encryption), the extracted image has near-maximum Shannon entropy.

| Binary | Size | Entropy | Assessment |
|--------|------|---------|------------|
| `coda_gateway.bin` | 90,112 bytes | 4.95 bits | Plaintext ARM firmware |
| `coda_bms.bin` | 249,856 bytes | **7.9992 bits** | Encrypted (AES-class) |

Maximum possible entropy for a byte stream is 8.0 bits. A value of 7.9992 indicates uniform byte distribution with no structure.

249,856 bytes is evenly divisible by 16: 249,856 / 16 = 15,616 blocks exactly.

**Re-measured 2026-09-24 with ISA-agnostic metrics.** The original assessment leaned on
"no recognizable ARM instruction patterns", which presumes a core we have never confirmed.
The BMS core has never been identified: the ARM7TDMI-S guess elsewhere in this project is
an *inference from the gateway*, which is a different module, and nothing has been observed
on the BMS itself. The tests were therefore redone so that none of them assumes an
instruction set, endianness or vector-table shape, each calibrated against known-plaintext
controls:

| Image | entropy | chi2 vs uniform | top byte | longest run | repeated 4-grams | zlib ratio |
|---|---|---|---|---|---|---|
| `coda_gateway.bin` (plaintext fw) | 4.9461 | 2,926,916 | FF 33.4% | 27,720 | 0.675 | 0.361 |
| DLCM CAL (plaintext, TriCore) | 0.7562 | 25,612,023 | 00 93.6% | 96,228 | 0.972 | 0.029 |
| `os.urandom` of equal length | 7.9992 | 264 | 0.42% | 3 | 0.000 | 1.000 |
| **`coda_bms.bin`** | **7.9992** | **282** | **0.43%** | **3** | **0.000** | **1.000** |

`coda_bms.bin` is statistically indistinguishable from random on every measure that does
not depend on the ISA. It also has **zero duplicate 16-byte blocks** across all 15,616,
so it is not ECB mode over anything structured.

This strengthens the "encrypted" conclusion while removing its dependence on the ARM
assumption. It does **not** identify the cipher: "AES-class" remains a hypothesis, and
high-entropy output is equally consistent with compression or any strong stream cipher.

*Artifacts:* `artifacts/bms_security_vs_dlcm.py`, `..._out.txt`.

### ECB and short repeating XOR are excluded by measurement (2026-09-26)

Block repetition was measured against the two plaintext controls. ECB preserves plaintext
block repetition exactly, so an image with none cannot be ECB over anything resembling
firmware. The same argument at 4-gram granularity excludes a repeating XOR of short period.

| Image | dup 4-grams (unaligned) | dup 8-byte blocks | dup 16-byte blocks |
|---|---|---|---|
| `coda_bms.bin` | **8** / 249,853 | **0** / 31,232 | **0** / 15,616 |
| `coda_gateway.bin` (plaintext) | 56,075 / 90,109 | 4,463 / 11,264 | 1,909 / 5,632 |
| DLCM CAL (plaintext) | 111,486 / 114,685 | 13,588 / 14,336 | 6,630 / 7,168 |

The controls establish that the population is non-empty — 40% and 95% duplicate 8-byte
blocks respectively — so the BMS zero is a true negative and not an empty filter. The 8
duplicate 4-grams match the random birthday expectation almost exactly
(249,853^2 / 2^33 = 7.3), which is an independent confirmation that the image is random at
that granularity rather than merely unstructured.

**Conclusion: the cipher is a stream cipher or a chained block mode (CBC/CFB/OFB/CTR).**
This is a measurement, not an assumption, and it is what made the 2026-09-26 brute force
affordable.

## SecurityAccess Key vs Firmware Encryption Key

These are two separate secrets the Omitec tool manages:

- **SecurityAccess key**: computed from the ECU's live seed via a challenge-response
  algorithm. Authorizes the programming session. **SOLVED 2026-09-24** — see below.
- **Firmware encryption key**: used to encrypt the image before it is sent over UDS. A
  static secret per ECU type. Likely hardcoded in the Omitec tool or held in the BMS
  bootloader, not derived from the live seed.

Cracking the SecurityAccess algorithm does not yield the firmware encryption key. **This
was predicted here and has now been tested directly rather than assumed** — see "The
firmware encryption is not the SecurityAccess LFSR".

The structural argument is independent of the measurements: the DLCM holds *both* of its
SecurityAccess constants in its binary and still flashes entirely in the clear, so there
is no sibling firmware cipher in this module set to inherit. Seed/key authorises a
session; it does not encrypt an image.

## Paths to Decryption

**Priority reordered 2026-09-24.** Option numbers are kept stable for cross-references, but
the ranking was **3, then 2, then 1** — and after the 2026-09-24 probe closed the
extended-session route, it is now **2, then 3, then 1**. Option 1 was originally marked
"recommended" on the assumption that the SecurityAccess algorithm would have to come from
the tool binary too; it no longer does.

### Option 1 — Decompile the Omitec tool (largest effort; needs a binary we do not have)
The Omitec scanner is a Windows application. Its binary contains both the SecurityAccess key derivation function and the firmware encryption key for every supported ECU. Finding the BMS module handler in the tool binary would yield both. It remains the only
path that would hand over the key outright, but it depends on obtaining the tool binary.

*2026-09-26:* a former Coda engineer was contacted, and does not appear to still hold the
BMS update file. Neither the tool binary nor a plaintext image is currently obtainable from
that source.

**DOWNGRADED 2026-10-03.** The premise of this option — that the tool binary contains the
firmware encryption key — is now contradicted by the source. The scanner stores and
transmits ciphertext and the *bootloader* decrypts, so the tool is a courier holding a file
we already have. See "Where the key lives" below. This option retains value only for the
byte-for-byte comparison test described there, which would distinguish a fixed bootloader
key from per-car re-encryption.

### Option 2 — JTAG/SWD physical access
A direct flash dump bypasses UDS entirely and reads the unencrypted image the MCU actually
executes, independent of every unknown above. The BMS PCB has not been inspected for a
debug header. The BMS core is **unidentified** (see the Encryption Finding note), so the
debug interface and the tooling that fits it are an open question until someone looks at
the board.

### Option 3 — Bootloader read via UDS (**probed 2026-09-24; needs the programming session**)
The bootloader decrypts and verifies the application image, so it necessarily holds the
decryption routine and key material, and is necessarily plaintext. It is not in the
extracted image: the flash wrote the application to `0x00000000`, so the bootloader lives
in a region that was never transferred. `0x35` RequestUpload and `0x23` ReadMemoryByAddress were
attempted on 2026-09-24 and are **not implemented in the application** — see the section
below. Reaching the bootloader now requires the programming session, which raises the
priority of Option 2 relative to this one.

### Option 4 — SecurityAccess algorithm reverse — **DONE, and it does not help decrypt**
Superseded by "SecurityAccess: SOLVED" below. The estimate of ~15-20 pairs was based on
brute-forcing a catalogue of generic automotive algorithms; it was overtaken by the DLCM
result, which supplied the algorithm outright and reduced the problem to recovering one
constant. As predicted, it does not expose the firmware encryption key — but it does
enable unlock without the Omitec, which is what makes Option 3 testable.

## Current Status

*Updated 2026-10-03.*

- Binary extracted and verified: complete, no errors
- Ghidra analysis: **still blocked** — binary is encrypted; decompile not meaningful until
  decrypted. The 2026-09-24 work reinforced this dead end rather than opening it.
- SecurityAccess: **SOLVED** for level 01/02 (26 pairs); level 03/04 constant recovered
  from a single pair and **unconfirmed**
- SecurityAccess level 01/02: **CONFIRMED LIVE ON THE CAR**, twice, without the Omitec
- Firmware encryption: unbroken, and now shown **not** to be the SecurityAccess LFSR
- Omitec tool binary: not yet obtained
- `0x23` / `0x35`: **tried and closed** — not implemented on the BMS application; the
  gateway is excluded as the source of the malformed NRC
- Firmware encryption: the **four-digit passcode hypothesis is tested and closed** —
  ~765,800 decryption attempts, 0 hits, with a calibrated detector (2026-09-26)
- Cipher class: narrowed by measurement to a **stream cipher or chained block mode**;
  ECB and short repeating XOR are excluded
- Remaining routes to a decryptable image: programming-session access to the bootloader
  (heavier now that `10 03` is known to drop the contactors), JTAG, or the Omitec binary
- Known-plaintext route via the former engineer's update file: **not available** — he does
  not appear to still have it
- **Omitec route downgraded (2026-10-03):** the scanner carries ciphertext, not the key;
  the key is in the bootloader only
- **New untested path (2026-10-03):** CCP/XCP calibration slave, suggested by the module
  having been flashed with ETAS INCA in development. Probe written, not yet run
- Probe reachability settled: on the Diag CAN only `0x722`/`0x7DF` reach the BMS, but
  **B CAN and C CAN are directly accessible at the J1962** and bypass the gateway entirely

---

## SecurityAccess: SOLVED (2026-09-24)

The BMS uses **the same algorithm as the DLCM** — the 48-round Galois-style LFSR with taps
at bits 4/11/20/29, keyed by a constant that varies per (module, security level):

```
key = LFSR48(seed XOR constant)      # seed and key both big-endian on the wire
```

See `dlcm/dlcm-security-access.md` section 1c for the algorithm's recovery from the DLCM
binary. The BMS constants were recovered by inverting captured seed/key pairs.

| Level | Constant | Basis | Confidence |
|---|---|---|---|
| `01`/`02` | `0x3D700822` | 26 distinct captured pairs, 26/26 reproduce | **CONFIRMED** |
| `03`/`04` | `0x2E56D6B7` | 1 pair (the flash session) | **unconfirmed** |

The level-01 pairs came from `Diagnostic/logs/charger_*.txt` and `parts_wholescan_M0.txt`,
where the Omitec unlocks routinely before `2F 67 02` I/O control. 26 independent seeds
agreeing on one constant is ~2^-750 against coincidence.

### CONFIRMED LIVE ON THE CAR (2026-09-24)

The in-car session unlocked the BMS **without the Omitec**, twice, using an independent
reimplementation of the LFSR rather than importing `coda_security_access.py`:

| seed | our key | result |
|---|---|---|
| `25F04471` | `CD994F55` | `67 02` granted |
| (run 2) | `D61E9B0E` | `67 02` granted |

So `0x3D700822` is confirmed against the live module, not only against captures.

### Ordering requirement — `10 03` → `27 01` → `27 02` must be uninterrupted

Established the same session. A first attempt ran `10 03` → `23` → `35` → `27 01` →
`27 02` and was refused with **`7F 27 22` conditionsNotCorrect** — notably **not** `7F 27
35` invalidKey, so the key itself was never judged wrong. Mirroring the captured Omitec
ordering (`charger_readdtcs_master_M1.txt` lines 33-41: tester-present before the session,
then `10 03` → `27 01` → `27 02` back to back inside ~90 ms with nothing interleaved)
granted it. The two truncated probes in between were what broke it.

Treat the unlock as an atomic sequence: interleave nothing between the session request and
the key.

**The top two bits of every constant are unobservable and it does not matter.** Bits 30
and 31 of `seed XOR constant` are shifted out before they can reach any tap, so all four
candidates (`0x3D700822`, `0x7D700822`, `0xBD700822`, `0xFD700822`) compute identical
keys. Verified explicitly. The value above is usable as-is.

Method control: inverting the DLCM's own captured pairs recovers exactly the constants
that were independently read out of the DLCM binary, which validates the procedure.

A verified implementation with a regression test over every captured pair in the corpus
(31/31 across DLCM, BMS and Gateway) is in `artifacts/coda_security_access.py`.

*Artifacts:* `artifacts/harvest_seedkey_all_ecus.py`, `..._out.txt`,
`artifacts/coda_security_access.py`.

### Open question — what module is `0x722`/`0x72A`?

Every script in `projects/coda/Diagnostic/precursor/` (and in the public
`coda-diagnostics` repo) labels this pair **BMS**, and this file follows
that. But the 26 level-01 pairs come from captures the user describes as *charger* work,
and the unlock is followed by `2F 67 02` (IOControlByID on DID `0x6702`). Flagged as an
open labelling question, not resolved. Nothing here depends on the answer — the constant
belongs to whichever module answers on `0x72A`.

---

## The firmware encryption is not the SecurityAccess LFSR (2026-09-24)

Tested directly, in two escalating steps.

**Step 1 — the recovered constants as keystream seeds.** 56 instantiations of the LFSR
(word-at-a-time BE/LE at 1/32/48 clocks per word, byte-at-a-time, bitwise; seeded from the
seed, the key, both BMS constants, the Gateway constant and both DLCM constants), XORed
against the image. None produced structure: entropy stayed at ~7.997 and the zlib ratio at
1.000, against 0.361 for known-plaintext firmware.

**Step 2 — the LFSR under *any* key.** The stronger question, because a 32-bit linear
keystream is recoverable from ciphertext alone and no constant would be needed. Firmware
images contain long constant-padding runs, and across such a run the ciphertext *is* the
raw keystream. So every 4-byte-aligned window of the image was taken as a candidate LFSR
state, clocked forward, and scored on how far it predicts the image — three tap sets, both
byte orders, 1 and 32 clocks per word:

| | words predicted |
|---|---|
| `coda_bms.bin`, all 12 configurations, every offset | **0 / 8** |
| Control: a real keystream injected at `0x01000` | **8 / 8**, found immediately |

The detector demonstrably works and finds nothing. **The image is not XOR-masked with this
class of LFSR under any key**, so no SecurityAccess constant can decrypt it.

*Caveat:* the step-2 test needs at least 36 consecutive bytes of constant plaintext at
4-byte alignment somewhere in the image. Firmware essentially always has that, and the
round `0x3D000` size argues for a padded region, but that is the condition under which
the result holds.

*Artifacts:* `artifacts/bms_lfsr_keystream_exhaustive.py`, `..._out.txt`.

---

## The `0x35` / `0x23` bootloader path: tried, and closed (2026-09-24)

Surveying every BMS exchange in the corpus, the services the Omitec ever sent to `0x722`:

| Service | Count |
|---|---|
| `0x22` ReadDataByID | 419 |
| `0x3E` TesterPresent | 184 |
| `0x10` DiagSessionControl | 55 |
| `0x27` SecurityAccess | 54 |
| `0x2F` IOControlByID | 50 |
| `0x19` ReadDTCInfo | 7 |

The only negatives the BMS ever returned were `NRC 0x31` on nine out-of-range DIDs and two
`0x78` response-pending. **`0x23` ReadMemoryByAddress and `0x35` RequestUpload were never
attempted** — not refused, never tried.

This matters because the decryptor and its key must live in the **BMS bootloader**, which
is not in the extracted image: the flash wrote the application to `0x00000000`, so the
bootloader occupies a region that was never transferred, and it is necessarily plaintext
since it is what performs the decryption. Reading it out would yield both the algorithm
and the key. With the level-01 constant confirmed, the BMS can now be unlocked without the
Omitec, which makes this probe possible for the first time.

Tempering it: on the DLCM, `0x23` proved to be gated by a hardcoded address allow-list
that security level does not widen (`dlcm/dlcm-uds-live-access.md` section 2). The BMS may
behave the same. `0x35` is a separate service and the BMS bootloader clearly implements
the download half of the transfer pair, so it is the more promising of the two.

### ATTEMPTED 2026-09-24 — both services answer with a malformed NRC

Sent live by the in-car session, unlocked at level 01, seven requests and seven responses
in an unfiltered raw capture:

```
23 14 00 00 00 00 04   (app base)       -> 7F 10 12
23 14 00 03 D0 00 04   (past the app)   -> 7F 10 12
23 14 FF FF 00 00 04   (high memory)    -> 7F 10 12
23 / 35  truncated, locked and unlocked -> 7F 10 12
```

Invariant across address, payload form and security state, on `0x72A`, ~20 ms after each
request. **`NRC 0x12` is subFunctionNotSupported, and neither `0x23` nor `0x35` has a
subfunction byte**, so the response is malformed whatever its source.

**The gateway is excluded as the source.** Two independent lines, both from data already in
hand rather than from the car:

1. On 2026-09-19 a `0x23` probe reached the DLCM *through the same J1962 path and the same
   GWM* (`dlcm/artifacts/dlcm_ram_probe_run1.log`: `TX 7E0 23 14` → `RX 7E8 7F 23 13`,
   then `7F 23 31` for well-formed reads). The gateway forwards `0x23`, and a target that
   dislikes it answers service-matched.
2. Static analysis of `coda_gateway.bin` (`artifacts/gateway_uds_routing_analysis.py`):
   the Diag routing table carries **no service field** — 28 records of CAN id plus
   source/destination bus, with `0x722` routed exactly like `0x7E0` — the firmware
   **never constructs `0x72A`** as a transmit id in either MOV-immediate or literal form,
   and its own negatives are service-matched (`7F 34 33`, `7F 11 12`, `7F 85 31`).
   `7F 10 12` exists nowhere in the image.

**Conclusion: `0x23` and `0x35` are not implemented on the BMS application, and the
malformed NRC is a BMS firmware defect.** The bootloader is therefore not reachable from
the extended session, and would need the programming session (`10 02`) — which is out of
scope on a live car and is a separate decision, made heavier by the contactor behaviour
recorded at the top of this file.

*Residual gap, stated honestly:* the static analysis covers the gateway **application**.
Gateway Finding 7 records that some CAN handling lives in its bootloader, above the 90 KB
application, which we do not have. A service filter there is not excluded by the above,
though the routing table's shape argues against it.

*Artifacts (in-car session):* `artifacts/bms_boot_probe.py`,
`artifacts/bms_raw_frame_probe.py`, `artifacts/bms_unlock_probe.py` and their `_out.txt`.

---

## The four-digit passcode hypothesis: tested and closed (2026-09-26)

### Where the hypothesis came from

The owner spoke to a former Coda engineer on 2026-09-26. Relayed verbatim:

> "Yeah all of them should be encrypted but it never happened. Some did some didn't. The
> file I have I know it The update version because I had it on my red Coda that I had.
> Some of them we were doing the encryption and the passcode was the last four of the VIN
> number. Then we changed it to a different four number password as 2012. But some
> engineers set their own code number."

This is consistent with what the project holds: the gateway and DLCM images are plaintext
and the BMS image is not — "some did some didn't" describes exactly that split.

The decisive property is that **all three of his cases are four-digit numbers**, so a sweep
of `0000`–`9999` covers last-four-of-VIN, `2012`, and any engineer's own code without
needing to know which one applied. Our car's VIN is `53G1U4A46CB000090`, so last-four is
`0090`.

### Result: negative, across ~765,800 decryption attempts

| Pass | Passcodes | Trials | Hits |
|---|---|---|---|
| Targeted (`0090`, `2012` + 10 variants) | 12 | 5,680 | **0** |
| Exhaustive four-digit | 10,000 | 760,000 | **0** |
| Per-transfer-block modes (`0090`, `2012`) | 2 | 36 | **0** |
| Homebrew hash-chained keystreams | 5 | 60 | **0** |

Ciphers swept: AES-128 (CBC/CTR/CFB/OFB), AES-256, Camellia, SM4, CAST5, IDEA, DES, 3DES,
Blowfish, RC4, ChaCha20, TEA and XTEA, plus XOR and subtractive keystreams from six PRNGs
(MSVC `rand`, glibc `random`, Park-Miller lo/hi, Java LCG, Mersenne) seeded by the code.
Key derivations: raw ASCII, zero-padded, repeated to 8/16/24/32 bytes, BCD, u16/u32 in both
endiannesses, and MD5/SHA-1/SHA-256 at several widths.

### The detector was calibrated, so the negative means something

A sweep that returns nothing is indistinguishable from a sweep whose filter is broken, so
the detector was pinned against controls at both ends before and during each run:

- **Positive control:** the known-plaintext gateway image was encrypted under
  AES-128-CBC with `md5("2012")`, then fed to the sweep. It recovered exactly that key,
  with **0 false positives in 1,020 trials**.
- The brute-force pass asserts at startup that the prefilter accepts the gateway plaintext
  (zlib 0.597) and rejects `os.urandom` (zlib 1.005), and re-recovers a second positive
  control under `md5("7777")` before the sweep begins.
- Scoring is ISA-agnostic throughout, because the BMS core is still unidentified.

### The extraction is not the problem

Re-verified 2026-09-26: `coda_bms.bin` is byte-exact against `coda_bms_flash.log` at both
ends (head `C7 CB 38 8E ...` matches transfer block 1; final byte `A8` matches the last
consecutive frame). A failure to decrypt is not an artifact of ISO-TP reassembly.

### Known blind spots

These are the gaps the sweep genuinely does not cover, stated so nobody re-derives them:

- **A nonzero IV or nonce in CTR/OFB/CFB/ChaCha20** would hide a true positive. CBC is
  immune — a wrong IV corrupts only the first block, and scoring skips it — which is why
  CBC was the backbone of the sweep.
- Key derivations outside the 16 tested, in particular the passcode **combined** with
  something else (full VIN, part number, build date).
- Any proprietary or homegrown cipher, which is out of reach by construction.

Note that per-transfer-block CBC is *already* covered by the whole-file sweep even though
it was tested separately: CBC decryption self-synchronises, so an encryptor that reset its
IV every 224 bytes would still leave 93% of the plaintext recoverable by a whole-file CBC
pass, and the scorer would have fired. 224 bytes is exactly 14 AES blocks, so the
hypothesis was plausible enough to test directly; 36 variants were all indistinguishable
from random.

### What the negative implies — hypotheses, not conclusions

The engineer is not necessarily wrong. One of the following is likely true, and they are
listed in the order judged most plausible:

1. **The passcode is not the file-encryption key.** It may be what authorises the *tool*.
   That secret is a separate one, and the project already cracked it independently — see
   "SecurityAccess: SOLVED" above.
2. **The tool decrypts before transmitting**, so the engineer's encryption never appears on
   the CAN bus at all, and the high-entropy payload captured here is a different layer.
3. **The key derivation combines the passcode with something else** rather than using it
   directly.
4. **The cipher is homegrown**, which his "some engineers set their own code number"
   half-implies.

Hypotheses 1 and 2 are distinguished by a single question to the source: *was the encrypted
thing the file on the PC, or the bytes going down the CAN bus?*

**Status of the source's files:** the engineer does not appear to still have the update
file he referred to (owner, 2026-09-26). The known-plaintext route that would have settled
this outright is therefore not currently available.

### Two dead ends recorded so they are not re-walked

**`dataFormatIdentifier` declares no encryption.** The RequestDownload decodes cleanly as
`34 | 00 | 44 | 00000000 | 0003D000` — dataFormatIdentifier `0x00`, meaning no compression
and no encryption, for a payload that is demonstrably not plaintext. Either this
implementation ignores the field, or the payload is not encrypted in the way assumed.

**The TransferExit response is not a checksum.** The BMS returns `05 77 00 FF C2 9F` and
the **gateway returns the same shape, `05 77 00 00 35 39`, on an image whose plaintext we
hold** — which made it a candidate known-plaintext oracle. It is not one: `0x3539` matches
none of 17 checksum and CRC algorithms over the full gateway image, and a scan of all
90,112 prefixes under four CRC-16 variants produced 5 matches against **5.5 expected by
chance**, at meaningless lengths. That is noise. (The DLCM, by contrast, returns a bare
`01 77` with no payload.)

### Artifacts

| File | What it does |
|---|---|
| `artifacts/bms_passcode_decrypt.py` | Phase 1 targeted sweep, with controls |
| `artifacts/bms_passcode_decrypt_p1.txt` | Phase 1 output |
| `artifacts/bms_passcode_brute.py` | Exhaustive `0000`-`9999` sweep, pruned to chained/stream modes |
| `artifacts/bms_passcode_brute_out.txt` | Brute-force output |

---

## Where the key lives: the Omitec is a courier, not a keyholder (2026-10-03)

Follow-up statements from the same former Coda engineer, relayed by the owner in the same
thread as the passcode account above (2026-09-26 onward). Asked directly whether the
encrypted thing was the file on the PC or the bytes on the CAN bus, he answered:

> "Yes, Omitec to the module"

> "It may be in some of the scanners cuz I know some of them yet you can do a reflash and
> the reflash is encrypted in the software. Not all of the scanners have them.
>
> Early on we were doing reflashes with Inca"

### The architecture this implies

Taken together: the scanner **stores** the image encrypted, **transmits** it encrypted, and
the **BMS bootloader decrypts it**. The ciphertext we captured off the wire is therefore the
same artefact the scanner holds.

**Consequence: decompiling the Omitec tool would not yield the decryption key.** The tool is
a courier. It carries ciphertext it cannot read. This contradicts the original framing of
Option 1 ("the only path that would hand over the key outright") and that option is
downgraded accordingly — see the note added there. The key exists in exactly one place: the
bootloader.

### An unresolved tension, and the test that settles it

If the image ships pre-encrypted inside the scanner software, the key must be **fixed per
firmware build** — the software cannot know which car it will meet, so the key cannot be
the last four of a VIN. Two readings survive and they have different consequences:

| Reading | Implication |
|---|---|
| **Fixed key held in the bootloader** | Per-VIN passcodes belong to some other mechanism; the 2026-09-26 brute-force negative is unsurprising; Option 1 stays dead |
| **The scanner re-encrypts per car at flash time** | The scanner *does* hold key material, and Option 1 revives |

**Decisive test, if a scanner with a BMS reflash image is ever obtained:** compare its
stored image against `artifacts/coda_bms.bin` byte-for-byte. Identical means fixed key,
bootloader-only. Different means per-car re-encryption.

### New lead: the module was developed with ETAS INCA

"Early on we were doing reflashes with Inca" places an **ETAS INCA** toolchain on this
module during development. INCA is the Bosch/ETAS engineering tool for ECU calibration and
flashing — the bench tool, as distinct from a dealer scan tool. Three consequences, in
descending order of value:

1. **INCA normally talks CCP or XCP to the ECU, not UDS.** Both are calibration protocols
   with raw memory primitives — `SET_MTA`, `UPLOAD`, `SHORT_UPLOAD` — and no concept of
   "application versus bootloader". **If a CCP or XCP slave survived into production, it
   reads the bootloader directly and the encryption problem ends.** This is the first
   genuinely new attack path since the `0x23`/`0x35` route closed.
2. **An A2L file probably existed.** That is the ASAM description INCA requires: a complete
   symbol and variable map. If one ever surfaced it would be worth more than the decrypted
   binary.
3. It weakly suggests the MCU class — the ETAS toolchain of that era is overwhelmingly
   TriCore or PowerPC, and the DLCM is already confirmed TriCore. **This is a hypothesis
   about the still-unidentified BMS core, not a finding**, and it is inference from a
   toolchain, which is weaker still than the ARM7TDMI-S inference it would displace.

### Why the corpus cannot answer this, and a scan that proved it

A search of the flash captures for XCP `CONNECT` (`0xFF`) and CCP command bytes returned
nothing, **and that result is worthless**: a CCP/XCP slave is silent until a master
addresses it, and every capture held is UDS plus passive traffic. The scan could not have
found anything even if a slave is sitting there enabled. (The three `01` hits it did return
are ISO-TP length bytes from `01 37` TransferExit frames — false positives of the filter's
own construction.) Recorded because this is precisely the
[fail-silent filter](../../../AGENTS.md) pattern: an empty result whose premise was wrong.

**Confirming or excluding CCP/XCP requires an active probe.**

### What reaches the BMS, and from where

The gateway's 28-entry diagnostic routing table is **entirely UDS** — every record is a
`B2=0x05` request or `B2=0x06` response pair. There is no non-UDS ID pair in it. The
`B3`/`B4` fields read as source/destination bus and place the BMS off the diagnostic bus:

| Entry | B3 -> B4 | Reading |
|---|---|---|
| `0x722` req | 02 -> 01 | diag bus -> BMS bus |
| `0x72A` resp | 01 -> 02 | BMS bus -> diag bus |
| `0x7E0`/`0x7E8` | 04 <-> 01 | DLCM, bus 4 |
| `0x710` req | 01 -> 01 | GWM — same bus, because it *is* the gateway |

So **on the Diag CAN pins, the only IDs that reach the BMS are `0x722` and the `0x7DF`
broadcast.** A blind ID sweep on that bus cannot reach the BMS at all; the gateway drops
everything unrouted.

**But that is a statement about the diagnostic bus, not about the connector.** All four
buses appear on the J1962: B CAN on pins 2/3, C CAN on 7/15, D CAN on 10/11, Diag CAN on
6/14. The BMS sits on **B CAN** and has its own **C CAN** diagnostic output. On either of
those the BMS is addressed directly, with no gateway mediation and no routing table in the
path. (An earlier draft of this analysis conflated "the diagnostic bus" with "the
connector" and wrongly concluded a sweep was impossible. It is not.)

### Observed-ID inventory, for a probe exclusion list

Measured across `projects/coda/logs/` with the bus identified by anchor content, never by
channel number — `artifacts/ccan_id_inventory.py`:

| Bus | Files | Distinct IDs | Frames | Highest ID |
|---|---|---|---|---|
| C CAN | 20 | 100 | 2,581,422 | `0x687` |
| B CAN | 20 | 57 | 27,632,629 | `0x6FA` |
| D CAN | 12 | 35 | 6,357,167 | `0x6FA` |

**Neither B CAN nor C CAN carries any diagnostic traffic whatsoever.** The entire
`0x700`-`0x7FF` range is never observed on either bus — all UDS lives on the Diag CAN. That
makes the conventional tool range both empty and conventional on exactly the two buses that
are easy to reach: 256 IDs, about 5 seconds of bus time at 20 ms spacing. C CAN has 1,948
never-observed 11-bit IDs in total, a full sweep of which is under a minute.

**The caveat the inventory cannot show.** It lists IDs modules *transmit*. An ID a module
only *listens* for appears in no passive capture, so absence here narrows the risk without
removing it. `0x7xx` on a bus with zero diagnostics is as safe as this gets; it is not a
proof.

### Probe plan — C CAN first, and why

C CAN is the right bus to try before B CAN:

- It is a **BMS-only output**, so any reply is unambiguously the BMS.
- It is a **diagnostic port, not a control bus**. Nothing on it commands a contactor, the
  DC-DC or a charger. B CAN does (`0x1D5` DCDC, `0x275` BMS limits, `0x615`-`0x61C`
  charger), which makes a B CAN sweep materially riskier.
- No gateway in the path.
- It is the most plausible surviving home for a calibration slave: a dedicated engineering
  port streaming 104 cell voltages (`0x000`-`0x019`) plus an apparent second 26-ID block at
  `0x100`-`0x119`.

For the record, the C CAN stream is **not itself a CCP/XCP DAQ** — that would be one ID
with a varying PID byte, not ~100 structured IDs.

| Probe | Action | Cost |
|---|---|---|
| 1 | XCP `CONNECT` (`FF 00`) on C CAN `0x700`-`0x7FF`, promiscuous listen, correlate replies by timing | ~5 s |
| 1b | Same over the remaining never-observed C CAN IDs | ~40 s |
| 2 | CCP `CONNECT` with station-address sweep, **only** on IDs that produced any reply — a silent CCP probe is uninformative because the station address is a second unknown | minutes |
| 3 | If anything connects: `GET_STATUS`, then `SHORT_UPLOAD` from low memory | — |
| 4 | B CAN, with the observed-ID exclusion list, **on the parts car** | separate session |

XCP is the better first probe than CCP: `CONNECT` needs only the right CAN ID, and its
reply is unmistakable — `0xFF` positive or `0xFE` error. **Either is a hit**; an error
response still means something is speaking XCP. CCP `CONNECT` needs the ID *and* the
station address, so silence tells you nothing.

Probe 1 is also safe on the Diag CAN against `0x722` directly, as a free extra: `0xFF` is
not a valid ISO-TP PCI (the PCI nibble defines only 0-3), so a UDS-only stack discards the
frame unparsed. Some integrators do layer XCP on the diagnostic mailbox pair.

**Honest odds: low.** Production builds usually compile the calibration slave out, and
leaving it in is a known security embarrassment. This is a lottery ticket — but it is a
cheap one on the only mechanism that would end the problem outright.

*Artifacts:* `artifacts/xcp_ccp_probe.py` (not yet run), `artifacts/ccan_id_inventory.py`,
`artifacts/ccan_id_inventory_out.txt`.

---

## Analysis Goals (when decryption is resolved)

### Goal 1: Cell balance and SOC algorithm
Understand how the BMS computes SOC and controls cell balancing — corroborates or refines the CAN signal interpretations already established.

### Goal 2: Fault code table
Locate the DTC/fault code table and string descriptors to map fault codes visible on the Omitec screen to internal conditions.

### Goal 3: CAN message dispatch
Find where CAN message IDs are assembled and transmitted — confirms byte layout and scaling for signals not yet validated against physical measurement.
