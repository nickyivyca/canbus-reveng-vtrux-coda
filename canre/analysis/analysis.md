# canre.analysis Reference


All analysis functions take `Iterator[CANFrame]` (or `list[CANFrame]` where noted) and return dicts. Use `iter(frame_list)` when calling with a stored list to allow re-iteration across multiple analysis passes.

---

## survey.py — Bus Survey

Streaming single-pass survey. Suitable for multi-GB captures — does not store raw frames.

### `run_survey(frames, bus_filter=None) -> dict`

Returns per-(bus, ID) statistics:

```python
{
    "ids": {
        "<bus>:<hex_id>": {
            "bus": int,
            "arbitration_id": int,
            "id_hex": str,
            "count": int,
            "first_seen": float,
            "last_seen": float,
            "frequency": float | None,  # Hz, None if <=1 frame
            "dlc": list[int],           # sorted unique DLCs observed
            "is_extended": bool,
            "bytes": {
                "0": {"min": int, "max": int, "unique_count": int},
                ...  # up to 7
            }
        }, ...
    },
    "total_frames": int,
    "duration": float,
}
```

**Key detail**: `unique_count` is capped at 257 (`_UNIQUE_CAP = 256`). Once a byte exceeds 256 unique values, individual value tracking stops and `unique_count` reads 257.

### `format_survey(results) -> str`

Table output grouped by bus, sorted by ID. Byte columns show `XX` (constant) or `XX-YY` (range).

### `save_survey_json(results, path) -> None`

Writes results dict to JSON file.

---

## bitstats.py — Deep Per-ID Analysis

Single-pass analysis of one CAN ID. Computes byte histograms, bit toggle rates, entropy, and byte-pair stats.

### `analyze_id(frames, target_id, bus_filter=None) -> dict`

```python
{
    "id": int,
    "id_hex": str,
    "frame_count": int,
    "first_seen": float,
    "last_seen": float,
    "frequency": float | None,
    "byte_stats": {
        "0": {
            "histogram": {val: count, ...},
            "min": int, "max": int,
            "mean": float, "std_dev": float,
            "entropy": float,       # Shannon entropy in bits
            "unique_count": int,
        }, ...
    },
    "bit_stats": {
        "0": {"toggle_rate": float, "stuck_0": int, "stuck_1": int},
        ...  # positions 0–63
    },
    "byte_pairs": {
        "0-1": {"min": int, "max": int, "unique_count": int},
        ...  # adjacent byte pairs, big-endian uint16
    },
    "sample_frames": [str, ...],  # repr of first 10 frames
}
```

**Bit numbering**: `bit 0 = MSB of byte 0`. Formula: `byte_pos = bit // 8`, `bit_within_byte = 7 - (bit % 8)`.

**Toggle rate**: fraction of frame-to-frame transitions where that bit flipped. A binary status flag has low toggle rate (e.g., 0.001) with both `stuck_0 > 0` and `stuck_1 > 0`.

### `format_bitstats(results) -> str`

Pretty-prints byte stats table, byte-pair table, active bits (only bits where both stuck_0 and stuck_1 are nonzero), and sample frames.

---

## counters.py — Counter & Checksum Detection

### `detect_counters(frames, target_id, bus_filter=None) -> dict`

Detects rolling counters at byte level (mod 256) and nibble level (mod 16).

```python
{
    "frame_count": int,
    "byte_counters": {
        "0": {"is_counter": bool, "confidence": float, "direction": "up"|"down"|"none"},
        ...
    },
    "nibble_counters": {
        "0_high": {"is_counter": bool, "confidence": float, "direction": "up"|"down"|"none"},
        "0_low":  { ... },
        ...
    },
}
```

**Threshold**: confidence >= 0.85 → flagged as counter. Confidence = fraction of frame-to-frame transitions that are exactly +1 or -1 (mod 256 for bytes, mod 16 for nibbles).

### `detect_checksums(frames: list, target_id) -> dict`

**Note**: takes a `list[CANFrame]`, not an iterator (needs multiple passes).

Tests each byte position as a potential checksum over the remaining bytes. Algorithms tested: XOR, sum (mod 256), CRC-8 SAE J1850, nibble sum.

```python
{
    "frame_count": int,
    "checksums": {
        "0": {
            "xor":        {"matches": int, "total": int, "confidence": float},
            "sum":        { ... },
            "crc8_j1850": { ... },
            "nibble_sum": { ... },
            "best": str | None,       # algorithm name if confidence > 0.95
            "best_confidence": float,
        }, ...
    },
}
```

---

## transitions.py — State/Event Detection

Detects three behaviors per byte position of a single CAN ID.

### `detect_transitions(frames, target_id, bus_filter=None, abrupt_threshold=10, state_max_unique=16, pulse_return_window=5) -> dict`

```python
{
    "frame_count": int,
    "bytes": {
        "0": {
            "abrupt_changes": [
                {"frame_idx": int, "timestamp": float, "from": int, "to": int, "delta": int},
                ...
            ],
            "state_machine": {
                "is_state_machine": bool,       # True if unique values <= state_max_unique
                "states": [int, ...],           # sorted unique values (empty if not SM)
                "transitions": {"X -> Y": count, ...},  # only value-change transitions
            },
            "pulses": [
                {"frame_idx": int, "timestamp": float, "baseline": int, "peak": int, "duration_frames": int},
                ...
            ],
        }, ...
    },
}
```

**Abrupt changes**: consecutive frames where `|delta| >= abrupt_threshold` (default 10).

**State machine**: triggered when unique values <= 16. Transition map counts only actual value changes (no self-loops).

**Pulses**: baseline = mode (most common value). Only detected if baseline > 60% of samples. A pulse = departure from baseline that returns within `pulse_return_window` frames (default 5).

### `format_transitions(results) -> str`

Pretty-prints state machine states (hex), first 10 abrupt changes, first 10 pulses per byte.

---

## correlation.py — Cross-ID Correlation

Finds byte positions in different CAN IDs that change in sync using Pearson correlation. Pure stdlib (no numpy).

### `find_correlations(frames, bus_filter=None, sample_every=10, min_samples=50, threshold=0.8, max_ids=200) -> dict`

```python
{
    "pairs": [
        {
            "id_a": str,        # hex
            "byte_a": int,
            "id_b": str,        # hex
            "byte_b": int,
            "correlation": float,
            "samples": int,
        }, ...
    ],
    "ids_analyzed": int,
    "threshold": float,
}
```

**Memory control**: `sample_every=10` keeps every 10th frame per ID. `max_ids=200` caps IDs analyzed (highest traffic first). Pairwise comparison is O(n^2) on the number of (ID, byte) signals.

**Filtering**: constant signals (zero variance) are skipped. Only cross-ID pairs are reported (not intra-ID). Series are truncated to the shorter length before correlating.

Results sorted by descending `|correlation|`.

---

## diff.py — Capture Comparison

Compares two captures by running `run_survey()` on each and diffing the results.

### `diff_captures(frames_a, frames_b, bus_filter=None) -> dict`

```python
{
    "only_a": [str, ...],       # "<bus>:<hex_id>" labels only in A
    "only_b": [str, ...],       # only in B
    "shared": {
        "<bus>:<hex_id>": {
            "id_hex": str,
            "bus": int,
            "count_a": int, "count_b": int,
            "freq_a": float|None, "freq_b": float|None,
            "freq_diff": float|None,
            "byte_diffs": {
                "0": {
                    "min_a": int, "max_a": int,
                    "min_b": int, "max_b": int,
                    "range_changed": bool,
                }, ...
            },
        }, ...
    },
    "summary": {
        "total_ids_a": int, "total_ids_b": int,
        "shared_ids": int,
        "only_a_count": int, "only_b_count": int,
        "ids_with_byte_diffs": int,
        "ids_with_freq_diffs": int,
    },
}
```

**Frequency diff threshold**: 1.0 Hz (hardcoded `freq_diff_threshold`).

### `format_diff(results, ids_only=False) -> str`

Table showing IDs unique to each capture, then shared IDs with byte-range changes.
If `ids_only=True`, only the ID presence summary is printed (byte-range section skipped).

---

## timeseries.py — Signal Extraction

Extracts a multi-byte signal from one CAN ID as a time series.

### `extract_timeseries(frames, target_id, byte_start, byte_count=1, endian="big", signed=False, bus_filter=None) -> list[tuple[float, int]]`

- `byte_start` / `byte_count`: 0-indexed byte range (1–4 bytes)
- `endian`: `"big"` or `"little"`
- `signed`: if True, applies two's complement interpretation
- Returns: list of `(timestamp_seconds, integer_value)` tuples

### `save_timeseries_csv(data, path, header="timestamp,value") -> None`

Writes `(timestamp, value)` tuples to CSV. Timestamps formatted to 6 decimal places. Creates parent directories if needed.
