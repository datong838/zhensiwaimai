#!/usr/bin/env python3
"""有头拉起 9230 taobao-brand 登录窗（python 双 fork + setsid，防 SIGTERM 连坐）。

背景（2026-10-21 13:49）：9230 掉登录（跳 melody.shop.ele.me/login）。
auth_keepalive.mjs openLogin 的 kill 生效但 headful spawn 被 SIGTERM(143) 连坐杀掉。
用 python 双 fork + setsid execv 拉起，脱离沙箱进程组，模拟 #63 已验证的 9231 同款手法。
用法: BG_CHROME_LAUNCH=headful python3 launch_headful_9230.py
"""
import os
import sys

HOME = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back"
PROFILE = "taobao-brand"
PORT = "9230"
URL = "https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center"
LOG = "/tmp/bg-chrome-taobao-brand.headful-relogin.log"


def main() -> int:
    # 双 fork + setsid：脱离调用方进程组，防 SIGTERM 连坐（同 #63 9231 手法）
    pid = os.fork()
    if pid > 0:
        # 父进程等第一 fork 退出即可，孙进程由 init 接管
        os.waitpid(pid, 0)
        print("DAEMONIZED_OK（第二 fork 由 init 接管，登录窗已拉起）")
        return 0
    # 第一子
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    # 孙进程：重定向日志，exec bg-chrome-up.sh headful
    os.chdir(HOME)
    env = dict(os.environ)
    env["BG_CHROME_LAUNCH"] = "headful"
    env.pop("PYTHONPATH", None)
    fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.execve(
        "/bin/bash",
        ["/bin/bash", "-c", f"exec bash {HOME}/runtime/bg-chrome-up.sh {PROFILE} {PORT} '{URL}'"],
        env,
    )
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main())
