# Hermes-native Warp gateway

This is the local-first compatibility gateway for the Hermes-native Warp fork. It is deliberately stdlib-only so it can run anywhere Joe can run Python, including a Tailscale node, without pulling a web framework into the fork.

Current surface:

- `GET /healthz` and `GET /readyz`
- `POST /graphql/v2`
  - `get_available_harnesses` / `availableHarnesses`
  - `free_available_models` / `freeAvailableModels`
  - `get_feature_model_choices` / `featureModelChoice`
  - `createWorkflow` / `updateWorkflow`
  - `createGenericStringObject` / `bulkCreateObjects` / `updateGenericStringObject`
  - `getCloudObject` / `getUpdatedCloudObjects`
- Local-first Drive object seam:
  - `GET /hermes/drive/objects`
  - `GET /hermes/drive/objects?objectType=workflow`
  - `GET /hermes/drive/objects/<id>`
  - `POST /hermes/drive/objects`
  - `PUT /hermes/drive/objects/<id>`
- Self-host session-sharing registry + event journal v0:
  - `updateAgentTask` persists task/session/conversation bindings in SQLite
  - `updateAgentTask` also appends an `agent.task.updated` session event when a session id is present
  - `GET /hermes/agent-tasks` lists reported task bindings
  - `GET /hermes/agent-tasks/<task_id>` reads a task binding
  - `GET /hermes/sessions/<session_id>` lists tasks and recent events attached to a session id
  - `GET /hermes/sessions/<session_id>/events` lists ordered session events
  - `POST /hermes/sessions/<session_id>/events` appends terminal/agent events
  - `GET /hermes/sessions/<session_id>/events/stream?once=1` emits the event backlog as SSE
  - WebSocket relay adapter routes on `WARP_SESSION_SHARING_SERVER_URL`:
    - `/sessions/create` creates a local relay record, returns session/reconnect credentials, journals initialization, and accepts ping/terminal-event upstream messages
    - `/sessions/<session_id>/resume` validates the reconnect token and returns the latest processed terminal event number
    - `/sessions/join/<session_id>` is explicitly handled and journals viewer attempts, but returns `FailedToJoin` until downstream event fanout is implemented
  - `GET /session/<session_id>` renders a small public-safe local handoff page

Unknown GraphQL operations return an explicit error. The gateway should not fabricate Warp cloud state.

## Quick local run

From the repo root:

```bash
script/run-hermes-warp-gateway
```

Then launch the client against it:

```bash
script/run-hermes-native
```

`script/run-hermes-native` checks `WARP_SERVER_ROOT_URL/healthz` before compiling/launching the client. If you are pointing at a future compatible gateway without `/healthz`, set `WARP_HERMES_NATIVE_SKIP_GATEWAY_CHECK=1` to bypass the guard.

Equivalent direct invocation:

```bash
python3 tools/hermes_warp_gateway.py \
  --host 127.0.0.1 \
  --port 8976 \
  --db ~/.local/share/hermes-warp-gateway/drive.sqlite \
  --hermes-base-url http://127.0.0.1:9120 \
  --openai-base-url http://127.0.0.1:8787/v1 \
  --default-model hermes/migi-default
```

Print the matching Warp launch environment:

```bash
python3 tools/hermes_warp_gateway.py --print-env
```

## User systemd unit

Install the unit for the current user. If your checkout is not at `~/Projects/warp-hermes-native`, set `HERMES_WARP_GATEWAY_REPO` in `~/.config/hermes-warp-gateway/env` before starting the service:

```bash
mkdir -p ~/.config/systemd/user ~/.config/hermes-warp-gateway
cp tools/hermes-warp-gateway.service ~/.config/systemd/user/
cp tools/hermes_warp_gateway.env.example ~/.config/hermes-warp-gateway/env
$EDITOR ~/.config/hermes-warp-gateway/env
systemctl --user daemon-reload
systemctl --user enable --now hermes-warp-gateway.service
systemctl --user status hermes-warp-gateway.service
```

Check it:

```bash
curl -fsS http://127.0.0.1:8976/healthz | python3 -m json.tool
```

For Tailscale LAN serving, set `HERMES_WARP_GATEWAY_HOST=0.0.0.0` and use the node DNS name in the Warp client env. Keep `WARP_SESSION_SHARING_SERVER_URL` without a trailing slash because Warp's session-sharing client appends route paths such as `/sessions/create`.

```bash
export WARP_HERMES_NATIVE=1
export WARP_SERVER_ROOT_URL=http://tower.tailb0557b.ts.net:8976
export WARP_WS_SERVER_URL=ws://tower.tailb0557b.ts.net:8976/graphql/v2
export WARP_SESSION_SHARING_SERVER_URL=ws://tower.tailb0557b.ts.net:8976
```

## Verification

Run the repo-local verification script:

```bash
script/verify-hermes-native
```

It formats the repo, checks the Rust app, starts the gateway on an isolated smoke-test port with a temporary SQLite database, verifies model/harness GraphQL responses, verifies REST Drive object create/read/update/list, verifies GraphQL workflow and generic prompt-like object create/read/update/list, verifies `updateAgentTask` task/session binding, verifies session event journal append/list/SSE backlog behavior, verifies the WebSocket relay adapter for `/sessions/create`, reconnect-token-gated `/sessions/<id>/resume`, and explicit `/sessions/join/<id>` failure handling, verifies `/hermes/sessions/<id>` and `/session/<id>`, and runs `git diff --check`.

## Next seams

- Replace the prototype GraphQL string router with typed resolvers backed by Hermes config/provider state.
- Patch the client cloud-object paths to use the Drive object compatibility layer.
- Add downstream viewer fanout plus scrollback/event catch-up over the session relay.
- Bind participant state/ACLs to Herdr/Hermes session identity and expose dashboard join/watch/steer links.
