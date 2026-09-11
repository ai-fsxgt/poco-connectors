import base64
import hashlib
import json
import mimetypes
import os
import platform
import re
import signal
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from errors import ProgramError

_PROVIDER_ROOT = Path(__file__).resolve().parent
_CATALOG_PATH = _PROVIDER_ROOT / "catalog.json"
_VENDOR_ROOT = _PROVIDER_ROOT / "vendor"
_MAX_FILE_INPUT_BYTES = 180 * 1024
_MAX_FILE_INPUT_BASE64_CHARS = 4 * ((_MAX_FILE_INPUT_BYTES + 2) // 3)
_MAX_FILE_INPUT_TEXT_CHARS = 32 * 1024
_MAX_OUTPUT_BYTES = 360 * 1024
_MAX_OUTPUT_FILES = 20
_FILE_INPUT_PARAMETERS = {
    ("aitable.record_create", "records-file"),
    ("aitable.record_update", "records-file"),
    ("aitable.record_upsert", "records-file"),
    ("aitable.shortcut_attachment_put", "file"),
    ("audit.verify", "file"),
    ("chat.favorite_personal_emotion", "file-path"),
    ("chat.reply_thread", "file"),
    ("chat.send_personal_message", "file"),
    ("chat.send_robot_message", "file-path"),
    ("chat.send_thread", "file"),
    ("chat.shortcut_messages_send", "file"),
    ("chat.shortcut_messages_send", "file-path"),
    ("chat.shortcut_messages_send", "groups-file"),
    ("chat.upload_local_conversation_file", "file"),
    ("dev.mcp_credential_save", "content-file"),
    ("doc.create_document", "content-file"),
    ("doc.media_insert", "file"),
    ("doc.media_upload", "file"),
    ("doc.shortcut_import", "file"),
    ("doc.shortcut_media_insert", "file"),
    ("doc.shortcut_resource_update", "file"),
    ("doc.style_cover_set", "file"),
    ("doc.update_document", "content-file"),
    ("doc.upload", "file"),
    ("drive.shortcut_upload", "file"),
    ("drive.upload", "file"),
    ("mail.create_draft", "attachment"),
    ("mail.create_draft", "inline-attachment"),
    ("mail.create_forward_draft", "attachment"),
    ("mail.create_forward_draft", "inline-attachment"),
    ("mail.create_reply_draft", "attachment"),
    ("mail.create_reply_draft", "inline-attachment"),
    ("mail.create_replyall_draft", "attachment"),
    ("mail.create_replyall_draft", "inline-attachment"),
    ("mail.send_email", "attachment"),
    ("mail.send_email", "inline-attachment"),
    ("mail.update_draft", "attachment"),
    ("mail.update_draft", "inline-attachment"),
    ("markdown.create", "file"),
    ("markdown.diff", "file"),
    ("markdown.overwrite", "file"),
    ("minutes.shortcut_upload", "file"),
    ("minutes.shortcut_upload_and_analyze", "file"),
    ("minutes.shortcut_upload_and_notify", "file"),
    ("oa.attachment_upload", "file"),
    ("recruit.create_job", "from"),
    ("report.create_report", "contents-file"),
    ("sheet.create_float_image", "file"),
    ("sheet.import", "file"),
    ("sheet.media_upload", "file"),
    ("sheet.range_batch_set_style", "batch"),
    ("sheet.update_float_image", "file"),
    ("sheet.write_image", "file"),
    ("todo.add_todo_attachment", "file"),
    ("todo.shortcut_upload_attachment", "file-path"),
    ("whiteboard.update", "source"),
}
_LITERAL_OR_FILE_PARAMETERS = {
    ("aitable.workflow_create", "dsl"),
    ("aitable.workflow_update", "dsl"),
    ("doc.shortcut_checkpoint_update", "content"),
    ("doc.shortcut_create", "content"),
    ("doc.shortcut_update", "content"),
    ("doc.shortcut_update", "text"),
    ("markdown.create", "content"),
    ("markdown.overwrite", "content"),
    ("minutes.shortcut_replace_batch", "json"),
    ("minutes.shortcut_summary", "content"),
    ("sheet.create_pivot_table", "properties"),
    ("sheet.formula_verify", "targets"),
    ("sheet.set_range_from_csv", "csv"),
    ("sheet.table_put", "sheets"),
    ("sheet.update_pivot_table", "properties"),
    ("whiteboard.shortcut_update", "source"),
}
_POSITIONAL_LIMITS = {
    "chat.chat_permission_grant": (1, 1),
    "chat.search_groups": (0, 1),
    "dev.search_open_platform_docs_rag": (0, 1),
    "devdoc.search_open_platform_docs_rag": (0, 1),
    "event.consume": (0, 8),
    "event.schema": (1, 1),
    "event.stop": (0, 1),
    "mcp.published_invoke": (2, 2),
    "mcp.published_tools": (1, 1),
    "mcp.url_get": (1, 1),
    "pat.batch_grant": (1, 8),
}
_FORBIDDEN_FLAGS = {
    "client-id",
    "client-secret",
    "debug",
    "jq",
    "mock",
    "profile",
    "verbose",
    "yes",
}
_CONFIRMATION_OVERRIDES = {"doc.update_document"}
_UNSUPPORTED_COMMANDS = {
    "audit.export": "Poco 单次调用不保留可供后续导出的 DWS 本地审计日志",
    "audit.tail": "Poco 单次调用不保留可供后续查看的 DWS 本地审计日志",
    "dev.connect_list": "Poco 的连接器进程不运行 DWS 本机开发守护进程",
    "dev.connect_restart": "Poco 的连接器进程不运行 DWS 本机开发守护进程",
    "dev.connect_status": "Poco 的连接器进程不运行 DWS 本机开发守护进程",
    "dev.connect_stop": "Poco 的连接器进程不运行 DWS 本机开发守护进程",
    "drive.folder_pull": "Poco 单次调用不提供可持续同步的本地目录",
    "drive.folder_push": "Poco 单次调用不提供可持续同步的本地目录",
    "drive.folder_status": "Poco 单次调用不提供可持续同步的本地目录",
    "drive.folder_sync": "Poco 单次调用不提供可持续同步的本地目录",
    "event.status": "Poco 单次调用不会保留 DWS 本地事件订阅状态",
    "event.stop": "Poco 单次调用不会保留 DWS 本地事件订阅状态",
    "pat.browser_policy": "Poco 单次调用不会保留 DWS 本地浏览器策略",
    "pat.shortcut_browser_policy": "Poco 单次调用不会保留 DWS 本地浏览器策略",
}
_TOOL_POLICIES = {
    "dws_search_commands": None,
    "dws_execute_read": ("read", None),
    "dws_execute_write": ("write", "not_required"),
    "dws_execute_confirmed_write": ("write", "user_required"),
    "dws_execute_destructive": ("destructive", None),
}


def _load_catalog() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    try:
        commands = json.loads(_CATALOG_PATH.read_text())["commands"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProgramError("external_error", "钉钉命令目录不可用") from exc
    for command in commands:
        if command.get("canonical_path") in _CONFIRMATION_OVERRIDES:
            command["confirmation"] = "user_required"
    return commands, {command["canonical_path"]: command for command in commands}


def _schema(
    properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _execution_schema() -> dict[str, Any]:
    file_input = _schema(
        {
            "flag": {"type": "string", "minLength": 1, "maxLength": 128},
            "name": {"type": "string", "minLength": 1, "maxLength": 128},
            "text": {"type": "string", "maxLength": _MAX_FILE_INPUT_TEXT_CHARS},
            "content_base64": {
                "type": "string",
                "maxLength": _MAX_FILE_INPUT_BASE64_CHARS,
            },
        },
        ["flag", "name"],
    )
    file_input["oneOf"] = [{"required": ["text"]}, {"required": ["content_base64"]}]
    return _schema(
        {
            "command": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
                "description": "search_commands 返回的 canonical_path。",
            },
            "flags": {
                "type": "object",
                "default": {},
                "description": "命令参数名到标量或数组值的映射，不含 -- 前缀。",
                "additionalProperties": True,
            },
            "positionals": {
                "type": "array",
                "items": {"type": "string", "maxLength": 10000},
                "maxItems": 8,
                "default": [],
            },
            "file_inputs": {
                "type": "array",
                "items": file_input,
                "maxItems": 20,
                "default": [],
                "description": "需要上传本地文件时使用；flag 必须是该命令的文件参数。",
            },
        },
        ["command"],
    )


def discover_tools(context: dict[str, Any]) -> dict[str, Any]:
    del context
    execute_schema = _execution_schema()
    tools = [
        {
            "key": "search_commands",
            "upstream_name": "dws_search_commands",
            "description": "检索当前钉钉连接器支持的命令、参数、风险和确认要求。执行命令前先调用。",
            "input_schema": _schema(
                {
                    "query": {"type": "string", "maxLength": 200, "default": ""},
                    "product": {"type": "string", "maxLength": 64},
                    "effect": {
                        "type": "string",
                        "enum": ["read", "write", "destructive"],
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 10,
                    },
                }
            ),
            "effect": "read",
            "retry_policy": "safe",
            "confirmation": "not_required",
            "source_revision": "dws-v1.0.61-poco.1",
        },
        {
            "key": "execute_read_command",
            "upstream_name": "dws_execute_read",
            "description": "执行 search_commands 返回的只读钉钉命令。",
            "input_schema": execute_schema,
            "effect": "read",
            "retry_policy": "safe",
            "confirmation": "not_required",
            "source_revision": "dws-v1.0.61-poco.1",
        },
        {
            "key": "execute_write_command",
            "upstream_name": "dws_execute_write",
            "description": "执行目录中无需用户确认的钉钉写操作。失败时不要自动重试，应先查询远端状态。",
            "input_schema": execute_schema,
            "effect": "write",
            "retry_policy": "never",
            "confirmation": "not_required",
            "source_revision": "dws-v1.0.61-poco.1",
        },
        {
            "key": "execute_confirmed_write_command",
            "upstream_name": "dws_execute_confirmed_write",
            "description": "执行目录中要求用户确认的钉钉写操作。Poco 会针对完整参数请求一次性确认。",
            "input_schema": execute_schema,
            "effect": "write",
            "retry_policy": "never",
            "confirmation": "user_required",
            "source_revision": "dws-v1.0.61-poco.1",
        },
        {
            "key": "execute_destructive_command",
            "upstream_name": "dws_execute_destructive",
            "description": "执行删除或其他高风险钉钉操作。每次操作均由 Poco 强制请求一次性确认。",
            "input_schema": execute_schema,
            "effect": "destructive",
            "retry_policy": "never",
            "confirmation": "user_required",
            "source_revision": "dws-v1.0.61-poco.1",
        },
    ]
    return {"tools": tools}


def _command_summary(command: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": command["canonical_path"],
        "summary": command.get("agent_summary") or command["description"],
        "effect": command["effect"],
        "confirmation": command["confirmation"],
        "poco_available": command["canonical_path"] not in _UNSUPPORTED_COMMANDS,
        "limitation": _UNSUPPORTED_COMMANDS.get(command["canonical_path"]),
        "usage": command.get("usage"),
        "parameters": command.get("parameters", {}),
        "constraints": command.get("constraints", []),
        "examples": command.get("examples", []),
    }


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {"query", "product", "effect", "limit"}
    if set(arguments) - allowed:
        raise ProgramError("bad_request", "命令检索参数包含未知字段")
    query = arguments.get("query", "")
    product = arguments.get("product")
    effect = arguments.get("effect")
    limit = arguments.get("limit", 10)
    if (
        not isinstance(query, str)
        or (product is not None and not isinstance(product, str))
        or (effect is not None and effect not in {"read", "write", "destructive"})
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 20
    ):
        raise ProgramError("bad_request", "命令检索参数无效")
    commands, _ = _load_catalog()
    words = [word for word in re.split(r"\s+", query.strip().lower()) if word]
    matches = []
    for command in commands:
        if product and command["canonical_path"].split(".", 1)[0] != product:
            continue
        if effect and command["effect"] != effect:
            continue
        haystack = " ".join(
            str(command.get(key, ""))
            for key in (
                "canonical_path",
                "cli_path",
                "description",
                "agent_summary",
                "use_when",
            )
        ).lower()
        if words and not all(word in haystack for word in words):
            continue
        matches.append(_command_summary(command))
        if len(matches) == limit:
            break
    payload = {"commands": matches, "count": len(matches)}
    return _result(payload)


def _is_file_parameter(command_key: str, flag: str) -> bool:
    return (command_key, flag) in (_FILE_INPUT_PARAMETERS | _LITERAL_OR_FILE_PARAMETERS)


def _uses_at_file(parameter: dict[str, Any]) -> bool:
    description = str(parameter.get("description", ""))
    return bool(
        re.search(r"@(?:文件|工作目录|相对)", description)
        or "@file" in description.lower()
    )


def _safe_name(name: object) -> str:
    if not isinstance(name, str) or not name or len(name.encode()) > 128:
        raise ProgramError("bad_request", "文件名无效")
    if Path(name).name != name or name in {".", ".."} or "\x00" in name:
        raise ProgramError("bad_request", "文件名只能是不含路径的普通文件名")
    return name


def _decode_file(item: dict[str, Any]) -> bytes:
    has_text = "text" in item
    has_base64 = "content_base64" in item
    if has_text == has_base64:
        raise ProgramError(
            "bad_request", "每个文件必须且只能提供 text 或 content_base64"
        )
    if has_text:
        if not isinstance(item["text"], str):
            raise ProgramError("bad_request", "文件 text 必须是字符串")
        return item["text"].encode()
    try:
        return base64.b64decode(item["content_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ProgramError("bad_request", "文件 content_base64 无效") from exc


def _stage_files(
    arguments: dict[str, Any],
    command: dict[str, Any],
    workspace: Path,
) -> dict[str, list[str]]:
    raw_items = arguments.get("file_inputs", [])
    if not isinstance(raw_items, list) or len(raw_items) > 20:
        raise ProgramError("bad_request", "file_inputs 必须是最多 20 项的数组")
    values: dict[str, list[str]] = {}
    total = 0
    input_root = workspace / "inputs"
    input_root.mkdir()
    parameters = command.get("parameters", {})
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict) or set(item) - {
            "flag",
            "name",
            "text",
            "content_base64",
        }:
            raise ProgramError("bad_request", "文件输入格式无效")
        flag = item.get("flag")
        parameter = parameters.get(flag) if isinstance(flag, str) else None
        if parameter is None or not _is_file_parameter(command["canonical_path"], flag):
            raise ProgramError("bad_request", f"--{flag} 不是该命令的文件输入参数")
        content = _decode_file(item)
        total += len(content)
        if total > _MAX_FILE_INPUT_BYTES:
            raise ProgramError("bad_request", "文件输入总大小不能超过 180 KiB")
        target = input_root / f"{index:02d}-{_safe_name(item.get('name'))}"
        target.write_bytes(content)
        relative = target.relative_to(workspace).as_posix()
        values.setdefault(flag, []).append(
            f"@{relative}" if _uses_at_file(parameter) else relative
        )
    return values


def _validate_path_value(flag: str, value: str, parameter: dict[str, Any]) -> None:
    description = str(parameter.get("description", "")).lower()
    path_like = (
        flag in {"output", "output-dir", "filename", "local-folder"}
        or "保存路径" in description
        or "输出目录" in description
    )
    if not path_like:
        return
    path = Path(value.removeprefix("@"))
    if path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ProgramError(
            "bad_request", f"--{flag} 只能使用本次调用目录内的安全相对路径"
        )


def _flag_arguments(
    command: dict[str, Any], arguments: dict[str, Any], staged: dict[str, list[str]]
) -> list[str]:
    flags = arguments.get("flags", {})
    if not isinstance(flags, dict):
        raise ProgramError("bad_request", "flags 必须是对象")
    parameters = command.get("parameters", {})
    result: list[str] = []
    for flag, value in flags.items():
        parameter = parameters.get(flag)
        if parameter is None:
            raise ProgramError("bad_request", f"命令不支持参数 --{flag}")
        if flag in _FORBIDDEN_FLAGS:
            raise ProgramError(
                "action_forbidden", f"Poco 不允许覆盖 DWS 全局参数 --{flag}"
            )
        parameter_key = (command["canonical_path"], flag)
        if parameter_key in _FILE_INPUT_PARAMETERS:
            raise ProgramError("bad_request", f"--{flag} 必须通过 file_inputs 提供")
        values = value if isinstance(value, list) else [value]
        if not values:
            continue
        cli_type = parameter.get("cli_type", "string")
        if cli_type == "bool":
            if len(values) != 1 or not isinstance(values[0], bool):
                raise ProgramError("bad_request", f"--{flag} 必须是布尔值")
            result.append(f"--{flag}={'true' if values[0] else 'false'}")
            continue
        if any(isinstance(item, (dict, list, bool)) or item is None for item in values):
            raise ProgramError("bad_request", f"--{flag} 的值类型无效")
        encoded = [str(item) for item in values]
        if parameter_key in _LITERAL_OR_FILE_PARAMETERS and any(
            item == "-" or item.startswith("@") for item in encoded
        ):
            raise ProgramError(
                "bad_request", f"--{flag} 的文件形式必须通过 file_inputs 提供"
            )
        for item in encoded:
            _validate_path_value(flag, item, parameter)
        if cli_type == "stringArray":
            for item in encoded:
                result.extend([f"--{flag}", item])
        else:
            result.extend([f"--{flag}", ",".join(encoded)])
    for flag, values in staged.items():
        if flag in flags:
            raise ProgramError(
                "bad_request", f"--{flag} 不能同时出现在 flags 和 file_inputs"
            )
        cli_type = parameters[flag].get("cli_type", "string")
        if cli_type != "stringArray" and len(values) != 1:
            raise ProgramError("bad_request", f"--{flag} 只接受一个文件")
        for value in values:
            result.extend([f"--{flag}", value])
    return result


def _positionals(command: dict[str, Any], arguments: dict[str, Any]) -> list[str]:
    values = arguments.get("positionals", [])
    if (
        not isinstance(values, list)
        or len(values) > 8
        or any(not isinstance(value, str) or len(value) > 10000 for value in values)
    ):
        raise ProgramError("bad_request", "positionals 必须是最多 8 项的字符串数组")
    if any(value.startswith("-") or "\x00" in value for value in values):
        raise ProgramError("bad_request", "位置参数不能以 - 开头或包含空字符")
    minimum, maximum = _POSITIONAL_LIMITS.get(command["canonical_path"], (0, 0))
    if not minimum <= len(values) <= maximum:
        raise ProgramError("bad_request", "位置参数数量与命令定义不匹配")
    return values


def _duration_seconds(value: str) -> float | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m)", value)
    if match is None:
        return None
    multiplier = {"ms": 0.001, "s": 1, "m": 60}[match.group(2)]
    return float(match.group(1)) * multiplier


def _validate_command_limits(
    command: dict[str, Any], arguments: dict[str, Any]
) -> None:
    key = command["canonical_path"]
    if key in _UNSUPPORTED_COMMANDS:
        raise ProgramError("action_forbidden", _UNSUPPORTED_COMMANDS[key])
    if key in {"event.consume", "event.listen_im"}:
        flags = arguments.get("flags", {})
        duration = flags.get("duration") if isinstance(flags, dict) else None
        seconds = _duration_seconds(duration) if isinstance(duration, str) else None
        if seconds is None or not 0 < seconds <= 15:
            raise ProgramError(
                "bad_request", "事件监听必须显式设置 15 秒以内的 duration"
            )
        forbidden = {
            "personal-event-base-url",
            "route",
            "stream-ticket-url",
        }
        if isinstance(flags, dict) and forbidden.intersection(flags):
            raise ProgramError(
                "action_forbidden", "Poco 不允许覆盖事件服务端点或本地路由目录"
            )


def _binary(runtime_root: Path) -> Path:
    machine = platform.machine().lower()
    arch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if arch is None or platform.system() != "Linux":
        raise ProgramError("unavailable", "钉钉连接器运行时仅支持 Linux amd64/arm64")
    archive = _VENDOR_ROOT / f"dws-linux-{arch}.tar.gz"
    try:
        checksums = json.loads((_VENDOR_ROOT / "checksums.json").read_text())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksums[archive.name]:
            raise ValueError("checksum mismatch")
        with tarfile.open(archive, "r:gz") as source:
            member = source.getmember("dws")
            if not member.isfile() or member.size > 80 * 1024 * 1024:
                raise ValueError("invalid runtime archive")
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError("missing runtime binary")
            target = runtime_root / "dws"
            target.write_bytes(stream.read())
            target.chmod(0o700)
    except (OSError, KeyError, ValueError, tarfile.TarError) as exc:
        raise ProgramError("external_error", "钉钉 DWS 运行时校验失败") from exc
    return target


def _run_dws(
    command: list[str], workspace: Path, runtime_root: Path
) -> tuple[int, str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "SSL_CERT_DIR",
            "SSL_CERT_FILE",
            "LANG",
            "LC_ALL",
        }
    }
    environment.update(
        {
            "DWS_CONFIG_DIR": str(runtime_root / "config"),
            "DWS_KEYCHAIN_DIR": str(runtime_root / "keychain"),
            "DINGTALK_DWS_AGENTCODE": "poco",
            "NO_COLOR": "1",
        }
    )
    with (
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=environment,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=24)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.wait()
            raise ProgramError(
                "unavailable", "钉钉命令执行超时；写操作可能已完成，请先查询远端状态"
            ) from exc
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout = _read_process_output(stdout_file)
        stderr = _read_process_output(stderr_file)
    return return_code, stdout, stderr


def _read_process_output(stream: Any) -> str:
    stream.seek(0)
    data = stream.read(_MAX_OUTPUT_BYTES + 1)
    if len(data) > _MAX_OUTPUT_BYTES:
        raise ProgramError(
            "response_too_large",
            "命令输出超过 360 KiB；写操作可能已完成，请先查询远端状态",
        )
    return data.decode("utf-8", errors="replace")


def _error_from_output(stdout: str, stderr: str) -> ProgramError:
    raw = stdout.strip() or stderr.strip()
    message = raw[-1800:] if raw else "钉钉命令执行失败"
    try:
        payload = json.loads(raw)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or message)
            reason = str(error.get("reason") or "").lower()
            category = str(error.get("category") or "").lower()
            joined = f"{reason} {category} {message}".lower()
            if "scope" in joined or "permission" in joined or "权限" in joined:
                return ProgramError(
                    "insufficient_scope",
                    message + "；请由管理员为 Poco 对应身份授予所需 PAT 权限",
                )
            if "auth" in joined or "token" in joined or "登录" in joined:
                return ProgramError("authorization_required", message)
    except ValueError:
        pass
    return ProgramError("external_error", message)


def _collect_outputs(workspace: Path) -> list[dict[str, Any]]:
    paths = sorted(
        path
        for path in workspace.rglob("*")
        if path.is_file() and "inputs" not in path.relative_to(workspace).parts
    )
    if len(paths) > _MAX_OUTPUT_FILES:
        raise ProgramError(
            "response_too_large",
            "命令生成的文件超过 20 个；远端操作可能已完成，请先查询状态",
        )
    result = []
    total = 0
    for path in paths:
        if path.is_symlink():
            raise ProgramError("external_error", "命令生成了不安全的符号链接")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ProgramError("external_error", "无法读取命令生成的文件") from exc
        total += size
        if total > _MAX_OUTPUT_BYTES:
            raise ProgramError(
                "response_too_large",
                "命令生成的文件超过 360 KiB；远端操作可能已完成，请先查询状态",
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ProgramError("external_error", "无法读取命令生成的文件") from exc
        if len(data) != size:
            raise ProgramError("external_error", "命令生成的文件在读取时发生变化")
        relative = path.relative_to(workspace).as_posix()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            text = (
                data.decode()
                if mime_type.startswith("text/")
                or mime_type in {"application/json", "application/xml"}
                else None
            )
        except UnicodeDecodeError:
            text = None
        resource = {
            "type": "resource",
            "uri": f"dingtalk-output:///{quote(relative, safe='/')}",
            "mime_type": mime_type,
        }
        if text is None:
            resource["data"] = base64.b64encode(data).decode()
        else:
            resource["text"] = text
        result.append(resource)
    return result


def _parse_stdout(stdout: str) -> object:
    text = stdout.strip()
    if not text:
        return {}
    if len(text.encode()) > _MAX_OUTPUT_BYTES:
        raise ProgramError(
            "response_too_large",
            "命令输出超过 360 KiB；写操作可能已完成，请先查询远端状态",
        )
    try:
        return json.loads(text)
    except ValueError:
        lines = [line for line in text.splitlines() if line.strip()]
        try:
            return [json.loads(line) for line in lines]
        except ValueError:
            return {"text": text}


def _result(
    payload: object, resources: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    structured = payload if isinstance(payload, dict) else {"result": payload}
    text = json.dumps(
        structured, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return {
        "content": [{"type": "text", "text": text}, *(resources or [])],
        "structured_content": structured,
        "is_error": False,
    }


def invoke_tool(context: dict[str, Any]) -> dict[str, Any]:
    tool_name = context.get("tool_name")
    arguments = context.get("arguments")
    if tool_name not in _TOOL_POLICIES or not isinstance(arguments, dict):
        raise ProgramError("bad_request", "钉钉工具或参数无效")
    if tool_name == "dws_search_commands":
        return _search(arguments)
    command_key = arguments.get("command")
    _, command_map = _load_catalog()
    command = command_map.get(command_key) if isinstance(command_key, str) else None
    if command is None:
        raise ProgramError(
            "bad_request", "未知的钉钉 canonical command；请先调用 search_commands"
        )
    expected_effect, expected_confirmation = _TOOL_POLICIES[tool_name]
    if command["effect"] != expected_effect or (
        expected_confirmation is not None
        and command["confirmation"] != expected_confirmation
    ):
        raise ProgramError("action_forbidden", "命令风险等级与所选执行工具不匹配")
    _validate_command_limits(command, arguments)
    credentials = context.get("credentials")
    token = credentials.get("access_token") if isinstance(credentials, dict) else None
    if not isinstance(token, str) or not token:
        raise ProgramError("authorization_required", "钉钉访问令牌不可用，请重新授权")
    with tempfile.TemporaryDirectory(prefix="poco-dingtalk-") as directory:
        runtime_root = Path(directory)
        workspace = runtime_root / "workspace"
        workspace.mkdir()
        staged = _stage_files(arguments, command, workspace)
        flags = _flag_arguments(command, arguments, staged)
        positionals = _positionals(command, arguments)
        binary = _binary(runtime_root)
        argv = [str(binary), "--token", token, "--format", "json", "--timeout", "20"]
        if (
            command["confirmation"] == "user_required"
            or command["effect"] == "destructive"
        ):
            argv.append("--yes")
        argv.extend(command["cli_path"].split())
        argv.extend(flags)
        if positionals:
            argv.extend(["--", *positionals])
        return_code, stdout, stderr = _run_dws(argv, workspace, runtime_root)
        if return_code != 0:
            raise _error_from_output(stdout, stderr)
        payload = _parse_stdout(stdout)
        return _result(payload, _collect_outputs(workspace))
