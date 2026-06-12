# GSD State — Hermes-native Warp fork

## Active mode
GSD quick/nest is being used to continue the Hermes-native Warp fork. GSD state was initialized after prior product commits; earlier durable project state lives in `specs/hermes-native-selfhost/` and git history.

## Current branch
`hermes-native-selfhost` in `/home/joe/Projects/warp-hermes-native`.

## Approval gates
Commit, push, upstream PR, deploy/restart, and destructive actions require Joe approval.

## Quick Tasks Completed
| Date | Task | Summary |
| --- | --- | --- |
| 2026-06-10 | Session sharing registry seam | Verified `updateAgentTask` local task/session binding plus session inspection/handoff routes in `hermes-warp-gateway`; full relay remains next seam. |
| 2026-06-11 | Session event journal v0 | Added self-hosted session event persistence/list/append/SSE backlog endpoints to `hermes-warp-gateway`, wired `updateAgentTask` into `agent.task.updated` events, and updated gateway/product docs; full protocol-compatible live relay remains next seam. |
| 2026-06-11 | Session relay adapter v0 | Added gateway-owned WebSocket adapter routes for `/sessions/create`, reconnect-token-gated `/sessions/<id>/resume`, and explicit `/sessions/join/<id>` failure handling, backed by local SQLite relay state and smoke-tested in `script/verify-hermes-native`; downstream viewer fanout remains next seam. |
