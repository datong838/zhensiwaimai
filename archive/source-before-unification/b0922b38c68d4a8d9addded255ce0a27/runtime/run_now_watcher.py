#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_now_watcher · 大同 2026-10-23 新规：补跑按当前时间，不准等周期。

每分钟（launchd StartInterval=60）扫描 runtime/state/control.json：
- 有 "force_run_now": [<skill>, ...] → 原子摘除该键 → 逐个 run_all.py --once <skill>
  （run_all 自带与 daemon 的互斥锁；锁被占/启动失败则降级写回 force_run，
  由 daemon 下一周期采纳，任务绝不静默丢失）。
- 其余键（force_run / reset_circuit）原样保留，归 daemon 周期逻辑消费。

设计边界（监理不下场铁律）：本 watcher 是"机制"，监理只写 control.json；
真正执行的是 run_all.py 封装的 skill 原入口，安全门零改动。

用法：
  python3 run_now_watcher.py             # 常规单次扫描（launchd 调度）
  python3 run_now_watcher.py --selftest  # 纯逻辑自测（不真跑任何 skill）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONTROL_FILE = REPO / "runtime" / "state" / "control.json"
LOG_FILE = REPO / "runtime" / "logs" / "run_now_watcher.log"
RUN_ALL = REPO / "runtime" / "run_all.py"
PYTHON = sys.executable

# UI delivery follows the original live process; elapsed time is not a failure.
ONCE_TIMEOUT_SECONDS = None


def log(msg: str) -> None:
    """append-only 日志（#64：追加用 >> 语义，open mode 'a'）。"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg))


def read_control() -> dict:
    try:
        return json.loads(CONTROL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_control_remove_key(key: str) -> None:
    """原子摘除一个键，其余键保留。文件不存在或无该键则 no-op。"""
    data = read_control()
    if key not in data:
        return
    data.pop(key, None)
    tmp = CONTROL_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONTROL_FILE)


def downgrade_to_force_run(names: list) -> None:
    """--once 失败（互斥锁占用/启动失败）→ 降级写回 force_run，防任务丢失。"""
    data = read_control()
    existing = data.get("force_run", [])
    if isinstance(existing, str):
        existing = [existing]
    merged = list(dict.fromkeys(list(existing) + list(names)))
    data["force_run"] = merged
    tmp = CONTROL_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONTROL_FILE)


def pop_now_names() -> list:
    """原子摘取 force_run_now 列表；无则空列表。"""
    data = read_control()
    raw = data.get("force_run_now")
    if not raw:
        return []
    names = [raw] if isinstance(raw, str) else list(raw)
    write_control_remove_key("force_run_now")
    return names


def run_once(name: str) -> bool:
    log("once-start %s" % name)
    try:
        proc = subprocess.run(
            [PYTHON, str(RUN_ALL), "--once", name],
            capture_output=True, text=True, timeout=ONCE_TIMEOUT_SECONDS,
            cwd=str(REPO),
        )
    except subprocess.TimeoutExpired:
        log("once-timeout %s (>=%ss) -> downgrade" % (name, ONCE_TIMEOUT_SECONDS))
        return False
    tail = (proc.stdout or "").strip().splitlines()
    log("once-end %s rc=%s last=%s" % (name, proc.returncode,
                                       tail[-1][:120] if tail else "(no stdout)"))
    return proc.returncode == 0


def process() -> int:
    names = pop_now_names()
    if not names:
        return 0
    log("picked force_run_now: %s" % names)
    failed = []
    for name in names:
        if not run_once(name):
            failed.append(name)
    if failed:
        downgrade_to_force_run(failed)
        log("downgraded to force_run: %s" % failed)
    return 0


def selftest() -> int:
    """纯逻辑自测：临时 control.json 读写/摘除/降级，不真跑任何 skill。"""
    import tempfile
    global CONTROL_FILE
    real = CONTROL_FILE
    try:
        with tempfile.TemporaryDirectory() as td:
            CONTROL_FILE = Path(td) / "control.json"
            # ① 无文件 → 空
            assert pop_now_names() == []
            # ② force_run_now 摘除，force_run 保留
            CONTROL_FILE.write_text(json.dumps(
                {"force_run": ["a"], "force_run_now": ["b", "c"]}))
            assert pop_now_names() == ["b", "c"]
            data = json.loads(CONTROL_FILE.read_text())
            assert data == {"force_run": ["a"]}, data
            # ③ 降级合并去重
            downgrade_to_force_run(["b"])
            data = json.loads(CONTROL_FILE.read_text())
            assert data["force_run"] == ["a", "b"], data
            # ④ 损坏 JSON → 安全空
            CONTROL_FILE.write_text("{broken")
            assert pop_now_names() == []
        print("selftest-ok")
        return 0
    finally:
        CONTROL_FILE = real


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--daemon" in sys.argv:
        # 常驻模式：launchd 在本机受限（bootstrap I/O error），改双 fork+setsid
        # 常驻循环（同 bg-chrome-up.sh 已验证手法），每 60s 扫描一次。
        log("watcher daemon started pid=%s" % os.getpid())
        while True:
            try:
                process()
            except Exception as error:  # 扫描循环永不退出
                log("loop-error %r" % error)
            time.sleep(60)
    if not CONTROL_FILE.exists():
        return 0
    return process()


if __name__ == "__main__":
    sys.exit(main())
