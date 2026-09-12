from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote, quote_plus, urljoin, urlsplit

import httpx

_ENDPOINT = "https://mcp-pan.baidu.com/sse"
_PROTOCOL_VERSION = "2024-11-05"
_MAX_RESPONSE_BYTES = 1024 * 1024
_TOOL_EFFECTS = {
    "file_list": "read",
    "file_doc_list": "read",
    "file_image_list": "read",
    "file_video_list": "read",
    "file_meta": "read",
    "file_keyword_search": "read",
    "file_semantics_search": "read",
    "user_info": "read",
    "get_quota": "read",
    # 这四个接口支持覆盖已有文件，统一采用破坏性操作策略。
    "make_dir": "destructive",
    "file_copy": "destructive",
    "file_move": "destructive",
    "file_rename": "destructive",
    "file_upload_by_url": "write",
    "file_sharelink_set": "write",
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _token(values: Any) -> str:
    token = values.get("access_token") if isinstance(values, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise ProgramError("authorization_required", "请在授权表单中填写 Access Token")
    if len(token.strip()) > 4096:
        raise ProgramError("bad_request", "Access Token 长度不能超过 4096 个字符")
    return token.strip()


def _policy(name: str) -> dict[str, str]:
    if name not in _TOOL_EFFECTS:
        raise ProgramError("action_forbidden", "该百度网盘工具未获连接器授权")
    effect = _TOOL_EFFECTS[name]
    return {
        "effect": effect,
        "retry_policy": "safe" if effect == "read" else "never",
        "confirmation": "not_required" if effect == "read" else "user_required",
    }


def _digest(value: Any) -> str:
    source = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(source).hexdigest()


async def _check_http(response: httpx.Response) -> None:
    if 200 <= response.status_code < 300:
        return
    if response.status_code in {401, 403}:
        raise ProgramError("authorization_required", "百度网盘授权失效，请重新授权")
    if response.status_code == 400:
        await response.aread()
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("errno") == 2003:
            raise ProgramError("authorization_required", "百度网盘拒绝了 Access Token")
    if response.status_code == 429:
        raise ProgramError("rate_limited", "百度网盘请求过于频繁，请稍后再操作")
    # 不输出 HTTP 异常对象；其中的请求 URL 包含用户 Token。
    raise ProgramError(
        "unavailable", f"百度网盘 MCP 请求失败（HTTP {response.status_code}）"
    )


async def _events(response: httpx.Response) -> AsyncIterator[tuple[str, str]]:
    event = "message"
    data: list[str] = []
    size = 0
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data, size = "message", [], 0
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            value = ""
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            size += len(value.encode()) + 1
            if size > _MAX_RESPONSE_BYTES:
                raise ProgramError("external_error", "百度网盘响应过大，请缩小查询范围")
            data.append(value)
    raise ProgramError("unavailable", "百度网盘 SSE 连接已关闭，未取得完整响应")


class _SseSession:
    def __init__(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        events: AsyncIterator[tuple[str, str]],
    ) -> None:
        self.client = client
        self.endpoint = endpoint
        self.events = events
        self.request_id = 0

    async def post(self, payload: dict[str, Any]) -> None:
        response = await self.client.post(self.endpoint, json=payload)
        await _check_http(response)

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.request_id += 1
        await self.post(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": params,
            }
        )
        async for event, data in self.events:
            if event != "message":
                raise ProgramError("external_error", "百度网盘返回了意外的 SSE 事件")
            message = json.loads(data)
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise ProgramError("external_error", "百度网盘 MCP 消息格式错误")
            if "id" not in message:
                continue  # MCP 通知不是当前请求的响应。
            if message["id"] != self.request_id:
                raise ProgramError("external_error", "百度网盘 MCP 响应编号不匹配")
            if "error" in message:
                error = message["error"]
                detail = error.get("message") if isinstance(error, dict) else None
                raise ProgramError(
                    "external_error",
                    detail
                    if isinstance(detail, str) and detail
                    else "百度网盘 MCP 请求失败",
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise ProgramError("external_error", "百度网盘 MCP 结果格式错误")
            return result
        raise ProgramError("unavailable", "百度网盘未返回 MCP 结果")

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            result = await self.request(
                "tools/list", {"cursor": cursor} if cursor else {}
            )
            page = result.get("tools")
            if not isinstance(page, list) or not all(isinstance(t, dict) for t in page):
                raise ProgramError("external_error", "百度网盘工具目录格式错误")
            tools.extend(page)
            cursor = result.get("nextCursor")
            if cursor is None:
                return tools
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ProgramError("external_error", "百度网盘工具目录游标无效")
            seen.add(cursor)


@asynccontextmanager
async def _mcp_session(token: str) -> AsyncIterator[_SseSession]:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        async with client.stream(
            "GET",
            _ENDPOINT,
            params={"access_token": token},
            headers={"Accept": "text/event-stream"},
        ) as response:
            await _check_http(response)
            if (
                response.headers.get("content-type", "").split(";")[0]
                != "text/event-stream"
            ):
                raise ProgramError("external_error", "百度网盘未返回 SSE 数据流")
            events = _events(response)
            event, data = await anext(events)
            if event != "endpoint":
                raise ProgramError("external_error", "百度网盘未返回 SSE 消息地址")
            endpoint = urljoin(_ENDPOINT, data)
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "mcp-pan.baidu.com"
                or parsed.username
                or parsed.password
                or parsed.fragment
            ):
                raise ProgramError(
                    "external_error", "百度网盘 SSE 消息地址不属于官方服务"
                )
            session = _SseSession(client, endpoint, events)
            result = await session.request(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "POCO", "version": "1"},
                },
            )
            if result.get("protocolVersion") != _PROTOCOL_VERSION:
                raise ProgramError("external_error", "百度网盘 MCP 协议版本不匹配")
            await session.post(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
            yield session


def _allowed_tools(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    allowed = {}
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or name not in _TOOL_EFFECTS:
            continue
        if name in allowed:
            raise ProgramError("external_error", "百度网盘工具目录包含重复名称")
        policy = _policy(name)
        annotations = tool.get("annotations")
        if annotations is None:
            annotations = {}
        if not isinstance(annotations, dict):
            raise ProgramError("external_error", "百度网盘工具风险标注格式错误")
        if (
            policy["effect"] == "read" and annotations.get("readOnlyHint") is False
        ) or (
            policy["effect"] != "destructive"
            and annotations.get("destructiveHint") is True
        ):
            raise ProgramError(
                "action_forbidden", "百度网盘工具风险已变化，需要更新连接器"
            )
        description = tool.get("description")
        schema = tool.get("inputSchema")
        output = tool.get("outputSchema")
        if (
            not isinstance(description, str)
            or not description.strip()
            or not isinstance(schema, dict)
            or schema.get("type") != "object"
            or (output is not None and not isinstance(output, dict))
        ):
            raise ProgramError("external_error", "百度网盘工具说明或参数 Schema 无效")
        spec = {
            "key": name,
            "upstream_name": name,
            "description": description,
            "input_schema": schema,
            "output_schema": output,
            **policy,
        }
        spec["source_revision"] = _digest({"tool": tool, "policy": policy})
        allowed[name] = spec
    if not allowed:
        raise ProgramError("insufficient_scope", "该授权未返回连接器允许的网盘工具")
    return allowed


def _content_blocks(result: dict[str, Any]) -> list[dict[str, Any]]:
    content = result.get("content")
    if not isinstance(content, list):
        raise ProgramError("external_error", "百度网盘工具内容格式错误")
    converted: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            raise ProgramError("external_error", "百度网盘工具内容项格式错误")
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
                raise ProgramError("external_error", "百度网盘资源缺少 URI")
            block = {"type": "resource", "uri": resource["uri"]}
            if isinstance(resource.get("mimeType"), str):
                block["mime_type"] = resource["mimeType"]
            if isinstance(resource.get("text"), str) and "blob" not in resource:
                block["text"] = resource["text"]
            elif isinstance(resource.get("blob"), str) and "text" not in resource:
                block["data"] = resource["blob"]
            else:
                raise ProgramError("external_error", "百度网盘资源缺少有效内容")
            converted.append(block)
        else:
            raise ProgramError("external_error", "百度网盘返回了不支持的内容类型")
    return converted


def _tool_result(result: dict[str, Any]) -> dict[str, Any]:
    content = _content_blocks(result)
    structured = result.get("structuredContent")
    is_error = result.get("isError", False)
    if not isinstance(is_error, bool) or (
        structured is not None and not isinstance(structured, dict)
    ):
        raise ProgramError("external_error", "百度网盘工具结果格式错误")
    payloads = [structured]
    for item in content:
        if item["type"] == "text":
            try:
                payloads.append(json.loads(item["text"]))
            except ValueError:
                continue  # MCP 文本内容也可以是普通文本。
    error_code = "external_error"
    for payload in payloads:
        if isinstance(payload, dict) and payload.get("errno") not in (None, 0, "0"):
            is_error = True
            if payload["errno"] in (2003, "2003"):
                error_code = "authorization_required"
    error = None
    if is_error:
        error = {
            "code": error_code,
            "message": "百度网盘工具执行失败，请查看返回内容；写操作请勿自动重试",
            "retryable": False,
        }
    return {
        "content": content,
        "structured_content": structured,
        "is_error": is_error,
        "error": error,
    }


async def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    configuration = context.get("configuration", {})
    if (
        not isinstance(configuration, dict)
        or set(configuration) - {"public", "secret"}
        or any(not isinstance(value, dict) or value for value in configuration.values())
    ):
        raise ProgramError("bad_request", "百度网盘连接器没有管理员配置项")
    return {}


async def authorization_identity(_context: dict[str, Any]) -> dict[str, Any]:
    return {"identity": {"endpoint": _ENDPOINT}}


async def authorization_begin(_context: dict[str, Any]) -> dict[str, Any]:
    return {"type": "form"}


async def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "credentials":
        raise ProgramError("bad_request", "请通过授权表单提交 Access Token")
    token = _token(submission.get("values"))
    async with _mcp_session(token) as session:
        _allowed_tools(await session.list_tools())
    return {
        "external_account_name": "百度网盘用户",
        "credential": {"values": {"access_token": token}},
        "public_metadata": {"endpoint": _ENDPOINT},
    }


async def tools_discover(context: dict[str, Any]) -> dict[str, Any]:
    async with _mcp_session(_token(context.get("credentials"))) as session:
        tools = _allowed_tools(await session.list_tools())
    return {"tools": list(tools.values())}


async def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    name = context.get("tool_name")
    if not isinstance(name, str):
        raise ProgramError("bad_request", "工具名称必须是字符串")
    _policy(name)
    arguments = context.get("arguments")
    if not isinstance(arguments, dict):
        raise ProgramError("bad_request", "工具参数必须是 JSON 对象")
    async with _mcp_session(_token(context.get("credentials"))) as session:
        tools = _allowed_tools(await session.list_tools())
        if name not in tools:
            raise ProgramError("action_forbidden", "该百度网盘工具未获授权或已下线")
        # Poco 已校验输入 Schema 并消费写操作的一次性确认；不接收调用方风险覆盖。
        result = await session.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
    return _tool_result(result)


_OPERATIONS = {
    "configuration_validate": configuration_validate,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "authorization_complete": authorization_complete,
    "tools_discover": tools_discover,
    "tool_invoke": tool_invoke,
}


async def _dispatch(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("protocol_version") != 1:
        raise ProgramError("bad_request", "连接器协议版本错误")
    operation = request.get("operation")
    context = request.get("context")
    handler = _OPERATIONS.get(operation) if isinstance(operation, str) else None
    if handler is None or not isinstance(context, dict):
        raise ProgramError("bad_request", "连接器操作或上下文无效")
    async with asyncio.timeout(25):
        return await handler(context)


def _failure(code: str, message: str) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "ok": False,
        "error": {"code": code, "message": message, "retryable": False},
    }


def _redact(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    return value


def main() -> None:
    request = None
    try:
        try:
            request = json.load(sys.stdin)
        except ValueError as exc:
            raise ProgramError("bad_request", "请求必须是有效 JSON") from exc
        result = asyncio.run(_dispatch(request))
        response = {"protocol_version": 1, "ok": True, "result": result}
    except ProgramError as exc:
        response = _failure(exc.code, exc.message)
    except (TimeoutError, httpx.TimeoutException):
        response = _failure(
            "unavailable", "百度网盘请求超时；写入结果可能未知，请先查询确认"
        )
    except httpx.HTTPError as exc:
        response = _failure(
            "unavailable", f"百度网盘网络请求失败（{type(exc).__name__}）"
        )
    except Exception as exc:
        response = _failure(
            "external_error", f"连接器响应处理失败（{type(exc).__name__}）"
        )
    # 成功授权必须把凭据交还 Poco；其他输出不得回显远端可能包含的 Token。
    is_authorization = (
        isinstance(request, dict)
        and request.get("operation") == "authorization_complete"
        and response["ok"]
    )
    if not is_authorization and isinstance(request, dict):
        context = request.get("context")
        if isinstance(context, dict):
            values = context.get("credentials")
            submission = context.get("submission")
            if request.get("operation") == "authorization_complete" and isinstance(
                submission, dict
            ):
                values = submission.get("values")
            if isinstance(values, dict):
                token = values.get("access_token")
                if isinstance(token, str) and token.strip():
                    secrets = {
                        token.strip(),
                        quote(token.strip(), safe=""),
                        quote_plus(token.strip()),
                    }
                    if response["ok"]:
                        response["result"] = _redact(response["result"], secrets)
                    else:
                        response["error"]["message"] = _redact(
                            response["error"]["message"], secrets
                        )
    if not response["ok"]:
        # 脱敏之后才能截断错误文本，避免输出被截断的 Token 前缀。
        response["error"]["message"] = response["error"]["message"][:2000]
    output = json.dumps(
        response, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(output.encode()) > _MAX_RESPONSE_BYTES:
        output = json.dumps(
            _failure(
                "external_error",
                "结果超过 Poco 响应上限；写操作请先查询结果，勿重复提交",
            ),
            ensure_ascii=False,
        )
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
