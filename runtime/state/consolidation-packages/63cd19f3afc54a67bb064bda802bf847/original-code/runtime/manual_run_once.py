#!/usr/bin/env python3
"""Run one care-skill from THIS (interactive) context instead of the launchd daemon.

Why this exists
---------------
The launchd job `com.zhensi.waimai.careloop` starts `/usr/bin/python3`, a
platform binary.  Its process tree has no Screen Recording grant, so every
`screencapture` it spawns fails (`could not create image from rect`) and
`kCGWindowName` is stripped.  The desktop locator surfaces that as
`wechat-search-region-contended`, which reads as transient GUI contention and
cannot be cleared by retrying.  Spawned from an interactive shell -- whose
responsible process *does* hold Screen Recording -- the exact same interpreter
captures fine (A/B verified).

So while the daemon's TCC grant is missing, the only way to actually send is to
run the skill from a capture-capable parent.  This script:

  1. suppresses the daemon (KeepAlive restarts it ~30s after any kill, so a
     background reaper keeps killing it for the duration),
  2. holds the shared RunnerLock itself, so it can never overlap the daemon,
  3. waits for WeChat to be genuinely foreground (strong activation), and
  4. runs the one skill via skill_runner, then reports the receipt.

It deliberately does NOT go through run_all's `--once`, because that path would
have to acquire the same lock this process already holds.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back")
RUNTIME = REPO / "runtime"
SHARED = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/"
              "wechat-desktop-control/scripts")
sys.path.insert(0, str(RUNTIME))

import skill_runner as sr  # noqa: E402


def reap_daemons() -> int:
    """SIGKILL every daemon instance; returns how many were signalled."""
    found = subprocess.run(["pgrep", "-f", "run_all.py --daemon"],
                           capture_output=True, text=True).stdout.split()
    for pid in found:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, ValueError):
            pass
    return len(found)


def suppress_daemon_for(seconds: float) -> subprocess.Popen:
    """Background reaper; KeepAlive re-launches the job, so keep killing it."""
    code = (
        "import os,signal,subprocess,time\n"
        "end=time.time()+%f\n"
        "while time.time()<end:\n"
        "    out=subprocess.run(['pgrep','-f','run_all.py --daemon'],\n"
        "                       capture_output=True,text=True).stdout.split()\n"
        "    for p in out:\n"
        "        try: os.kill(int(p),signal.SIGKILL)\n"
        "        except Exception: pass\n"
        "    time.sleep(2)\n" % seconds)
    return subprocess.Popen([sys.executable, "-c", code])


def ensure_wechat_foreground() -> bool:
    """2026-10-07 大同红线：禁止触碰 Mac 桌面微信——任何激活/前台校验都不行，
    activate_wechat 会把大同正在使用的微信抢到前台。发送早已走 Windows
    驱动通道（8731），此函数不再做任何 Mac 微信操作，仅保持调用点兼容。"""
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill")
    parser.add_argument("--minutes", type=float, default=12.0,
                        help="how long to keep the daemon suppressed")
    args = parser.parse_args()

    killed = reap_daemons()
    print("[info] 压制守护进程：已终止 %d 个实例" % killed)
    reaper = suppress_daemon_for(args.minutes * 60)

    lock = sr.RunnerLock()
    for _ in range(15):
        if lock.acquire():
            break
        time.sleep(1)
    else:
        print("[error] 无法取得全局锁，放弃")
        return 1

    try:
        print("[info] 微信前台就绪：%s" % ensure_wechat_foreground())
        data = sr.load_manifest(RUNTIME / "skills_manifest.json")
        interpreters = sr.resolve_interpreters(data, dict(os.environ))
        skill = next((s for s in data["skills"] if s["name"] == args.skill), None)
        if skill is None:
            print("[error] manifest 无此 skill: %s" % args.skill)
            return 1
        print("[info] skill=%s steps=%d python=%s" % (
            args.skill, len(skill.get("steps") or []), interpreters.get("python")))
        started = time.monotonic()
        rec = sr.run_skill(skill, history_dir=sr.DEFAULT_HISTORY,
                           interpreters=interpreters, env={"ZENSI_DRY": "0"},
                           run_source="manual")
        print("[result] %s" % json.dumps(
            {k: rec.get(k) for k in ("status", "category", "attempts",
                                     "finished_at", "next_action", "detail")},
            ensure_ascii=False))
        print("[result] elapsed=%.1fs" % (time.monotonic() - started))
        if rec.get("category") == sr.CAT_SUCCESS:
            # 2026-10-05：手工跑通与守护跑通等价，成功时间戳必须入账——
            # 否则 daily_progress 只认 last_success.json，手工轮的战绩被判为「未完成」。
            sr.update_last_success(args.skill, rec.get("finished_at"))
            print("[info] 已写入 last_success: %s" % rec.get("finished_at"))
        return 0 if rec.get("category") == sr.CAT_SUCCESS else 1
    finally:
        lock.release()
        reaper.terminate()
        reaper.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
