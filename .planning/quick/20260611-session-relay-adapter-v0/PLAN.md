# Quick Task: Session relay adapter v0

Date: 2026-06-11
Repo: `/home/joe/Projects/warp-hermes-native`
Branch: `hermes-native-selfhost`

## Goal

Bridge the session event journal into the first protocol-shaped self-hosted WebSocket relay adapter on `WARP_SESSION_SHARING_SERVER_URL`, without touching the Rust client or pretending the full live viewer relay exists.

## Scope

- Keep gateway stdlib-only.
- Move default `WARP_SESSION_SHARING_SERVER_URL` to the existing gateway host/port.
- Add local SQLite relay persistence for session id, reconnect token, sharer id, and last processed terminal event number.
- Add WebSocket routes:
  - `/sessions/create`
  - `/sessions/<session_id>/resume`
  - `/sessions/join/<session_id>`
- Journal relay initialization/upstream/viewer-attempt summaries into existing `session_events` without leaking reconnect tokens or session secrets through public inspection routes.
- Extend `script/verify-hermes-native` smoke coverage.
- Update product/operator docs and GSD state.

## Non-goals

- No downstream viewer event fanout yet.
- No full scrollback catch-up semantics yet.
- No participant ACL model yet.
- No Rust client changes in this slice.
- No deploy/restart/commit/push without Joe approval.

## Acceptance checks

- `python -m py_compile tools/hermes_warp_gateway.py`
- `./script/format`
- `git diff --check`
- `./script/verify-hermes-native`
- Leak scan confirms no new accidental `sessions.app.warp.dev`, `127.0.0.1:8977`, `tower.tailb0557b.ts.net:8977`, or `/session-relay` references outside intentional historical/source constants/tests/docs.
