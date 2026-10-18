# canre — CAN Bus Reverse Engineering Framework

Python package providing log parsing, signal analysis, DBC construction, and UDS diagnostic scanning. Used by all tools in `tools/` and vehicle-specific tools in `projects/<vehicle>/tools/`.

## Package Layout

```
canre/
    parsers/    -- Log file parsing (BUSMASTER, candump, PEAK TRC, SavvyCAN, Vector ASC)
    analysis/   -- Signal analysis (survey, bitstats, correlation, diff, timeseries, transitions)
    dbc/        -- DBC file construction, skeleton generation, and validation
    utils/      -- Streaming I/O, multi-file merging, session grouping
    uds/        -- UDS/KWP2000 diagnostic scanner (ISO 14229)
```

## Submodule Reference Docs

| Submodule | Doc | What it provides |
|-----------|-----|-----------------|
| `canre.parsers` | `parsers/parsers.md` | `CANFrame` dataclass, `BaseParser` ABC, auto-detecting `parse_file()` entry point, one parser class per format |
| `canre.analysis` | `analysis/analysis.md` | `run_survey`, `analyze_id`, `detect_counters`, `detect_checksums`, `find_correlations`, `diff_captures`, `extract_timeseries`, `detect_transitions` |
| `canre.dbc` | `dbc/dbc.md` | `DBCBuilder` (programmatic DBC editing), `generate_skeleton` (starter DBC from traffic), `validate_dbc` (coverage + decode check) |
| `canre.utils` | `utils/utils.md` | `stream_lines` / `count_lines` (streaming I/O), `merge_files` / `detect_capture_groups` (multi-file merge), `resolve_files` (per-file channel -> bus resolution), `group_files_by_session` (session discovery) |
| `canre.uds` | `uds/uds.md` | `ISOTPChannel`, `UDSClient`, `UDSScanner` — full UDS + KWP2000 scan pipeline used by `tools/uds_interrogator.py` |

## Primary Entry Points

```python
from canre.parsers import parse_file          # auto-detect format, yield CANFrame objects
from canre.analysis.survey import run_survey  # bus overview
from canre.analysis.bitstats import analyze_id
from canre.analysis.correlation import find_correlations
from canre.dbc.builder import DBCBuilder
from canre.utils.merge import merge_files, detect_capture_groups
```

See each submodule's `.md` for full API details, return dict shapes, and common-mistake tables.
