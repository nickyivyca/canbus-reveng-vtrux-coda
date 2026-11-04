# Protocols

Wire protocol specifications. These are language- and implementation-agnostic specs that any of the relevant components (Android server, Python test server, future ESP32 firmware, Android display client) must implement compatibly.

| File | Contents |
|------|----------|
| `can-display-protocol.md` | WebSocket protocol for streaming decoded CAN signals from a logger to a display. v1: JSON wire, server-decode, named buses, Tier 1 aggregations. Designed for Android, Python, and ESP32. |
| `gen-inhibit-status-interface.md` | The generator inhibitor's status frame (`0x7F1`) as the Vtrux live display reads it: fields, the "inhibiting" rule, freshness and version checks, ownership, and what to do when the layout changes. Consumer-side; the inhibitor's own spec and schema doc are authoritative. |
