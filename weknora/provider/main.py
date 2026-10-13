import ipaddress
import json
import re
import sys
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

_PROTOCOL_VERSION = 1
_READ_SCOPE = "knowledge.read"
# WeKnoraX grants only the scopes its application allows, so requesting write
# still yields a read-only connection where writes are not enabled.
_REQUESTED_SCOPES = "knowledge.read knowledge.write"
# Text tools mirror the REST API and MCP tools inspected at this WeKnoraX commit.
_WEKNORAX_SOURCE_REVISION = "WeKnoraX@f03b81a04fce3e951f0b95296e47d154559afeb4"
_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MANUAL_CONTENT_MAX_LENGTH = 200000
_MANUAL_STATUSES = ("publish", "draft")
_STATUS_ERROR_CODES = {
    400: "bad_request",
    403: "insufficient_scope",
    404: "not_found",
    409: "conflict",
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _normalize_base_url(value: object) -> str | None:
    raw = str(value or "").strip().rstrip("/")
    if not raw or any(character.isspace() for character in raw):
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
        hostname = _normalize_hostname(parsed.hostname or "")
    except (UnicodeError, ValueError):
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    if ":" in hostname:
        hostname = f"[{hostname}]"
    default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    port_suffix = f":{port}" if port is not None and not default_port else ""
    return f"{parsed.scheme}://{hostname}{port_suffix}"


def _normalize_hostname(hostname: str) -> str:
    normalized = hostname.rstrip(".").lower()
    if not normalized:
        raise ValueError("invalid HTTP hostname")
    try:
        return ipaddress.ip_address(normalized).compressed
    except ValueError:
        pass
    ascii_hostname = normalized.encode("idna").decode("ascii")
    if len(ascii_hostname) > 253 or any(
        not _DNS_LABEL_PATTERN.fullmatch(label) for label in ascii_hostname.split(".")
    ):
        raise ValueError("invalid HTTP hostname")
    return ascii_hostname


def _configuration(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    configuration = context.get("configuration")
    if not isinstance(configuration, dict):
        raise ProgramError("bad_request", "Connector configuration is invalid")
    public = configuration.get("public")
    secret = configuration.get("secret")
    if not isinstance(public, dict) or not isinstance(secret, dict):
        raise ProgramError("bad_request", "Connector configuration is invalid")
    return public, secret


def _validate_configuration(context: dict[str, Any]) -> dict[str, Any]:
    public, secret = _configuration(context)
    require_complete = context.get("require_complete") is True
    raw_base_url = public.get("base_url")
    base_url = _normalize_base_url(raw_base_url)
    client_id = str(public.get("client_id") or "").strip()
    client_secret = str(secret.get("client_secret") or "").strip()
    if base_url is None and (require_complete or raw_base_url):
        raise ProgramError(
            "bad_request",
            "WeKnora service URL must be an HTTP(S) origin",
        )
    if client_id and not client_id.startswith("wkapp_"):
        raise ProgramError("bad_request", "WeKnora Client ID must start with wkapp_")
    if client_secret and not client_secret.startswith("wks_"):
        raise ProgramError(
            "bad_request",
            "WeKnora Client Secret must start with wks_",
        )
    if require_complete and (not client_id or not client_secret):
        raise ProgramError(
            "bad_request",
            "WeKnora application credentials are required",
        )
    return {}


def _require_base_url(public: dict[str, Any]) -> str:
    base_url = _normalize_base_url(public.get("base_url"))
    if base_url is None:
        raise ProgramError("bad_request", "WeKnora service URL is invalid")
    return base_url


def _build_launch_url(base_url: str, launch_path: object) -> str:
    if not isinstance(launch_path, str) or not launch_path.strip():
        raise ProgramError("external_error", "WeKnora launch path is unavailable")
    try:
        parsed_path = urlsplit(launch_path)
    except ValueError as exc:
        raise ProgramError(
            "external_error",
            "WeKnora returned an invalid launch path",
        ) from exc
    if (
        parsed_path.scheme
        or parsed_path.netloc
        or not parsed_path.path.startswith("/integrations/launch/")
        or ".." in parsed_path.path.split("/")
        or parsed_path.query
        or parsed_path.fragment
    ):
        raise ProgramError("external_error", "WeKnora returned an invalid launch path")
    launch_url = urljoin(f"{base_url}/", launch_path.lstrip("/"))
    parsed_base = urlsplit(base_url)
    parsed_launch = urlsplit(launch_url)
    if (
        parsed_launch.scheme != parsed_base.scheme
        or parsed_launch.netloc != parsed_base.netloc
        or not parsed_launch.path.startswith("/integrations/launch/")
    ):
        raise ProgramError("external_error", "WeKnora returned an invalid launch path")
    return launch_url


def _authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    public, _ = _configuration(context)
    return {
        "identity": {
            "base_url": _normalize_base_url(public.get("base_url")),
            "client_id": str(public.get("client_id") or "").strip(),
        }
    }


def _authorization_begin(context: dict[str, Any]) -> dict[str, Any]:
    _validate_configuration({**context, "require_complete": True})
    public, _ = _configuration(context)
    base_url = _require_base_url(public)
    values = {
        "client_id": str(public["client_id"]).strip(),
        "redirect_uri": str(context.get("redirect_uri") or ""),
        "state": str(context.get("state") or ""),
        "scope": _REQUESTED_SCOPES,
        "code_challenge": str(context.get("code_challenge") or ""),
        "code_challenge_method": "S256",
    }
    if context.get("intent") == "reauthorize":
        values["prompt"] = "consent"
    return {
        "type": "redirect",
        "authorize_url": f"{base_url}/integrations/authorize?{urlencode(values)}",
        "private_context": {},
    }


def _authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    _validate_configuration({**context, "require_complete": True})
    public, secret = _configuration(context)
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "oauth_code":
        raise ProgramError(
            "bad_request", "WeKnora requires an OAuth authorization code"
        )
    base_url = _require_base_url(public)
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            response = client.post(
                f"{base_url}/api/v1/integrations/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": str(public["client_id"]).strip(),
                    "client_secret": secret["client_secret"],
                    "code": str(submission.get("code") or ""),
                    "redirect_uri": str(submission.get("redirect_uri") or ""),
                    "code_verifier": str(submission.get("code_verifier") or ""),
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise ProgramError(
            "external_error",
            "WeKnora rejected the connection request",
        ) from exc
    except (httpx.RequestError, ValueError, KeyError) as exc:
        raise ProgramError(
            "unavailable",
            "WeKnora connection service is unavailable",
            retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise ProgramError("external_error", "WeKnora returned an invalid response")
    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    connection_id = payload.get("connection_id")
    username = payload.get("username")
    launch_path = payload.get("launch_path")
    raw_scopes = payload.get("scopes")
    if not isinstance(raw_scopes, list) or not all(
        isinstance(scope, str) for scope in raw_scopes
    ):
        raise ProgramError("external_error", "WeKnora returned invalid scopes")
    scopes = sorted({scope.strip() for scope in raw_scopes if scope.strip()})
    if (
        not isinstance(access_token, str)
        or not access_token.startswith("wkic_")
        or token_type != "API-Key"
        or not isinstance(connection_id, str)
        or not connection_id.strip()
        or _READ_SCOPE not in scopes
    ):
        raise ProgramError(
            "external_error",
            "WeKnora returned an invalid connection credential",
        )
    if not isinstance(username, str) or not username.strip():
        raise ProgramError("external_error", "WeKnora returned an invalid username")
    normalized_launch_path = str(launch_path or "").strip()
    _build_launch_url(base_url, normalized_launch_path)
    return {
        "external_account_id": connection_id.strip(),
        "external_account_name": username,
        "granted_scopes": scopes,
        "credential": {"values": {"api_key": access_token}},
        "public_metadata": {"launch_path": normalized_launch_path},
        "invalidates_existing_credential": True,
    }


_ID_SCHEMA = {
    "type": "string",
    "description": "An explicit WeKnoraX ID returned by a previous tool call.",
    "pattern": _ID_PATTERN.pattern,
}
_TITLE_SCHEMA = {
    "type": "string",
    "description": "The document title.",
    "minLength": 1,
}
_CONTENT_SCHEMA = {
    "type": "string",
    "description": "The complete Markdown content of the document.",
    "minLength": 1,
    "maxLength": _MANUAL_CONTENT_MAX_LENGTH,
}
_STATUS_SCHEMA = {
    "type": "string",
    "description": "publish submits indexing; draft saves without indexing.",
    "enum": list(_MANUAL_STATUSES),
    "default": "publish",
}


def _object_schema(
    properties: dict[str, Any], *, optional: tuple[str, ...] = ()
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": [key for key in properties if key not in optional],
        "additionalProperties": False,
    }


def _tools_discover(context: dict[str, Any]) -> dict[str, Any]:
    public, _ = _configuration(context)
    _require_base_url(public)
    return {
        "tools": [
            {
                "key": "search",
                "upstream_name": "knowledge_search",
                "description": (
                    "Search the connected WeKnora knowledge base for internal "
                    "policies, procedures, product knowledge, and documents."
                ),
                "input_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "A focused natural-language search query.",
                            "minLength": 1,
                            "maxLength": 4000,
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {"items": {"type": "array"}},
                    "required": ["items"],
                    "additionalProperties": False,
                },
                "effect": "read",
                "retry_policy": "safe",
                "source_revision": "weknora-search-v1",
            },
            {
                "key": "list_knowledge_bases",
                "upstream_name": "list_knowledge_bases",
                "description": (
                    "List knowledge bases currently available to this connection. "
                    "Results include id, name, description, tenant_id, tenant_name, "
                    "type and can_write. Use can_write to find writable document "
                    "knowledge bases. Match the user's requested workspace and "
                    "knowledge base. If the destination is unspecified or names are "
                    "ambiguous, ask the user to choose before writing. Reuse a "
                    "confirmed destination only within the current task."
                ),
                "input_schema": _object_schema({}),
                "output_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {"items": {"type": "array"}},
                    "required": ["items"],
                    "additionalProperties": False,
                },
                "effect": "read",
                "retry_policy": "safe",
                "source_revision": _WEKNORAX_SOURCE_REVISION,
            },
            {
                "key": "get_knowledge",
                "upstream_name": "get_knowledge",
                "description": (
                    "Get a document by its explicit ID, including title, "
                    "knowledge_base_id, parse_status, error_message and metadata. "
                    "For manual text documents, metadata.content holds the full "
                    "Markdown content. pending, processing or finalizing means "
                    "indexing has not finished; completed means it has finished; "
                    "failed includes error_message."
                ),
                "input_schema": _object_schema(
                    {"knowledge_id": _ID_SCHEMA},
                ),
                "output_schema": None,
                "effect": "read",
                "retry_policy": "safe",
                "source_revision": _WEKNORAX_SOURCE_REVISION,
            },
            {
                "key": "create_knowledge_from_text",
                "upstream_name": "create_knowledge_from_text",
                "description": (
                    "Create a knowledge entry from raw Markdown text. kb_id is the "
                    "explicit ID from list_knowledge_bases, never a name or default. "
                    "Choose a document knowledge base with can_write. The user must "
                    "have specified or confirmed the destination in this task; ask "
                    "when the destination is unspecified or names are ambiguous. "
                    "status defaults to publish, which submits asynchronous "
                    "indexing. The response contains the document ID and "
                    "parse_status. Use get_knowledge until parse_status is "
                    "completed; pending, processing or finalizing has not finished, "
                    "and failed includes error_message. Use draft to save without "
                    "indexing. Keep the "
                    "returned document ID for subsequent updates; do not create "
                    "duplicates."
                ),
                "input_schema": _object_schema(
                    {
                        "kb_id": _ID_SCHEMA,
                        "title": _TITLE_SCHEMA,
                        "content": _CONTENT_SCHEMA,
                        "status": _STATUS_SCHEMA,
                    },
                    optional=("status",),
                ),
                "output_schema": None,
                "effect": "write",
                "retry_policy": "never",
                "confirmation": "not_required",
                "source_revision": _WEKNORAX_SOURCE_REVISION,
            },
            {
                "key": "update_knowledge_from_text",
                "upstream_name": "update_knowledge_from_text",
                "description": (
                    "Replace the full Markdown content of an existing manual "
                    "document. knowledge_id is the explicit document ID returned by "
                    "creation or get_knowledge. Read the existing document first "
                    "when editing it. Preserve content the user did not ask to "
                    "change and submit the complete revised text. Its knowledge "
                    "base stays the same; do not identify documents by title or "
                    "create a new one instead. Wait for pending, processing or "
                    "finalizing indexing to finish before updating. The document's "
                    "knowledge base must still have can_write. status defaults to "
                    "publish, which submits asynchronous reindexing. Check "
                    "parse_status using get_knowledge before reporting completion. "
                    "If permission is denied, report it; never switch to another "
                    "knowledge base automatically."
                ),
                "input_schema": _object_schema(
                    {
                        "knowledge_id": _ID_SCHEMA,
                        "title": _TITLE_SCHEMA,
                        "content": _CONTENT_SCHEMA,
                        "status": _STATUS_SCHEMA,
                    },
                    optional=("status",),
                ),
                "output_schema": None,
                "effect": "destructive",
                "retry_policy": "never",
                "confirmation": "user_required",
                "source_revision": _WEKNORAX_SOURCE_REVISION,
            },
        ]
    }


def _normalize_search_items(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ProgramError(
            "external_error",
            "WeKnora returned an invalid knowledge search response",
        )
    items: list[dict[str, Any]] = []
    for raw_item in payload["data"]:
        if not isinstance(raw_item, dict):
            raise ProgramError(
                "external_error",
                "WeKnora returned an invalid knowledge search response",
            )
        required_strings = ("id", "content", "knowledge_id", "knowledge_title")
        optional_strings = (
            "chunk_type",
            "image_info",
            "knowledge_filename",
            "knowledge_source",
            "knowledge_base_id",
        )
        if not all(isinstance(raw_item.get(key), str) for key in required_strings):
            raise ProgramError(
                "external_error",
                "WeKnora returned an invalid knowledge search response",
            )
        if any(
            key in raw_item and not isinstance(raw_item[key], str)
            for key in optional_strings
        ) or (
            "chunk_index" in raw_item
            and (
                isinstance(raw_item["chunk_index"], bool)
                or not isinstance(raw_item["chunk_index"], int)
            )
        ):
            raise ProgramError(
                "external_error",
                "WeKnora returned an invalid knowledge search response",
            )
        if "score" in raw_item and (
            isinstance(raw_item["score"], bool)
            or not isinstance(raw_item["score"], int | float)
        ):
            raise ProgramError(
                "external_error",
                "WeKnora returned an invalid knowledge search response",
            )
        if "metadata" in raw_item and not isinstance(raw_item["metadata"], dict):
            raise ProgramError(
                "external_error",
                "WeKnora returned an invalid knowledge search response",
            )
        item = dict(raw_item)
        item.setdefault("chunk_index", 0)
        item.setdefault("score", 0)
        item.setdefault("chunk_type", "text")
        item.setdefault("image_info", "")
        item.setdefault("metadata", {})
        item.setdefault("knowledge_filename", "")
        item.setdefault("knowledge_source", "")
        item.setdefault("knowledge_base_id", "")
        items.append(item)
    return items


def _require_api_key(context: dict[str, Any]) -> str:
    credentials = context.get("credentials")
    api_key = (
        str(credentials.get("api_key") or "").strip()
        if isinstance(credentials, dict)
        else ""
    )
    if not api_key.startswith("wkic_"):
        raise ProgramError(
            "authorization_required",
            "WeKnora credential is unavailable",
        )
    return api_key


def _search(context: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    if set(arguments) - {"query"}:
        raise ProgramError("bad_request", "WeKnora search arguments are invalid")
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ProgramError(
            "bad_request",
            "WeKnora search query must contain 1 to 4000 characters",
        )
    api_key = _require_api_key(context)
    public, _ = _configuration(context)
    base_url = _require_base_url(public)
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            response = client.post(
                f"{base_url}/api/v1/knowledge-search",
                headers={"X-API-Key": api_key},
                json={"query": query.strip()},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403}:
            raise ProgramError(
                "authorization_required",
                "WeKnora rejected the stored credential",
            ) from exc
        if exc.response.status_code == 400:
            raise ProgramError(
                "bad_request",
                "WeKnora rejected the knowledge search request",
            ) from exc
        raise ProgramError(
            "unavailable",
            "WeKnora knowledge search is unavailable",
            retryable=True,
        ) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise ProgramError(
            "unavailable",
            "WeKnora knowledge search is unavailable",
            retryable=True,
        ) from exc
    return {"items": _normalize_search_items(payload)}


def _status_error(response: httpx.Response, retryable: bool) -> ProgramError:
    status_code = response.status_code
    if status_code == 401:
        return ProgramError(
            "authorization_required",
            "WeKnora rejected the stored credential",
        )
    code = _STATUS_ERROR_CODES.get(status_code)
    if code is None:
        return ProgramError(
            "unavailable",
            "WeKnora service is unavailable",
            retryable=retryable,
        )
    try:
        upstream_message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        upstream_message = ""
    message = f"WeKnora rejected the request (HTTP {status_code})"
    if isinstance(upstream_message, str) and upstream_message.strip():
        message = f"{message}: {upstream_message.strip()[:500]}"
    return ProgramError(code, message)


def _call_weknora(
    context: dict[str, Any],
    method: str,
    path: str,
    *,
    retryable: bool,
    json_body: dict[str, Any] | None = None,
) -> object:
    api_key = _require_api_key(context)
    public, _ = _configuration(context)
    base_url = _require_base_url(public)
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            response = client.request(
                method,
                f"{base_url}/api/v1{path}",
                headers={"X-API-Key": api_key},
                json=json_body,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise _status_error(exc.response, retryable) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise ProgramError(
            "unavailable",
            "WeKnora service is unavailable",
            retryable=retryable,
        ) from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise ProgramError("external_error", "WeKnora returned an invalid response")
    return payload["data"]


def _check_arguments(
    arguments: dict[str, Any],
    required: set[str],
    optional: set[str] = frozenset(),
) -> None:
    if set(arguments) - required - optional or required - set(arguments):
        raise ProgramError("bad_request", "WeKnora tool arguments are invalid")


def _id_argument(arguments: dict[str, Any], key: str) -> str:
    value = arguments[key]
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ProgramError("bad_request", f"WeKnora {key} is invalid")
    return value


def _manual_payload(arguments: dict[str, Any]) -> dict[str, str]:
    title = arguments["title"]
    content = arguments["content"]
    status = arguments.get("status", "publish")
    if not isinstance(title, str) or not title.strip():
        raise ProgramError("bad_request", "WeKnora document title is required")
    if (
        not isinstance(content, str)
        or not content.strip()
        or len(content) > _MANUAL_CONTENT_MAX_LENGTH
    ):
        raise ProgramError(
            "bad_request",
            "WeKnora document content must contain 1 to "
            f"{_MANUAL_CONTENT_MAX_LENGTH} characters",
        )
    if status not in _MANUAL_STATUSES:
        raise ProgramError("bad_request", "WeKnora document status is invalid")
    return {"title": title, "content": content, "status": status}


def _require_object(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProgramError("external_error", "WeKnora returned an invalid response")
    return data


def _list_knowledge_bases(
    context: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    _check_arguments(arguments, set())
    data = _call_weknora(context, "GET", "/knowledge-bases", retryable=True)
    if not isinstance(data, list):
        raise ProgramError("external_error", "WeKnora returned an invalid response")
    return {"items": data}


def _get_knowledge(
    context: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    _check_arguments(arguments, {"knowledge_id"})
    knowledge_id = _id_argument(arguments, "knowledge_id")
    data = _call_weknora(
        context, "GET", f"/knowledge/{knowledge_id}", retryable=True
    )
    return _require_object(data)


def _create_knowledge_from_text(
    context: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    _check_arguments(arguments, {"kb_id", "title", "content"}, {"status"})
    kb_id = _id_argument(arguments, "kb_id")
    data = _call_weknora(
        context,
        "POST",
        f"/knowledge-bases/{kb_id}/knowledge/manual",
        retryable=False,
        json_body=_manual_payload(arguments),
    )
    return _require_object(data)


def _update_knowledge_from_text(
    context: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    _check_arguments(arguments, {"knowledge_id", "title", "content"}, {"status"})
    knowledge_id = _id_argument(arguments, "knowledge_id")
    data = _call_weknora(
        context,
        "PUT",
        f"/knowledge/manual/{knowledge_id}",
        retryable=False,
        json_body=_manual_payload(arguments),
    )
    return _require_object(data)


_TOOL_HANDLERS = {
    "knowledge_search": _search,
    "list_knowledge_bases": _list_knowledge_bases,
    "get_knowledge": _get_knowledge,
    "create_knowledge_from_text": _create_knowledge_from_text,
    "update_knowledge_from_text": _update_knowledge_from_text,
}


def _tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    tool_name = context.get("tool_name")
    handler = _TOOL_HANDLERS.get(tool_name) if isinstance(tool_name, str) else None
    if handler is None:
        raise ProgramError("action_forbidden", "Unsupported WeKnora tool")
    arguments = context.get("arguments")
    if not isinstance(arguments, dict):
        raise ProgramError("bad_request", "WeKnora tool arguments are invalid")
    structured_content = handler(context, arguments)
    try:
        text_content = json.dumps(
            structured_content,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProgramError(
            "external_error",
            "WeKnora returned an invalid response",
        ) from exc
    return {
        "content": [
            {
                "type": "text",
                "text": text_content,
            }
        ],
        "structured_content": structured_content,
        "is_error": False,
    }


def _launch_url(context: dict[str, Any]) -> dict[str, Any]:
    public = context.get("public_configuration")
    metadata = context.get("connection_metadata")
    if not isinstance(public, dict) or not isinstance(metadata, dict):
        raise ProgramError("bad_request", "Connector launch context is invalid")
    launch_path = metadata.get("launch_path")
    if not isinstance(launch_path, str) or not launch_path:
        return {"url": None}
    return {"url": _build_launch_url(_require_base_url(public), launch_path)}


_OPERATIONS = {
    "configuration_validate": _validate_configuration,
    "authorization_identity": _authorization_identity,
    "authorization_begin": _authorization_begin,
    "authorization_complete": _authorization_complete,
    "tools_discover": _tools_discover,
    "tool_invoke": _tool_invoke,
    "launch_url": _launch_url,
}


def _success(result: dict[str, Any]) -> dict[str, Any]:
    return {"protocol_version": _PROTOCOL_VERSION, "ok": True, "result": result}


def _failure(error: ProgramError) -> dict[str, Any]:
    return {
        "protocol_version": _PROTOCOL_VERSION,
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
        },
    }


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("protocol_version") != 1:
            raise ProgramError("bad_request", "Connector program request is invalid")
        operation = request.get("operation")
        context = request.get("context")
        handler = _OPERATIONS.get(operation) if isinstance(operation, str) else None
        if handler is None or not isinstance(context, dict):
            raise ProgramError("bad_request", "Connector operation is unsupported")
        response = _success(handler(context))
    except ProgramError as exc:
        response = _failure(exc)
    except Exception:
        response = _failure(ProgramError("external_error", "Connector program failed"))
    json.dump(
        response,
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


if __name__ == "__main__":
    main()
