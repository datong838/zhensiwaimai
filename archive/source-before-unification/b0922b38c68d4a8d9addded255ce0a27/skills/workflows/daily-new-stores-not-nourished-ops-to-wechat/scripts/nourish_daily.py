#!/usr/bin/env python3
"""Daily entry（对齐参考流 activity_daily）：采集服务商平台两页 → 按门店ID关联运营人 → 发运营群。

用法：
  # 只采集 + 生成 Excel（不发）
  python nourish_daily.py
  # 采集 + 生成 + 发群（受发送闸约束）
  python nourish_daily.py --execute
  # 发送闸：默认放行；--disarm 制动、--arm 解除
"""
from __future__ import annotations

import nourish_workflow

if __name__ == "__main__":
    nourish_workflow.main()
