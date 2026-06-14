---
status: ready
route: gsd-quick
owner: Migi
---

# Quick Task: session viewer fanout v0

Date: 2026-06-12
Repo: `/home/joe/Projects/warp-hermes-native`
Branch: `session-viewer-fanout-v0`
Base: `origin/master` @ `5f300fe5cdd08e25988c751c9ffa716bd6dc4a00`

## Goal

Turn the session relay adapter from a sharer/resume-only prototype into the first useful read-only viewer relay: a downstream viewer can join a self-hosted Warp session, receive a bounded/empty protocol scrollback frame for v0, and receive live terminal/session events fanned out by the gateway. Existing `session_events` remain the REST/SSE journal source; this slice must not pretend it can reconstruct renderable terminal scrollback blocks from summary events.

## Why now

The previous completed slice added protocol-shaped `/sessions/create`, `/sessions/<id>/resume`, and `/sessions/join/<id>` failure handling. The product docs and GSD state name downstream viewer fanout plus scrollback/event catch-up as the next seam. This slice makes `/sessions/join/<id>` real while preserving the safety boundaries: no public cloud dependency, no anonymous steering, no full ACL model yet.

## Scope

- Keep the gateway stdlib-only.
- Keep `WARP_SESSION_SHARING_SERVER_URL` on the Hermes gateway host/port.
- Add a local viewer connection path for `/sessions/join/<session_id>`.
- Reuse existing `session_events` as the REST/SSE journal source and for event-order assertions; do not map summary payloads into protocol terminal scrollback blocks.
- Fan out new relay/session events to joined viewer WebSockets while the gateway process is alive.
- Keep viewers read-only in this slice; viewer-originated terminal/control messages must be rejected or ignored with protocol-shaped failures.
- Add/extend smoke coverage in `script/verify-hermes-native` for create → viewer join → scrollback → live fanout → EndSession close.
- Update `tools/hermes_warp_gateway.md`, `specs/hermes-native-selfhost/PRODUCT.md`, `specs/hermes-native-selfhost/TECH.md`, and GSD summary/state when complete.

## Non-goals

- No remote/public auth or production deploy.
- No branch push, PR, merge, or service restart without Joe approval.
- No full participant ACL model yet.
- No viewer steering/control path yet.
- No Rust client changes unless the Python gateway smoke proves a protocol-shape mismatch that cannot be fixed at the gateway seam.
- No broad Drive/cloud-object compatibility work in this slice.

## Design sketch

1. Add an in-process relay hub keyed by `session_id`.
   - Track connected viewer sockets and lifecycle cleanup.
   - Do not persist socket handles or tokens in SQLite.
2. Add safe event fanout hooks around existing relay journal append points.
   - Forward sanitized protocol-shaped messages only.
   - Never include reconnect tokens/session secrets in viewer payloads.
3. Implement `/sessions/join/<session_id>` as read-only viewer attach.
   - Validate session exists.
   - Send participant/session metadata.
   - Send bounded/empty v0 protocol scrollback plus consistent event cursor metadata.
   - Keep socket open for live fanout.
4. Make EndSession close viewers and clear hub state.
5. Extend verifier with a pure-Python WebSocket client smoke using exact/bounded frame reads.

## Acceptance checks

- `python -m py_compile tools/hermes_warp_gateway.py`
- `bash -n script/verify-hermes-native script/run-hermes-native`
- `./script/format`
- `git diff --check`
- `./script/verify-hermes-native`
- New smoke proves:
  - viewer join succeeds for an existing session
  - nonexistent session join fails cleanly
  - viewer gets bounded/empty protocol scrollback in the join frame, while `session_events` remains the REST/SSE journal source
  - viewer receives a live event after join
  - viewer cannot send/control terminal events
  - EndSession closes joined viewers and prevents later resume/join
  - no reconnect token/session secret appears in viewer-visible inspection or payloads

## Completion/reporting

Stop at `[ready]` after local implementation and verification. Ask Joe before commit/push. If the verifier exposes protocol ambiguity, report the exact mismatch and smallest next option instead of widening scope silently.
