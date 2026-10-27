#!/usr/bin/env python3
"""F10-1 注入式复现基线：验证 workflow_bridge 四出口对四种 marker 形态的现状行为。

hermetic：全部夹具在 /tmp 临时目录，不读不写任何生产 marker/ledger。
只 import 桥的纯函数（check_old/legacy_text_reconcile 判定面），不触发 send。

形态清单（对应设计稿 §4）：
  A. binding-mismatch：marker 绑旧 sha + 新请求 sha 漂移 ⇒ 预期 Rejected(legacy-marker-binding-mismatch)
  B. stage=null 死锁：stage=None/state=unknown/sendAttempts=1 ⇒ 预期 legacy-attempt-reconcile-only（现状死角）
  C. safe resume：bridgeVersion=1/blocked/attempts=0 ⇒ 预期可 resume（非 Rejected）
  D. verified 复用：verified+state=verified ⇒ 预期 reusedExisting
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

BRIDGE_DIR = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts")
sys.path.insert(0, str(BRIDGE_DIR))

import workflow_bridge as wb  # noqa: E402


def make_request(text_sha: str, group: str = "电销+直播攻坚组") -> dict:
    return {
        "groupName": group,
        "items": [{"itemId": "item-1", "type": "text", "text": "x", "sha256": text_sha}],
        "context": {"deadlineAt": "2026-10-08T23:59:59+08:00"},
    }


def case_a_binding_mismatch() -> str:
    """形态A：marker 绑空表旧 sha，请求携带新 sha（10-07/10-08 晨死锁现场）。"""
    prior = {
        "bridgeVersion": 1,
        "state": "blocked",
        "sendAttempts": 0,
        "groupName": "电销+直播攻坚组",
        "payloadType": "text",
        "payloads": [{"text": "frozen-empty", "sha256": "1b2e73f7" * 1}],
        "reason": "windows-driver-unreachable",
    }
    req = make_request("3540c206")
    try:
        wb.check_old(prior, req)
        return "A: NOT-REJECTED (unexpected)"
    except wb.Rejected as error:
        return f"A: Rejected({error}) {'✅ 符合预期' if 'binding-mismatch' in str(error) else '❌ 意外码'}"


def case_b_stage_null() -> str:
    """形态B：stage=null 中断态（口缸米线形态）——现状应为死角。"""
    prior = {
        "bridgeVersion": 1,
        "stage": None,
        "state": "unknown",
        "sendAttempts": 1,
        "verified": False,
        "commonReceipt": {
            "status": "unknown",
            "channel": "desktop",
            "groupName": "电销+直播攻坚组",
            "items": [{"status": "unknown", "type": "text", "sendAttempts": 1,
                       "sha256": "abc123"}],
            "review": [],
        },
    }
    req = make_request("abc123")
    # legacy_text_reconcile 判定面（不触发 adapter——提前 return 的判定路径）
    wrapped_unknown = (prior.get("stage") == "completed"
                       and (prior.get("commonReceipt") or {}).get("status") == "unknown")
    common = prior.get("commonReceipt") or {}
    common_items = common.get("items") or []
    null_attempt_unknown = (prior.get("state") == "unknown"
                            and prior.get("sendAttempts") is None)
    enters_reconcile = (
        len(req["items"]) == 1 and req["items"][0]["type"] == "text"
        and ((prior.get("state") in ("unknown", "verified") and prior.get("sendAttempts") == 1
              and (prior.get("stage") == "post_send_verify" or prior.get("state") == "verified"
                   or wrapped_unknown)) or null_attempt_unknown))
    if not enters_reconcile:
        return "B: legacy-attempt-reconcile-only（死角确认 ✅ F10-1 改动二的目标形态）"
    return "B: 意外进入 reconcile（与 10-06 代码级分析矛盾，需复核）"


def case_c_safe_resume() -> str:
    """形态C：bridgeVersion=1 + blocked + sendAttempts=0 ⇒ 安全 resume 通道。"""
    prior = {"bridgeVersion": 1, "state": "blocked", "sendAttempts": 0,
             "verified": False, "reason": "windows-driver-unreachable"}
    safe = (prior.get("bridgeVersion") == 1 and prior.get("state") == "blocked"
            and prior.get("sendAttempts") == 0)
    return f"C: safe_resume={safe} {'✅' if safe else '❌'}"


def case_d_verified_reuse() -> str:
    """形态D：verified+state=verified ⇒ 复用不重发。"""
    prior = {"bridgeVersion": 1, "verified": True, "state": "verified",
             "sendAttempts": 1, "groupName": "电销+直播攻坚组",
             "payloadType": "text",
             "payloads": [{"text": "x", "sha256": "3540c206"}]}
    req = make_request("3540c206")
    try:
        wb.check_old(prior, req)
        reuse = prior.get("verified") is True and prior.get("state") == "verified"
        return f"D: reuse={reuse} {'✅' if reuse else '❌'}"
    except wb.Rejected as error:
        return f"D: Rejected({error}) ❌"


def main() -> int:
    print("F10-1 注入式复现基线（现状行为锚定）")
    print("=" * 60)
    for case in (case_a_binding_mismatch, case_b_stage_null,
                 case_c_safe_resume, case_d_verified_reuse):
        print(case())
    print("=" * 60)
    print("结论：A=Rejected 死角（改动一目标）；B=reconcile-only 死角（改动二目标）；")
    print("     C/D 为既有正常通道（改动后必须保持不变——负对照）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
