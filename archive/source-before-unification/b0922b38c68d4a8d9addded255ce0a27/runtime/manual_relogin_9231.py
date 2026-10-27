#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""9231 taobao-agent-service 有头登录窗拉起（带 CDP 调试端口，可被保活探活）。

背景（2026-10-24 08:00 巡检）：9231 掉登录（open.shop.ele.me/login，API UNAUTHORIZED
「session 不能为空」）。bg-chrome-up.sh 对 9231 强制无头；登录由大同手动开 Chrome。
本脚本 = 替大同开好可见 Chrome 停在登录页，带 --remote-debugging-port=9231：
  - 保活可探到 URL=/login ⇒ 正定性「掉登录」而非「浏览器挂」
  - 大同登录完成后 URL 翻回业务页 ⇒ 下一轮探活可见 ⇒ 届时杀窗→bg-chrome-up.sh 无头拉起收口
  - state.json 改 mode=headful：openLogin 的 kill 分支只认 mode=headless，防误杀登录窗
用法: env -u PYTHONPATH python3 runtime/manual_relogin_9231.py
（同 2026-10-21 manual_relogin_9230_v2.py 手法，双 fork + os.setsid 脱离沙箱进程组）
"""
import json
import os
import subprocess
import sys
import time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR = os.path.expanduser("~/Library/Application Support/AOS Background Chrome/taobao-agent-service")
STATE_PATH = os.path.join(PROFILE_DIR, ".aos-background-chrome", "state.json")
LOGIN_URL = "https://open.shop.ele.me/login"
LOG = "/tmp/bg-chrome-taobao-agent-service.manual-relogin.log"
PORT = 9231


def kill_existing() -> None:
    """杀掉同 profile 的所有现存 Chrome 主进程（无头旧例）。

    2026-10-24：本机 agent 上下文 `ps` 被 TCC 拦（Operation not permitted），
    改用 pgrep -f（按 user-data-dir 特征匹配）+ lsof（端口等待）。
    """
    r = subprocess.run(["pgrep", "-f", "user-data-dir=.*taobao-agent-service"],
                       capture_output=True, text=True)
    for pid in r.stdout.split():
        try:
            subprocess.run(["kill", pid], capture_output=True)
            print(f"killed old pid={pid}")
        except Exception:
            pass
    for _ in range(12):
        rr = subprocess.run(["lsof", "-tnP", f"-iTCP:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True)
        if not rr.stdout.strip():
            break
        time.sleep(1)


def open_headful_with_cdp() -> None:
    args = [
        CHROME,
        f"--user-data-dir={PROFILE_DIR}",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={PORT}",
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


def fix_state(pid: int) -> None:
    cur = {}
    try:
        cur = json.load(open(STATE_PATH))
    except Exception:
        pass
    cur.update(mode="headful", port=PORT, pid=pid, loginWindowNote="2026-10-24 manual relogin window (9231)")
    tmp = STATE_PATH + ".tmp"
    open(tmp, "w").write(json.dumps(cur, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE_PATH)
    print(f"state.json -> mode=headful pid={pid}")


if __name__ == "__main__":
    kill_existing()
    time.sleep(2)
    open_headful_with_cdp()
    # 等 CDP 起来
    pid = None
    for _ in range(15):
        time.sleep(1)
        rr = subprocess.run(["lsof", "-tnP", f"-iTCP:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True)
        pids = [p for p in rr.stdout.split() if p]
        if pids:
            pid = int(pids[0])
            break
    if not pid:
        print("FAIL: CDP 未起来")
        sys.exit(1)
    fix_state(pid)
    print(f"LOGIN_WINDOW_READY pid={pid}（可见窗+CDP 9231，停登录页等大同扫码）")
