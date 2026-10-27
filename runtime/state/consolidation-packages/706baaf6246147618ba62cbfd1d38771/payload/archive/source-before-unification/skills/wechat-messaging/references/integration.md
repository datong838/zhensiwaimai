# 优势来源与接入边界

| 来源 | 整合内容 | 当前落点 |
|---|---|---|
| 公共wechat-desktop-control | AX群快路径、唯一搜索、主窗抬升、窗口ID截图、直接输入、单次物理发送、交互锁 | desktop_adapter运行时复用，dependencies.json锁定 |
| 新增商家 | 全文原生复制、双帧稳定、滚动先抬窗、AX剪枝避免消息列表滚动、未知只读复核 | desktop_text_readback独立抽取；无商家模块依赖 |
| Top10 | 原图身份、内容指纹、稳定帧、未知不补发 | evidence、desktop_adapter图像内容验证；手机原图/大图步骤列入恢复规程待迁移 |
| 金鲨日报/隐藏底座 | 全文件名、显示大小、上传状态、防重、部分完成 | evidence文件证明、executor逐项结果；保留旧业务账本 |
| 淘宝下载上传 | 完整批次来源/顺序/哈希、授权绑定、有限抢占等待、阶段复盘 | contract/executor统一运行时；上传完成业务合同仍由原业务负责 |

不移植旧代码中的弱行为：unknown重发、按文件名前缀认定成功、OCR少一行仍通过、任意授权字符串、全局Al/AI替换、清掉未知草稿、用截图相似冒充原文。

业务接入只构造request，绑定已通过自身来源/日期/群名限制的授权，调用唯一executor并按verified收据提交自己的业务状态。不要直接调用desktop_adapter或公开底层发送器来绕过运行策略。

2026-09-16 四条生产业务的桌面发送与预检已接入本技能，业务总入口、线上群、历史及游标不变。商家封板不自动更新；离线迁移不冒充真实非空验收。

统一技能源目录为 `/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging`，可通过 `~/.codex/skills/wechat-messaging` 的符号链接发现。不复制第二套源文件。


## 手机通用模块来源与边界（2026-09-16）

mobile_helpers.py提取daily-top10-to-wechat-group/scripts/phone_executor.py的OCR、图像内容、导航原语；移除业务日期、1500像素、固定Top10字段和业务授权限制。mobile_text.py提取daily-agent-new-merchants-to-wechat/scripts/wechat_sender_executor.py的主实例定位及发送前后原生复制；移除商家收集、生产历史/游标及业务账本。mobile_files.py提取.daily-jinsha-reports-core/scripts/wechat_file_sender.py的系统文件选择原语，目录替换为wechat_messaging，移除旧业务发送与重试状态机。

mobile_adapter.py统一设备绑定、u0检查、事件attempt、三类发送、输入法恢复与失败证据；executor.py新增mobile路由。两个本机OCR二进制仍通过绝对路径和哈希作为只读依赖，未修改源业务文件。实际三类成功和缺口见mobile-acceptance.md。

## 桌面工作流桥接合同

| workflow-id | 原业务 | 群 | 对象 |
|---|---|---|---|
| merchants | 新增商家 | 电销+直播攻坚组 | 每商家1条文字 |
| top10 | 昨日Top10 | FEIBING NEO AI数字员工 | 1张图 |
| taobao-evidence | 淘宝下载上传金鲨 | FEIBING NEO AI数字员工 | 2张图，门店后评价 |
| jinsha-reports | 金鲨业务日报 | 上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰 | 2个文件 |
| negative-reviews | 昨日差评分析 | 上海臻肆外卖运营-盯个盯-饭敢当（搜索忽略头像、图标和后续装饰符号） | 1个Excel文件 |
| meituan-waimai-appeals | 美团外卖差评申诉日报 | FEIBING NEO AI数字员工 | 1个Excel文件 |

workflow_bridge.py校验注册身份、群、数量、类型、原授权、固定账本目录；taobao-evidence额外绑定昨日、固定截图目录/名称/顺序和逐字授权。来源/成品合同继续由业务总入口检查。桥接门禁独立于runtime-policy.json的单次测试策略，不将测试群或测试授权带入生产。

2026-09-23 经用户明确授权，新增 `meituan-waimai-appeals`：只接受上海时区昨日的 `美团外卖差评申诉汇总-YYYY-MM-DD.xlsx`，文件必须在当日固定输出目录，且事件标记必须与业务日期一致；投递至 `FEIBING NEO AI数字员工`，使用独立账本。该入口复用淘宝闪购差评日报已验证的桥接和桌面文件回读，不新增微信操作分支。

旧marker绝对路径作为eventId，通用事件账本在旧ledger/.wechat-messaging；独占迁移锁加上排他创建旧marker防止旧新入口并发双发。旧verified必须内容/名字/大小/顺序完全匹配；旧unknown只允许文字原生复制复核，文件/图片缺少证据时保持阻断。新桥unknown进入通用reconcile，不补发；仅明确blocked且sendAttempts=0才能重查群尝试。两个附件逐项发送，任意未verified整批不提交。桥接回写原marker供旧业务恢复器识别，保留commonReceipt逐项证据和耗时；商家再验证完整正文证据后才提交历史/游标。

隐藏金鲨底座、历史手机业务脚本、企业微信下载/巡店不迁移。商家executor-lock.json仍为UNSEALED_ACCEPTANCE，旧验收记录未改；本次新增依赖应随新的非空验收纳入封板。Top10路径校验与淘宝代码摘要更新为新桥，公共底层桌面代码未改。

2026-09-17用户以核心文字 `上海臻肆外卖运营-盯个盯-饭敢当` 指定运营群；只读AX解析出的当前唯一完整标题为 `上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰`，生产注册绑定该完整标题。该注册项使用独立授权与独立旧marker目录；Top10和淘宝证据仍保留原群。群定位只按文字唯一命中和标题复核，不读取头像。

2026-09-18昨日差评分析新增独立 `negative-reviews` 注册项。入口只接受该运营群、单个 `差评分析数据_YYYY-MM-DD_YYYY-MM-DD.xlsx`，且文件必须位于对应的 `outputs/yesterday-negative-YYYYMMDD/` 目录；使用独立授权与独立账本。定位时以核心群名搜索唯一文字结果，忽略头像、图标和后续装饰符号，打开后由当前完整标题和群人数复核群身份。

### 迁移验证

9组293项离线回归通过（通用82、商家70、Top10 22、金鲨桌面5、淘宝入口20、金鲨工作流24、金鲨策略32、Top10浏览器12、商家浏览器26）。收据位于 `.runtime/workflow-migration/offline-regression.json`。本轮没有线上发送；新桥尚无四条生产整链真实验收。Top10已改为在动作前验证通用完整依赖，不再保留重复过期的locator摘要。商家完整性文件集合已增加通用桥/预检/依赖清单，生产锁不重写、原UNSEALED_ACCEPTANCE状态不提升。
