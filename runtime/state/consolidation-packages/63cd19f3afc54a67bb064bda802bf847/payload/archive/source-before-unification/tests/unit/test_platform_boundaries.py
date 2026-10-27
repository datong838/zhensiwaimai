"""平台边界、兼容入口与外部副作用门的合同测试。"""
from __future__ import annotations

import pytest

from meituan_client import MeituanClient as LegacyMeituanClient
from mobile_runtime.safety import AuthorizationRequired
from platforms.meituan.client import MeituanClient
from platforms.meituan.selectors import SELECTORS as MEITUAN_SELECTORS
from platforms.taobao_flash.selectors import SELECTORS as TAOBAO_FLASH_SELECTORS
from platforms.wechat.client import WeChatClient
from platforms.wechat.selectors import SELECTORS as WECHAT_SELECTORS


def test_legacy_wrapper_points_to_new_platform_client() -> None:
    assert LegacyMeituanClient is MeituanClient


def test_platform_selectors_are_separate_mappings() -> None:
    assert MEITUAN_SELECTORS is not TAOBAO_FLASH_SELECTORS
    assert TAOBAO_FLASH_SELECTORS is not WECHAT_SELECTORS
    assert WECHAT_SELECTORS is not MEITUAN_SELECTORS


def test_wechat_send_fails_closed_before_device_access() -> None:
    client = WeChatClient(device=None)
    with pytest.raises(AuthorizationRequired):
        client.send_text("不会被发送")
