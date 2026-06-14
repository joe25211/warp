# Nest handoff — session viewer fanout v0

Use Terse Mode.

You are Claude Code Opus 4.8 with Ultracode effort in a visible Herdr pane, launched and monitored by Migi. Migi owns the mission, file mutations, central verification, commits, pushes, merges, and deployment decisions.

Clarification: "visible Herdr pane only" constrains Migi's dispatch/control channel. It does NOT restrict your official Claude Code capabilities inside this interactive session. For this substantive GSD/Nest mission, engage Claude Code Dynamic Workflows (`/workflows`) as the default planning/review substrate before implementation advice. You may use official Claude Code workflows, /deep-research, /workflows, subagents, agent teams, skills, and other subscription-safe in-session orchestration features if available and appropriate. Do not use hidden external API/programmatic paths outside this visible Claude Code session.

[handoff]
Owner: Migi
To: Claude-Opus
Status: working
Action: Planning-bounce / read-only architecture review for the active GSD quick slice. Do not modify files, install packages, commit, push, restart services, touch secrets, or delete branches.
Blocker: none
Evidence: repo and GSD artifacts listed below
Next: Migi

## Repo

`/home/joe/Projects/warp-hermes-native`

Current branch:

`session-viewer-fanout-v0`

Base:

`origin/master` / `5f300fe5cdd08e25988c751c9ffa716bd6dc4a00`

Current local state before your review:

- `.planning/STATE.md` modified to mark the new quick slice in progress.
- `.planning/quick/20260612-session-viewer-fanout-v0/PLAN.md` created.
- No implementation files changed yet for this slice.

## Source of truth

Read these first:

1. `.planning/STATE.md`
2. `.planning/quick/20260612-session-viewer-fanout-v0/PLAN.md`
3. `.planning/quick/20260611-session-relay-adapter-v0/PLAN.md`
4. `.planning/quick/20260611-session-relay-adapter-v0/SUMMARY.md`
5. `tools/hermes_warp_gateway.py`
6. `script/verify-hermes-native`
7. `tools/hermes_warp_gateway.md`
8. `specs/hermes-native-selfhost/PRODUCT.md`
9. `specs/hermes-native-selfhost/TECH.md`

## Goal

Critique and strengthen the implementation plan for `session viewer fanout v0`.

The intended slice:

- Implement read-only `/sessions/join/<session_id>` for existing relay sessions.
- Replay bounded scrollback from `session_events`.
- Fan out new relay/session events to joined viewer WebSockets while the gateway process is alive.
- Keep viewers read-only: viewer-originated terminal/control messages must not control the sharer.
- EndSession should close joined viewers and clear hub state.
- Extend `script/verify-hermes-native` with create → viewer join → scrollback → live fanout → EndSession close coverage.

## Constraints

- Gateway stays stdlib-only.
- No Rust client changes unless you can show an unavoidable protocol-shape mismatch.
- No public cloud dependency.
- No auth/ACL model in this slice beyond safe local/read-only behavior.
- No secret/token leakage in viewer-visible payloads or inspection routes.
- Do not broaden into Drive/cloud-object compatibility.
- Migi is the only writer unless explicitly reassigned.

## Return exactly this shape

1. Integration map: current functions/routes/tables likely involved.
2. Recommended minimal design: data structures, locks/threading concerns, WebSocket message shapes, and lifecycle cleanup.
3. Verification plan: exact smoke cases to add to `script/verify-hermes-native`.
4. Risks likely to be missed: race conditions, protocol mismatch, secret leakage, dead sockets, event ordering, replay cursor semantics.
5. Stop/go recommendation: what Migi should implement first, and what should stay out of scope.

If you cannot use Dynamic Workflows or cannot inspect the repo, report `[blocked]` with the reason and do not fabricate.
