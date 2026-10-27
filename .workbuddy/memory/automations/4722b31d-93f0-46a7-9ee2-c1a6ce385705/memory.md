# 监理环境复位（#8 前，15:00 档）— 执行记录

## 2026-10-04 14:55 (周日)
- 工位 9233 在线（Chrome/154.0.8037.95）。
- 关闭 imworkbench 旧页 1 个 → newPage → goto 工作台 URL（domcontentloaded）→ sleep 15s。
- 只读校验：body.innerText 长度 1065，含「未回复」✅ 与「待人工回复」✅ → **RESET_OK**。
- 未点击任何业务元素、未发消息、未改业务数据、未代跑 #8 业务流。
- 脚本：/tmp/mt_im_reset_9233.mjs（playwright-core 走 skills/posts/meituan-post/scripts/node_modules）。

## 2026-10-05 14:55 (周一)
- 工位 9233 在线（Chrome/154.0.8037.95）。
- 关闭 imworkbench 旧页 1 个 → newPage → goto 工作台 URL（domcontentloaded）→ sleep 15s。
- 只读校验：body.innerText 长度 1038，含「未回复」✅ 与「待人工回复」✅ → **RESET_OK**。
- 未点击任何业务元素、未发消息、未改业务数据、未代跑 #8 业务流。

## 2026-10-06 14:55 (周二)
- 工位 9233 在线（Chrome/154.0.8037.95）。
- 关闭 imworkbench 旧页 1 个 → newPage → goto 工作台 URL（domcontentloaded）→ sleep 15s。
- 只读校验：body.innerText 长度 1118，含「未回复」✅ 与「待人工回复」✅ → **RESET_OK**。
- 未点击任何业务元素、未发消息、未改业务数据、未代跑 #8 业务流。

## 2026-10-07 14:55 (周三)
- 工位 9233 在线（Chrome/154.0.8037.95）。
- 关闭 imworkbench 旧页 1 个 → newPage → goto 工作台 URL（domcontentloaded）→ sleep 15s。
- 只读校验：body.innerText 长度 1312，含「未回复」✅ 与「待人工回复」✅（待人工回复 10 条）→ **RESET_OK**。
- 未点击任何业务元素、未发消息、未改业务数据、未代跑 #8 业务流。

## 2026-10-08 14:55 (周四)
- 工位 9233 在线（Chrome/154.0.8037.98）。
- 关闭 imworkbench 旧页 1 个 → newPage → goto 工作台 URL（domcontentloaded）→ sleep 15s。
- 只读校验：body.innerText 长度 706，含「未回复」✅ 与「待人工回复」✅（待人工回复 6 条）→ **RESET_OK**。
- 未点击任何业务元素、未发消息、未改业务数据、未代跑 #8 业务流。

### 复用要点
- 判定成功只需 innerText 命中「未回复」或「待人工回复」任一，不依赖截图。
- 9233 不通时直接回报「9233 未在线，跳过」并结束，不重试、不做业务动作。
- 连续五日 RESET_OK；innerText 长度 706~1312 均属正常区间（随会话条数浮动），不作异常判据。
