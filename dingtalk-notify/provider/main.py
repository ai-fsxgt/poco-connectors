import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

_ROOT = Path(__file__).resolve().parent
_CATALOG = json.loads((_ROOT / "tools.json").read_text())
_API_URL = "https://api.dingtalk.com"
_OAPI_URL = "https://oapi.dingtalk.com"
_TIMEOUT = 15.0
_BATCH_SIZE = 20
_SEARCH_SIZE = 10
_USER_PAGE_SIZE = 100
_USER_NOT_FOUND_ERRCODE = 60121
_DEPARTMENT_OUT_OF_SCOPE_ERRCODE = 50004
_SEARCH_HINT = "请联系管理员确认应用已开通企业通讯录搜索权限"
_MEMBER_HINT = "请联系管理员确认应用已开通成员信息读权限"
_DEPARTMENT_HINT = "请联系管理员确认应用已开通通讯录部门信息读权限"
_MOBILE_HINT = "请联系管理员确认应用已开通根据手机号获取成员基本信息权限"
_CREDENTIAL_KEYS = ("client_id", "client_secret", "inbox_url", "inbox_token")
_TOOL_POLICIES = {
    "find_users": ("read", "safe", "not_required"),
    "find_user_by_mobile": ("read", "safe", "not_required"),
    "find_departments": ("read", "safe", "not_required"),
    "list_sub_departments": ("read", "safe", "not_required"),
    "list_department_users": ("read", "safe", "not_required"),
    "send_message": ("write", "never", "user_required"),
    "list_message_events": ("read", "safe", "not_required"),
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _credentials(values: Any) -> dict[str, str]:
    if not isinstance(values, dict) or not all(
        isinstance(values.get(key), str) and values[key] for key in _CREDENTIAL_KEYS
    ):
        raise ProgramError("authorization_required", "通知机器人凭证不完整，请重新授权")
    return values


def _validate(value: Any, schema: dict[str, Any], path: str = "arguments") -> None:
    expected = schema["type"]
    types = {"object": dict, "array": list, "string": str, "integer": int}
    if type(value) is not types[expected]:
        raise ProgramError("bad_request", f"{path} 必须为 {expected}")
    if expected == "object":
        properties = schema["properties"]
        if set(value) - properties.keys() or set(schema["required"]) - value.keys():
            raise ProgramError("bad_request", f"{path} 含未知参数或缺少必填参数")
        for key, item in value.items():
            _validate(item, properties[key], f"{path}.{key}")
    elif expected == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get(
            "maxItems", sys.maxsize
        ):
            raise ProgramError("bad_request", f"{path} 数量超出允许范围")
        for item in value:
            _validate(item, schema["items"], f"{path}[]")
        if schema.get("uniqueItems") and len(set(value)) != len(value):
            raise ProgramError("bad_request", f"{path} 不能包含重复值")
    elif expected == "integer":
        if value < schema.get("minimum", -sys.maxsize) or value > schema.get(
            "maximum", sys.maxsize
        ):
            raise ProgramError("bad_request", f"{path} 超出允许范围")
    elif expected == "string":
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", sys.maxsize
        ):
            raise ProgramError("bad_request", f"{path} 长度超出允许范围")
        if "enum" in schema and value not in schema["enum"]:
            raise ProgramError("bad_request", f"{path} 取值无效")
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


def _request(service: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
    try:
        return httpx.request(method, url, timeout=_TIMEOUT, **kwargs)
    except httpx.TimeoutException as exc:
        raise ProgramError("unavailable", f"连接{service}超时") from exc
    except httpx.TransportError as exc:
        raise ProgramError(
            "unavailable", f"连接{service}失败（{type(exc).__name__}）"
        ) from exc


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _dingtalk_api(
    access_token: str | None, path: str, body: dict[str, Any], hint: str
) -> dict[str, Any]:
    headers = {"x-acs-dingtalk-access-token": access_token} if access_token else {}
    response = _request("钉钉", "POST", f"{_API_URL}{path}", json=body, headers=headers)
    data = _json(response)
    if response.status_code == 200 and isinstance(data, dict):
        return data
    detail = (
        f"{data.get('code')}：{data.get('message')}"
        if isinstance(data, dict)
        else "无法解析的响应"
    )
    if response.status_code == 429:
        code = "rate_limited"
    elif response.status_code in (401, 403):
        code = "insufficient_scope"
    else:
        code = "external_error"
    raise ProgramError(
        code, f"钉钉返回 HTTP {response.status_code}（{detail}）；{hint}"
    )


def _access_token(credentials: dict[str, str]) -> str:
    data = _dingtalk_api(
        None,
        "/v1.0/oauth2/accessToken",
        {"appKey": credentials["client_id"], "appSecret": credentials["client_secret"]},
        "获取访问令牌失败，请联系管理员检查 IM 机器人的 Client ID 和 Client Secret",
    )
    return data["accessToken"]


def _oapi(
    access_token: str,
    path: str,
    body: dict[str, Any],
    hint: str,
    missing_errcode: int | None = None,
) -> Any:
    response = _request(
        "钉钉",
        "POST",
        f"{_OAPI_URL}{path}",
        params={"access_token": access_token},
        json=body,
    )
    data = _json(response)
    if isinstance(data, dict) and data.get("errcode") == 0:
        return data["result"]
    if (
        missing_errcode is not None
        and isinstance(data, dict)
        and data.get("errcode") == missing_errcode
    ):
        return None
    detail = (
        f"{data['errcode']}：{data.get('errmsg')}"
        if isinstance(data, dict) and "errcode" in data
        else f"HTTP {response.status_code}"
    )
    raise ProgramError("external_error", f"钉钉返回 {detail}；{hint}")


def _department(
    access_token: str, dept_id: int, cache: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    if dept_id not in cache:
        result = _oapi(
            access_token,
            "/topapi/v2/department/get",
            {"dept_id": dept_id, "language": "zh_CN"},
            _DEPARTMENT_HINT,
            missing_errcode=_DEPARTMENT_OUT_OF_SCOPE_ERRCODE,
        )
        cache[dept_id] = {
            "dept_id": dept_id,
            "name": result["name"] if result else None,
            "parent_id": result.get("parent_id") if result else None,
        }
    return cache[dept_id]


def _user_detail(
    access_token: str, user_id: str, departments: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    result = _oapi(
        access_token,
        "/topapi/v2/user/get",
        {"userid": user_id, "language": "zh_CN"},
        _MEMBER_HINT,
    )
    return {
        "user_id": result["userid"],
        "name": result.get("name", ""),
        "title": result.get("title", ""),
        "job_number": result.get("job_number", ""),
        "departments": [
            {
                "dept_id": dept_id,
                "name": _department(access_token, dept_id, departments)["name"],
            }
            for dept_id in result.get("dept_id_list", [])
        ],
    }


def _find_users(access_token: str, arguments: dict[str, Any]) -> dict[str, Any]:
    data = _dingtalk_api(
        access_token,
        "/v1.0/contact/users/search",
        {"queryWord": arguments["name"], "offset": 0, "size": _SEARCH_SIZE},
        _SEARCH_HINT,
    )
    departments: dict[int, dict[str, Any]] = {}
    return {
        "users": [
            _user_detail(access_token, user_id, departments)
            for user_id in data.get("list", [])
        ],
        "total_count": data.get("totalCount", 0),
        "has_more": data.get("hasMore", False),
    }


def _find_user_by_mobile(
    access_token: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    result = _oapi(
        access_token,
        "/topapi/v2/user/getbymobile",
        {"mobile": arguments["mobile"]},
        _MOBILE_HINT,
        missing_errcode=_USER_NOT_FOUND_ERRCODE,
    )
    if result is None:
        return {"user": None}
    return {"user": _user_detail(access_token, result["userid"], {})}


def _find_departments(access_token: str, arguments: dict[str, Any]) -> dict[str, Any]:
    data = _dingtalk_api(
        access_token,
        "/v1.0/contact/departments/search",
        {"queryWord": arguments["name"], "offset": 0, "size": _SEARCH_SIZE},
        _SEARCH_HINT,
    )
    departments: dict[int, dict[str, Any]] = {}
    return {
        "departments": [
            _department(access_token, dept_id, departments)
            for dept_id in data.get("list", [])
        ],
        "total_count": data.get("totalCount", 0),
        "has_more": data.get("hasMore", False),
    }


def _list_sub_departments(
    access_token: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    result = _oapi(
        access_token,
        "/topapi/v2/department/listsub",
        {"dept_id": arguments["dept_id"], "language": "zh_CN"},
        _DEPARTMENT_HINT,
    )
    return {
        "departments": [
            {
                "dept_id": item["dept_id"],
                "name": item["name"],
                "parent_id": item.get("parent_id"),
            }
            for item in result
        ]
    }


def _list_department_users(
    access_token: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    result = _oapi(
        access_token,
        "/topapi/v2/user/list",
        {
            "dept_id": arguments["dept_id"],
            "cursor": arguments.get("cursor", 0),
            "size": _USER_PAGE_SIZE,
            "language": "zh_CN",
        },
        _MEMBER_HINT,
    )
    return {
        "users": [
            {
                "user_id": item["userid"],
                "name": item.get("name", ""),
                "title": item.get("title", ""),
                "job_number": item.get("job_number", ""),
            }
            for item in result.get("list", [])
        ],
        "has_more": result.get("has_more", False),
        "next_cursor": result.get("next_cursor"),
    }


def _send_message(
    credentials: dict[str, str], arguments: dict[str, Any]
) -> dict[str, Any]:
    access_token = _access_token(credentials)
    user_ids = arguments["user_ids"]
    msg_param = json.dumps(
        {"title": arguments["title"], "text": arguments["text"]}, ensure_ascii=False
    )
    batches = []
    for start in range(0, len(user_ids), _BATCH_SIZE):
        chunk = user_ids[start : start + _BATCH_SIZE]
        try:
            data = _dingtalk_api(
                access_token,
                "/v1.0/robot/oToMessages/batchSend",
                {
                    "robotCode": credentials["client_id"],
                    "userIds": chunk,
                    "msgKey": "sampleMarkdown",
                    "msgParam": msg_param,
                },
                "请联系管理员确认应用已开通机器人发送消息权限（qyapi_robot_sendmsg），且收件人在应用可用范围内",
            )
            if not data.get("processQueryKey"):
                raise ProgramError(
                    "external_error",
                    "钉钉响应缺少 processQueryKey，无法确认该批是否已发出",
                )
        except ProgramError as exc:
            if not batches:
                raise
            return _partial_failure(batches, user_ids[start:], exc)
        batches.append(
            {
                "process_query_key": data["processQueryKey"],
                "user_ids": chunk,
                "invalid_user_ids": data.get("invalidStaffIdList", []),
                "filtered_user_ids": data.get("filteredStaffIdList", []),
                "flow_controlled_user_ids": data.get("flowControlledStaffIdList", []),
            }
        )
    return _tool_result({"batches": batches})


def _partial_failure(
    batches: list[dict[str, Any]], unsent_user_ids: list[str], exc: ProgramError
) -> dict[str, Any]:
    data = {"batches": batches, "unsent_user_ids": unsent_user_ids}
    message = (
        f"已发送 {len(batches)} 批，后续批次失败：{exc.message}。"
        "unsent_user_ids 中的人员未确认收到；请求超时时其中第一批可能已发出，重发前先查询已读记录"
    )
    return {
        "content": [
            {"type": "text", "text": json.dumps(data, ensure_ascii=False)},
            {"type": "text", "text": message},
        ],
        "structured_content": data,
        "is_error": True,
        "error": {"code": exc.code, "message": message[:2000], "retryable": False},
    }


def _list_message_events(
    credentials: dict[str, str], arguments: dict[str, Any]
) -> dict[str, Any]:
    params = [("message_ref", ref) for ref in arguments.get("message_refs", [])]
    for name, key in (
        ("event_type", "event_type"),
        ("platform_user_id", "user_id"),
        ("since", "since"),
        ("cursor", "cursor"),
        ("limit", "limit"),
    ):
        if key in arguments:
            params.append((name, str(arguments[key])))
    # The inbox only listens on the Backend host, so proxy settings must not apply.
    response = _request(
        "Poco 收件箱",
        "GET",
        credentials["inbox_url"],
        params=params,
        headers={"Authorization": f"Bearer {credentials['inbox_token']}"},
        trust_env=False,
    )
    data = _json(response)
    if response.status_code != 200 or not isinstance(data, dict):
        detail = (
            data.get("message") or data.get("detail")
            if isinstance(data, dict)
            else "无法解析的响应"
        )
        raise ProgramError(
            "external_error",
            f"查询收件箱失败，HTTP {response.status_code}：{json.dumps(detail, ensure_ascii=False)}",
        )
    return {
        "events": data["data"]["items"],
        "next_cursor": data["data"]["next_cursor"],
    }


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
        raise ProgramError("bad_request", "钉钉消息通知连接器没有管理员配置项")
    return {}


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
    credentials = _credentials(context.get("credentials"))
    if name == "send_message":
        return _send_message(credentials, arguments)
    if name == "list_message_events":
        return _tool_result(_list_message_events(credentials, arguments))
    return _tool_result(_DIRECTORY_TOOLS[name](_access_token(credentials), arguments))


_DIRECTORY_TOOLS = {
    "find_users": _find_users,
    "find_user_by_mobile": _find_user_by_mobile,
    "find_departments": _find_departments,
    "list_sub_departments": _list_sub_departments,
    "list_department_users": _list_department_users,
}


_OPERATIONS = {
    "configuration_validate": configuration_validate,
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
    except Exception as exc:
        response = _failure("external_error", f"连接器处理失败（{type(exc).__name__}）")
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
