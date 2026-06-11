---
status: verified
slug: session-sharing-registry
created: 2026-06-10
---

# Quick Task: Session sharing registry seam

## Goal
Add the smallest verified self-host session-sharing product seam to the Hermes-native Warp gateway without attempting full protocol relay yet.

## Scope
- Add gateway configuration for `WARP_SESSION_SHARING_SERVER_URL` instead of hardcoding the default in `--print-env`.
- Add local SQLite task/session binding for the existing `updateAgentTask` GraphQL mutation.
- Add local inspection endpoints for agent task bindings and session links.
- Add a minimal `/session/<id>` route so copied self-host links do not 404.
- Extend `script/verify-hermes-native` smoke coverage for these seams.
- Update product/tech/operator docs.

## Non-goals
- Full WebSocket session relay.
- Browser/mobile transcript viewer.
- Tailscale ACL identity enforcement.
- Commit/push without Joe approval.

## Nest note
Visible Claude lane unavailable: Herdr could not safely identify this Migi pane (`pane p_13 not found`, no matching `$HERMES_SESSION_ID`). Used a read-only Hermes subagent audit as the Nest second lobe; Migi remains sole writer and verifier.

## Acceptance
- Gateway `--print-env` emits the configured session relay URL and no `sessions.app.warp.dev`.
- `updateAgentTask` GraphQL mutation persists task/session/conversation/status metadata.
- `GET /hermes/agent-tasks/<task_id>` and `GET /hermes/sessions/<session_id>` return persisted binding.
- `GET /session/<session_id>` returns a public-safe HTML handoff page.
- `script/verify-hermes-native` passes.
- `git diff --check` passes.


## Result
Implemented and verified.

Changed files:
- `tools/hermes_warp_gateway.py`
- `script/verify-hermes-native`
- `script/run-hermes-warp-gateway`
- `tools/hermes_warp_gateway.env.example`
- `tools/hermes_warp_gateway.md`
- `specs/hermes-native-selfhost/PRODUCT.md`
- `specs/hermes-native-selfhost/TECH.md`

Verification:
- `python -m py_compile tools/hermes_warp_gateway.py`
- targeted gateway smoke for `--session-sharing-url`, `updateAgentTask`, `/hermes/agent-tasks/<id>`, `/hermes/sessions/<id>`, `/session/<id>`
- `./script/verify-hermes-native`
- `git diff --check`

Commit/push: not performed in this step.
