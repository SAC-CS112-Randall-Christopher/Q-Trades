"""Windowless owner for the project's two scheduled PowerShell supervisors."""

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def supervisor_command(
    kind: str, profile: str, runtime_root: Path | None = None
) -> list[str]:
    if kind not in ("paper", "models") or profile not in ("CpuTwoProcessors", "CpuElastic"):
        raise ValueError("Unknown project service")
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = "Run-PaperExperiment.ps1" if kind == "paper" else "Run-ResearchRuntime.ps1"
    command = [str(shell), "-NoProfile", "-NonInteractive", "-File", str(ROOT / "scripts" / script)]
    if runtime_root is not None:
        if kind != "paper":
            raise ValueError("Managed paper updates cannot redirect the model runtime")
        command.extend(["-RuntimeRoot", str(runtime_root)])
    if kind == "models":
        command.extend(["-RuntimeProfile", profile])
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("paper", "models"), required=True)
    parser.add_argument(
        "--runtime-profile", choices=("CpuTwoProcessors", "CpuElastic"), default="CpuTwoProcessors"
    )
    parser.add_argument("--runtime-root", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise RuntimeError("This service host requires Windows")
    runtime = args.runtime_root.resolve() if args.runtime_root else None
    command = supervisor_command(args.kind, args.runtime_profile, runtime)
    data = (runtime or ROOT) / "data"
    if runtime is not None and not data.is_dir():
        raise RuntimeError("Existing paper runtime data is missing; refusing a fresh installation")
    data.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    state = {
        "host_pid": os.getpid(),
        "kind": args.kind,
        "started_at": datetime.now(UTC).isoformat(),
        "host_has_console": bool(ctypes.windll.kernel32.GetConsoleWindow()),
        "child_creation_flags": "CREATE_NO_WINDOW",
        "command": command,
        "state": "starting",
    }
    state_path = data / f"service-host-{args.kind}.json"

    def save_state() -> None:
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        for attempt in range(8):
            try:
                temporary.replace(state_path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.1)

    save_state()
    with (
        (data / f"host-{args.kind}-{stamp}.out.log").open("xb") as output,
        (data / f"host-{args.kind}-{stamp}.err.log").open("xb") as errors,
    ):
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        state.update(state="running", supervisor_pid=child.pid)
        save_state()
        result = child.wait()
        state.update(state="exited", exit_code=result, finished_at=datetime.now(UTC).isoformat())
        save_state()
    # Preserve the native exit code for Task Scheduler; no silent relaunch or model retry.
    sys.exit(result)


if __name__ == "__main__":
    main()
