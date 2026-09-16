"""Generate and validate the pinned official Lark CLI command catalog."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any


CLI_VERSION = "1.0.95"
ARCHIVE_NAME = f"lark-cli-{CLI_VERSION}-linux-amd64.tar.gz"
ARCHIVE_SHA256 = "7da92d426b7d000908c76a36b87a7d0357c270debf4c7149bbc6010b20d2541e"
OFFICIAL_SCOPES_SHA256 = "0756ce2586c91eee16cb8f284050b098ca4943c06760b687426d3f5043af3e16"
EXPECTED_API_COMMANDS = 234
EXPECTED_SHORTCUT_COMMANDS = 516
MAX_OAUTH_SCOPES = 200
SUPPORTED_ROOTS = (
    "application",
    "approval",
    "apps",
    "attendance",
    "base",
    "calendar",
    "contact",
    "docs",
    "drive",
    "im",
    "mail",
    "markdown",
    "mindnotes",
    "minutes",
    "note",
    "okr",
    "sheets",
    "slides",
    "task",
    "vc",
    "whiteboard",
    "wiki",
)
GLOBAL_FLAGS = {"as", "debug", "format", "help", "jq", "json", "profile", "verbose"}
REPEATABLE_TYPES = {"ints", "intSlice", "stringArray", "strings", "stringSlice"}
INTEGER_TYPES = {"int", "int32", "int64", "uint", "uint32", "uint64"}
FLOAT_TYPES = {"float", "float32", "float64"}
KNOWN_CLI_TYPES = {
    "bool",
    "duration",
    "string",
    *REPEATABLE_TYPES,
    *INTEGER_TYPES,
    *FLOAT_TYPES,
}
OUTPUT_FLAGS = {"output", "output-dir", "output-path", "save-path"}
UNSUPPORTED_COMMANDS = {
    "apps +env-pull",
    "apps +git-credential-init",
    "apps +git-credential-list",
    "apps +git-credential-remove",
    "apps +html-publish",
    "apps +init",
    "apps +plugin-install",
    "apps +plugin-list",
    "apps +plugin-uninstall",
    "calendar calendars create",
    "calendar calendars delete",
    "calendar calendars patch",
    "im +messages-reply",
    "im +messages-send",
    "im chat.join_requests handle",
    "im chat.join_requests list",
    "im chat.moderation get",
    "im chat.moderation update",
    "im chat.user_setting batch_update",
    "mail +share-to-chat",
    "sheets spreadsheets get",
    "sheets spreadsheets patch",
    "vc +meeting-screenshot",
}


def _run(binary: Path, home: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "LARKSUITE_CLI_CONFIG_DIR": str(home / "config"),
            "LARKSUITE_CLI_BRAND": "feishu",
            "LARKSUITE_CLI_REMOTE_META": "off",
            "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
            "NO_COLOR": "1",
            "CI": "1",
        }
    )
    process = subprocess.run(
        [str(binary), *arguments],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=30,
    )
    if process.returncode:
        detail = process.stdout.strip() or process.stderr.strip()
        raise RuntimeError(f"lark-cli {' '.join(arguments)} failed: {detail}")
    return process.stdout


def _children(help_text: str) -> list[str]:
    result = []
    for heading in ("Available Commands", "Additional Commands"):
        match = re.search(
            rf"^{heading}:\n(?P<body>.*?)(?:\n\n|\Z)",
            help_text,
            re.MULTILINE | re.DOTALL,
        )
        if match is None:
            continue
        for line in match.group("body").splitlines():
            child = re.match(r"^\s{2}([^\s]+)\s+.*$", line)
            if child is not None:
                result.append(child.group(1))
    return result


def _command_leaves(binary: Path, home: Path) -> list[tuple[list[str], str]]:
    leaves: list[tuple[list[str], str]] = []

    def walk(path: list[str]) -> None:
        help_text = _run(binary, home, *path, "--help")
        children = _children(help_text)
        if not children:
            leaves.append((path, help_text))
            return
        for child in children:
            walk([*path, child])

    for root in SUPPORTED_ROOTS:
        walk([root])
    return leaves


def _parameter_type(cli_type: str) -> str:
    if cli_type == "bool":
        return "boolean"
    if cli_type in REPEATABLE_TYPES:
        return "array"
    if cli_type in INTEGER_TYPES:
        return "integer"
    if cli_type in FLOAT_TYPES:
        return "number"
    return "string"


def _normalize_cli_type(declared_type: str | None) -> str:
    if declared_type is None:
        return "bool"
    if declared_type in KNOWN_CLI_TYPES:
        return declared_type
    if declared_type.lower() in {"true", "false"} or "=" in declared_type:
        return "bool"
    return "string"


def _file_mode(name: str, description: str) -> str | None:
    lowered = description.lower()
    if name in OUTPUT_FLAGS or name.startswith("output-"):
        return None
    if "@file" in lowered:
        return "at"
    if "remote file path" in lowered:
        return None
    path_name = name in {
        "attach",
        "audio",
        "file",
        "image",
        "media",
        "slide",
        "video",
        "video-cover",
    } or name.endswith(("-file", "-image", "-path"))
    path_description = any(
        phrase in lowered
        for phrase in (
            "cwd-relative local path",
            "file path",
            "file to upload",
            "local file",
            "local image path",
            "local path",
            "read from file",
        )
    ) or re.search(r"path to (?:a |an )?.*file", lowered) is not None
    return "path" if path_name and path_description else None


def _shortcut_parameters(help_text: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    match = re.search(
        r"^Flags:\n(?P<body>.*?)(?:\n\n|\Z)",
        help_text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return result
    for line in match.group("body").splitlines():
        parts = re.split(r"\s{2,}", line.strip(), maxsplit=1)
        if len(parts) != 2 or "--" not in parts[0]:
            continue
        flag = re.fullmatch(
            r"(?:-[A-Za-z0-9],\s+)?--([A-Za-z0-9][A-Za-z0-9-]*)(?:\s+(\S+))?",
            parts[0],
        )
        if flag is None:
            continue
        name, declared_type = flag.groups()
        if name in GLOBAL_FLAGS:
            continue
        cli_type = _normalize_cli_type(declared_type)
        description = parts[1].strip()
        parameter: dict[str, Any] = {
            "type": _parameter_type(cli_type),
            "cli_type": cli_type,
            "description": description,
        }
        file_mode = _file_mode(name, description)
        if file_mode is not None:
            parameter["file_input"] = file_mode
        if name in OUTPUT_FLAGS or name.startswith("output-"):
            parameter["output_path"] = True
        result[name] = parameter
    return result


def _risk(help_text: str) -> str:
    match = re.search(r"^Risk:\s+(read|write|high-risk-write)\b", help_text, re.MULTILINE)
    if match is None:
        raise ValueError("command help is missing a supported risk level")
    return match.group(1)


def _usage(help_text: str) -> str:
    match = re.search(r"^Usage:\n\s{2}(lark-cli .+)$", help_text, re.MULTILINE)
    if match is None:
        raise ValueError("command help is missing usage")
    return match.group(1)


def _description(help_text: str) -> str:
    return help_text.split("\n\n", 1)[0].strip()


def _load_shortcut_scopes(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("cli_version") != CLI_VERSION:
        raise ValueError("shortcut scope metadata does not match the pinned CLI")
    shortcuts = payload.get("shortcuts")
    if not isinstance(shortcuts, list) or not shortcuts:
        raise ValueError("shortcut scope metadata is empty")
    result: dict[str, dict[str, Any]] = {}
    for shortcut in shortcuts:
        if not isinstance(shortcut, dict):
            raise ValueError("shortcut scope metadata contains an invalid entry")
        path_value = shortcut.get("canonical_path")
        auth_types = shortcut.get("auth_types")
        user_scopes = shortcut.get("user_scopes")
        if (
            not isinstance(path_value, str)
            or not isinstance(auth_types, list)
            or not all(isinstance(item, str) for item in auth_types)
            or not isinstance(user_scopes, list)
            or not all(isinstance(item, str) for item in user_scopes)
        ):
            raise ValueError("shortcut scope metadata contains invalid fields")
        if path_value in result:
            raise ValueError(f"duplicate shortcut scope metadata: {path_value}")
        result[path_value] = shortcut
    return result


def _load_official_user_scopes(path: Path) -> set[str]:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != OFFICIAL_SCOPES_SHA256:
        raise ValueError("official scope metadata checksum does not match")
    payload = json.loads(data)
    if payload.get("version") != CLI_VERSION:
        raise ValueError("official scope metadata does not match the pinned CLI")
    services = payload.get("scopes")
    if not isinstance(services, dict) or not services:
        raise ValueError("official scope metadata is empty")
    result = {"offline_access"}
    for service, metadata in services.items():
        if not isinstance(service, str) or not isinstance(metadata, dict):
            raise ValueError("official scope metadata contains an invalid service")
        user_scopes = metadata.get("user_scopes")
        if not isinstance(user_scopes, list) or not all(
            isinstance(scope, str) and scope for scope in user_scopes
        ):
            raise ValueError(
                f"official scope metadata contains invalid user scopes: {service}"
            )
        result.update(user_scopes)
    return result


def _select_oauth_scopes(
    commands: list[dict[str, Any]],
    official_user_scopes: set[str],
) -> list[str]:
    selected = {"offline_access"}
    for command in commands:
        unavailable = set(command["scopes"]) - official_user_scopes
        if unavailable:
            raise ValueError(
                f"command uses unpublished user scopes: {command['canonical_path']}"
            )
        if command["source"] == "shortcut":
            selected.update(command["scopes"])

    pending = [
        command
        for command in commands
        if command["source"] == "api"
        and not selected.intersection(command["scopes"])
    ]
    while pending:
        coverage: dict[str, int] = {}
        for command in pending:
            for scope in command["scopes"]:
                coverage[scope] = coverage.get(scope, 0) + 1
        if not coverage:
            raise ValueError("an API command has no usable OAuth scope")
        chosen = min(coverage, key=lambda scope: (-coverage[scope], scope))
        selected.add(chosen)
        pending = [
            command for command in pending if chosen not in command["scopes"]
        ]

    result = sorted(selected)
    if len(result) > MAX_OAUTH_SCOPES:
        raise ValueError(
            f"OAuth scope selection exceeds Feishu's {MAX_OAUTH_SCOPES}-scope limit"
        )
    return result


def _generate_catalog(
    binary: Path,
    shortcut_scope_path: Path,
    official_scope_path: Path,
) -> dict[str, Any]:
    shortcut_scopes = _load_shortcut_scopes(shortcut_scope_path)
    official_user_scopes = _load_official_user_scopes(official_scope_path)
    with tempfile.TemporaryDirectory(prefix="poco-feishu-catalog-") as directory:
        home = Path(directory)
        version = _run(binary, home, "--version").strip()
        if version != f"lark-cli version {CLI_VERSION}":
            raise ValueError(f"unexpected host CLI version: {version}")
        commands = []
        for path, help_text in _command_leaves(binary, home):
            canonical_path = " ".join(path)
            if canonical_path in UNSUPPORTED_COMMANDS:
                continue
            source = "shortcut" if any(part.startswith("+") for part in path) else "api"
            schema = None
            scopes: list[str] = []
            description = _description(help_text)
            if source == "api":
                schema_payload = json.loads(_run(binary, home, "schema", ".".join(path)))
                if not isinstance(schema_payload, dict):
                    raise ValueError(
                        f"unexpected schema for {' '.join(path)}: "
                        f"{type(schema_payload).__name__}"
                    )
                metadata = schema_payload.get("_meta", {})
                access_tokens = metadata.get("access_tokens", [])
                if isinstance(access_tokens, list) and "user" not in access_tokens:
                    continue
                schema = schema_payload.get("inputSchema")
                raw_scopes = metadata.get("scopes", [])
                if not isinstance(raw_scopes, list) or not all(
                    isinstance(scope, str) and scope for scope in raw_scopes
                ):
                    raise ValueError(f"API scopes are invalid: {canonical_path}")
                scopes = [
                    scope for scope in raw_scopes if scope in official_user_scopes
                ]
                if not scopes:
                    raise ValueError(
                        f"API has no published user scope: {canonical_path}"
                    )
                description = schema_payload.get("description") or description
            else:
                shortcut = shortcut_scopes.get(canonical_path)
                if shortcut is None:
                    raise ValueError(
                        f"shortcut scope metadata is missing: {canonical_path}"
                    )
                if "user" not in shortcut["auth_types"]:
                    continue
                scopes = shortcut["user_scopes"]
                if set(scopes) - official_user_scopes:
                    raise ValueError(
                        f"shortcut uses unpublished user scopes: {canonical_path}"
                    )
            commands.append(
                {
                    "canonical_path": canonical_path,
                    "cli_path": canonical_path,
                    "description": description,
                    "details": help_text.strip(),
                    "help_exit_code": 0,
                    "input_schema": schema,
                    "parameters": _shortcut_parameters(help_text) if source == "shortcut" else {},
                    "risk": _risk(help_text),
                    "scopes": scopes,
                    "source": source,
                    "usage": _usage(help_text),
                }
            )
    commands.sort(key=lambda item: item["canonical_path"])
    return {
        "cli_version": CLI_VERSION,
        "oauth_scopes": _select_oauth_scopes(commands, official_user_scopes),
        "commands": commands,
    }


def _validate_archive(archive: Path, sha256: str) -> None:
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != sha256:
        raise SystemExit(f"archive checksum mismatch: {actual}")
    with tarfile.open(archive, "r:gz") as source:
        member = source.getmember("lark-cli")
        if not member.isfile() or member.size == 0:
            raise SystemExit("official archive does not contain a regular lark-cli binary")


def _validate_catalog(catalog_path: Path, official_scope_path: Path) -> int:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    official_user_scopes = _load_official_user_scopes(official_scope_path)
    if catalog.get("cli_version") != CLI_VERSION:
        raise SystemExit("catalog CLI version does not match the pinned runtime")
    commands = catalog.get("commands")
    if not isinstance(commands, list) or not commands:
        raise SystemExit("catalog must contain commands")
    paths = []
    source_counts = {"api": 0, "shortcut": 0}
    for command in commands:
        if not isinstance(command, dict) or not isinstance(command.get("canonical_path"), str):
            raise SystemExit("catalog contains an invalid command")
        if command.get("risk") not in {"read", "write", "high-risk-write"}:
            raise SystemExit(f"catalog contains invalid risk: {command['canonical_path']}")
        source = command.get("source")
        if source not in source_counts:
            raise SystemExit(f"catalog contains invalid source: {command['canonical_path']}")
        parameters = command.get("parameters")
        if source == "shortcut" and not isinstance(parameters, dict):
            raise SystemExit(f"shortcut parameters are unavailable: {command['canonical_path']}")
        scopes = command.get("scopes")
        if not isinstance(scopes, list) or not all(
            isinstance(scope, str) and scope for scope in scopes
        ):
            raise SystemExit(f"command scopes are invalid: {command['canonical_path']}")
        if source == "api" and not scopes:
            raise SystemExit(f"API scopes are unavailable: {command['canonical_path']}")
        if set(scopes) - official_user_scopes:
            raise SystemExit(
                f"catalog contains unpublished user scopes: {command['canonical_path']}"
            )
        source_counts[source] += 1
        paths.append(command["canonical_path"])
    if len(paths) != len(set(paths)):
        raise SystemExit("catalog contains duplicate command paths")
    if source_counts != {
        "api": EXPECTED_API_COMMANDS,
        "shortcut": EXPECTED_SHORTCUT_COMMANDS,
    }:
        raise SystemExit(f"catalog command counts are incomplete: {source_counts}")
    if UNSUPPORTED_COMMANDS.intersection(paths):
        raise SystemExit("catalog contains commands incompatible with isolated execution")
    expected_oauth_scopes = _select_oauth_scopes(commands, official_user_scopes)
    if catalog.get("oauth_scopes") != expected_oauth_scopes:
        raise SystemExit("catalog OAuth scopes do not match the supported commands")
    return len(commands)


def _validate_upstream_catalog(catalog_root: Path) -> None:
    manifest = json.loads((catalog_root / "manifest.json").read_text(encoding="utf-8"))
    services = manifest.get("services")
    if not isinstance(services, list) or not services:
        raise SystemExit("upstream catalog manifest has no services")
    for service in services:
        if not isinstance(service, dict) or not isinstance(service.get("file"), str):
            raise SystemExit("upstream catalog manifest contains an invalid service")
        path = catalog_root / service["file"]
        data = path.read_bytes()
        if len(data) != service.get("size"):
            raise SystemExit(f"upstream catalog size mismatch: {service['file']}")
        if hashlib.sha256(data).hexdigest() != service.get("sha256"):
            raise SystemExit(f"upstream catalog checksum mismatch: {service['file']}")


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=root / "provider/vendor" / ARCHIVE_NAME)
    parser.add_argument("--catalog", type=Path, default=root / "provider/catalog.json")
    parser.add_argument(
        "--shortcut-scopes",
        type=Path,
        default=root / "provider/shortcut_scopes.json",
    )
    parser.add_argument(
        "--official-scopes",
        type=Path,
        default=root / "catalog/scopes.json",
    )
    parser.add_argument("--upstream-catalog", type=Path, default=root / "catalog")
    parser.add_argument("--sha256", default=ARCHIVE_SHA256)
    parser.add_argument(
        "--generate-from",
        type=Path,
        help="Official lark-cli binary for the current host; regenerates --catalog before validation.",
    )
    args = parser.parse_args()

    if args.generate_from is not None:
        generated = _generate_catalog(
            args.generate_from.resolve(),
            args.shortcut_scopes,
            args.official_scopes,
        )
        args.catalog.write_text(
            json.dumps(generated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    _validate_archive(args.archive, args.sha256)
    _validate_upstream_catalog(args.upstream_catalog)
    count = _validate_catalog(args.catalog, args.official_scopes)
    print(f"Validated official lark-cli {CLI_VERSION} archive and {count} catalog commands")


if __name__ == "__main__":
    main()
