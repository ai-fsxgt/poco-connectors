from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import os
import platform
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


AUTH_ENDPOINT = "https://qyapi.weixin.qq.com/cgi-bin/aibot/cli/get_cli_config"
VENDOR_BINARY = Path(__file__).resolve().parent / "vendor" / "wecom-cli-linux-amd64"
VENDOR_CHECKSUM = "a93389bd8957c8d719c392df1b42c0c13c3a9cbdd92b56d8434f446c3826b1a6"
MAX_OUTPUT_BYTES = 360 * 1024
MAX_INPUT_BYTES = 180 * 1024
MAX_FILES = 20


class ProgramError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:2000]
        self.retryable = retryable


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _configuration(context: dict[str, Any]) -> tuple[str, str]:
    configuration = context.get("configuration")
    if not isinstance(configuration, dict):
        return "", ""
    public = configuration.get("public")
    secret = configuration.get("secret")
    bot_id = public.get("bot_id") if isinstance(public, dict) else ""
    bot_secret = secret.get("bot_secret") if isinstance(secret, dict) else ""
    return (
        bot_id.strip() if isinstance(bot_id, str) else "",
        bot_secret.strip() if isinstance(bot_secret, str) else "",
    )


def _require_configuration(context: dict[str, Any]) -> tuple[str, str]:
    bot_id, bot_secret = _configuration(context)
    if not bot_id or not bot_secret:
        raise ProgramError("bad_request", "请配置企业微信机器人的 Bot ID 和 Secret")
    if len(bot_id) > 255 or len(bot_secret) > 4096:
        raise ProgramError("bad_request", "企业微信机器人配置过长")
    return bot_id, bot_secret


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    bot_id, bot_secret = _configuration(context)
    if context.get("require_complete") and (not bot_id or not bot_secret):
        raise ProgramError("bad_request", "请配置企业微信机器人的 Bot ID 和 Secret")
    if len(bot_id) > 255 or len(bot_secret) > 4096:
        raise ProgramError("bad_request", "企业微信机器人配置过长")
    return {}


def authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    bot_id, _ = _require_configuration(context)
    return {"identity": {"provider": "wecom", "bot_id": bot_id, "endpoint": AUTH_ENDPOINT}}


def _fetch_token(bot_id: str, bot_secret: str) -> str:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    signature = hashlib.sha256(
        f"{bot_secret}{bot_id}{timestamp}{nonce}".encode("utf-8")
    ).hexdigest()
    payload = {
        "bot_id": bot_id,
        "time": int(timestamp),
        "nonce": nonce,
        "signature": signature,
        "bind_source": 1,
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(12, connect=5), follow_redirects=False) as client:
            response = client.post(AUTH_ENDPOINT, json=payload)
    except httpx.RequestError as exc:
        raise ProgramError("unavailable", "企业微信授权服务连接失败，请稍后重试", retryable=True) from exc
    if response.status_code >= 500:
        raise ProgramError("unavailable", "企业微信授权服务暂时不可用，请稍后重试", retryable=True)
    if response.status_code >= 400:
        raise ProgramError("authorization_required", f"企业微信授权服务返回 HTTP {response.status_code}")
    try:
        result = response.json()
    except ValueError as exc:
        raise ProgramError("external_error", "企业微信授权服务未返回有效 JSON") from exc
    if not isinstance(result, dict):
        raise ProgramError("external_error", "企业微信授权服务响应格式错误")
    errcode = result.get("errcode", 0)
    if errcode not in (0, "0", None):
        message = str(result.get("errmsg") or f"企业微信授权失败（{errcode}）")
        try:
            numeric_errcode = int(errcode)
        except (TypeError, ValueError):
            numeric_errcode = -1
        code = "authorization_required" if numeric_errcode in {40001, 40014, 42001, 85004, 853004} else "external_error"
        raise ProgramError(code, message)
    token = result.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ProgramError("external_error", "企业微信授权响应缺少访问令牌")
    return token.strip()


def _account(bot_id: str, token: str) -> dict[str, Any]:
    return {
        "external_account_id": bot_id,
        "external_account_name": "企业微信机器人",
        "credential": {"values": {"access_token": token, "bot_id": bot_id}},
        "granted_scopes": [],
        "public_metadata": {"provider": "wecom", "endpoint": AUTH_ENDPOINT},
    }


def authorization_begin(context: dict[str, Any]) -> dict[str, Any]:
    bot_id, bot_secret = _require_configuration(context)
    return {"type": "account", "account": _account(bot_id, _fetch_token(bot_id, bot_secret))}


def credential_refresh(context: dict[str, Any]) -> dict[str, Any]:
    bot_id, bot_secret = _require_configuration(context)
    return {"credential": _account(bot_id, _fetch_token(bot_id, bot_secret))["credential"]}


def launch_url(_: dict[str, Any]) -> dict[str, Any]:
    return {"url": "https://work.weixin.qq.com/"}


def _load_catalog() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parent / "catalog.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        commands = payload["commands"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProgramError("external_error", "企业微信命令目录不可用") from exc
    if not isinstance(commands, list) or not all(isinstance(item, dict) for item in commands):
        raise ProgramError("external_error", "企业微信命令目录格式错误")
    return commands


def discover_tools(_: dict[str, Any]) -> dict[str, Any]:
    file_schema = _schema({
        "parameter": {"type": "string", "minLength": 1, "maxLength": 200, "description": "params 中的点号路径，例如 pages.0.page_filepath。"},
        "name": {"type": "string", "minLength": 1, "maxLength": 128},
        "text": {"type": "string", "maxLength": MAX_INPUT_BYTES},
        "content_base64": {"type": "string", "maxLength": 245760},
    }, ["parameter", "name"])
    file_schema["oneOf"] = [{"required": ["text"]}, {"required": ["content_base64"]}]
    execution_schema = _schema(
        {
            "command": {"type": "string", "minLength": 1, "maxLength": 160, "description": "search_commands 返回的 canonical command。"},
            "params": {"type": "object", "default": {}, "additionalProperties": True, "description": "源企业微信命令的 JSON 入参。"},
            "file_inputs": {
                "type": "array",
                "maxItems": MAX_FILES,
                "default": [],
                "items": file_schema,
            },
        },
        ["command"],
    )
    search_schema = _schema({
        "query": {"type": "string", "maxLength": 200, "default": ""},
        "product": {"type": "string", "maxLength": 64},
        "effect": {"type": "string", "enum": ["read", "write", "destructive"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    })
    revision = "wecom-cli-1.2.1-poco.1"
    return {"tools": [
        {"key": "search_commands", "upstream_name": "search_commands", "description": "检索当前企业微信 CLI 支持的命令、参数、风险和调用方式。执行前先调用。", "input_schema": search_schema, "effect": "read", "retry_policy": "safe", "confirmation": "not_required", "source_revision": revision},
        {"key": "execute_read_command", "upstream_name": "execute_read_command", "description": "执行目录中标记为只读的企业微信命令。", "input_schema": execution_schema, "effect": "read", "retry_policy": "safe", "confirmation": "not_required", "source_revision": revision},
        {"key": "execute_write_command", "upstream_name": "execute_write_command", "description": "执行无需额外确认的企业微信写命令。", "input_schema": execution_schema, "effect": "write", "retry_policy": "never", "confirmation": "not_required", "source_revision": revision},
        {"key": "execute_confirmed_write_command", "upstream_name": "execute_confirmed_write_command", "description": "执行需要用户确认的企业微信写命令。", "input_schema": execution_schema, "effect": "write", "retry_policy": "never", "confirmation": "user_required", "source_revision": revision},
        {"key": "execute_destructive_command", "upstream_name": "execute_destructive_command", "description": "执行删除或其他高风险企业微信命令。每次都需要用户确认。", "input_schema": execution_schema, "effect": "destructive", "retry_policy": "never", "confirmation": "user_required", "source_revision": revision},
    ]}


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    if set(arguments) - {"query", "product", "effect", "limit"}:
        raise ProgramError("bad_request", "命令检索参数包含未知字段")
    query = arguments.get("query", "")
    product = arguments.get("product")
    effect = arguments.get("effect")
    limit = arguments.get("limit", 10)
    if not isinstance(query, str) or not isinstance(product, (str, type(None))) or effect not in {None, "read", "write", "destructive"} or type(limit) is not int or not 1 <= limit <= 50:
        raise ProgramError("bad_request", "命令检索参数无效")
    words = [word for word in query.casefold().split() if word]
    matches = []
    for command in _load_catalog():
        canonical = command.get("canonical_path", "")
        if product and not canonical.startswith(f"{product}."):
            continue
        if effect and command.get("effect") != effect:
            continue
        haystack = json.dumps(command, ensure_ascii=False).casefold()
        if words and not all(word in haystack for word in words):
            continue
        matches.append({key: command.get(key) for key in ("canonical_path", "cli_path", "description", "effect", "confirmation", "usage")})
        if len(matches) >= limit:
            break
    return _result({"commands": matches, "count": len(matches)})


def _safe_filename(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 128 or Path(value).name != value or value in {".", ".."} or "\x00" in value:
        raise ProgramError("bad_request", "文件名只能是不含路径的普通文件名")
    return value


def _file_bytes(item: dict[str, Any]) -> bytes:
    has_text = "text" in item
    has_base64 = "content_base64" in item
    if has_text == has_base64:
        raise ProgramError("bad_request", "每个文件必须且只能提供 text 或 content_base64")
    if has_text:
        if not isinstance(item["text"], str):
            raise ProgramError("bad_request", "文件 text 必须是字符串")
        return item["text"].encode()
    try:
        return base64.b64decode(item["content_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise ProgramError("bad_request", "文件 content_base64 无效") from exc


def _set_path(value: object, path: str, replacement: str) -> None:
    if not isinstance(path, str):
        raise ProgramError("bad_request", "文件 parameter 必须是字符串路径")
    parts = path.split(".")
    if not parts or any(not part or part in {".", ".."} or "\x00" in part for part in parts):
        raise ProgramError("bad_request", "文件 parameter 路径无效")
    current = value
    for index, part in enumerate(parts[:-1]):
        if isinstance(current, dict):
            if part not in current:
                raise ProgramError("bad_request", f"文件 parameter 路径不存在: {path}")
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ProgramError("bad_request", f"文件 parameter 路径不存在: {path}")
    leaf = parts[-1]
    if isinstance(current, dict) and leaf in current:
        current[leaf] = replacement
    elif isinstance(current, list) and leaf.isdigit() and int(leaf) < len(current):
        current[int(leaf)] = replacement
    else:
        raise ProgramError("bad_request", f"文件 parameter 路径不存在: {path}")


def _stage_files(arguments: dict[str, Any], params: dict[str, Any], workspace: Path) -> dict[str, Any]:
    raw_files = arguments.get("file_inputs", [])
    if not isinstance(raw_files, list) or len(raw_files) > MAX_FILES:
        raise ProgramError("bad_request", "file_inputs 必须是最多 20 项的数组")
    result = copy.deepcopy(params)
    input_root = workspace / "inputs"
    input_root.mkdir()
    total = 0
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict) or set(item) - {"parameter", "name", "text", "content_base64"}:
            raise ProgramError("bad_request", "文件输入格式无效")
        data = _file_bytes(item)
        total += len(data)
        if total > MAX_INPUT_BYTES:
            raise ProgramError("bad_request", "文件输入总大小不能超过 180 KiB")
        target = input_root / f"{index:02d}-{_safe_filename(item.get('name'))}"
        target.write_bytes(data)
        _set_path(result, item.get("parameter", ""), target.relative_to(workspace).as_posix())
    return result


def _binary() -> Path:
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ProgramError("unavailable", "企业微信连接器运行时仅支持 Linux amd64")
    try:
        if hashlib.sha256(VENDOR_BINARY.read_bytes()).hexdigest() != VENDOR_CHECKSUM:
            raise ValueError("checksum mismatch")
    except (OSError, ValueError) as exc:
        raise ProgramError("external_error", "企业微信 CLI 运行时校验失败") from exc
    return VENDOR_BINARY


def _run(command: list[str], workspace: Path, runtime_root: Path, bot_id: str, bot_secret: str) -> tuple[str, str]:
    env = {key: value for key, value in os.environ.items() if key in {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_DIR", "SSL_CERT_FILE", "LANG", "LC_ALL", "PATH"}}
    config_dir = runtime_root / "config"
    config_dir.mkdir()
    log_dir = runtime_root / "logs"
    log_dir.mkdir()
    env.update({
        "WECOM_CLI_CONFIG_DIR": str(config_dir),
        "WECOM_CLI_TMP_DIR": str(workspace),
        "WECOM_CLI_LOG_DIR": str(log_dir),
        "WECOM_CLI_LOG_LEVEL": "error",
        "NO_COLOR": "1",
    })

    def execute(argv: list[str], timeout: int) -> tuple[int, str, str]:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                argv,
                cwd=workspace,
                env=env,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                raise ProgramError(
                    "unavailable",
                    "企业微信命令执行超时；写操作可能已完成，请先查询远端状态",
                    retryable=True,
                ) from exc
            stdout.seek(0)
            stderr.seek(0)
            out = stdout.read(MAX_OUTPUT_BYTES + 1)
            err = stderr.read(MAX_OUTPUT_BYTES + 1)
        if len(out) > MAX_OUTPUT_BYTES or len(err) > MAX_OUTPUT_BYTES:
            raise ProgramError("response_too_large", "企业微信命令输出超过 360 KiB；请缩小查询范围")
        return return_code, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")

    def raise_cli_failure(out_text: str, err_text: str, action: str) -> None:
        raw = out_text.strip() or err_text.strip() or f"企业微信{action}失败"
        message = raw[-1800:]
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or message)
                else:
                    message = str(payload.get("errmsg") or payload.get("message") or message)
        except ValueError:
            pass
        lowered = message.casefold()
        if any(word in lowered for word in ("auth", "token", "登录", "授权", "853000", "853004", "凭据", "bot_id", "secret")):
            raise ProgramError("authorization_required", message)
        if any(word in lowered for word in ("permission", "scope", "权限")):
            raise ProgramError("insufficient_scope", message)
        raise ProgramError("external_error", message)

    binary = command[0]
    auth_code, auth_out, auth_err = execute(
        [binary, "auth", "init", "--bot-id", bot_id, "--secret", bot_secret],
        timeout=10,
    )
    if auth_code:
        raise_cli_failure(auth_out, auth_err, "授权初始化")

    return_code, out_text, err_text = execute(command, timeout=20)
    if return_code:
        raise_cli_failure(out_text, err_text, "命令执行")
    return out_text, err_text


def _parse_output(text: str) -> object:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        lines = [line for line in text.splitlines() if line.strip()]
        try:
            return [json.loads(line) for line in lines]
        except ValueError:
            return {"text": text}


def _collect_outputs(workspace: Path) -> list[dict[str, Any]]:
    result = []
    total = 0
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or "inputs" in path.relative_to(workspace).parts:
            continue
        if path.is_symlink():
            raise ProgramError("external_error", "企业微信命令生成了不安全的符号链接")
        data = path.read_bytes()
        total += len(data)
        if len(result) >= MAX_FILES or total > MAX_OUTPUT_BYTES:
            raise ProgramError("response_too_large", "企业微信命令生成的文件超过返回限制")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        item: dict[str, Any] = {"type": "resource", "uri": f"wecom-output:///{quote(path.relative_to(workspace).as_posix(), safe='/')}", "mime_type": mime}
        if mime.startswith("text/") or mime in {"application/json", "application/xml"}:
            try:
                item["text"] = data.decode()
            except UnicodeDecodeError:
                item["data"] = base64.b64encode(data).decode()
        else:
            item["data"] = base64.b64encode(data).decode()
        result.append(item)
    return result


def _result(payload: object, resources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    structured = payload if isinstance(payload, dict) else {"result": payload}
    return {
        "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False, separators=(",", ":"))}, *(resources or [])],
        "structured_content": structured,
        "is_error": False,
    }


def invoke_tool(context: dict[str, Any]) -> dict[str, Any]:
    tool = context.get("tool_name")
    arguments = context.get("arguments")
    policies = {
        "execute_read_command": ("read", "not_required"),
        "execute_write_command": ("write", "not_required"),
        "execute_confirmed_write_command": ("write", "user_required"),
        "execute_destructive_command": ("destructive", "user_required"),
    }
    if tool == "search_commands":
        if not isinstance(arguments, dict):
            raise ProgramError("bad_request", "命令检索参数无效")
        return _search(arguments)
    if tool not in policies or not isinstance(arguments, dict):
        raise ProgramError("bad_request", "企业微信工具或参数无效")
    command_name = arguments.get("command")
    command = next((item for item in _load_catalog() if item.get("canonical_path") == command_name), None)
    if command is None:
        raise ProgramError("bad_request", "未知的企业微信命令；请先调用 search_commands")
    expected_effect, expected_confirmation = policies[tool]
    if command.get("effect") != expected_effect or command.get("confirmation") != expected_confirmation:
        raise ProgramError("action_forbidden", "命令风险等级与所选执行工具不匹配")
    params = arguments.get("params", {})
    if not isinstance(params, dict):
        raise ProgramError("bad_request", "params 必须是对象")
    bot_id, bot_secret = _require_configuration(context)
    credentials = context.get("credentials")
    values = credentials.get("values") if isinstance(credentials, dict) else None
    token = values.get("access_token") if isinstance(values, dict) else None
    if not isinstance(token, str) or not token:
        token = credentials.get("access_token") if isinstance(credentials, dict) else None
    if not isinstance(token, str) or not token:
        raise ProgramError("authorization_required", "企业微信访问令牌不可用，请重新授权")
    cli_path = command.get("cli_path")
    if not isinstance(cli_path, str) or not cli_path:
        raise ProgramError("external_error", "企业微信命令目录缺少执行路径")
    with tempfile.TemporaryDirectory(prefix="poco-wecom-") as directory:
        runtime_root = Path(directory)
        workspace = runtime_root / "workspace"
        workspace.mkdir()
        prepared = _stage_files(arguments, params, workspace)
        argv = [str(_binary()), *cli_path.split(), "--json", json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))]
        stdout, _ = _run(argv, workspace, runtime_root, bot_id, bot_secret)
        return _result(_parse_output(stdout), _collect_outputs(workspace))


def _operation_context(request: dict[str, Any]) -> dict[str, Any]:
    context = request.get("context")
    if not isinstance(context, dict):
        raise ProgramError("bad_request", "连接器上下文无效")
    return context


OPERATIONS = {
    "configuration_validate": configuration_validate,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "credential_refresh": credential_refresh,
    "launch_url": launch_url,
    "tools_discover": discover_tools,
    "tool_invoke": invoke_tool,
}


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("protocol_version") != 1:
            raise ProgramError("bad_request", "连接器协议版本错误")
        handler = OPERATIONS.get(request.get("operation"))
        if handler is None:
            raise ProgramError("bad_request", "不支持的连接器操作")
        result = handler(_operation_context(request))
        response = {"protocol_version": 1, "ok": True, "result": result}
    except ProgramError as exc:
        response = {"protocol_version": 1, "ok": False, "error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable}}
    except Exception:
        response = {"protocol_version": 1, "ok": False, "error": {"code": "external_error", "message": "企业微信连接器运行失败", "retryable": False}}
    encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > 950_000:
        encoded = json.dumps({"protocol_version": 1, "ok": False, "error": {"code": "response_too_large", "message": "结果超过 Poco 单次返回限制；请缩小查询范围。写操作可能已完成，请先查询状态。", "retryable": False}}, ensure_ascii=False)
    print(encoded)


if __name__ == "__main__":
    main()
