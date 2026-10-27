#!/usr/bin/env python3
"""把 docs/metrics_catalog.json 的 `user_rules` 渲染成台账的『你的规则』sheet。

为什么单独一张表
----------------
`global_rules` 是我这边沉淀的**工程规则**（路由、iframe、坑、判据…），读起来是技术笔记；
大同口述的**口径原话**（"顾客分布 > 下单时段"、"数据概览选本周…"）才是验收依据。
两者混在一张表里，时间一长就分不清"哪句是我说的、哪句是监理自己总结的"。

所以：原话单独一张表，**逐字保存、禁改写**，并附上页面实测与时间口径，
让「说的是什么 / 页面上是什么 / 时间怎么选 / 对不对得上」一眼可核。

设计原则
--------
1. **单一权威源**：只维护 `metrics_catalog.json.user_rules`，Excel 是渲染产物（禁手改）。
2. **幂等**：整表重写该 sheet，其它 sheet 不碰。
3. **双份同写**：默认同时写「当月实盘台账」+「空白模板」。
4. **缺位显式**：已收到几条、还差几条，直接铺成灰底待补行，不藏。（`--total` 默认=已收条数，不再铺待补行；要显式预留才传 `--total`。封板与否以 catalog 的 `rules_sealed` 字段为准——00:49 封过板，01:07 又发 R16 已解除，勿按 got==total 猜）

用法
----
    python scripts/sync_user_rules.py                 # 写当月台账 + 模板
    python scripts/sync_user_rules.py --ledger a.xlsx # 只写指定文件
    python scripts/sync_user_rules.py --total 20      # 指定规则总数（默认 20）
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
SHEET = "你的规则"

HEAD = ["规则号", "对应指标", "你给的口径（原话）", "页面实测", "时间口径", "判定"]
WIDTHS = [8, 10, 34, 78, 30, 18]

FONT = "PingFang SC"
HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=11)
BODY_FONT = Font(name=FONT, size=10)
PENDING_FILL = PatternFill("solid", fgColor="F2F2F2")
PENDING_FONT = Font(name=FONT, size=10, color="808080", italic=True)
OK_FILL = PatternFill("solid", fgColor="E2F0D9")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def default_ledgers(include_template: bool) -> list[pathlib.Path]:
    allx = list(DOCS.glob("全店铺运营指标商家反馈台账_*.xlsx"))
    live = [p for p in allx if "模板" not in p.name and re.search(r"_\d{4}-\d{2}\.xlsx$", p.name)]
    tpl = [p for p in allx if "模板" in p.name]
    out = []
    if live:
        out.append(max(live, key=lambda p: p.stat().st_mtime))
    if include_template and tpl:
        out.append(tpl[0])
    return out


def write_sheet(path: pathlib.Path, rules: list[dict], total: int) -> tuple[int, int]:
    wb = load_workbook(path)
    if SHEET in wb.sheetnames:
        idx = wb.sheetnames.index(SHEET)
        del wb[SHEET]
    else:
        # 紧跟在『规则清单』之后，原话→工程说明是自然的阅读顺序
        idx = wb.sheetnames.index("规则清单") + 1 if "规则清单" in wb.sheetnames else 1
    ws = wb.create_sheet(SHEET, idx)

    for col, (title, width) in enumerate(zip(HEAD, WIDTHS), start=1):
        c = ws.cell(row=1, column=col, value=title)
        c.font = HEAD_FONT
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 26

    got = len(rules)
    for i in range(total):
        r = i + 2
        if i < got:
            m = rules[i]
            vals = [m.get("id"), m.get("metric"), m.get("raw"), m.get("page"),
                    m.get("time"), m.get("verdict")]
            for col, v in enumerate(vals, start=1):
                c = ws.cell(row=r, column=col, value=v)
                c.font = BODY_FONT
                c.border = BORDER
                c.alignment = Alignment(
                    vertical="top",
                    wrap_text=(col in (3, 4, 5)),
                    horizontal="center" if col in (1, 2, 6) else "left",
                )
                if col == 6:
                    c.fill = OK_FILL
            ws.row_dimensions[r].height = max(32, min(140, 15 * (len(str(m.get("page") or "")) // 40 + 1)))
        else:
            vals = [f"R{i + 1:02d}", "", "（待大同补发）", "", "", "待补"]
            for col, v in enumerate(vals, start=1):
                c = ws.cell(row=r, column=col, value=v)
                c.font = PENDING_FONT
                c.fill = PENDING_FILL
                c.border = BORDER
                c.alignment = Alignment(vertical="center",
                                        horizontal="center" if col in (1, 2, 6) else "left")
            ws.row_dimensions[r].height = 22

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:F{total + 1}"
    wb.save(path)
    return got, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", type=pathlib.Path, action="append", default=None)
    ap.add_argument("--no-template", action="store_true")
    ap.add_argument("--catalog", type=pathlib.Path, default=CATALOG)
    ap.add_argument("--total", type=int, default=None,
                    help="规则总条数；默认=已收条数（不铺灰底待补行）。2026-10-22 00:49 大同拍板封板 R15，不再补发")
    a = ap.parse_args()

    cat = json.loads(a.catalog.read_text(encoding="utf-8"))
    rules = cat.get("user_rules") or []
    if not rules:
        raise SystemExit("catalog 里没有 user_rules，拒绝写空表")

    targets = a.ledger or default_ledgers(include_template=not a.no_template)
    if not targets:
        raise SystemExit("未找到目标台账文件")

    total = a.total if a.total else len(rules)
    sealed = bool(cat.get("rules_sealed"))
    for p in targets:
        got, total = write_sheet(p, rules, total)
        if sealed:
            print(f"OK  {p.name}  → 『{SHEET}』已封板 {got} 条（大同拍板不再补发）")
        elif got >= total:
            print(f"OK  {p.name}  → 『{SHEET}』已收 {got} 条（=total，但未封板：可能有参数待定项）")
        else:
            print(f"OK  {p.name}  → 『{SHEET}』已收 {got}/{total} 条（其余灰底待补）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
