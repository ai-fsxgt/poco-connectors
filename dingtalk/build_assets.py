"""Build the pinned command catalog and runtime archives from DWS source outputs."""

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


def write_runtime_archive(binary: Path, archive: Path) -> None:
    info = tarfile.TarInfo("dws")
    info.size = binary.stat().st_size
    info.mode = 0o755
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    with (
        archive.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        binary.open("rb") as source,
        tarfile.open(fileobj=compressed, mode="w") as target,
    ):
        target.addfile(info, source)


def command_entry(tool: dict[str, Any], binary: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(binary), *tool["cli_path"].split(), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    usage = re.search(r"Usage:\s*\n\s*(.+)", result.stdout)
    flag_help = (
        result.stdout.split("Flags:\n", 1)[1].split("When to use:", 1)[0]
        if "Flags:\n" in result.stdout
        else ""
    )
    flag_types = dict(
        re.findall(
            r"--([\w-]+)\s+(stringArray|strings|ints|int64|int32|int|float64|float32|uint|duration|string)\s",
            flag_help,
        )
    )
    declared_flags = set(re.findall(r"--([\w-]+)(?:\s|$)", flag_help, re.MULTILINE))
    entry = {
        key: tool[key]
        for key in (
            "canonical_path",
            "cli_path",
            "description",
            "agent_summary",
            "effect",
            "confirmation",
            "risk",
            "availability",
            "constraints",
            "examples",
            "use_when",
            "avoid_when",
        )
        if key in tool
    }
    entry["usage"] = usage.group(1) if usage else f"dws {tool['cli_path']} [flags]"
    entry["parameters"] = {}
    for name, parameter in tool.get("parameters", {}).items():
        if declared_flags and name not in declared_flags:
            raise ValueError(
                f"Schema flag missing from help: {tool['canonical_path']} --{name}"
            )
        default_cli_type = {
            "boolean": "bool",
            "integer": "int",
            "number": "float64",
            "array": "stringArray",
        }.get(parameter.get("type"), "string")
        entry["parameters"][name] = {
            **{
                key: value
                for key, value in parameter.items()
                if key
                in {
                    "type",
                    "description",
                    "required",
                    "cli_required",
                    "default",
                    "enum",
                    "required_when",
                    "format",
                }
            },
            "cli_type": flag_types.get(name, default_cli_type),
        }
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--dws", type=Path, required=True)
    parser.add_argument("--binary-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    schema = json.loads(args.schema.read_text())
    tools = [
        tool
        for product in schema["products"]
        for tool in product["tools"]
        if tool.get("availability") == "available"
    ]
    with ThreadPoolExecutor(max_workers=16) as executor:
        commands = list(executor.map(lambda tool: command_entry(tool, args.dws), tools))
    catalog = root / "provider" / "catalog.json"
    catalog.write_text(
        json.dumps(
            {"dws_version": "1.0.61", "commands": commands},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )
    vendor = root / "provider" / "vendor"
    vendor.mkdir(exist_ok=True)
    checksums = {}
    for arch in ("amd64",):
        binary = args.binary_dir / f"poco-dws-linux-{arch}"
        archive = vendor / f"dws-linux-{arch}.tar.gz"
        write_runtime_archive(binary, archive)
        checksums[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (vendor / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")
    print(f"Built {len(commands)} commands and one Linux runtime archive")


if __name__ == "__main__":
    main()
