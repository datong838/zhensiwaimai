"""Run the original 9233 reset exactly once under both original lease layers."""

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "runtime"))
from roster_post_lease import original_post_lease  # noqa: E402


SERVICE = "gui/501/com.zhensi.waimai.careloop"
NODE = "/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
EXPECTED_PIDS = {"9230": "12961", "9231": "3212", "9232": "89873", "9233": "7155"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=15, check=True).stdout


def chrome_pids():
    return {
        port: command("/usr/sbin/lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN").strip()
        for port in EXPECTED_PIDS
    }


now = dt.datetime.now(ZoneInfo("Asia/Shanghai"))
assert now.date().isoformat() == "2026-10-28" and now.hour == 22 and now.minute < 20, "outside-reviewed-window"
assert not (HERE / "2200-receipt.json").exists(), "same-day-receipt-exists"
assert not (HERE / "2200-attempt.json").exists(), "same-day-attempt-exists"
daemon = read(ROOT / "runtime/state/daemon.json")
assert daemon["status"] == "running"
os.kill(daemon["pid"], 0)
launchctl = command("/bin/launchctl", "print", SERVICE)
assert f"\tpid = {daemon['pid']}\n" in launchctl and "\tstate = running\n" in launchctl
assert not list((ROOT / "runtime/state/live_steps").iterdir()), "live-step-present"
assert not list((ROOT / "runtime/state/locks").glob("*.lock")), "group-lock-present"
for lock in ("/tmp/zhensi-post-9230.lock", "/tmp/zhensi-post-9231.lock", "/tmp/zhensi-post-9233.lock", "/tmp/zhensi-jinsha-cua-exam.lock"):
    assert not Path(lock).exists() and not Path(lock).is_symlink(), "physical-lock-present"
control = read(ROOT / "runtime/state/control.json")
assert not any(control.get(key) for key in ("force_run", "force_run_now", "reset_circuit")), "control-request-present"
assert chrome_pids() == EXPECTED_PIDS, "chrome-pid-drift"

with original_post_lease("meituan-merchant", "maintenance-2200-20261028", "/tmp/zhensi-post-9233.lock"):
    result = subprocess.run(
        [NODE, str(HERE / "run_im_reset_once.mjs")], capture_output=True, text=True, timeout=90
    )

(HERE / "im-reset-result.json").write_text(
    json.dumps(
        {
            "at": dt.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "chromePidsUnchanged": chrome_pids() == EXPECTED_PIDS,
            "liveSteps": len(list((ROOT / "runtime/state/live_steps").iterdir())),
            "remainingGroupLocks": len(list((ROOT / "runtime/state/locks").glob("*.lock"))),
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(result.stdout, end="")
if result.returncode:
    print(result.stderr, file=sys.stderr, end="")
raise SystemExit(result.returncode)
