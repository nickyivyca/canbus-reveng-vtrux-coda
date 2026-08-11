# CAN Display Protocol -- v1

Created: 2026-05-10
Locked: 2026-05-10 (v1)
Amendments:
- 2026-05-10 — added §8.5 best-effort multiplex decoding; updated §4.4 `dbc_unsupported_feature` to reference §8.5. Additive (no version bump).
- 2026-05-10 — replaced the single `config.dbc` string field with a `config.dbcs` object keyed by named bus. Backwards-incompatible (no implementations deployed); no version bump because the protocol was still in pre-implementation flux. Motivation: subscriptions span multiple source DBCs (BelInverter, GMLAN, EPRI), and shipping one giant concatenated DBC was awkward. Per-bus DBCs also make it natural for clients to ship only the messages they subscribe to on each bus (distillation), shrinking the wire payload.

WebSocket-based protocol for streaming decoded CAN signals from a logger (server) to a display (client). Designed to be implementable on Android (JVM), Python (test server), and ESP32 (future firmware) with the same wire semantics.

## 1. Versioning

- The protocol is versioned by integer. v1 is described here.
- Server advertises supported versions in the handshake. Client picks one. Mismatch closes the connection with `protocol_version_mismatch`.
- Backwards-incompatible changes bump the version. New optional fields are not version bumps.

## 2. Transport

- WebSocket over plain TCP (`ws://`). No TLS in v1.
- URL: `ws://<host>:<port>/stream`
- Default port: `9878` (logger phone). Test server defaults to the same.
- Auth: HTTP `Authorization: Bearer <token>` header on the upgrade request. Same token mechanism as the file sync server (`BuildConfig.SYNC_TOKEN`). Rejected with HTTP 401 if missing or wrong.
- Wire encoding v1: UTF-8 JSON, one JSON message per WebSocket text frame.
- Wire encoding future: CBOR over WebSocket binary frames. Negotiated at handshake. Not implemented in v1.

## 3. Connection lifecycle

```
client                                          server
  | --- WebSocket upgrade + Bearer header --->   |
  | <-- 101 Switching Protocols ----------------|
  | <-- {type: "hello", ...}  -------------------|
  | --- {type: "config", ...} ----------------->|
  | <-- {type: "ready", ...} OR {type: "error"}-|
  | <-- {type: "status", ...} (zero or more) ----|
  | <-- {type: "frame", ...} (many) -------------|
  | --- close ------------------------>          |
```

The server emits `frame` messages only after all named buses listed in the client's subscriptions have been identified alive. Until then, `status` messages report progress.

## 4. Handshake

### 4.1 `hello` (server -> client)

Sent immediately after WebSocket upgrade.

```json
{
  "type": "hello",
  "protocol_versions": [1],
  "wire_formats": ["json"],
  "server_name": "vtrux-logger" | "test-server" | "wican-pro",
  "server_version": "<string>",
  "supported_aggregations": ["decimate", "latest", "min", "max", "mean"],
  "supported_buses": ["vehicle", "obd"]
}
```

- `supported_aggregations` always includes Tier 1; Tier 2 (`median`, percentiles) listed if implemented.
- `supported_buses` is the static list of named buses the server can route subscriptions to. Whether each is currently alive is reported later via `status`.

### 4.2 `config` (client -> server)

Sent in response to `hello`.

```json
{
  "type": "config",
  "protocol_version": 1,
  "wire_format": "json",
  "dbcs": {
    "powertrain": "<DBC text covering at least every message_id subscribed on the 'powertrain' bus>",
    "obd": "<DBC text covering at least every message_id subscribed on the 'obd' bus>"
  },
  "subscriptions": [
    {
      "bus": "powertrain",
      "message_id": 1056,
      "signals": ["bcm_vbus", "bcm_iso"],
      "rate_hz": 10,
      "aggregation": "mean"
    },
    {
      "bus": "obd",
      "message_id": 1088,
      "signals": ["cell_max", "cell_min"],
      "rate_hz": 5,
      "aggregation": "latest"
    }
  ]
}
```

- `dbcs` -- object keyed by named bus. Each value is a self-contained DBC
  text. The server uses the DBC for a subscription's `bus` to decode that
  subscription's messages. Buses that have no subscriptions need not appear.
  Clients SHOULD include only the messages they subscribe to on each bus
  (distillation), keeping the payload small; servers MUST accept any
  well-formed DBC that covers at least the subscribed messages and MAY
  ignore extra messages.
- `message_id` is integer (decimal). DBC standard form.
- `signals` is a list of signal names that must exist in the DBC for the
  subscription's `bus`.
- `rate_hz` is the desired emit rate. Must be > 0. The server caps the actual emit rate to the rate it observes on the wire for this message; a client requesting 100 Hz on a 10 Hz signal will see ~10 Hz emissions. The DBC's `GenMsgCycleTime` is not consulted for rate validation.
- `aggregation`: see section 7.
- `signals` may be `"*"` to mean "all signals defined in the DBC for this message."

### 4.3 `ready` (server -> client)

Sent after `config` is accepted.

```json
{
  "type": "ready",
  "active_subscriptions": [
    { "bus": "vehicle", "message_id": 1056, "signals": ["bcm_vbus", "bcm_iso"], "rate_hz": 10 }
  ],
  "pending_buses": ["vehicle"]
}
```

`pending_buses` lists buses not yet identified alive. While this list is non-empty, no `frame` messages are sent for subscriptions on those buses.

### 4.4 `error` (server -> client)

Closes the connection if fatal. Non-fatal errors stay open.

```json
{
  "type": "error",
  "code": "<error_code>",
  "message": "<human readable>",
  "fatal": true
}
```

Error codes (v1):
- `auth_failed` -- pre-WebSocket; HTTP 401.
- `protocol_version_mismatch`
- `unsupported_wire_format`
- `dbc_parse_error` -- `message` names the offending bus and the parser error.
- `dbc_unsupported_feature` -- the client subscribed to a message using a DBC feature this server does not implement. `message` names the feature and DBC location. Multiplex decoding is governed by §8.5; servers that do not implement it return this code for multiplexed-message subscriptions.
- `subscription_missing_bus_dbc` -- a subscription references a bus that has no entry in `config.dbcs`.
- `subscription_unknown_signal`
- `subscription_unknown_bus`
- `unsupported_aggregation`
- `rate_invalid` -- e.g., zero or negative
- `bus_identification_timeout` -- non-fatal status, see section 5.
- `superseded` -- this connection was closed because a new authenticated client took over. See section 10.
- `internal`

## 5. Status messages (server -> client)

Sent for non-fatal lifecycle events. Frequency: typically 1 per state change, plus 1 per bus identification event.

```json
{
  "type": "status",
  "kind": "bus_identified" | "bus_silent" | "bus_lost" | "info",
  "bus": "vehicle",
  "detail": "matched 3/5 anchor IDs in 1.8s"
}
```

`kind`:
- `bus_identified` -- a previously pending bus is now alive. After this message, frames for that bus begin flowing.
- `bus_silent` -- bus was not identified within the server's identification window. Subscriptions on this bus produce no frames; client may show a "bus offline" indicator. The server keeps watching; if the bus comes alive later, a `bus_identified` follows.
- `bus_lost` -- a previously alive bus has stopped emitting frames for longer than a server-defined silence threshold (default 5 s).
- `info` -- general operational info, free-form `detail`.

## 6. Stream messages (server -> client)

The primary data carrier.

```json
{
  "type": "frame",
  "bus": "vehicle",
  "message_id": 1056,
  "t": 12345.678,
  "s": {
    "bcm_vbus": 402.5,
    "bcm_iso": 890.0
  }
}
```

- `t` is seconds since stream start, monotonically non-decreasing per bus. Float.
- `s` keys are the signal names from the corresponding subscription, post-decode and post-aggregation, as `Number` (JSON number).
- One `frame` message per emit cycle per subscription. Server MUST NOT batch multiple subscriptions into one frame in v1 (simpler client code; revisit if it matters).

## 7. Aggregation primitives

Server applies aggregation over the raw bus rate down to the subscription's `rate_hz`.

Window: `1 / rate_hz` seconds, **tumbling** (non-overlapping). At each emit boundary, the server flushes the accumulated aggregation state, emits one `frame`, and starts a fresh window. Sliding windows are not used in v1. This keeps Tier 1 aggregations O(1) memory and gives clients predictable "value covers exactly the previous window" semantics.

### Tier 1 (always supported)

- `decimate` -- emit every Nth raw frame, where N = bus_rate / rate_hz. Per-signal value is the *raw decoded* signal value at that frame. O(1) memory.
- `latest` -- emit the most recent decoded value seen in the window. O(1) memory.
- `min` -- minimum signal value seen in the window. O(1) memory.
- `max` -- maximum signal value seen in the window. O(1) memory.
- `mean` -- arithmetic mean over the window. O(1) memory (running sum + count).

### Tier 2 (optional)

- `median` -- median of all values seen in the window. Requires window buffer.
- `p<NN>` -- percentile (e.g., `p95`, `p99`). Requires window buffer.

If a server supports a Tier 2 aggregation it MUST list it in `hello.supported_aggregations`. Clients MUST NOT request aggregations not advertised; servers reject with `unsupported_aggregation`.

## 8. Decode operation set

This section specifies decode behaviour independently of any specific DBC library, so that Kotlin / Python / C implementations all produce identical output for the same `(message bytes, signal definition)`.

A signal is defined by:
- `start_bit` -- 0-based bit position within the 64-bit message payload.
- `length` -- bit length of the signal (1..64).
- `byte_order` -- one of `little_endian` (Intel) or `big_endian` (Motorola).
- `is_signed` -- bool.
- `scale` -- float.
- `offset` -- float.

### 8.1 Bit extraction

Treat the 8-byte payload as `u64 raw = byte[0] | (byte[1] << 8) | ... | (byte[7] << 56)` (little-endian-of-bytes, regardless of signal byte order; this is the canonical "raw" word).

**Little-endian (Intel):**
```
unsigned_value = (raw >> start_bit) & ((1 << length) - 1)
```

**Big-endian (Motorola):**
DBC start-bit numbering for Motorola is non-trivial. The reference algorithm:
```
bit_pos = start_bit
shift = 0
result = 0
for i in 0..length-1:
    byte_idx = bit_pos / 8
    bit_in_byte = bit_pos % 8
    result |= ((byte[byte_idx] >> bit_in_byte) & 1) << (length - 1 - i)
    if bit_in_byte == 0:
        bit_pos += 15
    else:
        bit_pos -= 1
unsigned_value = result
```

This matches `cantools` Motorola decode behaviour. Implementations MUST cross-test against `cantools.db.decode_message()` for the supported DBC feature set.

### 8.2 Signedness

If `is_signed` and the top bit of the extracted value is set:
```
signed_value = unsigned_value - (1 << length)
```

### 8.3 Scaling

```
physical_value = raw_value * scale + offset
```

`physical_value` is what gets emitted in the `frame.s` map.

### 8.4 Aggregation operates on physical values

All Tier 1 and Tier 2 aggregations operate on the post-scaled, post-offset `physical_value`, not on the raw bits.

### 8.5 Multiplexed messages (best-effort)

A multiplexed CAN message uses one signal as a *multiplexer* (marked `M` in DBC) and groups the remaining signals into *mux groups* (`m0`, `m1`, ...). On any given frame, only the group whose mux value matches the multiplexer signal's decoded value carries meaningful data; the other groups' bits are undefined.

Servers SHOULD decode multiplexed messages on a best-effort basis using the following procedure:

1. Decode the multiplexer signal first, using the rules in §8.1–§8.3.
2. Decode and emit signals belonging to the mux group whose index equals the multiplexer's decoded value.
3. Omit signals belonging to any other mux group from the emitted frame.

This produces sparse signal maps: a `frame.s` for a multiplexed `message_id` may omit subscribed signals on frames where their mux group is inactive. Clients MUST tolerate this.

Aggregation interaction:

- **`latest`, `min`, `max`** -- the aggregator updates only on frames where the requested signal is present; otherwise the prior window's state carries. If a window sees no frames in the signal's mux group, the aggregator emits nothing for that signal that window.
- **`mean`** -- only frames where the requested signal is present contribute to the running sum and count.
- **`decimate`** -- the decimation counter ticks on every frame of the `message_id`, irrespective of mux value. Effective output rate for a mux-gated signal is therefore `rate_hz * P`, where P is the fraction of frames whose mux group includes that signal.
- If an entire aggregation window contains no frames whose mux group includes any subscribed signal, the server MAY skip emitting a frame for that window. Otherwise the frame is emitted containing only the signals that did update.

Servers that do **not** implement multiplex decoding MUST reject subscriptions targeting multiplexed messages with `dbc_unsupported_feature` and `fatal: true`. The Python test server and the Kotlin server (Phase 6) are REQUIRED to implement §8.5; a future ESP32 server is RECOMMENDED to.

## 9. Bus identification (server-side)

Server is configured with a list of `BusIdentity { name, anchor_ids }`. On startup:

1. Open each physical CAN channel. Buffer incoming frames per channel for the identification window (default 2 s).
2. For each channel, count anchor-ID matches against each `BusIdentity`.
3. The `BusIdentity` with the highest match count above a threshold (default: 3 anchor IDs OR all anchors if the set has fewer than 3) wins.
4. If two channels match the same `BusIdentity`, the one with more matches wins; the loser is unassigned.
5. Unmatched channels stay unassigned. Their frames are dropped at the protocol layer.
6. If no channel matches a configured bus within the timeout (default 10 s), server emits `status { kind: "bus_silent", bus: "<name>" }` and continues watching.

This logic is server-side. Clients always speak in `bus` names from the configured list and never see channel numbers.

## 10. Single-client semantics and takeover

A server maintains a single active client session at a time. When a new authenticated WebSocket upgrade arrives while a session is already active, the server **takes over**: it closes the existing session with `error { code: "superseded", fatal: true }` (and a WebSocket close frame), then accepts the new connection and runs the normal handshake.

Rationale: this avoids the stale-TCP-connection failure mode where a client reconnects after a network blip and the server still holds the dead socket for tens of seconds before TCP keepalive fires. A reconnecting client is the same client — bearer-authenticated — and is allowed to reclaim the stream by handshaking again. The client must re-send `config` (subscriptions are not preserved across the new connection).

Multi-client (genuinely concurrent independent clients) is out of scope for v1. The protocol does not preclude it; takeover semantics replace the previous "busy" rejection model.

## 11. CBOR (future)

When implemented, negotiated at handshake:

- Client `config` includes `wire_format: "cbor"`.
- Server responds either accepting (subsequent messages are CBOR over WebSocket binary frames) or rejecting with `unsupported_wire_format`.
- The schema is identical -- the same field names and types. CBOR is purely an encoding swap.

## 12. ESP32 portability notes

The protocol is designed to be implementable on a constrained device:

- Decode operation set is a small fixed set of bit/scale/offset operations -- ~200 lines of C.
- DBC ingestion at runtime is *not required* on the ESP32. A precompiled binary decode table can be baked into firmware at build time and loaded in place of parsing DBC text. The decoder itself uses the same operation set.
- Tier 1 aggregations are all O(1) memory per subscription.
- JSON encoding is feasible (cJSON ~10 KB) but CBOR is cheaper. ESP32 implementations SHOULD support CBOR negotiation.
- Single-client default keeps connection state minimal.

## 13. Open issues / not specified in v1

- Mid-session subscription change. v1: client must reconnect to change subscriptions. v2 candidate: a `reconfigure` client message.
- Time synchronization. `t` is seconds since stream start, server-relative. No absolute wall-clock alignment in v1.
- Server-pushed enum/value-table data. Not in v1; clients hardcode any enum->string mapping if needed.

## 14. Backpressure / flow control

If the client cannot keep up, the server MUST drop the oldest pending `frame` per subscription rather than block on the WebSocket send. Each subscription has an independent send queue; head-of-line blocking across subscriptions is not allowed. The server SHOULD log dropped-frame counts but is not required to surface them on the wire in v1.

Status messages and error messages are NOT subject to drop and MUST be delivered in order.
