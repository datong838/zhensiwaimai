#!/usr/bin/env python3
"""9230 taobao-brand 有头登录窗拉起（不经 bg-chrome-up.sh，尊重 10-16 大同指示）。

背景（2026-10-21 13:5x）：9230 掉登录（melody.shop.ele.me/login，ksid/token TTL 到期）。
bg-chrome-up.sh 对 taobao-brand 强制无头（2026-10-16 大同指示），登录场景由大同手动开 Chrome。
本脚本 = 替大同把 Chrome 开好停在登录页：直接 exec Chrome 二进制（同 profile user-data-dir），
双 fork + setsid 防沙箱 SIGTERM 连坐，不写 state.json、不动 bg-chrome-up 体系。
前置：先杀当前无头实例（同 profile Singleton 锁互斥）。
用法: kill_headless_and_open.py  （内部完成杀无头 + 拉有头）
"""
import os
import subprocess
import sys
import time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR = os.path.expanduser("~/Library/Application Support/AOS Background Chrome/taobao-brand")
LOGIN_URL = "https://melody.shop.ele.me/login"
LOG = "/tmp/bg-chrome-taobao-brand.manual-relogin.log"
PORT = "9230"


def kill_headless() -> None:
    # 权威 pid：state.json + lsof 双源
    try:
        import json
        sp = os.path.join(PROFILE_DIR, ".aos-background-chrome", "state.json")
        st = json.load(open(sp))
        if st.get("pid"):
            subprocess.run(["kill", str(st["pid"])], capture_output=True)
    except Exception:
        pass
    for _ in range(12):
        r = subprocess.run(["lsof", "-tnP", f"-iTCP:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True)
        pids = [p for p in r.stdout.split() if p]
        if not pids:
            break
        for p in pids:
            subprocess.run(["kill", p], capture_output=True)
        time.sleep(1)


def open_headful() -> None:
    args = [
        CHROME,
        f"--user-data-dir={PROFILE_DIR}",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,760",
        LOGIN_URL,
    ]
    if os.fork() == 0:
        os.setsid()
        if os.fork() == 0:
            fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.dup2(fd, 1)
            os.dup2(fd, 2)
            os.execv(CHROME, args)
            os._exit(1)
        os._exit(0)


if __name__ == "__main__":
    kill_headless()
    time.sleep(2)
    open_headful()
    time.sleep(6)
    r = subprocess.run(["lsof", "-tnP", f"-iTCP:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True)
    pids = [p for p in r.stdout.split() if p]
    print(f"LOGIN_WINDOW_READY pids={pids}（可见窗口已开，停登录页等大同扫码）")
    sys.exit(0 if pids else 1)
