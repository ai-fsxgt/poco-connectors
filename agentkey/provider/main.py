import hashlib
import json
import sys
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

_ENDPOINT = "https://api.agentkey.app/v1/mcp"
_ISSUER = "https://api.agentkey.app"
_RESOURCE_METADATA_URL = "https://api.agentkey.app/.well-known/oauth-protected-resource"
_AUTHORIZATION_METADATA_URL = (
    "https://api.agentkey.app/.well-known/oauth-authorization-server"
)
_MCP_PROTOCOL_VERSION = "2025-06-18"
_SCOPES = "openid profile email offline_access"
_MAX_TOOL_PAGES = 20
_MAX_RESPONSE_BYTES = 950_000

_TOOL_POLICIES = {
    "find_tools": ("read", "safe"),
    "describe_tool": ("read", "safe"),
    "execute_tool": ("read", "never"),
}


class ProgramError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _configuration_endpoint(context: dict[str, Any]) -> str:
    configuration = context.get("configuration")
    if not isinstance(configuration, dict):
        return ""
    public = configuration.get("public")
    if not isinstance(public, dict):
        return ""
    value = public.get("endpoint")
    return value.strip() if isinstance(value, str) else ""


def _require_string(
    value: object,
    label: str,
    *,
    maximum: int = 4096,
    error_code: str = "bad_request",
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProgramError(error_code, f"{label}不能为空")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ProgramError(error_code, f"{label}过长")
    return normalized


def _validated_url(
    value: object,
    label: str,
    *,
    https_only: bool = True,
    error_code: str = "external_error",
) -> str:
    url = _require_string(
        value,
        label,
        maximum=2048,
        error_code=error_code,
    )
    parsed = urlsplit(url)
    allowed_schemes = {"https"} if https_only else {"http", "https"}
    if (
        parsed.scheme.lower() not in allowed_schemes
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ProgramError(error_code, f"{label}不是安全的 HTTP(S) 地址")
    return url


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _require_official_endpoint(context: dict[str, Any]) -> str:
    endpoint = _configuration_endpoint(context)
    if endpoint != _ENDPOINT:
        raise ProgramError(
            "bad_request",
            "AgentKey MCP 服务地址必须使用官方地址",
        )
    return endpoint


def _response_error(response: httpx.Response, action: str) -> ProgramError:
    if response.status_code == 401:
        return ProgramError(
            "authorization_required",
            "AgentKey 授权已失效，请重新授权",
        )
    if response.status_code == 400:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("error") in {
            "invalid_grant",
            "invalid_token",
        }:
            return ProgramError(
                "authorization_required",
                "AgentKey 授权已失效，请重新授权",
            )
    if response.status_code == 403:
        return ProgramError(
            "insufficient_scope",
            "AgentKey 当前授权范围不足，请重新授权",
        )
    if response.status_code == 429:
        return ProgramError(
            "rate_limited",
            "AgentKey 当前请求过多，请稍后重试",
        )
    if response.status_code >= 500:
        return ProgramError(
            "unavailable",
            f"AgentKey {action}服务暂时不可用",
            retryable=True,
        )
    return ProgramError(
        "external_error",
        f"AgentKey {action}请求被拒绝（HTTP {response.status_code}）",
    )


def _json_object(response: httpx.Response, action: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProgramError(
            "external_error",
            f"AgentKey {action}服务未返回有效 JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise ProgramError(
            "external_error",
            f"AgentKey {action}服务响应格式错误",
        )
    return payload


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    action: str,
    expected_statuses: Collection[int] = (200,),
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        raise ProgramError(
            "unavailable",
            f"AgentKey {action}服务连接失败",
            retryable=True,
        ) from exc
    if response.status_code not in expected_statuses:
        raise _response_error(response, action)
    return _json_object(response, action)


def _oauth_endpoints(client: httpx.Client) -> dict[str, str]:
    resource_metadata = _request_json(
        client,
        "GET",
        _RESOURCE_METADATA_URL,
        action="OAuth 资源发现",
    )
    resource = _validated_url(
        resource_metadata.get("resource"),
        "AgentKey OAuth 资源",
    )
    if resource.rstrip("/") != _ISSUER:
        raise ProgramError(
            "external_error",
            "AgentKey OAuth 资源与官方地址不匹配",
        )
    authorization_servers = resource_metadata.get("authorization_servers")
    if not isinstance(authorization_servers, list) or _ISSUER not in {
        str(item).rstrip("/") for item in authorization_servers
    }:
        raise ProgramError("external_error", "AgentKey OAuth 授权方不受信任")

    metadata = _request_json(
        client,
        "GET",
        _AUTHORIZATION_METADATA_URL,
        action="OAuth 授权发现",
    )
    issuer = _validated_url(metadata.get("issuer"), "AgentKey OAuth Issuer")
    if issuer.rstrip("/") != _ISSUER:
        raise ProgramError("external_error", "AgentKey OAuth Issuer 不匹配")

    endpoints = {
        "issuer": _ISSUER,
        "resource": resource.rstrip("/"),
        "authorization_url": _validated_url(
            metadata.get("authorization_endpoint"),
            "AgentKey OAuth 授权端点",
        ),
        "token_url": _validated_url(
            metadata.get("token_endpoint"),
            "AgentKey OAuth 令牌端点",
        ),
        "registration_url": _validated_url(
            metadata.get("registration_endpoint"),
            "AgentKey OAuth 注册端点",
        ),
    }
    if any(_origin(value) != _ISSUER for value in endpoints.values()):
        raise ProgramError(
            "external_error",
            "AgentKey OAuth 端点与 Issuer 不同源",
        )

    response_types = metadata.get("response_types_supported")
    grant_types = metadata.get("grant_types_supported")
    pkce_methods = metadata.get("code_challenge_methods_supported")
    auth_methods = metadata.get("token_endpoint_auth_methods_supported")
    scopes = metadata.get("scopes_supported")
    if not isinstance(response_types, list) or "code" not in response_types:
        raise ProgramError("external_error", "AgentKey OAuth 不支持授权码流程")
    if not isinstance(grant_types, list) or not {
        "authorization_code",
        "refresh_token",
    }.issubset(set(grant_types)):
        raise ProgramError(
            "external_error",
            "AgentKey OAuth 不支持所需授权类型",
        )
    if not isinstance(pkce_methods, list) or "S256" not in pkce_methods:
        raise ProgramError("external_error", "AgentKey OAuth 不支持 PKCE S256")
    if not isinstance(auth_methods, list) or "none" not in auth_methods:
        raise ProgramError("external_error", "AgentKey OAuth 不支持公共客户端")
    if not isinstance(scopes, list) or not set(_SCOPES.split()).issubset(set(scopes)):
        raise ProgramError("external_error", "AgentKey OAuth 缺少所需授权范围")
    return endpoints


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _configuration_endpoint(context)
    if not endpoint and not context.get("require_complete"):
        return {}
    _require_official_endpoint(context)
    return {}


def authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    _require_official_endpoint(context)
    return {
        "identity": {
            "endpoint": _ENDPOINT,
            "issuer": _ISSUER,
            "scopes": _SCOPES.split(),
        }
    }


def authorization_begin(context: dict[str, Any]) -> dict[str, Any]:
    _require_official_endpoint(context)
    redirect_uri = _validated_url(
        context.get("redirect_uri"),
        "OAuth 回调地址",
        https_only=False,
        error_code="bad_request",
    )
    state = _require_string(context.get("state"), "OAuth state")
    code_challenge = _require_string(
        context.get("code_challenge"),
        "PKCE code challenge",
    )

    with httpx.Client(timeout=8.0, follow_redirects=False) as client:
        endpoints = _oauth_endpoints(client)
        registration = _request_json(
            client,
            "POST",
            endpoints["registration_url"],
            action="OAuth 客户端注册",
            expected_statuses={200, 201},
            json={
                "redirect_uris": [redirect_uri],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": _SCOPES,
                "client_name": "POCO AgentKey Connector",
            },
        )

    client_id = _require_string(
        registration.get("client_id"),
        "AgentKey OAuth Client ID",
        maximum=2048,
        error_code="external_error",
    )
    registered_auth_method = registration.get("token_endpoint_auth_method")
    if registered_auth_method not in {None, "none"}:
        raise ProgramError(
            "external_error",
            "AgentKey 注册了不受支持的客户端类型",
        )

    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": endpoints["resource"],
            "scope": _SCOPES,
        }
    )
    authorize_url = f"{endpoints['authorization_url']}?{query}"
    return {
        "type": "redirect",
        "authorize_url": authorize_url,
        "private_context": {
            **endpoints,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": _SCOPES,
        },
    }


def _authorization_context(context: dict[str, Any]) -> dict[str, str]:
    private_context = context.get("private_context")
    required = {
        "issuer",
        "resource",
        "authorization_url",
        "token_url",
        "registration_url",
        "client_id",
        "redirect_uri",
        "scope",
    }
    if (
        not isinstance(private_context, dict)
        or set(private_context) != required
        or not all(
            isinstance(value, str) and value for value in private_context.values()
        )
    ):
        raise ProgramError("bad_request", "AgentKey OAuth 授权上下文无效")
    if (
        private_context["issuer"] != _ISSUER
        or private_context["resource"] != _ISSUER
        or private_context["authorization_url"] != f"{_ISSUER}/oauth/authorize"
        or private_context["token_url"] != f"{_ISSUER}/oauth/token"
        or private_context["registration_url"] != f"{_ISSUER}/oauth/register"
        or private_context["scope"] != _SCOPES
    ):
        raise ProgramError("bad_request", "AgentKey OAuth 授权上下文已变化")
    return private_context


def _expires_at(expires_in: object) -> str | None:
    if expires_in is None:
        return None
    if isinstance(expires_in, str) and expires_in.isdigit():
        expires_in = int(expires_in)
    if type(expires_in) is not int or expires_in <= 0:
        raise ProgramError("external_error", "AgentKey 令牌有效期无效")
    return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()


def _credential_from_token(
    payload: dict[str, Any],
    *,
    client_id: str,
    current_refresh_token: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    access_token = _require_string(
        payload.get("access_token"),
        "AgentKey access token",
        maximum=16_384,
        error_code="external_error",
    )
    if str(payload.get("token_type", "")).lower() != "bearer":
        raise ProgramError(
            "external_error",
            "AgentKey 返回了不受支持的令牌类型",
        )
    refresh_value = payload.get("refresh_token") or current_refresh_token
    refresh_token = _require_string(
        refresh_value,
        "AgentKey refresh token",
        maximum=16_384,
        error_code="external_error",
    )
    scope_value = payload.get("scope", _SCOPES)
    if not isinstance(scope_value, str):
        raise ProgramError("external_error", "AgentKey 返回了无效的授权范围")
    scopes = sorted(set(scope_value.split()))
    if not set(_SCOPES.split()).issubset(scopes):
        raise ProgramError("insufficient_scope", "AgentKey 授权范围不足")

    credential: dict[str, Any] = {
        "values": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "client_id": client_id,
            "issuer": _ISSUER,
            "resource": _ISSUER,
            "token_url": f"{_ISSUER}/oauth/token",
            "scope": _SCOPES,
        }
    }
    expires_at = _expires_at(payload.get("expires_in"))
    if expires_at is not None:
        credential["expires_at"] = expires_at
    return credential, scopes


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    _require_official_endpoint(context)
    oauth_context = _authorization_context(context)
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "oauth_code":
        raise ProgramError("bad_request", "AgentKey 连接器需要 OAuth 授权码")
    redirect_uri = _validated_url(
        submission.get("redirect_uri"),
        "OAuth 回调地址",
        https_only=False,
        error_code="bad_request",
    )
    if redirect_uri != oauth_context["redirect_uri"]:
        raise ProgramError("bad_request", "OAuth 回调地址与授权请求不一致")
    code = _require_string(submission.get("code"), "OAuth 授权码")
    code_verifier = _require_string(
        submission.get("code_verifier"),
        "PKCE code verifier",
    )

    with httpx.Client(timeout=12.0, follow_redirects=False) as client:
        tokens = _request_json(
            client,
            "POST",
            oauth_context["token_url"],
            action="OAuth 令牌",
            data={
                "grant_type": "authorization_code",
                "client_id": oauth_context["client_id"],
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "resource": oauth_context["resource"],
            },
        )
    credential, scopes = _credential_from_token(
        tokens,
        client_id=oauth_context["client_id"],
    )
    return {
        "external_account_name": "AgentKey",
        "granted_scopes": scopes,
        "credential": credential,
        "public_metadata": {
            "issuer": _ISSUER,
            "resource": _ISSUER,
        },
    }


def credential_refresh(context: dict[str, Any]) -> dict[str, Any]:
    _require_official_endpoint(context)
    credential = context.get("credential")
    values = credential.get("values") if isinstance(credential, dict) else None
    if not isinstance(values, dict):
        raise ProgramError("authorization_required", "AgentKey 凭据无效")
    client_id = _require_string(
        values.get("client_id"),
        "AgentKey Client ID",
        error_code="authorization_required",
    )
    refresh_token = _require_string(
        values.get("refresh_token"),
        "AgentKey refresh token",
        maximum=16_384,
        error_code="authorization_required",
    )
    if (
        values.get("issuer") != _ISSUER
        or values.get("resource") != _ISSUER
        or values.get("token_url") != f"{_ISSUER}/oauth/token"
        or values.get("scope") != _SCOPES
    ):
        raise ProgramError("authorization_required", "AgentKey 授权身份已变化")

    with httpx.Client(timeout=12.0, follow_redirects=False) as client:
        tokens = _request_json(
            client,
            "POST",
            f"{_ISSUER}/oauth/token",
            action="OAuth 令牌刷新",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "resource": _ISSUER,
            },
        )
    refreshed, scopes = _credential_from_token(
        tokens,
        client_id=client_id,
        current_refresh_token=refresh_token,
    )
    return {"credential": refreshed, "granted_scopes": scopes}


def _mcp_payload(response: httpx.Response) -> dict[str, Any]:
    body = response.text
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        return payload

    events: list[dict[str, Any]] = []
    for event in body.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")
        ]
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        if data == "[DONE]":
            continue
        try:
            candidate = json.loads(data)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            events.append(candidate)
    if not events:
        raise ProgramError("external_error", "AgentKey MCP 响应格式错误")
    return events[-1]


class _McpClient:
    def __init__(self, endpoint: str, access_token: str) -> None:
        self._endpoint = endpoint
        self._client = httpx.Client(
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": _MCP_PROTOCOL_VERSION,
            },
        )
        self._session_id: str | None = None
        self._request_id = 0

    def __enter__(self) -> "_McpClient":
        self._initialize()
        return self

    def __exit__(self, *args: object) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        return (
            {"Mcp-Session-Id": self._session_id} if self._session_id is not None else {}
        )

    def _post(
        self,
        payload: dict[str, Any],
        *,
        timeout: float,
        expect_response: bool = True,
    ) -> dict[str, Any] | None:
        try:
            response = self._client.post(
                self._endpoint,
                headers=self._headers(),
                json=payload,
                timeout=httpx.Timeout(timeout, connect=3.0),
            )
        except httpx.RequestError as exc:
            raise ProgramError(
                "unavailable",
                "AgentKey MCP 服务连接失败",
                retryable=True,
            ) from exc
        if response.status_code not in {200, 202, 204}:
            raise _response_error(response, "MCP")
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if not expect_response:
            return None
        if response.status_code in {202, 204} or not response.content:
            raise ProgramError("external_error", "AgentKey MCP 未返回调用结果")
        message = _mcp_payload(response)
        if message.get("jsonrpc") != "2.0" or message.get("id") != payload.get("id"):
            raise ProgramError("external_error", "AgentKey MCP 响应标识无效")
        error = message.get("error")
        if isinstance(error, dict):
            raise ProgramError("external_error", "AgentKey MCP 返回调用错误")
        result = message.get("result")
        if not isinstance(result, dict):
            raise ProgramError(
                "external_error",
                "AgentKey MCP 调用结果格式错误",
            )
        return result

    def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        self._request_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        result = self._post(payload, timeout=timeout)
        assert result is not None
        return result

    def _initialize(self) -> None:
        result = self._request(
            "initialize",
            {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "POCO", "version": "1"},
            },
            timeout=4.0,
        )
        protocol_version = result.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            raise ProgramError("external_error", "AgentKey MCP 初始化响应无效")
        self._client.headers["MCP-Protocol-Version"] = protocol_version
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=2.0,
            expect_response=False,
        )

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(_MAX_TOOL_PAGES):
            params = {"cursor": cursor} if cursor is not None else None
            result = self._request("tools/list", params, timeout=4.0)
            page = result.get("tools")
            if not isinstance(page, list) or not all(
                isinstance(tool, dict) for tool in page
            ):
                raise ProgramError(
                    "external_error",
                    "AgentKey 工具目录格式错误",
                )
            tools.extend(page)
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tools
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor in seen_cursors
            ):
                raise ProgramError(
                    "external_error",
                    "AgentKey 工具目录游标无效",
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise ProgramError("external_error", "AgentKey 工具目录分页过多")

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=18.0,
        )


def _access_token(context: dict[str, Any]) -> str:
    credentials = context.get("credentials")
    if not isinstance(credentials, dict):
        raise ProgramError("authorization_required", "AgentKey 凭据不存在")
    try:
        return _require_string(
            credentials.get("access_token"),
            "AgentKey access token",
            maximum=16_384,
        )
    except ProgramError as exc:
        raise ProgramError(
            "authorization_required",
            "AgentKey 凭据不存在或已失效",
        ) from exc


def _remote_tool_map(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or name not in _TOOL_POLICIES:
            continue
        if name in mapped:
            raise ProgramError("external_error", f"AgentKey 工具重复：{name}")
        mapped[name] = tool
    missing = sorted(set(_TOOL_POLICIES) - set(mapped))
    if missing:
        raise ProgramError(
            "unavailable",
            f"AgentKey 缺少必要工具：{', '.join(missing)}",
            retryable=True,
        )
    return mapped


def _tool_spec(name: str, tool: dict[str, Any]) -> dict[str, Any]:
    description = tool.get("description") or tool.get("title") or name
    input_schema = tool.get("inputSchema")
    output_schema = tool.get("outputSchema")
    if not isinstance(description, str) or not description or len(description) > 10_000:
        raise ProgramError("external_error", f"AgentKey 工具描述无效：{name}")
    if not isinstance(input_schema, dict):
        raise ProgramError(
            "external_error",
            f"AgentKey 工具参数定义无效：{name}",
        )
    if output_schema is not None and not isinstance(output_schema, dict):
        raise ProgramError(
            "external_error",
            f"AgentKey 工具输出定义无效：{name}",
        )
    source = json.dumps(
        tool,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()
    effect, retry_policy = _TOOL_POLICIES[name]
    spec = {
        "key": name,
        "upstream_name": name,
        "description": description,
        "input_schema": input_schema,
        "effect": effect,
        "retry_policy": retry_policy,
        "confirmation": "not_required",
        "source_revision": hashlib.sha256(source).hexdigest(),
    }
    if output_schema is not None:
        spec["output_schema"] = output_schema
    return spec


def tools_discover(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _require_official_endpoint(context)
    access_token = _access_token(context)
    with _McpClient(endpoint, access_token) as client:
        remote_tools = _remote_tool_map(client.list_tools())
    return {"tools": [_tool_spec(name, remote_tools[name]) for name in _TOOL_POLICIES]}


def _content_blocks(result: dict[str, Any]) -> list[dict[str, Any]]:
    content = result.get("content", [])
    if not isinstance(content, list):
        raise ProgramError("external_error", "AgentKey 工具内容格式错误")
    converted: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            raise ProgramError("external_error", "AgentKey 工具内容项格式错误")
        item_type = item.get("type")
        if item_type == "text" and isinstance(item.get("text"), str):
            converted.append({"type": "text", "text": item["text"]})
        elif item_type in {"image", "audio"}:
            data = item.get("data")
            mime_type = item.get("mimeType")
            if not isinstance(data, str) or not isinstance(mime_type, str):
                raise ProgramError(
                    "external_error",
                    "AgentKey 媒体内容格式错误",
                )
            converted.append({"type": item_type, "data": data, "mime_type": mime_type})
        elif item_type == "resource_link":
            uri, name = item.get("uri"), item.get("name")
            if not isinstance(uri, str) or not isinstance(name, str):
                raise ProgramError(
                    "external_error",
                    "AgentKey 资源链接格式错误",
                )
            block = {"type": "resource_link", "uri": uri, "name": name}
            if isinstance(item.get("description"), str):
                block["description"] = item["description"]
            if isinstance(item.get("mimeType"), str):
                block["mime_type"] = item["mimeType"]
            converted.append(block)
        elif item_type == "resource" and isinstance(item.get("resource"), dict):
            resource = item["resource"]
            uri = resource.get("uri")
            if not isinstance(uri, str):
                raise ProgramError(
                    "external_error",
                    "AgentKey 资源内容格式错误",
                )
            block = {"type": "resource", "uri": uri}
            if isinstance(resource.get("mimeType"), str):
                block["mime_type"] = resource["mimeType"]
            if isinstance(resource.get("text"), str):
                block["text"] = resource["text"]
            elif isinstance(resource.get("blob"), str):
                block["data"] = resource["blob"]
            else:
                raise ProgramError(
                    "external_error",
                    "AgentKey 资源缺少有效内容",
                )
            converted.append(block)
        else:
            raise ProgramError(
                "external_error",
                "AgentKey 返回了不支持的内容类型",
            )
    return converted


def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _require_official_endpoint(context)
    access_token = _access_token(context)
    tool_name = context.get("tool_name")
    arguments = context.get("arguments")
    if not isinstance(tool_name, str) or tool_name not in _TOOL_POLICIES:
        raise ProgramError("action_forbidden", "AgentKey 工具未获清单授权")
    if not isinstance(arguments, dict):
        raise ProgramError("bad_request", "AgentKey 工具参数必须是对象")

    with _McpClient(endpoint, access_token) as client:
        remote_tools = _remote_tool_map(client.list_tools())
        _tool_spec(tool_name, remote_tools[tool_name])
        result = client.call_tool(tool_name, arguments)

    blocks = _content_blocks(result)
    is_error = result.get("isError", False)
    if not isinstance(is_error, bool):
        raise ProgramError("external_error", "AgentKey 工具错误状态无效")
    structured = result.get("structuredContent")
    if structured is not None and not isinstance(structured, dict):
        raise ProgramError("external_error", "AgentKey 结构化结果格式错误")
    output: dict[str, Any] = {
        "content": blocks,
        "structured_content": structured,
        "is_error": is_error,
        "error": None,
    }
    if is_error:
        message = next(
            (
                block["text"]
                for block in blocks
                if block["type"] == "text" and block.get("text")
            ),
            "AgentKey 工具调用失败",
        )
        output["error"] = {
            "code": "provider_tool_error",
            "message": message[:2000],
            "retryable": False,
        }
    return output


_OPERATIONS = {
    "configuration_validate": configuration_validate,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "authorization_complete": authorization_complete,
    "credential_refresh": credential_refresh,
    "tools_discover": tools_discover,
    "tool_invoke": tool_invoke,
}


def _encode_response(response: dict[str, Any]) -> str:
    return json.dumps(
        response,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("protocol_version") != 1:
            raise ProgramError("bad_request", "连接器协议版本错误")
        operation = request.get("operation")
        context = request.get("context")
        handler = _OPERATIONS.get(operation)
        if handler is None or not isinstance(context, dict):
            raise ProgramError("bad_request", "不支持的连接器操作")
        result = handler(context)
        response = {"protocol_version": 1, "ok": True, "result": result}
    except ProgramError as exc:
        response = {
            "protocol_version": 1,
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
            },
        }
    except Exception:
        response = {
            "protocol_version": 1,
            "ok": False,
            "error": {
                "code": "external_error",
                "message": "AgentKey 连接器运行失败",
                "retryable": False,
            },
        }

    encoded = _encode_response(response)
    if len(encoded.encode()) > _MAX_RESPONSE_BYTES:
        encoded = _encode_response(
            {
                "protocol_version": 1,
                "ok": False,
                "error": {
                    "code": "response_too_large",
                    "message": (
                        "AgentKey 返回内容超过 POCO 单次响应限制；请缩小查询范围。"
                        "本次调用可能已经消耗积分，请勿自动重复执行。"
                    ),
                    "retryable": False,
                },
            }
        )
    sys.stdout.write(encoded)


if __name__ == "__main__":
    main()
