#!/usr/bin/env bash
# Restore this project's Ghidra setup on a Linux/macOS machine.
# POSIX twin of restore-ghidra.ps1 -- same three steps, same idempotency.
#
#   bash ghidra/restore-ghidra.sh
#   bash ghidra/restore-ghidra.sh --force
#   bash ghidra/restore-ghidra.sh --skip-sleigh
#   bash ghidra/restore-ghidra.sh --skip-workspaces
#
# See ghidra/README.md.

set -euo pipefail

FORCE=0
SKIP_SLEIGH=0
SKIP_WORKSPACES=0
for arg in "$@"; do
    case "$arg" in
        --force)           FORCE=1 ;;
        --skip-sleigh)     SKIP_SLEIGH=1 ;;
        --skip-workspaces) SKIP_WORKSPACES=1 ;;
        -h|--help)         sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=machine-paths.sh
. "$HERE/machine-paths.sh"

echo "Machine      : $(hostname)"
echo "Ghidra home  : $GHIDRA_HOME"
echo "JAVA_HOME    : ${JAVA_HOME:-<Ghidra will pick one from PATH>}"
echo "Workspace dir: $GHIDRA_WORKSPACE_DIR"
echo

# ----------------------------------------------------------------- SLEIGH ---
if [ "$SKIP_SLEIGH" -eq 0 ]; then
    LANG_DIR="$GHIDRA_HOME/Ghidra/Processors/SuperH4/data/languages"
    [ -d "$LANG_DIR" ] || { echo "ERROR: SuperH4 language dir not found: $LANG_DIR" >&2; exit 1; }

    TARGET="$LANG_DIR/SuperH4.sinc"
    BACKUP="$LANG_DIR/SuperH4.sinc.stock"
    SOURCE="$HERE/sleigh/SuperH4.sinc"
    COMPILED="$LANG_DIR/SuperH4_be.sla"

    source_hash="$(md5sum "$SOURCE" | cut -d' ' -f1)"
    target_hash=""
    [ -f "$TARGET" ] && target_hash="$(md5sum "$TARGET" | cut -d' ' -f1)"

    if [ "$target_hash" = "$source_hash" ] && [ "$FORCE" -eq 0 ]; then
        echo "SLEIGH   : already patched (MD5 $source_hash) - skipping."
    else
        if [ -f "$TARGET" ] && [ ! -f "$BACKUP" ]; then
            cp -p "$TARGET" "$BACKUP"
            echo "SLEIGH   : stock SuperH4.sinc backed up to SuperH4.sinc.stock"
        fi
        cp "$SOURCE" "$TARGET"
        # Bump mtime so Ghidra sees the .sinc as newer than any compiled .sla.
        touch "$TARGET"
        echo "SLEIGH   : installed modified SuperH4.sinc (MD5 $source_hash)"
        if [ -f "$COMPILED" ]; then
            rm -f "$COMPILED"
            echo "SLEIGH   : removed stale SuperH4_be.sla (Ghidra will recompile on next load)"
        fi
    fi
fi

# ------------------------------------------------------------- WORKSPACES ---
extract_zip() {
    # $1 = zip, $2 = destination dir
    if command -v unzip >/dev/null 2>&1; then
        unzip -oq "$1" -d "$2"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c 'import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$1" "$2"
    else
        echo "ERROR: need either 'unzip' or 'python3' to unpack $1" >&2
        exit 1
    fi
}

# Ghidra stamps the creating account into <project>.rep/project.prp and refuses
# to open a project owned by a different user (NotOwnerException). The archives
# were made on the Windows box as '<user>', so rewrite the owner to
# whoever is restoring.
retake_ownership() {
    # $1 = a *.rep directory
    local prp="$1/project.prp"
    [ -f "$prp" ] || return 0
    python3 - "$prp" <<'PYEOF'
import sys, re, getpass
p = sys.argv[1]
s = open(p).read()
me = getpass.getuser()
s2 = re.sub(r'(NAME="OWNER" TYPE="string" VALUE=")[^"]*(")',
            lambda m: m.group(1) + me + m.group(2), s)
if s2 != s:
    open(p, 'w').write(s2)
    print("OWNER    : " + p + " -> " + me)
PYEOF
}

if [ "$SKIP_WORKSPACES" -eq 0 ]; then
    mkdir -p "$GHIDRA_WORKSPACE_DIR"

    # "zip basename|marker path that exists after a successful extract"
    for entry in "dlcm_analysis|dlcm_analysis.rep" "coda_gateway|coda_gateway/coda_gateway.rep"; do
        name="${entry%%|*}"
        marker="$GHIDRA_WORKSPACE_DIR/${entry##*|}"
        zip="$HERE/workspaces/$name.zip"

        if [ ! -f "$zip" ]; then
            echo "WORKSPACE: $name.zip not found - skipping." >&2
            continue
        fi
        if [ -e "$marker" ] && [ "$FORCE" -eq 0 ]; then
            echo "WORKSPACE: $name already present - skipping (use --force to overwrite)."
            continue
        fi
        if [ -e "$marker" ] && [ "$FORCE" -eq 1 ]; then
            echo "WORKSPACE: --force given; overwriting $marker" >&2
            rm -rf "$marker"
        fi
        extract_zip "$zip" "$GHIDRA_WORKSPACE_DIR"
        echo "WORKSPACE: restored $name -> $GHIDRA_WORKSPACE_DIR"
    done

    # Fix ownership on everything now sitting in the workspace dir, including
    # projects restored by earlier runs of this script.
    for rep in "$GHIDRA_WORKSPACE_DIR"/*.rep "$GHIDRA_WORKSPACE_DIR"/*/*.rep; do
        [ -d "$rep" ] && retake_ownership "$rep"
    done

    mkdir -p "$GHIDRA_WORKSPACE_DIR/dlcm_export"
fi

echo
echo "Done. Headless scripts live in ghidra/scripts/ - pass that folder to -scriptPath."
echo "Example:"
echo "  \"$GHIDRA_HEADLESS\" \"$GHIDRA_WORKSPACE_DIR\" dlcm_analysis \\"
echo "      -process coda_dlcm_prog.bin -noanalysis -postScript DlcmTest.java \\"
echo "      -scriptPath \"$HERE/scripts\""
