"""下载来源硬门：必须是指定群里的原视频，且语义对得上群主题。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

TOPIC_TOKENS = ('鱼杂锅', '鱼杂王', '鱼杂')


def topic_keywords(group: str, shop: str = '') -> list[str]:
    blob = f'{group}{shop}'
    return [k for k in TOPIC_TOKENS if k in blob]


def matches_topic(text: str, keywords: list[str]) -> bool:
    if not text or not keywords:
        return False
    return any(k in text for k in keywords)


def header_is_target_group(header: str, group: str) -> bool:
    if not header or not group:
        return False
    return group in header or group[:8] in header


def cover_off_topic(cover: str, keywords: list[str]) -> bool:
    """封面已经有一长串中文，却完全看不到群主题 → 不是本群片子。"""
    zh = len(re.findall(r'[\u4e00-\u9fff]', cover or ''))
    if zh < 6:
        return False
    return not matches_topic(cover, keywords)


def stable_video_filename(message_time: str, cover: str = '', duration: str = '') -> str:
    """同一条群视频永远同一个文件名，用文件名防重复下载。"""
    try:
        ts = datetime.fromisoformat(message_time).strftime('%Y%m%dT%H%M')
    except ValueError:
        ts = re.sub(r'[^\dT]', '', message_time)[:13] or 'unknown'
    slug = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', cover or '')[:16]
    dur = (duration or '').replace(':', 'm')
    parts = [ts]
    if dur:
        parts.append(dur)
    parts.append(slug or 'video')
    return '_'.join(parts) + '.mp4'


def choose_new_mp4(
    before: dict[Path, float],
    after: dict[Path, float],
    *,
    since_epoch: float,
    exclude: set[Path],
) -> Path | None:
    """只接受本次点击之后新出现/新改写的 mp4。禁止回退到缓存里最新的任意文件。"""
    candidates: list[tuple[float, Path]] = []
    for path, mt in after.items():
        if path in exclude:
            continue
        if path not in before:
            candidates.append((mt, path))
        elif mt > before.get(path, 0) + 0.5:
            candidates.append((mt, path))
    if not candidates:
        return None
    return max(candidates)[1]
