# MoA Review Packet: session relay adapter v0

Repo: /home/joe/Projects/warp-hermes-native
Branch: hermes-native-selfhost
Mode: READ-ONLY review; do not edit/stage/commit/push/deploy.

## Scope
- Python stdlib gateway WebSocket relay adapter v0.
- Session relay create/resume/join routes.
- SQLite relay/event persistence.
- Launch/default env URL changes from :8977 to gateway :8976.
- Verify script raw WebSocket smoke coverage.

## Approval boundaries
- Commit/push/PR/deploy/restart require Joe approval.
- Review only; report high-confidence bugs with file:line evidence.

## Known prior audit findings already fixed
- Bad ?after= query no longer raises ValueError; helper _event_after added.
- WebSocket control ping frames are consumed internally and answered with pong.
- Resume participant_list is protocol-shaped and includes persisted sharer identity fields.

## Verification already passed
```text
./script/verify-hermes-native
warp_core channel tests: 5 passed
cargo check -p warp_core: passed
cargo check -p warp: passed
gateway smoke ok
Hermes-native verification passed
```

## Git status
```text
## hermes-native-selfhost...origin/hermes-native-selfhost
 M .planning/STATE.md
 M script/run-hermes-native
 M script/run-hermes-warp-gateway
 M script/verify-hermes-native
 M specs/hermes-native-selfhost/PRODUCT.md
 M specs/hermes-native-selfhost/TECH.md
 M tools/hermes_warp_gateway.env.example
 M tools/hermes_warp_gateway.md
 M tools/hermes_warp_gateway.py
?? .planning/quick/20260611-session-relay-adapter-v0/
?? .serena/
```

## Diff stat
```text
 .planning/STATE.md                      |   1 +
 script/run-hermes-native                |   2 +-
 script/run-hermes-warp-gateway          |   2 +-
 script/verify-hermes-native             | 126 +++++++++-
 specs/hermes-native-selfhost/PRODUCT.md |   4 +-
 specs/hermes-native-selfhost/TECH.md    |  12 +-
 tools/hermes_warp_gateway.env.example   |   6 +-
 tools/hermes_warp_gateway.md            |  10 +-
 tools/hermes_warp_gateway.py            | 396 +++++++++++++++++++++++++++++++-
 9 files changed, 538 insertions(+), 21 deletions(-)
```

## Changed file list
```text
.planning/STATE.md
script/run-hermes-native
script/run-hermes-warp-gateway
script/verify-hermes-native
specs/hermes-native-selfhost/PRODUCT.md
specs/hermes-native-selfhost/TECH.md
tools/hermes_warp_gateway.env.example
tools/hermes_warp_gateway.md
tools/hermes_warp_gateway.py
.planning/quick/20260611-session-relay-adapter-v0/CLAUDE_HANDOFF.md
.planning/quick/20260611-session-relay-adapter-v0/PLAN.md
.planning/quick/20260611-session-relay-adapter-v0/SUMMARY.md
.planning/quick/20260611-session-relay-adapter-v0/review/MOA_REVIEW_PACKET.md
```

## Full tracked diff
```diff
diff --git a/.planning/STATE.md b/.planning/STATE.md
index 1729ef8..e7c348f 100644
--- a/.planning/STATE.md
+++ b/.planning/STATE.md
@@ -14,3 +14,4 @@ Commit, push, upstream PR, deploy/restart, and destructive actions require Joe a
 | --- | --- | --- |
 | 2026-06-10 | Session sharing registry seam | Verified `updateAgentTask` local task/session binding plus session inspection/handoff routes in `hermes-warp-gateway`; full relay remains next seam. |
 | 2026-06-11 | Session event journal v0 | Added self-hosted session event persistence/list/append/SSE backlog endpoints to `hermes-warp-gateway`, wired `updateAgentTask` into `agent.task.updated` events, and updated gateway/product docs; full protocol-compatible live relay remains next seam. |
+| 2026-06-11 | Session relay adapter v0 | Added gateway-owned WebSocket adapter routes for `/sessions/create`, reconnect-token-gated `/sessions/<id>/resume`, and explicit `/sessions/join/<id>` failure handling, backed by local SQLite relay state and smoke-tested in `script/verify-hermes-native`; downstream viewer fanout remains next seam. |
diff --git a/script/run-hermes-native b/script/run-hermes-native
index 89e9c4f..6a801de 100755
--- a/script/run-hermes-native
+++ b/script/run-hermes-native
@@ -6,7 +6,7 @@ set -euo pipefail
 export WARP_HERMES_NATIVE="${WARP_HERMES_NATIVE:-1}"
 export WARP_SERVER_ROOT_URL="${WARP_SERVER_ROOT_URL:-http://127.0.0.1:8976}"
 export WARP_WS_SERVER_URL="${WARP_WS_SERVER_URL:-ws://127.0.0.1:8976/graphql/v2}"
-export WARP_SESSION_SHARING_SERVER_URL="${WARP_SESSION_SHARING_SERVER_URL:-ws://127.0.0.1:8977}"
+export WARP_SESSION_SHARING_SERVER_URL="${WARP_SESSION_SHARING_SERVER_URL:-ws://127.0.0.1:8976}"

 printf 'Hermes-native Warp mode enabled\n' >&2
 printf '  WARP_SERVER_ROOT_URL=%s\n' "$WARP_SERVER_ROOT_URL" >&2
diff --git a/script/run-hermes-warp-gateway b/script/run-hermes-warp-gateway
index 7481a98..0697d89 100755
--- a/script/run-hermes-warp-gateway
+++ b/script/run-hermes-warp-gateway
@@ -9,7 +9,7 @@ export HERMES_WARP_GATEWAY_DB="${HERMES_WARP_GATEWAY_DB:-$HOME/.local/share/herm
 export HERMES_BASE_URL="${HERMES_BASE_URL:-http://127.0.0.1:9120}"
 export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://127.0.0.1:8787/v1}"
 export HERMES_WARP_DEFAULT_MODEL="${HERMES_WARP_DEFAULT_MODEL:-hermes/migi-default}"
-export WARP_SESSION_SHARING_SERVER_URL="${WARP_SESSION_SHARING_SERVER_URL:-ws://127.0.0.1:8977}"
+export WARP_SESSION_SHARING_SERVER_URL="${WARP_SESSION_SHARING_SERVER_URL:-ws://${HERMES_WARP_GATEWAY_HOST}:${HERMES_WARP_GATEWAY_PORT}}"

 printf 'Starting Hermes-native Warp gateway\n' >&2
 printf '  gateway=http://%s:%s\n' "$HERMES_WARP_GATEWAY_HOST" "$HERMES_WARP_GATEWAY_PORT" >&2
diff --git a/script/verify-hermes-native b/script/verify-hermes-native
index 7890988..f29c075 100755
--- a/script/verify-hermes-native
+++ b/script/verify-hermes-native
@@ -17,9 +17,12 @@ cargo check -p warp

 printf '%s\n' '== gateway smoke =='
 python - <<'PY'
+import base64
+import hashlib
 import json
 import os
 import socket
+import struct
 import subprocess
 import sys
 import tempfile
@@ -44,14 +47,14 @@ with tempfile.TemporaryDirectory() as tmpdir:
             '--db',
             db_path,
             '--session-sharing-url',
-            f'ws://127.0.0.1:{port}/session-relay',
+            f'ws://127.0.0.1:{port}',
             '--print-env',
         ],
         text=True,
     )
     assert f'WARP_SERVER_ROOT_URL=http://127.0.0.1:{port}' in printed_env
     assert f'WARP_WS_SERVER_URL=ws://127.0.0.1:{port}/graphql/v2' in printed_env
-    assert f'WARP_SESSION_SHARING_SERVER_URL=ws://127.0.0.1:{port}/session-relay' in printed_env
+    assert f'WARP_SESSION_SHARING_SERVER_URL=ws://127.0.0.1:{port}' in printed_env
     assert 'sessions.app.warp.dev' not in printed_env

     proc = subprocess.Popen(
@@ -65,7 +68,7 @@ with tempfile.TemporaryDirectory() as tmpdir:
             '--db',
             db_path,
             '--session-sharing-url',
-            f'ws://127.0.0.1:{port}/session-relay',
+            f'ws://127.0.0.1:{port}',
         ],
         stdout=subprocess.PIPE,
         stderr=subprocess.STDOUT,
@@ -125,6 +128,103 @@ with tempfile.TemporaryDirectory() as tmpdir:
             with urllib.request.urlopen(request, timeout=3) as response:
                 return response.read().decode()

+        def ws_send_text(sock, payload):
+            raw = payload.encode()
+            mask = os.urandom(4)
+            header = bytearray([0x81])
+            if len(raw) < 126:
+                header.append(0x80 | len(raw))
+            elif len(raw) < 65536:
+                header.append(0x80 | 126)
+                header.extend(struct.pack('!H', len(raw)))
+            else:
+                header.append(0x80 | 127)
+                header.extend(struct.pack('!Q', len(raw)))
+            masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw))
+            sock.sendall(bytes(header) + mask + masked)
+
+        def ws_send_ping(sock, payload=b'probe'):
+            mask = os.urandom(4)
+            masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
+            sock.sendall(bytes([0x89, 0x80 | len(payload)]) + mask + masked)
+
+        def ws_read_frame(sock):
+            header = sock.recv(2)
+            if len(header) < 2:
+                raise AssertionError('short websocket header')
+            first, second = header
+            length = second & 0x7F
+            if length == 126:
+                length = struct.unpack('!H', sock.recv(2))[0]
+            elif length == 127:
+                length = struct.unpack('!Q', sock.recv(8))[0]
+            payload = b''
+            while len(payload) < length:
+                chunk = sock.recv(length - len(payload))
+                if not chunk:
+                    break
+                payload += chunk
+            return first & 0x0F, payload
+
+        def ws_read_text(sock):
+            opcode, payload = ws_read_frame(sock)
+            assert opcode == 0x1, f'unexpected websocket opcode {opcode}'
+            return payload.decode()
+
+        def ws_connect(path):
+            sock = socket.create_connection(('127.0.0.1', port), timeout=3)
+            key = base64.b64encode(os.urandom(16)).decode()
+            request = (
+                f'GET {path} HTTP/1.1\r\n'
+                f'Host: 127.0.0.1:{port}\r\n'
+                'Upgrade: websocket\r\n'
+                'Connection: Upgrade\r\n'
+                f'Sec-WebSocket-Key: {key}\r\n'
+                'Sec-WebSocket-Version: 13\r\n\r\n'
+            )
+            sock.sendall(request.encode())
+            response = b''
+            while b'\r\n\r\n' not in response:
+                response += sock.recv(4096)
+            assert b' 101 ' in response.split(b'\r\n', 1)[0], response.decode(errors='replace')
+            accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
+            assert f'sec-websocket-accept: {accept}'.lower() in response.decode(errors='replace').lower()
+            return sock
+
+        def relay_create_smoke():
+            sock = ws_connect('/sessions/create')
+            try:
+                ws_send_text(sock, json.dumps({'Initialize': {'source_task_id': 'task-smoke', 'scrollback': {'blocks': []}}}))
+                initialized = json.loads(ws_read_text(sock))
+                session_id = initialized['SessionInitialized']['session_id']
+                reconnect_token = initialized['SessionInitialized']['reconnect_token']
+                ws_send_text(sock, json.dumps({'Ping': {'data': [1, 2, 3]}}))
+                pong = json.loads(ws_read_text(sock))
+                ws_send_text(sock, json.dumps({'OrderedTerminalEvent': {'event_no': 7, 'event_type': {'PtyBytesRead': {'bytes': [104, 105]}}}}))
+                ack = json.loads(ws_read_text(sock))
+                return session_id, reconnect_token, initialized, pong, ack
+            finally:
+                sock.close()
+
+        def relay_resume_smoke(session_id, reconnect_token):
+            sock = ws_connect(f'/sessions/{session_id}/resume')
+            try:
+                ws_send_ping(sock)
+                pong_opcode, pong_payload = ws_read_frame(sock)
+                assert pong_opcode == 0xA and pong_payload == b'probe'
+                ws_send_text(sock, json.dumps({'Reconnect': {'reconnect_token': reconnect_token}}))
+                return json.loads(ws_read_text(sock))
+            finally:
+                sock.close()
+
+        def relay_join_smoke(session_id):
+            sock = ws_connect(f'/sessions/join/{session_id}')
+            try:
+                ws_send_text(sock, json.dumps({'Initialize': {'viewer_id': 'viewer-smoke', 'last_received_event_no': None}}))
+                return json.loads(ws_read_text(sock))
+            finally:
+                sock.close()
+
         harness = graphql(
             'get_available_harnesses',
             'query { user { __typename ... on UserOutput { user { availableHarnesses { harnesses { harness displayName enabled availableModels { id displayName reasoningLevel } } } } } } }',
@@ -182,6 +282,11 @@ with tempfile.TemporaryDirectory() as tmpdir:
             {'input': {'taskId': 'task-smoke', 'sessionId': 'session-smoke', 'conversationId': 'conversation-smoke', 'taskState': 'IN_PROGRESS', 'statusMessage': {'message': 'sharing locally'}}},
         )
         task_lookup = request_json('GET', '/hermes/agent-tasks/task-smoke')['task']
+        relay_session_id, relay_reconnect_token, relay_initialized, relay_pong, relay_ack = relay_create_smoke()
+        relay_resume = relay_resume_smoke(relay_session_id, relay_reconnect_token)
+        relay_join = relay_join_smoke(relay_session_id)
+        relay_lookup = request_json('GET', f'/hermes/sessions/{relay_session_id}')
+        relay_events = request_json('GET', f'/hermes/sessions/{relay_session_id}/events')['events']
         event_created = request_json('POST', '/hermes/sessions/session-smoke/events', {
             'kind': 'terminal.output',
             'taskId': 'task-smoke',
@@ -194,10 +299,11 @@ with tempfile.TemporaryDirectory() as tmpdir:
             f"/hermes/sessions/session-smoke/events?after={event_created['eventId'] - 1}&limit=1",
         )['events']
         session_events_stream = request_text('GET', '/hermes/sessions/session-smoke/events/stream?once=1')
+        session_events_bad_after = request_json('GET', '/hermes/sessions/session-smoke/events?after=not-an-int&limit=1')['events']
         session_page = urllib.request.urlopen(f'http://127.0.0.1:{port}/session/session-smoke', timeout=3).read().decode()

         assert health['ok'] is True
-        assert health['sessionSharingUrl'] == f'ws://127.0.0.1:{port}/session-relay'
+        assert health['sessionSharingUrl'] == f'ws://127.0.0.1:{port}'
         assert 'warp.dev' not in json.dumps(harness).lower()
         assert 'Hermes / Migi' in json.dumps(harness)
         assert 'Hermes / Migi' in json.dumps(models)
@@ -216,12 +322,23 @@ with tempfile.TemporaryDirectory() as tmpdir:
         assert task_update['data']['updateAgentTask']['__typename'] == 'UpdateAgentTaskOutput'
         assert task_lookup['sessionId'] == 'session-smoke'
         assert task_lookup['conversationId'] == 'conversation-smoke'
+        assert relay_initialized['SessionInitialized']['session_id'] == relay_session_id
+        assert relay_pong['Pong']['data'] == [1, 2, 3]
+        assert relay_ack['EventsProcessedAck']['latest_processed_event_no'] == 7
+        assert relay_resume['SessionReconnected']['last_received_event_no'] == 7
+        assert relay_resume['SessionReconnected']['participant_list']['sharer']['info']['profile_data']['display_name'] == 'Hermes local sharer'
+        assert relay_join['FailedToJoin']['reason'] == 'Invalid'
+        assert relay_lookup['relay']['sessionId'] == relay_session_id
+        assert any(event['kind'] == 'relay.sharer.initialize' for event in relay_events)
+        assert any(event['kind'] == 'relay.sharer.upstream' for event in relay_events)
         assert any(task['taskId'] == 'task-smoke' for task in session_lookup['tasks'])
         assert any(event['kind'] == 'agent.task.updated' for event in session_lookup['events'])
         assert any(event['kind'] == 'terminal.output' for event in session_events)
         assert event_created['payload']['text'] == 'hello from self-host event journal'
         assert [event['eventId'] for event in session_events] == sorted(event['eventId'] for event in session_events)
         assert session_events_after[0]['eventId'] == event_created['eventId']
+        assert len(session_events_after) == 1
+        assert len(session_events_bad_after) == 1
         assert 'event: agent.task.updated' in session_events_stream
         assert 'event: terminal.output' in session_events_stream
         assert 'data:' in session_events_stream
@@ -230,6 +347,7 @@ with tempfile.TemporaryDirectory() as tmpdir:
         assert '/hermes/sessions/session-smoke/events' in session_page
         assert 'sessions.app.warp.dev' not in session_page
         assert 'sessions.app.warp.dev' not in json.dumps(session_events).lower()
+        assert 'sessions.app.warp.dev' not in json.dumps(relay_events).lower()
         print('gateway smoke ok')
     finally:
         proc.terminate()
diff --git a/specs/hermes-native-selfhost/PRODUCT.md b/specs/hermes-native-selfhost/PRODUCT.md
index c8952e2..fc609b9 100644
--- a/specs/hermes-native-selfhost/PRODUCT.md
+++ b/specs/hermes-native-selfhost/PRODUCT.md
@@ -35,11 +35,11 @@ Joe wants a Warp Terminal fork that keeps the useful terminal/workspace/Drive/se
 8. Hermes/Migi is available as a first-class local harness option, including the `migi` alias.
 9. The gateway has a repo-local launch script, env example, user systemd unit, and operator docs.
 10. The docs cache under `~/.hermes/knowledge/warp-hermes-native/` records the Warp cloud/session/Drive docs used as source material.
-11. The gateway now has a self-host session-sharing registry plus event journal v0: `updateAgentTask` can persist a task/session/conversation binding locally, append an `agent.task.updated` event, expose session events through JSON/SSE endpoints, and `/session/<session_id>` gives a local/Tailscale handoff page instead of a Warp-hosted share surface.
+11. The gateway now has a self-host session-sharing registry, event journal v0, and relay adapter v0: `updateAgentTask` can persist a task/session/conversation binding locally, append an `agent.task.updated` event, expose session events through JSON/SSE endpoints, `/sessions/create` can initialize a local relay record over WebSocket, `/sessions/<id>/resume` is reconnect-token-gated, `/sessions/join/<id>` fails explicitly until viewer fanout exists, and `/session/<session_id>` gives a local/Tailscale handoff page instead of a Warp-hosted share surface.

 ## Later milestones
 - Replace the prototype `hermes-warp-gateway` with a typed service and GraphQL-compatible resolvers for login-free local workspace state, Drive object sync, harness catalog, and model list.
 - Replace Warp account/team assumptions with local workspace ACLs using Tailscale identity and/or Hermes profile identity.
 - Expand Drive compatibility beyond first-pass workflow/generic prompt-like objects into notebooks, env vars, folders, permissions, and deletion/conflict semantics.
-- Bridge the session event journal into a full protocol-compatible live terminal relay, wire it to Herdr panes/Migi session IDs, and expose join/watch/steer links on the Tailscale dashboard.
+- Complete the relay beyond adapter v0 with downstream viewer fanout, catch-up scrollback/event replay, participant state, Herdr/Migi session identity binding, and expose join/watch/steer links on the Tailscale dashboard.
 - Add migration/import for existing Warp Drive objects from local SQLite and/or exported files.
diff --git a/specs/hermes-native-selfhost/TECH.md b/specs/hermes-native-selfhost/TECH.md
index 13d883f..f178f5a 100644
--- a/specs/hermes-native-selfhost/TECH.md
+++ b/specs/hermes-native-selfhost/TECH.md
@@ -46,7 +46,7 @@ Use `script/run-hermes-native` from the repo root. Defaults are local loopback,
 ```bash
 WARP_SERVER_ROOT_URL=http://tower.tailb0557b.ts.net:8976 \
 WARP_WS_SERVER_URL=ws://tower.tailb0557b.ts.net:8976/graphql/v2 \
-WARP_SESSION_SHARING_SERVER_URL=ws://tower.tailb0557b.ts.net:8977 \
+WARP_SESSION_SHARING_SERVER_URL=ws://tower.tailb0557b.ts.net:8976 \
 script/run-hermes-native
 ```

@@ -96,6 +96,10 @@ The gateway must eventually provide:
   - `GET /hermes/sessions/<session_id>/events`
   - `POST /hermes/sessions/<session_id>/events`
   - `GET /hermes/sessions/<session_id>/events/stream?once=1` for SSE backlog reads
+  - WebSocket session relay adapter on the `WARP_SESSION_SHARING_SERVER_URL` seam:
+    - `/sessions/create` creates a local relay record, returns session/reconnect credentials, journals the sharer `Initialize`, accepts app-level `Ping`, and acknowledges `OrderedTerminalEvent` messages while updating `last_event_no`
+    - `/sessions/<session_id>/resume` validates the reconnect token and returns `SessionReconnected` with the last processed event number
+    - `/sessions/join/<session_id>` is route-compatible and journals viewer attempts, but still returns `FailedToJoin` until downstream event fanout/viewer catch-up is implemented
   - `GET /session/<session_id>` for a minimal local/Tailscale handoff page
 - REST Drive seam:
   - `GET /hermes/drive/objects`
@@ -105,7 +109,7 @@ The gateway must eventually provide:

 Objects are persisted in SQLite at `~/.local/share/hermes-warp-gateway/drive.sqlite` by default, or at `HERMES_WARP_GATEWAY_DB` / `--db` for tests/deployments. Workflow GraphQL mutations store `object_type=workflow`; generic string GraphQL mutations store `object_type=generic_string_object` and preserve `format`, `clientId`, and serialized prompt-like JSON payloads. This is the first wired compatibility layer for workflow/prompt-style Drive objects; it is still intentionally local-first and explicit-erroring for unknown resolvers.

-The gateway can be configured with environment variables or CLI flags:
+The gateway can be configured with environment variables or CLI flags. Keep `WARP_SESSION_SHARING_SERVER_URL` slashless because the Warp client appends session route paths directly:
 - `HERMES_WARP_GATEWAY_HOST` / `--host`
 - `HERMES_WARP_GATEWAY_PORT` / `--port`
 - `HERMES_WARP_GATEWAY_DB` / `--db`
@@ -143,13 +147,13 @@ Verify the slice end-to-end:
 script/verify-hermes-native
 ```

-This runs formatting, channel tests, `cargo check -p warp_core`, `cargo check -p warp`, gateway smoke checks for model/harness GraphQL responses, REST Drive object create/read/update/list, GraphQL workflow and generic prompt-like object create/read/update/list, `updateAgentTask` task/session binding, session event journal append/list/SSE backlog behavior, and `git diff --check`.
+This runs formatting, channel tests, `cargo check -p warp_core`, `cargo check -p warp`, gateway smoke checks for model/harness GraphQL responses, REST Drive object create/read/update/list, GraphQL workflow and generic prompt-like object create/read/update/list, `updateAgentTask` task/session binding, session event journal append/list/SSE backlog behavior, the WebSocket relay adapter for `/sessions/create`, reconnect-token-gated `/sessions/<id>/resume`, and explicit `/sessions/join/<id>` failure handling, and `git diff --check`.

 ## Hermes harness polish
 `crates/warp_cli/src/agent.rs` now has a first-class `Harness::Hermes` selectable as `hermes` or `migi`. The app maps it through CLI-agent selection, display, setup readiness, local child task config, ambient-agent selection, and auth-secret bypass paths. Hermes is intentionally local-first and does not request Warp-managed harness secrets.

 ## Next implementation slices
 1. Replace the prototype gateway with a typed service and real GraphQL schema/resolvers backed by Hermes config/provider state.
-2. Bridge the session event journal v0 into the protocol-compatible self-hosted relay and bind sessions to Herdr/Hermes session IDs.
+2. Complete the session relay beyond adapter v0: downstream viewer fanout, catch-up scrollback/event replay, participant state, and Herdr/Hermes session identity binding.
 3. Expand Drive compatibility beyond workflow and generic prompt-like objects into notebooks, env vars, folders, permissions, and deletion/conflict semantics.
 4. Add integration tests proving Hermes-native mode does not contact `*.warp.dev` for harness/model/session sharing paths.
diff --git a/tools/hermes_warp_gateway.env.example b/tools/hermes_warp_gateway.env.example
index 2bcc54a..43de58e 100644
--- a/tools/hermes_warp_gateway.env.example
+++ b/tools/hermes_warp_gateway.env.example
@@ -9,6 +9,6 @@ HERMES_BASE_URL=http://127.0.0.1:9120
 OPENAI_BASE_URL=http://127.0.0.1:8787/v1
 HERMES_WARP_DEFAULT_MODEL=hermes/migi-default

-# Self-host session-sharing relay URL advertised to Warp. For LAN/Tailscale sharing,
-# point this at the reachable host/port that will run the relay seam.
-WARP_SESSION_SHARING_SERVER_URL=ws://127.0.0.1:8977
+# Self-host session-sharing relay URL advertised to Warp. By default the gateway owns
+# the first relay adapter routes on the same host/port as the HTTP/GraphQL surface.
+WARP_SESSION_SHARING_SERVER_URL=ws://127.0.0.1:8976
diff --git a/tools/hermes_warp_gateway.md b/tools/hermes_warp_gateway.md
index 1859532..9fac8c8 100644
--- a/tools/hermes_warp_gateway.md
+++ b/tools/hermes_warp_gateway.md
@@ -27,6 +27,10 @@ Current surface:
   - `GET /hermes/sessions/<session_id>/events` lists ordered session events
   - `POST /hermes/sessions/<session_id>/events` appends terminal/agent events
   - `GET /hermes/sessions/<session_id>/events/stream?once=1` emits the event backlog as SSE
+  - WebSocket relay adapter routes on `WARP_SESSION_SHARING_SERVER_URL`:
+    - `/sessions/create` creates a local relay record, returns session/reconnect credentials, journals initialization, and accepts ping/terminal-event upstream messages
+    - `/sessions/<session_id>/resume` validates the reconnect token and returns the latest processed terminal event number
+    - `/sessions/join/<session_id>` is explicitly handled and journals viewer attempts, but returns `FailedToJoin` until downstream event fanout is implemented
   - `GET /session/<session_id>` renders a small public-safe local handoff page

 Unknown GraphQL operations return an explicit error. The gateway should not fabricate Warp cloud state.
@@ -85,13 +89,13 @@ Check it:
 curl -fsS http://127.0.0.1:8976/healthz | python3 -m json.tool
 ```

-For Tailscale LAN serving, set `HERMES_WARP_GATEWAY_HOST=0.0.0.0` and use the node DNS name in the Warp client env:
+For Tailscale LAN serving, set `HERMES_WARP_GATEWAY_HOST=0.0.0.0` and use the node DNS name in the Warp client env. Keep `WARP_SESSION_SHARING_SERVER_URL` without a trailing slash because Warp's session-sharing client appends route paths such as `/sessions/create`.

 ```bash
 export WARP_HERMES_NATIVE=1
 export WARP_SERVER_ROOT_URL=http://tower.tailb0557b.ts.net:8976
 export WARP_WS_SERVER_URL=ws://tower.tailb0557b.ts.net:8976/graphql/v2
-export WARP_SESSION_SHARING_SERVER_URL=ws://tower.tailb0557b.ts.net:8977
+export WARP_SESSION_SHARING_SERVER_URL=ws://tower.tailb0557b.ts.net:8976
 ```

 ## Verification
@@ -102,7 +106,7 @@ Run the repo-local verification script:
 script/verify-hermes-native
 ```

-It formats the repo, checks the Rust app, starts the gateway on an isolated smoke-test port with a temporary SQLite database, verifies model/harness GraphQL responses, verifies REST Drive object create/read/update/list, verifies GraphQL workflow and generic prompt-like object create/read/update/list, verifies `updateAgentTask` task/session binding, verifies session event journal append/list/SSE backlog behavior, verifies `/hermes/sessions/<id>` and `/session/<id>`, and runs `git diff --check`.
+It formats the repo, checks the Rust app, starts the gateway on an isolated smoke-test port with a temporary SQLite database, verifies model/harness GraphQL responses, verifies REST Drive object create/read/update/list, verifies GraphQL workflow and generic prompt-like object create/read/update/list, verifies `updateAgentTask` task/session binding, verifies session event journal append/list/SSE backlog behavior, verifies the WebSocket relay adapter for `/sessions/create`, reconnect-token-gated `/sessions/<id>/resume`, and explicit `/sessions/join/<id>` failure handling, verifies `/hermes/sessions/<id>` and `/session/<id>`, and runs `git diff --check`.

 ## Next seams

diff --git a/tools/hermes_warp_gateway.py b/tools/hermes_warp_gateway.py
index 5f85c6c..9c3dea1 100755
--- a/tools/hermes_warp_gateway.py
+++ b/tools/hermes_warp_gateway.py
@@ -12,10 +12,13 @@ storage primitive while the exact Warp Drive GraphQL compatibility layer is mapp
 from __future__ import annotations

 import argparse
+import base64
+import hashlib
 import html
 import json
 import os
 import sqlite3
+import struct
 import uuid
 from datetime import datetime, timezone
 from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
@@ -28,7 +31,7 @@ PORT = int(os.environ.get("HERMES_WARP_GATEWAY_PORT", "8976"))
 HERMES_BASE_URL = os.environ.get("HERMES_BASE_URL", "http://127.0.0.1:9120")
 OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8787/v1")
 DEFAULT_MODEL = os.environ.get("HERMES_WARP_DEFAULT_MODEL", "hermes/migi-default")
-SESSION_SHARING_URL = os.environ.get("WARP_SESSION_SHARING_SERVER_URL", "ws://127.0.0.1:8977")
+SESSION_SHARING_URL = os.environ.get("WARP_SESSION_SHARING_SERVER_URL", "ws://127.0.0.1:8976")
 DB_PATH = Path(
     os.environ.get(
         "HERMES_WARP_GATEWAY_DB",
@@ -111,6 +114,20 @@ def _connect() -> sqlite3.Connection:
         "CREATE INDEX IF NOT EXISTS idx_session_events_session_id_event_id "
         "ON session_events(session_id, event_id)"
     )
+    conn.execute(
+        """
+        CREATE TABLE IF NOT EXISTS session_relays (
+            session_id TEXT PRIMARY KEY,
+            session_secret TEXT NOT NULL,
+            reconnect_token TEXT NOT NULL,
+            sharer_id TEXT NOT NULL,
+            sharer_firebase_uid TEXT NOT NULL,
+            last_event_no INTEGER,
+            created_at TEXT NOT NULL,
+            updated_at TEXT NOT NULL
+        )
+        """
+    )
     return conn


@@ -300,6 +317,169 @@ def _event_limit(value: str | None) -> int:
     return max(1, min(limit, 1000))


+def _event_after(value: str | None) -> int:
+    try:
+        after = int(value or "0")
+    except ValueError:
+        after = 0
+    return max(0, after)
+
+
+def _row_to_session_relay(row: sqlite3.Row) -> dict[str, Any]:
+    return {
+        "sessionId": row["session_id"],
+        "sharerId": row["sharer_id"],
+        "sharerFirebaseUid": row["sharer_firebase_uid"],
+        "lastEventNo": row["last_event_no"],
+        "createdAt": row["created_at"],
+        "updatedAt": row["updated_at"],
+    }
+
+
+def _get_session_relay(session_id: str) -> dict[str, Any] | None:
+    with _connect() as conn:
+        row = conn.execute("SELECT * FROM session_relays WHERE session_id = ?", (session_id,)).fetchone()
+    return _row_to_session_relay(row) if row else None
+
+
+def _get_session_relay_private(session_id: str) -> sqlite3.Row | None:
+    with _connect() as conn:
+        return conn.execute("SELECT * FROM session_relays WHERE session_id = ?", (session_id,)).fetchone()
+
+
+def _create_session_relay() -> dict[str, str]:
+    timestamp = _now()
+    relay = {
+        "sessionId": str(uuid.uuid4()),
+        "sessionSecret": str(uuid.uuid4()),
+        "reconnectToken": str(uuid.uuid4()),
+        "sharerId": str(uuid.uuid4()),
+        "sharerFirebaseUid": "local-sharer",
+    }
+    with _connect() as conn:
+        conn.execute(
+            """
+            INSERT INTO session_relays (
+                session_id, session_secret, reconnect_token, sharer_id, sharer_firebase_uid,
+                last_event_no, created_at, updated_at
+            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
+            """,
+            (
+                relay["sessionId"],
+                relay["sessionSecret"],
+                relay["reconnectToken"],
+                relay["sharerId"],
+                relay["sharerFirebaseUid"],
+                None,
+                timestamp,
+                timestamp,
+            ),
+        )
+    return relay
+
+
+def _relay_field(relay: dict[str, Any] | sqlite3.Row, dict_key: str, row_key: str) -> Any:
+    if isinstance(relay, dict):
+        return relay[dict_key]
+    return relay[row_key]
+
+
+def _participant_info(participant_id: str, firebase_uid: str, display_name: str) -> dict[str, Any]:
+    return {
+        "id": participant_id,
+        "profile_data": {
+            "firebase_uid": firebase_uid,
+            "display_name": display_name,
+            "photo_url": None,
+            "email": None,
+            "input_replica_id": "",
+        },
+        "selection": "None",
+    }
+
+
+def _relay_participant_list(relay: dict[str, Any] | sqlite3.Row) -> dict[str, Any]:
+    sharer_id = str(_relay_field(relay, "sharerId", "sharer_id"))
+    firebase_uid = str(_relay_field(relay, "sharerFirebaseUid", "sharer_firebase_uid"))
+    return {
+        "sharer": {"info": _participant_info(sharer_id, firebase_uid, "Hermes local sharer")},
+        "viewers": [],
+        "present_viewers": [],
+        "absent_viewers": [],
+        "guests": [],
+        "pending_guests": [],
+    }
+
+
+def _update_relay_last_event(session_id: str, event_no: int | None) -> None:
+    if event_no is None:
+        return
+    with _connect() as conn:
+        conn.execute(
+            """
+            UPDATE session_relays
+            SET last_event_no = CASE
+                    WHEN last_event_no IS NULL OR ? > last_event_no THEN ?
+                    ELSE last_event_no
+                END,
+                updated_at = ?
+            WHERE session_id = ?
+            """,
+            (event_no, event_no, _now(), session_id),
+        )
+
+
+def _relay_message_summary(raw_message: str) -> dict[str, Any]:
+    try:
+        message = json.loads(raw_message)
+    except json.JSONDecodeError:
+        return {"variant": "invalid-json", "bytes": len(raw_message)}
+    if not isinstance(message, dict) or not message:
+        return {"variant": "unknown", "shape": type(message).__name__}
+    variant = next(iter(message.keys()))
+    value = message.get(variant)
+    summary: dict[str, Any] = {"variant": variant}
+    if isinstance(value, dict):
+        summary["fields"] = sorted(value.keys())
+        if variant == "OrderedTerminalEvent":
+            event_no = value.get("event_no")
+            if isinstance(event_no, int):
+                summary["eventNo"] = event_no
+        if variant == "Initialize":
+            source_task_id = value.get("source_task_id")
+            if source_task_id:
+                summary["sourceTaskId"] = source_task_id
+    return summary
+
+
+def _parse_relay_message(raw_message: str) -> dict[str, Any] | None:
+    try:
+        message = json.loads(raw_message)
+    except json.JSONDecodeError:
+        return None
+    return message if isinstance(message, dict) else None
+
+
+def _extract_ordered_event_no(raw_message: str) -> int | None:
+    message = _parse_relay_message(raw_message)
+    if message is None:
+        return None
+    event = message.get("OrderedTerminalEvent")
+    if isinstance(event, dict) and isinstance(event.get("event_no"), int):
+        return event["event_no"]
+    return None
+
+
+def _extract_reconnect_token(raw_message: str) -> str | None:
+    message = _parse_relay_message(raw_message)
+    reconnect = message.get("Reconnect") if message else None
+    if isinstance(reconnect, dict):
+        token = reconnect.get("reconnect_token")
+        if isinstance(token, str) and token:
+            return token
+    return None
+
+
 def _append_session_event(session_id: str, event_data: dict[str, Any]) -> dict[str, Any]:
     safe_session_id = str(session_id or "").strip()
     if not safe_session_id:
@@ -344,6 +524,71 @@ def _list_session_events(session_id: str, after: int = 0, limit: int = 200) -> l
     return [_row_to_session_event(row) for row in rows]


+_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
+
+
+def _websocket_accept_key(key: str) -> str:
+    digest = hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
+    return base64.b64encode(digest).decode("ascii")
+
+
+def _read_ws_text(rfile: Any, wfile: Any | None = None) -> str | None:
+    while True:
+        header = rfile.read(2)
+        if len(header) < 2:
+            return None
+        first, second = header
+        opcode = first & 0x0F
+        masked = bool(second & 0x80)
+        length = second & 0x7F
+        if length == 126:
+            length = struct.unpack("!H", rfile.read(2))[0]
+        elif length == 127:
+            length = struct.unpack("!Q", rfile.read(8))[0]
+        mask = rfile.read(4) if masked else b""
+        payload = rfile.read(length) if length else b""
+        if masked:
+            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
+        if opcode == 0x8:
+            return None
+        if opcode == 0x9:
+            if wfile is not None:
+                _write_ws_pong(wfile, payload)
+            continue
+        if opcode == 0xA:
+            continue
+        if opcode != 0x1:
+            return ""
+        return payload.decode("utf-8")
+
+
+def _write_ws_text(wfile: Any, text: str) -> None:
+    payload = text.encode("utf-8")
+    header = bytearray([0x81])
+    if len(payload) < 126:
+        header.append(len(payload))
+    elif len(payload) < 65536:
+        header.append(126)
+        header.extend(struct.pack("!H", len(payload)))
+    else:
+        header.append(127)
+        header.extend(struct.pack("!Q", len(payload)))
+    wfile.write(bytes(header) + payload)
+    wfile.flush()
+
+
+def _write_ws_pong(wfile: Any, payload: bytes = b"") -> None:
+    if len(payload) >= 126:
+        payload = payload[:125]
+    wfile.write(bytes([0x8A, len(payload)]) + payload)
+    wfile.flush()
+
+
+def _write_ws_close(wfile: Any) -> None:
+    wfile.write(b"\x88\x00")
+    wfile.flush()
+
+
 def _create_drive_object(payload: dict[str, Any]) -> dict[str, Any]:
     object_type = str(payload.get("objectType") or payload.get("object_type") or "prompt")
     title = str(payload.get("title") or "Untitled")
@@ -822,8 +1067,152 @@ class Handler(BaseHTTPRequestHandler):
         raw = self.rfile.read(length) if length else b"{}"
         return json.loads(raw.decode("utf-8"))

+    def _is_websocket_request(self) -> bool:
+        return self.headers.get("upgrade", "").lower() == "websocket"
+
+    def _send_websocket_handshake(self) -> bool:
+        key = self.headers.get("sec-websocket-key")
+        if not key:
+            self._send_json(400, {"error": "missing sec-websocket-key"})
+            return False
+        self.send_response(101, "Switching Protocols")
+        self.send_header("upgrade", "websocket")
+        self.send_header("connection", "Upgrade")
+        self.send_header("sec-websocket-accept", _websocket_accept_key(key))
+        self.end_headers()
+        return True
+
+    def _handle_session_websocket(self, parsed: Any) -> None:
+        parts = parsed.path.strip("/").split("/")
+        if parts == ["sessions", "create"]:
+            mode = "create"
+            session_id = None
+        elif len(parts) == 3 and parts[0] == "sessions" and parts[2] == "resume":
+            mode = "resume"
+            session_id = parts[1]
+        elif len(parts) == 3 and parts[0] == "sessions" and parts[1] == "join":
+            mode = "join"
+            session_id = parts[2]
+        else:
+            self._send_json(404, {"error": "unknown session relay websocket route"})
+            return
+
+        if not self._send_websocket_handshake():
+            return
+
+        first_message = _read_ws_text(self.rfile, self.wfile)
+        if first_message is None:
+            return
+
+        if mode == "create":
+            relay = _create_session_relay()
+            active_session_id = relay["sessionId"]
+            _append_session_event(
+                active_session_id,
+                {
+                    "kind": "relay.sharer.initialize",
+                    "payload": _relay_message_summary(first_message),
+                },
+            )
+            _write_ws_text(
+                self.wfile,
+                json.dumps(
+                    {
+                        "SessionInitialized": {
+                            "session_id": relay["sessionId"],
+                            "session_secret": relay["sessionSecret"],
+                            "reconnect_token": relay["reconnectToken"],
+                            "sharer_id": relay["sharerId"],
+                            "sharer_firebase_uid": relay["sharerFirebaseUid"],
+                        }
+                    },
+                    separators=(",", ":"),
+                ),
+            )
+        elif mode == "resume" and session_id is not None:
+            active_session_id = session_id
+            relay = _get_session_relay_private(session_id)
+            if relay is None or _extract_reconnect_token(first_message) != relay["reconnect_token"]:
+                _write_ws_text(
+                    self.wfile,
+                    json.dumps({"FailedToReconnect": {"reason": "Invalid"}}, separators=(",", ":")),
+                )
+                _write_ws_close(self.wfile)
+                return
+            _append_session_event(
+                active_session_id,
+                {
+                    "kind": "relay.sharer.reconnect",
+                    "payload": _relay_message_summary(first_message),
+                },
+            )
+            _write_ws_text(
+                self.wfile,
+                json.dumps(
+                    {
+                        "SessionReconnected": {
+                            "last_received_event_no": relay["last_event_no"],
+                            "participant_list": _relay_participant_list(relay),
+                        }
+                    },
+                    separators=(",", ":"),
+                ),
+            )
+        elif mode == "join" and session_id is not None:
+            active_session_id = session_id
+            relay = _get_session_relay(session_id)
+            _append_session_event(
+                active_session_id,
+                {
+                    "kind": "relay.viewer.join.attempted",
+                    "payload": _relay_message_summary(first_message),
+                },
+            )
+            reason = "Invalid" if relay else "SessionNotFound"
+            _write_ws_text(
+                self.wfile,
+                json.dumps({"FailedToJoin": {"reason": reason}}, separators=(",", ":")),
+            )
+            _write_ws_close(self.wfile)
+            return
+        else:  # pragma: no cover - defensive branch
+            return
+
+        while True:
+            message = _read_ws_text(self.rfile, self.wfile)
+            if message is None:
+                break
+            summary = _relay_message_summary(message)
+            event_no = _extract_ordered_event_no(message)
+            _append_session_event(
+                active_session_id,
+                {"kind": "relay.sharer.upstream", "payload": summary},
+            )
+            _update_relay_last_event(active_session_id, event_no)
+            variant = summary.get("variant")
+            if variant == "Ping":
+                try:
+                    data = json.loads(message).get("Ping", {}).get("data", [])
+                except json.JSONDecodeError:
+                    data = []
+                _write_ws_text(self.wfile, json.dumps({"Pong": {"data": data}}, separators=(",", ":")))
+            elif variant == "OrderedTerminalEvent" and event_no is not None:
+                _write_ws_text(
+                    self.wfile,
+                    json.dumps(
+                        {"EventsProcessedAck": {"latest_processed_event_no": event_no}},
+                        separators=(",", ":"),
+                    ),
+                )
+            elif variant == "EndSession":
+                _write_ws_close(self.wfile)
+                break
+
     def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
         parsed = urlparse(self.path)
+        if self._is_websocket_request() and parsed.path.startswith("/sessions/"):
+            self._handle_session_websocket(parsed)
+            return
         if parsed.path in {"/", "/healthz", "/readyz"}:
             self._send_json(
                 200,
@@ -872,7 +1261,7 @@ class Handler(BaseHTTPRequestHandler):
                 session_id = parts[2]
                 if len(parts) == 4 and parts[3] == "events":
                     params = parse_qs(parsed.query)
-                    after = int(params.get("after", ["0"])[0] or "0")
+                    after = _event_after(params.get("after", [None])[0])
                     limit = _event_limit(params.get("limit", [None])[0])
                     self._send_json(
                         200,
@@ -884,7 +1273,7 @@ class Handler(BaseHTTPRequestHandler):
                     return
                 if len(parts) == 5 and parts[3] == "events" and parts[4] == "stream":
                     params = parse_qs(parsed.query)
-                    after = int(params.get("after", ["0"])[0] or "0")
+                    after = _event_after(params.get("after", [None])[0])
                     limit = _event_limit(params.get("limit", [None])[0])
                     events = _list_session_events(session_id, after=after, limit=limit)
                     encoded = "".join(
@@ -909,6 +1298,7 @@ class Handler(BaseHTTPRequestHandler):
                             "sessionId": session_id,
                             "tasks": _list_session_tasks(session_id),
                             "events": _list_session_events(session_id, limit=20),
+                            "relay": _get_session_relay(session_id),
                         },
                     )
                     return
```
