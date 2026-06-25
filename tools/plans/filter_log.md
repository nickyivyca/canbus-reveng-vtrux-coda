# Plan: `tools/filter_log.py`

## Purpose

Pre-process a capture log into a smaller, bus-filtered log suitable for loading into
SavvyCAN for graphing. Addresses two problems:

1. **Dual-bus signal pollution**: IDs that exist on multiple buses (e.g. 0x0C9
   Engine_Speed on both GMLAN buses — one VCM-spoofed at ~800 RPM, one real OBD values)
   appear as a noisy alternating trace in SavvyCAN because SavvyCAN graphs all matching
   frames regardless of bus. Filtering to the correct bus fixes this.

2. **SavvyCAN render performance**: Large multi-bus logs with thousands of frames/second
   slow SavvyCAN's graph renderer significantly. Filtering to only the IDs needed for a
   graphing session (e.g. 4 IDs × 10–50 Hz) produces a tiny file that renders instantly.

## CLI Interface

```
py -3.12 tools/filter_log.py <log> [--bus N] [--id 0xABC [0xDEF ...]] --output PATH

  log           Input log file (any format — auto-detected)
  --bus N       Keep only frames from this bus/channel number
  --id 0xABC    Keep only frames with these CAN IDs (hex). Repeatable. Omit to keep all IDs.
  --output PATH Output BUSMASTER .log file
```

Both `--bus` and `--id` are optional independently:
- `--bus` only: keep all IDs from that bus
- `--id` only: keep those IDs from all buses
- Both: keep those IDs from that bus
- Neither: copy entire log (format conversion only)

## Implementation Notes

### Parser side
Use `canre.parsers.parse_file()` (streaming generator — memory-efficient for large logs).
`CANFrame` fields: `timestamp`, `arbitration_id`, `bus`, `is_extended`, `dlc`, `data`, `is_tx`.

### Writer side
`BUSMASTERWriter` in `tools/can_logger.py` is reusable as-is. Import it directly.
One mismatch to handle: `BUSMASTERWriter.write_message()` calls `msg.is_extended_id`
but `CANFrame` has `is_extended`. Bridge with a simple wrapper or `setattr`.

`BUSMASTERWriter.__init__` needs `num_buses` (for header channel lines) and `bitrate`.
Use `num_buses=1` (or derive from the filtered bus count) and `bitrate=500000` default.

### Timestamp handling
`parse_file()` returns timestamps relative to first frame (seconds).
`BUSMASTERWriter.write_message()` accepts seconds and converts to `HH:MM:SS:TTTT`.
No conversion needed — pass `frame.timestamp` directly.

## Workflow

```bash
# 1. Identify the correct bus for signals of interest
py -3.12 tools/survey.py "projects/vtrux/logs/some_capture.log"
# → see which bus has real engine RPM vs ~800 RPM spoof

# 2. Filter to that bus and only the IDs needed for the graph
py -3.12 tools/filter_log.py "projects/vtrux/logs/some_capture.log" \
    --bus 2 --id 0x0C9 0x3E9 0x63C 0x5A2 \
    --output "projects/vtrux/notes/artifacts/speeds_session.log"

# 3. Open filtered log in SavvyCAN, load speeds.gdf
```

Filtered log goes in `projects/<vehicle>/notes/artifacts/` alongside the `.gdf` it was
made for. Do NOT inventory ephemeral session logs in artifacts/README.md.

## Files to Create/Modify

| File | Action |
|------|--------|
| `tools/filter_log.py` | Create |
| `tools/tools.md` | Add entry |
