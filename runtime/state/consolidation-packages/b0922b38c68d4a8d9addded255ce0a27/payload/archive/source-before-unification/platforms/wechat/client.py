"""[DEPRECATED 2026-09-30] 微信业务适配器（手机 adb 旧架构）。

本目录（platforms/）是早期的「手机 app 操控」抽象，已无人引用：14 条流水线实际统一走
skills/ 下的桌面浏览器 CDP 实现 + skills/wechat-messaging 封印发送库（Windows 网关 / Mac 桌面
微信 / 手机 adb 三通道）。发送动作一律经 wechat-messaging 并带授权引用，请勿 import 本目录。
（⚠️ Mac 桌面微信通道已于 2026-09-30 停用，实际发送一律改走 Windows 网关/手机微信；以下「Mac 桌面微信」字样仅作历史架构审计，不得作为运行依据。）
如未来确需「手机端」能力，应作为独立岗位（posts/<platform>-post）按岗位实体化方案重建。
"""
import time
from typing import Any, Optional

from anti_popup import dismiss, ensure_permission
from human import click, type_text
from locator import click_primary
from mobile_runtime.contracts import ActionRequest, RiskLevel
from mobile_runtime.safety import authorize_action
from platforms.registry import Pkg, Platform
from vision import click_by_ocr


class WeChatClient:
    def __init__(self, device: Any): self.d = device

    def launch(self):
        self.d.app_start(Pkg.WECHAT); time.sleep(3); dismiss(self.d); ensure_permission(self.d)

    def open_chat(self, contact: str) -> bool:
        if not click_primary(self.d, Platform.WECHAT, "search_box") and not click_by_ocr(self.d, "搜索"): return False
        type_text(self.d, contact); time.sleep(1.5)
        for element in self.d(className="android.widget.TextView"):
            if contact in (element.get_text() or ""):
                click(self.d, element=element); time.sleep(2); return True
        return False

    def send_text(self, text: str, authorization_ref: Optional[str] = None) -> bool:
        authorize_action(ActionRequest(
            action_id="wechat-send-text", action_type="send_message", risk_level=RiskLevel.EXTERNAL_EFFECT,
            target_package=Pkg.WECHAT, parameters={"textLength": len(text)}, authorization_ref=authorization_ref,
        ))
        edit = self.d(className="android.widget.EditText")
        if not edit.exists(timeout=3): return False
        edit.click(); type_text(self.d, text); time.sleep(0.5)
        if self.d(text="发送").exists(timeout=2): click(self.d, text="发送")
        else: self.d.press("enter")
        return True

    def screenshot_current(self, path: str = "wechat_screen.png"):
        self.d.screenshot(path); return path

    def stop(self): self.d.app_stop(Pkg.WECHAT)
