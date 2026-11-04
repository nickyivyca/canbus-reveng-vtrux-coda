# Generator inhibitor status: the interface the Vtrux live display reads

**Status: agreed and implemented 2026-10-30; not yet seen against a real inhibitor.** Written
before the code at the owner's request. The inhibitor (`gen-inhibit`, a WiCAN on the Vtrux
powertrain bus) is not on the truck yet; the display code is in and shows nothing different
until it is.

## What the display does with it

The live display's EVAP status word (`display/.../LiveDisplayScreen.kt`, Generator panel) shows
**`INHIBIT` on purple (`#7B1FA2`)** whenever the inhibitor is inhibiting, as defined below. It
overrides every evap state (`COMPLETE`, `PURGE`, `PENDING` and `—`). When the inhibitor is not
inhibiting -- including when it is absent, silent, stale or speaking a layout version this app
does not know -- EVAP shows exactly what it shows without an inhibitor (`0x649`,
`../evap-bug.md`). Both the `:vtrux` app and the Vtrux `:companion` flavour carry it, through
the shared `:display` module.

## Who owns what

| | Owner | Where |
|---|---|---|
| The inhibitor's behaviour, and the frame's layout and meaning | the gen-inhibit reviewer session; the owner rules in that session | spec `projects/vtrux/notes/gen-inhibit-wican-spec.md` section 10 (reverse-it); layout `gen-inhibit/diag/wican_diag_schema.md` and decode DBC `gen-inhibit/diag/vtrux-wican-diag.dbc` on `gen-inhibit/main` of the `canbus-esp-fw-vtrux` repo |
| This file: which fields the app reads, the rule, the display | Android development session | here |

The app is a read-only consumer. It never transmits to the inhibitor and has no say in its
layout. The schema doc records the dependency (`gen-inhibit/main` `30bbd59`, owner 2026-10-30):
"If `0x7F1` changes, the Android app needs to change too", covering `diag_schema_ver`,
`diag_mode` and `diag_flags`, in layout or meaning. **Nothing enforces it**: the reviewer tells
the Android session when such a change is weighed, and the version check below is what keeps the
display from misreading a frame meanwhile.

## The frame

`0x7F1` `WICAN_Diag_Status`, standard 11-bit ID, DLC 8, on the **powertrain** bus, transmitted
by the inhibitor itself. Little-endian byte fields; the app reads three:

| Signal | Byte | Used for |
|---|---|---|
| `diag_schema_ver` | B0 | layout version; only **8** is accepted |
| `diag_mode` | B2 | `3` = INHIBIT (`0` OFF, `1` OBSERVE, `2` RESPOND, `4` PASSIVE) |
| `diag_flags` | B3 | bits 0, 4, 5, 6, 7 below |

Distilled into the apps' `live-display/dbcs/powertrain.dbc` from the decode DBC at
**`gen-inhibit/main` `50f4f63`** (schema 8; its signals are byte-identical to `32db7d0` and `30bbd59`, and `50f4f63` corrects the bit5 comment). The reverse-it copy
`projects/vtrux/vtrux-wican-diag.dbc` is frozen at schema 7 and is not a source.

**Cadence** (spec section 10): five diag pages round-robin at 240 ms, so `0x7F1` repeats about
every **1.2 s**. Best-effort: the pages never delay an inhibit frame and nothing bounds their own
delay, so **no worst-case gap is specified**. No pages at all in OFF or OBSERVE.

## The rule: "inhibiting"

```
inhibiting =  0x7F1 received within the last 3 s
           && diag_schema_ver == 8
           && diag_mode == 3                 INHIBIT
           && diag_flags bit5 == 1           inhibit_live
           && diag_flags bit6 == 1           key_on
           && diag_flags bit4 == 0           shutdown_suppressed
           && diag_flags bit7 == 0           abort_latched
           && diag_flags bit0 == 0           disabled
```

Anything else is **not inhibiting**. This is the firmware's own condition for sending a real
inhibit frame (`0x051`), read on `0x7F1` (gen-inhibit reviewer, from spec 6.3, 6.4, 7.1 and 10,
the schema doc and `gen_inhibit_core.c` at `32db7d0`; a reading of the published interface, not a
new ruling). Since `50f4f63` the schema doc and DBC state the same condition: a `0x051` is sent only
with bits 5 and 6 set and bits 0, 4 and 7 clear. Why each term is needed:

- **`diag_mode == 3`:** PASSIVE (mode 4, a dry run that transmits nothing) sets `inhibit_live`
  exactly as INHIBIT does. The mode also stays 3 through an abort, so it is never enough alone.
- **bit5 `inhibit_live`** means the arm gate is satisfied. It is **not** "transmitting": it stays
  set while the device is armed but silent. The schema doc and DBC comment say so since
  `50f4f63` (owner, 2026-10-30); before that the comment read "satisfied and transmitting".
- **bit6 `key_on`** (key on and `0x592` fresh): after a key-off a live device stays live and
  silent -- bit5 set, bit6 clear (spec 7.1).
- **bit4 `shutdown_suppressed`:** while the VCM commands generator shutdown (`0x051` B0 = `0x10`,
  parked; spec 6.3) bit5 stays set and transmission stops; it resumes by itself.
- **bit7 `abort_latched`, bit0 `disabled`:** a section 7 trip or a latched release (spec 6.4)
  clears bit5 as well; the firmware checks these terms anyway, and so does the app.

**Freshness, 3 s:** about 2.5 nominal periods. The direction is deliberate: stale means no
inhibit, so a removed, bus-off or stood-down inhibitor never leaves `INHIBIT` on the screen.

**Version:** bits 4 and 5 date from schema 2, bits 6 and 7 and "mode stays 3 through an abort"
from schema 3, PASSIVE from schema 4. The schema doc's rule is that a decoder holding a different
version flags a mismatch rather than trusting the fields, so the app accepts exactly the version
it was distilled and checked against (8) and treats every other value, older or newer, as
unknown -- not inhibiting.

**Not chosen:** "armed and would inhibit if the engine were wanted" (`mode == 3 && bit5 && !bit7
&& !bit0`). It would show `INHIBIT` parked with the key off. The full transmit test was chosen
(owner, 2026-10-30, on the reviewer's recommendation).

## How the app implements it

- **DBC:** `0x7F1`'s block, comments and nothing else, inserted into both
  `live-display/dbcs/powertrain.dbc` copies with `tools/distill_dbcs.py`'s own extraction from the
  pinned DBC. Not a full regeneration: the assets have drifted from that tool since 2026-09 (see its
  section in reverse-it `tools/tools.md`). The tool's SPEC now lists `0x7F1` and requires
  `--wican-diag-dbc <path>`, so a later regeneration cannot drop it silently.
- **Subscription:** both `live-display/manifest.json` files subscribe to powertrain `0x7F1`
  (`diag_schema_ver`, `diag_mode`, `diag_flags`) at 2 Hz `latest`. The aggregator emits nothing for
  a window with no frames, so a silent inhibitor produces no updates.
- **Freshness:** `LiveDisplayViewModel` keeps each signal's last value indefinitely, so it also
  records when each signal last arrived (`signalSeenAtMs`, `SystemClock.elapsedRealtime`). The
  screen re-evaluates once a second, so an inhibitor that goes quiet clears without any other frame
  arriving.
- **The rule** is `display/.../GenInhibitStatus.kt`, called by `LiveDisplayScreen`'s Generator
  panel. `GenInhibitStatusTest` covers each term, both edges of the 3 s window, other modes and
  schema versions, absence of each field, and decodes a `0x7F1` frame through both bundled DBCs
  with `:cancore`'s decoder and checks both manifests, so the DBC, the manifests and the rule
  cannot disagree.

## When the layout changes

When the reviewer reports a schema change that touches `0x7F1`: re-read the schema doc at the new
commit, re-distil `powertrain.dbc` from it, re-check the three fields and the five bits against
this file, update the accepted version and the pinned commit here, and update the tests. Until
then, a newer inhibitor simply shows as not inhibiting.
