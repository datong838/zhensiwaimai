#!/usr/bin/env python3
"""One bounded, code-owned recovery pass around the unified message executor."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dependency_maintenance import MAINTENANCE_AUTHORIZATION, prepare


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "scripts" / "executor.py"
RECOVERABLE_CODE_FAILURE = re.compile(
    r"^(dependency-drift:|.*(?:ModuleNotFoundError|ImportError|SyntaxError|NameError|AttributeError))"
)


def _zero_send_attempts(result: dict) -> bool:
    """Recovery is forbidden after any physical or indeterminate send attempt."""
    # A missing count is not proof that no physical send was attempted.
    # Fail closed: recovery may proceed only on an explicit zero from both the
    # batch and every item receipt.
    top = result.get("sendAttempts")
    if top != 0:
        return False
    for item in result.get("items", []):
        if item.get("sendAttempts") != 0:
            return False
        if item.get("status") in {"attempted", "unknown", "partial"}:
            return False
    return True


def _recoverable(result: dict) -> bool:
    reason = str(result.get("reason") or "")
    return (not result.get("ok") and _zero_send_attempts(result)
            and RECOVERABLE_CODE_FAILURE.search(reason) is not None)


def _send_attempts(result: dict) -> int:
    """Return the greatest known count for the review; unknown is never zero."""
    counts = [result.get("sendAttempts")]
    counts.extend(item.get("sendAttempts") for item in result.get("items", []))
    if any(not isinstance(value, int) or value < 0 for value in counts):
        return -1
    return max(counts, default=0)


def _run_executor(action: str, request: Path, authorization: Path) -> dict:
    process = subprocess.run(
        [sys.executable, str(EXECUTOR), action, "--request", str(request),
         "--authorization", str(authorization)],
        cwd=ROOT.parents[1], text=True, capture_output=True,
    )
    lines = [line for line in (process.stdout or "").splitlines() if line.strip()]
    if not lines:
        return {"ok": False, "status": "blocked", "reason": "total-executor-no-json",
                "sendAttempts": None, "returnCode": process.returncode}
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"ok": False, "status": "blocked", "reason": "total-executor-invalid-json",
                "sendAttempts": None, "returnCode": process.returncode}
    result["returnCode"] = process.returncode
    if process.returncode != 0 and result.get("ok") is True:
        result.update(ok=False, status="blocked", reason="total-executor-exit-code-mismatch")
    return result


def run(action: str, request: Path, authorization: Path, *, runner=_run_executor,
        maintainer=prepare, now=None) -> dict:
    """Run once, optionally repair dependency code, then permit exactly one retry."""
    started = time.monotonic()
    result = {"ok": False, "action": action, "status": "blocked", "recoveryUsed": False,
              "sendAttempts": 0, "runtimeModelDecisions": 0, "review": []}

    def stage(name, fn):
        tick = time.monotonic()
        row = {"stage": name, "status": "running", "pitfalls": []}
        result["review"].append(row)
        try:
            value = fn()
            row["status"] = "completed" if value.get("ok") else "failed"
            if not value.get("ok"):
                row["pitfalls"] = [str(value.get("reason") or value.get("status"))]
            return value
        except Exception as error:
            row.update(status="failed", pitfalls=[str(error)])
            # A crash while waiting for a child process is not proof that no
            # physical send happened. Preserve an unknown attempt count.
            return {"ok": False, "status": "blocked", "reason": str(error), "sendAttempts": None}
        finally:
            row["elapsedMs"] = round((time.monotonic() - tick) * 1000)

    initial = stage("总执行器首次运行", lambda: runner(action, request, authorization))
    result["initial"] = initial
    result["sendAttempts"] = _send_attempts(initial)
    if initial.get("ok"):
        result.update(ok=True, status=initial.get("status", "verified"), final=initial)
    elif not _recoverable(initial):
        result.update(status=initial.get("status", "blocked"), reason=initial.get("reason"), final=initial)
    else:
        result["recoveryUsed"] = True
        clock = now or datetime.now().astimezone()
        output = ROOT / ".runtime" / "heartbeat-maintenance" / str(time.time_ns())
        maintenance = stage("受控依赖维护与全量回归", lambda: maintainer(
            MAINTENANCE_AUTHORIZATION, (clock + timedelta(hours=1)).isoformat(), output
        ))
        result["maintenance"] = maintenance
        if maintenance.get("ok"):
            final = stage("总执行器最终复跑", lambda: runner(action, request, authorization))
            result.update(ok=bool(final.get("ok")), status=final.get("status", "blocked"),
                          reason=final.get("reason"), final=final)
            result["sendAttempts"] = max(result["sendAttempts"], _send_attempts(final))
        else:
            result.update(status="blocked", reason="maintenance-failed", final=initial)
    result["elapsedMs"] = round((time.monotonic() - started) * 1000)
    result["reviewSummary"] = {
        "totalElapsedMs": result["elapsedMs"], "result": result["status"],
        "stageCount": len(result["review"]),
        "failedStages": [row["stage"] for row in result["review"] if row["status"] == "failed"],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("execute", "reconcile"))
    parser.add_argument("--request", required=True)
    parser.add_argument("--authorization", required=True)
    args = parser.parse_args()
    output = run(args.action, Path(args.request).resolve(), Path(args.authorization).resolve())
    print(json.dumps(output, ensure_ascii=False))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
