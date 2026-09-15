from __future__ import annotations

import json
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from string import Formatter
from typing import Any
from urllib.parse import quote, urlencode

import httpx

_AUTHORIZE_URL = "https://meeting.tencent.com/marketplace/authorize.html"
_ACCESS_TOKEN_URL = (
    "https://meeting.tencent.com/wemeet-webapi/v2/oauth2/oauth/access_token"
)
_REFRESH_TOKEN_URL = (
    "https://meeting.tencent.com/wemeet-webapi/v2/oauth2/oauth/refresh_token"
)
_API_BASE = "https://api.meeting.qq.com"


class ProgramError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:2000]
        self.retryable = retryable


def _schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "additionalProperties": True,
        "properties": {},
    }


_COMMANDS: dict[str, dict[str, Any]] = {
    "meeting_create": {"description": "创建腾讯会议。参数使用官方会议创建 API 字段。", "method": "POST", "path": "/v1/meetings", "effect": "write"},
    "meeting_update": {"description": "更新会议主题、时间或设置。需要 meeting_id。", "method": "PUT", "path": "/v1/meetings/{meeting_id}", "effect": "write"},
    "meeting_cancel": {"description": "取消会议。需要 meeting_id；不可恢复。", "method": "POST", "path": "/v1/meetings/{meeting_id}/cancel", "effect": "destructive"},
    "meeting_get": {"description": "按 meeting_id 获取会议详情。", "method": "GET", "path": "/v1/meetings/{meeting_id}", "effect": "read"},
    "meeting_get_by_code": {"description": "按 meeting_code 获取会议详情。", "method": "GET", "path": "/v1/meetings", "effect": "read"},
    "meeting_list": {"description": "查询未开始或进行中的会议列表。", "method": "GET", "path": "/v1/meetings", "effect": "read"},
    "meeting_list_ended": {"description": "查询已结束会议列表。", "method": "GET", "path": "/v1/history/meetings/{open_id}", "effect": "read"},
    "meeting_search": {"description": "搜索用户有权访问的会议。", "method": "GET", "path": "/v1/meetings/search-meetings", "effect": "read"},
    "meeting_invitees_list": {"description": "查询会议受邀者列表。", "method": "GET", "path": "/v1/meetings/{meeting_id}/invitees", "effect": "read"},
    "meeting_invitees_add": {"description": "添加会议受邀者。", "method": "PUT", "path": "/v1/meetings/{meeting_id}/modify-invitees", "effect": "write"},
    "meeting_invitees_remove": {"description": "移除会议受邀者。", "method": "PUT", "path": "/v1/meetings/{meeting_id}/modify-invitees", "effect": "destructive"},
    "meeting_invitees_replace": {"description": "替换会议完整受邀者列表。", "method": "PUT", "path": "/v1/meetings/{meeting_id}/invitees", "effect": "destructive"},
    "record_list": {"description": "查询会议录制列表。", "method": "GET", "path": "/v1/mcp/records", "effect": "read"},
    "record_address": {"description": "获取录制文件下载地址。", "method": "GET", "path": "/v1/mcp/addresses", "effect": "read"},
    "record_smart_minutes": {"description": "获取录制文件智能纪要。", "method": "GET", "path": "/v1/smart/minutes/{record_file_id}", "effect": "read"},
    "record_transcript_get": {"description": "获取录制转写详情。", "method": "GET", "path": "/v1/records/mcp/transcripts/details", "effect": "read"},
    "record_transcript_paragraphs": {"description": "获取录制转写段落。", "method": "GET", "path": "/v1/records/mcp/transcripts/paragraphs", "effect": "read"},
    "record_transcript_search": {"description": "搜索录制转写内容。", "method": "GET", "path": "/v1/records/mcp/transcripts/search", "effect": "read"},
    "record_search": {"description": "按关键词搜索录制文件。", "method": "GET", "path": "/v1/mcp/records/search", "effect": "read"},
    "record_permission_apply_prepare": {"description": "预览录制权限申请信息。", "method": "GET", "path": "/v1/records/mcp/permission-apply/prepare", "effect": "read"},
    "record_permission_apply_commit": {"description": "提交录制权限申请。", "method": "GET", "path": "/v1/records/mcp/permission-apply/commit", "effect": "write"},
    "report_participants": {"description": "查询会议参会人列表。", "method": "GET", "path": "/v1/meetings/{meeting_id}/participants", "effect": "read"},
    "report_waiting_room_log": {"description": "查询会议等候室成员。", "method": "GET", "path": "/v1/meeting/{meeting_id}/waiting-room", "effect": "read"},
    "report_participants_export": {"description": "导出会议参会人报告。", "method": "POST", "path": "/v1/meetings/export-participants-list", "effect": "write"},
    "report_job_result": {"description": "查询参会人报告导出任务。", "method": "GET", "path": "/v1/export/{job_id}", "effect": "read"},
    "contact_search": {"description": "按姓名、职位或部门搜索企业通讯录成员。", "method": "GET", "path": "/v1/contacts/members/search", "effect": "read"},
    "contact_lookup_by_phone": {"description": "按手机号查找通讯录成员。", "method": "POST", "path": "/v1/contacts/members/lookup-by-phone", "effect": "read"},
    "contact_lookup_by_email": {"description": "按邮箱查找通讯录成员。", "method": "POST", "path": "/v1/contacts/members/lookup-by-email", "effect": "read"},
    "control_call": {"description": "呼叫成员入会，会对目标成员发起邀请。", "method": "POST", "path": "/v1/meetings/{meeting_id}/batch-call", "effect": "write"},
    "control_kick": {"description": "将当前参会成员踢出会议。", "method": "PUT", "path": "/v1/real-control/meetings/{meeting_id}/kickout", "effect": "destructive"},
    "control_waiting_room": {"description": "操作会议等候室成员。", "method": "PUT", "path": "/v1/real-control/meetings/{meeting_id}/waiting-room", "effect": "write"},
    "tshoot_feedback": {"description": "向腾讯会议平台提交工具问题反馈。", "method": "POST", "path": "/v1/api/feedback", "effect": "write"},
}

_OPERATOR_QUERY = {
    "meeting_list", "meeting_search", "meeting_invitees_list", "record_list",
    "record_address", "record_smart_minutes", "record_transcript_get",
    "record_transcript_paragraphs", "record_transcript_search", "record_search",
    "record_permission_apply_prepare", "record_permission_apply_commit",
    "report_participants", "report_waiting_room_log", "contact_search",
}
_OPERATOR_BODY = {
    "meeting_invitees_add", "meeting_invitees_remove", "meeting_invitees_replace",
    "report_participants_export", "contact_lookup_by_phone", "contact_lookup_by_email",
    "control_call", "control_kick", "control_waiting_room", "tshoot_feedback",
}


def _validate_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProgramError("bad_request", f"{name} 必须是对象")
    return value


def _credential_values(values: object) -> dict[str, str]:
    if not isinstance(values, dict):
        raise ProgramError("bad_request", "腾讯会议授权信息格式无效")
    result: dict[str, str] = {}
    for key in ("access_token", "refresh_token", "open_id", "sdk_id"):
        value = values.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 16384:
            raise ProgramError("bad_request", f"腾讯会议授权信息缺少 {key}")
        result[key] = value.strip()
    return result


def _credentials(context: dict[str, Any]) -> dict[str, str]:
    credentials = context.get("credentials")
    if not isinstance(credentials, dict):
        raise ProgramError("authorization_required", "腾讯会议凭据不存在")
    # 工具调用上下文使用凭据 values 的扁平形式；刷新操作则可能传入
    # 包含 values 的完整 credential 对象。
    return _credential_values(credentials.get("values", credentials))


def _json_response(response: httpx.Response, action: str) -> dict[str, Any]:
    if response.status_code in {401, 403}:
        raise ProgramError("authorization_required", "腾讯会议授权已失效，请重新授权")
    if response.status_code == 429:
        raise ProgramError("rate_limited", "腾讯会议请求过于频繁，请稍后重试")
    if response.status_code >= 500:
        raise ProgramError("unavailable", f"腾讯会议{action}服务暂时不可用", retryable=True)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProgramError("external_error", "腾讯会议返回了无效 JSON") from exc
    if not isinstance(payload, dict):
        raise ProgramError("external_error", "腾讯会议返回格式错误")
    if response.status_code >= 400:
        error_info = payload.get("error_info")
        nested_message = error_info.get("message") if isinstance(error_info, dict) else None
        message = payload.get("message") or nested_message
        raise ProgramError("external_error", str(message or f"腾讯会议请求失败（HTTP {response.status_code}）"))
    return payload


def _request_auth(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=8), follow_redirects=False) as client:
            response = client.post(url, json=payload)
    except httpx.RequestError as exc:
        raise ProgramError("unavailable", "腾讯会议授权服务连接失败，请稍后重试", retryable=True) from exc
    result = _json_response(response, "授权")
    response_code = result.get("code")
    if response_code not in {None, 0, "0"}:
        message = result.get("message")
        raise ProgramError("authorization_required", str(message or "腾讯会议授权失败"))
    return result


def _configuration(context: dict[str, Any]) -> tuple[str, str, str]:
    configuration = _validate_object(context.get("configuration"), "configuration")
    public = _validate_object(configuration.get("public"), "configuration.public")
    secrets_config = _validate_object(
        configuration.get("secret"), "configuration.secret"
    )
    corp_id = public.get("corp_id")
    sdk_id = public.get("sdk_id")
    app_secret = secrets_config.get("secret")
    return (
        corp_id.strip() if isinstance(corp_id, str) else "",
        sdk_id.strip() if isinstance(sdk_id, str) else "",
        app_secret.strip() if isinstance(app_secret, str) else "",
    )


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    corp_id, sdk_id, app_secret = _configuration(context)
    if context.get("require_complete") and not all((corp_id, sdk_id, app_secret)):
        raise ProgramError(
            "bad_request", "请配置腾讯会议第三方应用的企业 ID、应用 ID 和客户密钥"
        )
    return {}


def authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    corp_id, sdk_id, _ = _configuration(context)
    return {
        "identity": {
            "provider": "tencent-meeting",
            "corp_id": corp_id,
            "sdk_id": sdk_id,
            "api": _API_BASE,
        }
    }


def authorization_begin(context: dict[str, Any]) -> dict[str, Any]:
    corp_id, sdk_id, _ = _configuration(context)
    query = urlencode(
        {
            "corp_id": corp_id,
            "sdk_id": sdk_id,
            "redirect_uri": context["redirect_uri"],
            "state": context["state"],
        },
        quote_via=quote,
    )
    return {
        "type": "redirect",
        "authorize_url": f"{_AUTHORIZE_URL}?{query}",
        "private_context": {},
    }


def _token_credential(data: dict[str, Any], sdk_id: str) -> dict[str, Any]:
    values = {
        key: data.get(key)
        for key in ("access_token", "refresh_token", "open_id")
    }
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ProgramError("external_error", "腾讯会议令牌响应缺少必要字段")
    values["sdk_id"] = sdk_id
    expires = data.get("expires")
    credential: dict[str, Any] = {
        "values": values,
        "refresh_expires_at": (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat(),
    }
    if isinstance(expires, (int, float, str)) and str(expires).isdigit():
        timestamp = int(str(expires))
        if timestamp < int(time.time()):
            timestamp = int(time.time()) + int(expires)
        credential["expires_at"] = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    return credential


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    corp_id, sdk_id, app_secret = _configuration(context)
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "oauth_code":
        raise ProgramError("bad_request", "腾讯会议连接器需要 OAuth 授权码")
    auth_code = submission.get("code")
    if not isinstance(auth_code, str) or not auth_code:
        raise ProgramError("bad_request", "腾讯会议 OAuth 授权码无效")
    payload = _request_auth(
        _ACCESS_TOKEN_URL,
        {"sdk_id": sdk_id, "secret": app_secret, "auth_code": auth_code},
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ProgramError("external_error", "腾讯会议令牌响应格式错误")
    credential = _token_credential(data, sdk_id)
    scopes = data.get("scopes")
    granted_scopes = (
        [scope for scope in scopes if isinstance(scope, str)]
        if isinstance(scopes, list)
        else []
    )
    return {
        "external_account_id": credential["values"]["open_id"],
        "external_account_name": "腾讯会议用户",
        "credential": credential,
        "granted_scopes": granted_scopes,
        "public_metadata": {
            "api_endpoint": _API_BASE,
            "corp_id": corp_id,
            "open_corp_id": data.get("open_corp_id"),
        },
    }


def credential_refresh(context: dict[str, Any]) -> dict[str, Any]:
    _, sdk_id, _ = _configuration(context)
    credential = context.get("credential")
    if isinstance(credential, dict):
        credentials = _credential_values(credential.get("values", credential))
    else:
        credentials = _credentials(context)
    payload = _request_auth(
        _REFRESH_TOKEN_URL,
        {
            "refresh_token": credentials["refresh_token"],
            "sdk_id": sdk_id,
            "open_id": credentials["open_id"],
        },
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ProgramError("external_error", "腾讯会议刷新令牌响应格式错误")
    return {"credential": _token_credential(data, sdk_id)}


def _api_headers(credentials: dict[str, str]) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "AccessToken": credentials["access_token"],
        "OpenId": credentials["open_id"],
        "X-TC-Nonce": str(secrets.randbelow(2_147_483_646) + 1),
        "X-TC-Timestamp": str(int(time.time())),
    }


def _path_fields(path: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(path) if field}


def _timestamp(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        raise ProgramError("bad_request", "时间参数必须包含时区")
    return str(int(parsed.timestamp()))


def _normalize_arguments(command: str, params: dict[str, Any]) -> None:
    # Skill 文档使用 start/end；开放 API 按命令分别使用时间戳字段或 from/to。
    if "start" in params:
        target = "from" if command in {"meeting_search", "record_search"} else "start_time"
        params.setdefault(target, params.pop("start"))
    if "end" in params:
        target = "to" if command in {"meeting_search", "record_search"} else "end_time"
        params.setdefault(target, params.pop("end"))
    if command not in {"meeting_search", "record_search"}:
        for key in ("start_time", "end_time", "until_date"):
            if key in params:
                params[key] = _timestamp(params[key])


def _invoke(command: str, arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    spec = _COMMANDS[command]
    params = dict(arguments)
    _normalize_arguments(command, params)
    path = spec["path"]
    for field in _path_fields(path):
        value = params.pop(field, None)
        if value is None and field == "open_id":
            value = credentials["open_id"]
        if value is None:
            raise ProgramError("bad_request", f"缺少必填参数：{field}")
        path = path.replace("{" + field + "}", str(value))
    if command in _OPERATOR_QUERY:
        params.setdefault("operator_id", credentials["open_id"])
        params.setdefault("operator_id_type", "2")
    if command in _OPERATOR_BODY:
        params.setdefault("operator_id", credentials["open_id"])
        params.setdefault("operator_id_type", 2)
        params.setdefault("instanceid", 1)
    if command == "meeting_cancel":
        params.setdefault("userid", credentials["open_id"])
        params.setdefault("reason_code", 0)
        params.setdefault("instanceid", 1)
    if command in {"meeting_list", "meeting_invitees_list"}:
        params.setdefault("userid", credentials["open_id"])
        params.setdefault("instanceid", 1)
    if command == "meeting_list_ended":
        params.setdefault("userid", credentials["open_id"])
    if command in {"meeting_get", "meeting_update"}:
        params.pop("meeting_code", None)
    method = spec["method"]
    headers = _api_headers(credentials)
    try:
        with httpx.Client(timeout=httpx.Timeout(30, connect=8), follow_redirects=False) as client:
            response = client.request(
                method,
                f"{_API_BASE}{path}",
                headers=headers,
                params=params if method == "GET" else None,
                json=params if method != "GET" else None,
            )
    except httpx.RequestError as exc:
        raise ProgramError("unavailable", "腾讯会议 API 连接失败，请稍后重试", retryable=True) from exc
    return _json_response(response, command)


def tools_discover(_context: dict[str, Any]) -> dict[str, Any]:
    tools = []
    for name, spec in _COMMANDS.items():
        tools.append({
            "key": name,
            "upstream_name": name,
            "description": spec["description"],
            "input_schema": _schema("官方 API 参数；字段名称与腾讯会议开放 API 保持一致。"),
            "effect": spec["effect"],
            "retry_policy": "safe" if spec["effect"] == "read" else "never",
            "confirmation": "not_required" if spec["effect"] == "read" else "user_required",
        })
    return {"tools": tools}


def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("tool_name")
    if not isinstance(command, str) or command not in _COMMANDS:
        raise ProgramError("action_forbidden", "腾讯会议工具不存在或未获清单授权")
    arguments = _validate_object(context.get("arguments", {}), "arguments")
    credentials = _credentials(context)
    payload = _invoke(command, arguments, credentials)
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structured_content": payload,
        "is_error": False,
    }


_OPERATIONS = {
    "configuration_validate": configuration_validate,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "authorization_complete": authorization_complete,
    "credential_refresh": credential_refresh,
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
        response = {"protocol_version": 1, "ok": False, "error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable}}
    except Exception:
        response = {"protocol_version": 1, "ok": False, "error": {"code": "external_error", "message": "连接器程序执行失败", "retryable": False}}
    json.dump(response, sys.stdout, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    main()
