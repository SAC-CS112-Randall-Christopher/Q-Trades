"""Append one MCP observer entry without rewriting unrelated Codex configuration."""

import argparse
import copy
import hashlib
import json
import math
import os
import stat
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any

MAX_CONFIG_BYTES = 262144
SERVER = "qtrades_research"
TOOLS = [
    "research_status",
    "research_task",
    "research_lessons",
    "research_quality",
    "research_capabilities",
]


class RegistrationError(ValueError):
    """A safe error code, never a configuration value or parser error excerpt."""


def regular(path: Path) -> Path:
    if not path.is_absolute() or path.drive.startswith("\\\\"):
        raise RegistrationError("absolute_local_path_required")
    for component in (path, *path.parents):
        observed = component.lstat()
        if stat.S_ISLNK(observed.st_mode) or getattr(observed, "st_file_attributes", 0) & 0x400:
            raise RegistrationError("redirected_path_refused")
        if component != path and not stat.S_ISDIR(observed.st_mode):
            raise RegistrationError("regular_parent_required")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RegistrationError("regular_file_required")
    return path


def read_config(path: Path) -> bytes:
    regular(path)
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise RegistrationError("configuration_size_refused")
    with path.open("rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise RegistrationError("regular_file_required")
        raw = source.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise RegistrationError("configuration_size_refused")
    return raw


def parse(raw: bytes) -> dict[str, Any]:
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise RegistrationError("configuration_parse_refused") from None


def equal(left: Any, right: Any) -> bool:
    """Preserve TOML types, including bool/int distinctions and legal NaN values."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(equal(v, right[k]) for k, v in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(
            equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, float) and math.isnan(left):
        return math.isnan(right)
    return bool(left == right)


def private_file(path: Path, raw: bytes) -> None:
    # POSIX mode0600; Windows inherits the existing private config directory ACL.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(raw)
        destination.flush()
        os.fsync(destination.fileno())


def register(python: Path, artifact: Path, config: Path) -> dict[str, Any]:
    python, artifact = regular(python), regular(artifact)
    original = read_config(config)
    original_sha = hashlib.sha256(original).hexdigest()
    parsed = parse(original)
    selected = {
        "command": str(python),
        "args": ["-I", "-B", "-u", str(artifact)],
        "enabled_tools": TOOLS,
        "startup_timeout_sec": 15,
        "tool_timeout_sec": 20,
    }
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise RegistrationError("server_table_refused")
    if SERVER in servers:
        if not equal(servers[SERVER], selected):
            raise RegistrationError("different_existing_entry_refused")
        return {"status": "already_registered", "server": SERVER, "config_sha256": original_sha}

    newline = "\r\n" if b"\r\n" in original else "\n"
    entry = newline.join(
        [f"[mcp_servers.{SERVER}]"]
        + [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in selected.items()]
        + [""]
    ).encode("utf-8")
    suffix = b"" if original.endswith(b"\n") or not original else newline.encode()
    updated = original + suffix + newline.encode() + entry
    if len(updated) > MAX_CONFIG_BYTES:
        raise RegistrationError("configuration_size_refused")
    expected = copy.deepcopy(parsed)
    expected.setdefault("mcp_servers", {})[SERVER] = selected
    if not equal(parse(updated), expected):
        raise RegistrationError("configuration_preservation_refused")

    token = uuid.uuid4().hex
    backup = config.with_name(f".{config.name}.qtrades-{token}.backup")
    stage = config.with_name(f".{config.name}.qtrades-{token}.stage")
    private_file(backup, original)
    try:
        if read_config(backup) != original:
            raise RegistrationError("backup_verification_refused")
        private_file(stage, updated)
        if read_config(stage) != updated:
            raise RegistrationError("staging_verification_refused")
        # Detect intervening edits immediately before publication. This check and
        # os.replace are separate operations, not an interprocess compare-and-swap.
        current_sha = hashlib.sha256(read_config(config)).hexdigest()
        if current_sha != original_sha:
            raise RegistrationError("configuration_changed_before_publication")
        os.replace(stage, config)
        try:
            published = read_config(config)
            if published != updated or not equal(parse(published), expected):
                raise RegistrationError("registration_acknowledgment_unknown")
        except (OSError, ValueError):
            raise RegistrationError("registration_acknowledgment_unknown") from None
    finally:
        # Delete only our own uniquely named unpublished staging file. Retain the
        # private original backup on success or failure; never restore over edits.
        if stage.exists():
            stage.unlink()
    return {
        "status": "registered",
        "server": SERVER,
        "original_sha256": original_sha,
        "config_sha256": hashlib.sha256(updated).hexdigest(),
        "backup": str(backup),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preserve Codex configuration and register Q-Trades"
    )
    parser.add_argument(
        "--python", type=Path, required=True, help="Previously verified interpreter"
    )
    parser.add_argument("--artifact", type=Path, required=True, help="Frozen standalone observer")
    parser.add_argument("--config", type=Path, default=Path.home() / ".codex" / "config.toml")
    args = parser.parse_args(argv)
    try:
        result = register(args.python, args.artifact, args.config)
    except RegistrationError as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        return 1
    except OSError:
        print(
            json.dumps({"status": "refused", "reason": "filesystem_operation_failed"}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
