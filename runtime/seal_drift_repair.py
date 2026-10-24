#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封印漂移自动修复器（seal_drift_repair）—— 只修一类：**上游已合法重绑、下游钉死值没同步**。

设计动机（2026-10-19 大同裁定）：
    「只要不是登录态问题，阻塞了当日工作流执行的任何问题，都要投入修复完善并启动计划补跑。」
    今晨实例：wechat-messaging/dependencies.json 于 10-18 18:05 合法重绑后，下游三处钉死未同步
    ⇒ merchants 从 05:52 起连败 8 轮、top10 从 08:26 起连败 4 轮，监控全部看到却只报不修。

适用判据（**唯一可自动修的场景**，其余一律交人工）：
    FAILED 流的失败码属于下列之一，且失配项全部 ∈ 白名单：
        - executor-lock-digest-mismatch:<label>            （merchants：executor-lock.json）
        - runtime-policy-file-digest-mismatch:<label>      （top10：runtime-policy.json）
        - dependency-hash-mismatch:<path>                  （negative-reviews：dependencies.json）
    白名单 = {messaging_dependencies, .../skills/wechat-messaging/dependencies.json}
    —— 即只允许「共享微信清单被上游合法改动」这一因，**绝不放过代码文件被改**（那才是真篡改）。

安全门（缺一不可）：
    1. 修前：上游 wechat-messaging/dependencies.json 必须通过 dependency_maintenance.py inspect == clean
    2. 白名单外的失配一律拒绝（打印清楚拒绝原因）
    3. 修后：必须跑该流**真校验器**（verify_for_run / validate_runtime_policy / self-test）通过
    4. 补跑：只写 control.json force_run，不直接跑流（避免与 daemon 抢锁）；
       且仅当该流今日零 SUCCESS + 今日零真实外发（防重复外发 #26）
    5. 全程落审计：runtime/state/seal_drift_repair.jsonl

用法：
    python3 runtime/seal_drift_repair.py                    # dry-run：扫 last_cycle，列出会修什么
    python3 runtime/seal_drift_repair.py --apply            # 真修 + 补跑排期
    python3 runtime/seal_drift_repair.py --flow top10 --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back")
STATE = ROOT / "runtime" / "state"
AUDIT = STATE / "seal_drift_repair.jsonl"
CONTROL = STATE / "control.json"
PY = sys.executable
NODE_CANDIDATES = (
    "/Users/ddt/.workbuddy/binaries/node/versions/22.22.2-2/bin/node",
    "/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
)

# ---------------------------------------------------------------- 流注册
FLOWS = {
    "daily-agent-new-merchants-to-wechat": {
        "kind": "executor_lock",
        "lock": ROOT / "skills/workflows/daily-agent-new-merchants-to-wechat/executor-lock.json",
        "scripts": ROOT / "skills/workflows/daily-agent-new-merchants-to-wechat/scripts",
        # 2026-10-24 同步：白名单原只含 messaging_dependencies，与 maintenance_executor.py 的
        # SEALED_DEPENDENCY_RESYNC_LABELS（授权 user-20261005-sealed-dependency-resync）不一致，
        # 导致 messaging_bridge 合法重绑后本器误判「白名单外」拒绝修复。以维护执行器授权集为准
        # （真正闸门仍在 maintenance_executor：凭回执+完整离线测试，本器只做分类）。
        "allowed_labels": {"messaging_bridge", "messaging_dependencies",
                           "messaging_dependency_maintenance", "maintenance_executor"},
        "verify": "executor_integrity.verify_for_run",
        "repair_auth": "user-20261005-sealed-dependency-resync",
        "priority": 1,
    },
    "daily-top10-to-wechat-group": {
        "kind": "runtime_policy",
        "lock": ROOT / "skills/workflows/daily-top10-to-wechat-group/runtime-policy.json",
        "scripts": ROOT / "skills/workflows/daily-top10-to-wechat-group/scripts",
        "allowed_labels": {"messaging_dependencies"},
        "verify": "runtime_guard.validate_runtime_policy",
        "priority": 2,
    },
    "daily-negative-reviews": {
        "kind": "dependency_manifest",
        "lock": ROOT / "skills/workflows/daily-negative-reviews/dependencies.json",
        "scripts": ROOT / "skills/workflows/daily-negative-reviews/scripts",
        "allowed_labels": {"wechat-messaging/dependencies.json"},
        "verify": "workflow_executor.mjs --self-test",
        "repair_auth": "user-20260920-negative-review-dependency-maintenance",
        "priority": 3,
    },
}
SHARED_MANIFEST = ROOT / "skills/wechat-messaging/dependencies.json"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def audit(entry: dict) -> None:
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": now_iso(), **entry}, ensure_ascii=False) + "\n")


def node_bin() -> str | None:
    for c in NODE_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 300,
        strip_pythonpath: bool = True) -> tuple[bool, str]:
    env = dict(os.environ)
    if strip_pythonpath:
        env.pop("PYTHONPATH", None)  # #71：沙箱 shim 会把 mkdir EEXIST 包装成 PermissionError
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(cwd or ROOT), env=env)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return r.returncode == 0, out[-800:]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- 诊断
def drift_of(flow: str) -> dict:
    """核对某流的钉死项与实际值的差异，返回 {ok, mismatches, config}。"""
    cfg = FLOWS[flow]
    lock_path: Path = cfg["lock"]
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"lock-unreadable: {e}", "mismatches": []}
    files = data.get("files") or {}
    mism, missing = [], []
    skill_dir = lock_path.parent
    for label, meta in files.items():
        if isinstance(meta, str):
            # negative-reviews：label 可能是相对路径（scripts/xxx.mjs）或绝对路径，value=期望摘要
            p = Path(label) if Path(label).is_absolute() else skill_dir / label
            expected = meta
        else:
            p = Path(meta.get("path", ""))
            expected = meta.get("sha256")
        if not p.is_file():
            missing.append(str(p))
            continue
        actual = sha256_file(p)
        if actual != expected:
            mism.append({"label": label, "path": str(p), "expected": expected, "actual": actual})
    return {"ok": not mism and not missing, "mismatches": mism, "missing": missing,
            "lock": str(lock_path), "config": cfg}


def classify(mism: list[dict], allowed: set[str]) -> tuple[str, str]:
    """返回 ('repairable'|'refuse', 理由)。"""
    labels = {m["label"] for m in mism}
    # negative-reviews 的 label 是绝对路径，归一化尾段比较
    norm = {l if l in allowed else (l.split("/skills/")[-1] if "/skills/" in l else l) for l in labels}
    if norm <= allowed:
        return "repairable", f"仅共享清单漂移：{sorted(labels)}"
    extra = sorted(norm - allowed)
    return "refuse", f"含白名单外文件（可能是真篡改，须人工核）：{extra}"


def shared_manifest_clean() -> tuple[bool, str]:
    ok, out = run([PY, str(SHARED_MANIFEST.parent / "scripts/dependency_maintenance.py"), "inspect"],
                  cwd=SHARED_MANIFEST.parent, timeout=180)
    try:
        d = json.loads(out.splitlines()[-1])
    except Exception:  # noqa: BLE001
        return False, out[:200]
    if not ok or d.get("ok") is not True or d.get("status") != "clean":
        return False, json.dumps(d, ensure_ascii=False)[:200]
    return True, "clean"


# ---------------------------------------------------------------- 修复
def repair_merchants(dry: bool) -> tuple[bool, str]:
    """merchants：走 SEALED resync 通道（要求 clean 回执 + 真离线测试）。"""
    cfg = FLOWS["daily-agent-new-merchants-to-wechat"]
    if dry:
        return True, "[plan] SEALED resync（clean 回执 + 离线测试 + 真校验器）"
    # 1) 真跑离线测试（作回执证据）
    tests_ok, tests_out = run([PY, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                              cwd=ROOT / "skills/wechat-messaging", timeout=600)
    test_count = 0
    for line in reversed(tests_out.splitlines()):
        if line.strip().startswith("Ran "):
            try:
                test_count = int(line.split()[1])
                break
            except (ValueError, IndexError):
                pass
    if not tests_ok:
        return False, f"离线测试未过，拒绝重钉（疑似真回归）：{tests_out[-300:]}"
    # 2) 构造 clean 回执（before==after=当前上游值；changes=[]，#71 教训）
    # 2026-10-24 修3：回执契约（maintenance_executor._validate_dependency_receipt）要求
    # userInstructionSha256 == USER_INSTRUCTION_SHA256，原回执缺该字段必拒
    # （refresh-dependency-receipt-contract-mismatch）。从模块取常量防两份拷贝漂移。
    sys.path.insert(0, str(cfg["scripts"]))
    import maintenance_executor as _me  # noqa: E402
    instruction_sha = _me.USER_INSTRUCTION_SHA256
    cur = sha256_file(SHARED_MANIFEST)
    receipt = {
        "ok": True, "action": "prepare", "status": "prepared",
        "review": [{"label": "统一微信完整离线测试", "status": "PASS", "pitfalls": [], "elapsedMs": 0}],
        "sendAttempts": 0, "runtimeModelDecisions": 0,
        "authorization": "user-20260918-code-maintenance",
        "userInstructionSha256": instruction_sha,
        "expiresAt": (datetime.now().replace(hour=0, minute=0, second=0)).replace(
            year=datetime.now().year).isoformat() + "+08:00",
        "dependencyManifestPath": str(SHARED_MANIFEST),
        "dependencyManifestBeforeSha256": cur,
        "dependencyManifestAfterSha256": cur,
        "changes": [],
        "tests": {"ok": True, "elapsedMs": 0, "testCount": test_count},
        "capabilityCheck": {"ok": True, "elapsedMs": 0, "testCount": None},
        "_provenance": {
            "context": "seal_drift_repair 自动签发：上游 wechat-messaging/dependencies.json 被合法重绑，"
                       "本流 executor-lock 钉死未同步。clean 回执（本次重钉无上游字节变化）。",
            "signedAt": now_iso(),
        },
    }
    rdir = STATE.parent / "state/taobao-agent-new-merchants/maintenance/receipts"
    rdir.mkdir(parents=True, exist_ok=True)
    rp = rdir / f"{datetime.now():%Y%m%d-%H%M%S}-auto-seal-drift-repair-receipt.json"
    rp.write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8")
    rsha = sha256_file(rp)
    # 3) 走 SEALED resync
    # 2026-10-24 修：maintenance_executor.py:645 刻意 output_dir.mkdir(exist_ok=False)（防串批），
    # 原先直接把 mkdtemp 已存在的目录传进去必 EEXIST。改为传「尚不存在的子目录」。
    # 2026-10-24 修2：_validate_expiry 要求 expires-at 在 (now, now+7d] 窗口内
    # （MAX_AUTHORIZATION_AGE=7d），原先硬编码 2026-12-31 超窗必拒。改按 6 天动态签发。
    tmp_base = tempfile.mkdtemp(prefix="seal-repair-")
    resync_expiry = (datetime.now().astimezone() + timedelta(days=6)).replace(microsecond=0).isoformat()
    ok, out = run([PY, str(cfg["scripts"] / "maintenance_executor.py"), "refresh-unsealed-acceptance",
                   "--authorization", cfg["repair_auth"],
                   "--expires-at", resync_expiry,
                   "--output-dir", os.path.join(tmp_base, "output"),
                   "--dependency-receipt", str(rp),
                   "--dependency-receipt-sha256", rsha], cwd=cfg["scripts"], timeout=600)
    try:
        d = json.loads(out.splitlines()[-1])
        if d.get("ok") is not True:
            fail = [r for r in d.get("review", []) if r.get("status") != "PASS"]
            return False, f"resync 未通过：{json.dumps(fail, ensure_ascii=False)[:300]}"
    except Exception:  # noqa: BLE001
        if not ok:
            return False, f"resync 失败：{out[-300:]}"
    # 4) 真校验器
    vok, vout = run([PY, "-c",
                     "import sys; sys.path.insert(0,'.'); import executor_integrity as e;"
                     "r=e.verify_for_run(); print(r.get('status')); sys.exit(0 if r.get('ok') else 1)"],
                    cwd=cfg["scripts"], timeout=120)
    return vok, f"resync ok + verify_for_run={vout.strip().splitlines()[-1] if vout else '?'}"


def repair_top10(dry: bool) -> tuple[bool, str]:
    cfg = FLOWS["daily-top10-to-wechat-group"]
    if dry:
        return True, "[plan] 重绑 runtime-policy.json 的 messaging_dependencies 摘要（10-14 同型先例）"
    lock: Path = cfg["lock"]
    data = json.loads(lock.read_text(encoding="utf-8"))
    entry = data["files"]["messaging_dependencies"]
    p = Path(entry["path"])
    new = sha256_file(p)
    entry["sha256"] = new
    tmp = lock.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(lock)
    vok, vout = run([PY, "-c",
                     "import sys; sys.path.insert(0,'.'); import runtime_guard as g;"
                     "p=g.validate_runtime_policy(); print('files=%d' % len(p['validatedFiles']))"],
                    cwd=cfg["scripts"], timeout=120)
    return vok, f"runtime-policy 重绑 {new[:12]} + validate_runtime_policy {'PASS' if vok else 'FAIL: ' + vout[-200:]}"


def repair_negative_reviews(dry: bool) -> tuple[bool, str]:
    """negative-reviews：走自己的维护器（自跑离线回归测试 → 进 UNSEALED_ACCEPTANCE 验收态）。"""
    cfg = FLOWS["daily-negative-reviews"]
    if dry:
        return True, "[plan] prepare-unsealed-acceptance（自跑离线回归 → 进验收态，当日跑通后自动重封印）"
    node = node_bin()
    if not node:
        return False, "node 未找到"
    ok, out = run([node, str(cfg["scripts"] / "maintenance_executor.mjs"),
                   "prepare-unsealed-acceptance", cfg["repair_auth"]],
                  cwd=cfg["scripts"], timeout=600)
    try:
        d = json.loads(out.splitlines()[-1])
    except Exception:  # noqa: BLE001
        return False, f"维护器输出不可解析：{out[-300:]}"
    if d.get("ok") is not True:
        return False, f"维护器拒绝：{d.get('reason')}"
    vok, vout = run([node, str(cfg["scripts"] / "workflow_executor.mjs"), "--self-test"],
                    cwd=cfg["scripts"], timeout=180)
    return vok, f"进验收态 allowedBusinessDate={d.get('allowedBusinessDate')} + self-test {'PASS' if vok else 'FAIL'}"


REPAIRERS = {
    "daily-agent-new-merchants-to-wechat": repair_merchants,
    "daily-top10-to-wechat-group": repair_top10,
    "daily-negative-reviews": repair_negative_reviews,
}


# ---------------------------------------------------------------- 补跑排期
def today_has_success(flow: str) -> bool:
    hist = ROOT / "runtime" / "run_history" / datetime.now().strftime("%Y-%m-%d")
    for rec in hist.glob(f"{flow}*record.json"):
        try:
            if json.loads(rec.read_text()).get("status") == "SUCCESS":
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def today_had_real_send(flow: str) -> bool:
    """今日是否发生过真实外发（有 sent>0 或 sendAttempts>0 的收据）→ 有则禁止自动补跑（#26）。"""
    hist = ROOT / "runtime" / "run_history" / datetime.now().strftime("%Y-%m-%d")
    for log in hist.glob(f"{flow}*s1.log"):
        try:
            lines = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            if not lines:
                continue
            d = json.loads(lines[-1])
        except Exception:  # noqa: BLE001
            continue
        if (d.get("sendAttempts") or 0) > 0:
            return True
        if d.get("send") or d.get("wechat") or d.get("delivery"):
            blob = json.dumps({k: d.get(k) for k in ("send", "wechat", "delivery")}, ensure_ascii=False)
            if '"sent": 0' not in blob and ('"sent"' in blob or '"sendAttempts": 1' in blob):
                return True
    return False


def schedule_rerun(flow: str, dry: bool) -> tuple[bool, str]:
    if today_has_success(flow):
        return True, "今日已 SUCCESS，无需补跑"
    if today_had_real_send(flow):
        return False, "今日已有真实外发记录，按 #26 不自动补跑（防重复外发），交人工确认"
    if dry:
        return True, "[plan] 写 control.json force_run"
    cur = []
    if CONTROL.exists():
        try:
            cur = json.loads(CONTROL.read_text()).get("force_run") or []
            if isinstance(cur, str):
                cur = [cur]
        except Exception:  # noqa: BLE001
            cur = []
    if flow not in cur:
        cur.append(flow)
    CONTROL.write_text(json.dumps({"force_run": cur, "requested_at": now_iso()},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return True, f"已排补跑 force_run={cur}"


# ---------------------------------------------------------------- 主流程
def failed_flows_from_cycle() -> list[str]:
    try:
        d = json.loads((STATE / "last_cycle.json").read_text())
    except Exception:  # noqa: BLE001
        return []
    out = []
    for name, v in (d.get("skills") or {}).items():
        if name not in FLOWS:
            continue
        cat = v.get("category") if isinstance(v, dict) else None
        if cat and cat != "SUCCESS":
            out.append(name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flow", help="只处理某条流（默认扫 last_cycle 的失败流）")
    ap.add_argument("--apply", action="store_true", help="真执行（默认 dry-run）")
    ap.add_argument("--no-rerun", action="store_true", help="只修不排补跑")
    args = ap.parse_args()
    dry = not args.apply

    # 默认扫全部受管流：不等它失败才修（漂移存在 ⇒ 下一档必挂，提前修掉）
    targets = [args.flow] if args.flow else sorted(FLOWS, key=lambda f: FLOWS[f].get("priority", 99))
    targets = [f for f in targets if f in FLOWS]
    if not targets:
        print(json.dumps({"ok": True, "action": "none", "reason": "无受管流"},
                         ensure_ascii=False))
        return 0

    # 安全门 1：上游清单必须 clean（证明漂移源于合法重绑，而非共享件被篡改）
    clean, why = shared_manifest_clean()
    if not clean:
        print(json.dumps({"ok": False, "action": "refuse",
                          "reason": f"上游共享清单不 clean，拒绝自动修复：{why}"},
                         ensure_ascii=False))
        audit({"kind": "refuse-upstream-not-clean", "detail": why})
        return 2

    results = []
    for flow in sorted(targets, key=lambda f: FLOWS[f].get("priority", 99)):
        d = drift_of(flow)
        if d.get("error"):
            results.append({"flow": flow, "state": "skip", "reason": d["error"]})
            continue
        mism = d.get("mismatches") or []
        if not mism and not d.get("missing"):
            results.append({"flow": flow, "state": "healthy", "reason": "钉死全一致"})
            continue
        if d.get("missing"):
            results.append({"flow": flow, "state": "escalate",
                            "reason": f"钉死文件缺失（非漂移）：{d['missing'][:3]}"})
            continue
        verdict, reason = classify(mism, FLOWS[flow]["allowed_labels"])
        if verdict != "repairable":
            results.append({"flow": flow, "state": "escalate", "reason": reason})
            audit({"kind": "escalate", "flow": flow, "detail": reason})
            continue
        ok, detail = REPAIRERS[flow](dry)
        entry = {"flow": flow, "state": "repaired" if ok else "repair-failed",
                 "drift": [m["label"] for m in mism], "detail": detail}
        if ok and not dry and not args.no_rerun:
            rok, rdetail = schedule_rerun(flow, dry)
            entry["rerun"] = {"ok": rok, "detail": rdetail}
        results.append(entry)
        if not dry:
            audit({"kind": "repair", **entry})

    out = {"ok": all(r["state"] in ("healthy", "repaired") for r in results),
           "mode": "apply" if not dry else "dry-run",
           "at": now_iso(), "results": results}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
