#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「店铺运营指标 20 项轮转反馈流」台账 Excel 模板（只建结构，不含任何假数据）。

设计口径见 ../REQUIREMENTS.md：
  - 店铺池       ：品牌商运营组织树（营业中）全量店铺，7 列（含企业微信群名称路由键）
  - 指标字典     ：20 项指标的定义表（指标名/页面/形态/截图口径），大同补发后逐行填
  - 指标进度     ：宽表，每店 20 个指标一列，格子里写「反馈日期」，空=未反馈
  - 当月反馈记录 ：长表，逐条流水，审计主表
  - 说明         ：口径、流程、枚举、填法

用法：
  env -u PYTHONPATH /Users/ddt/.workbuddy/binaries/python/envs/default/bin/python \
    scripts/build_ledger_template.py [--out PATH] [--month 2026-10]
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HEADER_FILL = PatternFill("solid", fgColor="2F5597")
HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=10)
NOTE_FONT = Font(name="微软雅黑", size=10, color="444441")
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True, color="1F3864")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
GREEN_FILL = PatternFill("solid", fgColor="C6EFCE")
GREEN_FONT = Font(name="微软雅黑", size=10, color="0F6E56")

STORE_COLS = [
    ("店铺ID", 14),
    ("店铺名称", 34),
    ("营业状态", 10),
    ("运营组织", 26),
    ("企业微信群名称", 30),
    ("采集日期", 12),
    ("备注", 26),
]

METRIC_COLS = [
    ("序号", 8),
    ("指标名称", 26),
    ("所属页面／地址", 40),
    ("指标形态", 14),
    ("截图口径", 14),
    ("时间范围", 16),
    ("采集要点", 34),
    ("状态", 12),
]

RECORD_COLS = [
    ("日期", 12),
    ("轮次", 8),
    ("店铺id", 14),
    ("店铺名称", 30),
    ("指标序号", 9),
    ("指标名称", 24),
    ("企业微信群", 26),
    ("消息结果", 16),
    ("回执／消息ID", 24),
    ("截图路径", 44),
    ("备注", 26),
]

RESULT_ENUM = "verified,unknown,blocked,skipped-already,no-data"


def style_header(ws, cols, height=28):
    for idx, (name, width) in enumerate(cols, start=1):
        c = ws.cell(row=1, column=idx, value=name)
        c.fill, c.font, c.border = HEADER_FILL, HEADER_FONT, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.row_dimensions[1].height = height


def add_text_sheet(wb, month: str):
    ws = wb.create_sheet("说明", 0)
    ws.sheet_properties.tabColor = "888780"
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 118

    blocks = [
        ("title", "店铺运营指标 · 20 项轮转反馈流 · 台账（模板）"),
        ("sub", f"账期：{month}　｜　工作流：daily-store-metrics-rotation-to-wechat　｜　店铺池数据源：品牌商系统 9230 · 运营组织树（营业中店铺）"),
        ("h", "一、这张表干什么"),
        ("p", "把「品牌商系统里运营中的店铺」逐店、逐指标截图，发到该店自己的企业微信群；20 天轮完 20 个指标。"),
        ("p", "本台账负责回答三个问题：发过没有、哪天发的、哪家还没发。"),
        ("p", "数据源口径（2026-10-20 大同定案）：店铺池只认品牌商 9230「运营组织」下拉树里状态为「营业中」的店铺，"),
        ("p", "字段取 店铺ID + 店铺名称。不再并入旧系统（wmPoiId）名单——两套 ID 不互通、店名口径不同，混用只会制造缺口，"),
        ("p", "而切店/取数本来就只在品牌商系统里发生，用旧系统名单反而要额外维护一张映射表。"),
        ("h", "二、七张表的关系（顺序即本工作簿的 sheet 顺序）"),
        ("p", "① 规则清单——工程侧口径规则的唯一清单（★★★=最高优先级）。由 `scripts/sync_global_rules.py` 从 metrics_catalog.json 渲染，"),
        ("p", "   改规则只改 JSON 后重跑脚本，**不要手改这张表**，否则下次同步会被覆盖。"),
        ("p", "② 你的规则——需求方口述口径的原话存档（R01…R20，逐字不改写），附页面实测与时间口径，用来核对「说的」与「做的」是否一致。"),
        ("p", "   由 `scripts/sync_user_rules.py` 渲染；灰底行=尚未收到的规则。"),
        ("p", "③ 店铺池——店铺清单快照（每周刷新一次；店铺ID 为主键）。「企业微信群名称」是发送路由键，缺这一列就发不出去。"),
        ("p", "④ 指标字典——20 项指标的定义表（M01…M20）。改指标只改 JSON，由 `sync_metrics_catalog.py` 渲染，宽表列名不动。"),
        ("p", "⑤ 指标进度——宽表：每店一行、每个指标一列，格子里填「反馈日期」（如 10-21），空 = 还没反馈。"),
        ("p", "⑥ 当月反馈记录——长表流水：发一条写一行，是审计主表；争议时以它为准。"),
        ("h", "三、每天的作业顺序"),
        ("p", "1) 读店铺池 → 2) 取当天指标（D1=M01 … D20=M20 固定顺序）→ 3) 逐店截该指标图 → 4) 发该店企业微信群 →"),
        ("p", "5) 成功即回写：指标进度对应格子填日期 + 当月反馈记录加一行 → 6) 未成功的进次日补发队列，不打乱当天新指标。"),
        ("h", "四、消息结果枚举（唯一判据，别自创叫法）"),
        ("p", "verified = 已送达且回读核验通过（可结束）；unknown = 可能已发出但无回执（禁止重发，只做只读对账）；"),
        ("p", "blocked = 确定没发出去（可重试）；skipped-already = 幂等跳过（此前已发过）；no-data = 该店该指标无数据（不发空图）。"),
        ("h", "五、幂等与重发红线"),
        ("p", "幂等键 = 店铺id + 指标序号 + 月份。同一键发过就不再发：重跑一次 = 一次对外副作用，别把「补跑」当只读操作。"),
        ("p", "unknown 状态绝不重发；blocked 才可以安全重试；已 verified 的格子里有日期就不再动它。"),
        ("h", "六、填写规则"),
        ("p", "· 指标进度：不要手填文字，只填「月-日」（如 10-21）；整列空白 = 该指标还没开始。"),
        ("p", "· 已完成数列（X 列）= 公式 COUNTA(D:W)，由装载脚本按行写入，手填会破坏统计。"),
        ("p", "· 店铺池只留 店铺ID／名称／营业状态／运营组织／群名／采集日期，不含电话等隐私字段。"),
        ("p", "· 店铺池每周覆盖一次；历史快照另存 店铺池_YYYYMMDD.xlsx，不在这里留旧行。"),
        ("p", "· 本文件是**结构模板**：店铺池 / 指标进度 / 当月反馈记录 只到表头、不含任何店铺数据（不放假数据）。"),
        ("p", "  实盘由 `collect_shop_pool_brand.mjs`（采集 863 家营业中）→ `store_pool_to_ledger.py`（写台账）生成，两份结构完全一致。"),
        ("h", "七、覆盖率必须显式声明"),
        ("p", "每日报告固定写：店铺池 N 家（另有 M 家授权失败未纳入）/ 当日应发 N / 实发 X / 待补发 Y。缺口不静默。"),
    ]

    row = 1
    for kind, text in blocks:
        cell = ws.cell(row=row, column=2, value=text)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        if kind == "title":
            cell.font = TITLE_FONT
            ws.row_dimensions[row].height = 30
        elif kind == "sub":
            cell.font = NOTE_FONT
            ws.row_dimensions[row].height = 22
        elif kind == "h":
            cell.font = Font(name="微软雅黑", size=11, bold=True, color="2F5597")
            ws.row_dimensions[row].height = 24
        else:
            cell.font = BODY_FONT
            ws.row_dimensions[row].height = 20
        row += 1
    return ws


def build(out: pathlib.Path, month: str) -> pathlib.Path:
    wb = Workbook()
    wb.remove(wb.active)

    add_text_sheet(wb, month)

    # ① 店铺池
    ws = wb.create_sheet("店铺池")
    ws.sheet_properties.tabColor = "185FA5"
    style_header(ws, STORE_COLS)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(STORE_COLS))}1"

    # ② 指标字典
    ws = wb.create_sheet("指标字典")
    ws.sheet_properties.tabColor = "534AB7"
    style_header(ws, METRIC_COLS)
    ws.freeze_panes = "B2"
    for i in range(1, 21):
        r = i + 1
        ws.cell(row=r, column=1, value=f"M{i:02d}").font = BODY_FONT
        ws.cell(row=r, column=2, value="（待大同补发）").font = NOTE_FONT
        ws.cell(row=r, column=8, value="待补").font = NOTE_FONT
        for c in range(1, len(METRIC_COLS) + 1):
            ws.cell(row=r, column=c).border = BORDER
            if ws.cell(row=r, column=c).alignment.horizontal is None:
                ws.cell(row=r, column=c).alignment = Alignment(vertical="center", wrap_text=True)

    # ③ 指标进度（宽表）
    ws = wb.create_sheet("指标进度")
    ws.sheet_properties.tabColor = "0F6E56"
    cols = [("店铺id", 14), ("店铺名称", 30), ("企业微信群名称", 26)]
    cols += [(f"M{i:02d}", 7) for i in range(1, 21)]
    cols += [("已完成数", 10)]
    style_header(ws, cols, height=34)
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"

    # ④ 当月反馈记录（长表）
    ws = wb.create_sheet("当月反馈记录")
    ws.sheet_properties.tabColor = "BA7517"
    style_header(ws, RECORD_COLS)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(RECORD_COLS))}1"

    # —— 数据验证 ——
    dv_state = DataValidation(type="list", formula1='"营业中,休息中,已下线,暂停营业,已打烊"', allow_blank=True)
    dv_result = DataValidation(type="list", formula1=f'"{RESULT_ENUM}"', allow_blank=True)
    dv_form = DataValidation(type="list", formula1='"独立页面,页内卡片"', allow_blank=True)
    dv_shot = DataValidation(type="list", formula1='"整页,卡片,长图"', allow_blank=True)
    for dv in (dv_state, dv_result, dv_form, dv_shot):
        dv.showErrorMessage = True
    pool = wb["店铺池"]
    pool.add_data_validation(dv_state)
    dv_state.add("C2:C3000")
    rec = wb["当月反馈记录"]
    rec.column_dimensions["A"].number_format = "yyyy-mm-dd"
    rec.add_data_validation(dv_result)
    dv_result.add("H2:H20000")
    dic = wb["指标字典"]
    dic.add_data_validation(dv_form)
    dv_form.add("D2:D21")
    dic.add_data_validation(dv_shot)
    dv_shot.add("E2:E21")

    # —— 进度宽表条件格式：已填日期 → 绿底 ——
    prog = wb["指标进度"]
    prog.conditional_formatting.add(
        "D2:W1000",
        FormulaRule(formula=['LEN(D2)>0'], fill=GREEN_FILL, font=GREEN_FONT),
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def main(argv=None):
    here = pathlib.Path(__file__).resolve().parent
    default_out = here.parent / "docs" / "全店铺运营指标商家反馈台账_模板.xlsx"
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(default_out))
    ap.add_argument("--month", default="2026-10")
    a = ap.parse_args(argv)

    out = build(pathlib.Path(a.out), a.month)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()[:16]
    print(f"OK {out}")
    print(f"size={out.stat().st_size}B sha256={digest} month={a.month}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
