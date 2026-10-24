#!/usr/bin/env python3
"""合同解约申请「处理中」任务列表截图 → 发运营群（对齐 daily-store-basic-diagnosis 同款形态）。

流程：跑 contract_termination_shot.mjs（工位 9231 真会话探活 + 筛选处理中 + 表格原图截图，
超页自动翻页 p1/p2…）→ 收集 PNG → 经 Windows 网关发到运营群。

用法：
  python contract_termination_daily.py             # 只截图（不发）
  python contract_termination_daily.py --execute   # 截图 + 发群（受发送闸约束）
  python contract_termination_daily.py --deliver-run <run目录>   # 不重截，用某次 run 的图补发
  发送闸：默认放行；--disarm 制动、--arm 解除
退出码：0=成功（含 already_verified/no-report/ready）；1=失败/unknown/blocked
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SKILL = Path(__file__).resolve().parents[1]
RUNTIME = SKILL / ".runtime" / "contract-termination"
EVENTS = RUNTIME / "events"
RUNS = RUNTIME / "runs"
SHOT = Path(__file__).with_name("contract_termination_shot.mjs")
# 本机 node + playwright 依赖（已实测可跑 connectToPost 的组合）
NODE = Path(os.environ.get("ZENSI_NODE") or "/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
NODE_MODULES = "/Users/ddt/.workbuddy/binaries/node/workspace/node_modules"
WINDOWS_SCRIPTS = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts")
SHOT_OUT_ROOT = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/state/screenshots/contract-termination")

GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
WORKFLOW_ID = "contract-termination-ops"
AUTHORIZATION_REF = "user-20261020-contract-termination-ops-windows-gateway"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
ARM_FILE = RUNTIME / "SEND_ARMED.json"
DISARM_FILE = RUNTIME / "SEND_DISARMED.json"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def arm_state() -> dict:
    """发送闸：默认放行；存在 SEND_DISARMED.json 则制动（零外发）。"""
    if DISARM_FILE.exists():
        return {"armed": False, "mode": "disarmed"}
    return {"armed": True, "mode": "default-auto"}


def set_arm(armed: bool) -> dict:
    ARM_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if armed:
        DISARM_FILE.unlink(missing_ok=True)
        atomic_json(ARM_FILE, {"armed": True, "at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds")})
        return {"armed": True, "mode": "armed"}
    ARM_FILE.unlink(missing_ok=True)
    atomic_json(DISARM_FILE, {"armed": False, "at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds")})
    return {"armed": False, "mode": "disarmed"}


def shot(run_dir: Path, task_status: str = "处理中") -> dict:
    """跑截图脚本；返回收据 dict（含 pages[].file）。退出码 4=工位忙（可恢复跳过），3=掉登录。"""
    day = datetime.now(LOCAL_TZ).date().isoformat()
    out_dir = run_dir / "shot-out"
    env = dict(os.environ, NODE_PATH=NODE_MODULES)
    proc = subprocess.run(
        [str(NODE), str(SHOT), "--json", "--task-status", task_status, "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=600, check=False, env=env)
    payload = {}
    for line in reversed((proc.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    if proc.returncode == 4:
        return {"skippedBusy": True, "reason": payload.get("reason") or "post-busy"}
    if proc.returncode == 3:
        raise RuntimeError(f"service-login-required:{payload.get('reason') or '9231 session invalid'}")
    if proc.returncode or not payload.get("ok"):
        raise RuntimeError(f"shot-failed:{payload.get('error') or payload.get('reason') or (proc.stderr or '')[-250:]}")
    return payload


def collect_images(receipt: dict) -> list:
    """从收据 pages[] 收集 PNG 绝对路径（按页序）。"""
    files = []
    for p in receipt.get("pages", []):
        f = p.get("file")
        if f and Path(f).is_file():
            files.append(str(Path(f).resolve()))
    return files


def files_sha(files: list) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(Path(f).read_bytes())
        h.update(b"|")
    return h.hexdigest()


def deliver(images: list, run_dir: Path, day: str) -> dict:
    if not images:
        return {"status": "no-report", "sendAttempts": 0}  # 0 行/无图：铁律不产不发
    gate = arm_state()
    if not gate["armed"]:
        return {"status": "blocked", "reason": "send-disarmed", "sendAttempts": 0}
    file_sha = files_sha(images)
    event = f"{day}-contract-termination-ops"
    if not EVENTS.is_dir():
        return {"status": "blocked", "reason": "canonical-contract-termination-ledger-unavailable", "sendAttempts": 0}
    marker = EVENTS / f"{event}.json"
    if marker.exists():
        prior = json.loads(marker.read_text(encoding="utf-8"))
        if prior.get("sha256") != file_sha:
            # 当日已 verified 但 payload 变了（页面数据滚动/剩余时长递减等）：一事一发的正确语义是
            # 「当日已发、不重发」，记为 already_verified；绝不可重发造成重复外发，也不可记 UNKNOWN 故障
            # （2026-10-20 实战：daemon 补跑因此被判 FAILED/UNKNOWN，误导看护）。
            if prior.get("state") == "verified":
                return {"status": "already_verified", "sendAttempts": 0, "event": event,
                        "reason": "verified-earlier-today-payload-changed-no-resend"}
            return {"status": "blocked", "reason": "same-event-payload-conflict", "sendAttempts": 0}
        if prior.get("state") == "verified":
            return {"status": "already_verified", "sendAttempts": 0, "event": event}
        return {"status": "unknown", "reason": "prior-attempt-requires-read-only-reconciliation",
                "sendAttempts": 0, "event": event}

    if str(WINDOWS_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(WINDOWS_SCRIPTS))
    from wecom_adapter import WeComAdapter as WindowsAdapter, target_preflight_verified  # 2026-10-23 channel switch → 企微
    from contract import Rejected
    deadline = int(time.time()) + 300
    request = {"schemaVersion": 1, "groupName": GROUP,
               "items": [{"itemId": f"contract-termination-p{i + 1}", "type": "file", "path": f}
                         for i, f in enumerate(images)],
               "context": {"workflowId": WORKFLOW_ID, "eventId": event,
                           "accountAlias": "main-wechat", "channel": "desktop", "deadlineAt": deadline}}
    grant = {"schemaVersion": 1, "accountAlias": "main-wechat", "groupName": GROUP,
             "channel": "desktop", "expiresAt": deadline, "authorizationRef": AUTHORIZATION_REF}
    try:
        adapter = WindowsAdapter()
        with adapter.session(request):
            if marker.exists():
                prior = json.loads(marker.read_text(encoding="utf-8"))
                if prior.get("sha256") != file_sha:
                    if prior.get("state") == "verified":
                        return {"status": "already_verified", "sendAttempts": 0, "event": event,
                                "reason": "verified-earlier-today-payload-changed-no-resend"}
                    return {"status": "blocked", "reason": "same-event-payload-conflict", "sendAttempts": 0}
                return {"status": "already_verified" if prior.get("state") == "verified" else "unknown",
                        "reason": None if prior.get("state") == "verified" else "prior-attempt-requires-read-only-reconciliation",
                        "sendAttempts": 0, "event": event}
            preflight = adapter.preflight(request, run_dir / "windows-preflight")
            if not target_preflight_verified(preflight, GROUP):
                return {"status": "blocked", "reason": preflight.get("reason") or "target-group-not-exactly-listed",
                        "sendAttempts": 0}
            atomic_json(marker, {"state": "attempted", "event": event, "sha256": file_sha,
                                 "groupName": GROUP, "images": [Path(f).name for f in images], "sendAttempts": None})
            try:
                result = adapter.send_one(request, request["items"][0], run_dir / "windows-send", grant, deadline)
            except Exception as error:  # noqa: BLE001
                atomic_json(marker, {"state": "unknown", "event": event, "sha256": file_sha,
                                     "groupName": GROUP, "images": [Path(f).name for f in images],
                                     "reason": str(error), "sendAttempts": None})
                return {"status": "unknown", "reason": f"windows-execution-error:{error}", "sendAttempts": None}
    except Rejected as error:
        return {"status": "blocked", "reason": str(error), "sendAttempts": 0}
    if result.get("status") == "verified":
        atomic_json(marker, {"state": "verified", "event": event, "sha256": file_sha, "groupName": GROUP,
                             "images": [Path(f).name for f in images], "sendAttempts": result.get("sendAttempts"),
                             "verificationLevel": result.get("verificationLevel"), "evidence": result.get("evidence")})
        return {"status": "verified", "sendAttempts": result.get("sendAttempts"), "event": event,
                "verificationLevel": result.get("verificationLevel")}
    atomic_json(marker, {"state": "unknown", "event": event, "sha256": file_sha, "groupName": GROUP,
                         "images": [Path(f).name for f in images], "sendAttempts": result.get("sendAttempts"),
                         "reason": result.get("reason")})
    return {"status": "unknown", "reason": result.get("reason"),
            "sendAttempts": result.get("sendAttempts"), "event": event}


def find_run_images(run_dir: Path) -> list:
    """补发：从某次 run 的 shot-out 目录找 PNG（按文件名页序）。
    注意 shot.mjs 在 --out-dir 下还会拼 <YYYY-MM-DD>/ 子目录，必须 rglob。"""
    files = sorted(run_dir.rglob("*.png"),
                   key=lambda p: (int(re.search(r"_p(\d+)\.png$", p.name).group(1))
                                  if re.search(r"_p(\d+)\.png$", p.name) else 0, p.name))
    return [str(p.resolve()) for p in files]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="允许发群（否则只截图）")
    parser.add_argument("--arm", action="store_true", help="解除发送制动")
    parser.add_argument("--disarm", action="store_true", help="制动发送（写 SEND_DISARMED.json）")
    parser.add_argument("--deliver-run", help="不重截，直接用该 run 目录 shot-out 下的图补发")
    parser.add_argument("--task-status", default="处理中", help="任务状态筛选值（默认：处理中）")
    args = parser.parse_args()
    if args.arm or args.disarm:
        print(json.dumps(set_arm(bool(args.arm)), ensure_ascii=False))
        return
    day = datetime.now(LOCAL_TZ).date().isoformat()
    EVENTS.mkdir(parents=True, exist_ok=True, mode=0o700)  # 防重台账目录必须先建（#74）
    if args.deliver_run:
        run_dir = Path(args.deliver_run).resolve()
        receipt = {"deliverRun": True}
        images = find_run_images(run_dir)
        if not images:
            print(json.dumps({"status": "no-report", "reason": "deliver-run-no-images",
                              "runDir": str(run_dir), "day": day}, ensure_ascii=False))
            raise SystemExit(1)
        result = deliver(images, run_dir, day)
    else:
        run_dir = RUNS / f"{day}-{time.time_ns()}"
        run_dir.mkdir(parents=True, mode=0o700)
        try:
            receipt = shot(run_dir, args.task_status)
            if receipt.get("skippedBusy"):
                result = {"status": "skipped-busy", "reason": receipt.get("reason"), "sendAttempts": 0}
                print(json.dumps({**result, "day": day, "runDir": str(run_dir)}, ensure_ascii=False))
                return  # 工位忙：可恢复跳过，不算失败
            images = collect_images(receipt)
            result = (deliver(images, run_dir, day) if args.execute
                      else {"status": "ready" if images else "no-report", "sendAttempts": 0})
        except Exception as error:  # noqa: BLE001
            msg = str(error)
            result = {"status": "unknown", "reason": msg, "sendAttempts": 0, "runDir": str(run_dir), "day": day}
            atomic_json(run_dir / "summary.json", result)
            print(json.dumps(result, ensure_ascii=False))
            raise SystemExit(1)
    result.update({"day": day, "runDir": str(run_dir), "armState": arm_state(),
                   "images": [Path(f).name for f in images],
                   "rows": receipt.get("rows") and len(receipt.get("rows")),
                   "pages": receipt.get("pages") and len(receipt.get("pages")),
                   "warnings": receipt.get("warnings") or [],
                   "header": receipt.get("header")})
    atomic_json(run_dir / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] not in ("verified", "already_verified", "ready", "no-report", "skipped-busy"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
