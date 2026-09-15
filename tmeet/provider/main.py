from __future__ import annotations

import json
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
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
_CATALOG = json.loads(
    (Path(__file__).resolve().parent / "tools.json").read_text(encoding="utf-8")
)
_TOOLS = {item["key"]: item for item in _CATALOG}
_INVITEE_OPERATIONS = {"add": 1, "remove": 2, "replace": 3}


class ProgramError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:2000]
        self.retryable = retryable


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProgramError("bad_request", f"{name} 必须是对象")
    return value


def _credential_values(values: object) -> dict[str, str]:
    if not isinstance(values, dict):
        raise ProgramError("authorization_required", "腾讯会议授权信息格式无效")
    result: dict[str, str] = {}
    for key in ("access_token", "refresh_token", "open_id", "sdk_id"):
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProgramError("authorization_required", f"腾讯会议授权信息缺少 {key}")
        result[key] = value.strip()
    return result


def _credentials(context: dict[str, Any]) -> dict[str, str]:
    credentials = context.get("credentials")
    if not isinstance(credentials, dict):
        raise ProgramError("authorization_required", "腾讯会议凭据不存在")
    return _credential_values(credentials.get("values", credentials))


def _configuration(context: dict[str, Any]) -> tuple[str, str, str]:
    configuration = _object(context.get("configuration"), "configuration")
    public = _object(configuration.get("public"), "configuration.public")
    secret = _object(configuration.get("secret"), "configuration.secret")
    corp_id = public.get("corp_id")
    sdk_id = public.get("sdk_id")
    app_secret = secret.get("secret")
    return (
        corp_id.strip() if isinstance(corp_id, str) else "",
        sdk_id.strip() if isinstance(sdk_id, str) else "",
        app_secret.strip() if isinstance(app_secret, str) else "",
    )


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    corp_id, sdk_id, app_secret = _configuration(context)
    if context.get("require_complete") and not all((corp_id, sdk_id, app_secret)):
        raise ProgramError(
            "bad_request",
            "请配置腾讯会议第三方应用的企业 ID、应用 ID 和客户密钥",
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
    corp_id, sdk_id, app_secret = _configuration(context)
    if not all((corp_id, sdk_id, app_secret)):
        raise ProgramError("bad_request", "腾讯会议第三方应用配置不完整")
    redirect_uri = context.get("redirect_uri")
    state = context.get("state")
    if not isinstance(redirect_uri, str) or not redirect_uri.startswith("https://"):
        raise ProgramError("bad_request", "腾讯会议 OAuth 回调地址无效")
    if not isinstance(state, str) or not state:
        raise ProgramError("bad_request", "腾讯会议 OAuth state 无效")
    query = urlencode(
        {
            "corp_id": corp_id,
            "sdk_id": sdk_id,
            "redirect_uri": redirect_uri,
            "state": state,
        },
        quote_via=quote,
    )
    return {
        "type": "redirect",
        "authorize_url": f"{_AUTHORIZE_URL}?{query}",
        "private_context": {},
    }


def _json_response(response: httpx.Response, action: str) -> dict[str, Any]:
    if response.status_code in {401, 403}:
        raise ProgramError(
            "authorization_required", "腾讯会议授权已失效，请重新授权"
        )
    if response.status_code == 429:
        raise ProgramError("rate_limited", "腾讯会议请求过于频繁，请稍后重试")
    if response.status_code >= 500:
        raise ProgramError(
            "unavailable", f"腾讯会议{action}服务暂时不可用", retryable=True
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProgramError("external_error", "腾讯会议返回了无效 JSON") from exc
    if not isinstance(payload, dict):
        raise ProgramError("external_error", "腾讯会议返回格式错误")
    error_info = payload.get("error_info")
    error_code = error_info.get("error_code") if isinstance(error_info, dict) else None
    if response.status_code >= 400 or error_code not in {None, 0, "0"}:
        nested_message = error_info.get("message") if isinstance(error_info, dict) else None
        message = payload.get("message") or nested_message
        raise ProgramError(
            "external_error",
            str(message or f"腾讯会议请求失败（HTTP {response.status_code}）"),
        )
    return payload


def _request_auth(url: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20, connect=8), follow_redirects=False
        ) as client:
            response = client.post(url, json=body)
    except httpx.RequestError as exc:
        raise ProgramError(
            "unavailable", "腾讯会议授权服务连接失败，请稍后重试", retryable=True
        ) from exc
    try:
        payload = _json_response(response, "授权")
    except ProgramError as exc:
        if response.status_code in {400, 401, 403}:
            raise ProgramError("authorization_required", exc.message) from exc
        raise
    response_code = payload.get("code")
    if response_code not in {None, 0, "0"}:
        raise ProgramError(
            "authorization_required", str(payload.get("message") or "腾讯会议授权失败")
        )
    return payload


def _token_credential(data: dict[str, Any], sdk_id: str) -> dict[str, Any]:
    values = {key: data.get(key) for key in ("access_token", "refresh_token", "open_id")}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ProgramError("external_error", "腾讯会议令牌响应缺少必要字段")
    values["sdk_id"] = sdk_id
    credential: dict[str, Any] = {
        "values": values,
        "refresh_expires_at": (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat(),
    }
    expires = data.get("expires")
    if isinstance(expires, (int, float, str)) and str(expires).isdigit():
        timestamp = int(str(expires))
        if timestamp < int(time.time()):
            timestamp += int(time.time())
        credential["expires_at"] = datetime.fromtimestamp(
            timestamp, timezone.utc
        ).isoformat()
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
    return {
        "external_account_id": credential["values"]["open_id"],
        "external_account_name": "腾讯会议用户",
        "credential": credential,
        "granted_scopes": (
            [scope for scope in scopes if isinstance(scope, str)]
            if isinstance(scopes, list)
            else []
        ),
        "public_metadata": {
            "api_endpoint": _API_BASE,
            "corp_id": corp_id,
            "open_corp_id": data.get("open_corp_id"),
        },
    }


def credential_refresh(context: dict[str, Any]) -> dict[str, Any]:
    _, sdk_id, _ = _configuration(context)
    credential = context.get("credential")
    credentials = (
        _credential_values(credential.get("values", credential))
        if isinstance(credential, dict)
        else _credentials(context)
    )
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
        "X-TC-Nonce": str(int(time.time() * 1_000_000) + secrets.randbelow(1_000_000)),
        "X-TC-Timestamp": str(int(time.time())),
    }


def _api_request(
    credentials: dict[str, str],
    action: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        with httpx.Client(
            timeout=httpx.Timeout(30, connect=8), follow_redirects=False
        ) as client:
            response = client.request(
                method,
                f"{_API_BASE}{path}",
                headers=_api_headers(credentials),
                params=query,
                json=body,
            )
    except httpx.RequestError as exc:
        raise ProgramError(
            "unavailable", "腾讯会议 API 连接失败，请稍后重试", retryable=True
        ) from exc
    return _json_response(response, action)


def _timestamp(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value:
        raise ProgramError("bad_request", f"{field} 必须是包含时区的 ISO 8601 时间")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProgramError("bad_request", f"{field} 时间格式错误") from exc
    if parsed.tzinfo is None:
        raise ProgramError("bad_request", f"{field} 必须包含时区")
    return int(parsed.timestamp())


def _validate_time_range(arguments: dict[str, Any]) -> None:
    if "start" in arguments and "end" in arguments:
        if _timestamp(arguments["end"], "end") <= _timestamp(arguments["start"], "start"):
            raise ProgramError("bad_request", "end 必须晚于 start")


def _validate_arguments(command: str, arguments: dict[str, Any]) -> dict[str, Any]:
    schema = _TOOLS[command]["input_schema"]
    properties = schema.get("properties", {})
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ProgramError("bad_request", f"不支持的参数：{', '.join(unknown)}")
    missing = [key for key in schema.get("required", []) if key not in arguments]
    if missing:
        raise ProgramError("bad_request", f"缺少必填参数：{', '.join(missing)}")
    if len(arguments) < schema.get("minProperties", 0):
        raise ProgramError("bad_request", "至少需要提供一个要修改的字段")
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and not any(
        all(key in arguments for key in branch.get("required", []))
        for branch in any_of
        if isinstance(branch, dict)
    ):
        groups = [" + ".join(branch.get("required", [])) for branch in any_of]
        raise ProgramError("bad_request", f"必须提供其中一组参数：{'；'.join(groups)}")
    for key, value in arguments.items():
        rule = properties[key]
        expected = rule.get("type")
        if expected == "string":
            if not isinstance(value, str):
                raise ProgramError("bad_request", f"{key} 必须是字符串")
            if len(value) < rule.get("minLength", 0):
                raise ProgramError("bad_request", f"{key} 不能为空")
            if len(value) > rule.get("maxLength", 1_000_000):
                raise ProgramError("bad_request", f"{key} 超过长度限制")
            pattern = rule.get("pattern")
            if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
                raise ProgramError("bad_request", f"{key} 格式错误")
            if rule.get("format") == "date-time":
                _timestamp(value, key)
            if rule.get("format") == "email" and re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+", value
            ) is None:
                raise ProgramError("bad_request", f"{key} 邮箱格式错误")
        elif expected == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ProgramError("bad_request", f"{key} 必须是整数")
            if value < rule.get("minimum", value) or value > rule.get("maximum", value):
                raise ProgramError("bad_request", f"{key} 超出允许范围")
        elif expected == "boolean" and not isinstance(value, bool):
            raise ProgramError("bad_request", f"{key} 必须是布尔值")
        elif expected == "array":
            if not isinstance(value, list):
                raise ProgramError("bad_request", f"{key} 必须是数组")
            if len(value) < rule.get("minItems", 0) or len(value) > rule.get(
                "maxItems", len(value)
            ):
                raise ProgramError("bad_request", f"{key} 数量超出允许范围")
            if not all(isinstance(item, str) and item for item in value):
                raise ProgramError("bad_request", f"{key} 只能包含非空字符串")
            if rule.get("uniqueItems") and len(value) != len(set(value)):
                raise ProgramError("bad_request", f"{key} 不能包含重复值")
            item_rule = rule.get("items", {})
            item_max_length = item_rule.get("maxLength")
            if isinstance(item_max_length, int) and any(
                len(item) > item_max_length for item in value
            ):
                raise ProgramError("bad_request", f"{key} 包含超过长度限制的值")
            item_pattern = item_rule.get("pattern")
            if isinstance(item_pattern, str) and any(
                re.fullmatch(item_pattern, item) is None for item in value
            ):
                raise ProgramError("bad_request", f"{key} 包含格式错误的值")
            if item_rule.get("format") == "email" and any(
                re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", item) is None
                for item in value
            ):
                raise ProgramError("bad_request", f"{key} 包含格式错误的邮箱")
        if "enum" in rule and value not in rule["enum"]:
            raise ProgramError("bad_request", f"{key} 不在允许取值中")
    _validate_time_range(arguments)
    recurring_fields = {"recurring_type", "until_type", "until_count", "until_date"}
    if command == "meeting_create" and recurring_fields.intersection(arguments):
        if arguments.get("meeting_type", 0) != 1:
            raise ProgramError("bad_request", "周期规则参数要求 meeting_type 为 1")
    if command == "meeting_update":
        invitees_set = "invitees" in arguments
        invitees_type_set = "invitees_type" in arguments
        if invitees_set != invitees_type_set:
            raise ProgramError("bad_request", "invitees 和 invitees_type 必须同时提供")
        if "sub_meeting_id" in arguments and recurring_fields.intersection(arguments):
            raise ProgramError(
                "bad_request", "sub_meeting_id 不能与周期规则参数同时使用"
            )
        if "sub_meeting_id" in arguments and arguments.get("meeting_type") != 1:
            raise ProgramError("bad_request", "修改子会议时 meeting_type 必须为 1")
        if (
            recurring_fields.intersection(arguments)
            and arguments.get("meeting_type") != 1
        ):
            raise ProgramError("bad_request", "周期规则参数要求 meeting_type 为 1")
    if command == "control_kick":
        count = sum(
            len(arguments.get(key, []))
            for key in ("users", "sip_users", "pstn_users")
        )
        if count == 0 or count > 20:
            raise ProgramError("bad_request", "踢出成员总数必须为 1 至 20")
    return dict(arguments)


def _invitees(values: list[str]) -> list[dict[str, str]]:
    return [{"userid": value} for value in values]


def _control_users(
    values: list[str], *, special_instance: int | None = None
) -> list[dict[str, Any]]:
    if special_instance is None:
        return [
            {"to_operator_id": value, "to_operator_id_type": 2}
            for value in values
        ]
    return [
        {
            "to_operator_id": value,
            "to_operator_id_type": 4,
            "instanceid": special_instance,
        }
        for value in values
    ]


def _pagination(arguments: dict[str, Any], default_size: int) -> dict[str, Any]:
    return {
        "page_type": 1,
        "page_token": arguments.get("page_token", ""),
        "page_size": arguments.get("page_size", default_size),
    }


def _settings(arguments: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    if "join_type" in arguments:
        settings["only_user_join_type"] = arguments["join_type"]
    if "waiting_room" in arguments:
        settings["auto_in_waiting_room"] = arguments["waiting_room"]
    if "water_mark_type" in arguments:
        water_mark_type = arguments["water_mark_type"]
        if water_mark_type != 2:
            settings["water_mark_type"] = water_mark_type
        settings["allow_screen_shared_watermark"] = water_mark_type != 2
    for source, target in (
        ("audio_watermark", "audio_watermark"),
        ("auto_record_type", "auto_record_type"),
        ("auto_asr", "auto_asr"),
    ):
        if source in arguments:
            settings[target] = arguments[source]
    return settings


def _meeting_create(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    meeting_type = arguments.get("meeting_type", 0)
    body: dict[str, Any] = {
        "subject": arguments["subject"],
        "start_time": str(_timestamp(arguments["start"], "start")),
        "end_time": str(_timestamp(arguments["end"], "end")),
        "password": arguments.get("password", ""),
        "timezone": arguments.get("timezone", ""),
        "meeting_type": meeting_type,
        "type": 0,
        "instanceid": 1,
        "userid": credentials["open_id"],
    }
    if meeting_type == 1:
        recurring_rule: dict[str, Any] = {
            "recurring_type": arguments.get("recurring_type", 0),
            "until_type": arguments.get("until_type", 0),
            "until_count": arguments.get("until_count", 7),
        }
        if "until_date" in arguments:
            recurring_rule["until_date"] = _timestamp(arguments["until_date"], "until_date")
        body["recurring_rule"] = recurring_rule
    settings = _settings(arguments)
    if settings:
        body["settings"] = settings
    if "invitees" in arguments:
        body["invitees"] = _invitees(arguments["invitees"])
    return _api_request(credentials, "创建会议", "POST", "/v1/meetings", body=body)


def _meeting_update(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    meeting_id = quote(arguments.pop("meeting_id"), safe="")
    body: dict[str, Any] = {"userid": credentials["open_id"], "instanceid": 1}
    direct_fields = ("subject", "password", "timezone", "meeting_type")
    for field in direct_fields:
        if field in arguments:
            body[field] = arguments[field]
    for field in ("start", "end"):
        if field in arguments:
            body[f"{field}_time"] = str(_timestamp(arguments[field], field))
    if arguments.get("meeting_type") == 1:
        if "sub_meeting_id" in arguments:
            body["recurring_rule"] = {"sub_meeting_id": arguments["sub_meeting_id"]}
        else:
            recurring_rule: dict[str, Any] = {
                "recurring_type": arguments.get("recurring_type", 0),
                "until_type": arguments.get("until_type", 0),
                "until_count": arguments.get("until_count", 7),
            }
            if "until_date" in arguments:
                recurring_rule["until_date"] = _timestamp(
                    arguments["until_date"], "until_date"
                )
            body["recurring_rule"] = recurring_rule
    settings = _settings(arguments)
    if settings:
        body["settings"] = settings
    if "invitees" in arguments:
        body["invitees"] = _invitees(arguments["invitees"])
        body["invitees_operate_type"] = _INVITEE_OPERATIONS[arguments["invitees_type"]]
    return _api_request(
        credentials, "更新会议", "PUT", f"/v1/meetings/{meeting_id}", body=body
    )


def _meeting_cancel(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    meeting_id = quote(arguments["meeting_id"], safe="")
    body: dict[str, Any] = {
        "userid": credentials["open_id"],
        "reason_code": 0,
        "instanceid": 1,
        "meetingId": arguments["meeting_id"],
        "meeting_type": arguments.get("meeting_type", 0),
    }
    if "sub_meeting_id" in arguments:
        body["sub_meeting_id"] = arguments["sub_meeting_id"]
    return _api_request(
        credentials, "取消会议", "POST", f"/v1/meetings/{meeting_id}/cancel", body=body
    )


def _meeting_get(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    if "meeting_id" in arguments:
        meeting_id = quote(arguments["meeting_id"], safe="")
        query = {
            "instanceid": 1,
            "operator_id": credentials["open_id"],
            "operator_id_type": 2,
        }
        return _api_request(
            credentials,
            "查询会议",
            "GET",
            f"/v1/meetings/{meeting_id}",
            query=query,
        )
    query = {
        "userid": credentials["open_id"],
        "instanceid": 1,
        "meeting_code": arguments["meeting_code"],
    }
    return _api_request(credentials, "查询会议", "GET", "/v1/meetings", query=query)


def _filter_meeting_list(payload: dict[str, Any], start: int, end: int) -> None:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("meeting_info_list"), list):
        return
    filtered = []
    for item in data["meeting_info_list"]:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        try:
            item_start = int(item.get("start_time", 0))
            item_end = int(item.get("end_time", 0))
        except (TypeError, ValueError):
            filtered.append(item)
            continue
        if item_start > 100_000_000_000:
            item_start //= 1000
        if item_end > 100_000_000_000:
            item_end //= 1000
        if start and item_start and item_start < start:
            continue
        if end and item_end and item_end > end:
            continue
        filtered.append(item)
    data["meeting_info_list"] = filtered
    if "meeting_number" in data:
        data["meeting_number"] = len(filtered)


def _meeting_list(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    query = {
        "userid": credentials["open_id"],
        "instanceid": 1,
        **_pagination(arguments, 20),
    }
    start = _timestamp(arguments["start"], "start") if "start" in arguments else 0
    end = _timestamp(arguments["end"], "end") if "end" in arguments else 0
    if start and not arguments.get("page_token"):
        query["pos"] = start
    if "show_all_sub" in arguments:
        query["is_show_all_sub_meetings"] = arguments["show_all_sub"]
    payload = _api_request(credentials, "查询会议列表", "GET", "/v1/meetings", query=query)
    if start or end:
        _filter_meeting_list(payload, start, end)
    return payload


def _meeting_list_ended(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    query = _pagination(arguments, 30)
    if "start" in arguments:
        query["start_time"] = _timestamp(arguments["start"], "start")
    if "end" in arguments:
        query["end_time"] = _timestamp(arguments["end"], "end")
    open_id = quote(credentials["open_id"], safe="")
    return _api_request(
        credentials,
        "查询历史会议",
        "GET",
        f"/v1/history/meetings/{open_id}",
        query=query,
    )


def _meeting_invitees_list(
    arguments: dict[str, Any], credentials: dict[str, str]
) -> dict[str, Any]:
    meeting_id = quote(arguments["meeting_id"], safe="")
    query = {
        "userid": credentials["open_id"],
        "instanceid": 1,
        **_pagination(arguments, 30),
    }
    return _api_request(
        credentials,
        "查询受邀成员",
        "GET",
        f"/v1/meetings/{meeting_id}/invitees",
        query=query,
    )


def _meeting_invitees_change(
    arguments: dict[str, Any], credentials: dict[str, str], operation: str
) -> dict[str, Any]:
    meeting_id = quote(arguments["meeting_id"], safe="")
    if operation == "replace":
        body = {
            "meeting_id": arguments["meeting_id"],
            "userid": credentials["open_id"],
            "instanceid": 1,
            "invitees": _invitees(arguments["invitees"]),
        }
        path = f"/v1/meetings/{meeting_id}/invitees"
    else:
        body = {
            "operator_id": credentials["open_id"],
            "operator_id_type": 2,
            "instanceid": 1,
            f"{'add' if operation == 'add' else 'delete'}_invitees": _invitees(
                arguments["invitees"]
            ),
        }
        path = f"/v1/meetings/{meeting_id}/modify-invitees"
    return _api_request(credentials, "修改受邀成员", "PUT", path, body=body)


def _record_list(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    query = {
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
        **_pagination(arguments, 30),
    }
    for field in ("meeting_id", "meeting_code"):
        if field in arguments:
            query[field] = arguments[field]
    for field in ("start", "end"):
        if field in arguments:
            query[f"{field}_time"] = _timestamp(arguments[field], field)
    return _api_request(credentials, "查询录制", "GET", "/v1/mcp/records", query=query)


def _record_address(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    query = {
        "meeting_record_id": arguments["meeting_record_id"],
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
        **_pagination(arguments, 30),
    }
    return _api_request(credentials, "查询录制地址", "GET", "/v1/mcp/addresses", query=query)


def _record_smart_minutes(
    arguments: dict[str, Any], credentials: dict[str, str]
) -> dict[str, Any]:
    record_file_id = quote(arguments["record_file_id"], safe="")
    query = {
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
        "lang": arguments.get("lang", "default"),
    }
    if "pwd" in arguments:
        query["pwd"] = arguments["pwd"]
    return _api_request(
        credentials,
        "查询智能纪要",
        "GET",
        f"/v1/smart/minutes/{record_file_id}",
        query=query,
    )


def _record_query(
    arguments: dict[str, Any], credentials: dict[str, str], path: str
) -> dict[str, Any]:
    query = {
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
        **arguments,
    }
    return _api_request(credentials, "查询录制内容", "GET", path, query=query)


def _report_query(
    arguments: dict[str, Any], credentials: dict[str, str], *, waiting_room: bool
) -> dict[str, Any]:
    meeting_id = quote(arguments["meeting_id"], safe="")
    query = {
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
        **_pagination(arguments, 100),
    }
    if not waiting_room:
        for field in ("sub_meeting_id",):
            if field in arguments:
                query[field] = arguments[field]
        for field in ("start", "end"):
            if field in arguments:
                query[f"{field}_time"] = _timestamp(arguments[field], field)
    path = (
        f"/v1/meeting/{meeting_id}/waiting-room"
        if waiting_room
        else f"/v1/meetings/{meeting_id}/participants"
    )
    return _api_request(credentials, "查询会议报告", "GET", path, query=query)


def _contact_search(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    query = {
        "username": arguments["username"],
        "job_title": arguments.get("job_title", ""),
        "department_name": arguments.get("department_name", ""),
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
    }
    return _api_request(
        credentials,
        "查询通讯录",
        "GET",
        "/v1/contacts/members/search",
        query=query,
    )


def _contact_lookup(
    arguments: dict[str, Any], credentials: dict[str, str], field: str
) -> dict[str, Any]:
    body = {
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
        f"users_{field}": arguments[f"{field}s"],
    }
    return _api_request(
        credentials,
        "查询通讯录",
        "POST",
        f"/v1/contacts/members/lookup-by-{field}",
        body=body,
    )


def _control_call(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    meeting_id = quote(arguments["meeting_id"], safe="")
    body = {
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
        "users": _control_users(arguments["users"]),
    }
    return _api_request(
        credentials,
        "呼叫成员",
        "POST",
        f"/v1/meetings/{meeting_id}/batch-call",
        body=body,
    )


def _control_kick(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    meeting_id = quote(arguments["meeting_id"], safe="")
    users = _control_users(arguments.get("users", []))
    users.extend(_control_users(arguments.get("sip_users", []), special_instance=9))
    users.extend(_control_users(arguments.get("pstn_users", []), special_instance=0))
    body = {
        "operator_id": credentials["open_id"],
        "operator_id_type": 2,
        "instanceid": 1,
        "allow_rejoin": arguments.get("allow_rejoin", True),
        "users": users,
    }
    return _api_request(
        credentials,
        "踢出成员",
        "PUT",
        f"/v1/real-control/meetings/{meeting_id}/kickout",
        body=body,
    )


def _tshoot_feedback(arguments: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    body = {
        "operator_id": credentials["open_id"],
        "operator_id_type": "2",
        "category": arguments["category"],
        "intent": arguments["intent"],
        "actions_tried": arguments.get("actions_tried", ""),
        "result": arguments.get("result", ""),
        "tool_name": arguments.get("tool_name", ""),
        "error_code": arguments.get("error_code", ""),
        "from_source": "CLI",
    }
    return _api_request(credentials, "提交反馈", "POST", "/v1/api/feedback", body=body)


_HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, str]], dict[str, Any]]] = {
    "meeting_create": _meeting_create,
    "meeting_update": _meeting_update,
    "meeting_cancel": _meeting_cancel,
    "meeting_get": _meeting_get,
    "meeting_list": _meeting_list,
    "meeting_list_ended": _meeting_list_ended,
    "meeting_invitees_list": _meeting_invitees_list,
    "meeting_invitees_add": lambda args, creds: _meeting_invitees_change(
        args, creds, "add"
    ),
    "meeting_invitees_remove": lambda args, creds: _meeting_invitees_change(
        args, creds, "remove"
    ),
    "meeting_invitees_replace": lambda args, creds: _meeting_invitees_change(
        args, creds, "replace"
    ),
    "record_list": _record_list,
    "record_address": _record_address,
    "record_smart_minutes": _record_smart_minutes,
    "record_transcript_get": lambda args, creds: _record_query(
        args, creds, "/v1/records/mcp/transcripts/details"
    ),
    "record_transcript_paragraphs": lambda args, creds: _record_query(
        args, creds, "/v1/records/mcp/transcripts/paragraphs"
    ),
    "record_transcript_search": lambda args, creds: _record_query(
        args, creds, "/v1/records/mcp/transcripts/search"
    ),
    "record_permission_apply_prepare": lambda args, creds: _record_query(
        args, creds, "/v1/records/mcp/permission-apply/prepare"
    ),
    "record_permission_apply_commit": lambda args, creds: _record_query(
        args, creds, "/v1/records/mcp/permission-apply/commit"
    ),
    "report_participants": lambda args, creds: _report_query(
        args, creds, waiting_room=False
    ),
    "report_waiting_room_log": lambda args, creds: _report_query(
        args, creds, waiting_room=True
    ),
    "contact_search": _contact_search,
    "contact_lookup_by_phone": lambda args, creds: _contact_lookup(args, creds, "phone"),
    "contact_lookup_by_email": lambda args, creds: _contact_lookup(args, creds, "email"),
    "control_call": _control_call,
    "control_kick": _control_kick,
    "tshoot_feedback": _tshoot_feedback,
}


def tools_discover(_context: dict[str, Any]) -> dict[str, Any]:
    tools = []
    for item in _CATALOG:
        effect = item["effect"]
        tools.append(
            {
                "key": item["key"],
                "upstream_name": item["key"],
                "description": item["description"],
                "input_schema": item["input_schema"],
                "effect": effect,
                "retry_policy": "safe" if effect == "read" else "never",
                "confirmation": "not_required" if effect == "read" else "user_required",
                "source_revision": "tmeet-cli-v1.0.11",
            }
        )
    return {"tools": tools}


def tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("tool_name")
    if not isinstance(command, str) or command not in _HANDLERS:
        raise ProgramError("action_forbidden", "腾讯会议工具不存在或未获清单授权")
    raw_arguments = _object(context.get("arguments", {}), "arguments")
    arguments = _validate_arguments(command, raw_arguments)
    payload = _HANDLERS[command](arguments, _credentials(context))
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
        response,
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


if __name__ == "__main__":
    main()
