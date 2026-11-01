# canre.parsers Reference

**`canre.parsers` is a re-export of can-tools' `canbench.parsers`** (since 2026-10-31,
the internal `can-replay-readers` plan step 2). The readers, their API and their per-format notes
live in the can-tools git clone: **`canbench/parsers/parsers.md`** there (on a reverse-it machine
`~/Git/can-tools/canbench/parsers/parsers.md`; in a public-repo clone
`can-tools/canbench/parsers/parsers.md`). Pull the clone first, per `tools-reference.md`,
section "can-tools".

`canre/parsers/__init__.py` imports `canbench.parsers` (the per-machine clone via its `.pth`
file, else the `can-tools/` submodule of a public-repo clone) and registers its modules as
`canre.parsers.autodetect`, `.base`, `.busmaster`, `.candump`, `.peak_trc`, `.savvycan` and
`.vector_asc`, so existing imports keep working. It exports `CANFrame`, `CANEvent`,
`BaseParser`, `detect_format` and `parse_file`. If `canbench` is missing, the import fails with
an `ImportError` naming the fix. Do not put parser code back here: change it in the clone.

canbench's readers are a superset of the old canre copy: non-frame records (`CANEvent`, with
`include_events=True`) and inferred-error marking (`mark_inferred_errors=True`) are off by
default. Real fixes over the old copy: the TRC reader reads offsets as milliseconds in every
version and reads 2.0 lines (the old copy read ms as s and matched no 2.0 line), and the candump
reader handles error-frame lines, remote requests, 8-digit ids and FD flags.

The rest of this file is the canre-specific head that AGENTS.md routes import questions to.

## COMMON MISTAKES — Read before writing any script

### sys.path bootstrap (required in every scratchpad)

Scripts in `projects/<vehicle>/notes/artifacts/` are not on the Python path by default — Python adds the script's own directory, not the project root, so `canre` is invisible without this at the top of every scratchpad:

```python
import sys
sys.path.insert(0, ".")
```

All scratchpads are invoked via the Bash tool from the project root, so `"."` reliably resolves to the project root where `canre/` lives. Do **not** use the `Path(__file__).resolve().parent...` form — the required depth varies by script location and is easy to get wrong (a script in `artifacts/` needs five `.parent` calls to reach project root, not four).

### Wrong import names

| Wrong (do NOT use) | Correct |
|--------------------|---------|
| `from canre.parsers.parsers import parse_log` | `from canre.parsers import parse_file` |
| `from canre.parsers.parsers import parse_file` | `from canre.parsers import parse_file` |
| `from canre.parsers import parse_log` | `from canre.parsers import parse_file` |
| `frame.arb_id` | `frame.arbitration_id` |
| `frame.can_id` | `frame.arbitration_id` |
| `frame.id` | `frame.arbitration_id` |
| `frame.msg_id` | `frame.arbitration_id` |
| `frame.channel` | `frame.bus` |

There is no `canre.parsers.parsers` submodule. The function is `parse_file`, not `parse_log`. The ID field is `arbitration_id` and the bus field is `bus`.

### `parse_file` is a generator — it can be iterated once

Every `parse_file` yields frames; none returns a list. A second pass over the same result sees **nothing**, with no error. The usual trap is a bus-identification pass followed by an analysis pass: the second one comes back empty and reads as "the ID is absent". If you need more than one pass, materialise it first: `frames = list(parse_file(path))`. Found 2026-10-26, when an HVAC scratchpad reported every ID, its bus anchors included, as missing from all 20 captures.
