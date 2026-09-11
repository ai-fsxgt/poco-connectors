import base64
import hashlib
import hmac
import json
import mimetypes
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

_PROTOCOL_VERSION = 1
_BASE_URL = "https://ima.qq.com"
_SKILL_VERSION = "1.1.9"
_MAX_RESPONSE_BYTES = 900_000
_MAX_FILE_SIZE = 200 * 1024 * 1024

_MEDIA_TYPES = {
    "pdf": (1, "application/pdf", 200 * 1024 * 1024),
    "doc": (3, "application/msword", 200 * 1024 * 1024),
    "docx": (3, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 200 * 1024 * 1024),
    "ppt": (4, "application/vnd.ms-powerpoint", 200 * 1024 * 1024),
    "pptx": (4, "application/vnd.openxmlformats-officedocument.presentationml.presentation", 200 * 1024 * 1024),
    "xls": (5, "application/vnd.ms-excel", 10 * 1024 * 1024),
    "xlsx": (5, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 10 * 1024 * 1024),
    "csv": (5, "text/csv", 10 * 1024 * 1024),
    "md": (7, "text/markdown", 10 * 1024 * 1024),
    "markdown": (7, "text/markdown", 10 * 1024 * 1024),
    "png": (9, "image/png", 30 * 1024 * 1024),
    "jpg": (9, "image/jpeg", 30 * 1024 * 1024),
    "jpeg": (9, "image/jpeg", 30 * 1024 * 1024),
    "webp": (9, "image/webp", 30 * 1024 * 1024),
    "txt": (13, "text/plain", 10 * 1024 * 1024),
    "xmind": (14, "application/x-xmind", 10 * 1024 * 1024),
    "mp3": (15, "audio/mpeg", 200 * 1024 * 1024),
    "m4a": (15, "audio/x-m4a", 200 * 1024 * 1024),
    "wav": (15, "audio/wav", 200 * 1024 * 1024),
    "aac": (15, "audio/aac", 200 * 1024 * 1024),
    "html": (20, "text/html", 10 * 1024 * 1024),
    "epub": (21, "application/epub+zip", 50 * 1024 * 1024),
}

_CONTENT_MEDIA_TYPES = {
    "application/pdf": (1, "application/pdf", 200 * 1024 * 1024),
    "application/msword": (3, "application/msword", 200 * 1024 * 1024),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (3, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 200 * 1024 * 1024),
    "application/vnd.ms-powerpoint": (4, "application/vnd.ms-powerpoint", 200 * 1024 * 1024),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (4, "application/vnd.openxmlformats-officedocument.presentationml.presentation", 200 * 1024 * 1024),
    "application/vnd.ms-excel": (5, "application/vnd.ms-excel", 10 * 1024 * 1024),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (5, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 10 * 1024 * 1024),
    "text/csv": (5, "text/csv", 10 * 1024 * 1024),
    "text/markdown": (7, "text/markdown", 10 * 1024 * 1024),
    "text/x-markdown": (7, "text/x-markdown", 10 * 1024 * 1024),
    "application/md": (7, "application/md", 10 * 1024 * 1024),
    "application/markdown": (7, "application/markdown", 10 * 1024 * 1024),
    "image/png": (9, "image/png", 30 * 1024 * 1024),
    "image/jpeg": (9, "image/jpeg", 30 * 1024 * 1024),
    "image/webp": (9, "image/webp", 30 * 1024 * 1024),
    "text/plain": (13, "text/plain", 10 * 1024 * 1024),
    "application/x-xmind": (14, "application/x-xmind", 10 * 1024 * 1024),
    "application/vnd.xmind.workbook": (14, "application/vnd.xmind.workbook", 10 * 1024 * 1024),
    "application/zip": (14, "application/zip", 10 * 1024 * 1024),
    "audio/mpeg": (15, "audio/mpeg", 200 * 1024 * 1024),
    "audio/x-m4a": (15, "audio/x-m4a", 200 * 1024 * 1024),
    "audio/wav": (15, "audio/wav", 200 * 1024 * 1024),
    "audio/aac": (15, "audio/aac", 200 * 1024 * 1024),
    "text/html": (20, "text/html", 10 * 1024 * 1024),
    "application/epub+zip": (21, "application/epub+zip", 50 * 1024 * 1024),
}

_TOOL_DEFINITIONS = {
    "search_note": {
        "description": "Search the user's IMA notes by title or content.",
        "schema": {
            "type": "object",
            "properties": {
                "search_type": {"type": "integer", "enum": [0, 1]},
                "sort_type": {"type": "integer", "enum": [0, 1, 2, 3]},
                "query_info": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
                    "additionalProperties": False,
                },
                "start": {"type": "integer", "minimum": 0},
                "end": {"type": "integer", "minimum": 1},
            },
            "required": ["start", "end"],
            "additionalProperties": False,
        },
    },
    "list_notebook": {
        "description": "List the user's IMA notebooks.",
        "schema": {
            "type": "object",
            "properties": {
                "cursor": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "version": {"type": "string"},
            },
            "required": ["cursor", "limit"],
            "additionalProperties": False,
        },
    },
    "list_note": {
        "description": "List notes in an IMA notebook or across all notebooks.",
        "schema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string"},
                "sort_type": {"type": "integer", "enum": [0, 1, 2, 3]},
                "cursor": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["cursor", "limit"],
            "additionalProperties": False,
        },
    },
    "get_doc_content": {
        "description": "Read the text content of an IMA note.",
        "schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "minLength": 1},
                "target_content_format": {"type": "integer", "enum": [0, 1, 2]},
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
    },
    "import_doc": {
        "description": "Create a new Markdown note in IMA.",
        "schema": {
            "type": "object",
            "properties": {
                "content_format": {"type": "integer", "enum": [1]},
                "content": {"type": "string", "minLength": 1},
                "folder_id": {"type": "string", "minLength": 1},
                "folder_name": {"type": "string", "minLength": 1},
            },
            "required": ["content_format", "content"],
            "additionalProperties": False,
        },
    },
    "append_doc": {
        "description": "Append Markdown content to an existing IMA note.",
        "schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "minLength": 1},
                "content_format": {"type": "integer", "enum": [1]},
                "content": {"type": "string", "minLength": 1},
            },
            "required": ["note_id", "content_format", "content"],
            "additionalProperties": False,
        },
    },
    "get_knowledge_base": {
        "description": "Get details for one or more IMA knowledge bases.",
        "schema": {
            "type": "object",
            "properties": {"ids": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 20}},
            "required": ["ids"],
            "additionalProperties": False,
        },
    },
    "get_knowledge_list": {
        "description": "List files and folders in an IMA knowledge base.",
        "schema": {
            "type": "object",
            "properties": {
                "knowledge_base_id": {"type": "string", "minLength": 1},
                "cursor": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "folder_id": {"type": "string", "minLength": 1},
            },
            "required": ["knowledge_base_id"],
            "additionalProperties": False,
        },
    },
    "search_knowledge": {
        "description": "Search files and folders in an IMA knowledge base.",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "knowledge_base_id": {"type": "string", "minLength": 1},
                "cursor": {"type": "string"},
            },
            "required": ["query", "knowledge_base_id"],
            "additionalProperties": False,
        },
    },
    "search_knowledge_base": {
        "description": "Search IMA knowledge bases by name; an empty query lists all.",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "cursor": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "get_addable_knowledge_base_list": {
        "description": "List IMA knowledge bases where the user can add content.",
        "schema": {
            "type": "object",
            "properties": {"cursor": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            "additionalProperties": False,
        },
    },
    "check_repeated_names": {
        "description": "Check whether file names already exist in an IMA knowledge base.",
        "schema": {
            "type": "object",
            "properties": {
                "knowledge_base_id": {"type": "string", "minLength": 1},
                "params": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string", "minLength": 1}, "media_type": {"type": "integer"}}, "required": ["name", "media_type"], "additionalProperties": False}, "minItems": 1, "maxItems": 2000},
                "folder_id": {"type": "string", "minLength": 1},
            },
            "required": ["knowledge_base_id", "params"],
            "additionalProperties": False,
        },
    },
    "import_urls": {
        "description": "Add web pages or WeChat articles to an IMA knowledge base.",
        "schema": {
            "type": "object",
            "properties": {
                "knowledge_base_id": {"type": "string", "minLength": 1},
                "folder_id": {"type": "string", "minLength": 1},
                "urls": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 10},
            },
            "required": ["knowledge_base_id", "urls"],
            "additionalProperties": False,
        },
    },
    "add_knowledge": {
        "description": "Add an existing IMA note to a knowledge base.",
        "schema": {
            "type": "object",
            "properties": {
                "knowledge_base_id": {"type": "string", "minLength": 1},
                "note_id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
                "folder_id": {"type": "string", "minLength": 1},
            },
            "required": ["knowledge_base_id", "note_id", "title"],
            "additionalProperties": False,
        },
    },
    "upload_file": {
        "description": "Upload a supported local file to an IMA knowledge base.",
        "schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "minLength": 1},
                "knowledge_base_id": {"type": "string", "minLength": 1},
                "folder_id": {"type": "string", "minLength": 1},
                "content_type": {"type": "string", "minLength": 1},
                "duplicate_policy": {"type": "string", "enum": ["cancel", "append_timestamp"]},
            },
            "required": ["file_path", "knowledge_base_id"],
            "additionalProperties": False,
        },
    },
    "get_media_info": {
        "description": "Get access information for an IMA knowledge base file or note.",
        "schema": {
            "type": "object",
            "properties": {"media_id": {"type": "string", "minLength": 1}},
            "required": ["media_id"],
            "additionalProperties": False,
        },
    },
    "fetch_media_content": {
        "description": "Read the original content of an IMA knowledge-base file or note.",
        "schema": {
            "type": "object",
            "properties": {"media_id": {"type": "string", "minLength": 1}},
            "required": ["media_id"],
            "additionalProperties": False,
        },
    },
}


class ProgramError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:2000]
        self.retryable = retryable


def _credentials(context: dict[str, Any]) -> tuple[str, str]:
    credentials = context.get("credentials")
    if not isinstance(credentials, dict):
        raise ProgramError("authorization_required", "IMA 凭据不存在")
    client_id = credentials.get("client_id")
    api_key = credentials.get("api_key")
    if (
        not isinstance(client_id, str)
        or not client_id.strip()
        or not isinstance(api_key, str)
        or not api_key.strip()
    ):
        raise ProgramError("authorization_required", "IMA Client ID 或 API Key 不存在")
    return client_id.strip(), api_key.strip()


def _credential_values(values: object) -> tuple[str, str]:
    if not isinstance(values, dict):
        raise ProgramError("bad_request", "IMA 凭据格式无效")
    client_id = values.get("client_id")
    api_key = values.get("api_key")
    if (
        not isinstance(client_id, str)
        or not client_id.strip()
        or len(client_id.strip()) > 255
        or not isinstance(api_key, str)
        or not api_key.strip()
        or len(api_key.strip()) > 16384
    ):
        raise ProgramError("bad_request", "请填写有效的 IMA Client ID 和 API Key")
    return client_id.strip(), api_key.strip()


def _http_error(response: httpx.Response, action: str) -> ProgramError:
    if response.status_code in {401, 403}:
        return ProgramError("authorization_required", "IMA Client ID 或 API Key 无效，请重新授权")
    if response.status_code == 429:
        return ProgramError("rate_limited", "IMA 请求过于频繁，请稍后重试")
    if response.status_code >= 500:
        return ProgramError("unavailable", f"IMA {action}服务暂时不可用", retryable=True)
    return ProgramError("external_error", f"IMA {action}请求失败（HTTP {response.status_code}）")


def _request_json(
    client_id: str,
    api_key: str,
    api_path: str,
    body: dict[str, Any],
    *,
    action: str,
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            response = client.post(
                f"{_BASE_URL}/{api_path.lstrip('/')}",
                headers={
                    "ima-openapi-clientid": client_id,
                    "ima-openapi-apikey": api_key,
                    "ima-openapi-ctx": f"skill_version={_SKILL_VERSION}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.RequestError as exc:
        raise ProgramError("unavailable", f"IMA {action}服务连接失败", retryable=True) from exc
    if response.status_code != 200:
        raise _http_error(response, action)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProgramError("external_error", f"IMA {action}服务未返回有效 JSON") from exc
    if not isinstance(payload, dict):
        raise ProgramError("external_error", f"IMA {action}响应格式错误")
    if payload.get("code") != 0:
        message = payload.get("msg")
        if payload.get("code") in {401, 403, 20004}:
            raise ProgramError("authorization_required", str(message or "IMA 授权已失效"))
        if payload.get("code") in {429, 20002, 110021}:
            raise ProgramError("rate_limited", str(message or "IMA 请求过于频繁"))
        raise ProgramError("external_error", str(message or "IMA 请求失败"))
    return payload


def _validate_configuration(_context: dict[str, Any]) -> dict[str, Any]:
    return {}


def _authorization_identity(_context: dict[str, Any]) -> dict[str, Any]:
    return {"identity": {"service": "ima", "base_url": _BASE_URL}}


def _authorization_begin(_context: dict[str, Any]) -> dict[str, Any]:
    return {"type": "form"}


def _authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "credentials":
        raise ProgramError("bad_request", "IMA 需要提交 Client ID 和 API Key")
    client_id, api_key = _credential_values(submission.get("values"))
    _request_json(
        client_id,
        api_key,
        "openapi/wiki/v1/search_knowledge_base",
        {"query": "", "cursor": "", "limit": 1},
        action="授权校验",
    )
    return {
        "external_account_name": "IMA 用户",
        "credential": {"values": {"client_id": client_id, "api_key": api_key}},
        "public_metadata": {"base_url": _BASE_URL},
    }


def _tools_discover(context: dict[str, Any]) -> dict[str, Any]:
    _credentials(context)
    write_tools = {"import_doc", "append_doc", "import_urls", "add_knowledge", "upload_file"}
    return {
        "tools": [
            {
                "key": name,
                "upstream_name": name,
                "description": definition["description"],
                "input_schema": definition["schema"],
                "effect": "write" if name in write_tools else "read",
                "retry_policy": "never" if name in write_tools else "safe",
                "confirmation": "user_required" if name in write_tools else "not_required",
                "source_revision": "ima-openapi-v1.1.9",
            }
            for name, definition in _TOOL_DEFINITIONS.items()
        ]
    }


def _arguments(context: dict[str, Any], tool_name: str) -> dict[str, Any]:
    arguments = context.get("arguments")
    if not isinstance(arguments, dict):
        raise ProgramError("bad_request", f"IMA {tool_name} 参数格式无效")
    allowed = set(_TOOL_DEFINITIONS[tool_name]["schema"]["properties"])
    if set(arguments) - allowed:
        raise ProgramError("bad_request", f"IMA {tool_name} 参数格式无效")
    return arguments


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProgramError("bad_request", f"IMA 参数 {key} 不能为空")
    return value.strip()


def _json_result(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProgramError("external_error", "IMA 返回的数据格式错误")
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {
        "content": [{"type": "text", "text": text}],
        "structured_content": data,
        "is_error": False,
    }


def _body_string(arguments: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ProgramError("bad_request", f"IMA 参数 {key} 无效")
    return value.strip()


def _body_integer(
    arguments: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = arguments.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
        raise ProgramError("bad_request", f"IMA 参数 {key} 无效")
    return value


def _body_urls(arguments: dict[str, Any]) -> list[str]:
    urls = arguments.get("urls")
    if not isinstance(urls, list) or not 1 <= len(urls) <= 10:
        raise ProgramError("bad_request", "IMA urls 必须包含 1 到 10 个地址")
    if any(not isinstance(url, str) or not url.strip() for url in urls):
        raise ProgramError("bad_request", "IMA urls 包含无效地址")
    normalized = []
    for raw_url in urls:
        url = raw_url.strip()
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ProgramError("bad_request", "IMA 不支持本地或无效 URL")
        if (
            hostname in {"www.bilibili.com", "bilibili.com"} and parsed.path.startswith("/video/")
        ) or (
            hostname in {"www.youtube.com", "youtube.com"} and parsed.path == "/watch"
        ):
            raise ProgramError("bad_request", "IMA 不支持 Bilibili 或 YouTube 视频 URL，请使用 IMA 客户端")
        normalized.append(url)
    return normalized


def _body_ids(arguments: dict[str, Any], key: str, maximum: int) -> list[str]:
    values = arguments.get(key)
    if not isinstance(values, list) or not 1 <= len(values) <= maximum:
        raise ProgramError("bad_request", f"IMA 参数 {key} 无效")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ProgramError("bad_request", f"IMA 参数 {key} 无效")
    return [value.strip() for value in values]


def _body_params(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    params = arguments.get("params")
    if not isinstance(params, list) or not 1 <= len(params) <= 2000:
        raise ProgramError("bad_request", "IMA 参数 params 无效")
    normalized = []
    for item in params:
        if not isinstance(item, dict):
            raise ProgramError("bad_request", "IMA 参数 params 无效")
        name = item.get("name")
        media_type = item.get("media_type")
        if not isinstance(name, str) or not name.strip() or isinstance(media_type, bool) or not isinstance(media_type, int):
            raise ProgramError("bad_request", "IMA 参数 params 无效")
        normalized.append({"name": name.strip(), "media_type": media_type})
    return normalized


def _utf8_string(arguments: dict[str, Any], key: str) -> str:
    value = _required_string(arguments, key)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProgramError("bad_request", f"IMA 参数 {key} 不是有效的 UTF-8 文本") from exc
    return value


def _file_metadata(file_path: str, content_type: object) -> tuple[Path, str, int, int, str]:
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise ProgramError("bad_request", "上传文件不存在或不是普通文件")
    suffix = path.suffix.lower().lstrip(".")
    media = _MEDIA_TYPES.get(suffix)
    requested_content_type = content_type.strip().lower() if isinstance(content_type, str) and content_type.strip() else ""
    if requested_content_type in _CONTENT_MEDIA_TYPES:
        media = _CONTENT_MEDIA_TYPES[requested_content_type]
    if media is None:
        raise ProgramError("bad_request", "IMA 不支持该文件类型")
    media_type, default_content_type, size_limit = media
    size = path.stat().st_size
    if size > size_limit or size > _MAX_FILE_SIZE:
        raise ProgramError("bad_request", "上传文件超过 IMA 对该类型的大小限制")
    actual_content_type = requested_content_type or default_content_type
    return path, suffix, size, media_type, actual_content_type


def _upload_to_cos(credential: dict[str, Any], content: bytes, content_type: str) -> None:
    required = ("secret_id", "secret_key", "token", "bucket_name", "region", "cos_key")
    if any(not isinstance(credential.get(key), str) or not credential[key] for key in required):
        raise ProgramError("external_error", "IMA 返回的 COS 上传凭据不完整")
    try:
        start_time = int(credential.get("start_time"))
        expired_time = int(credential.get("expired_time"))
    except (TypeError, ValueError) as exc:
        raise ProgramError("external_error", "IMA 返回的 COS 凭据时间无效") from exc
    secret_id = credential["secret_id"]
    secret_key = credential["secret_key"]
    bucket = credential["bucket_name"]
    region = credential["region"]
    cos_key = credential["cos_key"]
    host = f"{bucket}.cos.{region}.myqcloud.com"
    pathname = f"/{cos_key}"
    key_time = f"{start_time};{expired_time}"
    sign_headers = {"content-length": str(len(content)), "host": host}
    canonical_headers = "&".join(
        f"{name}={quote(value, safe='')}" for name, value in sorted(sign_headers.items())
    )
    http_string = f"put\n{pathname}\n\n{canonical_headers}\n"
    sign_key = hmac.new(secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
    authorization = (
        "q-sign-algorithm=sha1&"
        f"q-ak={secret_id}&q-sign-time={key_time}&q-key-time={key_time}&"
        "q-header-list=content-length;host&q-url-param-list=&"
        f"q-signature={signature}"
    )
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            response = client.put(
                f"https://{host}{quote(pathname, safe='/')}",
                content=content,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(len(content)),
                    "Authorization": authorization,
                    "x-cos-security-token": credential["token"],
                },
            )
    except httpx.RequestError as exc:
        raise ProgramError("unavailable", "IMA COS 上传服务连接失败", retryable=True) from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise ProgramError("external_error", f"IMA COS 上传失败（HTTP {response.status_code}）")


def _fetch_url(url: object, headers: object) -> tuple[bytes, str, str]:
    if not isinstance(url, str) or not url.strip():
        raise ProgramError("external_error", "IMA 媒体没有可访问的原文地址")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ProgramError("external_error", "IMA 返回了无效的原文地址")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if hostname != "ima.qq.com" and not hostname.endswith(".myqcloud.com"):
        raise ProgramError("external_error", "IMA 原文地址不在允许的服务域名内")
    request_headers = {}
    if isinstance(headers, dict):
        request_headers = {
            str(key): value for key, value in headers.items() if isinstance(key, str) and isinstance(value, str)
        }
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0), follow_redirects=False) as client:
            response = client.get(url, headers=request_headers)
    except httpx.RequestError as exc:
        raise ProgramError("unavailable", "IMA 原文服务连接失败", retryable=True) from exc
    if response.status_code != 200:
        raise _http_error(response, "原文读取")
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise ProgramError("external_error", "IMA 原文超过连接器单次读取大小限制")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return response.content, content_type, url


def _media_result(
    client_id: str,
    api_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ProgramError("external_error", "IMA 媒体信息响应格式错误")
    if data.get("media_type") == 11:
        notebook_ext_info = data.get("notebook_ext_info")
        note_id = notebook_ext_info.get("notebook_id") if isinstance(notebook_ext_info, dict) else None
        if isinstance(note_id, str) and note_id.strip():
            note_payload = _request_json(
                client_id,
                api_key,
                "openapi/note/v1/get_doc_content",
                {"note_id": note_id.strip(), "target_content_format": 0},
                action="笔记原文读取",
            )
            note_data = note_payload.get("data")
            if not isinstance(note_data, dict) or not isinstance(note_data.get("content"), str):
                raise ProgramError("external_error", "IMA 笔记原文响应格式错误")
            return {
                "content": [{"type": "text", "text": note_data["content"]}],
                "structured_content": note_data,
                "is_error": False,
            }
    url_info = data.get("url_info")
    if not isinstance(url_info, dict) or not url_info.get("url"):
        return {
            "content": [{"type": "text", "text": "请使用 IMA 客户端查看原文。"}],
            "structured_content": data,
            "is_error": False,
        }
    content, content_type, url = _fetch_url(url_info.get("url"), url_info.get("headers"))
    if not content_type:
        content_type = mimetypes.guess_type(urlsplit(url).path)[0] or "application/octet-stream"
    is_text = content_type.startswith("text/") or content_type in {
        "application/json",
        "application/xml",
        "application/javascript",
    }
    if is_text:
        text = content.decode("utf-8", errors="replace")
        return {
            "content": [{"type": "text", "text": text}],
            "structured_content": {"media_type": data.get("media_type"), "content": text},
            "is_error": False,
        }
    return {
        "content": [
            {
                "type": "resource",
                "uri": url,
                "mime_type": content_type,
                "data": base64.b64encode(content).decode("ascii"),
            }
        ],
        "structured_content": {"media_type": data.get("media_type"), "mime_type": content_type},
        "is_error": False,
    }


def _upload_file(
    client_id: str,
    api_key: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    path, file_ext, file_size, media_type, content_type = _file_metadata(
        _required_string(arguments, "file_path"), arguments.get("content_type")
    )
    file_name = path.name
    repeated_payload = _request_json(
        client_id,
        api_key,
        "openapi/wiki/v1/check_repeated_names",
        {
            "knowledge_base_id": _required_string(arguments, "knowledge_base_id"),
            "params": [{"name": file_name, "media_type": media_type}],
            **({"folder_id": _required_string(arguments, "folder_id")} if arguments.get("folder_id") else {}),
        },
        action="文件重名检查",
    )
    repeated_data = repeated_payload.get("data")
    if not isinstance(repeated_data, dict):
        raise ProgramError("external_error", "IMA 文件重名检查响应格式错误")
    repeated_items = repeated_data.get("results", [])
    is_repeated = any(
        isinstance(item, dict) and item.get("name") == file_name and item.get("is_repeated") is True
        for item in repeated_items
    ) if isinstance(repeated_items, list) else False
    if is_repeated:
        duplicate_policy = arguments.get("duplicate_policy")
        if duplicate_policy != "append_timestamp":
            raise ProgramError(
                "bad_request",
                f"IMA 已存在同名文件 {file_name}，请确认保留副本后设置 duplicate_policy=append_timestamp，或取消上传",
            )
        timestamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
        file_name = f"{path.stem}_{timestamp}{path.suffix}"

    media_payload = _request_json(
        client_id,
        api_key,
        "openapi/wiki/v1/create_media",
        {
            "file_name": file_name,
            "file_size": file_size,
            "content_type": content_type,
            "knowledge_base_id": _required_string(arguments, "knowledge_base_id"),
            "file_ext": file_ext,
        },
        action="创建媒体",
    )
    media_data = media_payload.get("data")
    if not isinstance(media_data, dict):
        raise ProgramError("external_error", "IMA 创建媒体响应格式错误")
    media_id = media_data.get("media_id")
    cos_credential = media_data.get("cos_credential")
    if not isinstance(media_id, str) or not media_id.strip() or not isinstance(cos_credential, dict):
        raise ProgramError("external_error", "IMA 创建媒体响应缺少上传凭据")
    _upload_to_cos(cos_credential, path.read_bytes(), content_type)
    add_body: dict[str, Any] = {
        "media_type": media_type,
        "media_id": media_id,
        "title": file_name,
        "knowledge_base_id": _required_string(arguments, "knowledge_base_id"),
        "file_info": {
            "cos_key": cos_credential.get("cos_key"),
            "file_size": file_size,
            "last_modify_time": int(path.stat().st_mtime),
            "file_name": file_name,
        },
    }
    if arguments.get("folder_id"):
        add_body["folder_id"] = _required_string(arguments, "folder_id")
    add_payload = _request_json(
        client_id,
        api_key,
        "openapi/wiki/v1/add_knowledge",
        add_body,
        action="添加文件到知识库",
    )
    return _json_result({"file_name": file_name, "media_id": media_id, "data": add_payload.get("data", {})})


def _tool_invoke(context: dict[str, Any]) -> dict[str, Any]:
    client_id, api_key = _credentials(context)
    tool_name = context.get("tool_name")
    if tool_name not in _TOOL_DEFINITIONS:
        raise ProgramError("action_forbidden", "IMA 工具不在允许列表中")
    arguments = _arguments(context, tool_name)

    if tool_name == "search_note":
        start = _body_integer(arguments, "start", 0, 0, 2**31)
        end = _body_integer(arguments, "end", start + 20, start + 1, start + 20)
        body: dict[str, Any] = {
            "search_type": _body_integer(arguments, "search_type", 0, 0, 1),
            "sort_type": _body_integer(arguments, "sort_type", 0, 0, 3),
            "start": start,
            "end": end,
        }
        query_info = arguments.get("query_info")
        if query_info is not None:
            if not isinstance(query_info, dict) or set(query_info) - {"title", "content"}:
                raise ProgramError("bad_request", "IMA 参数 query_info 无效")
            normalized_query = {}
            for key, value in query_info.items():
                if not isinstance(value, str):
                    raise ProgramError("bad_request", "IMA 参数 query_info 无效")
                if value.strip():
                    normalized_query[key] = value.strip()
            body["query_info"] = normalized_query
        payload = _request_json(client_id, api_key, "openapi/note/v1/search_note", body, action="笔记搜索")
        return _json_result(payload.get("data", {}))

    if tool_name == "list_notebook":
        cursor = _body_string(arguments, "cursor", allow_empty=True) if "cursor" in arguments else "0"
        body = {"cursor": cursor, "limit": _body_integer(arguments, "limit", 20, 1, 20)}
        if arguments.get("version"):
            body["version"] = _body_string(arguments, "version")
        payload = _request_json(client_id, api_key, "openapi/note/v1/list_notebook", body, action="笔记本列表")
        return _json_result(payload.get("data", {}))

    if tool_name == "list_note":
        body = {
            "cursor": _body_string(arguments, "cursor", allow_empty=True) if "cursor" in arguments else "",
            "limit": _body_integer(arguments, "limit", 20, 1, 20),
            "sort_type": _body_integer(arguments, "sort_type", 0, 0, 3),
        }
        if arguments.get("folder_id"):
            body["folder_id"] = _body_string(arguments, "folder_id")
        payload = _request_json(client_id, api_key, "openapi/note/v1/list_note", body, action="笔记列表")
        return _json_result(payload.get("data", {}))

    if tool_name == "get_doc_content":
        body = {
            "note_id": _required_string(arguments, "note_id"),
            "target_content_format": _body_integer(arguments, "target_content_format", 0, 0, 2),
        }
        payload = _request_json(client_id, api_key, "openapi/note/v1/get_doc_content", body, action="笔记原文读取")
        return _json_result(payload.get("data", {}))

    if tool_name in {"import_doc", "append_doc"}:
        content = _utf8_string(arguments, "content")
        body = {"content_format": _body_integer(arguments, "content_format", 1, 1, 1), "content": content}
        if tool_name == "import_doc":
            if arguments.get("folder_id"):
                body["folder_id"] = _body_string(arguments, "folder_id")
            if arguments.get("folder_name"):
                body["folder_name"] = _body_string(arguments, "folder_name")
            api_path, action = "openapi/note/v1/import_doc", "新建笔记"
        else:
            body["note_id"] = _required_string(arguments, "note_id")
            api_path, action = "openapi/note/v1/append_doc", "追加笔记内容"
        payload = _request_json(client_id, api_key, api_path, body, action=action)
        return _json_result(payload.get("data", {}))

    if tool_name == "get_knowledge_base":
        payload = _request_json(
            client_id,
            api_key,
            "openapi/wiki/v1/get_knowledge_base",
            {"ids": _body_ids(arguments, "ids", 20)},
            action="知识库详情",
        )
        return _json_result(payload.get("data", {}))

    if tool_name == "get_knowledge_list":
        body = {
            "knowledge_base_id": _required_string(arguments, "knowledge_base_id"),
            "cursor": _body_string(arguments, "cursor", allow_empty=True) if "cursor" in arguments else "",
            "limit": _body_integer(arguments, "limit", 20, 1, 50),
        }
        if arguments.get("folder_id"):
            body["folder_id"] = _body_string(arguments, "folder_id")
        payload = _request_json(client_id, api_key, "openapi/wiki/v1/get_knowledge_list", body, action="知识库内容列表")
        return _json_result(payload.get("data", {}))

    if tool_name == "search_knowledge":
        payload = _request_json(
            client_id,
            api_key,
            "openapi/wiki/v1/search_knowledge",
            {
                "query": _required_string(arguments, "query"),
                "knowledge_base_id": _required_string(arguments, "knowledge_base_id"),
                "cursor": _body_string(arguments, "cursor", allow_empty=True) if "cursor" in arguments else "",
            },
            action="知识搜索",
        )
        return _json_result(payload.get("data", {}))

    if tool_name == "search_knowledge_base":
        payload = _request_json(
            client_id,
            api_key,
            "openapi/wiki/v1/search_knowledge_base",
            {
                "query": _body_string(arguments, "query", allow_empty=True) if "query" in arguments else "",
                "cursor": _body_string(arguments, "cursor", allow_empty=True) if "cursor" in arguments else "",
                "limit": _body_integer(arguments, "limit", 20, 1, 20),
            },
            action="知识库搜索",
        )
        return _json_result(payload.get("data", {}))

    if tool_name == "get_addable_knowledge_base_list":
        payload = _request_json(
            client_id,
            api_key,
            "openapi/wiki/v1/get_addable_knowledge_base_list",
            {
                "cursor": _body_string(arguments, "cursor", allow_empty=True) if "cursor" in arguments else "",
                "limit": _body_integer(arguments, "limit", 20, 1, 50),
            },
            action="可添加知识库列表",
        )
        return _json_result(payload.get("data", {}))

    if tool_name == "check_repeated_names":
        body: dict[str, Any] = {
            "knowledge_base_id": _required_string(arguments, "knowledge_base_id"),
            "params": _body_params(arguments),
        }
        if arguments.get("folder_id"):
            body["folder_id"] = _body_string(arguments, "folder_id")
        payload = _request_json(client_id, api_key, "openapi/wiki/v1/check_repeated_names", body, action="文件重名检查")
        return _json_result(payload.get("data", {}))

    if tool_name == "import_urls":
        body = {
            "knowledge_base_id": _required_string(arguments, "knowledge_base_id"),
            "urls": _body_urls(arguments),
        }
        if arguments.get("folder_id"):
            body["folder_id"] = _body_string(arguments, "folder_id")
        payload = _request_json(client_id, api_key, "openapi/wiki/v1/import_urls", body, action="网页导入")
        return _json_result(payload.get("data", {}))

    if tool_name == "add_knowledge":
        body: dict[str, Any] = {
            "media_type": 11,
            "title": _utf8_string(arguments, "title"),
            "knowledge_base_id": _required_string(arguments, "knowledge_base_id"),
            "note_info": {"content_id": _required_string(arguments, "note_id")},
        }
        if arguments.get("folder_id"):
            body["folder_id"] = _body_string(arguments, "folder_id")
        payload = _request_json(client_id, api_key, "openapi/wiki/v1/add_knowledge", body, action="添加笔记到知识库")
        return _json_result(payload.get("data", {}))

    if tool_name == "upload_file":
        return _upload_file(client_id, api_key, arguments)

    media_id = _required_string(arguments, "media_id")
    payload = _request_json(
        client_id,
        api_key,
        "openapi/wiki/v1/get_media_info",
        {"media_id": media_id},
        action="媒体信息",
    )
    if tool_name == "get_media_info":
        return _json_result(payload.get("data", {}))
    return _media_result(client_id, api_key, payload)


_OPERATIONS = {
    "configuration_validate": _validate_configuration,
    "authorization_identity": _authorization_identity,
    "authorization_begin": _authorization_begin,
    "authorization_complete": _authorization_complete,
    "tools_discover": _tools_discover,
    "tool_invoke": _tool_invoke,
}


def _success(result: dict[str, Any]) -> dict[str, Any]:
    return {"protocol_version": _PROTOCOL_VERSION, "ok": True, "result": result}


def _failure(error: ProgramError) -> dict[str, Any]:
    return {
        "protocol_version": _PROTOCOL_VERSION,
        "ok": False,
        "error": {"code": error.code, "message": error.message, "retryable": error.retryable},
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
        response = _success(handler(context))
    except ProgramError as exc:
        response = _failure(exc)
    except Exception:
        response = _failure(ProgramError("external_error", "连接器程序执行失败"))
    json.dump(response, sys.stdout, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    main()
