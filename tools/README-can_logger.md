# Multi-Device CAN Logger

## Overview

`can_logger.py` is a multi-device CAN bus logger that automatically detects all connected CAN interfaces and logs data from them simultaneously to a single BUSMASTER-format log file.

## Features

- **Automatic Multi-Device Detection**: Discovers all connected CAN interfaces across multiple hardware types
- **Intelligent Filtering**: Excludes phantom/virtual devices that have no physical connection
- **BUSMASTER Format Output**: Compatible with existing analysis tools and workflows
- **Concurrent Logging**: Uses threading to capture from multiple devices simultaneously without message loss
- **Hardware Support**: ixxat, kvaser, pcan, socketcan interfaces
- **ixxat Overflow Recovery**: Automatically detects receive-buffer overflow and performs a targeted USB hardware reset of the affected dongle, leaving other connected ixxat dongles unaffected

## Key Capabilities

### Multi-IXXAT Support

The logger uses hardware ID enumeration to detect and differentiate multiple IXXAT devices:
- Calls `get_ixxat_hwids()` to enumerate all connected IXXAT hardware
- Uses `unique_hardware_id` parameter to open each device independently
- Example: HW379841, HW630227 (both accessible simultaneously)

### Kvaser Virtual Device Filtering

Automatically filters out phantom Kvaser Virtual CAN Driver channels:
- Examines `channel_info` attribute during detection
- Skips any channel containing "Virtual" or "virtual" in the description
- Only real hardware (e.g., "Kvaser Leaf Light v2") is included

### BUSMASTER Format

Output files use standard BUSMASTER log format:
- Header with session start time, channel configuration, and bitrate
- Message format: `HH:MM:SS:TTTT Rx <Channel> <ID> <Type> <DLC> <Data>`
- Timestamp resolution: 10 kHz ticks (TTTT = 0.1ms resolution)
- Each device mapped to a numbered channel (1-indexed)

## Administrator Privileges

`can_logger.py` requires **administrator privileges** when ixxat dongles are connected, because overflow recovery uses `Disable-PnpDevice` / `Enable-PnpDevice` via PowerShell, which is admin-only.

**Recommended:** use the included wrapper instead of running Python directly:

```
tools\can_logger_admin.bat [--output file.log] [--bitrate 500000]
```

Double-click in Explorer or run from any (non-admin) cmd prompt. A UAC prompt will appear; click Yes. The script auto-detects whether elevation is already present and skips the prompt if so.

If running `python tools/can_logger.py` directly, launch from an **Administrator** command prompt. Without admin, the USB reset will fail silently (the logger will still capture, but overflow recovery won't work).

---

## Usage

### Basic Usage
```bash
# Auto-detect all devices and log to timestamped file
python tools/can_logger.py

# Specify output file
python tools/can_logger.py --output my_capture.log

# Set bitrate (default 500k)
python tools/can_logger.py --bitrate 250000

# Enable debug logging
python tools/can_logger.py --debug
```

### Example Session

```
$ python tools/can_logger.py --output session1.log

============================================================
Multi-device CAN Logger
============================================================
Bitrate: 500000 bps
Output: session1.log

Detecting CAN interfaces...
Detected ixxat HW379841
Detected ixxat HW630227
Detected kvaser channel 0

Found 3 interface(s):
  Bus 0: ixxat HW379841
  Bus 1: ixxat HW630227
  Bus 2: kvaser channel 0

Starting logging...
Press Ctrl+C to stop

Logged 10000 messages...
Logged 20000 messages...
^C
Shutdown signal received...

Stopping buses...
Wrote 25,432 messages to session1.log

Logging complete
```

## Performance

Tested with 3 simultaneous devices (2 ixxat + 1 kvaser):
- **~30,000 messages captured in 5 seconds**
- **~10,000 messages/second per device**
- Zero message loss during testing
- Clean shutdown with Ctrl+C

## Implementation Details

### Architecture

```
Main Thread                Thread Pool (per device)
-----------                -------------------------
detect_all_can_interfaces() → discovers hardware
create buses               → CANBusLogger instances
start logging threads      → _receive_loop() x N
                              ↓
                           Queue (thread-safe)
                              ↓
write messages             ← BUSMASTERWriter
periodic status updates
graceful shutdown
```

### ixxat Overflow Recovery

ixxat dongles (VCI4 USB-to-CAN V2, VID `08D8`) can latch in a hardware receive-buffer overflow state. When this happens, `bus.recv()` raises `"Data overrun occurred"` and never recovers without a hardware reset. A soft `shutdown()` + `Bus()` reopen does not clear the state.

**Recovery sequence** (triggered by the `"overrun"` exception):

1. `bus.shutdown()` — close the VCI connection
2. PowerShell `Disable-PnpDevice` on the specific dongle (matched by `unique_hardware_id` in the PnP instance ID, e.g. `USB\VID_08D8&PID_0008\HW379841`)
3. 2-second sleep (mandatory USB suspend / power-off settle)
4. PowerShell `Enable-PnpDevice` — USB re-enumeration
5. 4-second sleep for Windows to re-enumerate the VCI device
6. `Bus()` reopen with the same `unique_hardware_id`

**Device identification:**
- VID: `08D8` (HMS Industrial Networks, which acquired ixxat). Not `0A71` (older ixxat VID).
- The `unique_hardware_id` from `get_ixxat_hwids()` (e.g. `HW379841`) appears verbatim as the final component of the PnP instance ID, enabling targeted single-dongle reset.

**Multi-dongle safety:**
- Module-level lock (`_ixxat_reset_lock`) prevents concurrent resets if multiple bus threads overrun simultaneously
- 15-second cooldown (`_IXXAT_RESET_COOLDOWN_S`) prevents pile-on resets
- Only the specific overflowed dongle's PnP device is targeted — other connected ixxat dongles are unaffected

### Key Classes

**`CANBusLogger`**: Per-device background receiver
- Runs `_receive_loop()` in daemon thread
- Receives messages with `bus.recv(timeout=0.1)`
- Queues messages as `(timestamp, bus_id, msg)` tuples
- On `"overrun"` exception: calls `_reconnect()` → `_usb_reset_ixxat()`
- Clean shutdown with `running` flag

**`BUSMASTERWriter`**: Log file writer
- Context manager for file lifecycle
- Writes header with channel info and bitrate
- Formats messages: timestamp conversion to HH:MM:SS:TTTT
- Periodic flush every 1000 messages
- Writes footer on close

### Threading Model

- Main thread: writes messages from queue to file
- N daemon threads: one per CAN interface, receive messages
- Queue: thread-safe message passing between receivers and writer
- Signal handlers: graceful shutdown on Ctrl+C (SIGINT/SIGTERM)

### Timestamp Handling

- Each CANBusLogger records `start_time = time.time()` when started
- Messages timestamped as: `timestamp = time.time() - start_time`
- All devices synchronized to same time base (first device start)
- BUSMASTER format: converts to `HH:MM:SS:TTTT` where TTTT = timestamp % 1.0 * 10000

## Known Limitations

- **No traffic verification**: All detected devices are included, even if no messages are being transmitted (filtered virtual devices only)
- **Single bitrate**: All devices must use the same bitrate (specified by `--bitrate`)
- **Windows paths**: File paths use Windows-style backslashes (SeaDrive requirement)
- **No footer on Ctrl+C timeout**: If killed via timeout command, footer is not written (clean Ctrl+C works correctly)
- **ixxat overflow recovery requires admin**: Without admin privileges, the USB reset silently fails and overflow recovery does not work

## Troubleshooting

### Only 1 IXXAT detected (expected 2+)
- Verify devices visible in Windows Device Manager
- Check that `get_ixxat_hwids()` returns multiple IDs
- Ensure IXXAT drivers are properly installed

### Phantom Kvaser channels appearing
- Verify virtual device filtering is working
- Check `channel_info` attribute contains "Virtual"
- May need to adjust filtering logic for different virtual device names

### No messages captured
- Verify CAN bus is active (traffic present)
- Check bitrate matches network (default 500k)
- Use `--debug` flag to see detailed connection info

### Message loss / gaps
- Check system load during capture
- Consider shorter capture sessions
- Verify adequate disk I/O performance

### ixxat data overrun — PnP device not found
- Script must run as administrator (`can_logger_admin.bat` handles this automatically)
- Verify the ixxat devices appear in Device Manager under `USB\VID_08D8&PID_0008\HWxxxxxx`
- If using an older ixxat (pre-HMS acquisition), the VID may be `0A71` instead of `08D8` — update `_usb_reset_ixxat()` match condition accordingly

### ixxat CAN LED stays off after reconnect
- This is cosmetic — the LED indicator may not re-assert in software-reconnect mode
- Data path is functional if "reconnected successfully" appears in the log
- The USB hardware reset (`can_logger_admin.bat`) is required to restore the LED and fully clear the hardware error state

## Files

- `tools/can_logger.py` - Main logger implementation
- `tools/can_logger_admin.bat` - Self-elevating launcher (required for ixxat overflow recovery)
- `test_capture.log` - Reference capture (5 seconds, 16k messages, 2 devices)
- `test_capture2.log` - Reference capture (5 seconds, 30k messages, 3 devices)

## Dependencies

```python
python >= 3.10
python-can >= 4.6.1
```

IXXAT support requires:
- `can.interfaces.ixxat` module
- IXXAT VCI drivers installed

Kvaser support requires:
- `kvaser` python-can backend
- Kvaser CANlib drivers installed

## Future Enhancements

Potential improvements:
- [ ] Per-device bitrate configuration
- [ ] Traffic verification during detection (optional)
- [ ] Resume logging (append to existing file)
- [ ] Live message rate display
- [ ] Filter by CAN ID during capture
- [ ] DBC decoding during capture (optional)
