"""PreCompact hook: turn Claude Code's idle compaction into a self-compaction.

Claude Code compacts a session of 200K tokens or more that has been idle
about 54 minutes, with no instructions. This hook blocks the first such
attempt and wakes the session to self-compact with tools/session_compact.py
(AGENTS.md, "Compacting your own context"; installed at the user's request,
2026-10-26). If no compaction follows, the next attempt goes through as a
plain one. Adapted from the canbus-esp-fw-vtrux repo's
.claude/skills/self-compact/idle_compact_hook.py.

Installed on the Linux box only, in ~/.claude/settings.json, not in this
folder's .claude/ settings, because those sync to every machine. Two entries
under PreCompact, matcher "auto":
  block  sync: exit 2 blocks, if the session has been idle IDLE_MIN or more
         and nothing was blocked since its last compaction. Otherwise exit 0.
  wake   "asyncRewake": true, "timeout": 60: exit 2 with the message on
         stderr, only if block's last run, just now, blocked.
Each command checks that the session is in reverse-it, and that the script
exists, because python exits 2 when it can't open the script, and
PreCompact reads exit 2 as a block:
  [ "$CLAUDE_PROJECT_DIR" = <home>/Seafile/NotGit/reverse-it ] || exit 0; S="$CLAUDE_PROJECT_DIR/tools/idle_compact_hook.py"; test -f "$S" || exit 0; python3.13 "$S" block
and the same with wake.
A limit compaction happens mid-turn, so it is never idle and always passes.
Any error exits 0, so this hook can never block by accident. State and log
are regenerable, so they stay out of Seafile:
<temp>/reverse-it-session-compact/idle-hook/ (/tmp on madhouse).
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

IDLE_MIN = 40
WAKE_WINDOW_S = 30
STATE_DIR = os.path.join(tempfile.gettempdir(), "reverse-it-session-compact", "idle-hook")
WAKE_TEXT = (
    "IDLE-COMPACTION HOOK, installed at the user's request (2026-10-26), so"
    " this is the user asking: Claude Code tried to compact this idle session"
    " (about 54 min since the last request) with no instructions, and this"
    " hook blocked that once. Self-compact now, per AGENTS.md \"Compacting"
    " your own context\": write what is worth keeping to its files, then run"
    " tools/session_compact.py with a compact message and a resume message as"
    " that section says. If you can't (no tmux on Linux, Claude Desktop, or"
    " auto mode blocks it), reply with one line saying why and stop; the next"
    " idle compaction will go through as a plain one."
)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def read_transcript(path):
    last = boundary = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") in ("user", "assistant") and e.get("timestamp"):
                last = ts(e["timestamp"])
            if e.get("subtype") == "compact_boundary" and e.get("timestamp"):
                boundary = ts(e["timestamp"])
    return last, boundary


def read_state(state):
    if not os.path.exists(state):
        return {}
    with open(state, encoding="utf-8") as f:
        return json.load(f)


def run(kind, d, log):
    now = datetime.now(timezone.utc)
    last, boundary = read_transcript(d["transcript_path"])
    age = (now - last).total_seconds() / 60 if last else 0.0
    idle = age >= IDLE_MIN
    os.makedirs(STATE_DIR, exist_ok=True)
    state = os.path.join(STATE_DIR, d["session_id"] + ".json")
    if kind == "block":
        st = read_state(state)
        prev = ts(st["last_block"]) if st.get("last_block") else None
        already = prev is not None and (boundary is None or boundary < prev)
        act = idle and not already
        st["last_attempt"] = now.isoformat()
        st["blocked"] = act
        if act:
            st["last_block"] = now.isoformat()
        with open(state, "w", encoding="utf-8") as f:
            json.dump(st, f)
    else:
        time.sleep(3)
        st = read_state(state)
        recent = (st.get("last_attempt") and
                  abs((now - ts(st["last_attempt"])).total_seconds()) < WAKE_WINDOW_S)
        act = bool(recent and st.get("blocked"))
    log.append("%s %s trigger=%s idle_min=%.1f act=%s" % (
        now.isoformat(timespec="seconds"), kind, d.get("trigger"), age, act))
    return act


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    log = []
    try:
        d = json.loads(sys.stdin.read())
        if kind not in ("block", "wake") or d.get("trigger") != "auto":
            return 0
        act = run(kind, d, log)
    except Exception as exc:  # never block by accident
        log.append("%s %s error %r" % (time.strftime("%H:%M:%S"), kind, exc))
        act = False
    if log:
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(os.path.join(STATE_DIR, "hook.log"), "a", encoding="utf-8") as f:
                f.write("\n".join(log) + "\n")
        except OSError:
            pass
    if not act:
        return 0
    if kind == "block":
        sys.stderr.write("Idle compaction blocked once; the session is asked to self-compact.")
    else:
        sys.stderr.write(WAKE_TEXT)
    return 2


if __name__ == "__main__":
    sys.exit(main())
