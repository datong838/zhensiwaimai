#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析「店铺 → 企业微信群」映射表，产出 runtime/group_map.json + 覆盖率报告。

规则：店铺级 > 组织级 > 全局默认；三者都空 = 未覆盖（不发送，宁可漏发不可错发）。

用法：
  env -u PYTHONPATH /Users/ddt/.workbuddy/binaries/python/envs/default/bin/python \
    scripts/resolve_group_map.py [--xlsx docs/店铺群映射_待填_2026-10.xlsx]

退出码：0=全部覆盖 / 3=存在未覆盖店铺 / 4=冲突或读表失败
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from openpyxl import load_workbook

HERE = pathlib.Path(__file__).resolve().parent
WF = HERE.parent
GLOBAL_ROW_LABEL = "（全局默认兜底群）"


def norm(v) -> str:
    return str(v).strip() if v is not None else ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=str(WF / "docs" / "店铺群映射_待填_2026-10.xlsx"))
    ap.add_argument("--out", default=str(WF / ".runtime" / "group_map.json"))
    a = ap.parse_args(argv)

    src = pathlib.Path(a.xlsx)
    if not src.exists():
        print(f"ERR 找不到映射表 {src}", file=sys.stderr)
        return 4
    wb = load_workbook(src, data_only=True)
    if "组织级" not in wb.sheetnames or "店铺级" not in wb.sheetnames:
        print("ERR 缺少 Sheet：需要「组织级」和「店铺级」", file=sys.stderr)
        return 4

    org_map, default_group = {}, ""
    ws = wb["组织级"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        name, _cnt, group = norm(row[0]), row[1], norm(row[2] if len(row) > 2 else "")
        if not name or not group:
            continue
        if name == GLOBAL_ROW_LABEL:
            default_group = group
        else:
            org_map[name] = group

    rows, missing, conflicts = [], [], []
    seen_shop = {}
    ws = wb["店铺级"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        sid, name, org, shop_group = (norm(row[0]), norm(row[1]), norm(row[2]),
                                      norm(row[3] if len(row) > 3 else ""))
        if not sid:
            continue
        if sid in seen_shop:
            conflicts.append(f"店铺ID重复：{sid}")
        seen_shop[sid] = True
        group, level = "", ""
        if shop_group:
            group, level = shop_group, "shop"
        elif org and org in org_map:
            group, level = org_map[org], "org"
        elif default_group:
            group, level = default_group, "global"
        if not group:
            missing.append({"shopId": sid, "shopName": name, "org": org})
        rows.append({"shopId": int(sid), "shopName": name, "org": org,
                     "group": group, "level": level or "none"})

    # 群名重复是合法的（多店一群），但要显式报出来，防止「手滑整列粘贴同一个群」
    gcount = {}
    for r in rows:
        if r["group"]:
            gcount[r["group"]] = gcount.get(r["group"], 0) + 1
    shared = {k: v for k, v in gcount.items() if v > 1}

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "source": str(src),
        "total": len(rows),
        "covered": sum(1 for r in rows if r["group"]),
        "missing": len(missing),
        "byLevel": {lv: sum(1 for r in rows if r["level"] == lv) for lv in ("shop", "org", "global", "none")},
        "sharedGroups": shared,
        "missingList": missing,
        "map": {str(r["shopId"]): r["group"] for r in rows if r["group"]},
        "detail": rows,
    }, ensure_ascii=False, indent=1))

    print(f"OK {out}")
    print(f"总店铺 {len(rows)}　已覆盖 {sum(1 for r in rows if r['group'])}　未覆盖 {len(missing)}")
    print("来源分布：" + "、".join(f"{k}={v}" for k, v in
                                {"shop": sum(1 for r in rows if r['level'] == 'shop'),
                                 "org": sum(1 for r in rows if r['level'] == 'org'),
                                 "global": sum(1 for r in rows if r['level'] == 'global')}.items()))
    if shared:
        top = sorted(shared.items(), key=lambda x: -x[1])[:5]
        print("多店共用的群（前5）：" + "、".join(f"{k}×{v}" for k, v in top))
    if missing:
        print(f"未覆盖示例：" + "、".join(f"{m['shopName']}" for m in missing[:5]))
    if conflicts:
        print("冲突：" + "；".join(conflicts[:5]), file=sys.stderr)
        return 4
    return 0 if not missing else 3


if __name__ == "__main__":
    raise SystemExit(main())
