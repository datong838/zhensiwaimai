#!/usr/bin/env python3
"""经营任务完成率统计：按运营负责人分组求均值 → 白底加粗彩色卡片图。

为什么必须做成图片：Windows 驱动逐字键盘注入敲不进换行，driver read_messages 又会把
一条消息里的换行整体删除（见 wechat-messaging/scripts/windows_adapter.py 顶部注释），
多行文本外发后回读锚点永远匹配不上、会被判 unknown。图片是唯一可靠的载体（大同口径）。

颜色阈值（大同口径）：<90% 红字，>95% 绿字，90%~95% 黑字；全部加粗、白底。
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

# 阈值与配色（大同口径，勿擅改）
RED_BELOW = 90.0
GREEN_ABOVE = 95.0
COLOR_RED = (227, 49, 43)
COLOR_GREEN = (24, 144, 96)
COLOR_BLACK = (0, 0, 0)
COLOR_BG = (255, 255, 255)
# 图尾提示行（无数据未计入）：小一号灰字，与数据行区分，不占用红/绿/黑的语义
NOTE_COLOR = (89, 89, 89)

TITLE_TEXT = "经营任务完成率"
UNASSIGNED = "未分配"

# 加粗中文无衬线字体：Hiragino Sans GB W6（macOS 自带，idx=2 为 W6 真加粗字重）
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_INDEX = 2
FONT_FALLBACKS = (("/System/Library/Fonts/STHeiti Medium.ttc", 0),)

# 组名清洗：先查显式映射（运营人在门店分配表里的原始值 → 群里展示名），
# 再走通用前后缀剥离规则。两者都留在这里，以后要改只动这一处。
DISPLAY_OVERRIDES = {
    "盯个盯徐从众": "徐从众",   # 去掉「盯个盯」（自家团队前缀）
    "上海青辅咨询": "青辅",     # 去掉「上海…咨询」公司壳
    "张燕茹发数据": "张燕茹",
    "食迹科技吴文同": "吴文同",
    "蕉果科技谢心怡": "谢心怡",
    "溪雨观王加明": "王加明",
    "壹勺运营": "壹勺",
    "饭得科技": "饭得科技",
    "雷洁老师": "雷洁",
    # ★「雷洁2」必须与「雷洁老师」保持不同展示名：两者是门店分配表里的**不同运营人**。
    # 2026-10-13 踩过：曾把两者都映射成「雷洁」，于是按展示名分组时两家门店混算成一条
    # 「雷洁 95.33」——那 5 家全是雷洁2的，而雷洁老师的 23 家贡献 0 家且静默消失。
    # 别名**不得**互相合并成同一展示名；详见 compute_stats 的碰撞兜底。
    "雷洁2": "雷洁2",
}
STRIP_PREFIXES = ("盯个盯", "上海")
STRIP_SUFFIXES = ("科技", "咨询", "运营", "发数据", "老师", "组长号", "数据")


def display_name(raw: str) -> str:
    """运营人原始值 → 展示名；清洗不出东西就原样返回（绝不留空）。"""
    value = (raw or "").strip()
    if not value:
        return UNASSIGNED
    if value in DISPLAY_OVERRIDES:
        return DISPLAY_OVERRIDES[value]
    for prefix in STRIP_PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix):
            value = value[len(prefix):]
            break
    for suffix in STRIP_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
            break
    return value or (raw or "").strip() or UNASSIGNED


def _cells(text: str) -> float:
    """按全角=1、半角=0.5 折算显示宽度。"""
    return sum(1.0 if ord(ch) > 0x2E80 else 0.5 for ch in text)


def pad_name(name: str, target: float) -> str:
    """把组名补到统一显示宽度（用全角空格，短名补在字中间，对齐如「王　森」）。"""
    chars = list(name)
    gap = target - _cells(name)
    if gap <= 0.01:
        return name
    if gap >= len(chars):
        return name + "　" * int(round(gap))
    step = len(chars) / (gap + 1)
    for i in range(int(round(gap))):
        chars.insert(min(len(chars), int(round((i + 1) * step))), "　")
    return "".join(chars)


def format_pct(value: float) -> str:
    """92.08 / 91.8 / 88.9：最多两位小数，去掉多余的 0（对齐大同给的示例格式）。"""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def value_color(value: float) -> tuple[int, int, int]:
    """完成率 → 字色：<90 红、>95 绿、90~95 黑（阈值边界值归黑，属大同口径的「正常」）。"""
    if value < RED_BELOW:
        return COLOR_RED
    if value > GREEN_ABOVE:
        return COLOR_GREEN
    return COLOR_BLACK


def compute_stats(rows: list[tuple[str, float | None]]) -> list[dict]:
    """rows = [(运营人原始值, 经营任务完成率百分数或None)] → 按**原始运营人**聚合、按均值降序。

    ★ 分组键必须是门店分配表里的原始「运营人」，清洗后的展示名只用于显示。
    两个不同运营人清洗后撞成同一个展示名时（如「王森」与「王森组长号」），**退回原始值显示**、
    各自独立成行，绝不合并均值——合并会让一方的门店数被另一方冒领。
    空值不进均值（等价 Excel AVERAGE 忽略空单元格）；某组无任何数值则整组不出现在图里。
    """
    buckets: "OrderedDict[str, dict]" = OrderedDict()
    for owner, pct in rows:
        raw = (owner or "").strip() or UNASSIGNED
        bucket = buckets.setdefault(raw, {"raw": raw, "values": [], "shops": 0})
        bucket["shops"] += 1
        if pct is not None:
            bucket["values"].append(float(pct))
    # 展示名分配：默认清洗值；若两个原始值清洗后同名，则这些行一律退回原始值显示。
    name_count: dict[str, int] = {}
    for raw in buckets:
        name_count[display_name(raw)] = name_count.get(display_name(raw), 0) + 1
    for raw, bucket in buckets.items():
        candidate = display_name(raw)
        bucket["name"] = raw if name_count.get(candidate, 0) > 1 else candidate
    stats = []
    for bucket in buckets.values():
        if not bucket["values"]:
            continue
        values = bucket["values"]
        stats.append({
            "name": bucket["name"],
            "avg": sum(values) / len(values),
            "shops": bucket["shops"],
            "counted": len(values),
            "missing": bucket["shops"] - len(values),
            "raw": bucket["raw"],
        })
    stats.sort(key=lambda item: (-item["avg"], item["name"]))
    return stats


def coverage_notes(coverage: dict | None) -> list[str]:
    """覆盖盲区 → 图尾提示行，例：{"raw": "雷洁老师", "shops": 23} → 「雷洁老师 23 家无数据未计入」。

    ★ 用**原始运营人**而不是清洗后的展示名：清洗会把「雷洁老师」压成「雷洁」，
    与图里的「雷洁2」肉眼难分，用原始值才指得准人（大同 10-13 口径）。
    无盲区返回空列表 ⇒ 图尾不加行。顺序沿用 coverage 的按门店数降序。
    """
    if not coverage:
        return []
    notes: list[str] = []
    for entry in coverage.get("allocOnlyGroups") or []:
        raw = str(entry.get("raw") or "").strip()
        shops = int(entry.get("shops") or 0)
        if raw and shops > 0:
            notes.append(f"{raw} {shops} 家无数据未计入")
    return notes


def render_card(stats: list[dict], out_path: Path, title: str = TITLE_TEXT,
                notes: list[str] | tuple[str, ...] = ()) -> Path:
    """渲染白底加粗彩色统计图；返回输出路径。

    notes：图尾提示行（小一号灰字），如「雷洁老师 23 家无数据未计入」。
    """
    from PIL import Image, ImageDraw, ImageFont

    title_size, row_size, note_size, pad = 46, 40, 28, 36
    line_gap, line_gap_title = 58, 74
    note_gap, note_line_gap = 30, 42
    try:
        title_font = ImageFont.truetype(FONT_PATH, title_size, index=FONT_INDEX)
        row_font = ImageFont.truetype(FONT_PATH, row_size, index=FONT_INDEX)
        note_font = ImageFont.truetype(FONT_PATH, note_size, index=FONT_INDEX)
    except Exception:  # noqa: BLE001 字体索引漂移时退回任一中文字体
        title_font = row_font = note_font = None
        for path, index in FONT_FALLBACKS:
            try:
                title_font = ImageFont.truetype(path, title_size, index=index)
                row_font = ImageFont.truetype(path, row_size, index=index)
                note_font = ImageFont.truetype(path, note_size, index=index)
                break
            except Exception:  # noqa: BLE001
                continue
        if row_font is None:
            raise RuntimeError("no-cjk-font-available")
        note_font = note_font or row_font

    # 组名统一补到 3 字宽（对齐大同示例：2 字名补成「王　森」「青　辅」，3 字名不补）。
    # 不按最长名撑宽：组名普遍 ≤3 字，撑到 4/5 字会把「张燕茹」劈成「张燕　茹」。
    longest = max((_cells(item["name"]) for item in stats), default=2.0)
    target = min(max(longest, 2.0), 3.0)
    note_lines = [str(line) for line in (notes or ()) if str(line).strip()]
    lines = [title] + [f"{pad_name(item['name'], target)}：{format_pct(item['avg'])}"
                        for item in stats]
    width = int(pad * 2 + max(
        title_font.getlength(title) if title_font else 0,
        max((row_font.getlength(line) for line in lines[1:]), default=0),
        max((note_font.getlength(line) for line in note_lines), default=0)))
    height = int(pad * 2 + line_gap_title + line_gap * len(stats)
                 + (note_gap + note_line_gap * len(note_lines) if note_lines else 0) + 16)

    image = Image.new("RGB", (width, height), COLOR_BG)
    draw = ImageDraw.Draw(image)
    draw.text((pad, pad), title, font=title_font, fill=COLOR_BLACK)
    y = pad + line_gap_title
    for item in stats:
        label = pad_name(item["name"], target)
        draw.text((pad, y), f"{label}：", font=row_font, fill=COLOR_BLACK)
        text_w = row_font.getlength(f"{label}：")
        value = item["avg"]
        draw.text((pad + text_w, y), format_pct(value), font=row_font, fill=value_color(value))
        y += line_gap
    # 图尾提示：与数据行之间多留 note_gap，小一号灰字，左对齐同数据行
    if note_lines:
        y += note_gap
        for line in note_lines:
            draw.text((pad, y), line, font=note_font, fill=NOTE_COLOR)
            y += note_line_gap
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    image.save(out_path, format="PNG")
    return out_path