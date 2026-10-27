#!/usr/bin/env python3
"""WeCom desktop send API — the shared send capability for all task flows.

固化为独立可复用能力（大同 2026-10-23 指令）：15 流共用这一个入口，
不再各自实现发送。三类载荷：

    from wecom_sender_api import send_text, send_image, send_file
    r = send_text(group, "文本")                 # -> dict receipt
    r = send_image(group, "/path/a.png", caption="可选说明")
    r = send_file(group, "/path/a.xlsx", caption="可选说明")

receipt 统一结构：
    {"ok": bool, "result": "verified|sent-tail-unconfirmed|<fail-reason>",
     "kind": "text|image|file", "group": ..., "receipt_file": <path>}

内置纪律（全部 fail-closed，失败不产生外发）：
  1. 主窗锁定：永远定位最大的 AXWindow（聊天主窗），浮层/设置窗不参与。
  2. 导航：前缀搜索切会话（唯一命中 + 聊天区证据），0/多命中即停。
  3. 点击安全区闸门：搜索框只允许点击顶部条，输入框只允许点击底部区，
     越界 fail-closed —— 鼠标永不接近群名/设置区（硬规定 2026-10-23）。
  4. 修饰键清理：每次发送前清卡死的 Cmd/Ctrl/Shift/Alt（曾致 Enter 全变
     Cmd+Enter=换行，静默失败 40 分钟）。
  5. 单发：一次发送尝试；结果不确定（sent-tail-unconfirmed）绝不重发，
     与 Windows 网关 attempted 语义一致；上层防重 marker 不绕过。
  6. frontmost 还原：try/finally 保证发送窗口结束后归还前台。

通道现状（2026-10-23 验收）：text / image / file(+caption) 三类均已在
目标群实证送达（截图+群尾读回）。Windows 微信网关保留为兜底通道；
灰度切换在 registry/调用方侧逐流进行，本 API 不做通道选择。

注意：调用方负责业务级防重（按业务日期的 marker 等）。本 API 只保证
「单次调用 = 单次尝试 = 至多一条外发」。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SENDER = _HERE / "wecom_desktop_sender.py"
_PY = sys.executable

VALID_RESULTS_VERIFIED = {"verified", "sent-tail-unconfirmed"}


def _run(kind: str, group: str, *, text: str = "", path: str | None = None,
         timeout: float = 240.0) -> dict:
    """Invoke the hardened CLI sender and normalize the receipt."""
    cmd = [str(_PY), str(_SENDER)]
    if kind == "text":
        cmd += ["send", "--text", text]
    elif kind == "image":
        if not path:
            return {"ok": False, "result": "usage:image-path-required", "kind": kind, "group": group}
        cmd += ["send-image", "--image", path]
        if text:
            cmd += ["--text", text]
    elif kind == "file":
        if not path:
            return {"ok": False, "result": "usage:file-path-required", "kind": kind, "group": group}
        cmd += ["send-file", "--file", path]
        if text:
            cmd += ["--text", text]
    else:
        return {"ok": False, "result": "usage:kind-must-be-text|image|file", "kind": kind, "group": group}
    cmd += ["--group", group]

    try:
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
               "PYTHONPATH": ""}
        # 2026-10-24 测试群覆盖透传：本 env 是白名单式构造（刻意不继承
        # os.environ），但 WECHAT_TEST_GROUP / WECHAT_TEST_GROUPS 必须到达
        # 发送器子进程——否则覆盖静默失效、落群掉回各流写死的生产群
        # （fail-open 反向事故，比误发测试群严重一个量级）。同时透传 WECOM_AUTOSWEEP
        # 以激活发送器焦点锁定守卫（钉住企微前台）。
        for _k in ("WECHAT_TEST_GROUP", "WECHAT_TEST_GROUPS", "WECOM_AUTOSWEEP"):
            _v = os.environ.get(_k)
            if _v:
                env[_k] = _v
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": "timeout", "kind": kind, "group": group}
    out = (proc.stdout or "").strip()
    if not out:
        return {"ok": False, "result": f"sender-exit-{proc.returncode}",
                "stderr": (proc.stderr or "")[-200:], "kind": kind, "group": group}
    try:
        receipt = json.loads(out.splitlines()[-1])
    except json.JSONDecodeError:
        return {"ok": False, "result": "sender-output-unparseable",
                "raw": out[-200:], "kind": kind, "group": group}
    result = receipt.get("result", "")
    receipt["ok"] = result in VALID_RESULTS_VERIFIED
    receipt["kind"] = kind
    receipt["group"] = group
    return receipt


def send_text(group: str, text: str, timeout: float = 240.0) -> dict:
    """Send a plain text message. Returns unified receipt dict."""
    return _run("text", group, text=text, timeout=timeout)


def send_image(group: str, image_path: str, caption: str = "",
               timeout: float = 240.0) -> dict:
    """Send a PNG image (optionally with a caption line)."""
    return _run("image", group, text=caption, path=image_path, timeout=timeout)


def send_file(group: str, file_path: str, caption: str = "",
              timeout: float = 240.0) -> dict:
    """Send a file card (optionally with a caption line)."""
    return _run("file", group, text=caption, path=file_path, timeout=timeout)


if __name__ == "__main__":
    # quick self-check of arg plumbing only (no send): missing args -> usage results
    print(json.dumps({
        "send_text_no_group": send_text("", "x"),
        "send_image_no_path": send_image("g", ""),
        "send_file_no_path": send_file("g", ""),
    }, ensure_ascii=False, indent=1))
