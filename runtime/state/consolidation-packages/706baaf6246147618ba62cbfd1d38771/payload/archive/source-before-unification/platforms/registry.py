"""业务平台注册表。"""
from enum import Enum


class Platform(str, Enum):
    MEITUAN = "meituan"
    TAOBAO_FLASH = "taobao_flash"
    WECHAT = "wechat"


class Pkg:
    MEITUAN = "com.sankuai.meituan"
    TAOBAO = "com.taobao.taobao"
    WECHAT = "com.tencent.mm"
