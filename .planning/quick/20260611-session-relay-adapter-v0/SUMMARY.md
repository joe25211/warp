# Summary: Session relay adapter v0

Date: 2026-06-11
Repo: `/home/joe/Projects/warp-hermes-native`
Branch: `hermes-native-selfhost`

## Completed

Implemented the first protocol-shaped self-hosted WebSocket relay adapter in `tools/hermes_warp_gateway.py`.

Gateway additions:

- SQLite `session_relays` table for local relay records.
- Public-safe relay inspection through existing `/hermes/sessions/<session_id>`; secrets are not exposed in REST inspection output.
- WebSocket handshake/frame helpers in the stdlib gateway.
- `/sessions/create`:
  - accepts sharer `Initialize`
  - creates local session/reconnect/sharer credentials
  - returns `SessionInitialized`
  - journals `relay.sharer.initialize`
  - accepts app-level `Ping` and responds with `Pong`
  - consumes WebSocket ping control frames internally and answers with control pong without corrupting the text-message stream
  - accepts `OrderedTerminalEvent`, updates `last_event_no`, journals an upstream summary, and responds with `EventsProcessedAck`
- `/sessions/<session_id>/resume`:
  - validates `reconnect_token`
  - returns `SessionReconnected` with latest processed event number
  - returns a protocol-shaped `participant_list` populated from persisted sharer identity fields
  - rejects invalid/missing sessions with `FailedToReconnect`
- `/sessions/join/<session_id>`:
  - route-compatible and journals viewer attempts
  - returns explicit `FailedToJoin` until downstream viewer fanout/catch-up exists

Config/docs:

- Default session-sharing URL now points at the same gateway host/port instead of a separate `:8977` placeholder.
- Updated `script/run-hermes-native`, `script/run-hermes-warp-gateway`, env example, gateway docs, and product/tech specs.
- Extended `script/verify-hermes-native` with raw WebSocket smoke coverage for create/resume/join handling, control-frame ping/pong handling, protocol-shaped resume participant list, bad `after` query fallback, and relay event persistence.

## Verification

Passed:

```text
python -m py_compile tools/hermes_warp_gateway.py
./script/format
git diff --check
./script/verify-hermes-native
```

Full verify output included:

```text
== warp_core channel tests ==
5 passed
== warp_core check ==
Finished dev profile
== app check ==
Finished dev profile
== gateway smoke ==
gateway smoke ok
== diff hygiene ==
Hermes-native verification passed.
```

Leak/reference scan checked for:

```text
sessions.app.warp.dev
127.0.0.1:8977
tower.tailb0557b.ts.net:8977
/session-relay
```

Remaining hits are intentional historical/product/source constants/tests, not new launch/config defaults.

## Remaining seam

Next slice should complete real relay behavior beyond adapter v0:

- downstream viewer event fanout
- scrollback/event catch-up for `/sessions/join/<id>`
- participant state
- Herdr/Hermes session identity binding
- Tailscale dashboard join/watch/steer links

## Notes

- No commit or push performed in this slice.
- Visible Claude lane was used only as a bounded read-only audit/planning lobe; Migi stayed the sole writer/verifier.
