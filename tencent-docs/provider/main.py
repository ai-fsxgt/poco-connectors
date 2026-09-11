from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from typing import Any

import httpx

_ENDPOINT = "https://docs.qq.com/openapi/mcp"
_PROTOCOL_VERSION = "2025-06-18"
_MAX_TOOL_PAGES = 100

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
        "query": {
            "type": "string",
            "description": "工具名称或描述关键词；空串返回全部工具",
        },
        "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
    "required": ["query"],
    "additionalProperties": False,
}
_CALL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "search_tools 返回的官方工具名"},
        "arguments": {"type": "object", "description": "严格使用工具 Schema 的参数"},
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
        raise ProgramError("bad_request", "腾讯文档授权信息无效")
    token = values.get("token")
    if not isinstance(token, str) or not token.strip() or len(token.strip()) > 16384:
        raise ProgramError("bad_request", "腾讯文档 Token 不能为空且长度不能超过 16384 个字符")
    return token.strip()


def _token_from_context(context: dict[str, Any]) -> str:
    credentials = context.get("credentials")
    if not isinstance(credentials, dict):
        raise ProgramError("authorization_required", "腾讯文档凭据不存在")
    token = credentials.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise ProgramError("authorization_required", "腾讯文档凭据不存在或已失效")
    return token.strip()


def _http_error(response: httpx.Response, action: str) -> ProgramError:
    if response.status_code in {401, 403}:
        return ProgramError("authorization_required", "腾讯文档授权已失效，请重新授权")
    if response.status_code == 429:
        return ProgramError("rate_limited", "腾讯文档请求过于频繁，请稍后重试")
    if response.status_code >= 500:
        return ProgramError("unavailable", f"腾讯文档 {action} 服务暂时不可用", retryable=True)
    return ProgramError(
        "external_error", f"腾讯文档 {action} 请求失败（HTTP {response.status_code}）"
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
        raise ProgramError("external_error", "腾讯文档 MCP 响应格式错误")
    return events[-1]


class _McpClient:
    def __init__(self, token: str) -> None:
        self._client = httpx.Client(
            follow_redirects=False,
            headers={
                "Authorization": token,
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
            raise ProgramError("unavailable", "腾讯文档请求超时，请先核实操作状态")
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
                "unavailable", "腾讯文档 MCP 服务连接失败", retryable=True
            ) from exc
        if response.status_code not in {200, 202, 204}:
            raise _http_error(response, "MCP")
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if not expect_response:
            return None
        if response.status_code in {202, 204} or not response.content:
            raise ProgramError("external_error", "腾讯文档 MCP 未返回调用结果")
        message = _parse_message(response)
        if message.get("jsonrpc") != "2.0" or message.get("id") != payload.get("id"):
            raise ProgramError("external_error", "腾讯文档 MCP 响应标识无效")
        error = message.get("error")
        if isinstance(error, dict):
            error_message = error.get("message")
            raise ProgramError(
                "external_error",
                str(error_message)[:2000] if error_message else "腾讯文档 MCP 调用失败",
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise ProgramError("external_error", "腾讯文档 MCP 调用结果格式错误")
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
            raise ProgramError("external_error", "腾讯文档 MCP 初始化响应无效")
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
                raise ProgramError("external_error", "腾讯文档工具目录格式错误")
            tools.extend(page)
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tools
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor in seen
            ):
                raise ProgramError("external_error", "腾讯文档工具目录游标无效")
            seen.add(next_cursor)
            cursor = next_cursor
        raise ProgramError("external_error", "腾讯文档工具目录分页过多")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "tools/call", {"name": name, "arguments": arguments}, timeout=20.0
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


def _validate_arguments(
    value: Any, schema: dict[str, Any], path: str = "arguments"
) -> None:
    expected = schema.get("type")
    if expected is None and "properties" in schema:
        expected = "object"
    expected_type = expected if isinstance(expected, str) else None
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }
    if expected_type is not None and not valid.get(expected_type, True):
        raise ProgramError("bad_request", f"{path} 必须是 {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ProgramError("bad_request", f"{path} 不在工具允许的取值中")
    if expected_type in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise ProgramError("bad_request", f"{path} 小于允许的最小值")
        if "maximum" in schema and value > schema["maximum"]:
            raise ProgramError("bad_request", f"{path} 超过允许的最大值")
    if expected_type == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise ProgramError(
                "bad_request", f"{path} 缺少参数：{', '.join(sorted(missing))}"
            )
        if schema.get("additionalProperties") is False:
            extra = value.keys() - properties.keys()
            if extra:
                raise ProgramError(
                    "bad_request", f"{path} 包含未登记参数：{', '.join(sorted(extra))}"
                )
        for key, child in properties.items():
            if key in value and isinstance(child, dict):
                _validate_arguments(value[key], child, f"{path}.{key}")
    elif expected_type == "array" and "items" in schema and isinstance(value, list):
        for index, item in enumerate(value):
            _validate_arguments(item, schema["items"], f"{path}[{index}]")


def _tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    return schema


def _classify_tool(tool: dict[str, Any]) -> str:
    name = str(tool.get("name") or "").casefold()
    description = str(tool.get("description") or "").casefold()
    text = f"{name} {description}"
    if re.search(r"(^|[._-])(delete|remove|destroy|purge|trash|revoke)([._-]|$)", name):
        return "execute_destructive_tool"
    if any(word in text for word in ("删除", "delete", "remove", "destroy", "purge")):
        return "execute_destructive_tool"
    if any(
        word in text
        for word in (
            "share",
            "permission",
            "acl",
            "comment",
            "publish",
            "overwrite",
            "分享",
            "权限",
            "评论",
            "发布",
            "覆盖",
        )
    ):
        return "execute_confirmed_write_tool"
    if any(
        word in text
        for word in (
            "create",
            "update",
            "edit",
            "modify",
            "write",
            "insert",
            "append",
            "add",
            "set_",
            "rename",
            "move",
            "copy",
            "import",
            "upload",
            "创建",
            "编辑",
            "修改",
            "写入",
            "新增",
            "移动",
            "复制",
            "导入",
            "上传",
        )
    ):
        return "execute_write_tool"
    if re.search(r"(^|[._-])(get|list|search|query|read|fetch|find|check|describe|inspect|preview)([._-]|$)", name):
        return "execute_read_tool"
    if any(word in text for word in ("查询", "搜索", "读取", "获取", "查看", "列出")):
        return "execute_read_tool"
    return "execute_unknown_tool"


def _tool_summary(tool: dict[str, Any]) -> dict[str, Any]:
    name = tool.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProgramError("external_error", "腾讯文档工具缺少有效名称")
    return {
        "name": name,
        "description": str(tool.get("description") or ""),
        "input_schema": _tool_schema(tool),
        "dispatcher": _classify_tool(tool),
        "source_revision": _digest(tool),
    }


def _content_blocks(result: dict[str, Any]) -> list[dict[str, Any]]:
    content = result.get("content", [])
    if not isinstance(content, list):
        raise ProgramError("external_error", "腾讯文档工具内容格式错误")
    converted: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            raise ProgramError("external_error", "腾讯文档工具内容项格式错误")
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
        elif item_type == "resource_link" and isinstance(item.get("uri"), str):
            block: dict[str, Any] = {
                "type": "resource_link",
                "uri": item["uri"],
                "name": str(item.get("name") or item["uri"]),
            }
            if isinstance(item.get("description"), str):
                block["description"] = item["description"]
            if isinstance(item.get("mimeType"), str):
                block["mime_type"] = item["mimeType"]
            converted.append(block)
        elif item_type == "resource" and isinstance(item.get("resource"), dict):
            resource = item["resource"]
            if not isinstance(resource.get("uri"), str):
                raise ProgramError("external_error", "腾讯文档资源缺少 URI")
            block = {"type": "resource", "uri": resource["uri"]}
            if isinstance(resource.get("mimeType"), str):
                block["mime_type"] = resource["mimeType"]
            if isinstance(resource.get("text"), str):
                block["text"] = resource["text"]
            elif isinstance(resource.get("blob"), str):
                block["data"] = resource["blob"]
            else:
                raise ProgramError("external_error", "腾讯文档资源缺少有效内容")
            converted.append(block)
        else:
            raise ProgramError("external_error", "腾讯文档返回了不支持的内容类型")
    return converted


def _check_tool_result(result: dict[str, Any]) -> None:
    if not result.get("isError"):
        return
    message = next(
        (
            item["text"]
            for item in result.get("content", [])
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ),
        "腾讯文档工具调用失败",
    )
    raise ProgramError("external_error", message)


def configuration_validate(_context: dict[str, Any]) -> dict[str, Any]:
    return {}


def authorization_identity(_context: dict[str, Any]) -> dict[str, Any]:
    return {"identity": {"endpoint": _ENDPOINT}}


def authorization_begin(_context: dict[str, Any]) -> dict[str, Any]:
    return {"type": "form"}


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "credentials":
        raise ProgramError("bad_request", "腾讯文档需要提交 Token")
    token = _token_from_values(submission.get("values"))
    with _McpClient(token) as client:
        client.list_tools()
    return {
        "external_account_name": "腾讯文档用户",
        "credential": {"values": {"access_token": token}},
        "public_metadata": {"endpoint": _ENDPOINT},
    }


def tools_discover(context: dict[str, Any]) -> dict[str, Any]:
    token = _token_from_context(context)
    with _McpClient(token) as client:
        client.list_tools()
    descriptions = {
        "search_tools": "搜索腾讯文档当前可用工具，返回参数和风险分类。",
        "execute_read_tool": "调用只读工具；先使用 search_tools 获取官方工具名和参数。",
        "execute_write_tool": "调用普通写入工具，禁止自动重试。",
        "execute_confirmed_write_tool": "经用户确认后调用写入工具，禁止自动重试。",
        "execute_destructive_tool": "经用户确认后调用删除工具，禁止自动重试。",
        "execute_unknown_tool": "经用户确认后调用无法判断风险的工具，禁止自动重试。",
    }
    return {
        "tools": [
            {
                "key": name,
                "upstream_name": name,
                "description": descriptions[name],
                "input_schema": _SEARCH_SCHEMA if name == "search_tools" else _CALL_SCHEMA,
                "effect": effect,
                "retry_policy": retry,
                "confirmation": confirmation,
            }
            for name, (effect, retry, confirmation) in _TOOL_POLICIES.items()
        ]
    }


def _search_tools(arguments: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
    query = arguments["query"].strip().casefold()
    terms = query.split()
    summaries = [_tool_summary(tool) for tool in tools]
    matches = [
        tool
        for tool in summaries
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
    limit = arguments.get("limit", 20)
    page = matches[offset : offset + limit]
    return {
        "total": len(matches),
        "tools": page,
        "next_offset": offset + len(page) if offset + len(page) < len(matches) else None,
    }


def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    dispatcher = context.get("tool_name")
    if not isinstance(dispatcher, str) or dispatcher not in _TOOL_POLICIES:
        raise ProgramError("action_forbidden", "腾讯文档调用入口未获清单授权")
    arguments = context.get("arguments")
    _validate_arguments(arguments, _SEARCH_SCHEMA if dispatcher == "search_tools" else _CALL_SCHEMA)
    token = _token_from_context(context)
    with _McpClient(token) as client:
        tools = client.list_tools()
        if dispatcher == "search_tools":
            payload = _search_tools(arguments, tools)
            return {
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                "structured_content": payload,
                "is_error": False,
            }
        target_name = arguments["name"]
        target = next((tool for tool in tools if tool.get("name") == target_name), None)
        if target is None:
            raise ProgramError("action_forbidden", "腾讯文档工具不存在或已下线")
        expected_dispatcher = _classify_tool(target)
        if expected_dispatcher != dispatcher:
            raise ProgramError("action_forbidden", "工具风险分类与调用入口不匹配")
        _validate_arguments(arguments["arguments"], _tool_schema(target))
        result = client.call_tool(target_name, arguments["arguments"])
    _check_tool_result(result)
    structured = result.get("structuredContent")
    if structured is not None and not isinstance(structured, dict):
        raise ProgramError("external_error", "腾讯文档结构化结果格式错误")
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
