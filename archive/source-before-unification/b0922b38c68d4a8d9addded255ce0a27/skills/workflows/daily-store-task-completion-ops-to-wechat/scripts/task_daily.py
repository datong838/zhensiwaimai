#!/usr/bin/env python3
"""Daily entry（对齐参考流 nourish_daily）：采集服务商平台两页 → 按门店ID关联运营人
→ 明细 Excel + 完成率统计图 → 发运营群。

用法：
  python task_daily.py             # 只采集 + 生成（不发）
  python task_daily.py --execute   # 采集 + 生成 + 发群（受发送闸约束）
  python task_daily.py --deliver-run <run目录>   # 不采集，直接用某次 run 的明细+图发群（补发）
  python task_daily.py --disarm    # 制动发送；--arm 解除
"""
from __future__ import annotations

import task_workflow

if __name__ == "__main__":
    task_workflow.main()