"""One bounded original-director reload to load tested read-only business facts."""

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
EXPECTED_PID = 58654
SERVICE = "gui/501/com.zhensi.waimai.careloop"
LOG = RUNTIME / "state/daemon.out.log"
QUEUE = ROOT / "skills/wechat-messaging/.runtime/ui-post-queue"
FACT_FLOWS = {
    "daily-top10-to-wechat-group",
    "daily-negative-reviews",
    "contract-termination-applications-screenshot",
    "daily-taobao-download-to-jinsha",
    "taobao-flash-sale-negative-review-appeals",
    "meituan-waimai-negative-review-appeals-11",
    "daily-store-task-completion-ops-to-wechat",
    "daily-service-market-ranking-to-wechat",
    "daily-meituan-income-top10-to-wechat",
}

sys.path.insert(0, str(RUNTIME))
import business_delivery_facts  # noqa: E402
import run_all  # noqa: E402


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=15, check=True).stdout


def chrome_pids():
    return {
        str(port): command(
            "/usr/sbin/lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"
        ).strip()
        for port in range(9230, 9234)
    }


def queue_fingerprints():
    files = []
    for name in ("task.json", "response.json", "send-intent.json"):
        files.extend(QUEUE.glob(f"*/{name}"))
    return {
        str(path.relative_to(ROOT)): digest(path)
        for path in sorted(set(files))
    }


def lock_paths():
    locks = list((RUNTIME / "state/locks").glob("*.lock"))
    locks.extend(Path(f"/tmp/zhensi-post-{port}.lock") for port in (9230, 9231, 9233))
    locks.append(Path("/tmp/zhensi-jinsha-cua-exam.lock"))
    return [str(path) for path in locks if path.exists() or path.is_symlink()]


def snapshot():
    now = dt.datetime.now(ZoneInfo("Asia/Shanghai"))
    assert now.date().isoformat() == "2026-10-28", "wrong-reviewed-date"
    assert now.hour == 21 and now.minute < 45, "outside-reviewed-pre-maintenance-window"

    daemon = read_json(RUNTIME / "state/daemon.json")
    assert daemon["pid"] == EXPECTED_PID and daemon["status"] == "running", "director-changed"
    info = command("/bin/launchctl", "print", SERVICE)
    assert f"\tpid = {EXPECTED_PID}\n" in info and "\tstate = running\n" in info
    os.kill(EXPECTED_PID, 0)

    live_steps = sorted(str(path.relative_to(ROOT)) for path in (RUNTIME / "state/live_steps").iterdir())
    assert not live_steps, "live-step-registration-present"
    assert not lock_paths(), "business-lock-present"

    processes = command("/bin/ps", "-axo", "pid=,ppid=,comm=").splitlines()
    children = [
        line.strip()
        for line in processes
        if len(line.split()) >= 3 and line.split()[1] == str(EXPECTED_PID)
    ]
    assert all(line.split()[-1].endswith("caffeinate") for line in children), "director-child-executor"

    control = read_json(RUNTIME / "state/control.json")
    assert not any(control.get(key) for key in ("force_run", "force_run_now", "reset_circuit")), "control-request-present"

    manifest = read_json(RUNTIME / "skills_manifest.json")
    naive_now = now.replace(tzinfo=None)
    enabled = [skill for skill in manifest["skills"] if skill.get("enabled")]
    gates = {skill["name"]: run_all._cadence_gate(skill, naive_now) for skill in enabled}
    assert all(gate[0] is True for gate in gates.values()), "production-flow-could-start"
    assert {name for name, gate in gates.items() if gate[1] == "business_delivery_observed"} == FACT_FLOWS

    facts = {name: business_delivery_facts.read_fact(name, naive_now) for name in sorted(FACT_FLOWS)}
    assert all(fact and fact.get("businessDelivered") is True for fact in facts.values())
    assert all(fact.get("basis") == "bound-single-submission-standing-user-policy" for fact in facts.values())
    assert all(fact.get("technicalStatusPreserved") == "unknown" for fact in facts.values())
    assert all(fact.get("newSendAttempts") == 0 for fact in facts.values())

    protected = [
        RUNTIME / "run_all.py",
        RUNTIME / "business_delivery_facts.py",
        RUNTIME / "skills_manifest.json",
        RUNTIME / "state/control.json",
        RUNTIME / "posts.json",
    ]
    for post in ("taobao-brand-post", "taobao-svc-post", "jinsha-post", "meituan-post"):
        protected.append(ROOT / "skills/posts" / post / "dependencies.json")

    return {
        "at": now.isoformat(),
        "daemon": daemon,
        "children": children,
        "gates": {name: list(value) for name, value in gates.items()},
        "facts": facts,
        "chromePids": chrome_pids(),
        "protected": {str(path.relative_to(ROOT)): digest(path) for path in protected},
        "queueFingerprints": queue_fingerprints(),
        "liveSteps": live_steps,
        "locks": [],
        "launchctl": info,
        "logOffset": LOG.stat().st_size,
    }


assert not (EVIDENCE / "activation-result.json").exists(), "activation-already-attempted"
before = snapshot()
(EVIDENCE / "activation-before.json").write_text(
    json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8"
)

# Recheck all frozen, no-effect inputs immediately before the single authorized reload.
second = snapshot()
for key in ("daemon", "gates", "facts", "chromePids", "protected", "queueFingerprints"):
    assert second[key] == before[key], f"pre-reload-drift:{key}"

(EVIDENCE / "activation-attempt.json").write_text(
    json.dumps(
        {
            "at": dt.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "oldPid": EXPECTED_PID,
            "service": SERVICE,
            "reloadLimit": 1,
            "productionJobsRequested": 0,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

# The existing original launchd service is the only process manager used.
result = subprocess.run(
    ["/bin/launchctl", "kickstart", "-k", SERVICE],
    capture_output=True,
    text=True,
    timeout=20,
)
(EVIDENCE / "activation-result.json").write_text(
    json.dumps(
        {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
assert result.returncode == 0, "original-service-reload-failed"

deadline = time.monotonic() + 25
new_daemon = None
new_log = ""
while time.monotonic() < deadline:
    time.sleep(1)
    candidate = read_json(RUNTIME / "state/daemon.json")
    if candidate.get("pid") != EXPECTED_PID and candidate.get("status") == "running":
        new_daemon = candidate
    new_log = LOG.read_bytes()[before["logOffset"] :].decode("utf-8", errors="replace")
    if new_daemon and all(f"[skip] {name} business_delivery_observed" in new_log for name in FACT_FLOWS):
        break
else:
    raise RuntimeError("new-heartbeat-or-business-fact-log-not-observed-no-retry")

info = command("/bin/launchctl", "print", SERVICE)
assert f"\tpid = {new_daemon['pid']}\n" in info and "\tstate = running\n" in info
os.kill(new_daemon["pid"], 0)
assert before["chromePids"] == chrome_pids(), "business-browser-pid-changed"
assert all(digest(ROOT / path) == sha for path, sha in before["protected"].items()), "protected-file-changed"
assert before["queueFingerprints"] == queue_fingerprints(), "queue-task-or-receipt-changed"
assert not list((RUNTIME / "state/live_steps").iterdir()), "unexpected-live-step"
assert not lock_paths(), "unexpected-business-lock"

last_cycle = read_json(RUNTIME / "state/last_cycle.json")
assert all(last_cycle["skills"][name]["status"] == "PENDING" for name in FACT_FLOWS)
post_facts = {
    name: business_delivery_facts.read_fact(name, dt.datetime.now())
    for name in sorted(FACT_FLOWS)
}
assert post_facts == before["facts"], "business-fact-drift"

(EVIDENCE / "director-cycle.log").write_text(new_log, encoding="utf-8")
after = {
    "at": dt.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    "oldPid": EXPECTED_PID,
    "newPid": new_daemon["pid"],
    "daemon": new_daemon,
    "launchctlState": "running",
    "reloadCount": 1,
    "productionJobsRequested": 0,
    "newQueueTasksOrReceiptChanges": 0,
    "chromePids": chrome_pids(),
    "chromePidsUnchanged": True,
    "protectedFilesUnchanged": True,
    "technicalUnknownPreserved": True,
    "newSendAttempts": 0,
    "liveSteps": 0,
    "locks": 0,
    "businessDeliveryObserved": sorted(FACT_FLOWS),
    "lastCyclePendingPreserved": sorted(FACT_FLOWS),
    "lastCycleAt": last_cycle["cycle_at"],
}
(EVIDENCE / "activation-after.json").write_text(
    json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(after, ensure_ascii=False))
