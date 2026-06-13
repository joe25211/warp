#!/usr/bin/env python3
"""Tiny Hermes-native Warp compatibility gateway prototype.

This is not the final service. It is a stdlib-only executable seam that lets the fork point
`WARP_SERVER_ROOT_URL` / `WARP_WS_SERVER_URL` at Joe-controlled infrastructure and receive a
non-Warp-cloud harness/model catalog while the real Hermes gateway is built.

It also exposes a minimal local-first Drive object store under `/hermes/drive/objects`. That route
is intentionally outside Warp's upstream GraphQL schema for now: it gives Migi a working self-hosted
storage primitive while the exact Warp Drive GraphQL compatibility layer is mapped.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import sqlite3
import struct
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HOST = os.environ.get("HERMES_WARP_GATEWAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("HERMES_WARP_GATEWAY_PORT", "8976"))
HERMES_BASE_URL = os.environ.get("HERMES_BASE_URL", "http://127.0.0.1:9120")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8787/v1")
DEFAULT_MODEL = os.environ.get("HERMES_WARP_DEFAULT_MODEL", "hermes/migi-default")
SESSION_SHARING_URL = os.environ.get("WARP_SESSION_SHARING_SERVER_URL", "ws://127.0.0.1:8976")
# Match Warp's default shared-session size budget so ordinary Initialize frames with
# scrollback can be accepted and journaled by the v0 relay instead of being dropped
# before the protocol can answer.
MAX_WS_FRAME_BYTES = 128 * 1024 * 1024
DB_PATH = Path(
    os.environ.get(
        "HERMES_WARP_GATEWAY_DB",
        str(Path.home() / ".local/share/hermes-warp-gateway/drive.sqlite"),
    )
)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid port: {value}") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS drive_objects (
            id TEXT PRIMARY KEY,
            object_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            owner TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL,
            format TEXT,
            client_id TEXT,
            entrypoint TEXT
        )
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(drive_objects)")}
    for column, ddl in {
        "format": "ALTER TABLE drive_objects ADD COLUMN format TEXT",
        "client_id": "ALTER TABLE drive_objects ADD COLUMN client_id TEXT",
        "entrypoint": "ALTER TABLE drive_objects ADD COLUMN entrypoint TEXT",
    }.items():
        if column not in columns:
            conn.execute(ddl)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_tasks (
            task_id TEXT PRIMARY KEY,
            session_id TEXT,
            conversation_id TEXT,
            task_state TEXT,
            status_message TEXT,
            error_code TEXT,
            raw_input TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            task_id TEXT,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_events_session_id_event_id "
        "ON session_events(session_id, event_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_relays (
            session_id TEXT PRIMARY KEY,
            session_secret TEXT NOT NULL,
            reconnect_token TEXT NOT NULL,
            sharer_id TEXT NOT NULL,
            sharer_firebase_uid TEXT NOT NULL,
            last_event_no INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def _row_to_object(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "objectType": row["object_type"],
        "title": row["title"],
        "content": row["content"],
        "owner": row["owner"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "revision": row["revision"],
        "format": row["format"],
        "clientId": row["client_id"],
        "entrypoint": row["entrypoint"],
    }


def _row_to_agent_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "taskId": row["task_id"],
        "sessionId": row["session_id"],
        "conversationId": row["conversation_id"],
        "taskState": row["task_state"],
        "statusMessage": row["status_message"],
        "errorCode": row["error_code"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "rawInput": json.loads(row["raw_input"]),
    }


def _row_to_session_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "eventId": row["event_id"],
        "sessionId": row["session_id"],
        "taskId": row["task_id"],
        "kind": row["kind"],
        "payload": json.loads(row["payload"]),
        "createdAt": row["created_at"],
    }


def _input_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _list_drive_objects(object_type: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if object_type:
            rows = conn.execute(
                "SELECT * FROM drive_objects WHERE object_type = ? ORDER BY updated_at DESC",
                (object_type,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM drive_objects ORDER BY updated_at DESC").fetchall()
    return [_row_to_object(row) for row in rows]


def _get_drive_object(object_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM drive_objects WHERE id = ?", (object_id,)).fetchone()
    return _row_to_object(row) if row else None


def _upsert_agent_task(input_data: dict[str, Any]) -> dict[str, Any]:
    task_id = str(_input_value(input_data, "taskId", "task_id", "taskID") or "").strip()
    if not task_id:
        raise ValueError("updateAgentTask input missing taskId")

    status = _input_value(input_data, "statusMessage", "status_message")
    if isinstance(status, dict):
        status_message = str(status.get("message") or "")
        error_code = status.get("errorCode") or status.get("error_code")
    else:
        status_message = None
        error_code = None

    patch = {
        "task_id": task_id,
        "session_id": _input_value(input_data, "sessionId", "session_id"),
        "conversation_id": _input_value(input_data, "conversationId", "conversation_id"),
        "task_state": _input_value(input_data, "taskState", "task_state"),
        "status_message": status_message,
        "error_code": error_code,
        "raw_input": json.dumps(input_data, sort_keys=True),
    }
    timestamp = _now()
    with _connect() as conn:
        existing = conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, session_id, conversation_id, task_state, status_message, error_code,
                    raw_input, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patch["task_id"],
                    patch["session_id"],
                    patch["conversation_id"],
                    patch["task_state"],
                    patch["status_message"],
                    patch["error_code"],
                    patch["raw_input"],
                    timestamp,
                    timestamp,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE agent_tasks
                SET session_id = COALESCE(?, session_id),
                    conversation_id = COALESCE(?, conversation_id),
                    task_state = COALESCE(?, task_state),
                    status_message = COALESCE(?, status_message),
                    error_code = COALESCE(?, error_code),
                    raw_input = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    patch["session_id"],
                    patch["conversation_id"],
                    patch["task_state"],
                    patch["status_message"],
                    patch["error_code"],
                    patch["raw_input"],
                    timestamp,
                    task_id,
                ),
            )
    found = _get_agent_task(task_id)
    assert found is not None
    if found.get("sessionId"):
        _append_session_event(
            found["sessionId"],
            {
                "kind": "agent.task.updated",
                "taskId": found["taskId"],
                "payload": {
                    "taskId": found["taskId"],
                    "sessionId": found["sessionId"],
                    "conversationId": found["conversationId"],
                    "taskState": found["taskState"],
                    "statusMessage": found["statusMessage"],
                    "errorCode": found["errorCode"],
                },
            },
        )
    return found


def _get_agent_task(task_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
    return _row_to_agent_task(row) if row else None


def _list_agent_tasks() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM agent_tasks ORDER BY updated_at DESC").fetchall()
    return [_row_to_agent_task(row) for row in rows]


def _list_session_tasks(session_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_tasks WHERE session_id = ? ORDER BY updated_at DESC",
            (session_id,),
        ).fetchall()
    return [_row_to_agent_task(row) for row in rows]


def _event_limit(value: str | None) -> int:
    try:
        limit = int(value or "200")
    except ValueError:
        limit = 200
    return max(1, min(limit, 1000))


def _event_after(value: str | None) -> int:
    try:
        after = int(value or "0")
    except ValueError:
        after = 0
    return max(0, after)


def _row_to_session_relay(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "sessionId": row["session_id"],
        "sharerId": row["sharer_id"],
        "sharerFirebaseUid": row["sharer_firebase_uid"],
        "lastEventNo": row["last_event_no"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _get_session_relay(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM session_relays WHERE session_id = ?", (session_id,)).fetchone()
    return _row_to_session_relay(row) if row else None


def _get_session_relay_private(session_id: str) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute("SELECT * FROM session_relays WHERE session_id = ?", (session_id,)).fetchone()


def _delete_session_relay(session_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM session_relays WHERE session_id = ?", (session_id,))


def _create_session_relay() -> dict[str, str]:
    timestamp = _now()
    relay = {
        "sessionId": str(uuid.uuid4()),
        "sessionSecret": str(uuid.uuid4()),
        "reconnectToken": str(uuid.uuid4()),
        "sharerId": str(uuid.uuid4()),
        "sharerFirebaseUid": "local-sharer",
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO session_relays (
                session_id, session_secret, reconnect_token, sharer_id, sharer_firebase_uid,
                last_event_no, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relay["sessionId"],
                relay["sessionSecret"],
                relay["reconnectToken"],
                relay["sharerId"],
                relay["sharerFirebaseUid"],
                None,
                timestamp,
                timestamp,
            ),
        )
    return relay


def _relay_field(relay: dict[str, Any] | sqlite3.Row, dict_key: str, row_key: str) -> Any:
    if isinstance(relay, dict):
        return relay[dict_key]
    return relay[row_key]


def _participant_info(participant_id: str, firebase_uid: str, display_name: str) -> dict[str, Any]:
    return {
        "id": participant_id,
        "profile_data": {
            "firebase_uid": firebase_uid,
            "display_name": display_name,
            "photo_url": None,
            "email": None,
            "input_replica_id": "",
        },
        "selection": "None",
    }


def _relay_participant_list(relay: dict[str, Any] | sqlite3.Row) -> dict[str, Any]:
    sharer_id = str(_relay_field(relay, "sharerId", "sharer_id"))
    firebase_uid = str(_relay_field(relay, "sharerFirebaseUid", "sharer_firebase_uid"))
    return {
        "sharer": {"info": _participant_info(sharer_id, firebase_uid, "Hermes local sharer")},
        "viewers": [],
        "present_viewers": [],
        "absent_viewers": [],
        "guests": [],
        "pending_guests": [],
    }


def _update_relay_last_event(session_id: str, event_no: int | None) -> None:
    if event_no is None:
        return
    with _connect() as conn:
        conn.execute(
            """
            UPDATE session_relays
            SET last_event_no = CASE
                    WHEN last_event_no IS NULL OR ? > last_event_no THEN ?
                    ELSE last_event_no
                END,
                updated_at = ?
            WHERE session_id = ?
            """,
            (event_no, event_no, _now(), session_id),
        )


def _relay_message_summary(raw_message: str) -> dict[str, Any]:
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError:
        return {"variant": "invalid-json", "bytes": len(raw_message)}
    if not isinstance(message, dict) or not message:
        return {"variant": "unknown", "shape": type(message).__name__}
    variant = next(iter(message.keys()))
    value = message.get(variant)
    summary: dict[str, Any] = {"variant": variant}
    if isinstance(value, dict):
        summary["fields"] = sorted(value.keys())
        if variant == "OrderedTerminalEvent":
            event_no = value.get("event_no")
            if type(event_no) is int and event_no >= 0:
                summary["eventNo"] = event_no
        if variant == "Initialize":
            source_task_id = value.get("source_task_id")
            if source_task_id:
                summary["sourceTaskId"] = source_task_id
    return summary


def _parse_relay_message(raw_message: str) -> dict[str, Any] | None:
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError:
        return None
    return message if isinstance(message, dict) else None


def _extract_ordered_event_no(raw_message: str) -> int | None:
    message = _parse_relay_message(raw_message)
    if message is None:
        return None
    event = message.get("OrderedTerminalEvent")
    if isinstance(event, dict):
        event_no = event.get("event_no")
        if type(event_no) is int and event_no >= 0:
            return event_no
    return None


def _is_initialize_message(raw_message: str) -> bool:
    message = _parse_relay_message(raw_message)
    if message is None or set(message.keys()) != {"Initialize"}:
        return False
    return isinstance(message.get("Initialize"), dict)


def _failed_to_initialize_message(details: str) -> str:
    return json.dumps(
        {
            "FailedToInitializeSession": {
                "reason": {"InternalServerError": {"details": details}}
            }
        },
        separators=(",", ":"),
    )


def _failed_to_reconnect_message(reason: str) -> str:
    return json.dumps({"FailedToReconnect": {"reason": reason}}, separators=(",", ":"))


def _extract_reconnect_token(raw_message: str) -> str | None:
    message = _parse_relay_message(raw_message)
    reconnect = message.get("Reconnect") if message else None
    if isinstance(reconnect, dict):
        token = reconnect.get("reconnect_token")
        if isinstance(token, str) and token:
            return token
    return None


def _append_session_event(session_id: str, event_data: dict[str, Any]) -> dict[str, Any]:
    safe_session_id = str(session_id or "").strip()
    if not safe_session_id:
        raise ValueError("session event missing session id")
    kind = str(event_data.get("kind") or "session.event").strip() or "session.event"
    task_id = event_data.get("taskId") or event_data.get("task_id")
    payload = event_data.get("payload", event_data)
    timestamp = _now()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO session_events (session_id, task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                safe_session_id,
                str(task_id) if task_id is not None else None,
                kind,
                json.dumps(payload, sort_keys=True),
                timestamp,
            ),
        )
        row = conn.execute(
            "SELECT * FROM session_events WHERE event_id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    assert row is not None
    return _row_to_session_event(row)


def _list_session_events(session_id: str, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM session_events
            WHERE session_id = ? AND event_id > ?
            ORDER BY event_id ASC
            LIMIT ?
            """,
            (session_id, max(0, after), max(1, min(limit, 1000))),
        ).fetchall()
    return [_row_to_session_event(row) for row in rows]


_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _websocket_accept_key(key: str) -> str:
    digest = hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _read_exact(rfile: Any, size: int) -> bytes | None:
    data = rfile.read(size)
    return data if len(data) == size else None


def _read_ws_text(rfile: Any, wfile: Any | None = None) -> str | None:
    while True:
        header = _read_exact(rfile, 2)
        if header is None:
            return None
        first, second = header
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            extended = _read_exact(rfile, 2)
            if extended is None:
                return None
            length = struct.unpack("!H", extended)[0]
        elif length == 127:
            extended = _read_exact(rfile, 8)
            if extended is None:
                return None
            length = struct.unpack("!Q", extended)[0]
        if length > MAX_WS_FRAME_BYTES:
            return None
        mask = _read_exact(rfile, 4) if masked else b""
        if mask is None:
            return None
        payload = _read_exact(rfile, length) if length else b""
        if payload is None:
            return None
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            return None
        if opcode == 0x9:
            if wfile is not None:
                _write_ws_pong(wfile, payload)
            continue
        if opcode == 0xA:
            continue
        if opcode != 0x1:
            return ""
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return ""


def _write_ws_text(wfile: Any, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) < 65536:
        header.append(126)
        header.extend(struct.pack("!H", len(payload)))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", len(payload)))
    wfile.write(bytes(header) + payload)
    wfile.flush()


def _write_ws_pong(wfile: Any, payload: bytes = b"") -> None:
    if len(payload) >= 126:
        payload = payload[:125]
    wfile.write(bytes([0x8A, len(payload)]) + payload)
    wfile.flush()


def _write_ws_close(wfile: Any) -> None:
    wfile.write(b"\x88\x00")
    wfile.flush()


def _create_drive_object(payload: dict[str, Any]) -> dict[str, Any]:
    object_type = str(payload.get("objectType") or payload.get("object_type") or "prompt")
    title = str(payload.get("title") or "Untitled")
    content = str(payload.get("content") or "")
    owner = str(payload.get("owner") or "local")
    object_id = str(payload.get("id") or uuid.uuid4())
    object_format = payload.get("format")
    client_id = payload.get("clientId") or payload.get("client_id")
    entrypoint = payload.get("entrypoint")
    timestamp = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO drive_objects (
                id, object_type, title, content, owner, created_at, updated_at, revision, format, client_id, entrypoint
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (object_id, object_type, title, content, owner, timestamp, timestamp, object_format, client_id, entrypoint),
        )
    created = _get_drive_object(object_id)
    assert created is not None
    return created


def _update_drive_object(object_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    existing = _get_drive_object(object_id)
    if existing is None:
        return None
    object_type = str(payload.get("objectType") or payload.get("object_type") or existing["objectType"])
    title = str(payload.get("title") or existing["title"])
    content = str(payload.get("content") if "content" in payload else existing["content"])
    owner = str(payload.get("owner") or existing["owner"])
    object_format = payload.get("format") if "format" in payload else existing.get("format")
    client_id = payload.get("clientId") or payload.get("client_id") or existing.get("clientId")
    entrypoint = payload.get("entrypoint") or existing.get("entrypoint")
    timestamp = _now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE drive_objects
            SET object_type = ?, title = ?, content = ?, owner = ?, updated_at = ?, revision = revision + 1,
                format = ?, client_id = ?, entrypoint = ?
            WHERE id = ?
            """,
            (object_type, title, content, owner, timestamp, object_format, client_id, entrypoint, object_id),
        )
    return _get_drive_object(object_id)


def _llm_info(model_id: str | None = None) -> dict[str, Any]:
    model_id = model_id or DEFAULT_MODEL
    return {
        "displayName": "Hermes / Migi self-hosted",
        "baseModelName": model_id,
        "id": model_id,
        "reasoningLevel": None,
        "usageMetadata": {"creditMultiplier": None, "requestMultiplier": 0},
        "description": f"Joe-controlled Hermes provider catalog via {OPENAI_BASE_URL}",
        "disableReason": None,
        "visionSupported": True,
        "spec": {"cost": 0.0, "quality": 0.8, "speed": 0.8},
        "provider": "Unknown",
        "hostConfigs": [{"enabled": True, "modelRoutingHost": "CUSTOM_ENDPOINT"}],
        "pricing": {"discountPercentage": None},
        "contextWindow": {"isConfigurable": True, "min": 1024, "max": 262144, "default": 65536},
    }


def _feature_model_choice() -> dict[str, Any]:
    available = {
        "defaultId": DEFAULT_MODEL,
        "choices": [_llm_info(DEFAULT_MODEL)],
        "preferredCodexModelId": None,
    }
    return {
        "agentMode": available,
        "planning": available,
        "coding": available,
        "cliAgent": available,
        "computerUseAgent": available,
    }



def _response_context() -> dict[str, Any]:
    return {"serverVersion": "hermes-warp-gateway"}


def _space() -> dict[str, Any]:
    return {"__typename": "Space", "uid": "local", "type": "User"}


def _metadata(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "creatorUid": obj.get("owner") or "local",
        "currentEditorUid": None,
        "isWelcomeObject": False,
        "lastEditorUid": obj.get("owner") or "local",
        "metadataLastUpdatedTs": obj["updatedAt"],
        "parent": _space(),
        "revisionTs": obj["updatedAt"],
        "trashedTs": None,
        "uid": obj["id"],
    }


def _permissions(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "guests": [],
        "lastUpdatedTs": obj["updatedAt"],
        "anyoneLinkSharing": None,
        "space": _space(),
    }


def _workflow(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "__typename": "Workflow",
        "data": obj["content"],
        "metadata": _metadata(obj),
        "permissions": _permissions(obj),
    }


def _generic_string_object(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "__typename": "GenericStringObject",
        "format": obj.get("format") or "JsonWorkflowEnum",
        "metadata": _metadata(obj),
        "permissions": _permissions(obj),
        "serializedModel": obj["content"],
    }


def _graphql_cloud_object(obj: dict[str, Any]) -> dict[str, Any]:
    if obj["objectType"] == "workflow":
        return _workflow(obj)
    return _generic_string_object(obj)


def _extract_title(serialized: str, fallback: str) -> str:
    try:
        data = json.loads(serialized)
    except json.JSONDecodeError:
        return fallback
    if isinstance(data, dict):
        for key in ("name", "title", "description"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _variables(body: dict[str, Any]) -> dict[str, Any]:
    variables = body.get("variables")
    return variables if isinstance(variables, dict) else {}


def _input(body: dict[str, Any]) -> dict[str, Any]:
    value = _variables(body).get("input")
    return value if isinstance(value, dict) else {}


def _create_workflow_from_graphql(body: dict[str, Any]) -> dict[str, Any]:
    input_data = _input(body)
    serialized = str(input_data.get("data") or "")
    created = _create_drive_object(
        {
            "objectType": "workflow",
            "title": _extract_title(serialized, "Untitled workflow"),
            "content": serialized,
            "owner": "local",
            "entrypoint": input_data.get("entrypoint"),
        }
    )
    return {
        "data": {
            "createWorkflow": {
                "__typename": "CreateWorkflowOutput",
                "responseContext": _response_context(),
                "workflow": _workflow(created),
                "revisionTs": created["updatedAt"],
            }
        }
    }


def _update_workflow_from_graphql(body: dict[str, Any]) -> dict[str, Any]:
    input_data = _input(body)
    uid = str(input_data.get("uid") or "")
    serialized = str(input_data.get("data") or "")
    updated = _update_drive_object(
        uid,
        {
            "objectType": "workflow",
            "title": _extract_title(serialized, "Untitled workflow"),
            "content": serialized,
        },
    )
    if updated is None:
        return _graphql_error("workflow not found", body)
    return {
        "data": {
            "updateWorkflow": {
                "__typename": "UpdateWorkflowOutput",
                "responseContext": _response_context(),
                "update": {
                    "__typename": "ObjectUpdateSuccess",
                    "lastEditorUid": updated.get("owner") or "local",
                    "revisionTs": updated["updatedAt"],
                },
            }
        }
    }


def _generic_payload_from_graphql(input_data: dict[str, Any]) -> dict[str, Any]:
    gso = input_data.get("genericStringObject") or input_data.get("generic_string_object") or input_data
    if not isinstance(gso, dict):
        gso = {}
    serialized = str(gso.get("serializedModel") or gso.get("serialized_model") or "")
    object_format = str(gso.get("format") or "JsonWorkflowEnum")
    return {
        "id": str(gso.get("id") or uuid.uuid4()),
        "objectType": "generic_string_object",
        "title": _extract_title(serialized, object_format),
        "content": serialized,
        "owner": "local",
        "format": object_format,
        "clientId": gso.get("clientId") or gso.get("client_id"),
        "entrypoint": gso.get("entrypoint"),
    }


def _create_gso_output(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "__typename": "CreateGenericStringObjectOutput",
        "clientId": obj.get("clientId") or obj["id"],
        "genericStringObject": _generic_string_object(obj),
        "responseContext": _response_context(),
        "revisionTs": obj["updatedAt"],
    }


def _create_generic_string_object_from_graphql(body: dict[str, Any]) -> dict[str, Any]:
    created = _create_drive_object(_generic_payload_from_graphql(_input(body)))
    return {
        "data": {
            "createGenericStringObject": {
                "__typename": "CreateGenericStringObjectOutput",
                "clientId": created.get("clientId") or created["id"],
                "genericStringObject": _generic_string_object(created),
                "responseContext": _response_context(),
                "revisionTs": created["updatedAt"],
            }
        }
    }


def _bulk_create_objects_from_graphql(body: dict[str, Any]) -> dict[str, Any]:
    input_data = _input(body)
    bulk = input_data.get("genericStringObjects") or input_data.get("generic_string_objects") or {}
    if not isinstance(bulk, dict):
        bulk = {}
    objects = bulk.get("objects") if isinstance(bulk.get("objects"), list) else []
    created = [_create_drive_object(_generic_payload_from_graphql(obj)) for obj in objects]
    return {
        "data": {
            "bulkCreateObjects": {
                "__typename": "BulkCreateObjectsOutput",
                "genericStringObjects": {"objects": [_create_gso_output(obj) for obj in created]},
                "responseContext": _response_context(),
            }
        }
    }


def _update_generic_string_object_from_graphql(body: dict[str, Any]) -> dict[str, Any]:
    input_data = _input(body)
    uid = str(input_data.get("uid") or "")
    serialized = str(input_data.get("serializedModel") or input_data.get("serialized_model") or "")
    updated = _update_drive_object(
        uid,
        {
            "objectType": "generic_string_object",
            "title": _extract_title(serialized, "JsonWorkflowEnum"),
            "content": serialized,
        },
    )
    if updated is None:
        return _graphql_error("generic string object not found", body)
    return {
        "data": {
            "updateGenericStringObject": {
                "__typename": "UpdateGenericStringObjectOutput",
                "responseContext": _response_context(),
                "update": {
                    "__typename": "ObjectUpdateSuccess",
                    "lastEditorUid": updated.get("owner") or "local",
                    "revisionTs": updated["updatedAt"],
                },
            }
        }
    }


def _updated_cloud_objects_from_graphql(_: dict[str, Any]) -> dict[str, Any]:
    objects = _list_drive_objects()
    workflows = [obj for obj in objects if obj["objectType"] == "workflow"]
    generic_string_objects = [obj for obj in objects if obj["objectType"] == "generic_string_object"]
    return {
        "data": {
            "updatedCloudObjects": {
                "__typename": "UpdatedCloudObjectsOutput",
                "actionHistories": [],
                "deletedObjectUids": {
                    "folderUids": [],
                    "genericStringObjectUids": [],
                    "notebookUids": [],
                    "workflowUids": [],
                },
                "folders": [],
                "genericStringObjects": [_generic_string_object(obj) for obj in generic_string_objects],
                "mcpGallery": [],
                "notebooks": [],
                "responseContext": _response_context(),
                "userProfiles": [],
                "workflows": [_workflow(obj) for obj in workflows],
            }
        }
    }


def _cloud_object_from_graphql(body: dict[str, Any]) -> dict[str, Any]:
    uid = str(_input(body).get("uid") or "")
    obj = _get_drive_object(uid)
    if obj is None:
        return _graphql_error("cloud object not found", body)
    return {
        "data": {
            "cloudObject": {
                "__typename": "CloudObjectOutput",
                "object": _graphql_cloud_object(obj),
                "actionHistories": [],
                "responseContext": _response_context(),
            }
        }
    }


def _create_agent_task_from_graphql(body: dict[str, Any]) -> dict[str, Any]:
    input_data = dict(_input(body))
    task_id = str(uuid.uuid4())
    input_data["taskId"] = task_id
    input_data.setdefault("taskState", "CLAIMED")
    try:
        task = _upsert_agent_task(input_data)
    except ValueError as exc:
        return _graphql_error(str(exc), body)
    return {
        "data": {
            "createAgentTask": {
                "__typename": "CreateAgentTaskOutput",
                "responseContext": _response_context(),
                "taskId": task["taskId"],
            }
        }
    }


def _update_agent_task_from_graphql(body: dict[str, Any]) -> dict[str, Any]:
    try:
        task = _upsert_agent_task(_input(body))
    except ValueError as exc:
        return _graphql_error(str(exc), body)
    return {
        "data": {
            "updateAgentTask": {
                "__typename": "UpdateAgentTaskOutput",
                "responseContext": _response_context(),
                "taskId": task["taskId"],
                "sessionId": task["sessionId"],
                "conversationId": task["conversationId"],
            }
        }
    }


def _graphql_error(message: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "errors": [
            {
                "message": message,
                "extensions": {"operationName": body.get("operationName") or ""},
            }
        ],
        "data": None,
    }


def _graphql_response(body: dict[str, Any]) -> dict[str, Any]:
    query = body.get("query") or ""
    operation = body.get("operationName") or ""
    needle = (operation + "\n" + query).lower()

    if "get_available_harnesses" in needle or "availableharnesses" in needle:
        return {
            "data": {
                "user": {
                    "__typename": "UserOutput",
                    "user": {
                        "availableHarnesses": {
                            "harnesses": [
                                {
                                    "harness": "HERMES",
                                    "displayName": "Hermes / Migi local agent",
                                    "enabled": True,
                                    "availableModels": [
                                        {
                                            "id": DEFAULT_MODEL,
                                            "displayName": "Hermes / Migi self-hosted",
                                            "reasoningLevel": None,
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                }
            }
        }

    if "free_available_models" in needle or "freeavailablemodels" in needle:
        return {
            "data": {
                "freeAvailableModels": {
                    "__typename": "FreeAvailableModelsOutput",
                    "featureModelChoice": _feature_model_choice(),
                    "responseContext": _response_context(),
                }
            }
        }

    if "get_feature_model_choices" in needle or "featuremodelchoice" in needle:
        return {
            "data": {
                "user": {
                    "__typename": "UserOutput",
                    "user": {"workspaces": [{"featureModelChoice": _feature_model_choice()}]},
                }
            }
        }

    if "createworkflow" in needle or "create_workflow" in needle:
        return _create_workflow_from_graphql(body)
    if "updateworkflow" in needle or "update_workflow" in needle:
        return _update_workflow_from_graphql(body)
    if "creategenericstringobject" in needle or "create_generic_string_object" in needle:
        return _create_generic_string_object_from_graphql(body)
    if "bulkcreateobjects" in needle or "bulk_create_objects" in needle:
        return _bulk_create_objects_from_graphql(body)
    if "updategenericstringobject" in needle or "update_generic_string_object" in needle:
        return _update_generic_string_object_from_graphql(body)
    if "updatedcloudobjects" in needle or "get_updated_cloud_objects" in needle:
        return _updated_cloud_objects_from_graphql(body)
    if "createagenttask" in needle or "create_agent_task" in needle:
        return _create_agent_task_from_graphql(body)
    if "updateagenttask" in needle or "update_agent_task" in needle:
        return _update_agent_task_from_graphql(body)
    if "cloudobject" in needle or "get_cloud_object" in needle:
        return _cloud_object_from_graphql(body)

    # Safe default: do not fabricate successful cloud state for unknown resolvers.
    return _graphql_error("Hermes Warp gateway prototype has no resolver for this operation", body)


class Handler(BaseHTTPRequestHandler):
    server_version = "hermes-warp-gateway/0.1"
    protocol_version = "HTTP/1.1"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_html(self, status: int, markup: str) -> None:
        encoded = markup.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _is_websocket_request(self) -> bool:
        return self.headers.get("upgrade", "").lower() == "websocket"

    def _send_websocket_handshake(self, protocol: str | None = None) -> bool:
        key = self.headers.get("sec-websocket-key")
        if not key:
            self._send_json(400, {"error": "missing sec-websocket-key"})
            return False
        self.send_response(101, "Switching Protocols")
        self.send_header("upgrade", "websocket")
        self.send_header("connection", "Upgrade")
        self.send_header("sec-websocket-accept", _websocket_accept_key(key))
        requested_protocols = {
            value.strip()
            for value in self.headers.get("sec-websocket-protocol", "").split(",")
            if value.strip()
        }
        if protocol and protocol in requested_protocols:
            self.send_header("sec-websocket-protocol", protocol)
        self.end_headers()
        return True

    def _handle_graphql_websocket(self) -> None:
        if not self._send_websocket_handshake("graphql-transport-ws"):
            return
        self.close_connection = True
        while True:
            message = _read_ws_text(self.rfile, self.wfile)
            if message is None:
                return
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                _write_ws_close(self.wfile)
                return
            message_type = payload.get("type")
            if message_type == "connection_init":
                _write_ws_text(self.wfile, json.dumps({"type": "connection_ack"}, separators=(",", ":")))
            elif message_type == "ping":
                response = {"type": "pong"}
                if "payload" in payload:
                    response["payload"] = payload["payload"]
                _write_ws_text(self.wfile, json.dumps(response, separators=(",", ":")))
            elif message_type == "complete":
                _write_ws_close(self.wfile)
                return
            elif message_type == "subscribe":
                # v0 has no live Drive fanout yet. Keep the subscription open after ack
                # so Warp's listener has a valid local websocket instead of a 404/retry loop.
                continue

    def _handle_session_websocket(self, parsed: Any) -> None:
        parts = parsed.path.strip("/").split("/")
        if parts == ["sessions", "create"]:
            mode = "create"
            session_id = None
        elif len(parts) == 3 and parts[0] == "sessions" and parts[2] == "resume":
            mode = "resume"
            session_id = parts[1]
        elif len(parts) == 3 and parts[0] == "sessions" and parts[1] == "join":
            mode = "join"
            session_id = parts[2]
        else:
            self._send_json(404, {"error": "unknown session relay websocket route"})
            return

        if not self._send_websocket_handshake():
            return
        self.close_connection = True

        first_message = _read_ws_text(self.rfile, self.wfile)
        if first_message is None:
            return

        if mode == "create":
            if not _is_initialize_message(first_message):
                _write_ws_text(self.wfile, _failed_to_initialize_message("first message must be Initialize"))
                _write_ws_close(self.wfile)
                return
            relay = _create_session_relay()
            active_session_id = relay["sessionId"]
            _append_session_event(
                active_session_id,
                {
                    "kind": "relay.sharer.initialize",
                    "payload": _relay_message_summary(first_message),
                },
            )
            _write_ws_text(
                self.wfile,
                json.dumps(
                    {
                        "SessionInitialized": {
                            "session_id": relay["sessionId"],
                            "session_secret": relay["sessionSecret"],
                            "reconnect_token": relay["reconnectToken"],
                            "sharer_id": relay["sharerId"],
                            "sharer_firebase_uid": relay["sharerFirebaseUid"],
                        }
                    },
                    separators=(",", ":"),
                ),
            )
        elif mode == "resume" and session_id is not None:
            active_session_id = session_id
            relay = _get_session_relay_private(session_id)
            reconnect_token = _extract_reconnect_token(first_message)
            if relay is None:
                _write_ws_text(self.wfile, _failed_to_reconnect_message("SessionNotFound"))
                _write_ws_close(self.wfile)
                return
            if reconnect_token != relay["reconnect_token"]:
                _write_ws_text(self.wfile, _failed_to_reconnect_message("WrongReconnectionToken"))
                _write_ws_close(self.wfile)
                return
            _append_session_event(
                active_session_id,
                {
                    "kind": "relay.sharer.reconnect",
                    "payload": _relay_message_summary(first_message),
                },
            )
            _write_ws_text(
                self.wfile,
                json.dumps(
                    {
                        "SessionReconnected": {
                            "last_received_event_no": relay["last_event_no"],
                            "participant_list": _relay_participant_list(relay),
                        }
                    },
                    separators=(",", ":"),
                ),
            )
        elif mode == "join" and session_id is not None:
            active_session_id = session_id
            relay = _get_session_relay(session_id)
            _append_session_event(
                active_session_id,
                {
                    "kind": "relay.viewer.join.attempted",
                    "payload": _relay_message_summary(first_message),
                },
            )
            reason = "Invalid" if relay else "SessionNotFound"
            _write_ws_text(
                self.wfile,
                json.dumps({"FailedToJoin": {"reason": reason}}, separators=(",", ":")),
            )
            _write_ws_close(self.wfile)
            return
        else:  # pragma: no cover - defensive branch
            return

        while True:
            message = _read_ws_text(self.rfile, self.wfile)
            if message is None:
                break
            summary = _relay_message_summary(message)
            event_no = _extract_ordered_event_no(message)
            variant = summary.get("variant")
            if variant == "OrderedTerminalEvent" and event_no is None:
                continue
            _append_session_event(
                active_session_id,
                {"kind": "relay.sharer.upstream", "payload": summary},
            )
            _update_relay_last_event(active_session_id, event_no)
            if variant == "Ping":
                try:
                    data = json.loads(message).get("Ping", {}).get("data", [])
                except json.JSONDecodeError:
                    data = []
                _write_ws_text(self.wfile, json.dumps({"Pong": {"data": data}}, separators=(",", ":")))
            elif variant == "OrderedTerminalEvent" and event_no is not None:
                _write_ws_text(
                    self.wfile,
                    json.dumps(
                        {"EventsProcessedAck": {"latest_processed_event_no": event_no}},
                        separators=(",", ":"),
                    ),
                )
            elif variant == "EndSession":
                _append_session_event(
                    active_session_id,
                    {"kind": "relay.sharer.end", "payload": summary},
                )
                _delete_session_relay(active_session_id)
                _write_ws_close(self.wfile)
                break

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if self._is_websocket_request() and parsed.path == "/graphql/v2":
            self._handle_graphql_websocket()
            return
        if self._is_websocket_request() and parsed.path.startswith("/sessions/"):
            self._handle_session_websocket(parsed)
            return
        if parsed.path in {"/", "/healthz", "/readyz"}:
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "hermes-warp-gateway",
                    "hermesBaseUrl": HERMES_BASE_URL,
                    "openaiBaseUrl": OPENAI_BASE_URL,
                    "defaultModel": DEFAULT_MODEL,
                    "sessionSharingUrl": SESSION_SHARING_URL,
                    "driveDbPath": str(DB_PATH),
                },
            )
            return

        if parsed.path == "/hermes/drive/objects":
            params = parse_qs(parsed.query)
            self._send_json(200, {"objects": _list_drive_objects(params.get("objectType", [None])[0])})
            return

        if parsed.path.startswith("/hermes/drive/objects/"):
            object_id = parsed.path.rsplit("/", 1)[-1]
            found = _get_drive_object(object_id)
            if found is None:
                self._send_json(404, {"error": "drive object not found"})
            else:
                self._send_json(200, {"object": found})
            return

        if parsed.path == "/hermes/agent-tasks":
            self._send_json(200, {"tasks": _list_agent_tasks()})
            return

        if parsed.path.startswith("/hermes/agent-tasks/"):
            task_id = parsed.path.rsplit("/", 1)[-1]
            found = _get_agent_task(task_id)
            if found is None:
                self._send_json(404, {"error": "agent task not found"})
            else:
                self._send_json(200, {"task": found})
            return

        if parsed.path.startswith("/hermes/sessions/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "hermes" and parts[1] == "sessions":
                session_id = parts[2]
                if len(parts) == 4 and parts[3] == "events":
                    params = parse_qs(parsed.query)
                    after = _event_after(params.get("after", [None])[0])
                    limit = _event_limit(params.get("limit", [None])[0])
                    self._send_json(
                        200,
                        {
                            "sessionId": session_id,
                            "events": _list_session_events(session_id, after=after, limit=limit),
                        },
                    )
                    return
                if len(parts) == 5 and parts[3] == "events" and parts[4] == "stream":
                    params = parse_qs(parsed.query)
                    after = _event_after(params.get("after", [None])[0])
                    limit = _event_limit(params.get("limit", [None])[0])
                    events = _list_session_events(session_id, after=after, limit=limit)
                    encoded = "".join(
                        "id: {event_id}\nevent: {kind}\ndata: {data}\n\n".format(
                            event_id=event["eventId"],
                            kind=event["kind"],
                            data=json.dumps(event, separators=(",", ":")),
                        )
                        for event in events
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream; charset=utf-8")
                    self.send_header("cache-control", "no-cache")
                    self.send_header("content-length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                if len(parts) == 3:
                    self._send_json(
                        200,
                        {
                            "sessionId": session_id,
                            "tasks": _list_session_tasks(session_id),
                            "events": _list_session_events(session_id, limit=20),
                            "relay": _get_session_relay(session_id),
                        },
                    )
                    return

        if parsed.path.startswith("/session/"):
            session_id = parsed.path.rsplit("/", 1)[-1]
            tasks = _list_session_tasks(session_id)
            events = _list_session_events(session_id, limit=10)
            task_items = "".join(
                f"<li><code>{html.escape(task['taskId'])}</code> — "
                f"{html.escape(str(task.get('taskState') or 'state unknown'))}</li>"
                for task in tasks
            ) or "<li>No agent tasks have reported this session id yet.</li>"
            event_items = "".join(
                f"<li><code>#{event['eventId']}</code> "
                f"{html.escape(event['kind'])} — "
                f"{html.escape(str(event.get('taskId') or 'session'))}</li>"
                for event in events
            ) or "<li>No session events have been written yet.</li>"
            safe_session_id = html.escape(session_id)
            self._send_html(
                200,
                f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Hermes Warp Session {safe_session_id}</title><style>body{{margin:0;background:#030405;color:#e8ecec;font-family:system-ui,sans-serif;padding:32px}}main{{max-width:920px;margin:auto;border:1px solid #343b3d;border-radius:24px;background:#0b0f10;padding:28px;box-shadow:0 24px 80px #000}}.k{{color:#c89b45;text-transform:uppercase;letter-spacing:.16em;font-weight:900;font-size:12px}}h1{{font-size:clamp(32px,6vw,64px);line-height:.9;margin:.25em 0}}code{{color:#d8b16c}}li{{margin:.6em 0}}a{{color:#d8b16c}}</style></head><body><main><div class="k">Hermes-native Warp · self-host session registry + event journal</div><h1>Session {safe_session_id}</h1><p>This is the local/Tailscale handoff surface for a Warp shared session. Full protocol-compatible terminal relay is a later seam; this page proves the client can bind agent tasks and append session events to Joe-controlled infrastructure without Warp cloud.</p><h2>Linked tasks</h2><ul>{task_items}</ul><h2>Recent events</h2><ul>{event_items}</ul><p>Machine-readable state: <a href="/hermes/sessions/{safe_session_id}">/hermes/sessions/{safe_session_id}</a> · <a href="/hermes/sessions/{safe_session_id}/events">/hermes/sessions/{safe_session_id}/events</a> · <a href="/hermes/sessions/{safe_session_id}/events/stream?once=1">SSE once</a></p></main></body></html>""",
            )
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path.startswith("/graphql/v2"):
            try:
                body = self._read_json()
            except Exception as exc:  # pragma: no cover - defensive gateway edge
                self._send_json(400, {"error": f"invalid json: {exc}"})
                return
            self._send_json(200, _graphql_response(body))
            return

        if parsed.path.startswith("/hermes/sessions/") and parsed.path.endswith("/events"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "hermes" and parts[1] == "sessions" and parts[3] == "events":
                try:
                    event = _append_session_event(parts[2], self._read_json())
                except Exception as exc:  # pragma: no cover - defensive gateway edge
                    self._send_json(400, {"error": f"invalid session event: {exc}"})
                    return
                self._send_json(201, {"event": event})
                return

        if parsed.path == "/hermes/drive/objects":
            try:
                self._send_json(201, {"object": _create_drive_object(self._read_json())})
            except Exception as exc:  # pragma: no cover - defensive gateway edge
                self._send_json(400, {"error": f"invalid drive object: {exc}"})
            return

        self._send_json(404, {"error": "not found"})

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path.startswith("/hermes/drive/objects/"):
            object_id = parsed.path.rsplit("/", 1)[-1]
            try:
                updated = _update_drive_object(object_id, self._read_json())
            except Exception as exc:  # pragma: no cover - defensive gateway edge
                self._send_json(400, {"error": f"invalid drive object update: {exc}"})
                return
            if updated is None:
                self._send_json(404, {"error": "drive object not found"})
            else:
                self._send_json(200, {"object": updated})
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")


def _normalize_session_sharing_url(value: str, parser: argparse.ArgumentParser) -> str:
    parsed = urlparse(value)
    if parsed.path not in {"", "/"}:
        parser.error("--session-sharing-url must not include a path; use the gateway base ws://host:port")
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        parser.error("--session-sharing-url must be a ws:// or wss:// gateway base URL")
    return value.rstrip("/")


def main() -> None:
    global HOST, PORT, HERMES_BASE_URL, OPENAI_BASE_URL, DEFAULT_MODEL, SESSION_SHARING_URL, DB_PATH

    parser = argparse.ArgumentParser(
        description="Hermes-native Warp compatibility gateway prototype",
    )
    parser.add_argument(
        "--host",
        default=HOST,
        help="bind host (default: env HERMES_WARP_GATEWAY_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=PORT,
        help="bind port (default: env HERMES_WARP_GATEWAY_PORT or 8976)",
    )
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help="SQLite Drive object database path (default: env HERMES_WARP_GATEWAY_DB)",
    )
    parser.add_argument(
        "--hermes-base-url",
        default=HERMES_BASE_URL,
        help="Hermes dashboard/API base URL advertised in health output",
    )
    parser.add_argument(
        "--openai-base-url",
        default=OPENAI_BASE_URL,
        help="OpenAI-compatible provider base URL advertised in model catalog",
    )
    parser.add_argument(
        "--default-model",
        default=DEFAULT_MODEL,
        help="default Hermes/Migi model id advertised to Warp",
    )
    parser.add_argument(
        "--session-sharing-url",
        default=None,
        help="self-host/Tailscale session sharing URL exported for Warp launch",
    )
    parser.add_argument(
        "--print-env",
        action="store_true",
        help="print matching WARP_* launch environment and exit",
    )
    args = parser.parse_args()

    HOST = args.host
    PORT = args.port
    HERMES_BASE_URL = args.hermes_base_url
    OPENAI_BASE_URL = args.openai_base_url
    DEFAULT_MODEL = args.default_model
    if args.session_sharing_url is not None:
        SESSION_SHARING_URL = _normalize_session_sharing_url(args.session_sharing_url, parser)
    elif "WARP_SESSION_SHARING_SERVER_URL" in os.environ:
        SESSION_SHARING_URL = _normalize_session_sharing_url(SESSION_SHARING_URL, parser)
    else:
        SESSION_SHARING_URL = f"ws://{HOST}:{PORT}"
    DB_PATH = Path(args.db).expanduser()

    if args.print_env:
        print("export WARP_HERMES_NATIVE=1")
        print(f"export WARP_SERVER_ROOT_URL=http://{HOST}:{PORT}")
        print(f"export WARP_WS_SERVER_URL=ws://{HOST}:{PORT}/graphql/v2")
        print(f"export WARP_SESSION_SHARING_SERVER_URL={SESSION_SHARING_URL}")
        return

    _connect().close()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"hermes-warp-gateway listening on http://{HOST}:{PORT}")
    print(f"drive db: {DB_PATH}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
