"""下载来源硬门：指定群 + 群主题，对不上宁可不发。"""
from pathlib import Path

from lib.source_guard import (
    choose_new_mp4,
    cover_off_topic,
    header_is_target_group,
    matches_topic,
    stable_video_filename,
    topic_keywords,
)
from wechat_scan import _is_native_video_block
from test_wechat_scan import Hit


GROUP = '红太阳鱼杂王蜀川湘菜店抖音发视频'
SHOP = '红太阳鱼杂王·蜀湘川菜(杨浦保利店)'


def test_stable_filename_is_deterministic():
    a = stable_video_filename('2026-09-07T11:27:00+08:00', '独爱这一口鱼杂锅', '0:09')
    b = stable_video_filename('2026-09-07T11:27:00+08:00', '独爱这一口鱼杂锅', '0:09')
    c = stable_video_filename('2026-09-07T11:27:00+08:00', '吃鱼杂的运气都不会太差', '0:09')
    assert a == b == '20260907T1127_0m09_独爱这一口鱼杂锅.mp4'
    assert a != c


def test_topic_keywords_from_group():
    keys = topic_keywords(GROUP, SHOP)
    assert '鱼杂' in keys
    assert keys  # 提不出主题词就不能下


def test_fish_cover_passes_kitchen_cover_fails():
    keys = topic_keywords(GROUP, SHOP)
    assert matches_topic('独家秘制鱼杂锅每一口都是舌尖上的享受', keys)
    assert not matches_topic('独爱这口鲜！懂的人自然懂', keys)
    assert not matches_topic('减肥计划破功？先吃完这锅再说', keys)
    assert not matches_topic('', keys)
    assert cover_off_topic('独爱这口鲜！懂的人自然懂', keys)
    assert not cover_off_topic('独家秘制鱼杂锅每一口都是舌尖上的享受', keys)
    assert not cover_off_topic('[视频]', keys)


def test_header_must_be_the_named_group():
    assert header_is_target_group('红太阳鱼杂王蜀川湘菜店抖音发视频（21）', GROUP)
    assert not header_is_target_group('文件传输助手', GROUP)
    assert not header_is_target_group('', GROUP)


def test_no_global_cache_fallback():
    before = {Path('/tmp/old.mp4'): 100.0, Path('/tmp/unrelated-newest.mp4'): 200.0}
    after = {Path('/tmp/old.mp4'): 100.0, Path('/tmp/unrelated-newest.mp4'): 200.0}
    assert choose_new_mp4(before, after, since_epoch=500.0, exclude=set()) is None


def test_preexisting_recent_mtime_is_not_new():
    before = {Path('/tmp/other-chat.mp4'): 499.0}
    after = {Path('/tmp/other-chat.mp4'): 499.0}
    assert choose_new_mp4(before, after, since_epoch=500.0, exclude=set()) is None


def test_picks_only_mp4_newer_than_click():
    before = {Path('/tmp/old.mp4'): 100.0}
    after = {
        Path('/tmp/old.mp4'): 100.0,
        Path('/tmp/clicked.mp4'): 510.0,
    }
    assert choose_new_mp4(before, after, since_epoch=500.0, exclude=set()) == Path('/tmp/clicked.mp4')


def test_native_block_requires_video_marker():
    cover_only = [Hit(680, 520, text='独家秘制鱼杂锅')]
    assert _is_native_video_block(cover_only) is False
    with_marker = [Hit(680, 500, text='[视频]'), Hit(680, 520, text='独家秘制鱼杂锅')]
    assert _is_native_video_block(with_marker) is True
    with_duration = [Hit(885, 349, text='略略略'), Hit(1087, 450, text='0:10'), Hit(990, 420, text='吃过这家的鱼杂')]
    assert _is_native_video_block(with_duration) is True


if __name__ == '__main__':
    test_stable_filename_is_deterministic()
    test_topic_keywords_from_group()
    test_fish_cover_passes_kitchen_cover_fails()
    test_header_must_be_the_named_group()
    test_no_global_cache_fallback()
    test_preexisting_recent_mtime_is_not_new()
    test_picks_only_mp4_newer_than_click()
    test_native_block_requires_video_marker()
    print('ok')
