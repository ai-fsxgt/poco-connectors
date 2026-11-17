import base64
import hashlib
import html
import json
import re
import secrets
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

_ROOT = Path(__file__).resolve().parent
_CATALOG = json.loads((_ROOT / "tools.json").read_text(encoding="utf-8"))
_SYSTEM_ID = "km:meeting_new:view"
_TIMEOUT = 20.0
_BEIJING = timezone(timedelta(hours=8))
_LOCATE_PAGE_SIZE = 500
_SECTION_NUMBERS = "一二三四五六七八九十"
_MARKUP = re.compile(r"<[A-Za-z/!][^>]*>|\*\*|^\s*(#+|[-*+])\s")
_NUMBERED = re.compile(r"^\s*(?:(?:\d+|[一二三四五六七八九十]+)\s*[、．]|\d+\.(?!\d))")
_TOOL_POLICIES = {
    "list_meetings": ("read", "safe", "not_required"),
    "search_meetings": ("read", "safe", "not_required"),
    "get_meeting_history": ("read", "safe", "not_required"),
    "list_options": ("read", "safe", "not_required"),
    "list_tracking_items": ("read", "safe", "not_required"),
    "create_meeting": ("write", "never", "user_required"),
    "update_meeting": ("write", "never", "user_required"),
    "delete_meeting": ("destructive", "never", "user_required"),
    "create_tracking_item": ("write", "never", "user_required"),
    "update_tracking_item": ("write", "never", "user_required"),
    "delete_tracking_item": ("destructive", "never", "user_required"),
}
_DICTIONARIES = {
    "meet_types": ("/listMeetTypes", "type"),
    "meet_locations": ("/listMeetLocations", "location"),
    "meet_personnel": ("/listMeetPersonnel", "personnel"),
    "work_types": ("/listWorkTypes", "type"),
    "units": ("/listWorkUnits", "mainUnit"),
    "presenters": ("/listPresenters", "presenterName"),
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _validate(value: Any, schema: dict[str, Any], path: str = "arguments") -> None:
    expected = schema["type"]
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
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


def _base_url(context: dict[str, Any], key: str, label: str) -> str:
    configuration = context.get("configuration")
    public = configuration.get("public") if isinstance(configuration, dict) else None
    value = public.get(key) if isinstance(public, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ProgramError("bad_request", f"管理员需要配置{label}")
    url = value.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ProgramError("bad_request", f"{label}必须是 http(s) URL")
    return url


def _credentials(values: Any) -> tuple[str, str]:
    username = values.get("username") if isinstance(values, dict) else None
    password = values.get("password") if isinstance(values, dict) else None
    if not all(isinstance(item, str) and item.strip() for item in (username, password)):
        raise ProgramError("authorization_required", "请填写会议系统账号和密码")
    return username.strip(), password


def _der_item(der: bytes, offset: int) -> tuple[int, int]:
    length = der[offset + 1]
    start = offset + 2
    if length & 0x80:
        size = length & 0x7F
        length = int.from_bytes(der[start : start + size], "big")
        start += size
    return start, start + length


def _rsa_encrypt(public_key: str, text: str) -> str:
    """PKCS#1 v1.5 encryption, the same scheme as the SSO login page's JSEncrypt."""
    der = base64.b64decode(
        "".join(line for line in public_key.splitlines() if not line.startswith("-----"))
    )
    # SubjectPublicKeyInfo -> AlgorithmIdentifier, BIT STRING -> RSAPublicKey(n, e)
    info_start, _ = _der_item(der, 0)
    _, algorithm_end = _der_item(der, info_start)
    bits_start, _ = _der_item(der, algorithm_end)
    key_start, _ = _der_item(der, bits_start + 1)
    modulus_start, modulus_end = _der_item(der, key_start)
    exponent_start, exponent_end = _der_item(der, modulus_end)
    modulus = int.from_bytes(der[modulus_start:modulus_end], "big")
    exponent = int.from_bytes(der[exponent_start:exponent_end], "big")

    size = (modulus.bit_length() + 7) // 8
    message = text.encode()
    if len(message) > size - 11:
        raise ProgramError("bad_request", "账号或密码过长")
    padding = bytes(secrets.randbelow(255) + 1 for _ in range(size - len(message) - 3))
    block = int.from_bytes(b"\x00\x02" + padding + b"\x00" + message, "big")
    return base64.b64encode(pow(block, exponent, modulus).to_bytes(size, "big")).decode()


def _payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _unauthorized(response: httpx.Response) -> bool:
    payload = _payload(response)
    return response.status_code == 401 or (
        isinstance(payload, dict) and payload.get("code") == 401
    )


def _meeting_data(response: httpx.Response) -> Any:
    if response.status_code >= 500:
        raise ProgramError("unavailable", f"会议系统服务异常（HTTP {response.status_code}）")
    payload = _payload(response)
    if not isinstance(payload, dict):
        raise ProgramError(
            "external_error", f"会议系统返回了非 JSON 响应（HTTP {response.status_code}）"
        )
    if payload.get("code") not in (200, 0):
        raise ProgramError("external_error", f"会议系统返回错误：{payload.get('msg')}")
    return payload.get("data")


class _MeetingClient:
    """Meeting API client that signs in through SSO when the system answers 401."""

    def __init__(self, context: dict[str, Any], credentials: Any) -> None:
        self._base_url = _base_url(context, "meeting_base_url", "会议系统地址")
        self._username, self._password = _credentials(credentials)
        self._http = httpx.Client(timeout=_TIMEOUT, headers={"systemId": _SYSTEM_ID})
        self._user: dict[str, Any] | None = None
        self._dictionaries: dict[str, list[str]] = {}

    def __enter__(self) -> "_MeetingClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._http.close()

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProgramError("unavailable", "会议系统响应超时") from exc
        except httpx.TransportError as exc:
            raise ProgramError(
                "unavailable", f"无法连接会议系统或统一身份认证（{type(exc).__name__}）"
            ) from exc

    def login(self) -> None:
        response = self._send(
            "GET",
            f"{self._base_url}/sso/login",
            params={"back": f"{self._base_url}/index.html", "systemId": _SYSTEM_ID},
        )
        auth_url = response.headers.get("location")
        if response.status_code != 302 or not auth_url:
            raise ProgramError(
                "unavailable", "会议系统没有跳转到统一身份认证，请检查会议系统地址"
            )
        sso = urlsplit(auth_url)
        sso_origin = f"{sso.scheme}://{sso.netloc}"

        key_payload = _payload(self._send("GET", f"{sso_origin}/login/getPublicKey"))
        if not isinstance(key_payload, dict) or key_payload.get("code") != 200:
            raise ProgramError("unavailable", "无法获取统一身份认证的登录公钥")
        public_key = key_payload["data"]
        login_payload = _payload(
            self._send(
                "POST",
                f"{sso_origin}/sso/doLogin",
                data={
                    "userName": _rsa_encrypt(public_key, self._username),
                    "password": _rsa_encrypt(public_key, self._password),
                },
            )
        )
        if not isinstance(login_payload, dict) or login_payload.get("code") != 200:
            message = login_payload.get("msg") if isinstance(login_payload, dict) else None
            raise ProgramError("authorization_required", f"统一身份认证登录失败：{message}")
        # SSO redirects back with a ticket; the meeting system then sets its session cookie.
        self._send("GET", auth_url, follow_redirects=True)

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base_url}{path}"
        response = self._send(method, url, **kwargs)
        if _unauthorized(response):
            self.login()
            response = self._send(method, url, **kwargs)
            if _unauthorized(response):
                raise ProgramError(
                    "authorization_required", "重新登录后会议系统仍返回未登录，请重新授权"
                )
        return _meeting_data(response)

    def user(self) -> dict[str, Any]:
        if self._user is None:
            self._user = self.call("POST", "/loginService/getUserInfo", json={})
        return self._user

    def operator(self) -> dict[str, str]:
        user = self.user()
        return {"operatorCard": user["empNo"], "operatorName": user["chn"]}

    def dictionary(self, name: str) -> list[str]:
        if name not in self._dictionaries:
            path, field = _DICTIONARIES[name]
            items = self.call("GET", path)
            self._dictionaries[name] = list(dict.fromkeys(item[field] for item in items))
        return self._dictionaries[name]

    def check_choice(self, value: str, name: str, label: str) -> str:
        if value not in self.dictionary(name):
            raise ProgramError(
                "bad_request",
                f"{label}“{value}”不在会议系统字典中，请先用 list_options 查看可选值",
            )
        return value


def _search(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(context, 'search_base_url', '检索服务地址')}/api/v1/search/do-search"
    try:
        response = httpx.get(url, params=params, timeout=_TIMEOUT)
    except httpx.TimeoutException as exc:
        raise ProgramError("unavailable", "检索服务响应超时") from exc
    except httpx.TransportError as exc:
        raise ProgramError("unavailable", f"无法连接检索服务（{type(exc).__name__}）") from exc
    payload = _payload(response)
    if not isinstance(payload, dict) or payload.get("code") != 200:
        message = payload.get("message") if isinstance(payload, dict) else None
        raise ProgramError(
            "external_error",
            f"检索服务返回错误（HTTP {response.status_code}）：{message}",
        )
    return payload["data"]


def _date(value: str, path: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProgramError("bad_request", f"{path} 不是有效日期") from exc


def _date_range(arguments: dict[str, Any]) -> tuple[str, str] | None:
    if "start_date" not in arguments and "end_date" not in arguments:
        return None
    if "start_date" not in arguments or "end_date" not in arguments:
        raise ProgramError("bad_request", "start_date 和 end_date 需同时传入")
    start = _date(arguments["start_date"], "start_date")
    end = _date(arguments["end_date"], "end_date")
    if start > end:
        raise ProgramError("bad_request", "start_date 不能晚于 end_date")
    return start.isoformat(), end.isoformat()


def _past_date(value: str, path: str) -> str:
    day = _date(value, path)
    if day > datetime.now(_BEIJING).date():
        raise ProgramError("bad_request", f"{path} 不能晚于今天")
    return day.isoformat()


def _html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"</(?:p|li)\s*>|<br\s*/?>", "\n", value)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = (line.strip() for line in text.replace("\r", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


def _plain_text(value: str, path: str) -> str:
    text = value.strip()
    if not text:
        raise ProgramError("bad_request", f"{path} 不能为空")
    if "\n" in text or "\r" in text:
        raise ProgramError("bad_request", f"{path} 不能换行，每个条目单独作为一项")
    if _MARKUP.search(text):
        raise ProgramError("bad_request", f"{path} 只能是纯文本，不能包含 HTML 或 Markdown 标记")
    if _NUMBERED.match(text):
        raise ProgramError("bad_request", f"{path} 不要自带编号，连接器会自动编号")
    return text


def _render_content(sections: list[dict[str, Any]]) -> str:
    if len(sections) > 1 and any("title" not in section for section in sections):
        raise ProgramError("bad_request", "会议内容有多个分节时，每个分节都需要 title")
    paragraphs = []
    for index, section in enumerate(sections):
        if "title" in section:
            title = _plain_text(section["title"], f"sections[{index}].title")
            paragraphs.append(f"{_SECTION_NUMBERS[index]}、{title}")
        for number, item in enumerate(section["items"], 1):
            text = _plain_text(item, f"sections[{index}].items[{number - 1}]")
            paragraphs.append(f"{number}、{text}")
    return "".join(f"<p>{html.escape(text, quote=False)}</p>" for text in paragraphs)


def _names(values: list[str]) -> str:
    return "、".join(value.strip() for value in values)


def _meeting(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "meet_date": row["meetDate"],
        "meet_time": row["meetTime"],
        "meet_type": row["meetClassics"],
        "location": row["meetLocation"],
        "hoster": row["hoster"],
        "recorder": row["recoder"],
        "attendees": row["attender"],
        "absentees": row["absencer"],
        "late": row["later"],
        "content": _html_to_text(row["emphasize"]),
        "works": [_work(work) for work in row.get("works") or []],
        "operator": row.get("operatorName"),
        "updated_at": row.get("updateTime"),
    }


def _work(work: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "id": "id",
        "work_type": "workClassics",
        "content": "workContent",
        "standard": "workStandard",
        "main_unit": "mainUnit",
        "assist_unit": "assistUnit",
        "responser": "responser",
        "complete_date": "complateDate",
        "level": "classLevel",
        "separate": "separate",
        "repeat": "repeatUuid",
        "complete_memo": "complateMemo",
        "attachment": "annexName",
    }
    result = {key: work.get(field) for key, field in fields.items()}
    result["finished"] = work.get("workState") == "1"
    return result


def _page(arguments: dict[str, Any], default_size: int) -> tuple[int, int]:
    return arguments.get("page", 1), arguments.get("page_size", default_size)


def _list_meetings(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    start, end = _date_range(arguments)
    page, size = _page(arguments, 10)
    data = client.call(
        "GET",
        "/listMeetsByPage",
        params={
            "pageSize": size,
            "pageNum": page,
            "start": start,
            "end": end,
            "type": arguments.get("meet_type", ""),
        },
    )
    return {
        "total": data["total"],
        "page": page,
        "meetings": [_meeting(row) for row in data["rows"]],
    }


def _search_meetings(context: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    search_type = arguments.get("search_type", "meet")
    page, size = _page(arguments, 10)
    params = {
        "keyword": arguments["keyword"].strip(),
        "page": page,
        "size": size,
        "order_by": "time",
        "question_type": search_type,
    }
    dates = _date_range(arguments)
    if dates:
        params["meet_start_date"], params["meet_end_date"] = dates
    if "meet_type" in arguments:
        if search_type == "work":
            raise ProgramError("bad_request", "检索督办时请使用 work_type，不能使用 meet_type")
        params["meet_classics"] = arguments["meet_type"]
    if "work_type" in arguments:
        if search_type != "work":
            raise ProgramError("bad_request", "work_type 只能在 search_type 为 work 时使用")
        params["work_classics"] = arguments["work_type"]

    data = _search(context, params)
    results = []
    for item in data["lists"]:
        matched = re.findall(r"<em>(.*?)</em>", item.get("highlight_content") or "")
        results.append(
            {
                "id": item["primary_id"],
                "meet_date": item["meet_date"],
                "meet_time": item["meet_time"],
                "meet_type": item["meet_classics"],
                "location": item["meet_location"],
                "hoster": item["hoster"],
                "recorder": item["recoder"],
                "attendees": item["attender"],
                "labels": item["labels"],
                "content": _html_to_text(item["emphasize"]),
                "matched_terms": list(dict.fromkeys(matched)),
                "works": [
                    {
                        "id": work["primary_id"],
                        "work_type": work["work_classics"],
                        "content": work["work_content"],
                        "standard": work["work_standard"],
                        "main_unit": work["main_unit"],
                        "assist_unit": work["assist_unit"],
                        "responser": work["responser"],
                        "complete_date": work["complete_date"],
                        "finished": work["work_state"] == "1",
                    }
                    for work in item.get("works") or []
                ],
            }
        )
    return {"total": data["total"], "page": page, "results": results}


def _get_meeting_history(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    meeting_id = arguments["meeting_id"]
    records = client.call("GET", "/listMeetHistory", params={"id": meeting_id})
    return {
        "meeting_id": meeting_id,
        "versions": [
            {
                "id": record["id"],
                "operation": record["operation"],
                "recorded_at": record["recordTime"],
                "recorder": record["recorder"],
                "meeting": _meeting(json.loads(record["info"])),
            }
            for record in records
        ],
    }


def _list_options(client: _MeetingClient, _arguments: dict[str, Any]) -> dict[str, Any]:
    return {name: client.dictionary(name) for name in _DICTIONARIES}


def _units(value: str) -> list[str]:
    return [unit for unit in (value or "").split(",") if unit]


def _tracking_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "category": row["category"],
        "presenter": row["presenter"],
        "main_units": _units(row["mainUnit"]),
        "assign_units": _units(row["assignUnit"]),
        "meet_date": row["meetDate"],
        "plan_date": row["planDate"],
        "content": row["content"],
        "actual_date": row["actualDate"],
        "complete_status": row["completeStatus"],
        "status": row["status"],
        "is_tracking": row["isTracking"],
        "attachments": [annex["annexName"] for annex in row.get("eventAnnexes") or []],
        "operator": row["operatorName"],
    }


def _list_tracking_items(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    page, size = _page(arguments, 20)
    params: dict[str, Any] = {"pageSize": size, "pageNum": page}
    if arguments.get("due_only"):
        if set(arguments) - {"due_only", "page", "page_size"}:
            raise ProgramError("bad_request", "due_only 为 true 时不能同时使用其他筛选条件")
        data = client.call("GET", "/listRecentImportantEventsByPage", params=params)
    else:
        dates = _date_range(arguments)
        if dates is None:
            raise ProgramError("bad_request", "请传入计划完成日期范围 start_date 和 end_date")
        params["startDate"], params["endDate"] = dates
        for key, field in (
            ("category", "category"),
            ("presenter", "presenter"),
            ("main_unit", "mainUnit"),
            ("assign_unit", "assignUnit"),
            ("status", "status"),
            ("content", "content"),
        ):
            if key in arguments:
                params[field] = arguments[key]
        data = client.call("GET", "/listImportantEventsByPage", params=params)
    return {
        "total": data["total"],
        "page": page,
        "items": [_tracking_item(row) for row in data["rows"]],
    }


def _apply_meeting_changes(
    client: _MeetingClient, meet: dict[str, Any], arguments: dict[str, Any]
) -> None:
    for key, field, dictionary, label in (
        ("meet_type", "meetClassics", "meet_types", "会议类别"),
        ("location", "meetLocation", "meet_locations", "会议地点"),
        ("hoster", "hoster", "meet_personnel", "主持人"),
        ("recorder", "recoder", "meet_personnel", "记录人"),
    ):
        if key in arguments:
            meet[field] = client.check_choice(arguments[key], dictionary, label)
    if "start_time" in arguments or "end_time" in arguments:
        if "start_time" not in arguments or "end_time" not in arguments:
            raise ProgramError("bad_request", "start_time 和 end_time 需同时传入")
        if arguments["start_time"] >= arguments["end_time"]:
            raise ProgramError("bad_request", "end_time 必须晚于 start_time")
        meet["meetTime"] = f"{arguments['start_time']}-{arguments['end_time']}"
    for key, field in (("attendees", "attender"), ("absentees", "absencer"), ("late", "later")):
        if key in arguments:
            meet[field] = _names(arguments[key])
    if "sections" in arguments:
        meet["emphasize"] = _render_content(arguments["sections"])


def _meeting_form(meet: dict[str, Any], works: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "meet": (None, json.dumps(meet, ensure_ascii=False)),
        "works": (None, json.dumps(works, ensure_ascii=False)),
    }


def _find_meeting(client: _MeetingClient, meeting_id: int, meet_date: str) -> dict[str, Any]:
    day = _date(meet_date, "meet_date").isoformat()
    data = client.call(
        "GET",
        "/listMeetsByPage",
        params={
            "pageSize": _LOCATE_PAGE_SIZE,
            "pageNum": 1,
            "start": day,
            "end": day,
            "type": "",
        },
    )
    for row in data["rows"]:
        if row["id"] == meeting_id:
            return row
    raise ProgramError(
        "bad_request",
        f"{day} 没有 ID 为 {meeting_id} 的会议，请先用 list_meetings 确认会议 ID 和日期",
    )


def _create_meeting(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    meet = {
        "meetDate": _past_date(arguments["meet_date"], "meet_date"),
        "absencer": "",
        "later": "",
    }
    _apply_meeting_changes(client, meet, arguments)
    meet.update(client.operator())
    data = client.call("POST", "/saveMeet", files=_meeting_form(meet, []))
    return {"created": True, "result": data, "meeting": _meeting({"id": None, **meet})}


def _update_meeting(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    if not set(arguments) - {"meeting_id", "meet_date"}:
        raise ProgramError("bad_request", "请至少传入一个要修改的字段")
    row = _find_meeting(client, arguments["meeting_id"], arguments["meet_date"])
    meet = dict(row)
    if "new_meet_date" in arguments:
        meet["meetDate"] = _past_date(arguments["new_meet_date"], "new_meet_date")
    _apply_meeting_changes(client, meet, arguments)
    operator = client.operator()
    meet.update(operator)
    works = [
        {
            **work,
            "meetDate": meet["meetDate"],
            "meetClassics": meet["meetClassics"],
            "parentId": meet["id"],
            **operator,
        }
        for work in row["works"]
    ]
    data = client.call("POST", "/updateMeet", files=_meeting_form(meet, works))
    return {"updated": True, "result": data, "meeting": _meeting(meet)}


def _delete_meeting(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    row = _find_meeting(client, arguments["meeting_id"], arguments["meet_date"])
    data = client.call("POST", "/deleteMeet", json={**row, **client.operator()})
    return {"deleted": True, "result": data, "meeting_id": row["id"]}


def _require_tracking_permission(client: _MeetingClient) -> None:
    allowed = client.call("GET", "/listImportantEventsPermission")
    if client.user()["empNo"] not in allowed:
        raise ProgramError(
            "action_forbidden", "当前账号没有维护重点跟踪事项的权限，需由会议系统管理员授权"
        )


def _form_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def _apply_tracking_changes(
    client: _MeetingClient, event: dict[str, Any], arguments: dict[str, Any]
) -> None:
    if "category" in arguments:
        event["category"] = arguments["category"]
    if "presenter" in arguments:
        event["presenter"] = client.check_choice(arguments["presenter"], "presenters", "提出层级")
    for key, field, label in (
        ("main_units", "mainUnit", "责任单位"),
        ("assign_units", "assignUnit", "协助部门"),
    ):
        if key in arguments:
            units = [client.check_choice(unit, "units", label) for unit in arguments[key]]
            event[field] = ",".join(units)
    for key, field in (
        ("meet_date", "meetDate"),
        ("plan_date", "planDate"),
        ("new_plan_date", "planDate"),
        ("actual_date", "actualDate"),
    ):
        if key in arguments:
            event[field] = _date(arguments[key], key).isoformat()
    for key, field in (("content", "content"), ("complete_status", "completeStatus")):
        if key in arguments:
            event[field] = arguments[key].strip()
    if event["meetDate"] > event["planDate"]:
        raise ProgramError("bad_request", "会议日期不能晚于计划完成日期")


def _save_tracking_item(client: _MeetingClient, event: dict[str, Any]) -> Any:
    event.update(client.operator())
    form = {key: (None, _form_value(value)) for key, value in event.items()}
    return client.call("POST", "/saveImportantEvent", files=form)


def _create_tracking_item(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    _require_tracking_permission(client)
    event = {"id": "", "assignUnit": "", "actualDate": "", "completeStatus": ""}
    _apply_tracking_changes(client, event, arguments)
    data = _save_tracking_item(client, event)
    return {"created": True, "result": data}


def _find_tracking_item(client: _MeetingClient, item_id: int, plan_date: str) -> dict[str, Any]:
    day = _date(plan_date, "plan_date").isoformat()
    data = client.call(
        "GET",
        "/listImportantEventsByPage",
        params={"pageSize": _LOCATE_PAGE_SIZE, "pageNum": 1, "startDate": day, "endDate": day},
    )
    for row in data["rows"]:
        if row["id"] == item_id:
            return row
    raise ProgramError(
        "bad_request",
        f"计划完成日期为 {day} 的事项中没有 ID {item_id}，请先用 list_tracking_items 确认",
    )


def _update_tracking_item(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    changes = {key: value for key, value in arguments.items() if key not in {"id", "plan_date"}}
    if not changes:
        raise ProgramError("bad_request", "请至少传入一个要修改的字段")
    if changes.get("completed") is False:
        raise ProgramError("bad_request", "completed 只能传 true，不标记完成时不传")
    _require_tracking_permission(client)
    event = _find_tracking_item(client, arguments["id"], arguments["plan_date"])
    annexes = event.pop("eventAnnexes") or []
    event["srcAnnexNames"] = [annex["annexName"] for annex in annexes]
    event["annexNames"] = []
    _apply_tracking_changes(client, event, changes)
    if changes.get("completed"):
        if not event["actualDate"] or not event["completeStatus"]:
            raise ProgramError("bad_request", "标记完成前需要填写实际完成日期和完成情况")
        event["status"] = "已完成"
    data = _save_tracking_item(client, event)
    return {"updated": True, "result": data}


def _delete_tracking_item(client: _MeetingClient, arguments: dict[str, Any]) -> dict[str, Any]:
    _require_tracking_permission(client)
    event = _find_tracking_item(client, arguments["id"], arguments["plan_date"])
    payload = {"id": event["id"], "state": True, **client.operator()}
    data = client.call("POST", "/updateImportantEvent", json=payload)
    return {"deleted": True, "result": data, "id": event["id"], "content": event["content"]}


_MEETING_TOOLS = {
    "list_meetings": _list_meetings,
    "get_meeting_history": _get_meeting_history,
    "list_options": _list_options,
    "list_tracking_items": _list_tracking_items,
    "create_meeting": _create_meeting,
    "update_meeting": _update_meeting,
    "delete_meeting": _delete_meeting,
    "create_tracking_item": _create_tracking_item,
    "update_tracking_item": _update_tracking_item,
    "delete_tracking_item": _delete_tracking_item,
}


def _tool_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        "structured_content": None,
        "is_error": False,
        "error": None,
    }


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    _base_url(context, "meeting_base_url", "会议系统地址")
    _base_url(context, "search_base_url", "检索服务地址")
    return {}


def authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    return {"identity": {"meeting_base_url": _base_url(context, "meeting_base_url", "会议系统地址")}}


def authorization_begin(_context: dict[str, Any]) -> dict[str, Any]:
    return {"type": "form"}


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "credentials":
        raise ProgramError("bad_request", "请通过授权表单提交会议系统账号和密码")
    values = submission.get("values")
    username, password = _credentials(values)
    with _MeetingClient(context, values) as client:
        client.login()
        user = client.user()
    if "挂靠人员" in (user.get("post") or ""):
        raise ProgramError("action_forbidden", "该账号没有访问会议系统的权限")
    return {
        "external_account_id": user["empNo"],
        "external_account_name": user["chn"],
        "credential": {"values": {"username": username, "password": password}},
        "public_metadata": {"emp_no": user["empNo"], "post": user.get("post")},
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
    if name == "search_meetings":
        return _tool_result(_search_meetings(context, arguments))
    with _MeetingClient(context, context.get("credentials")) as client:
        return _tool_result(_MEETING_TOOLS[name](client, arguments))


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
        response = _failure(
            "external_error", f"连接器处理失败（{type(exc).__name__}: {exc}）"
        )
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
