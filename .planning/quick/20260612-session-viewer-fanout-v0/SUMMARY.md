---
status: ready
route: gsd-quick-nest
owner: Migi
---

# Summary: session viewer fanout v0

## Status

Ready for Joe approval to commit. No push/PR/deploy/restart performed.

## Implemented

- Added an in-process read-only viewer hub keyed by `session_id` in `tools/hermes_warp_gateway.py`.
- Implemented `/sessions/join/<session_id>` for existing relay sessions:
  - validates the relay exists
  - requires a viewer `Initialize` frame
  - returns protocol-shaped `JoinedSuccessfully`
  - uses empty/bounded v0 `scrollback` instead of pretending `session_events` can reconstruct terminal blocks
  - includes read-only participant metadata for the joining viewer
  - keeps the viewer socket open for live fanout
- Added allowlisted live fanout from the sharer loop:
  - only sanitized, exactly-one-top-level-key `OrderedTerminalEvent` frames are forwarded to viewers
  - token/secret field names are refused before fanout
  - viewer-visible join payloads exclude reconnect tokens and session secrets
- Kept viewers read-only:
  - viewer-originated terminal/control frames are journaled as rejected
  - viewer control attempts do not update relay `lastEventNo`
  - viewer `Ping` still receives `Pong`
- Added `EndSession` viewer lifecycle cleanup:
  - sends `SessionEnded`
  - sends WebSocket close
  - shuts down/closes viewer sockets to unblock handler threads
  - removes in-process hub state
- Updated docs:
  - `tools/hermes_warp_gateway.md`
  - `specs/hermes-native-selfhost/PRODUCT.md`
  - `specs/hermes-native-selfhost/TECH.md`

## GSD/Nest review

- Prior visible Claude Opus 4.8 Ultracode planning review remains captured in `NEST_REVIEW.md`.
- Implementation review used a bounded read-only Hermes delegate lobe because Herdr was available but current Migi pane identity was ambiguous from the terminal-tool shell.
- First review artifact: `NEST_IMPLEMENTATION_REVIEW.md`.
- Final review artifact after Joe said `gsd nest it`: `NEST_FINAL_REVIEW.md`.
- Must-fix findings from the Nest reviews were patched before final verification:
  - raw fanout sanitization, including camelCase/key-normalized secret markers and active relay token/secret string values
  - viewer registration before join success so live fanout cannot outrun the join frame
  - session-closing tombstone to reject late joins during EndSession
  - locked viewer writes
  - viewer close socket shutdown even after failed writes
  - verifier coverage for syntax checks, inspection-route secret absence, and same-session post-EndSession resume failure

## Verification

Migi ran:

```bash
./script/format
python -m py_compile tools/hermes_warp_gateway.py
bash -n script/verify-hermes-native script/run-hermes-native
git diff --check
./script/verify-hermes-native
```

Result:

```text
gateway smoke ok
operator artifacts ok
Hermes-native verification passed.
```

Additional verifier evidence included:

- `warp_core` channel tests: `5 passed`
- `cargo check -p warp_core`: passed
- `cargo check -p warp`: passed

New smoke coverage proves:

- join existing session succeeds with `JoinedSuccessfully`
- missing session join fails with `FailedToJoin.SessionNotFound`
- join payload has empty/bounded v0 scrollback and no reconnect token/session secret
- unsafe multi-variant fanout containing token-bearing data does not reach viewers
- unsafe single-variant fanout containing camelCase secret fields or active relay token/secret values does not reach viewers
- live sanitized `OrderedTerminalEvent` reaches viewer
- viewer-originated terminal/control message gets no ack and does not update relay `lastEventNo`
- `EndSession` sends `SessionEnded`, closes viewer/sharer sockets, and prevents later join/resume on the same ended session
- local relay inspection JSON and `/session/<id>` handoff page do not expose reconnect tokens or session secrets

## Residual work / non-goals

- Real protocol scrollback/event catch-up remains a later seam.
- Full participant ACL/identity binding remains a later seam.
- Real Rust viewer compatibility smoke remains a later seam.
- Commit/push/PR/deploy/restart require Joe approval.
