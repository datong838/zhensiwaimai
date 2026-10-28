# System Events图片复制像素核验候选

当前原图片发送已一次提交，但AXCell不暴露AXImage，15s有界等待仍unknown。历史10/24的双次TIFF复制与源PNG像素完全一致证明像素核验可行，但其main依赖CUA且保存全部原剪贴板类型，均不复用；禁止开启CUA/屏幕共享、截图坐标、读取原用户剪贴板内容或凭据。

候选仅存work/native-image-copy-candidate-20261028，不改现役共享源码/摘要，13点正常排班优先。路径：native_image_copy_candidate.py、native_image_copy_candidate.jxa及test_native_image_copy_candidate.py。仅适用原owner仍活跃的既有send图片任务，原claim/send-intent与绑定/source SHA/size一致、发送后原消息条数新增，目标群/空框/同一新尾行绑定。不创建新发送意图、不填字、不按发送/回车、不重发。

原worker持原UI租约时才调用：System Events选中该确切AXCell，读取原编辑→复制菜单C/修饰0与enabled属性，通过后仅点击可见菜单复制，不试探控制键。不激活抢回用户焦点，失焦或菜单不可用就保持pending。每帧先写随机文本nonce（不读取/备份原剪贴板数据），记录changeCount，原可见复制后只读取允许的PNG/TIFF数据，要求changeCount增长、源宽高/RGBA SHA完全一致。两帧来自同一消息行，期间群/空框/owner/源字节不变，才形成content proof；不是靠图标/新空白行/时间verified。拒绝文件卡文字与会议图标替代。实际证明不足仍unknown，不放宽门禁。

候选以依赖注入单测验证新鲜性、错图、错群、旧剪贴板、失焦、行变化、owner退出、文件漂移均失败；不启动候选实际UI操作。正式接入仍必须原共享受控授权/全回归/全部消费者摘要同步/原真实图片验收。不得把离线通过视作已上线或内容已验证；旧marker不回写、未来只读stage另立原协议后才能核验历史图。

## 原worker驱动补齐

新增同目录 `native_image_copy_driver.py` 和 `test_native_image_copy_driver.py`。驱动没有CLI，构造不触碰UI或剪贴板；原worker在同一发送任务尚未写response时传入原队列目录。每次动作前复核原task完整绑定、目录taskId、owner-process、原claim worker及send-intent三项身份；已有response一律拒绝，不能借活owner回读旧任务。原UI树仅浅层读取当前尾行与精确标题/空框，文件卡文字不作为图片候选。复制继续调用候选JXA，禁止激活或按键。

剪贴板驱动惰性加载AppKit，先清空并写nonce后才可发出原生复制；仅复制确认后且changeCount增长才读取PNG/TIFF，读取前后count不变才交像素比较，不读取原文字/旧类型列表、不保存原剪贴板。构造与隔离单测不调用真实UI。此批只补候选驱动，不修改共享摘要、生产任务、发送器或旧证据。正式接入仍待原worker受控安装和真实一次图片验收。

候选接入函数放同目录 `native_image_copy_hook.py`：原15秒观察成功直接复用；仅捕获原 `NativeImageObservationPending` 的精确内容未暴露原因，且冻结异常内原候选message_path后才进入复制。后续每帧必须仍是此路径，不允许观察期结束后改绑另一条新消息。无新行、群/草稿变化、owner退出及其他异常不触发复制。新增hook单测及原发送器内存接入回归，不改磁盘现役发送器或摘要。

原nativeDispatch在 `wecom_adapter.session` 的 `wecom-transport.lock` 内同步调用，task.owner.pid即当前发送Python进程。候选进一步硬核对owner.pid必须等于本驱动进程PID，活着的别的进程也不能借原任务复制；无CLI，不另起worker、不抢原锁。真实接入仅允许此同步原调用栈，不给历史任务开放外部诊断入口。

## 正式安装范围与顺序

正式模块为 `skills/wechat-messaging/scripts/native_image_content.py`、`native_image_content_driver.py`、`native_image_content_hook.py`、`native_image_content.jxa`；原 `native_ui_post.py` 只增加hook导入并在既有唯一提交之后调用hook。安装前先在 `runtime/state/native-image-content-install-20261028/stage/` 形成同名候选，核对原完整共享回归与候选测试。

受控维护另涉及 `skills/wechat-messaging/scripts/dependency_maintenance.py` 的精确路径/候选SHA授权及新模块摘要登记、共享 `dependencies.json`，原商家 `executor-lock.json`、Top10 `runtime-policy.json`、差评 `dependencies.json`/`runtime-policy.json` 的原维护同步。授权引用用户要求修复每天图片unknown及全部非登录阻碍；不沿用旧授权的候选字节，不修改业务授权/群/日期/防重事实。所有原文件先保存SHA与字节，任何步骤失败立即恢复本批代码与摘要/消费者policy原字节并核对clean，不启动生产补跑。

安装仅空闲窗口且留足下一新商家档时间；如不能在13:30前完成全部消费者原门核验则推迟到该档真实送达之后，不让部分安装跨过排班。共享维护器完整测试、capabilities与clean回读后，经原消费者维护入口同步；原发送事实/游标/旧unknown保持。真实验收只随下一原主任图片任务发生，不创建测试消息、不重发当日旧图。

13:34首轮安装已完整回滚：共享459测试及商家SEALED同步通过，但差评通用重验入口按原当前提交范围拒绝，不能用通用重验绕过原unknown。后续只扩展现有窄 `refresh-public-dependency` 入口：文件 `skills/workflows/daily-negative-reviews/scripts/maintenance_executor.mjs` 与 `test_public_dependency_resync.mjs`，增加本次固定共享维护收据SHA、6个精确变更路径及各自after SHA；保留旧分支、业务日期/status/验收事实/5个业务文件SHA，不能重新验收已提交载荷。输出目录改为收据SHA后缀的新独立目录，避免覆盖旧维护证据。重新安装时将这两个维护文件纳入原字节备份，任一步失败仍全部回滚。

## 实施结果

13:38第二轮安装完成。共享完整459测试与capabilities通过，维护器inspect为clean（38个登记文件）；商家原148测试及19文件SEALED门通过，Top10原14测试/8文件门通过；差评窄同步原24+新增8测试及原8组回归通过，原allowedBusinessDate/status不变、5个业务文件SHA不变、acceptedNewDelivery=false。8份消费者policy无漂移，0199ccb39630原unknown MD SHA不变。JXA编译通过，真实复制次数0、额外发送0，仍待下一原主任正常图片任务实证。

证据均在 `runtime/state/native-image-content-install-20261028/`：首轮 `rollback-receipt.json`、第二轮 `shared-install-2/receipt.json`、`merchant-sync-2/maintenance-receipt.json`、`top10-sync-2.json`、`negative-public-output.json` 和 `final-audit.json`。不把隔离测试或安装成功写成真实图片验收完成。
