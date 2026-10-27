#!/usr/bin/env python3
"""把 docs/metrics_catalog.json 的 global_rules 同步进台账的『规则清单』sheet。

为什么要有这个 sheet
--------------------
20 项指标的页面口径规则（哪条路由、必须单店视角、时间控件怎么切、切店怎么搜…）
原先只躺在 JSON 里，Excel 上完全看不见。大同要看「规则模版」时无从下手，
一线的判断依据也散落在 REQUIREMENTS 的各个 §3.x。本脚本把它渲染成一张可读表。

设计原则
--------
1. **单一权威源**：规则只维护 `metrics_catalog.json.global_rules`，Excel 是渲染产物。
2. **幂等**：每次都整表重写『规则清单』，其它 sheet 一律不碰。
3. **双份同写**：默认同时写「当月实盘台账」+「空白模板」，避免两份漂移（教训：同判据两份拷贝必同步）。
4. **零假数据**：等级从规则文本开头的 ★ 直接解析，不做主观推断；没有 ★ 就是「普通」。

用法
----
    python scripts/sync_global_rules.py                      # 写当月台账 + 模板
    python scripts/sync_global_rules.py --ledger a.xlsx      # 只写指定文件
    python scripts/sync_global_rules.py --no-template        # 只写当月台账
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = pathlib.Path(__file__).resolve().parent
WF = HERE.parent
DOCS = WF / "docs"
CATALOG = DOCS / "metrics_catalog.json"
SHEET = "规则清单"

HEAD = ["序号", "等级", "规则内容", "首次记录", "命中页/模块"]
WIDTHS = [6, 8, 96, 12, 22]

FONT = "PingFang SC"
HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=11)
BODY_FONT = Font(name=FONT, size=10)
LV_FILL = {
    3: PatternFill("solid", fgColor="FCE4E4"),   # ★★★ 最高
    2: PatternFill("solid", fgColor="FFF2CC"),   # ★★
    1: PatternFill("solid", fgColor="E2F0D9"),   # ★
}
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def default_ledgers(include_template: bool) -> list[pathlib.Path]:
    """当月实盘台账（最新一份）+ 可选模板。"""
    allx = list(DOCS.glob("全店铺运营指标商家反馈台账_*.xlsx"))
    live = [p for p in allx if "模板" not in p.name and re.search(r"_\d{4}-\d{2}\.xlsx$", p.name)]
    tpl = [p for p in allx if "模板" in p.name]
    out = []
    if live:
        out.append(max(live, key=lambda p: p.stat().st_mtime))
    if include_template and tpl:
        out.append(tpl[0])
    return out


def parse_level(text: str) -> int:
    m = re.match(r"^(★+)", text or "")
    return len(m.group(1)) if m else 0


def parse_date(text: str) -> str:
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", text or "")
    return m.group(1) if m else ""


def parse_scope(text: str) -> str:
    """只做「提到哪个页面」的原文摘取，不做推断。"""
    pats = [
        (r"customerStats", "顾客分析"),
        (r"comments", "顾客评价"),
        (r"stats__center|经营分析", "经营分析"),
        (r"切换器|运营组织|店铺池", "店铺池/切店"),
        (r"台账", "台账"),
    ]
    hit = [name for pat, name in pats if re.search(pat, text or "", re.I)]
    return "、".join(dict.fromkeys(hit))


def write_sheet(path: pathlib.Path, rules: list[str]) -> int:
    wb = load_workbook(path)
    if SHEET in wb.sheetnames:
        del wb[SHEET]
    # 放在「说明」之后：规则是阅读性内容，不该压在最后一张表
    ws = wb.create_sheet(SHEET, 1 if len(wb.sheetnames) > 0 else 0)

    for col, (title, width) in enumerate(zip(HEAD, WIDTHS), start=1):
        c = ws.cell(row=1, column=col, value=title)
        c.font = HEAD_FONT
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 24

    for i, raw in enumerate(rules, start=1):
        text = str(raw).strip()
        lv = parse_level(text)
        body = re.sub(r"^★+\s*", "", text)
        vals = [i, "★" * lv if lv else "—", body, parse_date(text), parse_scope(body)]
        vals = ["" if v is None else v for v in vals]
        r = i + 1
        for col, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=col, value=v)
            c.font = BODY_FONT
            c.border = BORDER
            c.alignment = Alignment(
                vertical="top",
                wrap_text=(col == 3),
                horizontal="center" if col in (1, 2, 4) else "left",
            )
            if col == 2 and lv in LV_FILL:
                c.fill = LV_FILL[lv]
        # 行高按字数粗估，避免 96 宽一行字压在一起
        ws.row_dimensions[r].height = max(30, min(150, 15 * (len(body) // 46 + 1)))

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:E{len(rules) + 1}"
    wb.save(path)
    return len(rules)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", type=pathlib.Path, action="append", default=None)
    ap.add_argument("--no-template", action="store_true")
    ap.add_argument("--catalog", type=pathlib.Path, default=CATALOG)
    a = ap.parse_args()

    cat = json.loads(a.catalog.read_text(encoding="utf-8"))
    rules = cat.get("global_rules") or []
    if not rules:
        raise SystemExit("catalog 里没有 global_rules，拒绝写空表")

    targets = a.ledger or default_ledgers(include_template=not a.no_template)
    if not targets:
        raise SystemExit("未找到目标台账文件")

    lv3 = sum(1 for r in rules if parse_level(str(r)) == 3)
    lv2 = sum(1 for r in rules if parse_level(str(r)) == 2)
    for p in targets:
        n = write_sheet(p, rules)
        print(f"OK  {p.name}  → 『{SHEET}』{n} 条")
    print(f"等级分布：★★★ {lv3} 条　★★ {lv2} 条　★/无 {len(rules) - lv3 - lv2} 条")
    print(f"共 {len(targets)} 份文件已同步（当月台账 + 模板同时写，防止两份漂移）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
