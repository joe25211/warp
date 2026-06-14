---
status: ready
source: visible-claude-opus48-ultracode
mode: read-only-planning-bounce
workflow: wf_5b0ff8d5-94e
---

# Nest Review — session viewer fanout v0

Visible Claude Opus 4.8 Ultracode ran a read-only Dynamic Workflow review of the GSD quick slice. Migi centrally verified the key claims against current files before accepting the plan adjustment.

## Verified key findings

1. `/sessions/join/<session_id>` is already routed but stubbed.
   - `tools/hermes_warp_gateway.py:1281-1297` currently appends `relay.viewer.join.attempted`, sends `FailedToJoin`, closes.

2. The sharer loop has the live fanout hook point.
   - `tools/hermes_warp_gateway.py:1301-1336` reads upstream frames, summarizes/journals them, acks `OrderedTerminalEvent`, and handles `EndSession`.

3. `session_events` is summary JSON, not terminal scrollback bytes.
   - `tools/hermes_warp_gateway.py:516-557` persists JSON payloads from `_relay_message_summary`, not renderable terminal blocks.
   - Therefore this slice should not claim protocol-faithful terminal scrollback reconstruction from `session_events`.

4. Rust viewer expects `DownstreamMessage::JoinedSuccessfully` and then live `OrderedTerminalEvent` / `SessionEnded` downstreams.
   - `app/src/terminal/shared_session/viewer/network.rs:559-650` consumes `JoinedSuccessfully { scrollback, latest_event_no, active_prompt, window_size, participant_list, viewer_id, viewer_firebase_uid, input_replica_id, universal_developer_input_context, detailed_source_type, source_task_id, ... }`, `OrderedTerminalEvent`, and `SessionEnded`.

## Accepted plan adjustment

Proceed with a narrow gateway-local viewer fanout v0:

- implement in-process viewer hub keyed by session id
- use per-viewer write locks and send timeouts
- implement read-only `/sessions/join/<session_id>`
- send protocol-shaped `JoinedSuccessfully` with empty/bounded protocol scrollback for v0
- fan out allowlisted live `OrderedTerminalEvent` frames from sharer loop to viewers
- reject/ignore viewer-originated terminal/control events without acking or affecting sharer state
- close viewers on `EndSession`
- extend verifier with bounded Python WebSocket smoke

## Keep out of scope

- real terminal-block scrollback reconstruction from `session_events`
- viewer reconnect/rejoin semantics
- participant ACL/password model
- viewer steering/control
- Rust client changes unless a concrete serde mismatch is proven
- broad Drive/cloud-object work

## Verification cases to add

1. Existing session join succeeds with `JoinedSuccessfully`.
2. Nonexistent join fails cleanly.
3. Joined frame has no reconnect token/session secret and includes participant/list metadata.
4. Protocol scrollback is bounded/empty in v0; `session_events` remain available through existing REST/SSE journal routes, not protocol scrollback reconstruction.
5. Live `OrderedTerminalEvent` from sharer reaches viewer within bounded timeout.
6. Viewer-originated terminal/control event is rejected/ignored and does not update sharer relay state.
7. `EndSession` closes viewers and prevents later resume/join.

## Stop/go

GO, narrow. Implement the hub/join/live-fanout path first. Treat actual Rust-client compatibility as residual risk until a later real-client smoke exists; Python verifier only proves gateway protocol shape and safety invariants.
