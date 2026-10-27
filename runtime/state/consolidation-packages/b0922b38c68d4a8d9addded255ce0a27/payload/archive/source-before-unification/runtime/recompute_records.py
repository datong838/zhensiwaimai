#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E4 · 旧记录语义重算（只读）

背景
----
2026-10-06 13:57 上线的「收据驱动分类」（P0-1 / P0-1b / P0-1c）只对**新产生**的
record 生效。13:57 之前落盘的 record 仍是旧分类（典型：`UNKNOWN` + detail
`Command failed: <整条命令>`，真故障码被 Node 包装层吃掉）。

本工具用**当前**分类器，对历史 record 重新算一遍，产出「旧分类 → 新分类」对照，
用于：① 判断台账/看护若要读历史该按什么口径；② 回归验证分类器演进的效果。

纪律
----
* **纯只读**：只读 `runtime/run_history/**/*--record.json` 与其中引用的日志；
  默认只打印，绝不改写任何 record / 日志 / 台账。
* **不是重跑**：它复算的是「同一份日志工件，当前分类器会怎么说」，不代表会重发。
* 需要落报告时，只有显式给 `--json <path>` 才写文件（且只写报告本身）。
* `--selftest` 为 hermetic：在临时目录造日志 + 造 record，自证「能读、能算、能对照」。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent          # runtime/
REPO = ROOT.parent
HISTORY = ROOT / "run_history"
MANIFEST = ROOT / "skills_manifest.json"

sys.path.insert(0, str(ROOT))


def _load_manifest_cwd() -> Dict[str, str]:
    """skill name -> 绝对 workdir（用于幂等证据定位）。缺失则空表。"""
    out: Dict[str, str] = {}
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return out
    skills = m.get("skills") if isinstance(m, dict) else m
    if isinstance(skills, dict):
        skills = [dict(v, name=(v.get("name") or k)) for k, v in skills.items()]
    for s in skills or []:
        name = s.get("name")
        cwd = s.get("cwd")
        if name and cwd:
            out[name] = str((REPO / cwd).resolve())
    return out


def recompute_one(rec: dict, cwd_map: Dict[str, str],
                  sr) -> Tuple[str, str, dict]:
    """对一个 record 复算，返回 (new_category, new_detail, new_signal)。

    复用与运行时**同一入口** `skill_runner.classify_with_receipt`，只是把文本
    换成从 record 自带的日志里读（原 runner 用内存里的 stdout tail，未落 record，
    故以日志文件为准；`parse_top_receipt_log` 就是设计成从日志读的）。
    """
    logs = rec.get("logs") or []
    last_log = logs[-1] if logs else None
    workdir = cwd_map.get(rec.get("skill") or "")
    # 运行时的 `text` 是内存里的 stdout_tail（未落 record），这里以日志尾部等价替代——
    # 否则「无 JSON 收据、靠文本兜底」的记录会被误算成无信号（实测踩过该保真度坑）。
    text = ""
    if last_log:
        try:
            import receipt as _rc  # noqa: PLC0415
            text = _rc._read_tail_text(last_log) or ""
        except Exception:  # noqa: BLE001
            try:
                text = Path(last_log).read_text(encoding="utf-8", errors="replace")[-8000:]
            except Exception:  # noqa: BLE001
                text = ""
    # exit_code 不在 record 里；这些 record 的 status ∈ {FAILED, SKIPPED}，
    # 底层必为非零退出。用 1：只影响「无收据兜底」时 detail 里的数字，不影响分类。
    cat, detail, sig = sr.classify_with_receipt(
        text, 1, False, log_path=last_log, workdir=workdir)
    return cat, detail, sig


def verdict_of(old_cat, old_code, new_cat, new_code) -> str:
    """对照判据（纯函数，便于自测）。

    same       —— 分类与码都没变
    improved   —— ①拿到真业务码（旧缺码/只有包装码）②或新获得带证据的幂等判定
    regressed  —— ①丢掉真码 ②或丢掉幂等判定（须人工看，可能真回归）
    changed    —— 其余（如包装层文案从无到有，属等价噪声）
    """
    old_real = bool(old_code) and not sr_is_wrapper(old_code)
    new_real = bool(new_code) and not sr_is_wrapper(new_code)
    if old_cat == new_cat and (old_code or None) == (new_code or None):
        return "same"
    if new_cat == "SKIPPED_IDEMPOTENT" and old_cat != "SKIPPED_IDEMPOTENT":
        return "improved"
    if old_cat == "SKIPPED_IDEMPOTENT" and new_cat != "SKIPPED_IDEMPOTENT":
        return "regressed"
    if new_real and not old_real:
        return "improved"
    if old_real and not new_real:
        return "regressed"
    return "changed"


def _row(rec: dict, new_cat: str, new_detail: str, new_sig: dict) -> dict:
    old_cat = rec.get("category")
    old_code = (rec.get("fail_signal") or {}).get("code")
    new_code = (new_sig or {}).get("code")
    return {
        "skill": rec.get("skill"), "old_category": old_cat, "new_category": new_cat,
        "old_code": old_code, "new_code": new_code,
        "verdict": verdict_of(old_cat, old_code, new_cat, new_code),
        "new_detail": new_detail[:200],
    }


def sr_is_wrapper(code) -> bool:
    try:
        import receipt as _r
        return bool(_r.is_wrapper_reason(code))
    except Exception:
        s = str(code or "")
        return s.startswith("Command failed") or s.startswith("exit=")


def collect(day: Optional[str], all_days: bool) -> List[Path]:
    if all_days:
        return sorted(HISTORY.glob("*/*--record.json"))
    if day:
        return sorted((HISTORY / day).glob("*--record.json"))
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    return sorted((HISTORY / today).glob("*--record.json"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="E4 旧记录语义重算（只读）")
    ap.add_argument("--date", help="YYYY-MM-DD（默认今天）")
    ap.add_argument("--all", action="store_true", help="全部历史日期")
    ap.add_argument("--json", help="把报告写到该路径（默认只打印）")
    ap.add_argument("--quiet", action="store_true", help="只打汇总")
    ap.add_argument("--selftest", action="store_true", help="hermetic 自测")
    args = ap.parse_args(argv)

    import skill_runner as sr  # noqa: PLC0415

    if args.selftest:
        return _selftest(sr)

    cwd_map = _load_manifest_cwd()
    files = collect(args.date, args.all)

    rows: List[dict] = []
    skipped_success = 0
    errors = 0
    for p in files:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            errors += 1
            continue
        if rec.get("category") == sr.CAT_SUCCESS:
            skipped_success += 1
            continue
        try:
            new_cat, new_detail, new_sig = recompute_one(rec, cwd_map, sr)
        except Exception as e:  # noqa: BLE001
            errors += 1
            rows.append({"skill": rec.get("skill"), "verdict": "error",
                         "new_detail": "recompute-failed: %r" % e})
            continue
        rows.append(_row(rec, new_cat, new_detail, new_sig))

    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    print("recompute-records: files=%d success_skipped=%d errors=%d"
          % (len(files), skipped_success, errors))
    print("  verdict:", ", ".join("%s=%d" % (k, v) for k, v in sorted(counts.items()))
          or "(none)")
    if counts.get("regressed"):
        print("  ⚠ regressed=%d —— 需人工确认是否真回归（明细见下）" % counts["regressed"])
    if not args.quiet:
        for r in rows:
            if r["verdict"] == "same":
                continue
            print("  [%s] %s" % (r["verdict"], r.get("skill")))
            print("      old: %s / %s" % (r.get("old_category"), r.get("old_code")))
            print("      new: %s / %s" % (r.get("new_category"), r.get("new_code")))

    if args.json:
        Path(args.json).write_text(
            json.dumps({"files": len(files), "counts": counts, "rows": rows},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print("  report -> %s" % args.json)
    return 0


# ---------------------------------------------------------------- hermetic 自测

def _selftest(sr) -> int:
    ok = True

    def check(name: str, cond: bool):
        nonlocal ok
        print("  [%s] %s" % ("OK" if cond else "FAIL", name))
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # 1) 造一条「被 Node 包装层吃掉真码」的日志。
        #    真实结构：外层 reason="Command failed: <命令>"（包装层），真业务码在被
        #    转义进 `stdout` 字符串的子收据里 —— 与线上 s2.log 逐字同形。
        inner = json.dumps({"ok": False,
                            "reason": "windows-driver-local-network-blocked"},
                           ensure_ascii=False)
        outer = json.dumps({"ok": False,
                            "reason": "Command failed: node foo.mjs",
                            "stdout": inner}, ensure_ascii=False)
        log = d / "wrap.log"
        log.write_text(outer + "\n", encoding="utf-8")

        rec = {"skill": "synthetic-flow", "category": "UNKNOWN",
               "status": "FAILED", "logs": [str(log)], "fail_signal": {}}
        cat, detail, sig = recompute_one(rec, {}, sr)
        check("下钻：从包装层 stdout 拿到内层真码",
              (sig or {}).get("code") == "windows-driver-local-network-blocked")
        check("下钻：kind 标为 embedded_*",
              str((sig or {}).get("kind", "")).startswith("embedded_"))
        check("下钻：detail 不再只含命令",
              "windows-driver-local-network-blocked" in detail)
        row = _row(rec, cat, detail, sig)
        check("对照：判为 improved（旧无码、新有真码）", row["verdict"] == "improved")

        # 1b) 反向保险：外层若本身就是有效业务 reason，不得被内层覆盖（语义优先级保持）
        log2 = d / "direct.log"
        log2.write_text(json.dumps({"ok": False, "reason": "direct-business-code"},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
        rec_b = {"skill": "synthetic-flow", "category": "UNKNOWN", "status": "FAILED",
                 "logs": [str(log2)], "fail_signal": {}}
        _, _, sig_b = recompute_one(rec_b, {}, sr)
        check("优先级：外层有效 reason 不被内层下钻覆盖",
              (sig_b or {}).get("code") == "direct-business-code"
              and (sig_b or {}).get("kind") == "reason")

        # 1c) 嵌入收据里是 stage（非 reason）⇒ kind 应为 embedded_stage，码取 stage 值
        log4 = d / "embstage.log"
        inner4 = json.dumps({"ok": False, "stage": "collection"}, ensure_ascii=False)
        log4.write_text(json.dumps({"ok": False, "reason": "Command failed: node baz.mjs",
                                    "stdout": inner4}, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        rec_d = {"skill": "synthetic-flow", "category": "UNKNOWN", "status": "FAILED",
                 "logs": [str(log4)], "fail_signal": {}}
        _, _, sig_d = recompute_one(rec_d, {}, sr)
        check("下钻：嵌入收据为 stage 时 kind=embedded_stage、码=stage 值",
              (sig_d or {}).get("code") == "collection"
              and (sig_d or {}).get("kind") == "embedded_stage")

        # 1d) 包装层 reason 但无嵌入收据 ⇒ 不得凭空造码（诚实退化为包装码）
        log3 = d / "wraponly.log"
        log3.write_text(json.dumps({"ok": False, "reason": "Command failed: node bar.mjs"},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
        rec_c = {"skill": "synthetic-flow", "category": "UNKNOWN", "status": "FAILED",
                 "logs": [str(log3)], "fail_signal": {}}
        _, _, sig_c = recompute_one(rec_c, {}, sr)
        check("诚实：无嵌入收据时不造真码（退化为包装码）",
              (sig_c or {}).get("code", "").startswith("Command failed"))

        # 2) 负例：根本没有收据 ⇒ 不该凭空造码
        bare = d / "bare.log"
        bare.write_text("some random failure without json\n", encoding="utf-8")
        rec2 = {"skill": "x", "category": "UNKNOWN", "status": "FAILED",
                "logs": [str(bare)], "fail_signal": {}}
        _, _, sig2 = recompute_one(rec2, {}, sr)
        check("负例：无收据时信号为空", not (sig2 or {}).get("code"))

        # 3) 幂等负例：裸 classify 不得静音（没有 workdir 证据）
        rec3 = {"skill": "x", "category": "UNKNOWN", "status": "FAILED",
                "logs": [str(bare)], "fail_signal": {}}
        cat3, _, _ = recompute_one(rec3, {}, sr)
        check("负例：无证据不静音（非 SKIPPED）", cat3 != "SKIPPED_IDEMPOTENT")

        # 4) 对照判据两轴（正负都要有）
        check("判据：同分类同码 = same",
              verdict_of("UNKNOWN", "a", "UNKNOWN", "a") == "same")
        check("判据：旧无码→新真码 = improved",
              verdict_of("UNKNOWN", None, "UNKNOWN", "real-code") == "improved")
        check("判据：旧包装码→新真码 = improved",
              verdict_of("UNKNOWN", "Command failed: x", "UNKNOWN", "real-code") == "improved")
        check("判据：旧真码→新无码 = regressed",
              verdict_of("UNKNOWN", "real-code", "UNKNOWN", None) == "regressed")
        check("判据：UNKNOWN→SKIPPED_IDEMPOTENT = improved",
              verdict_of("UNKNOWN", None, "SKIPPED_IDEMPOTENT", None) == "improved")
        check("判据：SKIPPED_IDEMPOTENT→UNKNOWN = regressed",
              verdict_of("SKIPPED_IDEMPOTENT", None, "UNKNOWN", None) == "regressed")
        check("判据：包装码从无到有 = changed（等价噪声）",
              verdict_of("UNKNOWN", None, "UNKNOWN", "Command failed: y") == "changed")

    print("recompute-records-selftest: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
