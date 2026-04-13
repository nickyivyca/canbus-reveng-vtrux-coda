"""Session grouping utilities for CAN log files.

Provides functions to discover and group log files by session patterns.
"""
import os
import re
from collections import defaultdict
from pathlib import Path


def group_files_by_session(folder: Path) -> dict[str, list[Path]]:
    """Group log files by session.

    Files are grouped into sessions based on naming patterns:
    - Files matching _M#_T# pattern are grouped by M number
    - Files with time gaps >1 hour are split into sub-sessions (M0_a, M0_b, etc.)
    - Files NOT matching the pattern become single-file sessions

    Args:
        folder: Directory containing log files

    Returns:
        Dictionary mapping session name to list of file paths
        Example: {"M0": [path1, path2], "full charge then fail": [path3]}
    """
    pattern = re.compile(r"_M(\d+)_T(\d+)", re.IGNORECASE)

    # Track which files match the M_T pattern
    matched_files = set()
    by_m = defaultdict(list)  # m_num -> [(t_num, mtime, path), ...]

    for f in sorted(folder.glob("*.log")):
        m = pattern.search(f.name)
        if m:
            matched_files.add(f)
            m_num = int(m.group(1))
            t_num = int(m.group(2))
            mtime = os.path.getmtime(f)
            by_m[m_num].append((t_num, mtime, f))

    sessions = {}

    # Process M_T pattern files - group by M, split on time gaps
    for m_num in sorted(by_m):
        entries = sorted(by_m[m_num], key=lambda x: (x[1], x[0]))  # sort by mtime, then T

        # Split on mtime gaps > 1 hour
        sub_sessions = []
        current = [entries[0]]
        for i in range(1, len(entries)):
            gap = abs(entries[i][1] - entries[i-1][1])
            if gap > 3600:
                sub_sessions.append(current)
                current = [entries[i]]
            else:
                current.append(entries[i])
        sub_sessions.append(current)

        for si, sub in enumerate(sub_sessions):
            # Re-sort each sub-session by T number for correct chaining
            sub.sort(key=lambda x: x[0])
            if len(sub_sessions) == 1:
                key = f"M{m_num}"
            else:
                key = f"M{m_num}_{chr(ord('a') + si)}"
            sessions[key] = [path for _, _, path in sub]

    # Add non-M_T files as single-file sessions
    for f in sorted(folder.glob("*.log")):
        if f not in matched_files:
            # Use filename without extension as session name
            session_name = f.stem
            sessions[session_name] = [f]

    return sessions


def list_session_files(folder: Path) -> tuple[dict[str, list[Path]], list[Path]]:
    """List all session files in a directory.

    Returns:
        Tuple of (grouped_sessions, standalone_files)
        - grouped_sessions: M_T pattern files grouped by session
        - standalone_files: Files that don't match the pattern
    """
    sessions = group_files_by_session(folder)

    # Separate into multi-file sessions and standalone files
    grouped = {}
    standalone = []

    for name, files in sessions.items():
        if len(files) > 1 or "_M" in name:
            grouped[name] = files
        else:
            standalone.extend(files)

    return grouped, standalone
