#!/usr/bin/env python3
"""flow-order-assert: 只读校验「先申诉 → 后汇报」的排班顺序（大同令，防回归）。

大同令（2026-10-06）：brand-negative-review-appeal-followup 必须在**全部申诉流之后**
执行 —— 否则会出现「还没申诉完就先往品牌群汇报」的错误时序。

判据：brand-negative-review-appeal-followup.order  >  max(所有申诉流.order)

申诉流识别：流名含 "negative-review" / "negative_review" / "appeal"，
但排除 brand 自身（大小写不敏感）。

用法：
  python3 assert_flow_order.py            # 校验线上 runtime/skills_manifest.json
  python3 assert_flow_order.py <path>     # 校验指定 manifest（离线/正负对照）
  python3 assert_flow_order.py --selftest # hermetic 自测（临时 manifest，三例对照）

输出末行恒为：
  flow-order-assert: ALL PASS      （通过，exit 0）
  flow-order-assert: FAIL ...      （不通过，exit 1）
纯只读：只读 manifest，不写任何文件、不发消息、不动 daemon。
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "skills_manifest.json"
BRAND = "brand-negative-review-appeal-followup"
APPEAL_HINTS = ("negative-review", "negative_review", "appeal")


def _skills(doc) -> dict:
    if isinstance(doc, dict) and "skills" in doc:
        s = doc["skills"]
        if isinstance(s, dict):
            return s
        return {(x.get("id") or x.get("name")): x for x in s}
    if isinstance(doc, dict):
        return doc
    return {(x.get("id") or x.get("name")): x for x in doc}


def evaluate(manifest_path) -> tuple:
    """纯函数式判定：返回 (ok: bool, verdict: str, lines: list[str])。

    verdict 形如 "ALL PASS" / "FAIL brand-flow-absent"；lines 为可打印的诊断行。
    """
    lines = []
    try:
        doc = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, "FAIL manifest-unreadable: %s" % exc, lines

    skills = _skills(doc)
    orders = []
    for name, spec in skills.items():
        if not isinstance(spec, dict):
            continue
        o = spec.get("order")
        if isinstance(o, int):
            orders.append((name, o))
    if not orders:
        return False, "FAIL no-orders-found (manifest 结构异常，零个 order)", lines

    def is_appeal(n: str) -> bool:
        low = n.lower()
        return any(h in low for h in APPEAL_HINTS) and low != BRAND

    appeals = sorted([(n, o) for n, o in orders if is_appeal(n)], key=lambda x: x[1])
    brand = [(n, o) for n, o in orders if n.lower() == BRAND]

    lines.append("申诉流 (%d):" % len(appeals))
    for n, o in appeals:
        lines.append("  order=%-4s %s" % (o, n))
    if not brand:
        return False, ("FAIL brand-flow-absent (manifest 里找不到 %s，"
                       "排班被删/改名 ⇒ 无法保证时序)" % BRAND), lines
    b_name, b_order = brand[0]
    lines.append("brand: order=%-4s %s" % (b_order, b_name))
    if not appeals:
        return False, ("FAIL no-appeal-flows (brand 存在但未识别到任何申诉流，"
                       "清单改名？判 FAIL 以免掩盖回归)"), lines

    max_appeal = max(o for _, o in appeals)
    worst = [n for n, o in appeals if o == max_appeal]
    if b_order > max_appeal:
        lines.append("")
        lines.append("判据: brand.order %s > max(申诉流).order %s ✅" % (b_order, max_appeal))
        return True, "ALL PASS", lines
    lines.append("")
    lines.append("判据: brand.order %s <= max(申诉流).order %s ❌ (并列最高: %s)"
                 % (b_order, max_appeal, ", ".join(worst)))
    return False, ("FAIL order-regression "
                   "(brand 未排在全部申诉流之后 ⇒ 违反「先申诉→后汇报」)"), lines


def main(argv) -> int:
    if argv and argv[0] == "--selftest":
        return _selftest()
    path = Path(argv[0]) if argv else DEFAULT_MANIFEST
    ok, verdict, lines = evaluate(path)
    for ln in lines:
        print(ln)
    print("flow-order-assert: %s" % verdict)
    return 0 if ok else 1


def _selftest() -> int:
    """hermetic 三例对照：正例通过 / 顺序回归必FAIL / brand 缺失必FAIL。"""
    ok = True

    def mk(brand_order, drop_brand=False):
        sk = [
            {"name": "daily-negative-reviews", "order": 2},
            {"name": "meituan-waimai-negative-review-appeals-11", "order": 7},
            {"name": "taobao-flash-sale-negative-review-appeals", "order": 8},
        ]
        if not drop_brand:
            sk.append({"name": BRAND, "order": brand_order})
        return {"skills": sk}

    cases = [
        ("正例-顺序成立", mk(19), True, "ALL PASS"),
        ("负例-顺序回归", mk(5), False, "FAIL order-regression"),
        ("负例-brand缺失", mk(19, drop_brand=True), False, "FAIL brand-flow-absent"),
    ]
    with tempfile.TemporaryDirectory() as td:
        for i, (label, doc, want_ok, want_prefix) in enumerate(cases, 1):
            p = Path(td) / ("m%d.json" % i)
            p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            got_ok, verdict, _ = evaluate(p)
            good = (got_ok == want_ok) and verdict.startswith(want_prefix)
            ok = ok and good
            print("  [%s] %s ⇒ %s" % ("OK" if good else "FAIL", label, verdict))
    print("assert-flow-order selftest: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
