#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 · 流目标群「四处同收口」一致性机检（治 2026-10-21 top10 漏改第 4 处）。

背景（MEMORY #83）：改某条流的目标群必须同步 4 处——
  1. skills/workflows/<flow>/runtime-policy.json → targetGroup
  2. skills/workflows/<flow>/scripts/phone_executor.py → TARGET_GROUP
  3. skills/workflows/<flow>/scripts/runtime_guard.py → CANONICAL_TARGET_GROUP
  4. skills/wechat-messaging/config/registry-routing.json → routes.<route>.group
     （外置路由表，不在封印清单，最易漏）
10-20 top10 改群漏了第 4 处，10-21 连续 4 轮 workflow-target-or-payload-mismatch。

本脚本只读校验（fail-closed）：解析 4 处实际生效值（路由表经 workflow_bridge
REGISTRY 解析，与生产同源），任一不一致 → exit 1 + 明细。
用法：
  python3 group_consistency_check.py [--flow top10]        # 校验单流（默认 top10）
  python3 group_consistency_check.py --all                 # 校验路由表全部流量化流
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parent
BRIDGE = REPO_ROOT / "skills" / "wechat-messaging" / "scripts" / "workflow_bridge.py"
ROUTES = REPO_ROOT / "skills" / "wechat-messaging" / "config" / "registry-routing.json"
GROUP_ALIAS = {
    "GROUP": "FEIBING NEO AI数字员工",
    "JINSHA_GROUP": "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰",
}

# 路由名 → (workflow 目录名, 群名配置点形态)。
# 形态：'top10-style' = policy.targetGroup + phone_executor.TARGET_GROUP + guard.CANONICAL_TARGET_GROUP
#       'mjs-policy'  = scripts/<file> 里的 group:'...' 常量（JS 单点配置）
#       'mjs-const'   = scripts/jinsha.mjs 的 GROUP 常量
ROUTE_FLOWS = {
    "top10": ("daily-top10-to-wechat-group", "top10-style"),
    "negative-reviews": ("daily-negative-reviews", "mjs-policy"),
    "negative-feedback-appeals": ("negative-feedback-list-appeals", "mjs-const"),
    "jinsha-reports": ("daily-jinsha-reports-to-business-wechat", "mjs-policy-jinsha"),
}


def resolve_alias(v: str) -> str:
    return GROUP_ALIAS.get(v, v)


def load_registry_target(route: str):
    """与生产同源：经 workflow_bridge.REGISTRY 解析路由目标群。"""
    spec = importlib.util.spec_from_file_location("workflow_bridge", BRIDGE)
    wb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wb)
    target = wb.REGISTRY.get(route)
    if not target:
        return None, "routes.%s 不存在" % route
    group = target[0]
    return group, None


def policy_target(flow_dir: Path):
    p = flow_dir / "runtime-policy.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("targetGroup"), None
    except (OSError, ValueError) as e:
        return None, "runtime-policy.json 读失败: %r" % e


def _py_const(path: Path, const: str):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, "读失败: %r" % e
    m = re.search(r'^%s\s*=\s*["\']([^"\']+)["\']' % re.escape(const),
                  text, re.M)
    if not m:
        return None, "常量 %s 未找到" % const
    return m.group(1), None


def _js_group_const(path: Path, pattern: str):
    """从 mjs 文件抓 group:'...' 或 GROUP = '...' 常量。pattern 传正则。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, "读失败: %r" % e
    m = re.search(pattern, text)
    if not m:
        return None, "常量未找到（%s）" % pattern
    return m.group(1), None


JS_CONFIG = {
    "mjs-policy": [("scripts/workflow_policy.mjs", r"group\s*:\s*['\"]([^'\"]+)['\"]")],
    "mjs-policy-jinsha": [("scripts/business_workflow_policy.mjs", r"group\s*:\s*['\"]([^'\"]+)['\"]")],
    "mjs-const": [("scripts/jinsha.mjs", r"GROUP\s*=\s*['\"]([^'\"]+)['\"]")],
}


def check_flow(route: str, flow: str, style: str) -> list:
    """返回该流的问题列表（空=全部一致）。"""
    problems = []
    flow_dir = REPO_ROOT / "skills" / "workflows" / flow
    registry_group, err = load_registry_target(route)
    if err:
        return ["路由表: %s" % err]
    registry_group = resolve_alias(registry_group)

    if style == "top10-style":
        checks = [("policy", *policy_target(flow_dir)),
                  ("phone_executor", *_py_const(flow_dir / "scripts" / "phone_executor.py", "TARGET_GROUP")),
                  ("runtime_guard", *_py_const(flow_dir / "scripts" / "runtime_guard.py", "CANONICAL_TARGET_GROUP"))]
        for name, val, err in checks:
            if err:
                problems.append("%s: %s" % (name, err))
            elif resolve_alias(val) != registry_group:
                problems.append("%s =%r ≠ 路由表 %r" % (name, val, registry_group))
    else:
        for rel, pat in JS_CONFIG[style]:
            val, err = _js_group_const(flow_dir / rel, pat)
            if err:
                problems.append("%s: %s" % (rel, err))
            elif resolve_alias(val) != registry_group:
                problems.append("%s group=%r ≠ 路由表 %r" % (rel, val, registry_group))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="流目标群四处一致性机检")
    ap.add_argument("--flow", default="top10", help="路由名（默认 top10）")
    ap.add_argument("--all", action="store_true", help="校验 ROUTE_FLOWS 全部")
    args = ap.parse_args()

    routes = dict(ROUTE_FLOWS) if args.all else {args.flow: ROUTE_FLOWS.get(args.flow)}
    failed = False
    for route, spec in routes.items():
        if not spec:
            print("[FAIL] %s: 未登记 ROUTE_FLOWS 映射（新流请补登）" % route)
            failed = True
            continue
        flow, style = spec
        problems = check_flow(route, flow, style)
        if problems:
            failed = True
            print("[FAIL] %s (%s):" % (route, flow))
            for p in problems:
                print("  - %s" % p)
        else:
            print("[ok] %s (%s) 四处一致" % (route, flow))
    if failed:
        print("\n结论：不一致——按 MEMORY #83 四处同收口（改完重跑本脚本复验）")
        return 1
    print("\n结论：全部一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
