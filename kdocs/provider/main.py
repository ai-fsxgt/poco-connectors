import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_ENDPOINT = "https://mcp-center.wps.cn/skill_hub/mcp"
_SKILL_VERSION = "1.4.12"
_REQUEST_SOURCE = "poco"
_PROTOCOL_VERSION = "2025-06-18"
_MAX_TOOL_PAGES = 20

_TOOL_POLICIES = {
    "search_tools": ("read", "safe", "not_required"),
    "execute_read_tool": ("read", "safe", "not_required"),
    "execute_write_tool": ("write", "never", "not_required"),
    "execute_confirmed_write_tool": ("write", "never", "user_required"),
    "execute_destructive_tool": ("destructive", "never", "user_required"),
    "execute_unknown_tool": ("unknown", "never", "user_required"),
}
_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "工具全名、名称片段或描述关键词；空串列出全部"},
        "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    "required": ["query"],
    "additionalProperties": False,
}
_CALL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "search_tools 返回的官方工具名"},
        "arguments": {"type": "object", "description": "严格使用目录中 input_schema 的参数"},
    },
    "required": ["name", "arguments"],
    "additionalProperties": False,
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:2000]
        self.retryable = retryable


def _token_from_values(values: object) -> str:
    if not isinstance(values, dict):
        raise ProgramError("bad_request", "金山文档授权信息无效")
    token = values.get("token")
    if not isinstance(token, str) or not token.strip() or len(token.strip()) > 16384:
        raise ProgramError("bad_request", "WPS Token 不能为空且长度不能超过 16384 个字符")
    return token.strip()


def _token_from_context(context: dict[str, Any]) -> str:
    credentials = context.get("credentials")
    if not isinstance(credentials, dict):
        raise ProgramError("authorization_required", "金山文档凭据不存在")
    token = credentials.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise ProgramError("authorization_required", "金山文档凭据不存在或已失效")
    return token.strip()


def _http_error(response: httpx.Response, action: str) -> ProgramError:
    if response.status_code in {401, 403}:
        return ProgramError("authorization_required", "金山文档授权已失效，请重新授权")
    if response.status_code == 429:
        return ProgramError("rate_limited", "金山文档请求过于频繁，请稍后重试")
    if response.status_code >= 500:
        return ProgramError("unavailable", f"金山文档 {action} 服务暂时不可用", retryable=True)
    return ProgramError(
        "external_error", f"金山文档 {action} 请求失败（HTTP {response.status_code}）"
    )


def _parse_message(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        return payload
    events: list[dict[str, Any]] = []
    for event in response.text.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(
            line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")
        )
        if not data or data == "[DONE]":
            continue
        try:
            candidate = json.loads(data)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            events.append(candidate)
    if not events:
        raise ProgramError("external_error", "金山文档 MCP 响应格式错误")
    return events[-1]


class _McpClient:
    def __init__(self, token: str) -> None:
        self._client = httpx.Client(
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Skill-Version": _SKILL_VERSION,
                "X-Request-Source": _REQUEST_SOURCE,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": _PROTOCOL_VERSION,
            },
        )
        self._deadline = time.monotonic() + 25.0
        self._session_id: str | None = None
        self._request_id = 0

    def __enter__(self) -> "_McpClient":
        try:
            self._initialize()
        except Exception:
            self._client.close()
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        self._client.close()

    def _post(
        self, payload: dict[str, Any], *, timeout: float, expect_response: bool = True
    ) -> dict[str, Any] | None:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise ProgramError("unavailable", "金山文档请求超时，请先核实操作状态")
        timeout = min(timeout, remaining)
        headers = {"Mcp-Session-Id": self._session_id} if self._session_id else {}
        try:
            response = self._client.post(
                _ENDPOINT,
                headers=headers,
                json=payload,
                timeout=httpx.Timeout(timeout, connect=min(4.0, timeout)),
            )
        except httpx.RequestError as exc:
            raise ProgramError(
                "unavailable", "金山文档 MCP 服务连接失败", retryable=True
            ) from exc
        if response.status_code not in {200, 202, 204}:
            raise _http_error(response, "MCP")
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if not expect_response:
            return None
        if response.status_code in {202, 204} or not response.content:
            raise ProgramError("external_error", "金山文档 MCP 未返回调用结果")
        message = _parse_message(response)
        if message.get("jsonrpc") != "2.0" or message.get("id") != payload.get("id"):
            raise ProgramError("external_error", "金山文档 MCP 响应标识无效")
        error = message.get("error")
        if isinstance(error, dict):
            error_message = error.get("message")
            raise ProgramError(
                "external_error",
                str(error_message)[:2000] if error_message else "金山文档 MCP 调用失败",
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise ProgramError("external_error", "金山文档 MCP 调用结果格式错误")
        return result

    def _request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float
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
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "POCO", "version": "1"},
            },
            timeout=8.0,
        )
        protocol_version = result.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            raise ProgramError("external_error", "金山文档 MCP 初始化响应无效")
        self._client.headers["MCP-Protocol-Version"] = protocol_version
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=3.0,
            expect_response=False,
        )

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_TOOL_PAGES):
            result = self._request(
                "tools/list", {"cursor": cursor} if cursor else None, timeout=8.0
            )
            page = result.get("tools")
            if not isinstance(page, list) or not all(
                isinstance(tool, dict) for tool in page
            ):
                raise ProgramError("external_error", "金山文档工具目录格式错误")
            tools.extend(page)
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tools
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor in seen
            ):
                raise ProgramError("external_error", "金山文档工具目录游标无效")
            seen.add(next_cursor)
            cursor = next_cursor
        raise ProgramError("external_error", "金山文档工具目录分页过多")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "tools/call", {"name": name, "arguments": arguments}, timeout=25.0
        )


def _digest(value: Any) -> str:
    source = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(source).hexdigest()


def _catalog() -> dict[str, Any]:
    return json.loads(
        Path(__file__).with_name("catalog.json").read_text(encoding="utf-8")
    )


def _validate_arguments(
    value: Any, schema: dict[str, Any], path: str = "arguments"
) -> None:
    expected = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }
    if expected is not None and not valid.get(expected, False):
        raise ProgramError("bad_request", f"{path} 必须是 {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ProgramError("bad_request", f"{path} 不在目录允许的取值中")
    if expected in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise ProgramError("bad_request", f"{path} 小于允许的最小值")
        if "maximum" in schema and value > schema["maximum"]:
            raise ProgramError("bad_request", f"{path} 超过允许的最大值")
    if expected == "object":
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise ProgramError(
                "bad_request", f"{path} 缺少参数：{', '.join(sorted(missing))}"
            )
        # 官方留空的嵌套对象承载业务数据；有明确字段的对象禁止额外参数。
        if properties or schema.get("additionalProperties") is False:
            extra = value.keys() - properties.keys()
            if extra:
                raise ProgramError(
                    "bad_request", f"{path} 包含未登记参数：{', '.join(sorted(extra))}"
                )
        for key, child in properties.items():
            if key in value:
                _validate_arguments(value[key], child, f"{path}.{key}")
    elif expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _validate_arguments(item, schema["items"], f"{path}[{index}]")


def _check_result(
    result: dict[str, Any], *, require_business_code: bool = False
) -> None:
    if result.get("isError"):
        message = next(
            (
                item["text"]
                for item in result.get("content", [])
                if isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ),
            "金山文档工具返回错误",
        )
        raise ProgramError("external_error", message[:2000])
    payloads = []
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        payloads.append(structured)
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                payload = json.loads(item["text"])
            except (ValueError, KeyError):
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
    found_code = False
    for payload in payloads:
        if "code" not in payload:
            continue
        found_code = True
        code = payload["code"]
        if code == 0:
            continue
        if code == 400006:
            raise ProgramError("authorization_required", "WPS Token 无效，请重新授权")
        if code in {429001, 429002}:
            raise ProgramError("rate_limited", f"金山文档已限频或熔断（{code}），请停止请求")
        message = payload.get("message") or payload.get("msg") or "金山文档业务请求失败"
        raise ProgramError("external_error", f"{str(message)[:2000]}（错误码 {code}）")
    if require_business_code and not found_code:
        raise ProgramError("external_error", "金山文档授权验证缺少业务状态码")


def _content_blocks(result: dict[str, Any]) -> list[dict[str, Any]]:
    content = result.get("content", [])
    if not isinstance(content, list):
        raise ProgramError("external_error", "金山文档工具内容格式错误")
    converted: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            raise ProgramError("external_error", "金山文档工具内容项格式错误")
        item_type = item.get("type")
        if item_type == "text" and isinstance(item.get("text"), str):
            converted.append({"type": "text", "text": item["text"]})
        elif (
            item_type in {"image", "audio"}
            and isinstance(item.get("data"), str)
            and isinstance(item.get("mimeType"), str)
        ):
            converted.append(
                {"type": item_type, "data": item["data"], "mime_type": item["mimeType"]}
            )
        elif (
            item_type == "resource_link"
            and isinstance(item.get("uri"), str)
            and isinstance(item.get("name"), str)
        ):
            block: dict[str, Any] = {
                "type": "resource_link",
                "uri": item["uri"],
                "name": item["name"],
            }
            if isinstance(item.get("description"), str):
                block["description"] = item["description"]
            if isinstance(item.get("mimeType"), str):
                block["mime_type"] = item["mimeType"]
            converted.append(block)
        elif item_type == "resource" and isinstance(item.get("resource"), dict):
            resource = item["resource"]
            if not isinstance(resource.get("uri"), str):
                raise ProgramError("external_error", "金山文档资源缺少 URI")
            block = {"type": "resource", "uri": resource["uri"]}
            if isinstance(resource.get("mimeType"), str):
                block["mime_type"] = resource["mimeType"]
            if isinstance(resource.get("text"), str):
                block["text"] = resource["text"]
            elif isinstance(resource.get("blob"), str):
                block["data"] = resource["blob"]
            else:
                raise ProgramError("external_error", "金山文档资源缺少有效内容")
            converted.append(block)
        else:
            raise ProgramError("external_error", "金山文档返回了不支持的内容类型")
    return converted


def configuration_validate(_context: dict[str, Any]) -> dict[str, Any]:
    return {}


def authorization_identity(_context: dict[str, Any]) -> dict[str, Any]:
    return {"identity": {"endpoint": _ENDPOINT, "skill_version": _SKILL_VERSION}}


def authorization_begin(_context: dict[str, Any]) -> dict[str, Any]:
    return {"type": "form"}


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "credentials":
        raise ProgramError("bad_request", "金山文档需要提交 Token")
    token = _token_from_values(submission.get("values"))
    with _McpClient(token) as client:
        result = client.call_tool("list_latest_items", {"page_size": 1})
    _check_result(result, require_business_code=True)
    return {
        "external_account_name": "金山文档用户",
        "credential": {"values": {"access_token": token}},
        "public_metadata": {"endpoint": _ENDPOINT, "skill_version": _SKILL_VERSION},
    }


def tools_discover(context: dict[str, Any]) -> dict[str, Any]:
    _token_from_context(context)
    revision = _digest(_catalog())
    descriptions = {
        "search_tools": "搜索包内固定的金山文档官方目录，返回完整参数、风险和调用入口；支持分页。",
        "execute_read_tool": "调用目录中标记为只读的官方工具。先使用 search_tools 获取参数。",
        "execute_write_tool": "调用目录中的普通写入工具，禁止自动重试。",
        "execute_confirmed_write_tool": "经用户确认后调用分享、权限、评论或覆盖等敏感写入工具，禁止重试。",
        "execute_destructive_tool": "经用户确认后调用删除或包含删除能力的工具，禁止重试。",
        "execute_unknown_tool": "经用户确认后调用目录中风险无法确定的工具，禁止重试。",
    }
    return {
        "tools": [
            {
                "key": name,
                "upstream_name": name,
                "description": descriptions[name],
                "input_schema": _SEARCH_SCHEMA
                if name == "search_tools"
                else _CALL_SCHEMA,
                "effect": effect,
                "retry_policy": retry,
                "confirmation": confirmation,
                "source_revision": revision,
            }
            for name, (effect, retry, confirmation) in _TOOL_POLICIES.items()
        ]
    }


def _search_tools(arguments: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    query = arguments["query"].strip().casefold()
    terms = query.split()
    matches = [
        tool
        for tool in catalog["tools"]
        if all(
            term in (tool["name"] + " " + tool["description"]).casefold()
            for term in terms
        )
    ]
    matches.sort(
        key=lambda tool: (
            tool["name"].casefold() != query,
            not tool["name"].casefold().startswith(query),
            tool["name"],
        )
    )
    offset = arguments.get("offset", 0)
    limit = arguments.get("limit", 10)
    page = matches[offset : offset + limit]
    return {
        "catalog_revision": catalog["source"]["sha256"],
        "total": len(matches),
        "tools": page,
        "next_offset": offset + len(page)
        if offset + len(page) < len(matches)
        else None,
    }


def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    name = context.get("tool_name")
    if not isinstance(name, str) or name not in _TOOL_POLICIES:
        raise ProgramError("action_forbidden", "金山文档调用入口未获清单授权")
    arguments = context.get("arguments")
    _validate_arguments(
        arguments, _SEARCH_SCHEMA if name == "search_tools" else _CALL_SCHEMA
    )
    token = _token_from_context(context)
    catalog = _catalog()
    if name == "search_tools":
        payload = _search_tools(arguments, catalog)
        return {
            "content": [
                {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
            ],
            "structured_content": payload,
            "is_error": False,
        }
    tool = next(
        (tool for tool in catalog["tools"] if tool["name"] == arguments["name"]), None
    )
    if tool is None:
        raise ProgramError("action_forbidden", "金山文档工具未登记在当前包内目录")
    policy = (tool["effect"], tool["retry"], tool["confirmation"])
    if tool["dispatcher"] != name or _TOOL_POLICIES[name] != policy:
        raise ProgramError("action_forbidden", "调用入口与工具风险或确认要求不匹配")
    _validate_arguments(arguments["arguments"], tool["input_schema"])
    # 用户确认由 POCO 在启动 Provider 前消费；调用方不能自报风险或确认状态。
    with _McpClient(token) as client:
        remote = next(
            (item for item in client.list_tools() if item.get("name") == tool["name"]),
            None,
        )
        if remote is None or _digest(remote) != tool["source_revision"]:
            raise ProgramError("action_forbidden", "官方工具定义已变化，请更新连接器包后再调用")
        result = client.call_tool(tool["name"], arguments["arguments"])
    _check_result(result)
    structured = result.get("structuredContent")
    if structured is not None and not isinstance(structured, dict):
        raise ProgramError("external_error", "金山文档结构化结果格式错误")
    return {
        "content": _content_blocks(result),
        "structured_content": structured,
        "is_error": False,
    }


_OPERATIONS = {
    "configuration_validate": configuration_validate,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "authorization_complete": authorization_complete,
    "tools_discover": tools_discover,
    "tool_invoke": tool_invoke,
}


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("protocol_version") != 1:
            raise ProgramError("bad_request", "连接器协议版本错误")
        operation = request.get("operation")
        context = request.get("context")
        handler = _OPERATIONS.get(operation) if isinstance(operation, str) else None
        if handler is None or not isinstance(context, dict):
            raise ProgramError("bad_request", "连接器操作不受支持")
        response = {"protocol_version": 1, "ok": True, "result": handler(context)}
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
                "message": "连接器程序执行失败",
                "retryable": False,
            },
        }
    json.dump(
        response, sys.stdout, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


if __name__ == "__main__":
    main()
