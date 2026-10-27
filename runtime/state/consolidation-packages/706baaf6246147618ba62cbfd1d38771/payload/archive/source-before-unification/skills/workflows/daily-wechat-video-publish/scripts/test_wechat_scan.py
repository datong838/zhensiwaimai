"""wechat_scan 单元测试：模拟 Mac 微信原生视频 OCR 结构。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from lib.time_parse import parse_cutoff
from lib.wechat_bridge import _chat_looks_latest
from wechat_scan import _parse_hits

TZ = ZoneInfo('Asia/Shanghai')


@dataclass
class Hit:
    cx: float
    cy: float
    w: float = 80
    h: float = 24
    confidence: float = 0.9
    text: str = ''


def test_native_video_after_yesterday_19():
    """略略略：@消息不算；分割线后缩略图封面 OCR 算原生视频。"""
    now = datetime(2026, 9, 6, 15, 0, tzinfo=TZ)
    cutoff = parse_cutoff('昨天 19:00', now=now)
    hits = [
        Hit(1100, 300, text='昨天 19:16'),
        Hit(580, 360, text='略略略'),
        Hit(720, 365, text='@Li·Hui'),
        Hit(600, 400, text='———分割线———'),
        Hit(580, 480, text='略略略'),
        Hit(680, 500, text='[视频]'),
        Hit(680, 520, text='独家秘制鱼杂锅'),
        Hit(670, 560, text='每一口都是舌尖上的享受！'),
    ]
    found = _parse_hits(hits, group='红太阳鱼杂王蜀川湘菜店抖音发视频', sender='略略略', cutoff=cutoff, now=now)
    assert len(found) == 1, found
    assert found[0]['source']['messageTime'].startswith('2026-09-05T19:16')
    assert '独家秘制' in found[0]['source']['coverPreview']
    assert found[0]['click']['cx'] > 430


def test_skip_channels_card():
    now = datetime(2026, 9, 6, 15, 0, tzinfo=TZ)
    cutoff = parse_cutoff('昨天 19:00', now=now)
    hits = [
        Hit(1100, 300, text='昨天 20:00'),
        Hit(260, 400, text='时间海'),
        Hit(700, 450, text='视频号·某某'),
    ]
    found = _parse_hits(hits, group='g', sender='时间海', cutoff=cutoff, now=now)
    assert len(found) == 0


def test_mac_duration_badge_is_native_video():
    """Mac 微信原视频：封面 + 0:10，没有 [视频] 三字。"""
    now = datetime(2026, 9, 7, 12, 0, tzinfo=TZ)
    cutoff = parse_cutoff('2026-09-06T13:39:00+08:00', now=now)
    hits = [
        Hit(1100, 220, text='11:56'),
        Hit(885, 349, text='略略略'),
        Hit(990, 420, text='吃过这家的鱼杂'),
        Hit(1087, 450, text='0:10'),
    ]
    found = _parse_hits(hits, group='红太阳鱼杂王蜀川湘菜店抖音发视频', sender='略略略', cutoff=cutoff, now=now)
    assert len(found) == 1, found
    assert '鱼杂' in found[0]['source']['coverPreview']


def test_duration_can_sit_below_sender_name():
    now = datetime(2026, 9, 7, 12, 0, tzinfo=TZ)
    cutoff = parse_cutoff('2026-09-06T13:39:00+08:00', now=now)
    hits = [
        Hit(1100, 500, text='11:56'),
        Hit(885, 568, text='略略略'),
        Hit(990, 698, text='独爱这一口鱼杂锅'),
        Hit(1091, 1052, text='0:12'),
    ]
    found = _parse_hits(hits, group='红太阳鱼杂王蜀川湘菜店抖音发视频', sender='略略略', cutoff=cutoff, now=now)
    assert len(found) == 1, found


def test_chat_looks_latest_needs_today_tail():
    yesterday = [
        Hit(1608, 221, text='昨天 14:50'),
        Hit(1609, 872, text='昨天 18:46'),
        Hit(900, 900, text='时间海'),
    ]
    saturday = [
        Hit(1608, 400, text='星期六 21:21'),
        Hit(920, 500, text='---分割线---'),
        Hit(900, 600, text='略略略'),
    ]
    latest = [
        Hit(1606, 916, text='14:49'),
        Hit(900, 400, text='略略略'),
        Hit(920, 500, text='---分割线---'),
        Hit(930, 600, text='动画表情'),
    ]
    assert _chat_looks_latest(yesterday) is False
    assert _chat_looks_latest(saturday) is False
    assert _chat_looks_latest(latest) is True


def test_no_nearby_chat_time_skips_download():
    now = datetime(2026, 9, 7, 13, 0, tzinfo=TZ)
    cutoff = parse_cutoff('2026-09-06T13:39:00+08:00', now=now)
    hits = [
        Hit(660, 220, text='12:11'),
        Hit(885, 349, text='略略略'),
        Hit(990, 420, text='吃过这家的鱼杂'),
        Hit(1087, 450, text='0:10'),
    ]
    found = _parse_hits(hits, group='红太阳鱼杂王蜀川湘菜店抖音发视频', sender='略略略', cutoff=cutoff, now=now)
    assert found == []


def test_saturday_before_cutoff_is_not_downloaded():
    now = datetime(2026, 9, 7, 13, 0, tzinfo=TZ)
    cutoff = parse_cutoff('2026-09-06T13:39:00+08:00', now=now)
    hits = [
        Hit(1100, 300, text='星期六 21:21'),
        Hit(885, 400, text='略略略'),
        Hit(990, 480, text='吃过这家的鱼杂'),
        Hit(1087, 510, text='0:10'),
    ]
    found = _parse_hits(hits, group='红太阳鱼杂王蜀川湘菜店抖音发视频', sender='略略略', cutoff=cutoff, now=now)
    assert found == []


def test_time_below_video_is_not_used():
    now = datetime(2026, 9, 7, 16, 20, tzinfo=TZ)
    cutoff = parse_cutoff('2026-09-06T13:39:00+08:00', now=now)
    hits = [
        Hit(994, 250, text='这锅肥肠鱼杂就是答案！'),
        Hit(1087, 587, text='0:08'),
        Hit(885, 680, text='略略略'),
        Hit(982, 783, text='---分割线---'),
        Hit(1606, 916, text='14:49'),
    ]
    found = _parse_hits(hits, group='红太阳鱼杂王蜀川湘菜店抖音发视频', sender='略略略', cutoff=cutoff, now=now)
    assert found == []


def test_time_above_video_is_required():
    now = datetime(2026, 9, 7, 16, 20, tzinfo=TZ)
    cutoff = parse_cutoff('2026-09-06T13:39:00+08:00', now=now)
    hits = [
        Hit(1100, 210, text='14:40'),
        Hit(994, 250, text='这锅肥肠鱼杂就是答案！'),
        Hit(1087, 587, text='0:08'),
        Hit(885, 680, text='略略略'),
    ]
    found = _parse_hits(hits, group='红太阳鱼杂王蜀川湘菜店抖音发视频', sender='略略略', cutoff=cutoff, now=now)
    assert len(found) == 1, found
    assert found[0]['source']['messageTime'].startswith('2026-09-07T14:40')
    assert '肥肠鱼杂' in found[0]['source']['coverPreview']


def test_cover_text_without_video_marker_is_not_a_video():
    """只有封面长文案、没有 [视频]，不能当群原视频（避免点到别人的片/视频号）。"""
    now = datetime(2026, 9, 6, 15, 0, tzinfo=TZ)
    cutoff = parse_cutoff('昨天 19:00', now=now)
    hits = [
        Hit(1100, 300, text='昨天 19:16'),
        Hit(580, 480, text='略略略'),
        Hit(680, 520, text='独家秘制鱼杂锅'),
        Hit(670, 560, text='每一口都是舌尖上的享受！'),
    ]
    found = _parse_hits(hits, group='红太阳鱼杂王蜀川湘菜店抖音发视频', sender='略略略', cutoff=cutoff, now=now)
    assert found == []


if __name__ == '__main__':
    test_native_video_after_yesterday_19()
    test_skip_channels_card()
    test_mac_duration_badge_is_native_video()
    test_duration_can_sit_below_sender_name()
    test_chat_looks_latest_needs_today_tail()
    test_no_nearby_chat_time_skips_download()
    test_saturday_before_cutoff_is_not_downloaded()
    test_time_below_video_is_not_used()
    test_time_above_video_is_required()
    test_cover_text_without_video_marker_is_not_a_video()
    print('ok')

