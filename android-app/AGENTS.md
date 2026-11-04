# Agent instructions: android-canbus-apps

This repo holds the Android apps that log and display CAN data on the Coda,
the Vtrux and the Porsche 914 EV, and their development notes.

| Path | What |
|---|---|
| `CanLoggerApps/` | The Gradle multi-module project. `:cancore` (shared library: gs_usb and SLCAN transports, pipeline, logging service, log file server, display server), `:display` (live display UI), `:tpms` (Coda indirect TPMS), and the apps `:coda`, `:vtrux`, `:p914` and `:companion` (flavours `coda` and `vtrux`) |
| `CanReaderApp/` | The original gs_usb proof of concept |
| `notes/` | Development notes, plans and protocols. Start at `notes/README.md` |
| `tools/` | The `:tpms` parity generators (`tpms_*_parity.py`), which hold the port to its Python prototype in reverse-it. See `tools/README.md` |
| `android-coda-app-notes.md`, `android-coda-tpms-implementation.md`, `android-otg-power-cycling.md` | Per-topic notes kept at the top level |
| `local-paths.template.md` | The template for this clone's `local-paths.md` |
| `.claude/skills/` | Claude Code skills: `self-compact` (see "Compacting your own context") |

**This repo is private only because of its GM-derived content** (the GMLAN
DBCs and what is derived from them; owner, 2026-10-30). Otherwise keep out
of it what would not belong in a public repo (see "Pushing").

## Local paths: `local-paths.md`

Anything that differs per machine is in `local-paths.md` at the root of this
clone: the Python command, the JDK and Android SDK, how `gradlew` is invoked,
this machine's `REVERSE_IT_DIR`, and where `reverseit.secretsDir` is set. It
is gitignored and filled in on each machine. Read it before running Python,
a build or a device command. If it is missing, copy
`local-paths.template.md` to it and follow the template's text.

Per-machine tool paths are never committed here. Their reference is
`../android-app/android-tools-reference.md`, in Seafile.

## Reverse-it: the project behind this repo

Raw CAN logs, the vehicle DBCs and notes, the analysis tools, and the
Android material kept out of git live in the reverse-it project folder in
Seafile, at `..` (also in `local-paths.md`; if unset, ask the
user). Kept at `../android-app/`, never in this repo:

| Path | What |
|---|---|
| `secrets/` | The sync token (`android.properties`) and the signing keystore (`debug.keystore`) |
| `android-tools-reference.md` | Per-machine tool paths, and the Coda head unit dropoff |
| `notes/artifacts/` | Run output, test-rig scripts and evidence the notes cite |
| `notes/plans/private-git-migration.md` | The plan that moved these apps from Seafile to git |
| `history-pre-git/` | Every change from 2026-03-21 to the git import, rebuilt from Seafile history |

**Paths in the notes.** `android-app/<x>` means `<x>` in this repo, except
the five entries above, which mean `../android-app/<x>` (so the
notes' links into `artifacts/` resolve in Seafile). `tools/tpms_*_parity.py`
is this repo's `tools/`. Any other reverse-it path (`tools/...`, `canre/...`,
`projects/...`, `../../projects/...`) means `../<x>`.

**This repo is the only source.** The Seafile copies of the source and
notes were deleted on 2026-11-03; Seafile history and
`../android-app/history-pre-git/` keep the pre-git history.

**Work on reverse-it's data** (logs, DBCs, InfluxDB) follows
`../AGENTS.md`: read it in full first. Its tools and
scratchpads run from its root, so `cd ".."` before running
them, and their output goes to its `artifacts/` folders, normally
`android-app/notes/artifacts/`, not into this clone. The CAN replayer and
logger live in the `can-tools` clone; pull it before use (reverse-it
`AGENTS.md`, "can-tools").

## Builds

- **The token and the keystore come from the secrets folder,** named by the
  Gradle property `reverseit.secretsDir` in `~/.gradle/gradle.properties`.
  A missing keystore fails the build, and must: never let a build fall back
  to `~/.android/debug.keystore`. A missing token does not fail it; the
  build silently uses `DEV_TOKEN_UNSET`, and the companion and the log file
  server then refuse each other.
- **One keystore signs every APK,** debug and release, so a build from any
  machine installs over what is in the cars and keeps their data. Its
  certificate SHA-256 is
  `88:F3:FF:6C:45:1E:3B:6A:C9:AE:0A:BB:E3:35:2C:8A:81:4D:D2:91:DF:90:0F:2D:BE:60:60:12:F2:AD:28:5D`
  (`apksigner verify --print-certs <apk>`).
- **Car and in-use phone loads are release builds** (`assembleRelease`,
  `notes/outstanding-changes.md` Change 15); debug builds are for the AVD
  and the bench. Bump `versionCode` / `versionName` for each set handed out.
- **Install over, never uninstall** (`adb install -r`): uninstalling wipes
  the app's permissions, logs and TPMS store.
- **The Coda head unit has no adb.** Builds go to it through a Drive
  dropoff (`android-tools-reference.md`). Every build gets the next unused
  number, `coda-release (N).apk`, and an existing name is never reused.
- **Never print the sync token.** Filter output that can carry it: a
  `uiautomator` dump of the companion's settings, and the startup log of
  reverse-it's `tools/can_display_server.py`.

## Tests

`:cancore`, `:tpms`, `:coda`, `:display` and `:p914` have unit tests
(`testDebugUnitTest`).

- **Some tests skip when an environment variable is unset,** which looks
  like a pass: `REVERSE_IT_DIR` and the `TPMS_*` / `SLCAN_*` variables in
  `CanLoggerApps/tpms/README.md`. Gradle does not track them, so run
  `:tpms:cleanTestDebugUnitTest` after changing one.
- **Generated test resources** are committed here. reverse-it's
  `tools/dbc_parity_generate.py`, `tools/slcan_parity_generate.py` and
  `tools/distill_dbcs.py` write into this clone, found through
  `canre.utils.android_repo` (`$ANDROID_APPS_REPO`, default
  `~/Git/android-canbus-apps`). The `:tpms` generators are in this repo's
  `tools/`; they run from the reverse-it root (`tools/README.md`).

## Devices and rigs

- **Leave the phones alone unless the user asks** -- the OnePlus 7T and
  the Pixel: target the AVD (`-s emulator-5554`). The AVD that stands in for the Coda head unit is in
  `notes/avd-emulator-bringup.md`.
- **Before transmitting on a bench or running a simulator,** read
  `../simulators.md`; the Linux box SocketCAN rig is in
  reverse-it's `tools-reference.md`.
- **The generator inhibitor's `0x7F1` status** is defined by the gen-inhibit
  project, not here (`notes/protocols/gen-inhibit-status-interface.md`).
  Take a contradiction to the user.

## Pushing

Commit and push to `main` directly (owner, 2026-11-03). Before a push, run
the leak scan on the tree being pushed, from the reverse-it root:

```bash
git -C <clone> archive HEAD | tar -C <scratch dir> -xf -
cd ".." && <python> artifacts/publish_leakscan.py --root <scratch dir>
```

Not on the clone itself (it walks `build/`). The standing hits are fine:
GM content, the machine names `the bench laptop`, `the Linux box` and
`Desktop`, and the `sdk.dir` placeholder line in
`notes/canlogger-build-notes.md`. Anything new -- a token, a home IP, a
work-machine name or path, a per-machine tool path, a VIN, personal
details -- stops the push and goes to the user. The Coda hotspot gateway
`192.168.43.8` and the emulator's `10.0.2.2` are fine.

## Compacting your own context: `/self-compact`

A session can compact its own context and resume without anyone at the
keyboard, with the `/self-compact` skill. It types `/compact` into this
session's terminal and then, once the compaction is done, one resume message
naming the next step. By default it resumes. A session sure that nothing
more is needed from it until a message, a task notification or the user
arrives may pass `--compact-only` instead, and then nothing is typed (user,
2026-10-31: a wedged session costs more than a needless resume, so when in
doubt, resume). It is the only sanctioned way for a session to type into its
own input. The skill mirrors the `canbus-esp-fw-vtrux` repo's copy; its
design and ownership are in `../../Infrastructure/tools/self-compact/`.

- **When:** only when the user asks for it, or when the idle-compaction
  hook asks for it (user, 2026-10-24).
- **The idle-compaction hook.** Claude Code compacts a session of 200K
  tokens or more that has been idle about 54 minutes, before its prompt
  cache expires, with no instructions. In this repo a PreCompact hook,
  `.claude/skills/self-compact/idle_compact_hook.py`, blocks the first such
  attempt and wakes the session with a message asking it to self-compact.
  Do it, per the skill. If you can't, say so in one line; the hook lets the
  next attempt through, as a plain compaction. Its two entries go in each
  machine's `.claude/settings.local.json`, in the guarded form its header
  gives.
- **Before it:** write everything worth keeping to its files. The summary
  loses detail; files do not.
- **After it:** the next turn starts from a summary. Re-read the docs per
  "Working rules" before acting.
- **If auto mode blocks it,** do not retry it, reword it or run it another
  way. Carry on without compacting and tell the user in one line.
- **Where it works:** in tmux on Linux, and in terminal Claude Code on
  Windows. Not in Claude Desktop.

The procedure, and the rules for the two messages, are in the skill.

## Working rules

- **Read this file and `local-paths.md` in full** at the start, and again
  after a compaction before acting: a summary records what the session did,
  not what the docs say. **Skills too:** a compaction re-attaches each
  skill invoked earlier as the text it had then, not the current
  `SKILL.md`, so re-read `.claude/skills/<name>/SKILL.md` in full for every
  skill invoked in the session before acting under it.
- **Every folder has an `.md` describing its contents.** Update it when you
  add, move or remove files.
- **Line endings are LF** (`.gitattributes`), except `.bat` and `.cmd`.
- **Python:** use the command in `local-paths.md`; no non-ASCII in anything
  printed (the Windows console raises on it).
- **Scope `find` to this clone** or one named folder; never `/` or `~`.
- **Plans** live in `notes/plans/`; bugs and changes in
  `notes/outstanding-changes.md`, newest first, one number sequence, index
  table at the top. After each plan step, stop and present the findings to
  the user before writing them up or starting the next step.
- **No unreviewed claims get committed:** an interpretation or hypothesis
  goes to the user first, and into a file only as approved.
- **Don't write to Claude Code's auto-memory** in `~/.claude/`. A plan
  step's worklog may go in `.claude/memory/` (gitignored) and is cleared
  when the step closes.
- **`CLAUDE.md` holds only `@AGENTS.md`.**
