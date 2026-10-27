#!/usr/bin/env python3
"""昨日差评分析「整表长图」渲染器（daily-negative-reviews 流截图阶段）。

2026-10-22 大同要求：Excel 发群之后，再补一张整表长截图进同一运营群。
样式对齐大同手工样板（feibing_zhensi/差评分析数据_2026-10-21 参考文件与参考长图）：
  * 表头浅粉 #E6B9B8（= Office 主题 accent2 C0504D tint 0.6），加粗深字；
  * 序号列浅青 #DBEEF4（= accent5 4BACC6 tint 0.8），其余数据行白底；
  * 细边框 #C7D2D6，微软雅黑系字体（Mac 侧 Hiragino Sans GB 回退）；
  * 100+ 行同样整表渲染（行高按换行动态计算，超长截断加省略号）。
设计约束（与 appeals_summary_card.py 同哲学）：
  * 只渲染，不发送；发送统一走 workflow_bridge（防重台账 + 回执）。
  * 数据只来自 final-data.json 现场工件，不臆造不补齐。
  * 输出 PNG（2x 视网膜），白底深字，可直接进微信群。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

INTERNAL_INVOCATION = 'daily-negative-reviews-workflow-executor-v1'

FONT_CANDIDATES = [
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/System/Library/Fonts/Supplemental/Songti.ttc',
]

# 参考样板取色（Office 经典主题 accent2/accent5 调亮后）
HEADER_FILL = '#E6B9B8'   # accent2 C0504D tint 0.6
INDEX_FILL = '#DBEEF4'    # accent5 4BACC6 tint 0.8
BORDER_COLOR = '#C7D2D6'
TEXT_COLOR = '#262626'
HEADER_TEXT = '#3A2424'

SCALE = 1
# 列宽（1x 基准像素，总宽 1200）：序号/店铺名称/总分/评价日期/店铺类型/差评内容/评论订单详情
COLUMNS = [
    ('序号', 46, 2, 'center'),
    ('店铺名称', 190, 2, 'left'),
    ('总分', 46, 2, 'center'),
    ('评价日期', 118, 2, 'center'),
    ('店铺类型', 96, 2, 'center'),
    ('差评内容', 404, 3, 'left'),
    ('评论订单详情', 300, 3, 'left'),
]
PAD_X = 8
PAD_Y = 6
HEADER_H = 52
ROW_MIN_H = 42
LINE_H = 27
HEADER_FONT_SIZE = 21
BODY_FONT_SIZE = 19


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _display_width(text: str) -> float:
    return sum(1.0 if ord(ch) > 255 else 0.55 for ch in text)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list:
    """按像素宽换行（CJK 逐字断行），超 max_lines 截断加省略号。"""
    lines: list = []
    for hard in str(text or '').split('\n'):
        current = ''
        for ch in hard:
            if font.getlength(current + ch) > max_width and current:
                lines.append(current)
                current = ch
            else:
                current += ch
        lines.append(current)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = kept[-1][:-1] + '…' if kept[-1] else '…'
        return kept
    return lines


def _row_lines(values: list, fonts: dict, widths: list) -> list:
    result = []
    for index, value in enumerate(values):
        _, _, max_lines, _ = COLUMNS[index]
        result.append(_wrap(value, fonts['body'], widths[index] - 2 * PAD_X, max_lines))
    return result


def render(rows: list, business_date: str, output: Path) -> dict:
    fonts = {'header': _font(HEADER_FONT_SIZE * SCALE, bold=True), 'body': _font(BODY_FONT_SIZE * SCALE)}
    widths = [w * SCALE for _, w, _, _ in COLUMNS]
    total_w = sum(widths)
    line_h = LINE_H * SCALE
    header_h = HEADER_H * SCALE

    # 预排版：算每行行数 → 行高
    table = []
    for index, row in enumerate(rows, start=1):
        values = [
            str(index),
            str(row.get('店铺名称') or ''),
            str(row.get('总分') if row.get('总分') is not None else ''),
            str(row.get('评价日期') or '')[:10],
            str(row.get('店铺类型') or ''),
            str(row.get('差评内容') or ''),
            str(row.get('评论订单详情') or ''),
        ]
        lines = _row_lines(values, fonts, widths)
        max_lines = max(len(group) for group in lines)
        row_h = max(ROW_MIN_H * SCALE, max_lines * line_h + 2 * PAD_Y * SCALE)
        table.append((values, lines, row_h))
    total_h = header_h + sum(row_h for _, _, row_h in table)

    image = Image.new('RGB', (total_w, total_h), '#FFFFFF')
    draw = ImageDraw.Draw(image)

    # 表头
    draw.rectangle([0, 0, total_w, header_h], fill=HEADER_FILL)
    x = 0
    for index, (title, _, _, align) in enumerate(COLUMNS):
        w = widths[index]
        text_w = fonts['header'].getlength(title)
        tx = x + (w - text_w) / 2 if align == 'center' else x + PAD_X * SCALE
        draw.text((tx, (header_h - HEADER_FONT_SIZE * SCALE * 1.25) / 2), title, font=fonts['header'], fill=HEADER_TEXT)
        x += w

    # 数据行
    y = header_h
    for values, lines, row_h in table:
        # 序号列底色
        draw.rectangle([0, y, widths[0], y + row_h], fill=INDEX_FILL)
        x = 0
        for index, group in enumerate(lines):
            w = widths[index]
            _, _, _, align = COLUMNS[index]
            text = '\n'.join(group)
            if align == 'center':
                block_w = max(fonts['body'].getlength(line) for line in group) if group else 0
                tx = x + (w - block_w) / 2
            else:
                tx = x + PAD_X * SCALE
            draw.multiline_text((tx, y + PAD_Y * SCALE), text, font=fonts['body'],
                                fill=TEXT_COLOR, spacing=4 * SCALE)
            x += w
        y += row_h

    # 边框（外框 + 全内网格）
    y = header_h
    draw.rectangle([0, 0, total_w - 1, total_h - 1], outline=BORDER_COLOR, width=1 * SCALE)
    x = 0
    for w in widths[:-1]:
        x += w
        draw.line([(x, 0), (x, total_h)], fill=BORDER_COLOR, width=1 * SCALE)
    for _, _, row_h in table:
        draw.line([(0, y), (total_w, y)], fill=BORDER_COLOR, width=1 * SCALE)
        y += row_h

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in ('.jpg', '.jpeg'):
        image.save(output, format='JPEG', quality=85, optimize=True, progressive=True)
    else:
        image.save(output, optimize=True)
    data = output.read_bytes()
    return {
        'ok': True,
        'businessDate': business_date,
        'rows': len(rows),
        'path': str(output),
        'name': output.name,
        'size': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'width': total_w,
        'height': total_h,
        'runtimeModelDecisions': 0,
    }


def main() -> None:
    if os.environ.get('NEGATIVE_REVIEW_INTERNAL') != INTERNAL_INVOCATION:
        print(json.dumps({'ok': False, 'reason': 'direct-stage-invocation-forbidden',
                          'runtimeModelDecisions': 0}))
        sys.exit(1)
    config = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    rows = json.loads(Path(config['finalData']).read_text(encoding='utf-8'))
    if not isinstance(rows, list) or not rows:
        print(json.dumps({'ok': False, 'reason': 'empty-source-data', 'runtimeModelDecisions': 0}))
        sys.exit(1)
    receipt = render(rows, config['businessDate'], Path(config['screenshot']))
    receipt_path = Path(config['screenshotReceipt'])
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
