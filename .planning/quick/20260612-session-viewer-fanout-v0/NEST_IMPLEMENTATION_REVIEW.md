---
status: addressed
source: hermes-delegate-nest-lobe
mode: read-only-implementation-review
---

# Nest implementation review — session viewer fanout v0

Migi attempted GSD/Nest continuation after recovering the active quick slice. Herdr was running, but the current Migi pane identity was ambiguous from the terminal-tool shell (`Migi` panes existed with unknown agent state and no safe current-session binding), so Migi used a bounded read-only Hermes delegate lobe as the Nest reviewer and kept Migi as the only writer.

## Review result

The read-only lobe inspected the current uncommitted diff for:

- `tools/hermes_warp_gateway.py`
- `script/verify-hermes-native`
- active GSD plan/state artifacts

It found two must-fix issues:

1. Live viewer fanout forwarded raw sharer JSON after checking only the summary variant.
   - Risk: an `OrderedTerminalEvent` frame with extra top-level keys or token-looking fields could be forwarded verbatim.
   - Fix applied: `_viewer_safe_ordered_terminal_event()` now requires exactly one top-level `OrderedTerminalEvent`, validates non-negative `event_no`, re-encodes only that allowlisted payload, and refuses token/secret field names before fanout.

2. Viewer `Ping` responses wrote directly to `self.wfile` outside the per-viewer write lock.
   - Risk: concurrent `Pong`, live fanout, and `SessionEnded` writes could interleave WebSocket frames.
   - Fix applied: viewer `Pong` now routes through `_viewer_write_text()`, sharing the same per-viewer write lock as fanout/close.

Migi also applied the lobe's lifecycle improvement:

- `_viewer_close()` now sends the WebSocket close frame and then shuts down/closes the socket to unblock non-cooperative viewer handler threads.

## Verification added from review

`script/verify-hermes-native` now checks that a malicious multi-variant sharer message containing `OrderedTerminalEvent` plus token-bearing `SessionInitialized` data is acknowledged by the sharer path but not fanned out to the viewer.

## Central verification evidence

After the review fixes, Migi ran:

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

`./script/verify-hermes-native` also reported:

- `warp_core` channel tests: `5 passed`
- `cargo check -p warp_core`: passed
- `cargo check -p warp`: passed

## Residual scope

Still out of scope for this slice:

- real protocol scrollback reconstruction
- viewer reconnect/rejoin semantics
- full multi-viewer participant presence
- ACL/password model
- real Rust viewer compatibility smoke
- deployment/restart
- commit/push/PR without Joe approval
