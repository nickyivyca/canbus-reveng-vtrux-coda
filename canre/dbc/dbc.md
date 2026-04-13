# canre.dbc Reference


Tools for building, generating, and validating DBC (CAN database) files. All DBC operations depend on the `cantools` library.

---

## builder.py — DBC Construction & Editing

Programmatic interface for creating and modifying DBC files via `cantools`. Wraps `cantools.database.can.Database` with convenience methods for message and signal management.

### `DBCBuilder` class

```python
class DBCBuilder:
    def __init__(self, path: Path | str | None = None): ...
```

Loads an existing DBC file if `path` points to an existing file; otherwise creates an empty database. The path is retained as the default save location.

#### `add_message(msg_id, name, length=8, is_extended=False, comment="", signals=None) -> Message`

Add a new message definition to the database.

- `msg_id`: CAN arbitration ID (int)
- `name`: Human-readable message name (e.g. `"EngineRPM"`)
- `length`: Payload length in bytes (default 8)
- `is_extended`: `True` for 29-bit extended frames
- `comment`: Optional description string
- `signals`: Optional list of pre-built `cantools.database.can.Signal` objects

Returns the newly created `Message`. Internally uses `db._add_message()` with a fallback to direct append + `db.refresh()` for compatibility across cantools versions.

#### `add_signal(msg_id, name, start_bit, length, byte_order="big_endian", is_signed=False, scale=1.0, offset=0.0, minimum=None, maximum=None, unit="", comment="") -> Signal`

Add a signal to an existing message identified by `msg_id`.

**Important caveat**: Because cantools `Message` objects have immutable signal lists, this method removes the old message and creates a replacement with the new signal appended. The message is matched by both `frame_id` and `is_extended_frame` to avoid collisions between standard and extended IDs.

#### `save(path=None) -> Path`

Write the database to a `.dbc` file. Falls back to the path given at construction time if `path` is `None`. Creates parent directories automatically. Raises `ValueError` if no path is available.

#### `get_message(msg_id) -> Message | None`

Look up a message by frame ID. Returns `None` instead of raising `KeyError` if not found.

#### `list_messages() -> list[dict]`

Returns a summary of all messages sorted by frame ID. Each dict contains: `id` (hex string), `name`, `length`, `signals` (count), `extended` (bool).

#### `remove_message(msg_id, is_extended=False) -> bool`

Remove a message by frame ID and extended flag. Returns `True` if removed, `False` if no match. Calls `db.refresh()` after removal.

---

## skeleton.py — Skeleton DBC Generation

Generates a starter DBC file from observed CAN traffic. Single streaming pass over frames, then builds one message per unique `(bus, arbitration_id)`.

### `generate_skeleton(frames_iter, output_path, bus_filter=None) -> Path`

- `frames_iter`: `Iterable[CANFrame]` — can be a generator (single-pass)
- `output_path`: Destination `.dbc` file path
- `bus_filter`: If set, only includes frames from this bus number

Returns the resolved output `Path`.

**What the skeleton contains for each message:**
- Message name: `MSG_0x123` (standard) or `MSG_0x18FF0320` (extended, 8-digit hex)
- Length: largest observed DLC for that ID
- Signals: one raw 8-bit unsigned signal per byte (`byte0` through `byte{dlc-1}`), little-endian, start bit at `i * 8`
- Comment: bus number, frame count, average frequency, duration, and per-byte min/max ranges

**Edge cases:**
- Raises `ValueError` if no frames match the filter
- DLC 0 defaults to 8 bytes
- DLC is tracked as the maximum observed across all frames for each ID

---

## validator.py — DBC Validation Against Traffic

Validates a DBC file against actual CAN bus traffic, reporting coverage metrics and decode results.

### `validate_dbc(dbc_path, frames, bus_filter=None) -> dict`

Loads a DBC file and streams through frames, attempting to decode each matched frame.

```python
{
    "id_coverage_pct": float,           # % of observed IDs defined in DBC
    "traffic_coverage_pct": float,      # % of total frames matched a DBC message
    "total_frames": int,
    "matched_frames": int,
    "defined_ids": list[int],           # sorted IDs in the DBC
    "observed_ids": list[int],          # sorted IDs seen in traffic
    "matched_ids": list[int],           # intersection (sorted)
    "unmatched_observed": list[int],    # in traffic but not in DBC
    "unmatched_defined": list[int],     # in DBC but not in traffic
    "observed_counts": dict[int, int],  # arb_id -> frame count
    "decode_errors": dict[int, list[str]],  # arb_id -> up to 5 unique errors
    "signal_ranges": {
        arb_id: {
            signal_name: {"min": float, "max": float, "count": int},
        },
    },
}
```

**Decode error cap**: At most 5 unique error strings per arbitration ID.

**Signal ranges**: Only numeric values (`int` or `float`) are tracked. Non-numeric decoded values are skipped.

### `format_validation(results) -> str`

Pretty-prints: summary line, matched IDs with signal ranges and errors, undefined IDs with counts, unobserved defined IDs.
