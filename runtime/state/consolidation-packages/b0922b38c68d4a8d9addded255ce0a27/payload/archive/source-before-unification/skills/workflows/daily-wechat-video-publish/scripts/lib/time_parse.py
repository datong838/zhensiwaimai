"""聊天时间解析（Asia/Shanghai）。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')


def parse_cutoff(text: str, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(TZ)
    text = text.strip()
    if 'T' in text or '+' in text:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(TZ)
    m = re.match(r'昨天\s*(\d{1,2}):(\d{2})', text)
    if m:
        d = (now - timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return d
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})', text)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), tzinfo=TZ)
    raise ValueError(f'无法解析 cutoff: {text}')


_WEEKDAY = {
    '一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6,
}


def _date_for_weekday(target: int, now: datetime) -> datetime:
    delta = (now.weekday() - target) % 7
    if delta == 0:
        delta = 7
    return now - timedelta(days=delta)


def _valid_clock(hour: str, minute: str) -> bool:
    """OCR 可能产生 18:84；非法时分不是聊天时间。"""
    return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59


def parse_message_time(text: str, *, now: datetime | None = None) -> datetime | None:
    """解析聊天区时间：10:19、昨天 23:34、星期六 21:21。"""
    now = now or datetime.now(TZ)
    text = text.strip()
    if not text:
        return None
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', text)
    if m:
        if not _valid_clock(m.group(1), m.group(2)):
            return None
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    m = re.fullmatch(r'昨天\s*(\d{1,2}):(\d{2})', text)
    if m:
        if not _valid_clock(m.group(1), m.group(2)):
            return None
        base = now - timedelta(days=1)
        return base.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    m = re.fullmatch(r'(星期|周)([一二三四五六日天])\s*(\d{1,2}):(\d{2})', text)
    if m:
        if not _valid_clock(m.group(3), m.group(4)):
            return None
        base = _date_for_weekday(_WEEKDAY[m.group(2)], now)
        return base.replace(hour=int(m.group(3)), minute=int(m.group(4)), second=0, microsecond=0)
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})', text)
    if m:
        if not _valid_clock(m.group(4), m.group(5)):
            return None
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), tzinfo=TZ)
    return None
