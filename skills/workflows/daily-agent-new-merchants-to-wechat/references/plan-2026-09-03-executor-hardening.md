# 计时前执行器固化方案（2026-09-03）

## 目标

把本轮实操跑通的桌面/手机动作收进**预建执行器**，计时后模型只做：

1. 跑自测 / 预检  
2. 跑采集执行器拿收据  
3. 审计收据  
4. 跑发送执行器  

禁止再在计时中临场拼 AppleScript/OCR 脚本。

## 本轮实操已证明、必须固化的点

| 编号 | 问题 | 固化动作 |
|---|---|---|
| D1 | AOS Dedicated Chrome「第三方应用」、桌面微信/企微与服务商窗同框叠盖 | 每次截图/点击前 `declutterOverlays`，再 Raise「淘宝闪购服务商平台」 |
| D2 | `seizeChromeFocus` 只 Raise `window 1`，多 Chrome 进程时点错 | 按窗口标题/服务商窗 Raise；采集只认含「淘宝闪购服务商」的窗 |
| D3 | 侧栏 OCR 点击偶发不进页；AX 点「意向商户管理」稳定 | 进页：先 AX 点菜单文案，失败再 OCR；列表判据放宽为「意向商户管理 +（商家意向列表 或 待处理+详情）」 |
| D4 | 筛选项在首屏外 | 进页后 PageUp/Home 露出「开始日期/结束日期/查询」 |
| D5 | 「推荐时间」既是筛选项标签也是表列；表列常需横滑 | 当日查询后 Shift+滚轮横滑，直到行上出现 `YYYY-MM-DD HH:mm:ss` |
| D6 | OCR 把「详情 去签约 释放」粘成一块；点偏会进签约 | 只点块左侧约 8% 宽；禁止点「去签约」 |
| D7 | 详情字段解析误吃表头 | 仅解析弹层区域（「推荐商家详情」附近） |
| W1 | 荣耀双开：`HwChooserActivity` 有「微信」「微信分身」；2s 内找不到就停 | 加长等待；优先 `content-desc/text` 精确「微信」；已在主微信前台则跳过 chooser |

## 文件职责

| 路径 | 职责 |
|---|---|
| `scripts/chrome_desktop_bridge.py` | **新建**。桌面侧唯一快速执行器：清遮挡、抢焦点、进页、当日筛选、横滑露推荐时间、详情采集、写 `collection_receipt.json` |
| `scripts/merchant_collector_executor.mjs` | 保留 Computer Use/`sky` 主路径；无 sky 时委托 bridge；预检/自测调用 bridge 能力；`executor` 字段仍为 `merchant-collector` |
| `scripts/wechat_sender_executor.py` | 固化主微信 chooser 选择（W1） |
| `references/workflow-contract.md` | 写入 D1–D7 / W1 军规 |
| `SKILL.md` | 标准流程改为：自测 → bridge/collector → 审计 → sender；明确禁止计时中临场脚本 |

## 执行器对外接口（计时用）

```bash
# 1) 离线自测
node scripts/merchant_collector_executor.mjs --self-test
python scripts/wechat_sender_executor.py --self-test
python scripts/chrome_desktop_bridge.py --self-test

# 2) 只读进页预检
node scripts/merchant_collector_executor.mjs --preflight-nav
# 或
python scripts/chrome_desktop_bridge.py --preflight-nav

# 3) 采集（无 Computer Use 时走 bridge）
python scripts/chrome_desktop_bridge.py --collect \
  --group "臻肆测试群" \
  --cursor-file .../cursor.test.json \
  --out /tmp/zhensi_agent_merchants/collection_receipt.json

# 4) 发送
python scripts/wechat_sender_executor.py --execute \
  --group "臻肆测试群" \
  --serial MGFNW19731004216 \
  --collection-receipt /tmp/zhensi_agent_merchants/collection_receipt.json \
  --standing-authorization "zhensi-test-main-wechat-merchant-v1"
```

## 非目标（本波不做）

- 不改生产游标路径与生产群。  
- 不开启 Chrome AppleScript JS。  
- 不把 Computer Use `sky` 路径删掉；有 sky 仍优先 AX。  
- 不在计时流程里再写临时 `/tmp` 采集脚本。

## 验收

1. `--self-test` 全绿（collector / bridge / sender）。  
2. `--preflight-nav` 在已登录会话下 `intentionListVisible=true`。  
3. bridge `--collect` 产出合法收据（`executor=merchant-collector`，四行消息与 sha256）。  
4. 合同与 SKILL 文案与上述接口一致。  
