#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 侧监听服务（直连 IP 模式）
- 仅接受带 Bearer Token 的 POST /command
- 收到指令后调用 driver.dispatch() 在本地操作微信（UI 自动化）
- 必须在 Windows + 同用户会话下运行（才能驱动 GUI）
"""
import json
import os
import sys

from http.server import BaseHTTPRequestHandler, HTTPServer

import driver  # 同目录下的驱动模块

TOKEN = os.environ.get("WECHAT_AGENT_TOKEN", "CHANGE_ME_STRONG_TOKEN")
HOST = os.environ.get("WECHAT_AGENT_HOST", "0.0.0.0")
PORT = int(os.environ.get("WECHAT_AGENT_PORT", "8731"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "msg": "agent up", "uiautomation": driver.auto is not None})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        # 鉴权：必须在 Authorization: Bearer <TOKEN>
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {TOKEN}":
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            req = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._send(400, {"ok": False, "error": f"bad request: {e}"})
            return

        action = req.get("action")
        params = req.get("params", {})
        try:
            result = driver.dispatch(action, params)
            self._send(200, {"ok": True, "data": result})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def log_message(self, *a):
        pass  # 静默


if __name__ == "__main__":
    print(f"[wechat-windows-agent] listening on {HOST}:{PORT}")
    print(f"[wechat-windows-agent] uiautomation loaded: {driver.auto is not None}")
    try:
        HTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[wechat-windows-agent] stopped")
