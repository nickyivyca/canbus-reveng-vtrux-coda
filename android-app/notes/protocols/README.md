# Protocols

Wire protocol specifications. These are language- and implementation-agnostic specs that any of the relevant components (Android server, Python test server, future ESP32 firmware, Android display client) must implement compatibly.

| File | Contents |
|------|----------|
| `can-display-protocol.md` | WebSocket protocol for streaming decoded CAN signals from a logger to a display. v1: JSON wire, server-decode, named buses, Tier 1 aggregations. Designed for Android, Python, and ESP32. |
