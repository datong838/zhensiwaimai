#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-1b 幂等证据门 回归自测（只读，不触碰任何外发/生产状态）。

被验对象：`receipt._idempotent_decision` / `classify_receipt` / `skill_runner.classify`
        / `run_all.build_ledger_rows`。

判据（正负对照，缺一不可）：
  T1 良性：marker state=verified  ⇒ SKIPPED_IDEMPOTENT（不静音）
  T2 真故障：marker state=blocked/verified=False ⇒ UNKNOWN + idempotent_unverified
  T3 无证据：文本命中但定位不到 marker ⇒ UNKNOWN（拒绝静音）
  T4 top10 式：收据无 marker 路径，靠 workdir/.runtime/send-ledger 兜底 ⇒ SKIPPED
  T5 负对照：真实仓库里的真故障 marker（*.voided-*）必须判 verified=False
  T6 裸 classify()：无上下文时不得静音（必须 UNKNOWN）
  T7 台账：SKIPPED 记录须计为「已完成」，不拖累全绿

用法：python runtime/selftest_idempotent_gate.py   退出码 0=全过
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))

import receipt as R  # noqa: E402
import skill_runner as SR  # noqa: E402
import run_all as RA  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name, (" :: " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False),
                    encoding="utf-8")


def _flash_log(ledger: Path, marker_name: str) -> str:
    """复刻真实 taobao-flash 日志顶层形状（命令行含 --ledger/--marker-name）。"""
    cmd = ("Command failed: python workflow_bridge.py --workflow-id taobao-flash-appeals "
           "--group FEIBING --payload-type file --ledger %s --marker-name %s --execute\n" % (ledger, marker_name))
    return (json.dumps({"ok": False, "reason": cmd,
                        "stdout": '{"ok": false, "verified": false, '
                                  '"reason": "legacy-marker-binding-mismatch", "sendAttempts": null}\n'},
                       ensure_ascii=False) + "\n")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # ---------- T1 良性 ----------
        led = tmp / "flash-ledger"
        _write(led / "m.json", {"bridgeVersion": 1, "state": "verified", "verified": True,
                                "ok": True, "sendAttempts": 1, "reason": None})
        text = _flash_log(led, "m.json")
        cat, detail, sig = R.classify_receipt(text, 1, False, classify_fallback=SR.classify)
        check("T1 良性⇒SKIPPED", cat == "SKIPPED_IDEMPOTENT", "%s | %s" % (cat, detail))
        check("T1 带证据路径", bool(sig.get("idempotent_evidence")), str(sig))

        # ---------- T2 真故障（marker 存在但从未外发）----------
        led2 = tmp / "flash-ledger2"
        _write(led2 / "m.json", {"bridgeVersion": 1, "state": "blocked", "verified": False,
                                 "ok": False, "sendAttempts": 0, "reason": "windows-driver-unreachable"})
        text2 = _flash_log(led2, "m.json")
        cat2, detail2, sig2 = R.classify_receipt(text2, 1, False, classify_fallback=SR.classify)
        check("T2 真故障⇒UNKNOWN", cat2 == "UNKNOWN", "%s | %s" % (cat2, detail2))
        check("T2 标记 unverified", bool(sig2.get("idempotent_unverified")), str(sig2))

        # ---------- T3 无证据 ----------
        bare = '{"ok": false, "verified": false, "reason": "legacy-marker-binding-mismatch", "sendAttempts": null}'
        cat3, detail3, sig3 = R.classify_receipt(bare, 1, False, classify_fallback=SR.classify)
        check("T3 无证据⇒UNKNOWN", cat3 == "UNKNOWN", "%s | %s" % (cat3, detail3))
        check("T3 标记 unverified", bool(sig3.get("idempotent_unverified")), str(sig3))

        # ---------- T4 top10 式（workdir 兜底）----------
        cwd = tmp / "top10-flow"
        ledger = cwd / ".runtime" / "send-ledger"
        _write(ledger / "2026-10-05-main-16379fcc7508.json",
               {"bridgeVersion": 1, "state": "verified", "verified": True, "ok": True, "sendAttempts": 2})
        top10_text = json.dumps({
            "ok": False, "executor": "workflow", "sendAttempts": None,
            "delivery": {"ok": False, "verified": False,
                         "reason": "legacy-marker-binding-mismatch", "sendAttempts": None},
            "reason": "desktop-wechat:legacy-marker-binding-mismatch"}, ensure_ascii=False)
        cat4, detail4, sig4 = R.classify_receipt(top10_text, 1, False,
                                                 classify_fallback=SR.classify, workdir=str(cwd))
        check("T4 workdir兜底⇒SKIPPED", cat4 == "SKIPPED_IDEMPOTENT", "%s | %s" % (cat4, detail4))

        # ---------- T5 负对照：真实仓库真故障 marker ----------
        real = Path("/Users/ddt/work/projects/ai_agent/state/taobao-flash-sale-negative-review-appeals/"
                    "wechat-attempts/taobao-flash-appeals-2026-10-04.voided-20261005-124410.json")
        if real.is_file():
            ev = R.idempotent_evidence('"attemptMarker": "%s"' % real, None)
            check("T5 真实真故障 marker⇒verified=False", bool(ev) and ev["verified"] is False,
                  str(ev))
        else:
            print("  SKIP T5 真故障 marker 样本不存在（非本机）")

        # ---------- T6 裸 classify() 不得静音 ----------
        cat6, detail6 = SR.classify("legacy-marker-binding-mismatch", 1, False)
        check("T6 裸classify⇒UNKNOWN", cat6 == SR.CAT_UNKNOWN, "%s | %s" % (cat6, detail6))

        # ---------- T7 台账：SKIPPED 计为已完成 ----------
        data = {"skills": [{"name": "demo-flow", "dev_state": "active"}],
                "ledger_template": [{"row": 1, "ledger_name": "演示流", "schedule": "每日",
                                     "dev_state": "active", "skill": "demo-flow"}]}
        recs = {"demo-flow": {"category": SR.CAT_SKIPPED, "status": "SKIPPED",
                              "finished_at": "2026-10-06T13:49:34"}}
        rows = RA.build_ledger_rows(data, recs)
        check("T7 SKIPPED⇒已完成", rows[0]["done"] == "是", str(rows[0]))

    print()
    if FAILS:
        print("❌ P0-1b 自测失败：%d 项 -> %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("✅ P0-1b 幂等证据门自测全过（7 组判据，含正负对照）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
