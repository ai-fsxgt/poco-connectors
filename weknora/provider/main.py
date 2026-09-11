import ipaddress
import json
import re
import sys
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

_PROTOCOL_VERSION = 1
_SEARCH_SCOPE = "knowledge.read"
_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)


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
        "scope": _SEARCH_SCOPE,
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
        or _SEARCH_SCOPE not in scopes
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
            }
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


def _tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    if context.get("tool_name") != "knowledge_search":
        raise ProgramError("action_forbidden", "Unsupported WeKnora tool")
    arguments = context.get("arguments")
    if not isinstance(arguments, dict) or set(arguments) - {"query"}:
        raise ProgramError("bad_request", "WeKnora search arguments are invalid")
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ProgramError(
            "bad_request",
            "WeKnora search query must contain 1 to 4000 characters",
        )
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
    structured_content = {"items": _normalize_search_items(payload)}
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
            "WeKnora returned an invalid knowledge search response",
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
