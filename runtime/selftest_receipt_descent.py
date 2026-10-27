#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-1c 自测：嵌入收据下钻（receipt.extract_signal）+ 认知层加载。

判据纪律（大同）：
- 正负对照：既验「该下钻的能下钻」，也验「不该覆盖的没被覆盖」；
- 真日志回归：拿当日全部真实 skill 日志跑 before/after，证明**没有任何一条变差**
  （原非 None 的码不得变为 None；原有效业务 reason 不得被改写）。

用法：
  env -u PYTHONPATH <py> runtime/selftest_receipt_descent.py [--before <bak路径>]
退出码：0 全过；1 有失败。
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))
import receipt as RC  # noqa: E402

FAIL = []
PASS = []


def check(name: str, got, want):
    if got == want:
        PASS.append(name)
        print("  \033[32mPASS\033[0m %s" % name)
    else:
        FAIL.append(name)
        print("  \033[31mFAIL\033[0m %s\n       got : %r\n       want: %r" % (name, got, want))


def sig_of(obj):
    s = RC.extract_signal(obj)
    return None if s is None else (s["kind"], s["code"])


def load_before(path: Path):
    """按文件加载「下钻前」的 receipt 作为基线模块（备份文件名非 .py，需显式 loader）。"""
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("receipt_before", str(path))
    spec = importlib.util.spec_from_loader("receipt_before", loader)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["receipt_before"] = mod
    loader.exec_module(mod)
    return mod


def _is_wrap(code) -> bool:
    """基线模块无 is_wrapper_reason，回归判据自带一份（与认知层默认前缀一致）。"""
    return isinstance(code, str) and code.strip().lower().startswith("command failed")


def unit_cases():
    print("\n== A. 单元正负对照 ==")
    WRAP = "Command failed: /venv/bin/python workflow_bridge_windows.py --execute"

    # A1 正例：包装层 -> 下钻取真码
    r1 = {"ok": False, "reason": WRAP,
          "stdout": json.dumps({"ok": False, "reason": "windows-driver-local-network-blocked"}) + "\n",
          "stderr": ""}
    check("A1 包装层下钻到真 reason", sig_of(r1),
          ("embedded_reason", "windows-driver-local-network-blocked"))

    # A2 负例：有效业务 reason 不得被覆盖
    r2 = {"ok": False, "reason": "business-real-code", "stdout": json.dumps({"reason": "其他码"})}
    check("A2 有效 reason 不被覆盖", sig_of(r2), ("reason", "business-real-code"))

    # A3 负例：顶层 stage 优先级最高
    r3 = {"stage": "collection", "reason": WRAP}
    check("A3 顶层 stage 优先", sig_of(r3), ("stage", "collection"))

    # A4 负例：嵌套 stage+failed 优先于下钻
    r4 = {"ok": False, "nested": {"stage": "preflight", "status": "failed"},
          "stdout": json.dumps({"reason": "x"})}
    check("A4 嵌套 stage+failed 优先", sig_of(r4), ("nested_stage", "preflight"))

    # A5 正例：包装层内层只有 stage+failed -> embedded_nested_stage
    r5 = {"ok": False, "reason": WRAP,
          "stdout": json.dumps({"ok": False, "phase": {"stage": "send", "status": "failed"}})}
    check("A5 下钻内层 stage+failed", sig_of(r5), ("embedded_nested_stage", "send"))

    # A6 负例：无任何信号 -> None
    check("A6 无信号返回 None", sig_of({"ok": True, "count": 3}), None)

    # A7 负例（回归护栏）：包装层且无嵌入收据 -> 仍退回包装文案（旧行为不变）
    r7 = {"ok": False, "reason": WRAP, "stdout": "", "stderr": ""}
    check("A7 无嵌入收据时退回包装文案", sig_of(r7), ("reason", WRAP))

    # A8 正例：phaseHistory 下钻
    r8 = {"ok": False, "reason": WRAP,
          "stdout": json.dumps({"phaseHistory": ["a", "b-last"]})}
    check("A8 phaseHistory 下钻", RC._phase_history_last(r8), "b-last")

    # A9 认知层：包装层前缀识别
    check("A9 包装层识别(大小写)", (RC.is_wrapper_reason(WRAP), RC.is_wrapper_reason("Command Failed:x"),
                                RC.is_wrapper_reason("legacy-marker-binding-mismatch")),
          (True, True, False))

    # A10 认知层：带命名空间前缀的码也能查到 note
    note = RC.code_note("windows-wechat:windows-driver-local-network-blocked")
    check("A10 命名空间前缀查 note", bool(note and "中继" in note), True)

    # A11 负例：未知码查不到 note（不得凭空造）
    check("A11 未知码无 note", RC.code_note("totally-unknown-code"), None)


def classify_cases():
    print("\n== B. classify_receipt 语义保持 ==")
    import skill_runner as SR
    # B1 exit=0 -> SUCCESS（不变）
    check("B1 exit=0 SUCCESS", SR.classify_with_receipt("", 0, False)[0], "SUCCESS")
    # B2 timed_out -> RECOVERABLE（不变）
    check("B2 超时 RECOVERABLE", SR.classify_with_receipt("", 1, True)[0], "RECOVERABLE")
    # B3 幂等证据缺失 -> 不得静音（UNKNOWN）
    log = RUNTIME / "run_history" / "__nonexistent__.log"
    cat, detail, _ = SR.classify_with_receipt(
        json.dumps({"ok": False, "reason": "legacy-marker-binding-mismatch"}), 1, False,
        str(log), workdir=str(RUNTIME))
    check("B3 幂等无证据 UNKNOWN", cat, "UNKNOWN")
    # B4 真故障包装层经下钻后 detail 含可读码 + note
    text = json.dumps({"ok": False, "reason": "Command failed: x --execute",
                       "stdout": json.dumps({"reason": "windows-driver-local-network-blocked"})})
    cat, detail, sig = SR.classify_with_receipt(text, 1, False, None, workdir=str(RUNTIME))
    check("B4 detail 含真码", "windows-driver-local-network-blocked" in detail, True)
    check("B4 detail 含处置提示", "[note:" in detail, True)
    check("B4 signal 码正确", sig.get("code"), "windows-driver-local-network-blocked")


def real_log_regression(before_path: Path):
    print("\n== C. 真日志 before/after 回归（当日全部 skill 日志）==")
    before = load_before(before_path)
    logs = sorted((RUNTIME / "run_history").glob("2026-*/*--s*.log"))
    if not logs:
        print("  (无历史日志，跳过)"); return
    n = improved = same = worse = 0
    better_samples, worse_samples = [], []
    for lg in logs:
        try:
            txt = lg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        top = RC.parse_top_receipt_text(txt)
        if not top:
            continue
        n += 1
        b = before.extract_signal(top)
        a = RC.extract_signal(top)
        b_k, b_c = (None, None) if b is None else (b["kind"], b["code"])
        a_k, a_c = (None, None) if a is None else (a["kind"], a["code"])
        if b_c == a_c:
            same += 1
            continue
        # 变差判据：原非空 -> 现为空；或原有非包装码被改成包装码
        if a_c is None or (b_c and not _is_wrap(b_c) and _is_wrap(a_c)):
            worse += 1
            if len(worse_samples) < 5:
                worse_samples.append((lg.name, b_c, a_c))
            continue
        improved += 1
        if len(better_samples) < 5:
            better_samples.append((lg.name, b_c, a_c))
    print("  抽样日志: %d  等价: %d  改善: %d  变差: %d" % (n, same, improved, worse))
    for nm, bc, ac in better_samples:
        print("    \033[32m改善\033[0m %s\n         %s  ->  %s" % (nm[:58], str(bc)[:56], str(ac)[:56]))
    for nm, bc, ac in worse_samples:
        print("    \033[31m变差\033[0m %s\n         %s  ->  %s" % (nm[:58], str(bc)[:56], str(ac)[:56]))
    check("C 真日志零回归", worse, 0)
    check("C 至少一条改善", improved > 0, True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default=None, help="下钻前的 receipt.py 备份路径（回归基线）")
    args = ap.parse_args()
    unit_cases()
    classify_cases()
    if args.before and Path(args.before).is_file():
        real_log_regression(Path(args.before))
    else:
        print("\n(未提供 --before，跳过真日志回归)")
    print("\n==== 汇总: PASS=%d FAIL=%d ====" % (len(PASS), len(FAIL)))
    print("selftest_receipt_descent: %s" % ("ALL PASS" if not FAIL else "FAIL"))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
