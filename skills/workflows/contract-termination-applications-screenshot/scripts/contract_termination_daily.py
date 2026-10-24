#!/usr/bin/env python3
"""Daily entry（对齐 daily-store-basic-diagnosis-to-wechat）：合同解约申请·处理中任务列表截图 → 发运营群。

用法：
  python contract_termination_daily.py             # 只截图（不发）
  python contract_termination_daily.py --execute   # 截图 + 发群（受发送闸约束）
  python contract_termination_daily.py --deliver-run <run目录>   # 不重截，用某次 run 的图补发
  发送闸：默认放行；--disarm 制动、--arm 解除
"""
from __future__ import annotations

import contract_termination_workflow

if __name__ == "__main__":
    contract_termination_workflow.main()
