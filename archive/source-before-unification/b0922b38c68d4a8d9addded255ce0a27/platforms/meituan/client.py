"""[DEPRECATED 2026-09-30] 美团外卖业务适配器（手机 adb 旧架构）。

本目录（platforms/）是早期的「手机 app 操控」抽象，已无人引用：14 条流水线实际统一走
skills/ 下的桌面浏览器 CDP 实现（金鲨 9232 / 淘宝品牌商 9230 / 淘宝服务商 9231 / 美团 9233 /
各视频平台实例）。请勿在新代码中 import 本目录。如未来确需「手机端」能力，应作为独立岗位
（posts/<platform>-post）按岗位实体化方案重建，而非复用此处。
"""
import json
import time
from typing import Any

from anti_popup import dismiss, ensure_permission
from human import click, swipe_up, type_text
from locator import click_primary
from platforms.registry import Pkg, Platform
from vision import click_by_ocr, ocr_image, screenshot
from .extractors import build_shop_info


class MeituanClient:
    def __init__(self, device: Any): self.d = device

    def launch(self):
        self.d.app_start(Pkg.MEITUAN); time.sleep(3); dismiss(self.d); ensure_permission(self.d)

    def _ensure_address(self, address: str):
        raise NotImplementedError("请在已授权测试设备上校准地址切换逻辑")

    def search_shop(self, address: str, keyword: str):
        self._ensure_address(address)
        if not click_primary(self.d, Platform.MEITUAN, "search_box"): click_by_ocr(self.d, "搜索")
        type_text(self.d, keyword); self.d.press("enter"); time.sleep(2); dismiss(self.d)

    def enter_first_shop(self) -> bool:
        cards = self.d(className="android.widget.TextView")
        if cards.count <= 0: return False
        click(self.d, element=cards[0]); time.sleep(3); dismiss(self.d); return True

    def scrape_current(self, rank: int = 1) -> dict:
        path = f"mt_shop_{rank}.png"; screenshot(self.d, path)
        return build_shop_info(ocr_image(path), rank)

    def collect(self, address: str, keyword: str, top_n: int = 5) -> list:
        self.launch(); self.search_shop(address, keyword); results = []
        for index in range(top_n):
            if self.enter_first_shop():
                results.append(self.scrape_current(index + 1)); self.d.press("back"); time.sleep(2); swipe_up(self.d, times=2)
        self.d.app_stop(Pkg.MEITUAN); return results

    @staticmethod
    def dump(results: list, path: str = "meituan_result.json"):
        with open(path, "w", encoding="utf-8") as stream: json.dump(results, stream, ensure_ascii=False, indent=2)
