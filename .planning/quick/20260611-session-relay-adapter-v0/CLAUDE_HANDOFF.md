[handoff]
Owner: Migi
To: Claude-Fable
Status: working
Action: Read-only audit of the current uncommitted Hermes Warp session relay adapter v0 slice.
Blocker: none
Evidence: repo /home/joe/Projects/warp-hermes-native on branch hermes-native-selfhost; current diff touches tools/hermes_warp_gateway.py, script/verify-hermes-native, runner scripts, env example.
Next: Claude-Fable returns terse findings only; Migi remains sole writer/verifier.

Use Terse Mode: keep chatter minimal, report only decisions, blockers, changed files, commands run, and evidence. Do not narrate tool use or restate the prompt.

This lane is owned by Hermes session 20260611_203833_0cec5d. If you are not in that lane or permissions are not visible/interactive, stop and report blocked.

Task:
1. Inspect the uncommitted diff only.
2. Focus on correctness of the stdlib WebSocket relay adapter for:
   - /sessions/create
   - /sessions/<id>/resume
   - /sessions/join/<id>
   - handshake/frame handling
   - persistence shape in SQLite/session_events/session_relays
   - smoke coverage in script/verify-hermes-native
   - public/private token leakage in inspection routes/docs
3. Do NOT edit files. Do NOT commit. Do NOT push. No hidden agents.
4. Return:
   - PASS or BLOCKED
   - top 3 concrete issues, if any
   - exact file/line evidence
   - recommended smallest fix.

Acceptance bar:
Migi can independently verify your claims with git diff, py_compile, and ./script/verify-hermes-native.
