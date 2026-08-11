#!/usr/bin/env python3
"""Generate parity test cases for cancore's DbcParityTest.

For each Vtrux DBC, copies the DBC into cancore's test resources, generates
N random byte payloads per non-multiplexed message and per mux value of
multiplexed messages, decodes them with cantools, and writes a flat TSV the
Kotlin test consumes from the classpath.

TSV columns (tab-separated):
    dbc_basename
    message_id_decimal
    payload_hex
    signal1=value1;signal2=value2;...

Run from project root:
    py -3.12 tools/dbc_parity_generate.py
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

import cantools

DEFAULT_DBCS = [
    "projects/vtrux/epri-pt-bus.dbc",
    "projects/vtrux/epri-obd-bus.dbc",
    "projects/vtrux/BelInverter-v2.dbc",
    "projects/vtrux/GMW8762_PPEI_GMLAN.dbc",
]
DEFAULT_OUT_DIR = Path(
    "android-app/CanLoggerApps/cancore/src/test/resources"
)


def _format_value(v) -> str:
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        # Enough precision to round-trip a double; trim trailing zeros so the
        # diff is friendlier when regenerating.
        return f"{v:.10g}"
    try:
        return str(int(v))
    except Exception:
        return str(v)


def _gen_payload(message, mux_value: int | None, rng: random.Random) -> bytes:
    payload = bytearray(rng.randrange(0, 256) for _ in range(message.length))
    if mux_value is None:
        return bytes(payload)
    # Find the multiplexer signal and force its bits to mux_value.
    muxer = next(
        (s for s in message.signals if s.is_multiplexer),
        None,
    )
    if muxer is None:
        return bytes(payload)
    return _set_signal_bits(message, payload, muxer, mux_value)


def _set_signal_bits(message, data: bytearray, signal, value: int) -> bytes:
    """Directly inject `value` into `signal`'s bit field within `data`."""
    if signal.byte_order in ("little_endian", "intel"):
        return _force_intel_bits(data, signal.start, signal.length, value)
    return _force_motorola_bits(data, signal.start, signal.length, value)


def _force_intel_bits(data: bytearray, start_bit: int, length: int, value: int) -> bytes:
    out = bytearray(data)
    mask = (1 << length) - 1
    value &= mask
    for i in range(length):
        byte_idx = (start_bit + i) // 8
        bit_in_byte = (start_bit + i) % 8
        bit = (value >> i) & 1
        if byte_idx >= len(out):
            break
        out[byte_idx] = (out[byte_idx] & ~(1 << bit_in_byte)) | (bit << bit_in_byte)
    return bytes(out)


def _force_motorola_bits(data: bytearray, start_bit: int, length: int, value: int) -> bytes:
    out = bytearray(data)
    mask = (1 << length) - 1
    value &= mask
    bit_pos = start_bit
    for i in range(length):
        byte_idx = bit_pos // 8
        bit_in_byte = bit_pos % 8
        bit = (value >> (length - 1 - i)) & 1
        if byte_idx < len(out):
            out[byte_idx] = (out[byte_idx] & ~(1 << bit_in_byte)) | (bit << bit_in_byte)
        bit_pos = bit_pos + 15 if bit_in_byte == 0 else bit_pos - 1
    return bytes(out)


def _mux_values(message) -> list[int]:
    seen: set[int] = set()
    for s in message.signals:
        ids = s.multiplexer_ids
        if ids:
            for v in ids:
                seen.add(int(v))
    return sorted(seen)


def _process_dbc(
    dbc_path: Path,
    out_dbc_dir: Path,
    cases_per_subcase: int,
    rng: random.Random,
) -> list[str]:
    db = cantools.database.load_file(str(dbc_path), strict=False)
    basename = dbc_path.name
    shutil.copy2(dbc_path, out_dbc_dir / basename)

    lines: list[str] = []
    for msg in db.messages:
        is_muxed = any(s.is_multiplexer for s in msg.signals)
        mux_values = _mux_values(msg) if is_muxed else [None]

        for mv in mux_values:
            for _ in range(cases_per_subcase):
                payload = _gen_payload(msg, mv, rng)
                try:
                    decoded = msg.decode(payload, decode_choices=False)
                except Exception as e:
                    # Skip cases cantools refuses to decode (e.g., out-of-range
                    # signed value triggering a strict-mode warning).
                    continue
                if hasattr(decoded, "items"):
                    items = list(decoded.items())
                else:
                    items = list(decoded)

                sig_strs: list[str] = []
                for name, val in items:
                    sig_strs.append(f"{name}={_format_value(val)}")
                hex_payload = payload.hex().upper()
                lines.append(
                    f"{basename}\t{msg.frame_id}\t{hex_payload}\t{';'.join(sig_strs)}"
                )
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate DBC parity test cases")
    ap.add_argument("--dbc", action="append", default=None,
                    help="DBC path (repeatable). Defaults to all Vtrux DBCs.")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR,
                    help="cancore test resources directory")
    ap.add_argument("--cases", type=int, default=30,
                    help="Random payloads per message (per mux value for muxed)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    dbcs = [Path(p) for p in (args.dbc or DEFAULT_DBCS)]
    out_dir: Path = args.output_dir
    out_dbcs = out_dir / "dbcs"
    out_dbcs.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    all_lines: list[str] = [
        "# DBC parity test cases. Regenerate via tools/dbc_parity_generate.py.",
        "# Columns (tab-separated): dbc_basename\tmessage_id\tpayload_hex\tsig=val;sig=val;...",
        f"# seed={args.seed} cases_per_subcase={args.cases}",
    ]
    for path in dbcs:
        if not path.exists():
            raise SystemExit(f"DBC not found: {path}")
        print(f"processing {path} -> {out_dbcs / path.name}")
        all_lines += _process_dbc(path, out_dbcs, args.cases, rng)

    out_tsv = out_dir / "dbc_parity_cases.tsv"
    out_tsv.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    print(f"wrote {len(all_lines) - 3} cases to {out_tsv}")


if __name__ == "__main__":
    main()
