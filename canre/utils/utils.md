# canre.utils Reference


Shared utilities for file I/O, multi-file merging, and session discovery.

---

## io.py — Streaming File Reading

Low-level line streaming and line counting for large CAN log files. Handles encoding detection automatically.

### `stream_lines(path) -> Iterator[str]`

Yields lines from a file with trailing newlines stripped.

**Encoding strategy**: Opens as UTF-8 first. If a `UnicodeDecodeError` occurs (at open time or mid-stream), falls back to Latin-1, which accepts every byte value and never raises a decode error. If the error occurs mid-stream, the file is reopened from the beginning in Latin-1, meaning some lines may be yielded twice in the rare case of a mid-file encoding failure.

### `count_lines(path) -> int`

Counts lines quickly using binary reads (1 MiB buffer). Counts `\n` bytes directly, avoiding encoding overhead. Useful for progress bars on large files.

---

## merge.py — Multi-File Capture Merging

Merges multi-file captures into a single time-sorted frame stream. Two naming conventions are supported:

### Naming Conventions

**`_M{bus}_T{chunk}` style** (BUSMASTER multi-bus):
```
<prefix>_M{bus}_T{chunk}.log
```
Used when BUSMASTER is configured with a fixed base filename. Each new logging start = new M number; M encodes which physical bus the chunk belongs to. Frames get their bus number overridden by the M value from the filename.

**`_T{chunk}` style** (timestamp-keyed sessions):
```
<prefix>_T{chunk}.log
```
Used when the session prefix already encodes identity (e.g. timestamp-keyed files like `coda_20260328_101624_T0.log`). No M number means no bus override — frames keep the bus number recorded in the file.

### `detect_capture_groups(paths_or_dir) -> dict[str, list[Path]]`

Groups files by capture session prefix. Tries `_M{bus}_T{chunk}` first; falls back to `_T{chunk}` for files without an M number.

- `paths_or_dir`: list of file paths, or a single directory path
- Returns: dict mapping session prefix to sorted list of `Path` objects, ordered by `(bus, chunk)`
- Files matching neither pattern are silently ignored

### `merge_files(paths) -> Iterator[CANFrame]`

Parses multiple log files and yields frames sorted by timestamp using a heap merge.

- Uses `absolute=True` so T-chunk files chain correctly on a shared timeline (requires `busmaster.py` to parse the `***START DATE AND TIME***` header for the wall-clock epoch)
- **Bus number** on each frame is overridden by `_M{bus}` from the filename only if `_M{bus}_T{chunk}` pattern matches; T-only files are not overridden
- Heap merge uses `(timestamp, index)` as key; index is a per-file counter for tie-breaking
- All timestamps shifted so earliest frame becomes `t=0`

---

## sessions.py — Session Grouping

Higher-level session discovery that groups log files by the `_M#_T#` pattern and splits on filesystem timestamp gaps.

### `group_files_by_session(folder) -> dict[str, list[Path]]`

Groups `.log` files in a directory into sessions.

**Grouping rules:**
1. Files matching `_M#_T#` are grouped by M number
2. Within each M group, sorted by mtime then T number
3. Mtime gap > **1 hour (3600 seconds)** splits into sub-sessions (`M0_a`, `M0_b`, etc.)
4. Within each sub-session, re-sorted by T number for correct chaining
5. Non-matching files become single-file sessions keyed by filename stem

**Example return value:**
```python
{
    "M0": [path_M0_T0, path_M0_T1, path_M0_T2],
    "M1_a": [path_M1_T0, path_M1_T1],
    "M1_b": [path_M1_T3, path_M1_T4],
    "full charge then fail": [path_standalone],
}
```

### `list_session_files(folder) -> tuple[dict[str, list[Path]], list[Path]]`

Convenience wrapper. Returns:
- `grouped_sessions`: dict of sessions with multiple files or `_M` prefix
- `standalone_files`: flat list of single-file sessions that didn't match the pattern
