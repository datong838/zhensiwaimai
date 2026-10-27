# 2026-09-03 执行器固化验收

## 范围

把实操稳定点收进预建执行器，减少计时中模型临场脚本。

## 自测

| 执行器 | 结果 |
|---|---|
| `chrome_desktop_bridge.py --self-test` | GREEN（5） |
| `wechat_sender_executor.py --self-test` | GREEN（5） |
| `merchant_collector_executor.mjs --self-test` | GREEN（10，含 bridge） |

## 固化交付

- 方案：`references/plan-2026-09-03-executor-hardening.md`
- 桌面桥：`scripts/chrome_desktop_bridge.py`（D1–D7）
- 采集器接线：`--preflight-nav` / `--collect-ocr-bridge` 委托 bridge；`seizeChromeFocus` 先清遮挡
- 发送器：主微信 chooser 等待加长，精确点「微信」
- 合同 / SKILL 已同步

## 计时口令（无 sky）

```bash
python scripts/chrome_desktop_bridge.py --self-test
python scripts/wechat_sender_executor.py --self-test
python scripts/chrome_desktop_bridge.py --preflight-nav
python scripts/chrome_desktop_bridge.py --collect --group "臻肆测试群"
# 审计收据后
python scripts/wechat_sender_executor.py --execute --group "臻肆测试群" \
  --serial MGFNW19731004216 \
  --collection-receipt /tmp/zhensi_agent_merchants/collection_receipt.json \
  --standing-authorization "zhensi-test-main-wechat-merchant-v1"
```
