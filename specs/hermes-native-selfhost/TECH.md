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
WARP_SESSION_SHARING_SERVER_URL=ws://tower.tailb0557b.ts.net:8977 \
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
- `GET /healthz`
- `POST /graphql/v2` for the first AI/model catalog resolvers:
  - `get_available_harnesses` / `availableHarnesses`
  - `free_available_models` / `freeAvailableModels`
  - `get_feature_model_choices` / `featureModelChoice`

It intentionally returns an error for unknown GraphQL operations instead of pretending to implement Warp cloud.

It also exposes a first local-first Drive storage primitive outside the upstream Warp GraphQL schema:
- `GET /hermes/drive/objects`
- `GET /hermes/drive/objects?objectType=workflow`
- `GET /hermes/drive/objects/<id>`
- `POST /hermes/drive/objects`
- `PUT /hermes/drive/objects/<id>`

Objects are persisted in SQLite at `~/.local/share/hermes-warp-gateway/drive.sqlite` by default, or at `HERMES_WARP_GATEWAY_DB` for tests/deployments. This is not yet wired into the Warp client object model; it is the working self-hosted storage seam for the next compatibility layer.

Run it locally:

```bash
python tools/hermes_warp_gateway.py
```

Then launch the fork against it:

```bash
script/run-hermes-native
```

Verify the slice end-to-end:

```bash
script/verify-hermes-native
```

This runs formatting, channel tests, `cargo check -p warp_core`, `cargo check -p warp`, gateway smoke checks for model/harness GraphQL responses, Drive object create/read/update/list smoke checks, and `git diff --check`.

## Next implementation slices
1. Replace the prototype gateway with a typed service and real GraphQL schema/resolvers backed by Hermes config/provider state.
2. Add a first-class Hermes harness variant or adapter path that launches Hermes/Migi through a local/Tailscale service instead of Oz.
3. Wire the Warp Drive/cloud-object client paths to the gateway's local object store; start with workflow/prompt read-write-list compatibility before notebooks/env vars.
4. Patch session sharing to use the self-hosted relay and bind sessions to Herdr/Hermes session IDs.
5. Add integration tests proving Hermes-native mode does not contact `*.warp.dev` for harness/model/session sharing paths.
