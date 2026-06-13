---
status: complete
route: gsd-nest-dynamic-workflow
owner: Migi
---

# Team Report — Hermes-native Warp completion teams

## Team A — PR readiness / merge gate

Evidence:
- Branch: `session-viewer-fanout-v0`
- Commit: `f313ea8db39658836c3434ec8a1e927c822596aa`
- Remote sync before PR: `origin/session-viewer-fanout-v0...HEAD` was `0 0`
- Base: `origin/master` at merge base `5f300fe5cdd08e25988c751c9ffa716bd6dc4a00`
- Diff hygiene: `git diff --check origin/master...HEAD` clean

PR body summary used:
- Adds read-only viewer attach at `/sessions/join/<session_id>`.
- Returns empty/bounded v0 `JoinedSuccessfully` scrollback.
- Fans out sanitized live `OrderedTerminalEvent` frames.
- Rejects/journals viewer control without sharer mutation.
- Closes viewers on `EndSession`.

Merge gates:
- PR must remain mergeable.
- CodeRabbit/CI/review comments must settle clean.
- Joe approval required before merge.
- No deploy/restart/branch deletion without separate approval.

## Team B — Session relay next-seams plan

Serial chain:
1. Real Rust protocol compatibility smoke.
   - Prove Rust `session_sharing_protocol::{sharer,viewer}` parse gateway create/join/fanout/end responses.
   - Add targeted Rust integration smoke before changing relay semantics.
2. Raw protocol event persistence.
   - Persist viewer-safe raw `OrderedTerminalEvent` JSON separately from summary-only `session_events`.
   - Track contiguous high-watermark from event `0`.
3. Initial viewer catch-up.
   - Persist sharer initialize state: scrollback, active prompt, window size, init/input IDs, source context.
   - On join, return real scrollback and `latest_event_no` only when history is contiguous.
   - Send backlog `0..latest_event_no` before live fanout.
4. Viewer reconnect/catch-up.
   - Support existing viewer IDs and `last_received_event_no`.
   - Return `RejoinedSuccessfully` and send missed backlog.
5. Sharer reconnect durability.
   - Treat acked event number as durably persisted contiguous high-watermark.
6. Participant identity and ACL enforcement.
   - Bind participants to Hermes/Herdr/Tailscale identity.
   - Default viewers to Reader.
   - Add explicit permission failures / role request flow before allowing steering/control.

Parallel-safe work:
- Identity extraction/storage design can begin before ACL enforcement.
- Operator docs/dashboard links can move after participant table design.
- Typed service evaluation should wait until protocol semantics stabilize.

## Team C — Platform compatibility plan

Immediate integration hazard:
- Branch is 18 ahead / 44 behind `upstream/master`.
- Gateway files are low-conflict; deeper Rust/client work should rebase/merge upstream first.
- Known conflict-risk files from upstream overlap:
  - `app/src/ai/agent/conversation.rs`
  - `app/src/ai/agent_sdk/mod.rs`
  - `app/src/lib.rs`
  - `app/src/pane_group/pane/terminal_pane.rs`
  - `app/src/server/server_api/ai.rs`

Phased platform plan:
1. Drift checkpoint before deeper Rust patches.
   - Rebase/merge current fork onto upstream master before touching client/shared-session surfaces.
2. Typed gateway/service hardening.
   - Replace substring GraphQL routing with exact operation registry.
   - Add DTO-ish typed request/response helpers and service/schema version in `/healthz`.
   - Add malformed/oversized request tests and explicit unknown operation errors.
3. Broader Drive/cloud object compatibility.
   - Add notebooks, folders, move/trash/delete, permissions/guests, action history, deleted UID tracking, cloud environments.
   - Expand SQLite model beyond current workflow/generic-string object shape.
4. Cloud-leak integration proof.
   - Fail fast on `WARP_SERVER_ROOT_URL`, `WARP_WS_SERVER_URL`, or `WARP_SESSION_SHARING_SERVER_URL` when they point at `*.warp.dev` in Hermes-native mode.
   - Add egress/DNS/proxy recorder or deny harness proving runtime makes no `*.warp.dev` calls for tested replacement surfaces.
5. Session relay/service hardening.
   - Durable protocol scrollback/catch-up, participant state, ACL roles, restart recovery, dashboard/watch/steer links.

Parallel workstreams after PR #2:
- Drift/rebase lead: update fork integration base.
- Relay semantics lead: Rust compatibility smoke -> raw event persistence -> catch-up.
- Gateway service lead: typed operation registry + health/schema version.
- Drive lead: object model expansion after typed registry.
- Cloud-leak lead: fail-fast URL guards + network proof harness.

## Migi reduction

Do not start broad product work inside PR #2. Keep #2 as the viewer-fanout v0 PR. Next implementation should be a separate GSD quick/phase slice. The highest-leverage next slice is:

`Rust protocol compatibility smoke for Hermes session relay`

Reason: it turns current Python smoke from plausible protocol shape into real client compatibility evidence and derisks every later scrollback/catch-up/ACL change.
