#!/usr/bin/env python3
"""Daily entry（对齐 daily-new-stores-not-nourished-ops-to-wechat）：采集基础诊断14指标 + 门店分配 → 按门店ID关联运营人 → 一个 Excel（按指标分 sheet）→ 发运营群。

用法：
  # 只采集 + 生成 Excel（不发）
  python basic_diag_daily.py
  # 采集 + 生成 + 发群（受发送闸约束）
  python basic_diag_daily.py --execute
  # 发送闸：默认放行；--disarm 制动、--arm 解除
  python basic_diag_daily.py --disarm
"""
from __future__ import annotations

import basic_diag_workflow

if __name__ == "__main__":
    basic_diag_workflow.main()
