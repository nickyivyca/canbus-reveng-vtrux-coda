"""Counter and checksum detection for CAN bus frames.

Detects rolling counters (byte-level and nibble-level) and common
CRC/checksum algorithms applied per-message.
"""
from __future__ import annotations

from typing import Iterator

from canre.parsers.base import CANFrame

# CRC-8 SAE J1850 lookup table.
_CRC8_J1850_TABLE: list[int] = []


def _init_crc8_table() -> None:
    """Build the CRC-8 SAE J1850 lookup table (poly=0x1D, init=0xFF)."""
    if _CRC8_J1850_TABLE:
        return
    poly = 0x1D
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
        _CRC8_J1850_TABLE.append(crc)


def _crc8_j1850(data: bytes) -> int:
    """Compute CRC-8 SAE J1850 over *data*."""
    _init_crc8_table()
    crc = 0xFF
    for b in data:
        crc = _CRC8_J1850_TABLE[crc ^ b]
    return crc ^ 0xFF


def detect_counters(
    frames: Iterator[CANFrame],
    target_id: int,
    bus_filter: int | None = None,
) -> dict:
    """Detect rolling counters in a single CAN ID's data stream.

    Checks both byte-level (8-bit, mod 256) and nibble-level (4-bit,
    mod 16) counters in the high and low nibble of each byte.

    Parameters
    ----------
    frames:
        Iterator of CANFrame objects.
    target_id:
        The arbitration ID to analyse.
    bus_filter:
        If set, only consider frames on this bus.

    Returns
    -------
    dict with structure::

        {
            "frame_count": int,
            "byte_counters": {
                "0": {"is_counter": bool, "confidence": float, "direction": "up"|"down"},
                ...
            },
            "nibble_counters": {
                "0_high": {"is_counter": bool, "confidence": float, "direction": "up"|"down"},
                "0_low":  {"is_counter": bool, "confidence": float, "direction": "up"|"down"},
                ...
            },
        }
    """
    # We need to track the previous value and count increments.
    # byte-level
    prev_byte: dict[int, int | None] = {}
    byte_inc_up: dict[int, int] = {}      # +1 mod 256
    byte_inc_down: dict[int, int] = {}    # -1 mod 256
    byte_transitions: dict[int, int] = {}

    # nibble-level  (keyed by "{pos}_high" / "{pos}_low")
    prev_nibble: dict[str, int | None] = {}
    nibble_inc_up: dict[str, int] = {}
    nibble_inc_down: dict[str, int] = {}
    nibble_transitions: dict[str, int] = {}

    frame_count = 0

    for frame in frames:
        if frame.arbitration_id != target_id:
            continue
        if bus_filter is not None and frame.bus != bus_filter:
            continue

        frame_count += 1
        dlc = min(frame.dlc, len(frame.data))

        for i in range(dlc):
            val = frame.data[i]

            # ---- Byte-level ----
            if i not in prev_byte:
                prev_byte[i] = None
                byte_inc_up[i] = 0
                byte_inc_down[i] = 0
                byte_transitions[i] = 0

            if prev_byte[i] is not None:
                byte_transitions[i] += 1
                expected_up = (prev_byte[i] + 1) & 0xFF
                expected_down = (prev_byte[i] - 1) & 0xFF
                if val == expected_up:
                    byte_inc_up[i] += 1
                if val == expected_down:
                    byte_inc_down[i] += 1
            prev_byte[i] = val

            # ---- Nibble-level ----
            high_nib = (val >> 4) & 0x0F
            low_nib = val & 0x0F
            for suffix, nib_val, mod in [("high", high_nib, 16), ("low", low_nib, 16)]:
                nkey = f"{i}_{suffix}"
                if nkey not in prev_nibble:
                    prev_nibble[nkey] = None
                    nibble_inc_up[nkey] = 0
                    nibble_inc_down[nkey] = 0
                    nibble_transitions[nkey] = 0

                if prev_nibble[nkey] is not None:
                    nibble_transitions[nkey] += 1
                    exp_up = (prev_nibble[nkey] + 1) % mod
                    exp_down = (prev_nibble[nkey] - 1) % mod
                    if nib_val == exp_up:
                        nibble_inc_up[nkey] += 1
                    if nib_val == exp_down:
                        nibble_inc_down[nkey] += 1
                prev_nibble[nkey] = nib_val

    # ---- Build output ----
    threshold = 0.85  # minimum confidence to flag as counter

    byte_counters: dict[str, dict] = {}
    for i in sorted(prev_byte):
        total = byte_transitions[i]
        if total == 0:
            byte_counters[str(i)] = {
                "is_counter": False,
                "confidence": 0.0,
                "direction": "none",
            }
            continue

        conf_up = byte_inc_up[i] / total
        conf_down = byte_inc_down[i] / total

        if conf_up >= conf_down:
            best_conf = conf_up
            direction = "up"
        else:
            best_conf = conf_down
            direction = "down"

        byte_counters[str(i)] = {
            "is_counter": best_conf >= threshold,
            "confidence": round(best_conf, 4),
            "direction": direction if best_conf >= threshold else "none",
        }

    nibble_counters: dict[str, dict] = {}
    for nkey in sorted(prev_nibble):
        total = nibble_transitions[nkey]
        if total == 0:
            nibble_counters[nkey] = {
                "is_counter": False,
                "confidence": 0.0,
                "direction": "none",
            }
            continue

        conf_up = nibble_inc_up[nkey] / total
        conf_down = nibble_inc_down[nkey] / total

        if conf_up >= conf_down:
            best_conf = conf_up
            direction = "up"
        else:
            best_conf = conf_down
            direction = "down"

        nibble_counters[nkey] = {
            "is_counter": best_conf >= threshold,
            "confidence": round(best_conf, 4),
            "direction": direction if best_conf >= threshold else "none",
        }

    return {
        "frame_count": frame_count,
        "byte_counters": byte_counters,
        "nibble_counters": nibble_counters,
    }


def detect_checksums(
    frames: list[CANFrame],
    target_id: int,
) -> dict:
    """Detect common checksum/CRC algorithms applied per-message.

    Tries each byte position as a potential checksum and tests against:
      - XOR of all other bytes
      - Sum of all other bytes (mod 256)
      - CRC-8 SAE J1850 of all other bytes
      - Nibble sum of all other bytes (mod 256)

    Parameters
    ----------
    frames:
        **List** of CANFrame objects (needs multiple passes).
    target_id:
        The arbitration ID to analyse.

    Returns
    -------
    dict mapping byte position (str) to algorithm match results::

        {
            "frame_count": int,
            "checksums": {
                "0": {
                    "xor":        {"matches": int, "total": int, "confidence": float},
                    "sum":        {"matches": int, "total": int, "confidence": float},
                    "crc8_j1850": {"matches": int, "total": int, "confidence": float},
                    "nibble_sum": {"matches": int, "total": int, "confidence": float},
                    "best": str | None,       # name of best algorithm if confidence > 0.95
                    "best_confidence": float,
                },
                ...
            }
        }
    """
    # Filter to target ID.
    target_frames = [f for f in frames if f.arbitration_id == target_id]

    if not target_frames:
        return {"frame_count": 0, "checksums": {}}

    # Determine max DLC.
    max_dlc = max(min(f.dlc, len(f.data)) for f in target_frames)

    checksums_out: dict[str, dict] = {}

    for ckpos in range(max_dlc):
        algo_results: dict[str, dict] = {}

        for algo_name in ("xor", "sum", "crc8_j1850", "nibble_sum"):
            matches = 0
            total = 0

            for frame in target_frames:
                dlc = min(frame.dlc, len(frame.data))
                if ckpos >= dlc:
                    continue
                total += 1

                actual = frame.data[ckpos]
                other_bytes = bytes(
                    frame.data[i] for i in range(dlc) if i != ckpos
                )

                if algo_name == "xor":
                    expected = 0
                    for b in other_bytes:
                        expected ^= b
                elif algo_name == "sum":
                    expected = sum(other_bytes) & 0xFF
                elif algo_name == "crc8_j1850":
                    expected = _crc8_j1850(other_bytes)
                elif algo_name == "nibble_sum":
                    nib_sum = 0
                    for b in other_bytes:
                        nib_sum += (b >> 4) + (b & 0x0F)
                    expected = nib_sum & 0xFF
                else:
                    expected = -1

                if actual == expected:
                    matches += 1

            confidence = matches / total if total > 0 else 0.0
            algo_results[algo_name] = {
                "matches": matches,
                "total": total,
                "confidence": round(confidence, 4),
            }

        # Determine best algorithm.
        best_name: str | None = None
        best_confidence = 0.0
        for name, res in algo_results.items():
            if res["confidence"] > best_confidence:
                best_confidence = res["confidence"]
                best_name = name

        if best_confidence < 0.95:
            best_name = None

        algo_results["best"] = best_name  # type: ignore[assignment]
        algo_results["best_confidence"] = best_confidence  # type: ignore[assignment]
        checksums_out[str(ckpos)] = algo_results

    return {
        "frame_count": len(target_frames),
        "checksums": checksums_out,
    }
