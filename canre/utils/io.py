"""Streaming file reading utilities for large CAN log files."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator


def stream_lines(path: Path | str) -> Iterator[str]:
    """Yield lines from a file, handling encoding issues gracefully.

    Tries UTF-8 first; falls back to Latin-1 (which never raises a
    decode error since every byte is a valid Latin-1 character).

    Lines are yielded with trailing newline stripped.
    """
    path = Path(path)

    try:
        fh = open(path, "r", encoding="utf-8")
    except UnicodeDecodeError:
        fh = open(path, "r", encoding="latin-1")

    try:
        for line in fh:
            yield line.rstrip("\n\r")
    except UnicodeDecodeError:
        # UTF-8 failed mid-stream -- reopen as Latin-1 from the start.
        fh.close()
        fh = open(path, "r", encoding="latin-1")
        for line in fh:
            yield line.rstrip("\n\r")
    finally:
        fh.close()


def count_lines(path: Path | str) -> int:
    """Quickly count lines in a file for progress reporting.

    Uses a large binary read buffer for speed -- avoids the overhead of
    Python-level line iteration and encoding.
    """
    path = Path(path)
    count = 0
    buf_size = 1 << 20  # 1 MiB

    with open(path, "rb") as fh:
        while True:
            buf = fh.read(buf_size)
            if not buf:
                break
            count += buf.count(b"\n")

    return count
