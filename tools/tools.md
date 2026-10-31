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

Moved here from `tools/artifacts/error-report-sweep/` on 2026-10-31 (owner: a tools project, not
an artifact). The scripts and `README.md` sit at the top, and their regenerable outputs in
`artifacts/` (`scan.jsonl` ~150 MB). The rules and the evidence for them are in the README.
Corpus sweeps read `CANLogs/`, so run them on the Linux box from the reverse-it root, e.g.
`python3.13 tools/error-report-sweep/marker_check.py kvaser`. The rules themselves live in
can-tools, `canbench/parsers/inferred_errors.py`.
