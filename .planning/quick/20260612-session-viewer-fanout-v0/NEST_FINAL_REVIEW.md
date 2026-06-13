---
status: addressed
source: hermes-delegate-nest-lobes
mode: read-only-final-review
---

# Final Nest review — session viewer fanout v0

After Joe said `gsd nest it`, Migi ran two bounded read-only Hermes delegate lobes over the uncommitted slice and kept Migi as the only writer/verifier.

## Lobe 1: gateway code/safety review

The code review found four concrete blockers:

1. Secret-marker leakage risk in live fanout sanitizer.
   - Prior sanitizer rejected only snake-case `reconnect_token` / `session_secret` substrings after reserializing the whole event.
   - Fix: recursive JSON secret-marker detection now rejects token/secret-like keys after key normalization, rejects forbidden token/secret string values from the active private relay row, and keeps exact-one-variant re-encoding.

2. Join/fanout race immediately after `JoinedSuccessfully`.
   - Prior flow wrote join success before registering the viewer.
   - Fix: viewer registration now happens before join success is sent, under the viewer write lock, so fanout cannot interleave ahead of the join frame.

3. EndSession/join lifecycle race.
   - Prior close path popped current viewers but did not mark the session closing before concurrent joins.
   - Fix: the viewer hub now tombstones closing sessions under the hub lock; late joins receive `FailedToJoin.SessionEnded` instead of registering after close begins.

4. Failed EndSession write could skip socket shutdown.
   - Prior `_viewer_close()` returned early when `viewer.alive` was already false.
   - Fix: close always attempts socket shutdown/close; `alive` only controls whether to send the WebSocket close frame.

## Lobe 2: verifier/GSD coverage review

The verification review found three coverage gaps:

1. `script/verify-hermes-native` did not include the syntax checks listed in the GSD acceptance checks.
   - Fix: verifier now runs `python -m py_compile tools/hermes_warp_gateway.py`, `bash -n script/verify-hermes-native`, and `bash -n script/run-hermes-native`.

2. Secret absence was asserted for viewer payloads but not local inspection surfaces.
   - Fix: verifier now checks the relay JSON inspection route and local `/session/<id>` page do not contain the reconnect token or session secret.

3. EndSession prevented later join on the viewer-fanout session, but later resume failure was only proven on a separate smoke session.
   - Fix: viewer-fanout smoke now also attempts resume on the same ended session and asserts `FailedToReconnect.SessionNotFound`.

## Central verification after fixes

Migi ran:

```bash
python -m py_compile tools/hermes_warp_gateway.py
bash -n script/verify-hermes-native
bash -n script/run-hermes-native
git diff --check
./script/verify-hermes-native
```

Result:

```text
== syntax ==
warp_core channel tests: 5 passed
cargo check -p warp_core: passed
cargo check -p warp: passed
gateway smoke ok
operator artifacts ok
Hermes-native verification passed.
```

## Remaining non-goals

- No push/PR/deploy/restart performed.
- Real Rust viewer compatibility smoke remains a later seam.
- Real protocol scrollback/event catch-up remains a later seam.
- Full participant ACL/identity binding remains a later seam.
