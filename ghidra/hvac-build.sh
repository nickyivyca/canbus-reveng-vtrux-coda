#!/usr/bin/env bash
# Rebuild the coda_hvac Ghidra project from the in-repo packed image, from scratch.
#   bash ghidra/hvac-build.sh            # refuses if the project exists
#   bash ghidra/hvac-build.sh --force    # deletes and rebuilds it
# Steps: pack_hvac_image.py -> import prog (HCS-12X:BE:24, base 0x780000) and the SBL
#        (coda_hvac_sbl.bin, base 0x0FE020 = local 0x2020) -> HvacFlowSeed on prog
#        -> DlcmApplySymbols (hvac_symbols.csv) -> DlcmSymbolCensus.
# The project is regenerable, so it lives in the local workspace, not SeaDrive.
# See ghidra/README.md (HVAC section) and projects/coda/notes/hvac/README.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/machine-paths.sh"
cd "$REPO_ROOT"
WS="$GHIDRA_WORKSPACE_DIR"; EXP="$WS/hvac_export"; mkdir -p "$EXP"
if [ -e "$WS/coda_hvac.gpr" ]; then
    [ "${1:-}" = "--force" ] || { echo "coda_hvac exists; pass --force to rebuild" >&2; exit 1; }
    rm -rf "$WS/coda_hvac.gpr" "$WS/coda_hvac.rep"
fi
python3 projects/coda/notes/hvac/artifacts/pack_hvac_image.py
RANGES=$(python3 -c "import json;m=json.load(open('projects/coda/notes/hvac/coda_hvac_map.json'));print(','.join(s['global'][2:]+'-'+s['global_end'][2:] for s in m['segments'] if s['seg']))")
"$GHIDRA_HEADLESS" "$WS" coda_hvac -import "$REPO_ROOT/projects/coda/notes/hvac/coda_hvac_prog.bin" \
    -processor "HCS-12X:BE:24:default" -loader BinaryLoader -loader-baseAddr 0x780000 -noanalysis \
    > "$EXP/import_log.txt" 2>&1
"$GHIDRA_HEADLESS" "$WS" coda_hvac -import "$REPO_ROOT/projects/coda/notes/hvac/coda_hvac_sbl.bin" \
    -processor "HCS-12X:BE:24:default" -loader BinaryLoader -loader-baseAddr 0x0FE020 -noanalysis \
    > "$EXP/import_sbl_log.txt" 2>&1
"$GHIDRA_HEADLESS" "$WS" coda_hvac -process coda_hvac_prog.bin -noanalysis \
    -postScript HvacFlowSeed.java "$EXP/flow_seed.txt" "$RANGES" -scriptPath "$HERE/scripts" \
    > "$EXP/HvacFlowSeed_log.txt" 2>&1
grep -E "HvacFlowSeed:|ERROR|Exception" "$EXP/HvacFlowSeed_log.txt" || true
"$GHIDRA_HEADLESS" "$WS" coda_hvac -process coda_hvac_prog.bin -noanalysis \
    -postScript DlcmApplySymbols.java "$REPO_ROOT/projects/coda/notes/hvac/artifacts/hvac_symbols.csv" "$EXP/apply_symbols.txt" \
    -postScript DlcmSymbolCensus.java "$EXP/symbol_census.txt" -scriptPath "$HERE/scripts" \
    > "$EXP/apply_symbols_log.txt" 2>&1
grep -E "^rows read|^bad addresses" "$EXP/apply_symbols.txt" || true
echo "reports: $EXP/flow_seed.txt, $EXP/apply_symbols.txt, $EXP/symbol_census.txt"
