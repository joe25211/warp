# Hermes-native Warp fork — technical plan

## Source observations
- The fork is based on `warpdotdev/warp`, cloned to `/home/joe/Projects/warp-hermes-native` with Joe's fork as `origin` and upstream push disabled.
- `crates/warp_core/src/channel/config.rs` bakes production Warp endpoints:
  - server root: `https://app.warp.dev`
  - RTC GraphQL websocket: `wss://rtc.app.warp.dev/graphql/v2`
  - session sharing: `wss://sessions.app.warp.dev`
  - Oz dashboard: `https://oz.warp.dev`
- `app/src/lib.rs` applies server URL overrides only when `Channel::allows_server_url_overrides()` returns true.
- Upstream `Channel::allows_server_url_overrides()` allowed only Dev/Local/Integration, so OSS builds ignored the existing `WARP_*_URL` escape hatch.
- `app/src/ai/harness_availability.rs` seeded Oz/Warp as the default harness before server response, and cached harnesses could reintroduce stale Warp cloud entries.
- Warp Drive/session docs have been cached under `/home/joe/.hermes/knowledge/warp-hermes-native/`.

## Implemented slice
### 1. Hermes-native mode gate
`crates/warp_core/src/channel/mod.rs` now defines:

```rust
Channel::HERMES_NATIVE_MODE_ENV == "WARP_HERMES_NATIVE"
Channel::hermes_native_mode_enabled()
```

Truthy values: `1`, `true`, `yes`, `on`.

### 2. OSS URL override escape hatch
`Channel::allows_server_url_overrides()` now returns true for:
- Dev
- Local
- Integration
- OSS only when `WARP_HERMES_NATIVE` is truthy

Stable/Preview remain pinned to their baked-in endpoints.

### 3. No Warp cloud harness fallback in Hermes-native mode
`app/src/ai/harness_availability.rs` now:
- seeds no default Oz/Warp harnesses when `WARP_HERMES_NATIVE` is enabled
- ignores cached harnesses in Hermes-native mode
- refuses to refresh harnesses from Warp cloud if Hermes-native mode is enabled but `server_root_url` still contains `warp.dev`

This does not complete the full Hermes harness; it prevents silent cloud fallback and creates the safe seam for a self-hosted Hermes compatibility server.

## Launch contract
Use `script/run-hermes-native` from the repo root. Defaults are local loopback, but all three URLs can point at Tailscale names/IPs:

```bash
WARP_SERVER_ROOT_URL=http://tower.tailb0557b.ts.net:8976 \
WARP_WS_SERVER_URL=ws://tower.tailb0557b.ts.net:8976/graphql/v2 \
WARP_SESSION_SHARING_SERVER_URL=ws://tower.tailb0557b.ts.net:8976 \
script/run-hermes-native
```

The gateway must eventually provide:
- `/graphql/v2` HTTP GraphQL for workspace/Drive/harness/model resolvers
- `/graphql/v2` WebSocket or SSE-compatible realtime updates for Drive/session state
- session sharing WebSocket relay compatible with client expectations or a patched Hermes-native client adapter

## Cloud surface cut list
1. AI/model/harness catalog:
   - `app/src/server/server_api/ai.rs:get_available_harnesses`
   - `app/src/server/server_api/ai.rs:get_free_available_models`
   - `app/src/ai/harness_availability.rs`
2. Workspace policy and BYOK/custom inference gating:
   - `app/src/workspaces/user_workspaces.rs`
   - AI settings render paths in `app/src/settings_view/ai_page.rs`
3. Drive/cloud objects:
   - `crates/cloud_objects/*`
   - `crates/cloud_object_models/*`
   - `crates/cloud_object_persistence/*`
   - `app/src/cloud_object/*`
4. Session sharing:
   - `app/src/terminal/view/shared_session/*`
   - code paths using `ChannelState::session_sharing_server_url()`
5. Auth/team/billing assumptions:
   - `app/src/auth/*`
   - `app/src/workspaces/*`
6. Remote/Oz/cloud agents:
   - `crates/warp_cli/src/agent.rs`
   - `app/src/ai/agent_sdk/*`
   - Oz root/workload audience from channel config

## Gateway prototype
`tools/hermes_warp_gateway.py` is a stdlib-only prototype compatibility gateway. It serves:
- `GET /healthz` and `GET /readyz`
- `POST /graphql/v2` model/harness responses
- `POST /graphql/v2` Drive compatibility responses for workflow and generic string objects:
  - `createWorkflow` / `updateWorkflow`
  - `createGenericStringObject` / `bulkCreateObjects` / `updateGenericStringObject`
  - `getCloudObject` / `getUpdatedCloudObjects`
- `POST /graphql/v2` session-sharing registry response:
  - `updateAgentTask` stores `taskId`, `sessionId`, `conversationId`, state, and status locally
- REST session registry and event-journal inspection:
  - `GET /hermes/agent-tasks`
  - `GET /hermes/agent-tasks/<task_id>`
  - `GET /hermes/sessions/<session_id>`
  - `GET /hermes/sessions/<session_id>/events`
  - `POST /hermes/sessions/<session_id>/events`
  - `GET /hermes/sessions/<session_id>/events/stream?once=1` for SSE backlog reads
  - WebSocket session relay adapter on the `WARP_SESSION_SHARING_SERVER_URL` seam:
    - `/sessions/create` creates a local relay record, returns session/reconnect credentials, journals the sharer `Initialize`, accepts app-level `Ping`, and acknowledges `OrderedTerminalEvent` messages while updating `last_event_no`
    - `/sessions/<session_id>/resume` validates the reconnect token and returns `SessionReconnected` with the last processed event number
    - `/sessions/join/<session_id>` validates an existing relay, returns protocol-shaped `JoinedSuccessfully` with empty/bounded v0 scrollback and preserved sharer window/source metadata, registers a read-only viewer socket, treats viewer reconnect initializes as `RejoinedSuccessfully`, and receives live allowlisted `OrderedTerminalEvent` fanout from the sharer with viewer-local contiguous event numbers
  - `GET /session/<session_id>` for a minimal local/Tailscale handoff page
- REST Drive seam:
  - `GET /hermes/drive/objects`
  - `GET /hermes/drive/objects/<id>`
  - `POST /hermes/drive/objects`
  - `PUT /hermes/drive/objects/<id>`

Objects are persisted in SQLite at `~/.local/share/hermes-warp-gateway/drive.sqlite` by default, or at `HERMES_WARP_GATEWAY_DB` / `--db` for tests/deployments. Workflow GraphQL mutations store `object_type=workflow`; generic string GraphQL mutations store `object_type=generic_string_object` and preserve `format`, `clientId`, and serialized prompt-like JSON payloads. This is the first wired compatibility layer for workflow/prompt-style Drive objects; it is still intentionally local-first and explicit-erroring for unknown resolvers.

The gateway can be configured with environment variables or CLI flags. Keep `WARP_SESSION_SHARING_SERVER_URL` slashless because the Warp client appends session route paths directly:
- `HERMES_WARP_GATEWAY_HOST` / `--host`
- `HERMES_WARP_GATEWAY_PORT` / `--port`
- `HERMES_WARP_GATEWAY_DB` / `--db`
- `HERMES_BASE_URL` / `--hermes-base-url`
- `OPENAI_BASE_URL` / `--openai-base-url`
- `HERMES_WARP_DEFAULT_MODEL` / `--default-model`
- `WARP_SESSION_SHARING_SERVER_URL` / `--session-sharing-url`
- `--print-env` emits matching `WARP_*` launch exports.

Gateway packaging/operator artifacts:
- `script/run-hermes-warp-gateway`
- `tools/hermes_warp_gateway.env.example`
- `tools/hermes-warp-gateway.service`
- `tools/hermes_warp_gateway.md`

## Running gateway

Run it locally:

```bash
python tools/hermes_warp_gateway.py
```

Then launch the fork against it:

```bash
script/run-hermes-native
```

The launch script checks `WARP_SERVER_ROOT_URL/healthz` before running the client so it fails fast instead of silently falling back to a dead/self-host seam. Set `WARP_HERMES_NATIVE_SKIP_GATEWAY_CHECK=1` only when intentionally testing another compatible gateway.

Verify the slice end-to-end:

```bash
script/verify-hermes-native
```

This runs formatting, channel tests, `cargo check -p warp_core`, `cargo check -p warp`, gateway smoke checks for model/harness GraphQL responses, REST Drive object create/read/update/list, GraphQL workflow and generic prompt-like object create/read/update/list, `updateAgentTask` task/session binding, session event journal append/list/SSE backlog behavior, the WebSocket relay adapter for `/sessions/create`, reconnect-token-gated `/sessions/<id>/resume`, read-only `/sessions/join/<id>` viewer attach with empty/bounded v0 scrollback, preserved sharer metadata, viewer-local event-number fanout, `RejoinedSuccessfully` reconnect handling, protocol-shaped viewer-control rejection, `EndSession` viewer close behavior, and `git diff --check`.

## Hermes harness polish
`crates/warp_cli/src/agent.rs` now has a first-class `Harness::Hermes` selectable as `hermes` or `migi`. The app maps it through CLI-agent selection, display, setup readiness, local child task config, ambient-agent selection, and auth-secret bypass paths. Hermes is intentionally local-first and does not request Warp-managed harness secrets.

## Next implementation slices
1. Replace the prototype gateway with a typed service and real GraphQL schema/resolvers backed by Hermes config/provider state.
2. Complete the session relay beyond viewer fanout v0: real protocol scrollback/event catch-up, full participant state, and Herdr/Hermes session identity binding.
3. Expand Drive compatibility beyond workflow and generic prompt-like objects into notebooks, env vars, folders, permissions, and deletion/conflict semantics.
4. Add integration tests proving Hermes-native mode does not contact `*.warp.dev` for harness/model/session sharing paths.
