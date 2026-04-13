"""State/event detection for CAN bus signals.

Detects three kinds of behaviour per byte position:
  1. **Abrupt changes** -- large value jumps (delta > threshold).
  2. **State machines** -- a small number of discrete values with
     well-defined transitions between them.
  3. **Pulse events** -- value briefly departs from a baseline and returns.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterator

from canre.parsers.base import CANFrame

# ---- Configuration defaults ----
_ABRUPT_THRESHOLD = 10        # minimum delta to flag as "abrupt"
_STATE_MAX_UNIQUE = 16        # if unique values <= this, treat as state machine
_PULSE_RETURN_WINDOW = 5      # frames to check for return-to-baseline


def detect_transitions(
    frames: Iterator[CANFrame],
    target_id: int,
    bus_filter: int | None = None,
    abrupt_threshold: int = _ABRUPT_THRESHOLD,
    state_max_unique: int = _STATE_MAX_UNIQUE,
    pulse_return_window: int = _PULSE_RETURN_WINDOW,
) -> dict:
    """Detect transitions, state machines, and pulse events for an ID.

    Parameters
    ----------
    frames:
        Iterator of CANFrame objects.
    target_id:
        The arbitration ID to analyse.
    bus_filter:
        If set, only consider frames on this bus.
    abrupt_threshold:
        Minimum absolute delta between consecutive values to flag as
        an abrupt change.
    state_max_unique:
        Maximum number of unique values to consider a byte position
        a "state machine".
    pulse_return_window:
        Number of frames after a departure from baseline within which
        the value must return to count as a "pulse".

    Returns
    -------
    dict with structure::

        {
            "frame_count": int,
            "bytes": {
                "0": {
                    "abrupt_changes": [
                        {"frame_idx": int, "timestamp": float,
                         "from": int, "to": int, "delta": int},
                        ...
                    ],
                    "state_machine": {
                        "is_state_machine": bool,
                        "states": list[int],
                        "transitions": {
                            "from_val -> to_val": count,
                            ...
                        },
                    },
                    "pulses": [
                        {"frame_idx": int, "timestamp": float,
                         "baseline": int, "peak": int, "duration_frames": int},
                        ...
                    ],
                },
                ...
            },
        }
    """
    # ---- Collect per-byte value sequences ----
    # We store (timestamp, value) per byte position, plus the global
    # frame index.
    byte_sequences: dict[int, list[tuple[int, float, int]]] = {}
    frame_count = 0

    for frame in frames:
        if frame.arbitration_id != target_id:
            continue
        if bus_filter is not None and frame.bus != bus_filter:
            continue

        dlc = min(frame.dlc, len(frame.data))
        for i in range(dlc):
            val = frame.data[i]
            seq = byte_sequences.get(i)
            if seq is None:
                seq = []
                byte_sequences[i] = seq
            seq.append((frame_count, frame.timestamp, val))

        frame_count += 1

    # ---- Analyse each byte position ----
    bytes_out: dict[str, dict] = {}

    for pos in sorted(byte_sequences):
        seq = byte_sequences[pos]
        values = [v for (_, _, v) in seq]

        # -- Abrupt changes --
        abrupt_changes: list[dict] = []
        for k in range(1, len(seq)):
            idx_prev, _, val_prev = seq[k - 1]
            idx_cur, ts_cur, val_cur = seq[k]
            delta = val_cur - val_prev
            if abs(delta) >= abrupt_threshold:
                abrupt_changes.append({
                    "frame_idx": idx_cur,
                    "timestamp": round(ts_cur, 6),
                    "from": val_prev,
                    "to": val_cur,
                    "delta": delta,
                })

        # -- State machine detection --
        unique_vals = sorted(set(values))
        is_state_machine = len(unique_vals) <= state_max_unique and len(unique_vals) > 1

        transitions_counter: Counter = Counter()
        if is_state_machine:
            for k in range(1, len(values)):
                if values[k] != values[k - 1]:
                    key = f"{values[k - 1]} -> {values[k]}"
                    transitions_counter[key] += 1

        state_machine_info: dict = {
            "is_state_machine": is_state_machine,
            "states": unique_vals if is_state_machine else [],
            "transitions": dict(transitions_counter.most_common()) if is_state_machine else {},
        }

        # -- Pulse detection --
        # Baseline = most common value (mode).
        val_counter = Counter(values)
        baseline = val_counter.most_common(1)[0][0] if val_counter else 0
        baseline_pct = val_counter[baseline] / len(values) if values else 0

        pulses: list[dict] = []
        # Only look for pulses if there is a clear baseline (>60% of samples).
        if baseline_pct > 0.6:
            k = 0
            while k < len(seq):
                idx_k, ts_k, val_k = seq[k]
                if val_k != baseline:
                    # Departure from baseline -- look for return.
                    pulse_start = k
                    peak = val_k
                    returned = False
                    for j in range(k + 1, min(k + 1 + pulse_return_window, len(seq))):
                        _, _, val_j = seq[j]
                        if abs(val_j) > abs(peak) or (abs(val_j) == abs(peak) and val_j != peak):
                            peak = val_j if abs(val_j) > abs(peak) else peak
                        if val_j == baseline:
                            pulses.append({
                                "frame_idx": idx_k,
                                "timestamp": round(ts_k, 6),
                                "baseline": baseline,
                                "peak": peak,
                                "duration_frames": j - pulse_start,
                            })
                            k = j
                            returned = True
                            break
                    if not returned:
                        k += 1
                    else:
                        k += 1
                else:
                    k += 1

        bytes_out[str(pos)] = {
            "abrupt_changes": abrupt_changes,
            "state_machine": state_machine_info,
            "pulses": pulses,
        }

    return {
        "frame_count": frame_count,
        "bytes": bytes_out,
    }


def format_transitions(results: dict) -> str:
    """Pretty-print transition analysis results."""
    lines: list[str] = []

    lines.append(f"Transition Analysis ({results['frame_count']:,} frames)")
    lines.append("")

    bytes_info = results.get("bytes", {})
    if not bytes_info:
        lines.append("(no data)")
        return "\n".join(lines)

    for pos in sorted(bytes_info, key=int):
        info = bytes_info[pos]
        lines.append(f"--- Byte {pos} ---")

        # State machine.
        sm = info.get("state_machine", {})
        if sm.get("is_state_machine"):
            states = sm.get("states", [])
            lines.append(
                f"  State machine: YES  ({len(states)} states: "
                f"{', '.join(f'0x{s:02X}' for s in states)})"
            )
            transitions = sm.get("transitions", {})
            if transitions:
                lines.append("  Transitions:")
                for trans, count in sorted(transitions.items(), key=lambda t: -t[1]):
                    lines.append(f"    {trans}  ({count}x)")
        else:
            lines.append("  State machine: no")

        # Abrupt changes.
        abrupt = info.get("abrupt_changes", [])
        lines.append(f"  Abrupt changes: {len(abrupt)}")
        if abrupt:
            # Show first 10.
            for ac in abrupt[:10]:
                lines.append(
                    f"    t={ac['timestamp']:.4f}  "
                    f"0x{ac['from']:02X} -> 0x{ac['to']:02X}  "
                    f"(delta={ac['delta']:+d})"
                )
            if len(abrupt) > 10:
                lines.append(f"    ... and {len(abrupt) - 10} more")

        # Pulses.
        pulses = info.get("pulses", [])
        lines.append(f"  Pulses: {len(pulses)}")
        if pulses:
            for p in pulses[:10]:
                lines.append(
                    f"    t={p['timestamp']:.4f}  "
                    f"baseline=0x{p['baseline']:02X}  "
                    f"peak=0x{p['peak']:02X}  "
                    f"duration={p['duration_frames']} frames"
                )
            if len(pulses) > 10:
                lines.append(f"    ... and {len(pulses) - 10} more")

        lines.append("")

    return "\n".join(lines)
