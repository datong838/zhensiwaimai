# 美团无头迁移验证记录

状态：HEADLESS_STARTED_PAGE_UNVERIFIED。此前可见模式的接管验证不能沿用为无头成功证据。

用户明确要求切换无头并重新验证登录；已退出已验收的 visible-handoff PID 11818，使用原 profile meituan-merchant、原端口 9233、restore-last-session 启动 headless PID 16649。新任务页为 meituan-headless-20260913-01。

两次页面验证返回 FRAME_ORIGIN_UNVERIFIED 后停止认证重试。限定目标只读诊断证明该 frame 为屏幕下方 about:blank（框架 y=596，高150；视口高596），修复了可见性判断。主页面正文长度仍为 0，document.readyState=complete，仅有页面标题“美团外卖商家版”；既没有可验收的商家首页，也未发现足以判定需要重登的登录页。不把白屏解释为账号掉线，不把资源跨站 responseStatus=0 解释为加载失败。未关闭未知页面、未绕过验证码、未复制凭证。

代码改动为 scripts/run_task.mjs 复用共享美团观察器、增加限定目标只读 diagnose；scripts/handoff.mjs 修复视口外框架判断，并补充测试。累计21项测试全部通过，0失败、0跳过；这仅证明代码与本机隔离流程，不能替代真实网站验收。

当前保留无头进程和原 profile。该步未完成真实登录验收，不标记“稳定无头接管”。下一步应对真实白屏进行有界诊断；不得用历史可见页面、连接正常或测试通过充当登录证据。
