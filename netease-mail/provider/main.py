import base64
import binascii
import hashlib
import imaplib
import json
import re
import signal
import smtplib
import ssl
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, make_msgid
from pathlib import Path
from typing import Any
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parent
_PRESETS = json.loads((_ROOT / "presets.json").read_text())
_CATALOG = json.loads((_ROOT / "tools.json").read_text())
_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_SOCKET_TIMEOUT = 8
_NETEASE_DOMAINS = {
    "163.com",
    "vip.163.com",
    "126.com",
    "vip.126.com",
    "188.com",
    "vip.188.com",
    "yeah.net",
}
_TOOL_POLICIES = {
    "check": ("read", "safe", "not_required"),
    "search": ("read", "safe", "not_required"),
    "fetch": ("read", "safe", "not_required"),
    "download": ("read", "safe", "not_required"),
    "list_mailboxes": ("read", "safe", "not_required"),
    "test_connection": ("read", "safe", "not_required"),
    "mark_read": ("write", "never", "not_required"),
    "mark_unread": ("write", "never", "not_required"),
    "send": ("write", "never", "user_required"),
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _credentials(values: Any) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(values, dict):
        raise ProgramError("authorization_required", "请填写邮箱地址和授权码")
    email = values.get("email")
    password = values.get("authorization_code")
    if not all(isinstance(value, str) and value.strip() for value in (email, password)):
        raise ProgramError("authorization_required", "请填写邮箱地址和授权码")
    email, password = email.strip(), password.strip()
    if len(email) > 320 or len(password) > 4096:
        raise ProgramError("bad_request", "邮箱地址或授权码长度超过限制")
    if any(char in password for char in "\r\n\x00"):
        raise ProgramError("bad_request", "授权码不能包含换行或空字符")
    if not re.fullmatch(r"[^@\s<>\"\\]+@[^@\s]+", email) or not email.isascii():
        raise ProgramError("bad_request", "请填写完整邮箱地址")
    local, domain = email.rsplit("@", 1)
    domain = domain.lower()
    if domain not in _PRESETS:
        raise ProgramError("bad_request", "该邮箱域名没有预设的 IMAP/SMTP 服务器")
    return f"{local}@{domain}", password, _PRESETS[domain]


def _validate(value: Any, schema: dict[str, Any], path: str = "arguments") -> None:
    expected = schema["type"]
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "boolean": bool,
    }
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
    elif expected == "string":
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", sys.maxsize
        ):
            raise ProgramError("bad_request", f"{path} 长度超出允许范围")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ProgramError("bad_request", f"{path} 格式错误")
    elif expected == "integer":
        if value < schema["minimum"] or value > schema["maximum"]:
            raise ProgramError("bad_request", f"{path} 数值超出允许范围")


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


def _imap_ok(response: tuple[str, list], operation: str) -> list:
    status, data = response
    if status != "OK":
        detail = " ".join(
            item.decode("utf-8", errors="replace")
            for item in data
            if isinstance(item, bytes)
        )
        raise ProgramError("external_error", f"{operation} 失败：{detail}")
    return data


def _imap_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@contextmanager
def _imap_session(email: str, password: str, preset: dict[str, Any]):
    client = imaplib.IMAP4_SSL(
        preset["imapHost"],
        preset["imapPort"],
        ssl_context=ssl.create_default_context(),
        timeout=_SOCKET_TIMEOUT,
    )
    try:
        try:
            client.login(_imap_quote(email), password)
        except imaplib.IMAP4.abort:
            raise
        except imaplib.IMAP4.error as exc:
            raise ProgramError(
                "authorization_required",
                "IMAP 认证失败，请检查授权码及 IMAP 服务是否已开启",
            ) from exc
        if email.rsplit("@", 1)[1] in _NETEASE_DOMAINS:
            # Python 3.12 未提供 ID 方法；网易需要客户端声明身份。
            imaplib.Commands["ID"] = ("AUTH",)
            _imap_ok(
                client._simple_command(
                    "ID", '("name" "poco" "version" "1.0.0" "vendor" "poco")'
                ),
                "IMAP ID",
            )
        yield client
    finally:
        # 直接关闭连接，不使用可能清除已删除邮件的 CLOSE/EXPUNGE。
        client.shutdown()


@contextmanager
def _smtp_session(email: str, password: str, preset: dict[str, Any]):
    tls_context = ssl.create_default_context()
    if preset["secure"]:
        client = smtplib.SMTP_SSL(
            preset["smtpHost"],
            preset["smtpPort"],
            timeout=_SOCKET_TIMEOUT,
            context=tls_context,
        )
    else:
        client = smtplib.SMTP(
            preset["smtpHost"], preset["smtpPort"], timeout=_SOCKET_TIMEOUT
        )
    try:
        if not preset["secure"]:
            client.starttls(context=tls_context)
        client.login(email, password)
        yield client
    finally:
        # DATA 成功后 QUIT 失败不能把已发送邮件报告为需要重发。
        client.close()


def _encode_mailbox(name: str) -> str:
    def encode(match: re.Match) -> str:
        encoded = base64.b64encode(match[0].encode("utf-16-be")).decode()
        return "&" + encoded.rstrip("=").replace("/", ",") + "-"

    return re.sub(r"[^\x20-\x7e]+", encode, name.replace("&", "&-"))


def _decode_mailbox(name: str) -> str:
    def decode(match: re.Match) -> str:
        encoded = match[1]
        if not encoded:
            return "&"
        encoded = encoded.replace(",", "/")
        return base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), validate=True
        ).decode("utf-16-be")

    return re.sub(r"&([^-]*)-", decode, name)


def _select(client: imaplib.IMAP4_SSL, mailbox: str, *, readonly: bool = True) -> None:
    _imap_ok(
        client.select(_imap_quote(_encode_mailbox(mailbox)), readonly=readonly),
        "打开邮箱文件夹",
    )


def _list_mailboxes(client: imaplib.IMAP4_SSL) -> dict[str, Any]:
    boxes = []
    quoted = rb'"((?:[^"\\]|\\.)*)"'
    pattern = rb"\(([^)]*)\) (NIL|" + quoted + rb") (.+)"
    for row in _imap_ok(client.list(), "列出邮箱文件夹"):
        # imaplib 在 LIST literal 后保留一个空的行尾片段。
        if row is None or row == b"":
            continue
        metadata, literal = row if isinstance(row, tuple) else (row, None)
        match = re.fullmatch(pattern, metadata)
        if match is None:
            raise ProgramError("external_error", "IMAP 返回了无效的文件夹列表")
        raw_name = literal if literal is not None else match[4]
        if literal is None and raw_name.startswith(b'"'):
            raw_name = re.sub(rb"\\(.)", rb"\1", raw_name[1:-1])
        delimiter = match[3]
        boxes.append(
            {
                "name": _decode_mailbox(raw_name.decode("ascii")),
                "delimiter": re.sub(rb"\\(.)", rb"\1", delimiter).decode("ascii")
                if delimiter is not None
                else None,
                "attributes": match[1].decode("ascii").split(),
            }
        )
    return {"mailboxes": boxes}


def _search_uids(
    client: imaplib.IMAP4_SSL, arguments: dict[str, Any], since: datetime | None
) -> list[int]:
    criteria = []
    for option in ("unseen", "seen"):
        if arguments.get(option):
            criteria.append(option.upper())
    if since is not None:
        # SEARCH SINCE 只有日期精度；留出时区边界，再用 INTERNALDATE 精确筛选。
        day = since - timedelta(days=1)
        months = (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        )
        criteria.extend(["SINCE", f"{day.day:02d}-{months[day.month - 1]}-{day.year}"])
    criteria = criteria or ["ALL"]
    filters = [
        (key.upper(), arguments[key]) for key in ("from", "subject") if key in arguments
    ]
    matches = None
    # imaplib 每条命令支持一个 literal；多个文本条件分别搜索后取交集。
    for key, value in filters or [(None, None)]:
        terms = list(criteria)
        if key is not None:
            client.literal = value.encode("utf-8")
            terms.append(key)
        charset = ["CHARSET", "UTF-8"] if key is not None else []
        data = _imap_ok(client.uid("SEARCH", *charset, *terms), "搜索邮件")
        found = {int(uid) for row in data if row for uid in row.split()}
        matches = found if matches is None else matches & found
    return sorted(matches)


def _metadata(row: bytes) -> dict[str, Any]:
    uid = re.search(rb"\bUID (\d+)\b", row)
    received = imaplib.Internaldate2tuple(row)
    if uid is None or received is None:
        raise ProgramError("external_error", "邮件缺少 UID 或服务器收信时间")
    return {
        "uid": int(uid[1]),
        "received_at": datetime.fromtimestamp(time.mktime(received), timezone.utc),
        "flags": [flag.decode("ascii") for flag in imaplib.ParseFlags(row)],
    }


def _fetch_messages(
    client: imaplib.IMAP4_SSL, uids: list[int]
) -> dict[int, tuple[EmailMessage, dict]]:
    data = _imap_ok(
        client.uid(
            "FETCH", ",".join(map(str, uids)), "(UID FLAGS INTERNALDATE BODY.PEEK[])"
        ),
        "读取邮件",
    )
    messages = {}
    for index, row in enumerate(data):
        if isinstance(row, tuple):
            # 服务器可以把 UID/FLAGS/INTERNALDATE 放在正文 literal 之后。
            if index + 1 >= len(data) or not isinstance(data[index + 1], bytes):
                raise ProgramError("external_error", "邮件正文响应缺少结束片段")
            metadata = _metadata(row[0] + b" " + data[index + 1])
            messages[metadata["uid"]] = (
                BytesParser(policy=policy.default).parsebytes(row[1]),
                metadata,
            )
    if set(uids) - messages.keys():
        raise ProgramError(
            "external_error", "邮件 UID 不存在或邮件已被移走，请重新查询"
        )
    return messages


def _attachment_parts(message: EmailMessage) -> list[EmailMessage]:
    if (
        message.get_content_disposition() == "attachment"
        or message.get_filename()
        or message.get("Content-ID")
    ):
        return [message]
    return [part for child in message.iter_parts() for part in _attachment_parts(child)]


def _attachment_bytes(part: EmailMessage) -> bytes:
    if part.get_content_type() == "message/rfc822":
        return part.get_payload(0).as_bytes(policy=policy.SMTP)
    if part.is_multipart():
        return part.as_bytes(policy=policy.SMTP)
    return part.get_payload(decode=True)


def _attachment_info(part: EmailMessage) -> dict[str, Any]:
    return {
        "filename": part.get_filename(),
        "content_type": part.get_content_type(),
        "size": len(_attachment_bytes(part)),
    }


def _message_result(message: EmailMessage, metadata: dict[str, Any]) -> dict[str, Any]:
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    text = plain.get_content() if plain is not None else None
    return {
        "uid": metadata["uid"],
        "from": str(message["From"]) if message["From"] is not None else None,
        "to": str(message["To"]) if message["To"] is not None else None,
        "subject": str(message["Subject"]) if message["Subject"] is not None else None,
        "date": str(message["Date"]) if message["Date"] is not None else None,
        "received_at": metadata["received_at"].isoformat(),
        "text": text,
        "html": html.get_content() if html is not None else None,
        "snippet": text[:200] if text is not None else None,
        "flags": metadata["flags"],
        "attachments": [_attachment_info(part) for part in _attachment_parts(message)],
    }


def _read_messages(
    client: imaplib.IMAP4_SSL, arguments: dict[str, Any], default_limit: int
) -> dict[str, Any]:
    since = None
    if "recent" in arguments:
        recent = arguments["recent"]
        seconds = int(recent[:-1]) * {"m": 60, "h": 3600, "d": 86400}[recent[-1]]
        try:
            since = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        except OverflowError as exc:
            raise ProgramError("bad_request", "recent 时间范围过大") from exc
    uids = _search_uids(client, arguments, since)
    if not uids:
        return {"messages": []}
    data = _imap_ok(
        client.uid("FETCH", ",".join(map(str, uids)), "(UID FLAGS INTERNALDATE)"),
        "读取邮件索引",
    )
    metadata = [_metadata(row) for row in data if isinstance(row, bytes)]
    selected = sorted(
        (item for item in metadata if since is None or item["received_at"] >= since),
        key=lambda item: (item["received_at"], item["uid"]),
        reverse=True,
    )[: arguments.get("limit", default_limit)]
    if not selected:
        return {"messages": []}
    messages = _fetch_messages(client, [item["uid"] for item in selected])
    return {"messages": [_message_result(*messages[item["uid"]]) for item in selected]}


def _download(message: EmailMessage, arguments: dict[str, Any]) -> dict[str, Any]:
    attachments, resources = [], []
    for index, part in enumerate(_attachment_parts(message), 1):
        if "file" in arguments and part.get_filename() != arguments["file"]:
            continue
        info = _attachment_info(part)
        uri = f"netease-mail://attachment/{arguments['uid']}/{index}"
        attachments.append({**info, "uri": uri})
        resources.append(
            {
                "type": "resource",
                "uri": uri,
                "mime_type": info["content_type"],
                "data": base64.b64encode(_attachment_bytes(part)).decode("ascii"),
            }
        )
    if "file" in arguments and not attachments:
        raise ProgramError("bad_request", "该邮件中没有指定名称的附件")
    return _tool_result(
        {"uid": arguments["uid"], "attachments": attachments}, resources
    )


def _mark(
    client: imaplib.IMAP4_SSL, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    uids = arguments["uids"]
    # UID STORE 会静默忽略不存在的 UID，写前先确认目标仍存在。
    data = _imap_ok(
        client.uid("SEARCH", None, "UID", ",".join(map(str, uids))), "检查邮件 UID"
    )
    existing = {int(uid) for row in data if row for uid in row.split()}
    if set(uids) != existing:
        raise ProgramError("bad_request", "部分邮件 UID 不存在，请重新查询")
    action = "+FLAGS" if name == "mark_read" else "-FLAGS"
    data = _imap_ok(
        client.uid("STORE", ",".join(map(str, uids)), action, r"(\Seen)"), "标记邮件"
    )
    changed = set()
    for row in data:
        if isinstance(row, bytes):
            match = re.search(rb"\bUID (\d+)\b", row)
            if match and (b"\\Seen" in imaplib.ParseFlags(row)) == (
                name == "mark_read"
            ):
                changed.add(int(match[1]))
    if changed != set(uids):
        raise ProgramError(
            "external_error", "未确认全部邮件的标记结果，请重新查询状态；不要自动重试"
        )
    return {"uids": uids, "action": name}


def _build_message(
    email: str, arguments: dict[str, Any]
) -> tuple[EmailMessage, list[str]]:
    message = EmailMessage()
    message["From"] = arguments.get("from", email)
    message["To"] = arguments["to"]
    for key in ("cc", "bcc"):
        if key in arguments:
            message[key] = arguments[key]
    recipients = []
    for key in ("From", "To", "Cc", "Bcc"):
        header = message[key]
        if header is None:
            continue
        if (
            header.defects
            or not header.addresses
            or any(not address.domain for address in header.addresses)
        ):
            raise ProgramError("bad_request", f"{key} 邮箱地址格式错误")
        if key == "From" and len(header.addresses) != 1:
            raise ProgramError("bad_request", "只允许一个发件人地址")
        if key != "From":
            recipients.extend(address.addr_spec for address in header.addresses)
    message["Subject"] = arguments["subject"]
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = make_msgid(domain=email.rsplit("@", 1)[1])
    message.set_content(
        arguments.get("body", ""), subtype="html" if arguments.get("html") else "plain"
    )
    for attachment in arguments.get("attachments", []):
        try:
            content = base64.b64decode(attachment["data"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ProgramError(
                "bad_request", "附件 data 必须是有效的标准 Base64 编码"
            ) from exc
        maintype, subtype = attachment["mime_type"].split("/", 1)
        message.add_attachment(
            content, maintype=maintype, subtype=subtype, filename=attachment["filename"]
        )
    return message, list(dict.fromkeys(recipients))


def _send(
    email: str, password: str, preset: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    message, recipients = _build_message(email, arguments)
    with _smtp_session(email, password, preset) as client:
        refused = client.send_message(message, to_addrs=recipients)
    result = {
        "message_id": str(message["Message-ID"]),
        "accepted": [address for address in recipients if address not in refused],
        "refused": [
            {
                "address": address,
                "code": code,
                "message": reason.decode("utf-8", errors="replace"),
            }
            for address, (code, reason) in refused.items()
        ],
    }
    error = None
    if refused:
        error = {
            "code": "external_error",
            "message": "部分收件人被拒绝；已接受的收件人可能已收到邮件，请勿重复整封发送",
            "retryable": False,
        }
    return _tool_result(result, error=error)


def _check_connection(
    email: str, password: str, preset: dict[str, Any]
) -> dict[str, Any]:
    with _imap_session(email, password, preset) as client:
        _select(client, "INBOX")
    with _smtp_session(email, password, preset):
        pass
    return {"email": email, "imap": "connected", "smtp": "connected"}


def _tool_result(
    data: dict[str, Any], resources: list | None = None, *, error: dict | None = None
) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": json.dumps(data, ensure_ascii=False)},
            *(resources or []),
        ],
        "structured_content": data,
        "is_error": error is not None,
        "error": error,
    }


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    configuration = context.get("configuration", {})
    if (
        not isinstance(configuration, dict)
        or set(configuration) - {"public", "secret"}
        or any(not isinstance(value, dict) or value for value in configuration.values())
    ):
        raise ProgramError("bad_request", "网易邮箱连接器没有管理员配置项")
    return {}


def authorization_identity(_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": {"service": "netease-mail", "authorization_contract_version": "1"}
    }


def authorization_begin(_context: dict[str, Any]) -> dict[str, Any]:
    return {"type": "form"}


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "credentials":
        raise ProgramError("bad_request", "请通过授权表单提交邮箱地址和授权码")
    email, password, preset = _credentials(submission.get("values"))
    _check_connection(email, password, preset)
    return {
        "external_account_id": email,
        "external_account_name": email,
        "credential": {"values": {"email": email, "authorization_code": password}},
        "public_metadata": {"email": email},
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
    if arguments.get("unseen") and arguments.get("seen"):
        raise ProgramError("bad_request", "不能同时筛选已读和未读邮件")
    # 风险只取包内策略，不接受参数覆盖。发送确认由 POCO 在调用前绑定并消费。
    email, password, preset = _credentials(context.get("credentials"))
    if name == "send":
        return _send(email, password, preset, arguments)
    if name == "test_connection":
        return _tool_result(_check_connection(email, password, preset))
    with _imap_session(email, password, preset) as client:
        if name == "list_mailboxes":
            return _tool_result(_list_mailboxes(client))
        _select(
            client, arguments.get("mailbox", "INBOX"), readonly=spec["effect"] == "read"
        )
        if name in {"check", "search"}:
            return _tool_result(
                _read_messages(client, arguments, 10 if name == "check" else 20)
            )
        if name in {"mark_read", "mark_unread"}:
            return _tool_result(_mark(client, name, arguments))
        message, metadata = _fetch_messages(client, [arguments["uid"]])[
            arguments["uid"]
        ]
        if name == "download":
            return _download(message, arguments)
        return _tool_result(_message_result(message, metadata))


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
        return {
            key: item
            if value.get("type") == "resource" and key == "data"
            else _redact(item, secrets)
            for key, item in value.items()
        }
    return value


def _timeout(_signum, _frame) -> None:
    raise TimeoutError("连接器调用超时")


def _reject_constant(_value: str) -> None:
    raise ValueError("JSON 不允许非有限数值")


def main() -> None:
    request = None
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(25)
    try:
        raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
        if len(raw) > _MAX_REQUEST_BYTES:
            raise ProgramError(
                "bad_request", "请求超过 POCO 的 2 MiB 上限，请减少正文或附件大小"
            )
        try:
            request = json.loads(raw, parse_constant=_reject_constant)
        except (ValueError, UnicodeError) as exc:
            raise ProgramError("bad_request", "请求必须是有效 JSON") from exc
        response = {"protocol_version": 1, "ok": True, "result": _dispatch(request)}
    except ProgramError as exc:
        response = _failure(exc.code, exc.message)
    except smtplib.SMTPAuthenticationError:
        response = _failure(
            "authorization_required",
            "SMTP 认证失败，请检查授权码及 SMTP 服务是否已开启",
        )
    except (TimeoutError, imaplib.IMAP4.abort, smtplib.SMTPServerDisconnected):
        response = _failure(
            "unavailable",
            "邮箱连接超时或断开；写操作结果可能未知，请先查询状态，勿自动重试",
        )
    except ssl.SSLCertVerificationError:
        response = _failure("unavailable", "邮箱服务器 TLS 证书校验失败")
    except (imaplib.IMAP4.error, smtplib.SMTPException) as exc:
        response = _failure(
            "external_error", f"邮箱服务拒绝操作：{exc}；发送失败时请先确认投递情况"
        )
    except OSError as exc:
        response = _failure(
            "unavailable",
            f"邮箱网络连接失败（{type(exc).__name__}）；写操作请先确认结果",
        )
    except Exception as exc:
        response = _failure("external_error", f"连接器处理失败（{type(exc).__name__}）")
    finally:
        signal.alarm(0)
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
            password = (
                values.get("authorization_code") if isinstance(values, dict) else None
            )
            if isinstance(password, str) and password.strip():
                secret = password.strip()
                secrets = {
                    secret,
                    quote(secret, safe=""),
                    base64.b64encode(secret.encode()).decode(),
                }
                if response["ok"]:
                    if request.get("operation") == "tool_invoke":
                        response["result"] = _redact(response["result"], secrets)
                else:
                    response["error"]["message"] = _redact(
                        response["error"]["message"], secrets
                    )
    if not response["ok"]:
        response["error"]["message"] = response["error"]["message"][:2000]
    output = json.dumps(
        response, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(output.encode()) > _MAX_RESPONSE_BYTES:
        output = json.dumps(
            _failure(
                "external_error",
                "结果超过 POCO 的 1 MiB 上限，请缩小查询范围或选择更小的附件；写操作请先确认结果，勿重复提交",
            ),
            ensure_ascii=False,
        )
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
