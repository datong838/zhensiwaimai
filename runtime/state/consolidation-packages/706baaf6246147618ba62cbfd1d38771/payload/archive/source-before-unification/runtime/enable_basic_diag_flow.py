#!/usr/bin/env python3
"""把 daily-store-basic-diagnosis-to-wechat（门店商户运营问题诊断）接入 / 撤出 daemon 调度。

背景：daemon（run_all.py --daemon）启动时只 load_manifest 一次、不热加载；新流写入 manifest 后必须重载
才能纳入排班。且**当天新接入的流若已过其 latest_hour，会被判 past_latest → 台账"未全绿" + 夜间巡检
每小时报 YELLOW**。故接入动作安排在每日开档前执行（见 runtime 的接入自动化）。

用法：
  python3 enable_basic_diag_flow.py --status      # 只读：打印当前是否已接入
  python3 enable_basic_diag_flow.py --enable      # 接入（写 manifest + posts.json，校验，重载 daemon）
  python3 enable_basic_diag_flow.py --disable     # 撤出（恢复原状）
可选：
  --manifest PATH   指定 skills_manifest.json（默认 runtime/skills_manifest.json）
  --posts PATH      指定 posts.json（默认 runtime/posts.json）
  --no-reload       不改动 daemon（离线测试用）

幂等：目标态已达到则不改文件；除非 --force-reload 不再重载 daemon。
安全：写盘前自动备份 <file>.bak-basicdiag-<ts>；写盘前跑 JSON 校验 + flow-order 断言。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent                       # runtime/
REPO = ROOT.parent
DEFAULT_MANIFEST = ROOT / "skills_manifest.json"
DEFAULT_POSTS = ROOT / "posts.json"
DAEMON_STATE = ROOT / "state" / "daemon.json"
CARELOOP_LABEL = "com.zhensi.waimai.careloop"

FLOW = "daily-store-basic-diagnosis-to-wechat"
LEDGER_ROW = 19
LEDGER_NAME = "门店商户运营问题诊断（每日11:18）"
SCHEDULE = "每日11:18"
TARGET_GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
POST_KEY = "taobao-agent-service"
FAMILY_ORDER = 10

SKILL_ENTRY = {
    "name": FLOW,
    "target_group": TARGET_GROUP,
    "ledger_name": LEDGER_NAME,
    "schedule": SCHEDULE,
    "dev_state": "active",
    "enabled": True,
    "order": FAMILY_ORDER,
    "cadence_hours": 24,
    "earliest_hour": 11,
    "earliest_minute": 18,
    "cwd": f"skills/workflows/{FLOW}",
    "timeout_seconds": 900,
    "max_retries": 2,
    "cooldown_seconds": 300,
    "needs_adapter": False,
    "steps": [{"argv": ["{python}", "scripts/basic_diag_daily.py", "--execute"]}],
    "latest_hour": 18,
    "note": ("2026-10-13 新建：服务商平台(9231) 经营任务→基础诊断 14 指标(每指标 任务状态=未完成) "
             "任务商户列表 —— 走列表接口 pageQueryOpenTaskMerchantList（必须带请求头 token；签名不覆盖 "
             "pageSize/agentCode，一份凭证换 agentCode 批量取全量，pageSize=1000；响应含 shop_id/门店ID）→ "
             "站点自带下载的 CSV 不含门店ID，不可用于关联；门店分配(已分配门店·根角色)下载 XLSX；"
             "按门店ID 关联「运营人」→ 一个 Excel（每指标一个 sheet，只出有数据的指标，列=门店ID/门店名称/"
             "问题分析/当前值/建议值/运营人）发运营群。0 行不产表不发。发送闸语义=【默认放行 + --disarm 制动】。"),
}
LEDGER_ROW_PENDING = {"row": LEDGER_ROW, "ledger_name": "门店商户运营问题诊断",
                      "schedule": "—", "dev_state": "pending", "skill": None}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_atomic(path: Path, doc: dict) -> None:
    backup = path.with_name(f"{path.name}.bak-basicdiag-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    print(f"[backup] {backup}")


def find_skill(doc: dict):
    for s in doc.get("skills", []):
        if s.get("name") == FLOW:
            return s
    return None


def find_row(doc: dict):
    for r in doc.get("ledger_template", []):
        if r.get("row") == LEDGER_ROW:
            return r
    return None


def is_enabled(manifest: dict, posts: dict) -> bool:
    s = find_skill(manifest)
    r = find_row(manifest)
    used = posts.get("posts", {}).get(POST_KEY, {}).get("usedBy", [])
    return bool(s and s.get("enabled") and s.get("dev_state") == "active"
                and r and r.get("dev_state") == "active" and r.get("skill") == FLOW
                and FLOW in used)


def validate(manifest_path: Path, manifest: dict, posts: dict, expect_present: bool) -> list:
    """方向感知校验：expect_present=True 校验"已接入"，False 校验"已撤出"。"""
    problems = []
    s = find_skill(manifest)
    r = find_row(manifest)
    used = posts.get("posts", {}).get(POST_KEY, {}).get("usedBy", [])
    if not r:
        problems.append("ledger-row-19-missing")
    if expect_present:
        if not s:
            problems.append("skill-entry-missing")
        elif not (s.get("enabled") and s.get("dev_state") == "active"):
            problems.append("skill-entry-not-active")
        if r and not (r.get("dev_state") == "active" and r.get("skill") == FLOW):
            problems.append("ledger-row-19-not-active")
        if FLOW not in used:
            problems.append("posts-usedBy-missing")
    else:
        if s is not None:
            problems.append("skill-entry-still-present")
        if r and (r.get("dev_state") == "active" or r.get("skill") == FLOW):
            problems.append("ledger-row-19-still-active")
        if FLOW in used:
            problems.append("posts-usedBy-still-present")
    # flow-order 断言（只读，纯函数）
    try:
        sys.path.insert(0, str(ROOT))
        import assert_flow_order as afo
        ok, verdict, _ = afo.evaluate(manifest_path)
        if not ok:
            problems.append(f"flow-order-{verdict}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"flow-order-check-error:{exc}")
    return problems


def reload_daemon() -> dict:
    """优先 launchctl kickstart；沙箱下不可见时回退 kill+SIGTERM 让 KeepAlive 重生。"""
    uid = os.getuid()
    try:
        r = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{CARELOOP_LABEL}"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return {"method": "launchctl-kickstart", "ok": True}
        first = (r.stderr or r.stdout or "").strip()[:200]
    except Exception as exc:  # noqa: BLE001
        first = f"{type(exc).__name__}: {exc}"
    # 回退：读 daemon.json 的 pid → SIGTERM → 等 pid 变化
    try:
        pid = (load(DAEMON_STATE) or {}).get("pid")
        if not pid:
            return {"method": "fallback-kill", "ok": False, "reason": "daemon.json 无 pid", "launchctl": first}
        os.kill(int(pid), 15)
        for _ in range(30):
            time.sleep(2)
            try:
                npid = (load(DAEMON_STATE) or {}).get("pid")
            except Exception:  # noqa: BLE001
                npid = None
            if npid and npid != pid:
                return {"method": "fallback-kill", "ok": True, "oldPid": pid, "newPid": npid}
        return {"method": "fallback-kill", "ok": False, "reason": "pid 未变化", "launchctl": first}
    except Exception as exc:  # noqa: BLE001
        return {"method": "fallback-kill", "ok": False, "reason": str(exc), "launchctl": first}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--enable", action="store_true")
    g.add_argument("--disable", action="store_true")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--posts", default=str(DEFAULT_POSTS))
    ap.add_argument("--no-reload", action="store_true")
    ap.add_argument("--force-reload", action="store_true")
    args = ap.parse_args()

    mpath, ppath = Path(args.manifest), Path(args.posts)
    manifest, posts = load(mpath), load(ppath)
    state = is_enabled(manifest, posts)

    if args.status:
        print(json.dumps({"flow": FLOW, "enabled": state,
                          "skill_entry": bool(find_skill(manifest)),
                          "ledger_row_19": find_row(manifest),
                          "posts_usedBy": posts.get("posts", {}).get(POST_KEY, {}).get("usedBy", [])},
                         ensure_ascii=False, indent=2))
        return 0

    changed = False
    if args.enable:
        if state and not args.force_reload:
            print("[noop] 已处于接入态")
        else:
            entry = find_skill(manifest)
            if entry is None:
                manifest.setdefault("skills", []).append(json.loads(json.dumps(SKILL_ENTRY)))
            else:
                entry.clear()
                entry.update(json.loads(json.dumps(SKILL_ENTRY)))
            row = find_row(manifest)
            if row is None:
                manifest.setdefault("ledger_template", []).append(json.loads(json.dumps(LEDGER_ROW_PENDING)))
                row = find_row(manifest)
            row.clear()
            row.update({"row": LEDGER_ROW, "ledger_name": LEDGER_NAME, "schedule": SCHEDULE,
                        "dev_state": "active", "skill": FLOW})
            used = posts.setdefault("posts", {}).setdefault(POST_KEY, {}).setdefault("usedBy", [])
            if FLOW not in used:
                used.append(FLOW)
            problems = validate(mpath, manifest, posts, True)
            if problems:
                print(json.dumps({"ok": False, "problems": problems}, ensure_ascii=False))
                return 1
            dump_atomic(mpath, manifest)
            dump_atomic(ppath, posts)
            changed = True

    if args.disable:
        if not state and not args.force_reload:
            print("[noop] 已处于撤出态")
        else:
            s = find_skill(manifest)
            if s is not None:
                manifest["skills"].remove(s)
            row = find_row(manifest)
            if row is not None:
                row.clear()
                row.update(json.loads(json.dumps(LEDGER_ROW_PENDING)))
            used = posts.get("posts", {}).get(POST_KEY, {}).get("usedBy", [])
            if FLOW in used:
                used.remove(FLOW)
            dump_atomic(mpath, manifest)
            dump_atomic(ppath, posts)
            changed = True

    result = {"ok": True, "flow": FLOW, "action": ("enable" if args.enable else "disable"),
              "changed": changed, "validate": validate(mpath, manifest, posts, bool(args.enable))}
    if args.no_reload:
        result["reload"] = {"method": "skipped", "ok": None}
    elif changed or args.force_reload:
        result["reload"] = reload_daemon()
    else:
        result["reload"] = {"method": "not-needed", "ok": None}
    print(json.dumps(result, ensure_ascii=False))
    if result["validate"] or (result["reload"].get("ok") is False):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
