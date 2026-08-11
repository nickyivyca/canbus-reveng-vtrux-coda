#!/usr/bin/env python3
"""Distill per-bus DBCs for the Vtrux live-display app.

The CAN Display Protocol v1 expects the client to send one DBC per named
bus (see `config.dbcs` in android-app/notes/protocols/can-display-protocol.md
§4.2). This tool builds those per-bus DBCs by pulling only the message IDs
the live-display app subscribes to, drawing from across multiple source
DBC files when needed (e.g. obd needs TRAC_TrqFbk from
`vtrux-obd-experimental.dbc` *and* ECM coolant temp from
`epri-obd-bus.dbc`).

The output goes into the vtrux flavor's bundled assets:
    android-app/CanLoggerApps/companion/src/vtrux/assets/live-display/dbcs/

Run from project root:
    py -3.12 tools/distill_dbcs.py
"""
from __future__ import annotations

import re
from pathlib import Path

# Per-bus distillation spec: bus_name -> source_dbc -> list of frame IDs to
# include. IDs are decimal; comments give the hex form. Extended IDs (>= 1<<31)
# are also accepted. Order within a bus determines output order.
SPEC: dict[str, dict[str, list[int]]] = {
    "powertrain": {
        "projects/vtrux/epri-pt-bus.dbc": [
            0x0054,      # EPRI_MCU_Cmd2_Response  -- GENE_RotSpd
            0x0410,      # EPRI_BCM_Status          -- bcm_ibat / alarm / gfd / epo / hvil_mon
            0x0420,      # EPRI_BCM_Limits          -- bcm_dis_max / bcm_chg_max
            0x0430,      # EPRI_BCM_Data1           -- cell V/T min/max
            0x0440,      # EPRI_BCM_Data2           -- balancing, mainc_stat (rich 4-bit)
            0x0471,      # EPRI_MCU_Info2           -- GENE_Mot_Trq
            0x0479,      # EPRI_MCU_Thermal1        -- GENE_ThermInd_pct, GENE_DrvCoolFlowReq_pct
            0x18FFD6B3,  # EPRI_DCDC                -- DCDC_Temperature (absolute degC)
        ],
        "projects/vtrux/vtrux-powertrain-experimental.dbc": [
            0x0649,      # VCM_EvapControl          -- vcm_evap_active
        ],
        "projects/vtrux/BelInverter-v2.dbc": [
            0x18FFD5C0,  # BELINV_overallTemperature   -- BELINV_overAllInverterTemperature
            0x18FFD7C0,  # BELINV_hvBatteryAndCharger  -- AC input V/I, HV battery V/I
            0x18FFD8C0,  # BELINV_j1772Info            -- BELINV_pilotDuty
            0x18FFD9C0,  # BELINV_chargeInfo           -- max available charging current
        ],
    },
    "obd": {
        "projects/vtrux/epri-obd-bus.dbc": [
            0x044A,      # EPRI_MCU_Thermal1_044A -- TRAC_ThermInd_pct, TRAC_DrvCoolFlowReq_pct
        ],
        "projects/vtrux/vtrux-obd-experimental.dbc": [
            0x0442,      # TRAC_TrqFbk_0442 -- TRAC_TrqFbk
        ],
        "projects/vtrux/GMW8762_PPEI_GMLAN.dbc": [
            0x03D1,      # Engine_General_Status_2 -- Throttle_Position (engine APP proxy per vtrux.md)
            0x03FB,      # Engine_Fuel_Status -- Fuel_Alcohol_Composition (dual-native; also on Vehicle bus)
            0x04C1,      # Engine_General_Status_4 -- Engine_Coolant_Temperature. The EPRI DBC's
                         # definition for this message produced a stuck ~70 C
                         # reading on the live display; the GMLAN one is used.
        ],
    },
}

OUT_DIRS = [
    Path("android-app/CanLoggerApps/companion/src/vtrux/assets/live-display/dbcs"),
    Path("android-app/CanLoggerApps/vtrux/src/main/assets/live-display/dbcs"),
]

# Header reused on every distilled file. Matches the canonical DBC NS_ token set
# (cantools tolerates extras but emits a friendlier error message when the file
# is well-formed). BS_ and BU_ are intentionally minimal -- we don't carry node
# information for live display.
HEADER = '''VERSION ""

NS_ :
\tNS_DESC_
\tCM_
\tBA_DEF_
\tBA_
\tVAL_
\tCAT_DEF_
\tCAT_
\tFILTER
\tBA_DEF_DEF_
\tEV_DATA_
\tENVVAR_DATA_
\tSGTYPE_
\tSGTYPE_VAL_
\tBA_DEF_SGTYPE_
\tBA_SGTYPE_
\tSIG_TYPE_REF_
\tVAL_TABLE_
\tSIG_GROUP_
\tSIG_VALTYPE_
\tSIGTYPE_VALTYPE_
\tBO_TX_BU_
\tBA_DEF_REL_
\tBA_REL_
\tBA_DEF_DEF_REL_
\tBU_SG_REL_
\tBU_EV_REL_
\tBU_BO_REL_
\tSG_MUL_VAL_

BS_:

BU_:
'''

EXTENDED_MARKER = 0x80000000


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _extract_message_block(text: str, frame_id: int) -> str | None:
    """Return the BO_ block (BO_ + indented SG_ lines) for `frame_id`, or None."""
    # Accept either bare ID or extended-marker-OR'd ID in the DBC source.
    candidates = {frame_id, frame_id | EXTENDED_MARKER}
    lines = text.splitlines()
    out: list[str] = []
    in_block = False
    for line in lines:
        if line.startswith("BO_ "):
            if in_block:
                break  # next BO_ ends this block
            m = re.match(r"BO_\s+(\d+)\s", line)
            if m and int(m.group(1)) in candidates:
                in_block = True
                out.append(line)
            continue
        if in_block:
            # SG_ lines belong to the current BO_; blank/non-indented terminates.
            if line.startswith(" ") or line.startswith("\t"):
                out.append(line)
            else:
                break
    if not out:
        return None
    return "\n".join(out)


def _extract_message_attrs(text: str, frame_id: int) -> list[str]:
    """Return CM_ BO_, CM_ SG_, VAL_, and BA_ GenMsgCycleTime lines for this id."""
    candidates = {frame_id, frame_id | EXTENDED_MARKER}
    out: list[str] = []
    # Multi-line comments can span lines (quoted strings). Read whole file as one
    # string and scan with regex including DOTALL on the comment body.
    cm_bo = re.findall(
        r'CM_\s+BO_\s+(\d+)\s+"((?:[^"\\]|\\.)*)"\s*;',
        text,
        flags=re.DOTALL,
    )
    for raw_id, body in cm_bo:
        if int(raw_id) in candidates:
            out.append(f'CM_ BO_ {raw_id} "{body}";')

    cm_sg = re.findall(
        r'CM_\s+SG_\s+(\d+)\s+(\S+)\s+"((?:[^"\\]|\\.)*)"\s*;',
        text,
        flags=re.DOTALL,
    )
    for raw_id, sig, body in cm_sg:
        if int(raw_id) in candidates:
            out.append(f'CM_ SG_ {raw_id} {sig} "{body}";')

    val = re.findall(
        r'(VAL_\s+(\d+)\s+\S+\s+(?:\d+\s+"[^"]*"\s+)+;)',
        text,
    )
    for full, raw_id in val:
        if int(raw_id) in candidates:
            out.append(full)

    ba = re.findall(
        r'BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+)\s*;',
        text,
    )
    for raw_id, value in ba:
        if int(raw_id) in candidates:
            out.append(f'BA_ "GenMsgCycleTime" BO_ {raw_id} {value};')
    return out


def distill_bus(
    bus_name: str,
    sources: dict[str, list[int]],
    skip: tuple[str, ...] = (),
) -> str:
    pieces = [HEADER.rstrip()]
    pieces.append("")  # blank line after BU_
    attr_pieces: list[str] = []

    for src_path, ids in sources.items():
        # A source DBC may legitimately be unavailable: GMW8762_PPEI_GMLAN.dbc is
        # generated from a proprietary GM spec and is not distributed with this
        # repo. Skip it rather than failing, so the tool still produces the other
        # buses. Supply the spec DBC yourself and it is picked up automatically.
        if any(s in src_path for s in skip):
            print(f"  skip (--without): {src_path}")
            continue
        if not Path(src_path).is_file():
            print(f"  skip (not present): {src_path}")
            continue
        text = _read(Path(src_path))
        for fid in ids:
            block = _extract_message_block(text, fid)
            if block is None:
                raise SystemExit(
                    f"{bus_name}: frame_id 0x{fid:X} not found in {src_path}"
                )
            pieces.append(block)
            pieces.append("")  # blank line between messages
            attr_pieces.extend(_extract_message_attrs(text, fid))

    if attr_pieces:
        pieces.append("")
        pieces.extend(attr_pieces)
        pieces.append("")  # trailing newline

    return "\n".join(pieces).rstrip() + "\n"


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--without",
        action="append",
        default=[],
        metavar="SUBSTR",
        help="skip any source DBC whose path contains SUBSTR, even if present. "
             "Use --without GMW8762 to build GMLAN-free assets on a machine that "
             "does have the spec DBC.",
    )
    ap.add_argument(
        "--out",
        metavar="DIR",
        help="write to DIR instead of the app asset folders (leaves the local "
             "assets untouched).",
    )
    args = ap.parse_args()
    skip = tuple(args.without)

    out_dirs = [Path(args.out)] if args.out else OUT_DIRS
    for out_dir in out_dirs:
        out_dir.mkdir(parents=True, exist_ok=True)
    for bus, sources in SPEC.items():
        used = {
            p: ids
            for p, ids in sources.items()
            if not any(s in p for s in skip) and Path(p).is_file()
        }
        text = distill_bus(bus, sources, skip=skip)
        msg_count = sum(len(v) for v in used.values())
        src_count = len(used)
        for out_dir in out_dirs:
            out = out_dir / f"{bus}.dbc"
            out.write_text(text, encoding="utf-8")
            print(f"wrote {out} ({msg_count} msgs from {src_count} source(s))")


if __name__ == "__main__":
    main()
