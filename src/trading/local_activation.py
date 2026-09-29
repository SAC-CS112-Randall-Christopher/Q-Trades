"""Explicit workstation cutover with durable recovery; never restore account databases."""

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from trading.activation_state import (
    ACK_NAME,
    ACTIVATION_NAME,
    capture_accounts,
    digest,
    runtime_binding,
)
from trading.local_updates import (
    RECEIPT_NAME,
    SHA,
    MainUpdates,
    UpdateError,
    artifacts_match,
    command,
    expected_origin,
    git,
    read_record,
    source_identity,
    validate_release_files,
    write_record,
)
from trading.ownership import CollectorLock

FINAL_PHASES = {"verified", "recovered", "cancelled"}
FINANCIAL_FILES = (
    "src/trading/paper_engine.py",
    "src/trading/paper_store.py",
    "src/trading/options_engine.py",
    "src/trading/options_store.py",
)


def source_fingerprint(root: Path) -> str:
    files: list[Path] = []
    for directory in ("src/trading", "scripts"):
        files.extend(p for p in (root / directory).rglob("*") if p.suffix in {".py", ".ps1", ".cs"})
    files.extend(
        root / n for n in ("pyproject.toml", "requirements-lock.txt", "apps/web/package-lock.json")
    )
    if not files or any(not p.is_file() or p.is_symlink() for p in files):
        raise UpdateError("Source files are missing or redirected; preserve and inspect them")
    return digest(
        {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)
        }
    )


def financial_fingerprint(root: Path) -> str:
    return digest(
        {
            name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in FINANCIAL_FILES
        }
    )


def validate_prepared(root: Path, commit: str) -> dict[str, Any]:
    if not SHA.fullmatch(commit):
        raise UpdateError("Select the exact approved commit")
    expected_origin(root)
    validate_release_files(root)
    for name in ("src/trading/activation_state.py", "scripts/QTradesNativeUpdate.ps1"):
        if not (root / name).is_file():
            raise UpdateError("This prepared release predates managed activation support")
    receipt = read_record(root / RECEIPT_NAME)
    if (
        receipt.get("state") != "prepared"
        or receipt.get("commit") != commit
        or git(root, "rev-parse", "HEAD") != commit
        or receipt.get("tree") != git(root, "rev-parse", "HEAD^{tree}")
        or git(root, "status", "--porcelain", "--untracked-files=normal")
        or not artifacts_match(root, receipt)
    ):
        raise UpdateError("Prepared release is incomplete, modified or not the selected commit")
    return receipt


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise UpdateError("Local verification refused an HTTP redirect")


def local_json(endpoint: str) -> dict[str, Any]:
    if endpoint not in {"status", "installation"}:
        raise UpdateError("Unknown local verification endpoint")
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with client.open(f"http://127.0.0.1:8780/api/{endpoint}", timeout=5) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise UpdateError("Local verification response is too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise UpdateError("Local verification requires an object")
    return value


def healthy(status: dict[str, Any], *, options_required: bool) -> bool:
    names = ("paper", "options") if options_required else ("paper",)
    for name in names:
        row = status.get(name)
        if (
            not isinstance(row, dict)
            or row.get("enabled") is not True
            or row.get("running") is not True
            or not isinstance(row.get("journal"), dict)
            or row["journal"].get("balanced") is not True
        ):
            return False
        # Historical options replay has no real-time stale flag. A depleted free-data
        # budget may report a source error while its worker and ledger remain healthy.
        if name == "paper" and (
            row.get("stale") is not False or "error" not in row or row["error"] is not None
        ):
            return False
    return True


class WindowsNative:
    """Small native adapter; PowerShell validates ownership again on every mutation."""

    def __init__(self, source: Path, runtime: Path):
        if sys.platform != "win32":
            raise UpdateError("Activation runs on the Windows workstation, not the Linux checkout")
        self.source: Path = source
        self.runtime: Path = runtime

    def call(self, action: str, plan: dict[str, Any]) -> dict[str, Any]:
        directory = self.runtime / "data" / "update-receipts"
        directory.mkdir(exist_ok=True)
        request = directory / f"native-{uuid.uuid4().hex}.json"
        write_record(request, plan)
        shell = str(
            Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        try:
            result = command(
                [
                    shell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(self.source / "scripts/QTradesNativeUpdate.ps1"),
                    "-Action",
                    action,
                    "-Request",
                    str(request),
                ],
                self.source,
                120,
            )
            value = json.loads(result)
            if not isinstance(value, dict):
                raise UpdateError("Native updater returned an invalid receipt")
            return value
        finally:
            request.unlink(missing_ok=True)

    def status(self) -> dict[str, Any]:
        return local_json("status")

    def installation(self) -> dict[str, Any]:
        return local_json("installation")


class LocalActivation:
    def __init__(self, source: Path, runtime: Path, native: Any = None):
        self.source, self.runtime = source.resolve(), runtime.resolve()
        self.path = self.runtime / "data" / ACTIVATION_NAME
        self.native = native if native is not None else WindowsNative(self.source, self.runtime)

    def save(self, plan: dict[str, Any], phase: str) -> None:
        plan.update(phase=phase, updated_at=time.time())
        # Archive first: a failed archive write must not publish a successful phase.
        # Immutable per-phase receipts survive a later update or recovery attempt.
        write_record(
            self.runtime / "data/update-receipts" / f"{plan['id']}-{time.time_ns()}-{phase}.json",
            plan,
        )
        write_record(self.path, plan)

    def inspect_plan(self, release: Path, commit: str) -> dict[str, Any]:
        release = release.resolve()
        if any(
            release.is_relative_to(p) or p.is_relative_to(release)
            for p in (self.runtime, self.source)
        ):
            raise UpdateError(
                "Use a separate prepared release, not the runtime or development tree"
            )
        validate_prepared(release, commit)
        # Revalidate main membership; never promote an arbitrary PR commit by supplying its SHA.
        updater = MainUpdates(self.source, self.runtime / "data")
        updater._check()
        git(self.source, "merge-base", "--is-ancestor", commit, "refs/remotes/origin/main")
        base = {"runtime_root": str(self.runtime), "target_root": str(release), "commit": commit}
        inspection = self.native.call("inspect", base)
        if not inspection.get("owned") or not inspection.get("enabled"):
            raise UpdateError("Current installation ownership or enabled task is not established")
        previous = Path(inspection["code_root"])
        if financial_fingerprint(previous) != financial_fingerprint(release):
            raise UpdateError("Financial code differs; this update requires compatibility review")
        snapshot = capture_accounts(self.runtime)
        if not healthy(self.native.status(), options_required=snapshot["options"] is not None):
            raise UpdateError("Current accounts must report healthy before an update")
        return {
            **base,
            "id": uuid.uuid4().hex,
            "old_root": str(previous),
            "previous": inspection,
            "source_sha256": source_fingerprint(previous),
            "financial_sha256": financial_fingerprint(previous),
            "binding": snapshot["runtime_binding"],
            "created_at": time.time(),
            "baseline": snapshot,
            "automatic_activation": False,
        }

    def activate(self, release: Path, commit: str, *, apply: bool = False) -> dict[str, Any]:
        lock = CollectorLock(self.runtime / "data/main-update.lock")
        lock.acquire()
        try:
            prior = read_record(self.path)
            if self.path.exists() and prior.get("phase") not in FINAL_PHASES:
                raise UpdateError(
                    "An unfinished update exists; run recovery instead of another activation"
                )
            plan = self.inspect_plan(release, commit)
            if plan["old_root"] == plan["target_root"]:
                return {"phase": "already_running", "commit": commit, "native_changes": False}
            if not apply:
                return {"phase": "preflight_passed", "commit": commit, "native_changes": False}
            plan["desktop"] = self.native.call("prepare_desktop", plan)
            self.save(plan, "planned")
            try:
                # Journal intent before stopping: even a timeout/crash is recoverable.
                self.save(plan, "stopping")
                self.native.call("stop", plan)
                if source_fingerprint(Path(plan["old_root"])) != plan["source_sha256"]:
                    raise UpdateError("Original source changed during update; preserve it")
                plan["baseline"] = capture_accounts(self.runtime, require_stopped=True)
                if plan["baseline"]["runtime_binding"] != plan["binding"]:
                    raise UpdateError("Runtime configuration changed during update")
                self.save(plan, "stopped")
                validate_prepared(release.resolve(), commit)
                self.native.call("configure_target", plan)
                plan["launch"] = {"code_root": plan["target_root"], "commit": commit}
                self.save(plan, "starting")
                self.native.call("start", plan)
                self.wait_healthy(plan, expect_ack=True)
                self.native.call("install_desktop", plan)
                self.save(plan, "verified")
                return {"phase": "verified", "commit": commit, "checked_at": plan["updated_at"]}
            except Exception as exc:
                # Do not assume a timeout means no task change. Inspect during explicit recovery.
                self.save(plan, "recovery_required")
                raise UpdateError(
                    "Update did not verify. Run recover --apply; do not reset data"
                ) from exc
        finally:
            lock.release()

    def wait_healthy(self, plan: dict[str, Any], *, expect_ack: bool) -> None:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                actual = self.native.call("inspect", plan)
                if actual.get("code_root") != plan["launch"]["code_root"] or not actual.get(
                    "owned"
                ):
                    raise UpdateError("The running process is not the selected installation")
                if expect_ack:
                    ack = read_record(self.runtime / "data" / ACK_NAME)
                    expected = {
                        "operation": plan["id"],
                        "commit": plan["launch"]["commit"],
                        "checkpoint": digest(plan["baseline"]),
                    }
                    if ack != expected:
                        raise UpdateError("Startup account preservation is not acknowledged")
                    installation = self.native.installation()
                    if (
                        installation.get("running_commit") != plan["launch"]["commit"]
                        or installation.get("running_source_dirty") is not False
                    ):
                        raise UpdateError("Running code version is not verified")
                if healthy(
                    self.native.status(), options_required=plan["baseline"]["options"] is not None
                ):
                    return
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(1)
        raise UpdateError("The selected application did not verify within 90 seconds")

    def recover(self, *, apply: bool = False) -> dict[str, Any]:
        lock = CollectorLock(self.runtime / "data/main-update.lock")
        lock.acquire()
        try:
            plan = read_record(self.path)
            if not plan or plan.get("runtime_root") != str(self.runtime):
                raise UpdateError("No valid local recovery receipt exists")
            if plan.get("phase") in {"recovered", "cancelled"}:
                return {"phase": plan["phase"], "already_completed": True}
            if not re.fullmatch(r"[0-9a-f]{32}", str(plan.get("id", ""))):
                raise UpdateError("Invalid recovery identifier")
            required = ("old_root", "target_root", "source_sha256", "financial_sha256", "binding")
            if any(not isinstance(plan.get(key), str) or not plan[key] for key in required):
                raise UpdateError("Incomplete recovery record")
            previous, target = Path(plan["old_root"]), Path(plan["target_root"])
            if source_fingerprint(previous) != plan["source_sha256"]:
                raise UpdateError("Previous code changed; automatic restoration is unsafe")
            # CP0 supplies no schema/policy downgrade. New incompatible CPs must add a tested path.
            if financial_fingerprint(target) != plan["financial_sha256"]:
                raise UpdateError("Financial code differs; recovery requires compatibility review")
            if runtime_binding(self.runtime) != plan["binding"]:
                raise UpdateError("Runtime configuration changed; recovery needs review")
            if not apply:
                return {"phase": "recovery_preflight_passed", "native_changes": False}
            self.save(plan, "recovering")
            try:
                self.native.call("stop", plan)
                plan["baseline"] = capture_accounts(self.runtime, require_stopped=True)
                self.native.call("configure_previous", plan)
                self.native.call("restore_desktop", plan)
                identity = source_identity(previous)
                plan["launch"] = {"code_root": str(previous), "commit": identity["commit"]}
                expect_ack = (previous / "src/trading/activation_state.py").is_file()
                if expect_ack and identity["dirty"] is not False:
                    raise UpdateError("Previous managed release is modified")
                self.save(plan, "recovering_start")
                self.native.call("start", plan)
                self.wait_healthy(plan, expect_ack=expect_ack)
                self.save(plan, "recovered")
                return {"phase": "recovered", "commit": identity["commit"], "data_restored": False}
            except Exception as exc:
                self.save(plan, "recovery_required")
                raise UpdateError(
                    "Recovery needs inspection; account data was not restored or deleted"
                ) from exc
        finally:
            lock.release()
