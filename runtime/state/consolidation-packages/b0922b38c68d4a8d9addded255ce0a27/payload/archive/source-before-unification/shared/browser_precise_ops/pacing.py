#!/usr/bin/env python3
"""pacing.py — ③ 拟人节奏 + 反检测启动参数（移植自 Easel xhs_publish.py 反检测纪律）.

问题：自动化点击/输入若匀速、零间隔，极易被反爬识别，且连续动作可能在页面未就绪时叠加
出错（点错、吞键）。

方案：
  - human_delay(min_ms, max_ms)：在动作之间加随机停顿（对齐 Easel _human_type 的 30~110ms
    逐字符 + 元素间 200~1800ms 的随机感）。
  - anti_detect_launch_args()：若确需自行拉起浏览器，给出与 Easel 一致的启动参数
    （--disable-blink-features=AutomationControlled + zh-CN）。本项目默认「附着已有 Chrome」
    不自行拉起，故该函数主要供需要独立内核的副流程复用。

纯 stdlib，带 selftest。
"""
from __future__ import annotations

import random
import time


def human_delay(min_ms: int = 120, max_ms: int = 420, *, sleep_fn=time.sleep, rng=random) -> float:
    """动作间随机停顿，返回实际毫秒数。默认 120~420ms（比固定 sleep 更像人）。"""
    ms = rng.randint(min_ms, max_ms)
    sleep_fn(ms / 1000.0)
    return ms


def type_char_delay(*, sleep_fn=time.sleep, rng=random) -> float:
    """逐字符输入时的停顿（对齐 Easel _human_type 的 30~110ms）。返回实际毫秒数。"""
    ms = rng.randint(30, 110)
    sleep_fn(ms / 1000.0)
    return ms


def anti_detect_launch_args(extra: list[str] | None = None) -> list[str]:
    """返回去自动化的 Chromium 启动参数（仅在自行拉起浏览器时使用）。

    与 Easel xhs_publish.py 一致：禁用 AutomationControlled 标记 + 简体中文 locale。
    """
    args = [
        "--disable-blink-features=AutomationControlled",
        "--lang=zh-CN",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if extra:
        args.extend(extra)
    return args


def self_test() -> dict:
    calls = []

    def fake_sleep(s):
        calls.append(s)

    d = human_delay(100, 100, sleep_fn=fake_sleep, rng=random)
    assert d == 100 and calls == [0.1]
    c = type_char_delay(sleep_fn=fake_sleep, rng=random)
    assert 30 <= c <= 110
    a = anti_detect_launch_args()
    assert "--disable-blink-features=AutomationControlled" in a
    assert "--lang=zh-CN" in a
    # 不自行拉起时返回空列表也合理
    assert anti_detect_launch_args([]) == [
        "--disable-blink-features=AutomationControlled",
        "--lang=zh-CN",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    return {"ok": True, "tests": 4}


if __name__ == "__main__":
    import json

    print(json.dumps(self_test(), ensure_ascii=False, indent=2))
