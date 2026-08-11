#!/usr/bin/env bash
# Ghidra per-machine path resolution (Linux / macOS twin of machine-paths.ps1).
#
# Source this from any Ghidra runner script so the runner stays machine-agnostic:
#
#     . "$(dirname "$0")/../../ghidra/machine-paths.sh"     # adjust depth to taste
#     "$GHIDRA_HEADLESS" "$proj" MyProject ...
#
# Variables exported:
#   REPO_ROOT             - absolute path of the reverse-it project root
#   GHIDRA_HOME           - Ghidra install directory
#   GHIDRA_HEADLESS       - full path to support/analyzeHeadless
#   GHIDRA_JAVA_HOME      - JDK used by Ghidra (also exported as JAVA_HOME)
#   GHIDRA_WORKSPACE_DIR  - directory holding .gpr/.rep projects
#
# Adding a machine: add a case branch below, and add the same machine to
# ghidra/README.md and tools-reference.md.

_gmp_self="${BASH_SOURCE[0]:-$0}"
_gmp_dir="$(cd "$(dirname "$_gmp_self")" && pwd)"
REPO_ROOT="$(cd "$_gmp_dir/.." && pwd)"

case "$(hostname)" in
    the Linux box)
        : "${GHIDRA_HOME:=$HOME/ghidra_12.0.4_PUBLIC}"
        : "${GHIDRA_JAVA_HOME:=$HOME/jdk-25.0.4+7}"
        GHIDRA_WORKSPACE_DIR="${GHIDRA_WORKSPACE_DIR:-$HOME/ghidra-projects}"
        ;;
    *)
        GHIDRA_WORKSPACE_DIR="${GHIDRA_WORKSPACE_DIR:-$HOME/ghidra-projects}"
        ;;
esac

# Autodetect if the machine has no table entry and GHIDRA_HOME is unset.
if [ -z "${GHIDRA_HOME:-}" ]; then
    for _c in "$HOME"/ghidra_*_PUBLIC /opt/ghidra_*_PUBLIC /opt/ghidra \
              /usr/local/ghidra_*_PUBLIC /usr/local/ghidra; do
        if [ -x "$_c/support/analyzeHeadless" ]; then
            GHIDRA_HOME="$_c"
            break
        fi
    done
    unset _c
fi

if [ -z "${GHIDRA_HOME:-}" ]; then
    echo "ERROR: Ghidra not found. Set GHIDRA_HOME, or add a case branch for" >&2
    echo "       '$(hostname)' in $_gmp_dir/machine-paths.sh (see ghidra/README.md)." >&2
    return 1 2>/dev/null || exit 1
fi

GHIDRA_HEADLESS="$GHIDRA_HOME/support/analyzeHeadless"
if [ ! -x "$GHIDRA_HEADLESS" ]; then
    echo "ERROR: analyzeHeadless not executable at '$GHIDRA_HEADLESS'." >&2
    return 1 2>/dev/null || exit 1
fi

# Ghidra finds a JDK on its own via PATH; only override when we were told one.
if [ -n "${GHIDRA_JAVA_HOME:-}" ]; then
    JAVA_HOME="$GHIDRA_JAVA_HOME"
    export JAVA_HOME
fi

export REPO_ROOT GHIDRA_HOME GHIDRA_HEADLESS GHIDRA_WORKSPACE_DIR
unset _gmp_self _gmp_dir
