"""全局配置：设备、三应用包名、交互节奏参数。

所有业务模块从这里读取，避免硬编码。
"""
from platforms.registry import Pkg, Platform
from platforms.meituan.selectors import SELECTORS as MEITUAN_SELECTORS
from platforms.taobao_flash.selectors import SELECTORS as TAOBAO_FLASH_SELECTORS
from platforms.wechat.selectors import SELECTORS as WECHAT_SELECTORS


# ==================== 设备 ====================
# adb devices 查看；USB 连接留 None 即可自动选取
DEVICE_SERIAL = None

# 当前验证基线 uiautomator2 3.7.0 的 init 不支持 --mirror
INIT_MIRROR = False

# ==================== 稳健交互参数 ====================
class HumanConfig:
    # 点击前 / 后等待窗口（秒），用于等待界面稳定并降低误触
    CLICK_BEFORE = (0.3, 0.8)
    CLICK_AFTER = (0.5, 1.2)
    # 滑动持续时间
    SWIPE = (0.3, 0.6)
    # 逐字符输入间隔
    TYPING = (0.08, 0.25)
    # 翻页后等待
    SCROLL_AFTER = (0.5, 1.5)
    # 点击坐标容错范围；仅用于远离危险按钮的安全定位
    COORD_JITTER = 8
    # 失败重试
    MAX_RETRY = 3
    # 退避基数（指数退避）
    BACKOFF_BASE = 1.0


HUMAN = HumanConfig()


# ==================== 应用层包名 ====================
# ==================== 控件指纹池（需在 weditor 实测后填充） ====================
# 说明：resourceId 会随版本变化，此处为占位/常见值，
# 首次运行前请用 `python -m uiautomator2 init` 后打开 weditor 校准。
SELECTORS = {
    Platform.MEITUAN: MEITUAN_SELECTORS,
    Platform.TAOBAO_FLASH: TAOBAO_FLASH_SELECTORS,
    Platform.WECHAT: WECHAT_SELECTORS,
}


# ==================== 运行开关 ====================
# main.py 根据此字段决定跑哪个应用
TARGET_PLATFORM = Platform.MEITUAN

# 输出文件
OUTPUT_JSON = "result.json"
OCR_LANG = "ch"
