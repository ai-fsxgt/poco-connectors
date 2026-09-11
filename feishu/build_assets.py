"""Validate the pinned official Lark CLI archive and command catalog."""

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=root / "provider/vendor/lark-cli-1.0.72-linux-amd64.tar.gz")
    parser.add_argument("--catalog", type=Path, default=root / "provider/catalog.json")
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()

    actual = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    if actual != args.sha256:
        raise SystemExit(f"archive checksum mismatch: {actual}")
    with tarfile.open(args.archive, "r:gz") as archive:
        member = archive.getmember("lark-cli")
        if not member.isfile() or member.size == 0:
            raise SystemExit("official archive does not contain a regular lark-cli binary")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    commands = catalog.get("commands")
    if not isinstance(commands, list) or not commands:
        raise SystemExit("catalog must contain commands")
    if any(not isinstance(item, dict) or not item.get("canonical_path") for item in commands):
        raise SystemExit("catalog contains an invalid command")
    print(f"Validated official archive and {len(commands)} catalog commands")


if __name__ == "__main__":
    main()
