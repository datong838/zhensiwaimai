#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「店铺 → 企业微信群」映射待填表（真数据：863 家营业中店铺，无 mock）。

为什么需要这张表：发送路由键=企业微信群名，缺它发不出去。网关 list_sessions 只回
当前可见的 10 条会话、也没有搜索接口 ⇒ 群名只能由人工提供或从群列表导出。

表结构（三级回落，优先级从上到下）：
  ① 店铺级：某家店单独指定群（大多数店不用填）
  ② 组织级：该运营组织下所有店共用一个群（推荐：先把 15 个组织填满）
  ③ 全局默认：兜底群（可留空 = 不兜底，宁可漏发不可错发）

用法：
  env -u PYTHONPATH /Users/ddt/.workbuddy/binaries/python/envs/default/bin/python \
    scripts/build_group_map_sheet.py [--pool .runtime/store_pool_brand.json]
产物：
  docs/店铺群映射_待填_YYYY-MM.xlsx
"""
from __future__ import annotations

import argparse
import json
import pathlib

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="2F5597")
HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=10)
NOTE_FONT = Font(name="微软雅黑", size=10, color="444441")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")   # 待人工填写列=浅黄
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

HERE = pathlib.Path(__file__).resolve().parent
WF = HERE.parent


def head(ws, cols):
    for i, (name, w) in enumerate(cols, start=1):
        c = ws.cell(row=1, column=i, value=name)
        c.fill, c.font, c.border = HEADER_FILL, HEADER_FONT, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default=str(WF / ".runtime" / "store_pool_brand.json"))
    ap.add_argument("--month", default="2026-10")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)

    doc = json.loads(pathlib.Path(a.pool).read_text())
    shops = [s for s in doc.get("shops", []) if "营业中" in (s.get("status") or "")]
    shops.sort(key=lambda s: ((s.get("orgLabel") or ""), (s.get("shopName") or "")))

    orgs = {}
    for s in shops:
        k = (s.get("orgLabel") or "顶级单店").strip() or "顶级单店"
        orgs[k] = orgs.get(k, 0) + 1

    out = pathlib.Path(a.out) if a.out else WF / "docs" / f"店铺群映射_待填_{a.month}.xlsx"
    wb = Workbook()
    wb.remove(wb.active)

    # —— 说明 ——
    ws = wb.create_sheet("说明", 0)
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 112
    lines = [
        ("店铺 → 企业微信群 映射（待填）", "T"),
        (f"店铺数 {len(shops)} 家（营业中）　｜　运营组织 {len(orgs)} 个　｜　来源：品牌商 9230 运营组织树　｜　账期 {a.month}", "N"),
        ("一、为什么要填这张表", "H"),
        ("发送时用「企业微信群名」当路由键：群名错一个字就发不出去，填错店名则会发到别人群（生产事故）。", "P"),
        ("网关只能列出当前可见的 10 条会话、没有搜索接口，所以群名必须由人工提供。", "P"),
        ("二、三级回落规则（只认顺序，不猜）", "H"),
        ("① 店铺级（本表 Sheet「店铺级」最后一列）——某家店要单独进某个群时填；", "P"),
        ("② 组织级（Sheet「组织级」）——该运营组织下所有店共用一个群，推荐先填这 14 行（13 个组织 + 1 行全局兜底）；", "P"),
        ("③ 全局默认（Sheet「组织级」最后一行）——兜底群，留空表示不兜底。", "P"),
        ("优先级 ① > ② > ③。三者都没有的店，解析结果为「未覆盖」，不会被发送（宁可漏发，不可错发）。", "P"),
        ("三、怎么填", "H"),
        ("· 只填黄色底色的列，一个字都不要改店铺ID/店铺名称（脚本按店铺ID join）。", "P"),
        ("· 群名必须与微信里显示的群名完全一致，包括全角括号、空格、emoji。", "P"),
        ("· 多店共用一个群是允许的；同一家店填两个群不合法（脚本会报冲突）。", "P"),
        ("四、填完怎么校验", "H"),
        ("env -u PYTHONPATH /Users/ddt/.workbuddy/binaries/python/envs/default/bin/python scripts/resolve_group_map.py", "P"),
        ("输出 .runtime/group_map.json：覆盖多少家、未覆盖多少家、哪些群名重复、哪些店冲突。", "P"),
        ("退出码：0=全部覆盖　3=有未覆盖店铺　4=冲突（同店多群）", "P"),
    ]
    r = 1
    for text, kind in lines:
        c = ws.cell(row=r, column=2, value=text)
        c.alignment = Alignment(vertical="center", wrap_text=True)
        if kind == "T":
            c.font = Font(name="微软雅黑", size=14, bold=True, color="1F3864")
            ws.row_dimensions[r].height = 30
        elif kind == "H":
            c.font = Font(name="微软雅黑", size=11, bold=True, color="2F5597")
            ws.row_dimensions[r].height = 24
        elif kind == "N":
            c.font = NOTE_FONT
            ws.row_dimensions[r].height = 22
        else:
            c.font = BODY_FONT
            ws.row_dimensions[r].height = 20
        r += 1

    # —— 组织级 ——
    ws = wb.create_sheet("组织级")
    head(ws, [("运营组织", 30), ("该组织营业中店铺数", 18), ("默认企业微信群名（待填）", 46), ("备注", 30)])
    rr = 2
    for name, n in sorted(orgs.items(), key=lambda x: -x[1]):
        ws.cell(row=rr, column=1, value=name).font = BODY_FONT
        ws.cell(row=rr, column=2, value=n).font = BODY_FONT
        c = ws.cell(row=rr, column=3, value="")
        c.fill = INPUT_FILL
        c.font = BODY_FONT
        for cc in range(1, 5):
            ws.cell(row=rr, column=cc).border = BORDER
            ws.cell(row=rr, column=cc).alignment = Alignment(vertical="center", wrap_text=True)
        rr += 1
    ws.cell(row=rr, column=1, value="（全局默认兜底群）").font = Font(name="微软雅黑", size=10, bold=True)
    ws.cell(row=rr, column=2, value=len(shops)).font = BODY_FONT
    c = ws.cell(row=rr, column=3, value="")
    c.fill = INPUT_FILL
    c.font = BODY_FONT
    for cc in range(1, 5):
        ws.cell(row=rr, column=cc).border = BORDER

    # —— 店铺级 ——
    ws = wb.create_sheet("店铺级")
    head(ws, [("店铺ID", 14), ("店铺名称", 40), ("运营组织", 24), ("企业微信群名（仅本店用，可空）", 46), ("备注", 26)])
    for i, s in enumerate(shops, start=2):
        vals = [int(s["shopId"]), s.get("shopName") or "", s.get("orgLabel") or "", "", ""]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=i, column=c, value=v)
            cell.font = BODY_FONT
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if c == 1:
                cell.number_format = "0"
            if c == 4:
                cell.fill = INPUT_FILL
    ws.auto_filter.ref = f"A1:E{len(shops)+1}"

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"OK {out}")
    print(f"shops={len(shops)} orgs={len(orgs)}")
    print("orgs: " + ", ".join(f"{k}({v})" for k, v in sorted(orgs.items(), key=lambda x: -x[1])[:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
