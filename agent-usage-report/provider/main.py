import base64
import gzip
import json
import signal
import sys
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import httpx

_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_ADMIN_ROLES = {"admin", "super_admin"}
_TOOL_NAME = "get_usage_dataset"
_TOOL_SPEC = {
    "key": _TOOL_NAME,
    "upstream_name": _TOOL_NAME,
    "description": (
        "获取 Agent 平台指定日期区间（北京时间，最长 31 天）的使用数据集："
        "汇总与上一周期对比、逐日数据、用户与部门、工作项明细（定时任务、对话、API "
        "会话的标题、AI 摘要、运行次数、成功失败、成本、Token）。"
        "数据以 .json.gz 文件保存到工作区，由 agent-usage-report 技能的脚本处理。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                "description": "开始日期（含），格式 YYYY-MM-DD，北京时间。",
            },
            "end_date": {
                "type": "string",
                "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                "description": "结束日期（含），格式 YYYY-MM-DD，北京时间。",
            },
        },
        "required": ["start_date", "end_date"],
        "additionalProperties": False,
    },
    "output_schema": None,
    "effect": "read",
    "retry_policy": "safe",
    "confirmation": "not_required",
    "source_revision": "get-usage-dataset-v1",
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _api_base_url(context: dict[str, Any]) -> str:
    configuration = context.get("configuration")
    public = configuration.get("public") if isinstance(configuration, dict) else None
    value = public.get("api_base_url") if isinstance(public, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ProgramError("bad_request", "管理员需要配置平台 API 地址")
    url = value.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ProgramError("bad_request", "平台 API 地址必须是 http(s) URL")
    return url


def _credentials(values: Any) -> tuple[str, str]:
    username = values.get("username") if isinstance(values, dict) else None
    password = values.get("password") if isinstance(values, dict) else None
    if not all(isinstance(item, str) and item.strip() for item in (username, password)):
        raise ProgramError("authorization_required", "请填写管理员账号和密码")
    return username.strip(), password


def _data(response: httpx.Response, action: str) -> Any:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProgramError(
            "unavailable",
            f"{action}失败：平台返回了非 JSON 响应（HTTP {response.status_code}）",
        ) from exc
    if response.status_code >= 500:
        raise ProgramError("unavailable", f"{action}失败：{payload.get('message')}")
    if response.is_error or payload.get("code") != 0:
        raise ProgramError("external_error", f"{action}失败：{payload.get('message')}")
    return payload.get("data")


def _client(context: dict[str, Any]) -> httpx.Client:
    return httpx.Client(base_url=_api_base_url(context), timeout=60.0)


def _login_admin(client: httpx.Client, username: str, password: str) -> dict:
    """Log in, bind the token to the client and require an admin role."""
    response = client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    if response.status_code == 400:
        raise ProgramError(
            "authorization_required",
            f"登录失败：{response.json().get('message')}，请重新授权",
        )
    token = _data(response, "登录")["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    me = _data(client.get("/auth/me"), "读取账号信息")
    if me["role"] not in _ADMIN_ROLES:
        raise ProgramError("action_forbidden", "该账号不是平台管理员，无法读取使用数据")
    return me


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    _api_base_url(context)
    return {}


def authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    return {"identity": {"api_base_url": _api_base_url(context)}}


def authorization_begin(_context: dict[str, Any]) -> dict[str, Any]:
    return {"type": "form"}


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "credentials":
        raise ProgramError("bad_request", "请通过授权表单提交管理员账号和密码")
    username, password = _credentials(submission.get("values"))
    with _client(context) as client:
        me = _login_admin(client, username, password)
    return {
        "external_account_id": me["id"],
        "external_account_name": me["full_name"] or me["username"],
        "credential": {"values": {"username": username, "password": password}},
        "public_metadata": {"username": me["username"], "role": me["role"]},
    }


def tools_discover(context: dict[str, Any]) -> dict[str, Any]:
    _credentials(context.get("credentials"))
    return {"tools": [_TOOL_SPEC]}


def _date_argument(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ProgramError(
            "bad_request", f"{key} 必须是 YYYY-MM-DD 格式的日期"
        ) from exc


def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    if context.get("tool_name") != _TOOL_NAME:
        raise ProgramError("bad_request", "未知工具")
    arguments = context.get("arguments")
    if not isinstance(arguments, dict) or set(arguments) != {"start_date", "end_date"}:
        raise ProgramError("bad_request", "参数只能且必须包含 start_date 和 end_date")
    params = {
        "start_date": _date_argument(arguments, "start_date"),
        "end_date": _date_argument(arguments, "end_date"),
        "timezone": "Asia/Shanghai",
    }

    username, password = _credentials(context.get("credentials"))
    with _client(context) as client:
        _login_admin(client, username, password)
        response = client.get("/admin/usage-report/dataset", params=params)
        if response.status_code == 400:
            raise ProgramError("bad_request", response.json().get("message"))
        dataset = _data(response, "读取使用数据")

    archive = gzip.compress(json.dumps(dataset, ensure_ascii=False).encode())
    overview = {
        "start_date": params["start_date"],
        "end_date": params["end_date"],
        "totals": dataset["totals"],
        "work_items": len(dataset["work_items"]),
        "users": len(dataset["users"]),
        "next_step": "数据集已保存为工作区中的 .json.gz 文件，请按技能说明交给 scripts/report.py 处理，不要直接读取全文。",
    }
    return {
        "content": [
            {"type": "text", "text": json.dumps(overview, ensure_ascii=False)},
            {
                "type": "resource",
                "uri": f"agent-usage-report://dataset/{params['start_date']}_{params['end_date']}",
                "mime_type": "application/gzip",
                "data": base64.b64encode(archive).decode("ascii"),
            },
        ],
        "structured_content": None,
        "is_error": False,
        "error": None,
    }


_OPERATIONS = {
    "configuration_validate": configuration_validate,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "authorization_complete": authorization_complete,
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


def _timeout(_signum, _frame) -> None:
    raise TimeoutError


def main() -> None:
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(70)
    try:
        raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
        if len(raw) > _MAX_REQUEST_BYTES:
            raise ProgramError("bad_request", "请求超过 2 MiB 上限")
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ProgramError("bad_request", "请求必须是有效 JSON") from exc
        response = {"protocol_version": 1, "ok": True, "result": _dispatch(request)}
    except ProgramError as exc:
        response = _failure(exc.code, exc.message)
    except (TimeoutError, httpx.TimeoutException):
        response = _failure("unavailable", "平台接口响应超时，请缩短日期区间后重试")
    except httpx.RequestError as exc:
        response = _failure("unavailable", f"无法连接平台接口（{type(exc).__name__}）")
    except Exception as exc:
        # The protocol requires one JSON response; surface the real failure.
        response = _failure(
            "external_error", f"连接器处理失败（{type(exc).__name__}: {exc}）"
        )
    finally:
        signal.alarm(0)

    output = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    if len(output.encode()) > _MAX_RESPONSE_BYTES:
        output = json.dumps(
            _failure("bad_request", "数据集超过 1 MiB 上限，请缩短日期区间后分段获取"),
            ensure_ascii=False,
        )
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
