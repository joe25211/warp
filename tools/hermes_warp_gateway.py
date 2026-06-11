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
import json
import os
import sqlite3
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


def _llm_info(model_id: str = DEFAULT_MODEL) -> dict[str, Any]:
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
        "hostConfigs": [{"enabled": True, "modelRoutingHost": "CustomEndpoint"}],
        "pricing": {"discountPercentage": None},
        "contextWindow": {"isConfigurable": True, "min": 1024, "max": 262144, "default": 65536},
    }


def _feature_model_choice() -> dict[str, Any]:
    available = {
        "defaultId": DEFAULT_MODEL,
        "choices": [_llm_info()],
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
                                    "harness": "ClaudeCode",
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
    if "cloudobject" in needle or "get_cloud_object" in needle:
        return _cloud_object_from_graphql(body)

    # Safe default: do not fabricate successful cloud state for unknown resolvers.
    return _graphql_error("Hermes Warp gateway prototype has no resolver for this operation", body)


class Handler(BaseHTTPRequestHandler):
    server_version = "hermes-warp-gateway/0.1"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/healthz", "/readyz"}:
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "hermes-warp-gateway",
                    "hermesBaseUrl": HERMES_BASE_URL,
                    "openaiBaseUrl": OPENAI_BASE_URL,
                    "defaultModel": DEFAULT_MODEL,
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


def main() -> None:
    global HOST, PORT, HERMES_BASE_URL, OPENAI_BASE_URL, DEFAULT_MODEL, DB_PATH

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
    DB_PATH = Path(args.db).expanduser()

    if args.print_env:
        print("export WARP_HERMES_NATIVE=1")
        print(f"export WARP_SERVER_ROOT_URL=http://{HOST}:{PORT}")
        print(f"export WARP_WS_SERVER_URL=ws://{HOST}:{PORT}/graphql/v2")
        print("export WARP_SESSION_SHARING_SERVER_URL=ws://127.0.0.1:8977")
        return

    _connect().close()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"hermes-warp-gateway listening on http://{HOST}:{PORT}")
    print(f"drive db: {DB_PATH}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
