# Hermes-native Warp fork — product contract

## Intent
Joe wants a Warp Terminal fork that keeps the useful terminal/workspace/Drive/session-sharing ergonomics while removing dependence on Warp-hosted cloud services. The fork should feel native to Hermes/Migi: local-first, agent-addressable, self-hostable on Joe's Tailscale network, and able to use Joe-controlled model/provider surfaces through Hermes/Headroom instead of Warp cloud models.

## Non-negotiables
- No built-in fallback to Warp-hosted Oz/cloud agent models.
- No silent calls to Warp-hosted cloud surfaces when Hermes-native mode is enabled.
- Session sharing must be self-hostable over Tailscale, not dependent on `sessions.app.warp.dev`.
- Warp Drive-like objects — workflows, notebooks, prompts/rules/context, environment variables — must remain usable.
- Workspace/team-like sharing must exist without Warp account/team billing dependency.
- Hermes/Migi must have a native integration path, not just a shell prompt workaround.
- Official upstream/public PRs require Joe's explicit approval; public fork branch work is acceptable.

## Replacement map
| Warp cloud surface | Current upstream shape | Hermes-native replacement target |
| --- | --- | --- |
| Hosted app GraphQL/API | `https://app.warp.dev/graphql/v2` via `ChannelState::server_root_url()` | `hermes-warp-gateway` GraphQL-compatible API on Tailscale |
| RTC/Warp Drive realtime sync | `wss://rtc.app.warp.dev/graphql/v2` | Tailscale WebSocket/SSE sync backed by SQLite/Postgres |
| Session sharing | `wss://sessions.app.warp.dev` | Self-hosted session relay tied to Hermes/Herdr session IDs |
| Oz cloud dashboard | `https://oz.warp.dev` | Hermes Desktop/dashboard links and Herdr/MigiMux run views |
| Hosted model/harness catalog | `getAvailableHarnesses` and `freeAvailableModels` GraphQL | Hermes provider catalog from Hermes config/Headroom/OpenAI-compatible local endpoints |
| Warp Drive storage | Cloud object GraphQL + local SQLite cache | Local-first Drive objects, synced through gateway |
| Authentication/team billing | Firebase/Warp accounts/team policy | Tailscale identity + optional local ACLs |
| Telemetry/crash cloud | RudderStack/Sentry where configured | Disabled by default; local log bundle only |

## First milestone acceptance
1. The open-source client has an explicit Hermes-native mode flag.
2. In Hermes-native mode, the OSS client honors `WARP_SERVER_ROOT_URL`, `WARP_WS_SERVER_URL`, and `WARP_SESSION_SHARING_SERVER_URL` overrides.
3. In Hermes-native mode, stale cached/cloud default Oz harnesses are not seeded into the UI.
4. If Hermes-native mode is enabled but the server URL still points at `warp.dev`, harness refresh does not fetch Warp cloud harnesses.
5. A launch script documents the local/Tailscale endpoint contract.
6. A prototype gateway returns Hermes/Migi model/harness catalog responses without Warp cloud.
7. The prototype gateway can create, read, update, and list local-first Drive-like objects in SQLite.
8. The docs cache under `~/.hermes/knowledge/warp-hermes-native/` records the Warp cloud/session/Drive docs used as source material.

## Later milestones
- Replace the prototype `hermes-warp-gateway` with a typed service and GraphQL-compatible resolvers for login-free local workspace state, Drive object sync, harness catalog, and model list.
- Add a first-class `Hermes`/`Migi` harness instead of treating Hermes only as a custom endpoint.
- Replace Warp account/team assumptions with local workspace ACLs using Tailscale identity and/or Hermes profile identity.
- Wire the Warp client cloud-object/Drive paths to the gateway's local object store.
- Wire session sharing to Herdr panes/Migi session IDs and expose join/watch/steer links on the Tailscale dashboard.
- Add migration/import for existing Warp Drive objects from local SQLite and/or exported files.
