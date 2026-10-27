#!/usr/bin/env python3
"""status_protocol.py — ① 登录/挑战长流程状态文件协议（移植自 Easel login_state.py）.

问题：浏览器采集常遇到「需要已登录的标签页 / 扫码 / 短信验证 / 滑块」这类要人介入的
长流程。若把状态塞在 agent 内存里，守护进程重启、跨天续跑、或 human-in-the-loop 回填
验证码时就丢了上下文，只能从头来。

方案：把长流程外置成一个原子写的 JSON 状态文件，agent / 守护进程只轮询它；验证码用
「一次性消费码文件」传递。这与 Easel 的 web_publisher / xhs_publish 解耦浏览器的做法一致。

状态机：starting → qr_ready → [scanned] → [sms_required → verifying] → success | expired | error
（sms_required：扫码后平台风控要求短信验证，runner 等外部回填验证码；verifying：已拿到码
 正在提交；校验失败会退回 sms_required 让重输）

用法：
  from shared.browser_precise_ops import status_protocol as sp
  sp.write_status(path, "qr_ready", message="请扫码", qr="data:image/png;base64,...")
  st = sp.read_status(path)            # {state, message, qr, ts}
  code = sp.read_sms_code(code_path)    # 读到即删除（一次性），无则 ""
  sp.write_status(path, "success")
"""
from __future__ import annotations

import json
import os
import tempfile
import time

# 合法状态（read_status 用它过滤损坏文件）
STATES = (
    "starting",
    "qr_ready",
    "scanned",
    "sms_required",
    "verifying",
    "success",
    "expired",
    "error",
)


def write_status(path: str | None, state: str, message: str = "", qr: str = "") -> None:
    """原子写登录/挑战状态。path 为空则跳过（CLI 直跑不需要文件时）。

    用临时文件 + os.replace 保证读到半截也不会出现（避免守护进程读到损坏 JSON）。
    """
    if not path:
        return
    if state not in STATES:
        raise ValueError(f"bad-state:{state}")
    data = {"state": state, "message": message, "qr": qr, "ts": int(time.time())}
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_status(path: str) -> dict:
    """读状态；不存在或损坏返回 unknown。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("state") in STATES:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"state": "unknown", "message": "", "qr": "", "ts": 0}


def read_sms_code(path: str | None) -> str:
    """读并消费一次性短信验证码文件（外部回填后写入）。

    约定：路径为 <run_dir>/<platform>.code，内容为纯数字验证码。读到后立即删除
    （消费一次），返回验证码；无文件/为空返回 ""。
    """
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            code = f.read().strip()
    except OSError:
        return ""
    try:
        os.unlink(path)
    except OSError:
        pass
    return code


def self_test() -> dict:
    import tempfile

    d = tempfile.mkdtemp(prefix="sp-selftest-")
    sp = os.path.join(d, "login.json")
    cp = os.path.join(d, "douyin.code")
    write_status(sp, "qr_ready", message="请扫码")
    assert read_status(sp)["state"] == "qr_ready"
    write_status(sp, "sms_required", message="尾号 1234")
    assert read_status(sp)["state"] == "sms_required"
    with open(cp, "w", encoding="utf-8") as f:
        f.write("654321")
    assert read_sms_code(cp) == "654321"
    assert read_sms_code(cp) == ""  # 一次性消费
    assert not os.path.exists(cp)
    # 损坏文件返回 unknown
    bad = os.path.join(d, "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert read_status(bad)["state"] == "unknown"
    # 空 path 安全
    write_status(None, "starting")
    assert read_sms_code(None) == ""
    return {"ok": True, "tests": 5}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, indent=2))
