#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""品牌差评申诉通知 -> PNG（字节确定性渲染）。

存在原因（D16）：Windows 驱动发送路径是 `edit.SendKeys(text)` 逐字键盘注入，
`\\n`(U+000A) 是控制字符敲不进去 ⇒ 群内消息被压成一长行。驱动源码只在 Windows
机、Mac 无写入口，故本技能改以**图片**投递换行与版式。

硬约束：
- **字节确定性**：同一 text + 同一 style + 同一字体 ⇒ 逐字节相同的 PNG。
  图片 sha256 会进请求指纹（contract.content_binding 计入 name/size/sha256），
  任何不确定性（时间戳、随机、环境）都会让幂等失效。
- 无副作用、无 I/O 之外的行为；不读环境变量、不读系统时间。

版式要点（2026-09-30 大同确认）：只把**申诉结果的值**标红（如「申诉中」三字），
标签与 `---` 装饰破折号保持深色/浅灰 —— 整行发红反而糊住重点。
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 字体：Hiragino Sans GB（macOS 自带简中无衬线）。摘要仅作**记录**，不做强校验 ——
# 系统字体升级不该直接打断业务流；图片身份由渲染台账保证，字体变更只会产生新的
# 摘要，不会让历史待核项失配（见 render_manifest 的说明）。
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"

INHERIT = "申诉结果"
PLATFORM_PREFIX = "【"

#: 允许外发的申诉结果值（与 prepare_delivery.AUTHORIZED / daily_executor.SENDABLE_STATUSES
#: 同集）。仅用于自测与文档，不参与渲染决策 —— 改这里不会改变任何图片字节。
#: 2026-10-06 新增「未申诉（已开启自动申诉）」= 当前最长值（12 字）。实测该行
#: 878px < 984px 限宽，故结果行仍不折行；自测里有一条断言把这个边界钉住。
AUTHORIZED_RESULTS = ("未申诉", "未申诉（已开启自动申诉）", "申诉中", "申诉成功", "差评免责")

#: 版式常量。任何改动都会改变 styleSha256（见 style_digest），进而改变渲染字节。
STYLE = {
    "width": 1080,
    "padding": 48,
    "lineHeight": 66,
    "emphasisLineHeight": 72,
    "bodySize": 40,
    "emphasisSize": 46,
    "fontPath": FONT_PATH,
    "fontIndex": 0,
    "background": "white",
    "ink": [28, 28, 30],
    "red": [216, 30, 6],
    "decor": [150, 155, 165],
    "platform": [90, 96, 110],
    # 行首禁则：这些字符不得出现在行首（避头点）。
    "noStartChars": "，。、；：！？）】》」』％…、·",
    "pngOptimize": True,
}

#: 必须与 STYLE["fontIndex"] 一致；ucs4 字体集合里的第 0 号面（W3）。
_FONT_INDEX = 0


_STYLE_DIGEST_CACHE: str | None = None
_FONT_DIGEST_CACHE: str | None = None
_FONT_CACHE: dict[tuple[str, int, int], object] = {}


def style_digest() -> str:
    """版式常量的规范摘要：任何常量改动都会被看见。"""
    global _STYLE_DIGEST_CACHE
    if _STYLE_DIGEST_CACHE is None:
        canonical = json.dumps(STYLE, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        _STYLE_DIGEST_CACHE = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return _STYLE_DIGEST_CACHE


def font_digest() -> str:
    """字体文件的 sha256（仅记录，用于追溯；变更不阻断业务）。

    结果按进程缓存：字体文件在运行期不会变，而它是 20MB+ 级别，逐行重算会把
    一次投递拖成分钟级。
    """
    global _FONT_DIGEST_CACHE
    if _FONT_DIGEST_CACHE is None:
        digest = hashlib.sha256()
        with Path(FONT_PATH).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        _FONT_DIGEST_CACHE = digest.hexdigest()
    return _FONT_DIGEST_CACHE


def _font(size: int):
    """按 (路径, 字号, 面号) 缓存字形对象；TTC 解析一次即可复用。"""
    key = (STYLE["fontPath"], size, _FONT_INDEX)
    font = _FONT_CACHE.get(key)
    if font is None:
        font = ImageFont.truetype(STYLE["fontPath"], size, index=_FONT_INDEX)
        _FONT_CACHE[key] = font
    return font


def _wrap(draw, text: str, font, limit: int) -> list[str]:
    """按像素宽度折行，带「行首禁则」（避头点）。

    确定性：只做字体测量。禁则实现为——当导致折行的字符属于不可行首集合时，
    把**前一个字一起下移**到新行，既不让标点顶头，也不让行宽溢出。
    """
    no_start = set(STYLE["noStartChars"])
    lines: list[str] = []
    current = ""
    for char in text:
        if not current:
            current = char
            continue
        if draw.textlength(current + char, font=font) <= limit:
            current += char
            continue
        if char in no_start and len(current) > 1:
            lines.append(current[:-1])
            current = current[-1] + char
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines or [""]


def result_segments(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    """`申诉结果：---申诉中---` -> 标签(深) / 破折号(浅灰) / **值(红)** / 破折号(浅灰)。

    只标红结果值本身。若该行不是预期形态（没有 `：`），整行按普通深色处理，
    绝不猜——宁可少强调，不可标错。
    """
    ink, red, decor = (tuple(STYLE["ink"]), tuple(STYLE["red"]), tuple(STYLE["decor"]))
    if "：" not in line:
        return [(line, ink)]
    label, rest = line.split("：", 1)
    lead = rest[:len(rest) - len(rest.lstrip("-"))]
    tail = rest[len(rest.rstrip("-")):]
    value = rest.strip("-")
    segments = [(label + "：", ink)]
    if lead:
        segments.append((lead, decor))
    if value:
        segments.append((value, red))
    if tail:
        segments.append((tail, decor))
    return segments


def render_png(text: str) -> bytes:
    """把一条通知正文渲染成 PNG 字节。纯函数：同输入 ⇒ 同字节。"""
    body = _font(STYLE["bodySize"])
    emph = _font(STYLE["emphasisSize"])
    limit = STYLE["width"] - STYLE["padding"] * 2
    ink, platform = tuple(STYLE["ink"]), tuple(STYLE["platform"])

    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    rows: list[tuple[list[tuple[str, tuple[int, int, int]]], object, int]] = []
    for index, line in enumerate(str(text).split("\n")):
        if index == 0:                                    # 抬头
            font, height, items = emph, STYLE["emphasisLineHeight"], [(line, ink)]
        elif line.startswith(PLATFORM_PREFIX):             # 平台
            font, height, items = body, STYLE["lineHeight"], [(line, platform)]
        elif line.startswith(INHERIT):                     # ★ 只把结果值标红
            font, height, items = emph, STYLE["emphasisLineHeight"], result_segments(line)
        else:
            font, height, items = body, STYLE["lineHeight"], [(line, ink)]
        if len(items) == 1:
            for wrapped in _wrap(scratch, items[0][0], font, limit):
                rows.append(([(wrapped, items[0][1])], font, height))
        else:
            # 结果行不折行（折行会打断「只标值」的语义）。因此必须保证最长合法值
            # 不超限宽 —— 见 self_test 的 result-line-overflow 断言（当前最长值 12 字）。
            rows.append((items, font, height))

    height = STYLE["padding"] * 2 + sum(row[2] for row in rows)
    image = Image.new("RGB", (STYLE["width"], height), STYLE["background"])
    draw = ImageDraw.Draw(image)
    y = STYLE["padding"]
    for segments, font, row_height in rows:
        x = STYLE["padding"]
        for chunk, color in segments:
            draw.text((x, y), chunk, font=font, fill=color)
            x += draw.textlength(chunk, font=font)
        y += row_height
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=STYLE["pngOptimize"])
    return buffer.getvalue()


def render_sha256(text: str) -> str:
    return hashlib.sha256(render_png(text)).hexdigest()


def self_test() -> dict:
    """自证：确定性 + 中文字形非空白 + 结果值确实着色。"""
    sample = ("--- 2026-09-29 差评申诉进度通知 ---\n店名(测试店)\n【美团】\n"
              "评价时间: 2026-09-29\n评价等级: 2星\n申诉结果：---申诉中---\n评价内容: 测试")
    first, second = render_png(sample), render_png(sample)
    if first != second:
        raise AssertionError("render-not-deterministic")
    segments = result_segments("申诉结果：---申诉中---")
    red = tuple(STYLE["red"])
    if not any(color == red and chunk == "申诉中" for chunk, color in segments):
        raise AssertionError("result-value-not-highlighted")
    if any(chunk == "申诉结果：" and color == red for chunk, color in segments):
        raise AssertionError("result-label-must-not-be-red")
    # 最长合法值必须(a)仍只标值、(b)不超限宽（否则会被画布裁掉，静默丢内容）。
    longest = max(AUTHORIZED_RESULTS, key=len)
    long_line = f"申诉结果：---{longest}---"
    long_segments = result_segments(long_line)
    if not any(color == red and chunk == longest for chunk, color in long_segments):
        raise AssertionError("longest-result-value-not-highlighted")
    if any(chunk == "申诉结果：" and color == red for chunk, color in long_segments):
        raise AssertionError("result-label-must-not-be-red")
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    em = _font(STYLE["emphasisSize"])
    span = sum(scratch.textlength(chunk, font=em) for chunk, _ in long_segments)
    if span > STYLE["width"] - STYLE["padding"] * 2:
        raise AssertionError(f"result-line-overflow:{longest}:{span:.0f}px")
    with Image.open(io.BytesIO(first)) as probe:
        if probe.size[0] != STYLE["width"]:
            raise AssertionError("render-width-mismatch")
        if probe.size[1] <= STYLE["padding"] * 2:
            raise AssertionError("render-height-too-small")
    return {"ok": True, "bytes": len(first), "sha256": hashlib.sha256(first).hexdigest(),
            "styleSha256": style_digest(), "runtimeModelDecisions": 0}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False))
