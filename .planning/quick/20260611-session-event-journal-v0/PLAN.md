---
status: complete
route: gsd-quick-nest
owner: Migi
---

# Quick task: session event journal v0

## Goal

Extend the Hermes-native Warp gateway beyond a registry-only session seam by adding a self-hosted session event journal that can persist terminal/agent events under a session id and expose them through JSON/SSE-compatible routes.

## Scope

- Keep Migi as the only writer/verifier.
- Use Nest as a bounded read-only audit lane to choose the safest finishable seam.
- Do not implement the full Warp WebSocket session-sharing protocol in this slice.
- Do not touch secrets, deploy services, or open an upstream PR.

## Implementation

- Add SQLite `session_events` storage to `tools/hermes_warp_gateway.py`.
- Add helper functions to append/list session events.
- Make `updateAgentTask` append `agent.task.updated` when a session id is present.
- Add:
  - `GET /hermes/sessions/<session_id>/events`
  - `POST /hermes/sessions/<session_id>/events`
  - `GET /hermes/sessions/<session_id>/events/stream?once=1`
- Update `/session/<session_id>` to show recent events and event links.
- Extend `script/verify-hermes-native` smoke coverage.
- Update product/technical/operator docs.

## Acceptance checks

- `python -m py_compile tools/hermes_warp_gateway.py`
- `./script/verify-hermes-native`
- `git diff --check`
- Existing Drive/model/harness/session registry smoke remains green.
- Event append/list/SSE smoke passes without `sessions.app.warp.dev` leakage.
