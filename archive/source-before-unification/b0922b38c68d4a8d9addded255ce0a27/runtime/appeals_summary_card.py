#!/usr/bin/env python3
"""申诉结果「汇总台账」卡片渲染器（两条申诉流共用）。

用途：淘宝闪购差评申诉 / 美团外卖差评申诉——Excel 结果表发群之后，
再补发一张汇总台账截图（大同 2026-10-22 要求）。

设计约束：
  * 只做渲染，不发送。发送统一走 workflow_bridge（防重台账 + 回执）。
  * 数字全部来自现场工件（records 事实源 + 汇总 xlsx 的平台统计行 + 运行日志），
    不臆造、不补齐；取不到就写「未取得」，绝不编。
  * 输出 PNG（2x 视网膜），白底深字，可直接进微信群。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT = Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back')
RECORDS = PROJECT / 'records'
OUTPUTS = PROJECT / 'outputs'
RUNS = PROJECT / 'runtime' / 'state' / 'runs'

FONT_CANDIDATES = [
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/System/Library/Fonts/Supplemental/Songti.ttc',
]

FLOW_META = {
    'taobao': {
        'label': '淘宝闪购差评申诉',
        'records_dir': RECORDS / 'taobao-flash-sale-negative-review-appeals',
        'outputs_glob': 'taobao-flash-sale-negative-review-appeals-*',
        'report_name': '淘宝闪购差评申诉汇总-{date}.xlsx',
        'runs_glob': 'taobao-shangou-negative-review-appeals/*',
        'extra_logs': ['taobao-flash-sale-negative-review-appeals/*'],
    },
    'meituan': {
        'label': '美团外卖差评申诉',
        'records_dir': RECORDS / 'meituan-waimai-negative-review-appeals',
        'outputs_glob': 'meituan-waimai-negative-review-appeals-*',
        'report_name': '美团外卖差评申诉汇总-{date}.xlsx',
        'runs_glob': 'meituan-waimai-negative-review-appeals*/*',
        'extra_logs': ['meituan-waimai-negative-review-appeals*/*'],
    },
}

# ---------- 数据采集 ----------

def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def load_record_counts(flow: str, business_date: str) -> dict:
    meta = FLOW_META[flow]
    day_dir = meta['records_dir'] / business_date
    counts = {'total': 0, 'verified': 0, 'unknown': 0, 'other': 0}
    if not day_dir.is_dir():
        return counts
    for path in sorted(day_dir.glob('*.md')):
        text = path.read_text(encoding='utf-8', errors='ignore')
        match = re.search(r'^- 记录状态：(\S+)', text, re.M)
        status = match.group(1) if match else 'no-status'
        counts['total'] += 1
        if status == 'verified_submitted':
            counts['verified'] += 1
        elif status == 'unknown':
            counts['unknown'] += 1
        else:
            counts['other'] += 1
    return counts


def load_platform_summary(flow: str, business_date: str, run_key: str) -> dict | None:
    """从汇总 xlsx 的平台统计行取数（第 5 行：全部/申诉成功/申诉失败/申诉中/未申诉）。"""
    meta = FLOW_META[flow]
    name = meta['report_name'].format(date=business_date)
    candidates = [OUTPUTS / f'{meta["outputs_glob"].rstrip("*")}{run_key}' / name]
    candidates += [Path(p) for p in glob.glob(str(OUTPUTS / '*' / name))]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            cells = _xlsx_row_cells(path, row_number=5)
        except Exception:
            continue
        values = [v for v in cells.values() if str(v).strip() != '']
        if len(values) >= 10:
            # A=全部 B=数值 C=申诉成功 D=值 E=申诉失败 F=值 G=申诉中 H=值 I=未申诉 J=值
            ordered = [cells.get(col, '') for col in ('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J')]
            def num(idx):
                try:
                    return int(float(ordered[idx]))
                except (TypeError, ValueError):
                    return None
            return {
                'total': num(1), 'success': num(3), 'failed': num(5),
                'appealing': num(7), 'unappealed': num(9),
                'source': path.name,
            }
    return None


def _xlsx_row_cells(path: Path, row_number: int) -> dict:
    import zipfile
    with zipfile.ZipFile(path) as zipped:
        sheet = zipped.read('xl/worksheets/sheet1.xml').decode('utf-8', 'ignore')
    prefix = 'x:' if '<x:row' in sheet else ''
    pattern = rf'<{prefix}row[^>]*r="{row_number}"[^>]*>(.*?)</{prefix}row>'
    match = re.search(pattern, sheet, re.S)
    if not match:
        return {}
    body = match.group(1)
    cells = {}
    cell_pattern = rf'<{prefix}c r="([A-Z]+)\d+"([^>]*)>(.*?)</{prefix}c>'
    for cm in re.finditer(cell_pattern, body, re.S):
        col, attrs, inner = cm.group(1), cm.group(2), cm.group(3)
        inline = ''.join(re.findall(rf'<{prefix}t[^>]*>(.*?)</{prefix}t>', inner, re.S))
        if inline:
            cells[col] = inline
        else:
            vm = re.search(rf'<{prefix}v>(.*?)</{prefix}v>', inner, re.S)
            cells[col] = vm.group(1) if vm else ''
    return cells


def load_elsewhere_handled(flow: str, business_date: str) -> int:
    """当日「处理前已被其他渠道申诉」条数：扫运行日志里的 candidate-no-longer-unappealed:xxx。"""
    meta = FLOW_META[flow]
    keys = set()
    patterns = [str(RUNS / meta['runs_glob'])] + [str(RUNS / p) for p in meta['extra_logs']]
    seen = set()
    for pattern in patterns:
        for run_dir in glob.glob(pattern):
            if run_dir in seen or not os.path.isdir(run_dir):
                continue
            seen.add(run_dir)
            # 只看当日运行目录（目录名带 20261022 形式）
            if re.fullmatch(r'\d{8}-\d{6}', os.path.basename(run_dir)) is None:
                continue
            for log in glob.glob(os.path.join(run_dir, 'step1.log')):
                text = Path(log).read_text(encoding='utf-8', errors='ignore')
                if business_date not in text:
                    continue
                for key in re.findall(r'candidate-no-longer-unappealed:([0-9a-f]{6,})', text):
                    keys.add(key)
    return len(keys)


# ---------- 版面 ----------

SCALE = 2
WIDTH = 620
PAD = 22
ROW_H = 40
HEADER_H = 38
TITLE_SIZE = 22
SUB_SIZE = 12
CELL_SIZE = 15
FOOT_SIZE = 11

COLOR_TITLE = (17, 24, 39)
COLOR_SUB = (110, 118, 130)
COLOR_HEADER_BG = (47, 85, 151)
COLOR_HEADER_TX = (255, 255, 255)
COLOR_LINE = (223, 227, 234)
COLOR_ZEBRA = (246, 248, 251)
COLOR_TEXT = (31, 41, 55)
COLOR_ACCENT = (12, 106, 78)


def render(title: str, subtitle: str, rows: list[tuple[str, str]], footer: str,
           highlight: str | None = None) -> Image.Image:
    height = PAD + 40 + 26 + HEADER_H + ROW_H * len(rows) + 34 + PAD
    image = Image.new('RGB', (WIDTH * SCALE, height * SCALE), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    s = SCALE

    def text(xy, content, font, fill, anchor=None):
        draw.text((xy[0] * s, xy[1] * s), content, font=font, fill=fill, anchor=anchor)

    f_title = _font(TITLE_SIZE * s)
    f_sub = _font(SUB_SIZE * s)
    f_cell = _font(CELL_SIZE * s)
    f_head = _font(CELL_SIZE * s)
    f_foot = _font(FOOT_SIZE * s)

    y = PAD
    text((PAD, y), title, f_title, COLOR_TITLE)
    y += 40
    text((PAD, y), subtitle, f_sub, COLOR_SUB)
    y += 26

    # 表头
    draw.rectangle([PAD * s, y * s, (WIDTH - PAD) * s, (y + HEADER_H) * s], fill=COLOR_HEADER_BG)
    text((PAD + 12, y + HEADER_H / 2), '指标', f_head, COLOR_HEADER_TX, anchor='lm')
    text((WIDTH - PAD - 12, y + HEADER_H / 2), '数值', f_head, COLOR_HEADER_TX, anchor='rm')
    y += HEADER_H

    for index, (label, value) in enumerate(rows):
        if index % 2 == 1:
            draw.rectangle([PAD * s, y * s, (WIDTH - PAD) * s, (y + ROW_H) * s], fill=COLOR_ZEBRA)
        draw.line([PAD * s, (y + ROW_H) * s, (WIDTH - PAD) * s, (y + ROW_H) * s], fill=COLOR_LINE, width=s)
        text((PAD + 12, y + ROW_H / 2), label, f_cell, COLOR_TEXT, anchor='lm')
        is_highlight = highlight is not None and label == highlight
        text((WIDTH - PAD - 12, y + ROW_H / 2), value, f_cell,
             COLOR_ACCENT if is_highlight else COLOR_TEXT, anchor='rm')
        y += ROW_H

    y += 12
    text((PAD, y), footer, f_foot, COLOR_SUB)
    # 外框
    draw.rectangle([PAD * s, (PAD + 92) * s, (WIDTH - PAD) * s, y * s], outline=COLOR_LINE, width=s)
    return image


# ---------- 组装 ----------

def build_rows(flow: str, business_date: str, run_key: str) -> tuple[list[tuple[str, str]], str]:
    counts = load_record_counts(flow, business_date)
    platform = load_platform_summary(flow, business_date, run_key)
    elsewhere = load_elsewhere_handled(flow, business_date)

    total = counts['total'] + elsewhere
    rows: list[tuple[str, str]] = []
    rows.append(('今日待申诉（合计）', f'{total} 条'))
    rows.append(('已提交申诉 · 平台回读确认', f"{counts['verified']} 条"))
    rows.append(('已提交 · 待平台受理确认', f"{counts['unknown']} 条"))
    rows.append(('处理前已被其他渠道申诉', f'{elsewhere} 条'))
    if counts['other']:
        rows.append(('其他状态待核', f"{counts['other']} 条"))
    rows.append(('当前未申诉（开启自动申诉）', f"{platform['unappealed']} 条" if platform and platform.get('unappealed') is not None else '未取得'))
    if platform:
        rows.append(('平台侧统计 · 全部评价', f"{platform['total']} 条" if platform.get('total') is not None else '未取得'))
        rows.append(('　申诉成功 / 失败 / 申诉中',
                     f"{platform['success']} / {platform['failed']} / {platform['appealing']}"))
    note = '' if platform else '（平台统计行未取得）'
    return rows, note


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='申诉汇总台账卡片渲染')
    parser.add_argument('--flow', required=True, choices=sorted(FLOW_META))
    parser.add_argument('--business-date', required=True, help='业务日期 YYYY-MM-DD')
    parser.add_argument('--run-key', required=True, help='运行日 YYYYMMDD')
    parser.add_argument('--output', required=True, help='输出 PNG 路径')
    parser.add_argument('--title-date', help='标题里的日期（默认运行日 YYYY-MM-DD）')
    args = parser.parse_args(argv)

    meta = FLOW_META[args.flow]
    rows, note = build_rows(args.flow, args.business_date, args.run_key)
    title_date = args.title_date or f'{args.run_key[:4]}-{args.run_key[4:6]}-{args.run_key[6:8]}'
    title = f"{meta['label']} · {title_date} 处理结果台账"
    subtitle = f"业务日期 {args.business_date}｜数据来源：records 事实源 + 平台回读{note}"
    footer = '生成时间 ' + datetime.now().strftime('%Y-%m-%d %H:%M') + '　｜　明细可查当日申诉汇总表'

    image = render(title, subtitle, rows, footer, highlight='今日待申诉（合计）')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format='PNG', optimize=True)
    print(json.dumps({'ok': True, 'flow': args.flow, 'businessDate': args.business_date,
                      'rows': rows, 'output': str(output),
                      'bytes': output.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
