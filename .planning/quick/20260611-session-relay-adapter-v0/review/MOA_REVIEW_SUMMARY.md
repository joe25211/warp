# MoA Deep Code Review Synthesis: session relay adapter v0

Date: 2026-06-11
Repo: `/home/joe/Projects/warp-hermes-native`
Branch: `hermes-native-selfhost`
Mode: read-only review before commit

## Review lanes

- Visible Nest/Claude-Fable Medium read-only lane via Herdr pane `w653f0b59b64c1d-2`.
- Hermes MoA delegate: gateway/security/protocol reviewer.
- Hermes MoA delegate: state/session invariants reviewer.
- Hermes MoA delegate: operator/test coverage reviewer.
- Migi central verification of cited line ranges and live behavior.

No source patches, commits, pushes, deploys, or restarts were performed during this review.

## Verdict

Escalation paid off. The current relay adapter v0 should not be committed yet without a small fix batch.

## Must-fix before commit

### P1: WebSocket handshake is HTTP/1.0, likely incompatible with real Warp client

Evidence:

- `tools/hermes_warp_gateway.py:1046-1083` uses `BaseHTTPRequestHandler` without setting `protocol_version`, so the default response protocol is HTTP/1.0.
- Live probe against the gateway returned:
  - `HTTP/1.0 101 Switching Protocols`
- Warp's websocket client uses async-tungstenite:
  - `crates/websocket/src/native.rs:1-9`

Impact:

- The hand-rolled verifier accepts any status line containing `101`, but the real client stack may reject HTTP/1.0 WebSocket upgrades.

Suggested fix:

- Add `protocol_version = "HTTP/1.1"` to `Handler`.
- Ensure websocket paths close the connection after the websocket lifecycle (`self.close_connection = True`) so HTTP/1.1 keep-alive does not parse post-upgrade bytes as another HTTP request.
- Tighten `script/verify-hermes-native` to assert the websocket status line starts with `HTTP/1.1 101`.

### P1: `/sessions/create` accepts malformed/non-Initialize first frames and still creates a durable relay

Evidence:

- `tools/hermes_warp_gateway.py:1103-1128` reads `first_message`, immediately creates a relay, journals a summary, and returns credentials without requiring variant `Initialize`.
- `tools/hermes_warp_gateway.py:432-438` classifies invalid JSON/unknown shapes but create still succeeds.
- Live probe proved `not json at all` created a relay:
  - `invalid_create_created_relay: true`

Impact:

- Invalid JSON or wrong variants can create persisted `session_relays` rows and valid reconnect credentials.
- This weakens protocol compatibility and pollutes local relay/session event state.

Suggested fix:

- Parse and validate the first frame before `_create_session_relay()`.
- Require a dict with an `Initialize` object; reject invalid/missing/wrong variants with `FailedToInitializeSession` or close without creating rows.
- Add smoke coverage proving invalid create does not create a relay.

### P1: `EndSession` closes the socket but does not revoke the relay

Evidence:

- Protocol defines `EndSession` as explicit session end:
  - pinned `session-sharing-protocol` `sharer.rs:507-509`
- Gateway handling at `tools/hermes_warp_gateway.py:1207-1209` only sends close and breaks.
- Resume path `tools/hermes_warp_gateway.py:1134-1159` accepts any existing relay row with the old reconnect token.
- Live probe proved resume still succeeds after `EndSession`:
  - `end_session_resume: SessionReconnected`

Impact:

- Stopping sharing does not invalidate reconnect credentials.
- Old reconnect tokens remain valid after explicit session end.

Suggested fix:

- Add ended/revoked state or delete relay row on `EndSession`.
- Reject resume for ended sessions with a protocol-shaped failure reason.
- Journal `relay.sharer.end` if audit history is desired.

### P1: Invalid `event_no` values can be acknowledged and persisted

Evidence:

- `_extract_ordered_event_no` at `tools/hermes_warp_gateway.py:463-469` accepts `isinstance(event_no, int)`.
- Python accepts negative ints and bools through that branch.
- `_update_relay_last_event` at `tools/hermes_warp_gateway.py:414-428` persists the value.
- `EventsProcessedAck` at `tools/hermes_warp_gateway.py:1199-1206` echoes it.
- Protocol uses unsigned `usize` for event numbers.
- Live probe proved `event_no: -1` produced:
  - `EventsProcessedAck.latest_processed_event_no: -1`
  - `SessionReconnected.last_received_event_no: -1`

Impact:

- Real protocol clients may fail to deserialize or mis-handle negative resume/ack event numbers.

Suggested fix:

- Require `type(event_no) is int and event_no >= 0` before persisting or acking.
- Reject/ignore malformed `OrderedTerminalEvent` frames without advancing relay state.
- Add smoke coverage for negative/bool event numbers.

## Verify-first / coverage gaps

### Wrong-token resume path is implemented but not covered

Evidence:

- `tools/hermes_warp_gateway.py:1134-1140` has the failure branch.
- `script/verify-hermes-native:285-328` only tests the valid token path.
- Live probe proved current wrong-token behavior returns `FailedToReconnect: Invalid`.

Suggested fix:

- Add verifier coverage for wrong token, missing token, and nonexistent session.
- Prefer protocol-shaped reasons:
  - `SessionNotFound` when relay row is missing
  - `WrongReconnectionToken` when token mismatches

### Python smoke does not prove serde compatibility with pinned Rust protocol types

Evidence:

- Smoke hand-writes minimal JSON at `script/verify-hermes-native:197` instead of serializing/deserializing through `session-sharing-protocol` types.
- Gateway currently accepts permissive summaries rather than parsing protocol structs.

Suggested fix:

- Stronger later gate: add a small Rust helper/test that serializes pinned protocol upstream messages and deserializes gateway downstream responses.
- Short-term: send fuller serde-shaped JSON in Python smoke after adding create validation.

## Low / doc cleanup

- `tools/hermes_warp_gateway.md:111-115` still describes adding `/sessions/create`, `/sessions/join/<id>`, and `/sessions/<id>/resume` as a next seam even though adapter v0 now includes those routes.
- Replace that line with the actual remaining seam: downstream viewer fanout, scrollback/event catch-up, participant state/ACLs, Herdr/Hermes session identity binding, dashboard links.

## Recommended patch batch

Smallest safe patch batch before commit:

1. Set HTTP/1.1 for gateway responses and force close after websocket lifecycle.
2. Add relay first-frame validation for `/sessions/create`.
3. Add relay revocation/deletion on `EndSession`.
4. Tighten event number validation.
5. Add verifier smoke cases:
   - HTTP/1.1 websocket status line
   - invalid create rejected/no relay
   - wrong token / missing token / nonexistent session rejected
   - EndSession prevents resume
   - negative/bool event_no does not ack/persist
6. Update gateway docs next-seam line.
7. Re-run `./script/verify-hermes-native`.

## Stop condition

No further MoA review needed before this fix batch. The findings converge on one invariant family: permissive relay adapter validation/lifecycle behavior plus verifier gaps.
