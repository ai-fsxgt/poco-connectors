import hashlib
import json
import sys
from typing import Any

import httpx

_TOKEN_PATH = "/oauth2/wecom_agent_token"
_TIMEOUT = 20.0
_TOOL = {
    "key": "get_oa_token",
    "upstream_name": "get_oa_token",
    "description": (
        "以当前 IM 消息发送人的身份换取建龙 OA 访问凭证，返回 access_token、"
        "token_type、工号 emp_no 和过期时间。凭证默认 10 分钟有效，未过期前可复用，"
        "过期后重新调用。只能在企业微信、钉钉、飞书等 IM 对话中使用。"
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    "output_schema": None,
    "effect": "read",
    "retry_policy": "safe",
    "confirmation": "not_required",
}
_TOOL["source_revision"] = hashlib.sha256(
    json.dumps(_TOOL, ensure_ascii=False, sort_keys=True).encode()
).hexdigest()


class ProgramError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _config_value(context: dict[str, Any], scope: str, key: str, label: str) -> str:
    value = context["configuration"][scope].get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProgramError("bad_request", f"管理员需要配置{label}")
    return value.strip()


def _exchange_token(context: dict[str, Any]) -> dict[str, Any]:
    sender = context.get("im_sender")
    if not sender:
        raise ProgramError(
            "bad_request", "只能在企业微信、钉钉、飞书等 IM 对话中使用，网页对话无法获取员工身份"
        )
    base_url = _config_value(context, "public", "base_url", "OA 认证服务地址")
    body = {
        "appId": _config_value(context, "public", "app_id", "应用 appId"),
        "appSecret": _config_value(context, "secret", "app_secret", "应用密钥"),
        "ticketType": "open_userid",
        "ticket": sender["user_id"],
    }
    response = httpx.post(base_url.rstrip("/") + _TOKEN_PATH, json=body, timeout=_TIMEOUT)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict) and data.get("access_token"):
        return data
    detail = (
        f"code {payload.get('code')}：{payload.get('message')}"
        if isinstance(payload, dict)
        else response.text[:500]
    )
    code = "unavailable" if response.status_code >= 500 else "external_error"
    raise ProgramError(code, f"换取 OA 凭证失败（HTTP {response.status_code}，{detail}）")


def configuration_validate(_context: dict[str, Any]) -> dict[str, Any]:
    return {}


def tools_discover(_context: dict[str, Any]) -> dict[str, Any]:
    return {"tools": [_TOOL]}


def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    if context.get("tool_name") != _TOOL["key"]:
        raise ProgramError("action_forbidden", "该工具未获连接器授权")
    if context.get("arguments") != {}:
        raise ProgramError("bad_request", "该工具不接受参数")
    data = _exchange_token(context)
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        "structured_content": data,
        "is_error": False,
        "error": None,
    }


_OPERATIONS = {
    "configuration_validate": configuration_validate,
    "tools_discover": tools_discover,
    "tool_invoke": tool_invoke,
}


def _dispatch(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("protocol_version") != 1:
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
    except Exception as exc:
        # The protocol requires one JSON response; surface the real failure.
        response = _failure("external_error", f"连接器处理失败（{type(exc).__name__}: {exc}）")
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
