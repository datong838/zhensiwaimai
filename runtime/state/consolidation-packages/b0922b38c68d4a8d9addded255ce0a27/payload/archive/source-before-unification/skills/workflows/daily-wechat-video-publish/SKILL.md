---
name: daily-wechat-video-publish
description: 从已登录的 Mac 企业微信中，按运行时企业和群参数精确发现、下载并隔离归档 MP4；人工检查后准备文案，再发布到抖音、快手和微信视频号。适用于业务企业微信已有内部群或外部群的视频发布流程，不用于普通微信、任意缓存最新文件或未授权的会话采集。
---

# 企业微信群视频 → 三平台发布

## 开始前

先读 [企业微信群视频下载技术方案](references/20260908-企业微信群视频下载技术方案.md)。发布阶段再读 [快手与视频号发布方案](references/20260907-快手与视频号发布方案.md)。

- 企业微信 Mac 客户端已由人工登录；执行器只连接现有会话，不接收或保存账号密码。
- `enterprise` 和 `group` 必须由本轮参数传入。当前实操参数是上海臻肆文化传播有限公司和红太阳鱼杂王蜀川湘菜店抖音发视频。
- Chrome 已登录抖音创作者中心、快手创作者中心和微信视频号助手。
- macOS 已授予辅助功能和屏幕录制权限。

## 固定工作流

```bash
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-wechat-video-publish/scripts

# 1. 初始化
python3 workflow_executor.py \
  --enterprise '上海臻肆文化传播有限公司' \
  --enterprise-marker '上海臻肆文化传播有限公司' \
  --group '红太阳鱼杂王蜀川湘菜店抖音发视频' \
  --sender '略略略@微信' \
  init

# 2. 预检并扫描
python3 workflow_executor.py --run-id <run_id> scan

# 3. 只下载第 2 步确认的精确文件
python3 workflow_executor.py --run-id <run_id> download

# 4. 强制暂停，由人工逐个检查视频内容

# 5. 人工确认后准备发布计划
python3 workflow_executor.py --run-id <run_id> prepare --confirm-reviewed

# 6. 发前校对作品描述；得到发布授权后才加 --confirm-publish
python3 workflow_executor.py --run-id <run_id> publish --platform all
python3 workflow_executor.py --run-id <run_id> publish --platform all --confirm-publish
```

映射表中没有目标群时，在 `init` 增加 `--shop` 和 `--address`。若同一天不同企业或群产生相同 `run_id`，后续命令同时传 `--enterprise` 与 `--group` 消歧。

## 数据隔离

| 路径 | 用途 |
|---|---|
| `/Users/ddt/work/臻肆/视频/runs/<enterprise_key>/<group_key>/<run_id>/` | 本轮视频、证据和回执 |
| `/Users/ddt/work/臻肆/视频/state/<enterprise_key>/<group_key>/` | 企业和群维度的游标、去重状态 |
| `/Users/ddt/work/臻肆/视频/微信群-店铺名-店铺地址.xlsx` | 兼容现有群到店铺、地址映射 |

不得把一个企业的窗口元素、缓存路径、游标或去重结果用于另一个企业。

## 下载硬门

- 当前企业标识和聊天标题必须与参数相符。
- 文件附件只接受聊天辅助功能树中完整出现的 `.mp4` 文件名及界面大小。
- 无文件名原生视频必须按目标发送人、消息时间、时长和消息行冻结候选，并用当前企业 Profile、缓存时间窗、候选数量及完整时长集合整批绑定。
- 禁止按缓存修改时间选择“最新 MP4”，禁止写死企业微信 Profile 哈希。
- 同名同大小文件若出现不同内容，状态为 `download_unknown`，停止处理。
- 文件大小稳定、MP4 容器头可读并生成 SHA-256 后，才进入 `human_review_pending`。
- 实际数量必须等于 `expected-count`。数量不足或过多都不算完成。
- 结果未知的下载动作不自动重做。

桌面附件列表无法稳定提供发送人或逐条消息时间时，不得假装已经按这些字段筛选。需要严格的发送人、时间和持续增量能力时，按技术方案接入企业微信会话内容存档。

## 内容与发布硬门

- 下载后必须暂停人工检查。未检查的视频不得进入发布计划。
- OCR 只生成文案草稿。主题无法确认时保留视频并标记 `review_required`，禁止发布，不删除源文件。
- 发布前对照封面或平台预览校对作品描述，纠正 OCR 错字。
- 每个视频只提取、校对一次作品描述并写入 `publish-plan.json`；三个平台共同读取同一 `caption` 和 `captionVersion`，平台循环中禁止重新 OCR 或重新生成。
- 发布页只填作品描述和位置，保持平台默认封面。
- `publish_unknown`、`download_unknown`、`review_required` 不自动重试或发布。
- 登录失效、验证码或风控立即停止。

## 三个平台

| 平台 | 执行器 | 发布后回读 |
|---|---|---|
| 抖音 | `douyin_chrome_bridge.py` | 内容管理页 |
| 快手 | `kuaishou_chrome_bridge.py` | 作品管理页 |
| 微信视频号 | `channels_chrome_bridge.py` | 动态管理页 |

小红书尚未接入本技能。
