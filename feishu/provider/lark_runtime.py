"""Run the pinned official Lark CLI through a Poco-safe command surface."""

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

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "catalog.json"
VENDOR = ROOT / "vendor"
MAX_INPUT = 180 * 1024
MAX_OUTPUT = 360 * 1024
MAX_FILES = 20
FORBIDDEN_FLAGS = {"as", "profile", "yes", "debug", "jq", "verbose"}
POLICIES = {
    "search_commands": None,
    "execute_read_command": ("read", "not_required"),
    "execute_write_command": ("write", "not_required"),
    "execute_confirmed_write_command": ("write", "user_required"),
    "execute_destructive_command": ("destructive", "user_required"),
}
CONFIRMATION_OVERRIDES = {"mail +forward", "mail +reply", "mail +reply-all", "mail +send"}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "properties": properties,
        "required": required or [], "additionalProperties": False,
    }


def _execution_schema() -> dict[str, Any]:
    file_input = _schema({
        "flag": {"type": "string", "minLength": 1, "maxLength": 128},
        "name": {"type": "string", "minLength": 1, "maxLength": 128},
        "text": {"type": "string", "maxLength": 32768},
        "content_base64": {"type": "string", "maxLength": 245760},
    }, ["flag", "name"])
    file_input["oneOf"] = [{"required": ["text"]}, {"required": ["content_base64"]}]
    return _schema({
        "command": {"type": "string", "minLength": 1, "maxLength": 240},
        "flags": {"type": "object", "default": {}, "additionalProperties": True},
        "positionals": {"type": "array", "items": {"type": "string", "maxLength": 10000}, "maxItems": 8, "default": []},
        "file_inputs": {"type": "array", "items": file_input, "maxItems": MAX_FILES, "default": []},
    }, ["command"])


def discover_tools(_: dict[str, Any]) -> dict[str, Any]:
    execution = _execution_schema()
    return {"tools": [
        {"key": "search_commands", "upstream_name": "search_commands", "description": "检索官方飞书 CLI 当前支持的命令、参数、权限和风险。执行前先调用。", "input_schema": _schema({"query": {"type": "string", "maxLength": 200, "default": ""}, "product": {"type": "string", "maxLength": 64}, "effect": {"type": "string", "enum": ["read", "write", "destructive"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}}), "effect": "read", "retry_policy": "safe", "confirmation": "not_required", "source_revision": "lark-cli-1.0.72"},
        {"key": "execute_read_command", "upstream_name": "execute_read_command", "description": "执行目录中的只读飞书命令。", "input_schema": execution, "effect": "read", "retry_policy": "safe", "confirmation": "not_required", "source_revision": "lark-cli-1.0.72"},
        {"key": "execute_write_command", "upstream_name": "execute_write_command", "description": "执行目录中无需额外确认的飞书写命令。", "input_schema": execution, "effect": "write", "retry_policy": "never", "confirmation": "not_required", "source_revision": "lark-cli-1.0.72"},
        {"key": "execute_confirmed_write_command", "upstream_name": "execute_confirmed_write_command", "description": "执行需要用户确认的飞书写命令。", "input_schema": execution, "effect": "write", "retry_policy": "never", "confirmation": "user_required", "source_revision": "lark-cli-1.0.72"},
        {"key": "execute_destructive_command", "upstream_name": "execute_destructive_command", "description": "执行删除或其他高风险飞书命令。", "input_schema": execution, "effect": "destructive", "retry_policy": "never", "confirmation": "user_required", "source_revision": "lark-cli-1.0.72"},
    ]}


def _load_catalog() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    try:
        raw_commands = json.loads(CATALOG.read_text(encoding="utf-8"))["commands"]
        commands = []
        for raw in raw_commands:
            if not isinstance(raw, dict) or not isinstance(raw.get("canonical_path"), str):
                raise TypeError
            risk = raw.get("risk")
            effect = {"read": "read", "write": "write", "high-risk-write": "destructive"}.get(risk)
            if effect is None:
                raise ValueError
            command = dict(raw)
            command["effect"] = effect
            command["confirmation"] = "user_required" if effect == "destructive" or raw["canonical_path"] in CONFIRMATION_OVERRIDES else "not_required"
            command["parameters"] = _catalog_parameters(raw)
            commands.append(command)
        if not isinstance(commands, list):
            raise TypeError
        mapping = {item["canonical_path"]: item for item in commands}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProgramError("external_error", "飞书命令目录不可用") from exc
    return commands, mapping


def _catalog_parameters(command: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten the CLI's nested input schema into flag names."""
    result: dict[str, dict[str, Any]] = {}
    schema = command.get("input_schema", {})

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            return
        for name, parameter in properties.items():
            if not isinstance(parameter, dict):
                continue
            flag = parameter.get("flag")
            carrier = parameter.get("carrier")
            if isinstance(flag, str) and flag.startswith("--"):
                key = flag[2:]
                item = dict(parameter)
                item["type"] = parameter.get("type", "string")
                item["cli_type"] = "bool" if item["type"] == "boolean" else "string"
                if carrier or "@file" in str(parameter.get("description", "")).lower():
                    item["file_input"] = "at"
                result[key] = item
            elif isinstance(carrier, str):
                key = carrier[2:] if carrier.startswith("--") else carrier
                item = dict(parameter)
                item["type"] = "string"
                item["cli_type"] = "string"
                item["file_input"] = "at"
                result[key] = item
            else:
                walk(parameter)

    walk(schema)
    # These are stable CLI output/preview flags not repeated in every schema.
    result.setdefault("output", {"type": "string", "cli_type": "string", "output_path": True})
    result.setdefault("dry-run", {"type": "boolean", "cli_type": "bool"})
    return result


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {"query", "product", "effect", "limit"}
    if set(arguments) - allowed:
        raise ProgramError("bad_request", "命令检索参数包含未知字段")
    query = arguments.get("query", "")
    product = arguments.get("product")
    effect = arguments.get("effect")
    limit = arguments.get("limit", 10)
    if not isinstance(query, str) or not isinstance(product, (str, type(None))) or effect not in {None, "read", "write", "destructive"} or type(limit) is not int or not 1 <= limit <= 20:
        raise ProgramError("bad_request", "命令检索参数无效")
    words = [word for word in re.split(r"\s+", query.lower().strip()) if word]
    matches = []
    for command in _load_catalog()[0]:
        path = command["canonical_path"]
        if product and path.split(" ", 1)[0] != product:
            continue
        if effect and command["effect"] != effect:
            continue
        haystack = json.dumps(command, ensure_ascii=False).lower()
        if words and not all(word in haystack for word in words):
            continue
        matches.append({key: command.get(key) for key in ("command", "canonical_path", "cli_path", "description", "effect", "confirmation", "usage", "parameters", "scopes") if key in command} | {"command": path})
        if len(matches) >= limit:
            break
    return _result({"commands": matches, "count": len(matches)})


def _safe_name(value: object) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."} or "\x00" in value:
        raise ProgramError("bad_request", "文件名只能是不含路径的普通文件名")
    return value


def _decode_file(item: dict[str, Any]) -> bytes:
    text = item.get("text")
    encoded = item.get("content_base64")
    if (text is None) == (encoded is None):
        raise ProgramError("bad_request", "每个文件必须且只能提供 text 或 content_base64")
    if text is not None:
        if not isinstance(text, str):
            raise ProgramError("bad_request", "文件 text 必须是字符串")
        return text.encode()
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ProgramError("bad_request", "文件 content_base64 无效") from exc


def _stage_files(arguments: dict[str, Any], command: dict[str, Any], workspace: Path) -> dict[str, list[str]]:
    items = arguments.get("file_inputs", [])
    if not isinstance(items, list) or len(items) > MAX_FILES:
        raise ProgramError("bad_request", "file_inputs 必须是最多 20 项的数组")
    total = 0
    values: dict[str, list[str]] = {}
    input_root = workspace / "inputs"
    input_root.mkdir()
    params = command.get("parameters", {})
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) - {"flag", "name", "text", "content_base64"}:
            raise ProgramError("bad_request", "文件输入格式无效")
        flag = item.get("flag")
        parameter = params.get(flag) if isinstance(flag, str) else None
        if not isinstance(parameter, dict) or not parameter.get("file_input"):
            raise ProgramError("bad_request", f"--{flag} 不是该命令的文件参数")
        data = _decode_file(item)
        total += len(data)
        if total > MAX_INPUT:
            raise ProgramError("bad_request", "文件输入总大小不能超过 180 KiB")
        target = input_root / f"{index:02d}-{_safe_name(item.get('name'))}"
        target.write_bytes(data)
        relative = target.relative_to(workspace).as_posix()
        values.setdefault(flag, []).append(f"@{relative}" if parameter["file_input"] == "at" else relative)
    return values


def _validate_path(flag: str, value: str, parameter: dict[str, Any]) -> None:
    if not parameter.get("output_path") and flag not in {"output", "output-dir", "output-path"}:
        return
    path = Path(value.removeprefix("@"))
    if path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ProgramError("bad_request", f"--{flag} 只能使用安全相对路径")


def _flag_arguments(command: dict[str, Any], arguments: dict[str, Any], staged: dict[str, list[str]]) -> list[str]:
    flags = arguments.get("flags", {})
    if not isinstance(flags, dict):
        raise ProgramError("bad_request", "flags 必须是对象")
    params = command.get("parameters", {})
    result: list[str] = []
    for flag, value in flags.items():
        if flag == "yes" and command["effect"] == "destructive":
            if value is not True:
                raise ProgramError("action_forbidden", "高风险命令必须在用户确认后传入 --yes")
            continue
        parameter = params.get(flag)
        if not isinstance(parameter, dict):
            raise ProgramError("bad_request", f"命令不支持参数 --{flag}")
        if flag in FORBIDDEN_FLAGS:
            raise ProgramError("action_forbidden", f"Poco 不允许覆盖 CLI 全局参数 --{flag}")
        values = value if isinstance(value, list) else [value]
        if parameter.get("cli_type") == "bool":
            if len(values) != 1 or not isinstance(values[0], bool):
                raise ProgramError("bad_request", f"--{flag} 必须是布尔值")
            result.append(f"--{flag}={'true' if values[0] else 'false'}")
            continue
        if any(isinstance(item, (dict, list, bool)) or item is None for item in values):
            raise ProgramError("bad_request", f"--{flag} 的值类型无效")
        for item in values:
            encoded = str(item)
            if parameter.get("file_input") and encoded.startswith("@"):
                raise ProgramError("bad_request", f"--{flag} 的文件内容必须通过 file_inputs 提供")
            _validate_path(flag, encoded, parameter)
            result.extend([f"--{flag}", encoded])
    for flag, values in staged.items():
        if flag in flags:
            raise ProgramError("bad_request", f"--{flag} 不能同时出现在 flags 和 file_inputs")
        for value in values:
            result.extend([f"--{flag}", value])
    return result


def _positionals(arguments: dict[str, Any]) -> list[str]:
    values = arguments.get("positionals", [])
    if not isinstance(values, list) or len(values) > 8 or any(not isinstance(value, str) or value.startswith("-") or "\x00" in value for value in values):
        raise ProgramError("bad_request", "positionals 必须是最多 8 项的安全字符串数组")
    return values


def _binary(runtime_root: Path) -> Path:
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ProgramError("unavailable", "飞书连接器运行时仅支持 Linux amd64")
    archive = VENDOR / "lark-cli-1.0.72-linux-amd64.tar.gz"
    try:
        checksums = json.loads((VENDOR / "checksums.json").read_text())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksums[archive.name]:
            raise ValueError("checksum mismatch")
        with tarfile.open(archive, "r:gz") as source:
            member = source.getmember("lark-cli")
            if not member.isfile() or member.size > 80 * 1024 * 1024:
                raise ValueError("invalid official runtime")
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError("missing official runtime")
            target = runtime_root / "lark-cli"
            target.write_bytes(stream.read())
            target.chmod(0o700)
            return target
    except (OSError, KeyError, ValueError, tarfile.TarError) as exc:
        raise ProgramError("external_error", "官方飞书 CLI 校验失败") from exc


def _run(command: list[str], workspace: Path, runtime_root: Path, token: str, app_id: str, app_secret: str) -> tuple[str, str]:
    environment = {key: value for key, value in os.environ.items() if key in {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_DIR", "SSL_CERT_FILE", "LANG", "LC_ALL"}}
    environment.update({
        "HOME": str(runtime_root / "home"), "LARKSUITE_CLI_CONFIG_DIR": str(runtime_root / "config"),
        "LARKSUITE_CLI_APP_ID": app_id, "LARKSUITE_CLI_APP_SECRET": app_secret,
        "LARKSUITE_CLI_USER_ACCESS_TOKEN": token, "LARKSUITE_CLI_DEFAULT_AS": "user",
        "LARKSUITE_CLI_BRAND": "feishu", "LARKSUITE_CLI_REMOTE_META": "off",
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1", "CI": "1",
    })
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, cwd=workspace, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            code = process.wait(timeout=25)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            raise ProgramError("unavailable", "飞书命令执行超时；写操作可能已完成，请先查询远端状态") from exc
        stdout.seek(0); stderr.seek(0)
        out, err = stdout.read(MAX_OUTPUT + 1), stderr.read(MAX_OUTPUT + 1)
    if len(out) > MAX_OUTPUT or len(err) > MAX_OUTPUT:
        raise ProgramError("response_too_large", "飞书命令输出超过 360 KiB；请缩小查询范围")
    text_out, text_err = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    if code:
        raw = text_out.strip() or text_err.strip() or "飞书命令执行失败"
        try:
            payload = json.loads(raw)
            detail = payload.get("error", payload) if isinstance(payload, dict) else payload
            message = detail.get("message", raw) if isinstance(detail, dict) else raw
        except ValueError:
            message = raw
        lowered = str(message).lower()
        if any(word in lowered for word in ("scope", "permission", "权限")):
            raise ProgramError("insufficient_scope", str(message) + "；请由管理员授予飞书应用所需权限")
        if any(word in lowered for word in ("auth", "token", "登录")):
            raise ProgramError("authorization_required", str(message))
        raise ProgramError("external_error", str(message)[-1800:])
    return text_out, text_err


def _parse_output(text: str) -> object:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


def _collect_outputs(workspace: Path) -> list[dict[str, Any]]:
    result = []
    total = 0
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or "inputs" in path.relative_to(workspace).parts:
            continue
        data = path.read_bytes()
        total += len(data)
        if len(result) >= MAX_FILES or total > MAX_OUTPUT:
            raise ProgramError("response_too_large", "飞书命令生成的文件超过返回限制")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        item: dict[str, Any] = {"type": "resource", "uri": f"feishu-output:///{quote(path.relative_to(workspace).as_posix(), safe='/')}", "mime_type": mime}
        try:
            item["text"] = data.decode() if mime.startswith("text/") or mime in {"application/json", "application/xml"} else None
        except UnicodeDecodeError:
            item["text"] = None
        if item["text"] is None:
            item["data"] = base64.b64encode(data).decode()
            item.pop("text", None)
        result.append(item)
    return result


def _result(payload: object, resources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    structured = payload if isinstance(payload, dict) else {"result": payload}
    return {"content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False, separators=(",", ":"))}, *(resources or [])], "structured_content": structured, "is_error": False}


def invoke_tool(context: dict[str, Any]) -> dict[str, Any]:
    tool = context.get("tool_name")
    arguments = context.get("arguments")
    if tool not in POLICIES or not isinstance(arguments, dict):
        raise ProgramError("bad_request", "飞书工具或参数无效")
    if tool == "search_commands":
        return _search(arguments)
    _, commands = _load_catalog()
    key = arguments.get("command")
    command = commands.get(key) if isinstance(key, str) else None
    if command is None:
        raise ProgramError("bad_request", "未知的飞书 canonical command；请先调用 search_commands")
    expected = POLICIES[tool]
    if command["effect"] != expected[0] or command["confirmation"] != expected[1]:
        raise ProgramError("action_forbidden", "命令风险等级与所选执行工具不匹配")
    raw_flags = arguments.get("flags", {})
    if not isinstance(raw_flags, dict):
        raise ProgramError("bad_request", "flags 必须是对象")
    if command["effect"] == "destructive" and raw_flags.get("yes") is not True:
        raise ProgramError("action_forbidden", "高风险命令必须在用户确认后传入 --yes")
    credential = context.get("credentials")
    token = credential.get("access_token") if isinstance(credential, dict) else None
    if not isinstance(token, str) or not token:
        raise ProgramError("authorization_required", "飞书访问令牌不可用，请重新授权")
    configuration = context.get("configuration", {})
    public = configuration.get("public", {}) if isinstance(configuration, dict) else {}
    secret = configuration.get("secret", {}) if isinstance(configuration, dict) else {}
    app_id = public.get("app_id", "") if isinstance(public, dict) else ""
    app_secret = secret.get("app_secret", "") if isinstance(secret, dict) else ""
    with tempfile.TemporaryDirectory(prefix="poco-feishu-") as directory:
        runtime_root = Path(directory); workspace = runtime_root / "workspace"; workspace.mkdir(parents=True)
        staged = _stage_files(arguments, command, workspace)
        flags = _flag_arguments(command, arguments, staged)
        positionals = _positionals(arguments)
        binary = _binary(runtime_root)
        argv = [str(binary), *command["cli_path"].split(), "--format", "json"]
        if command["effect"] == "destructive":
            argv.append("--yes")
        argv.extend(flags)
        if positionals:
            argv.extend(["--", *positionals])
        stdout, _ = _run(argv, workspace, runtime_root, token, str(app_id), str(app_secret))
        return _result(_parse_output(stdout), _collect_outputs(workspace))
