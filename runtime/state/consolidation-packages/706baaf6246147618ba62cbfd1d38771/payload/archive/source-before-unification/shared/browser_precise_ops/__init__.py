"""browser_precise_ops — 引擎无关的浏览器精确操作加固模块.

移植自 Easel skills/shared/scripts（xhs_publish.py / douyin_publish.py / login_state.py /
content_guard.py）沉淀的工程纪律，去 Playwright/CDP 依赖，纯 stdlib，可被
zhensi_waimai_back 任意 Python/Node 采集器复用。

四大能力：
  - status_protocol : ① 登录/挑战长流程解耦成可轮询状态机（原子写 + 一次性码文件）
  - verify          : ② 成功校验 + 超时重试 wait_until（断言结果态而非只信动作返回）
  - pacing          : ③ 拟人节奏 + 反检测启动参数
  - content_guard   : ④ fail-closed 出站内容泄漏闸门（BLOCK 级拦发 / WARN 级告警）

本模块不进 executor-lock，改动它不影响 fail-closed 完整性门。
"""
from . import content_guard, pacing, status_protocol, verify

__all__ = ["content_guard", "pacing", "status_protocol", "verify"]
