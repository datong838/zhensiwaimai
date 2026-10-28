# System Events图片复制像素核验候选

当前原图片发送已一次提交，但AXCell不暴露AXImage，15s有界等待仍unknown。历史10/24的双次TIFF复制与源PNG像素完全一致证明像素核验可行，但其main依赖CUA且保存全部原剪贴板类型，均不复用；禁止开启CUA/屏幕共享、截图坐标、读取原用户剪贴板内容或凭据。

候选仅存work/native-image-copy-candidate-20261028，不改现役共享源码/摘要，13点正常排班优先。路径：native_image_copy_candidate.py、native_image_copy_candidate.jxa及test_native_image_copy_candidate.py。仅适用原owner仍活跃的既有send图片任务，原claim/send-intent与绑定/source SHA/size一致、发送后原消息条数新增，目标群/空框/同一新尾行绑定。不创建新发送意图、不填字、不按发送/回车、不重发。

原worker持原UI租约时才调用：System Events选中该确切AXCell，读取原编辑→复制菜单C/修饰0与enabled属性，通过后仅点击可见菜单复制，不试探控制键。不激活抢回用户焦点，失焦或菜单不可用就保持pending。每帧先写随机文本nonce（不读取/备份原剪贴板数据），记录changeCount，原可见复制后只读取允许的PNG/TIFF数据，要求changeCount增长、源宽高/RGBA SHA完全一致。两帧来自同一消息行，期间群/空框/owner/源字节不变，才形成content proof；不是靠图标/新空白行/时间verified。拒绝文件卡文字与会议图标替代。实际证明不足仍unknown，不放宽门禁。

候选以依赖注入单测验证新鲜性、错图、错群、旧剪贴板、失焦、行变化、owner退出、文件漂移均失败；不启动候选实际UI操作。正式接入仍必须原共享受控授权/全回归/全部消费者摘要同步/原真实图片验收。不得把离线通过视作已上线或内容已验证；旧marker不回写、未来只读stage另立原协议后才能核验历史图。

## 原worker驱动补齐

新增同目录 `native_image_copy_driver.py` 和 `test_native_image_copy_driver.py`。驱动没有CLI，构造不触碰UI或剪贴板；原worker在同一发送任务尚未写response时传入原队列目录。每次动作前复核原task完整绑定、目录taskId、owner-process、原claim worker及send-intent三项身份；已有response一律拒绝，不能借活owner回读旧任务。原UI树仅浅层读取当前尾行与精确标题/空框，文件卡文字不作为图片候选。复制继续调用候选JXA，禁止激活或按键。

剪贴板驱动惰性加载AppKit，先清空并写nonce后才可发出原生复制；仅复制确认后且changeCount增长才读取PNG/TIFF，读取前后count不变才交像素比较，不读取原文字/旧类型列表、不保存原剪贴板。构造与隔离单测不调用真实UI。此批只补候选驱动，不修改共享摘要、生产任务、发送器或旧证据。正式接入仍待原worker受控安装和真实一次图片验收。
