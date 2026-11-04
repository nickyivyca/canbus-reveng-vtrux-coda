"""The Android apps from this folder's side: where their git clone is, and
the sync token they share.

The Android apps left this folder for a private git repo on 2026-10-30
(android-app/notes/plans/private-git-migration.md). Scripts here that read
or write the app tree resolve it through android_apps_repo() instead of a
path relative to the reverse-it root, and scripts that talk to the apps'
servers read the token through sync_token() instead of hard-coding it.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CLONE = Path.home() / "Git" / "android-canbus-apps"
SECRETS_FILE = Path(__file__).resolve().parents[2] / "android-app" / "secrets" / "android.properties"


def android_apps_repo() -> Path:
    """Return the clone's root: $ANDROID_APPS_REPO if set, else
    ~/Git/android-canbus-apps, the clone path on every machine.
    Exits with a message if no clone is there."""
    env = os.environ.get("ANDROID_APPS_REPO")
    repo = Path(env).expanduser() if env else DEFAULT_CLONE
    if not (repo / "CanLoggerApps").is_dir():
        raise SystemExit(
            f"android-canbus-apps clone not found at {repo}: clone "
            "github.com/nickyivyca/android-canbus-apps there, or set ANDROID_APPS_REPO"
        )
    return repo


def sync_token() -> str:
    """Return the apps' sync token (`sync.token` in android-app/secrets/
    android.properties). Never print it. Exits with a message if missing."""
    if SECRETS_FILE.is_file():
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "sync.token" and value.strip():
                return value.strip()
    raise SystemExit(f"sync.token not found in {SECRETS_FILE}")
