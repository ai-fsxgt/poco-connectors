import base64
import hashlib
import hmac
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit

import httpx

_ROOT = Path(__file__).resolve().parent
_CATALOG = json.loads((_ROOT / "tools.json").read_text())
_WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send"
_TIMEOUT = 15.0
_RATE_LIMIT_ERRCODES = {130101, 410100}
_TOOL_POLICIES = {
    "get_connection_info": ("read", "safe", "not_required"),
    "send_text": ("write", "never", "user_required"),
    "send_markdown": ("write", "never", "user_required"),
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _credentials(values: Any) -> tuple[str, str, str]:
    """返回 (群名称, access_token, 加签密钥)。"""
    keys = ("group_name", "webhook_url", "secret")
    if not isinstance(values, dict) or not all(
        isinstance(values.get(key), str) and values[key].strip() for key in keys
    ):
        raise ProgramError(
            "authorization_required", "请填写群名称、Webhook 地址和加签密钥"
        )
    group_name, webhook_url, secret = (values[key].strip() for key in keys)
    if len(group_name) > 64 or not group_name.isprintable():
        raise ProgramError("bad_request", "群名称不能超过 64 个字符且不能包含控制字符")
    parts = urlsplit(webhook_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    tokens = query.get("access_token", [])
    if (
        f"{parts.scheme}://{parts.netloc}{parts.path}" != _WEBHOOK_URL
        or parts.fragment
        or set(query) != {"access_token"}
        or len(tokens) != 1
        or re.fullmatch(r"[0-9A-Za-z]{1,256}", tokens[0]) is None
    ):
        raise ProgramError(
            "bad_request",
            "Webhook 地址格式错误，应为 https://oapi.dingtalk.com/robot/send?access_token=...",
        )
    if re.fullmatch(r"SEC[0-9A-Za-z]{1,253}", secret) is None:
        raise ProgramError(
            "bad_request", "加签密钥格式错误，应为机器人加签设置中以 SEC 开头的密钥"
        )
    return group_name, tokens[0], secret


def _validate(value: Any, schema: dict[str, Any], path: str = "arguments") -> None:
    expected = schema["type"]
    types = {"object": dict, "array": list, "string": str, "boolean": bool}
    if type(value) is not types[expected]:
        raise ProgramError("bad_request", f"{path} 必须为 {expected}")
    if expected == "object":
        properties = schema["properties"]
        if set(value) - properties.keys() or set(schema["required"]) - value.keys():
            raise ProgramError("bad_request", f"{path} 含未知参数或缺少必填参数")
        for key, item in value.items():
            _validate(item, properties[key], f"{path}.{key}")
    elif expected == "array":
        for item in value:
            _validate(item, schema["items"], f"{path}[]")
        if schema.get("uniqueItems") and len(set(value)) != len(value):
            raise ProgramError("bad_request", f"{path} 不能包含重复值")
    elif expected == "string":
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", sys.maxsize
        ):
            raise ProgramError("bad_request", f"{path} 长度超出允许范围")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ProgramError("bad_request", f"{path} 格式错误")


def _tool_spec(name: str) -> dict[str, Any]:
    if name not in _TOOL_POLICIES or name not in _CATALOG:
        raise ProgramError("action_forbidden", "该工具未获连接器授权")
    effect, retry, confirmation = _TOOL_POLICIES[name]
    tool = {
        "key": name,
        "upstream_name": name,
        **_CATALOG[name],
        "output_schema": None,
        "effect": effect,
        "retry_policy": retry,
        "confirmation": confirmation,
    }
    source = json.dumps(tool, ensure_ascii=False, sort_keys=True).encode()
    tool["source_revision"] = hashlib.sha256(source).hexdigest()
    return tool


def _signed_url(access_token: str, secret: str) -> str:
    timestamp = str(round(time.time() * 1000))
    digest = hmac.new(
        secret.encode(), f"{timestamp}\n{secret}".encode(), hashlib.sha256
    ).digest()
    sign = quote_plus(base64.b64encode(digest).decode())
    return (
        f"{_WEBHOOK_URL}?access_token={access_token}&timestamp={timestamp}&sign={sign}"
    )


def _message(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    at = {
        "atMobiles": arguments.get("at_mobiles", []),
        "atUserIds": arguments.get("at_user_ids", []),
        "isAtAll": arguments.get("is_at_all", False),
    }
    if name == "send_text":
        return {"msgtype": "text", "text": {"content": arguments["content"]}, "at": at}
    return {
        "msgtype": "markdown",
        "markdown": {"title": arguments["title"], "text": arguments["text"]},
        "at": at,
    }


def _send(access_token: str, secret: str, message: dict[str, Any]) -> None:
    response = httpx.post(
        _signed_url(access_token, secret), json=message, timeout=_TIMEOUT
    )
    if response.status_code != 200:
        raise ProgramError(
            "external_error",
            f"钉钉返回 HTTP {response.status_code}；消息可能未发送，请先到群里确认，勿重复发送",
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ProgramError(
            "external_error", "钉钉返回了无法解析的响应；请先到群里确认，勿重复发送"
        ) from exc
    errcode, errmsg = data.get("errcode"), data.get("errmsg")
    if errcode == 0:
        return
    if errcode == 300001 or (errcode == 310000 and "sign not match" in str(errmsg)):
        code = "authorization_required"
        hint = "请检查 Webhook 地址和加签密钥后重新授权"
    elif errcode == 310000:
        code = "bad_request"
        hint = "消息未发送；请检查消息是否包含自定义关键词，以及 IP 白名单设置"
    elif errcode in _RATE_LIMIT_ERRCODES:
        code = "rate_limited"
        hint = "机器人每分钟最多发送 20 条，超出后被限流 10 分钟"
    else:
        code = "external_error"
        hint = "消息未发送"
    raise ProgramError(code, f"钉钉返回错误 {errcode}：{errmsg}；{hint}")


def _tool_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        "structured_content": data,
        "is_error": False,
        "error": None,
    }


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    configuration = context.get("configuration", {})
    if (
        not isinstance(configuration, dict)
        or set(configuration) - {"public", "secret"}
        or any(not isinstance(value, dict) or value for value in configuration.values())
    ):
        raise ProgramError("bad_request", "钉钉群机器人连接器没有管理员配置项")
    return {}


def authorization_identity(_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": {"service": "dingtalk-robot", "authorization_contract_version": "1"}
    }


def authorization_begin(_context: dict[str, Any]) -> dict[str, Any]:
    return {"type": "form"}


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "credentials":
        raise ProgramError(
            "bad_request", "请通过授权表单提交群名称、Webhook 地址和加签密钥"
        )
    group_name, access_token, secret = _credentials(submission.get("values"))
    return {
        "external_account_id": hashlib.sha256(access_token.encode()).hexdigest()[:32],
        "external_account_name": group_name,
        "credential": {
            "values": {
                "group_name": group_name,
                "webhook_url": f"{_WEBHOOK_URL}?access_token={access_token}",
                "secret": secret,
            }
        },
        "public_metadata": {"group_name": group_name},
    }


def tools_discover(context: dict[str, Any]) -> dict[str, Any]:
    _credentials(context.get("credentials"))
    return {"tools": [_tool_spec(name) for name in _TOOL_POLICIES]}


def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    name = context.get("tool_name")
    if not isinstance(name, str):
        raise ProgramError("bad_request", "工具名称必须是字符串")
    spec = _tool_spec(name)
    arguments = context.get("arguments")
    _validate(arguments, spec["input_schema"])
    group_name, access_token, secret = _credentials(context.get("credentials"))
    if name == "get_connection_info":
        return _tool_result(
            {"group_name": group_name, "message_types": ["text", "markdown"]}
        )
    message = _message(name, arguments)
    _send(access_token, secret, message)
    return _tool_result(
        {"sent": True, "group_name": group_name, "msgtype": message["msgtype"]}
    )


_OPERATIONS = {
    "configuration_validate": configuration_validate,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "authorization_complete": authorization_complete,
    "tools_discover": tools_discover,
    "tool_invoke": tool_invoke,
}


def _dispatch(request: Any) -> dict[str, Any]:
    if (
        not isinstance(request, dict)
        or type(request.get("protocol_version")) is not int
        or request["protocol_version"] != 1
    ):
        raise ProgramError("bad_request", "连接器协议版本错误")
    operation, context = request.get("operation"), request.get("context")
    handler = _OPERATIONS.get(operation) if isinstance(operation, str) else None
    if handler is None or not isinstance(context, dict):
        raise ProgramError("bad_request", "连接器操作或上下文无效")
    return handler(context)


def _failure(code: str, message: str) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "ok": False,
        "error": {"code": code, "message": message[:2000], "retryable": False},
    }


def main() -> None:
    try:
        try:
            request = json.loads(sys.stdin.buffer.read())
        except (ValueError, UnicodeError) as exc:
            raise ProgramError("bad_request", "请求必须是有效 JSON") from exc
        response = {"protocol_version": 1, "ok": True, "result": _dispatch(request)}
    except ProgramError as exc:
        response = _failure(exc.code, exc.message)
    except httpx.TimeoutException:
        response = _failure(
            "unavailable", "连接钉钉超时，消息可能已发送；请先到群里确认，勿自动重试"
        )
    except httpx.TransportError as exc:
        response = _failure(
            "unavailable",
            f"连接钉钉失败（{type(exc).__name__}）；请先到群里确认消息是否已发送",
        )
    except Exception as exc:
        response = _failure("external_error", f"连接器处理失败（{type(exc).__name__}）")
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
