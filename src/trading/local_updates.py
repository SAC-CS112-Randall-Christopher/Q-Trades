"""Prepare main releases off the trading path; never activate code or mutate accounts."""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trading.ownership import CollectorLock

REPOSITORY = "https://github.com/SAC-CS112-Randall-Christopher/Q-Trades.git"
RELEASE_CONTRACT = "local-paper-runtime-v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
STATUS_NAME = "main-update-status.json"
RECEIPT_NAME = ".qtrades-release.json"
REQUIRED = ("src/trading/__main__.py", "requirements-lock.txt", "apps/web/package-lock.json")


class UpdateError(RuntimeError):
    """A bounded update operation failed without changing the running installation."""


def read_record(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 256_000:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_record(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        # Bounded retries for Windows readers/virus scanners, never truncate the old record.
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1)
    finally:
        temporary.unlink(missing_ok=True)


def command(args: list[str], cwd: Path, timeout: int = 30) -> str:
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never", GIT_PAGER="cat")
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError("Update command unavailable or timed out; code is unchanged") from exc
    if result.returncode:
        # Git/npm output may contain authenticated URLs or private registry configuration.
        # Do not copy it into the API, a receipt or an exception exposed to the operator.
        raise UpdateError("Update failed; check local Git/dependency access. Code is unchanged")
    return result.stdout.strip()


def git(root: Path, *args: str) -> str:
    return command(["git", "--no-pager", "-C", str(root), *args], root)


def expected_origin(root: Path) -> None:
    urls = git(root, "remote", "get-url", "--all", "origin").splitlines()
    accepted = (REPOSITORY, REPOSITORY.removesuffix(".git"))
    if len(urls) != 1 or urls[0] not in accepted:
        raise UpdateError("This checkout does not have the expected private Q-Trades origin")
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root.resolve():
        raise UpdateError("Use the Q-Trades repository root, not a nested directory")


def artifacts_match(root: Path, receipt: dict[str, Any]) -> bool:
    assets = receipt.get("assets")
    if not isinstance(assets, dict) or not 1 <= len(assets) <= 2000:
        return False
    dist = root / "apps/web/dist"
    try:
        actual = {p.relative_to(root).as_posix(): p for p in dist.rglob("*") if p.is_file()}
        if set(actual) != set(assets):
            return False
        for name, path in actual.items():
            expected = assets[name]
            if (
                path.is_symlink()
                or not path.resolve().is_relative_to(dist.resolve())
                or path.stat().st_size > 50_000_000
                or not isinstance(expected, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                return False
        return True
    except OSError:
        return False


def source_identity(root: Path) -> dict[str, Any]:
    """Capture once at process startup: later pulls cannot relabel the running process."""
    result: dict[str, Any] = {"commit": None, "dirty": None, "kind": "unversioned"}
    try:
        expected_origin(root)
        commit = git(root, "rev-parse", "HEAD")
        if not SHA.fullmatch(commit):
            return result
        dirty = bool(git(root, "status", "--porcelain", "--untracked-files=normal"))
        receipt = read_record(root / RECEIPT_NAME)
        prepared = receipt.get("commit") == commit and receipt.get("state") == "prepared"
        if prepared and not artifacts_match(root, receipt):
            result.update(commit=commit, dirty=True, kind="modified_release")
        else:
            result.update(
                commit=commit, dirty=dirty, kind="prepared_release" if prepared else "checkout"
            )
    except UpdateError:
        pass  # Git unavailable does not prevent an already installed application from starting.
    return result


def public_status(started: dict[str, Any], status_path: Path) -> dict[str, Any]:
    """Only fixed messages and validated metadata; no paths, command output or credentials."""
    receipt = read_record(status_path)
    messages = {
        "not_checked": "Main has not been checked from this installation.",
        "checking": "Checking GitHub main; the paper worker continues unchanged.",
        "available": "Approved main code is available to prepare. It is not installed yet.",
        "no_release": "Main does not contain the application release files yet.",
        "preparing": "Building an isolated release; the running installation is unchanged.",
        "prepared": "Prepared, not activated. Startup and account checks are still required.",
        "failed": "Update check or preparation failed. The installed application was not changed.",
    }
    phase = receipt.get("phase", "not_checked")
    if not isinstance(phase, str) or phase not in messages:
        phase = "failed"
    available = receipt.get("main_commit")
    if not isinstance(available, str) or not SHA.fullmatch(available):
        available = None
    checked = receipt.get("checked_at")
    if (
        not isinstance(checked, (float, int))
        or isinstance(checked, bool)
        or not 0 < checked <= time.time() + 60
    ):
        checked = None
    # A crashed updater must not look like a worker that is still making progress.
    stale_operation = phase in {"checking", "preparing"} and (
        not isinstance(receipt.get("operation_started_at"), (float, int))
        or not math.isfinite(receipt["operation_started_at"])
        or time.time() - receipt["operation_started_at"] > 3600
    )
    if stale_operation:
        phase = "failed"
    return {
        "running_commit": started.get("commit"),
        "running_source_dirty": started.get("dirty"),
        "running_source_kind": started.get("kind", "unversioned"),
        "main_commit": available,
        "checked_at": checked,
        "phase": phase,
        "same_commit": bool(
            available and available == started.get("commit") and not started.get("dirty")
        ),
        "message": messages[phase],
        "activation": "not_connected",
        "automatic_activation": False,
    }


def validate_release_files(root: Path) -> None:
    for relative in (*REQUIRED, "configs/local-release.json"):
        if not (root / relative).is_file():
            raise UpdateError("Main does not yet contain a complete Q-Trades release")
    manifest = read_record(root / "configs/local-release.json")
    if manifest != {"contract": RELEASE_CONTRACT, "mode": "paper", "automatic_activation": False}:
        raise UpdateError("Unsupported release contract; compatibility review is required")
    tracked = git(root, "ls-files", "-z").split("\0")
    for name in filter(None, tracked):
        parts = Path(name).parts
        if any(part in {"data", ".venv", "node_modules", "__pycache__"} for part in parts):
            raise UpdateError("Release contains tracked runtime data or dependencies")
        if Path(name).name == ".env" or name.endswith(
            (".sqlite", ".sqlite3", ".db", ".pem", ".key")
        ):
            raise UpdateError("Release contains a prohibited runtime or credential file")
        if (root / name).is_symlink():
            raise UpdateError("Release contains a symlink; review before installation")


def build_release(root: Path) -> None:
    """Separate dependencies, final path from the start: venvs are not moved or reused."""
    command([sys.executable, "-m", "venv", str(root / ".venv")], root, 120)
    python = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    command(
        [str(python), "-m", "pip", "install", "--no-input", "-r", "requirements-lock.txt"],
        root,
        900,
    )
    command([str(python), "-m", "pip", "install", "--no-input", "--no-deps", "."], root, 300)
    command([str(python), "-m", "pip", "check"], root, 60)
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not npm:
        raise UpdateError("npm is not installed; the running application is unchanged")
    # Lifecycle scripts in third-party packages are not implicitly authorized.
    command(
        [npm, "--prefix", "apps/web", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
        root,
        900,
    )
    command([npm, "--prefix", "apps/web", "run", "build"], root, 300)
    command(
        [
            str(python),
            "-c",
            "from trading.api import create_app; from trading.config import Settings",
        ],
        root,
        60,
    )


class MainUpdates:
    def __init__(self, source: Path, status_dir: Path):
        self.source = source.resolve()
        self.status_dir = status_dir.resolve()
        self.status_path = self.status_dir / STATUS_NAME

    def _check(self) -> str:
        expected_origin(self.source)
        git(self.source, "fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main")
        commit = git(self.source, "rev-parse", "refs/remotes/origin/main")
        if not SHA.fullmatch(commit):
            raise UpdateError("GitHub main did not resolve to an exact commit")
        try:
            contract = json.loads(git(self.source, "show", f"{commit}:configs/local-release.json"))
        except (UpdateError, ValueError):
            contract = None
        ready = contract == {
            "contract": RELEASE_CONTRACT,
            "mode": "paper",
            "automatic_activation": False,
        }
        write_record(
            self.status_path,
            {
                "phase": "available" if ready else "no_release",
                "main_commit": commit,
                "checked_at": time.time(),
                "activation": "not_connected",
            },
        )
        return commit

    def _failure(self) -> None:
        previous = read_record(self.status_path)
        write_record(self.status_path, {**previous, "phase": "failed", "failed_at": time.time()})

    def check(self) -> dict[str, Any]:
        lock = CollectorLock(self.status_dir / "main-update.lock")
        lock.acquire()
        try:
            previous = read_record(self.status_path)
            write_record(
                self.status_path,
                {**previous, "phase": "checking", "operation_started_at": time.time()},
            )
            self._check()
            return read_record(self.status_path)
        except Exception:
            self._failure()
            raise
        finally:
            lock.release()

    def prepare(
        self, releases: Path, builder: Callable[[Path], None] = build_release
    ) -> dict[str, Any]:
        """Prepare only; never stop a process, move runtime data, reset Git, or activate."""
        releases = releases.resolve()
        if any(
            releases.is_relative_to(p) or p.is_relative_to(releases)
            for p in (self.source, self.status_dir)
        ):
            raise UpdateError("Release storage must be separate from source and runtime data")
        lock = CollectorLock(self.status_dir / "main-update.lock")
        lock.acquire()
        destination = None
        try:
            expected_origin(self.source)
            if git(self.source, "status", "--porcelain", "--untracked-files=normal"):
                raise UpdateError(
                    "Source checkout has local changes; preserve and review before preparation"
                )
            commit = self._check()
            if read_record(self.status_path).get("phase") != "available":
                raise UpdateError(
                    "The application and local-update PRs must be merged into main first"
                )
            releases.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(releases).free < 5 * 1024**3:
                raise UpdateError(
                    "Preparation requires 5 GiB free; existing releases were preserved"
                )
            destination = releases / f"{commit}-{uuid.uuid4().hex[:12]}"
            status = {
                **read_record(self.status_path),
                "phase": "preparing",
                "operation_started_at": time.time(),
            }
            write_record(self.status_path, status)
            command(
                [
                    "git",
                    "clone",
                    "--no-checkout",
                    "--single-branch",
                    "--branch",
                    "main",
                    REPOSITORY,
                    str(destination),
                ],
                releases,
                180,
            )
            git(destination, "checkout", "--detach", commit)
            if git(destination, "rev-parse", "HEAD") != commit:
                raise UpdateError("Prepared source commit does not match the selected main commit")
            validate_release_files(destination)
            builder(destination)
            if git(destination, "rev-parse", "HEAD") != commit or git(
                destination, "status", "--porcelain", "--untracked-files=normal"
            ):
                raise UpdateError("Build modified source or commit; candidate was not accepted")
            index = destination / "apps/web/dist/index.html"
            if not index.is_file():
                raise UpdateError("Dashboard build did not produce its entry page")
            assets = {
                str(p.relative_to(destination)).replace(os.sep, "/"): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in sorted((destination / "apps/web/dist").rglob("*"))
                if p.is_file()
            }
            receipt = {
                "state": "prepared",
                "commit": commit,
                "tree": git(destination, "rev-parse", "HEAD^{tree}"),
                "contract": RELEASE_CONTRACT,
                "prepared_at": time.time(),
                "assets": assets,
                "activation": "not_connected",
            }
            write_record(destination / RECEIPT_NAME, receipt)
            write_record(
                self.status_path,
                {**status, "phase": "prepared", "prepared_at": receipt["prepared_at"]},
            )
            return {**receipt, "release_directory": str(destination)}
        except Exception:
            self._failure()
            # Failed builds remain available for local diagnosis. Never delete old releases.
            if destination is not None and destination.is_dir():
                write_record(
                    destination / RECEIPT_NAME, {"state": "failed", "failed_at": time.time()}
                )
            raise
        finally:
            lock.release()
