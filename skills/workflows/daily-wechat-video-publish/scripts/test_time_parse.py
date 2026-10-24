"""聊天时间：今天 HH:MM、昨天、星期六 21:21。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from lib.time_parse import parse_message_time

TZ = ZoneInfo('Asia/Shanghai')


def test_weekday_before_cutoff():
    now = datetime(2026, 9, 7, 13, 4, tzinfo=TZ)  # 周一
    sat = parse_message_time('星期六 21:21', now=now)
    assert sat == datetime(2026, 9, 5, 21, 21, tzinfo=TZ)
    cutoff = datetime(2026, 9, 6, 13, 39, tzinfo=TZ)
    assert sat < cutoff


def test_yesterday_and_today():
    now = datetime(2026, 9, 7, 13, 4, tzinfo=TZ)
    assert parse_message_time('昨天 18:46', now=now) == datetime(2026, 9, 6, 18, 46, tzinfo=TZ)
    assert parse_message_time('12:11', now=now) == datetime(2026, 9, 7, 12, 11, tzinfo=TZ)


def test_invalid_ocr_clock_is_ignored():
    now = datetime(2026, 9, 8, 19, 0, tzinfo=TZ)
    assert parse_message_time('18:84', now=now) is None
    assert parse_message_time('昨天 25:10', now=now) is None
    assert parse_message_time('星期一 12:99', now=now) is None


if __name__ == '__main__':
    test_weekday_before_cutoff()
    test_yesterday_and_today()
    test_invalid_ocr_clock_is_ignored()
    print('ok')
