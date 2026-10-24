"""从视频缩略图 / 首帧图片 OCR 封面文案。"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

OCR_BIN = Path(
    '/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts/ocr_vision_bin'
)


def ocr_image(path: Path) -> list[tuple[str, float]]:
    if not path.exists():
        return []
    proc = subprocess.run([str(OCR_BIN), str(path)], capture_output=True, text=True, check=False)
    rows: list[tuple[str, float]] = []
    for line in proc.stdout.splitlines():
        if '\t' not in line:
            continue
        box, conf, text = line.split('\t', 2)
        rows.append((text.strip(), float(conf)))
    return rows


def extract_cover_text(path: Path, *, min_len: int = 6) -> str:
    """取 OCR 结果中最像封面大字的行（较长、中文为主）。"""
    rows = ocr_image(path)
    candidates = []
    for text, conf in rows:
        if len(text) < min_len:
            continue
        if '地址' in text or '视频号' in text or text.startswith('http'):
            continue
        zh = len(re.findall(r'[\u4e00-\u9fff]', text))
        if zh >= 4:
            candidates.append((zh * conf, text))
    if not candidates:
        return ''
    candidates.sort(reverse=True)
    return re.sub(r'\s+', '', candidates[0][1]).strip('。！!')


def find_thumbnail_for_video(video: Path) -> Path | None:
    """微信缓存常伴 _thumb.jpg；否则用同名 .jpg。"""
    for suffix in ('_thumb.jpg', '.jpg', '_thumb.png', '.png'):
        p = video.with_name(video.stem + suffix) if suffix.startswith('_') else video.with_suffix(suffix)
        if p.exists():
            return p
    side = video.parent / f'{video.stem}_thumb.jpg'
    return side if side.exists() else None
