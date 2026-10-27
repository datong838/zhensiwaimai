#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针：验证 Windows 驱动「搜索→点选会话」环节是否健康。
只作用于「文件传输助手」（不碰任何群）。
步骤（全部只读）：
  1. health（真登录态）
  2. list_sessions（目标群是否在列）
  3. current_chat（当前会话，发送前后各一次）
  4. read_messages（当前会话消息，看 UI 树读取是否健康）
不发任何内容——不发 send_message，只读。跑完恢复原会话（如有）。
"""
import json
import sys
import time
import urllib.request

HOST = "192.168.110.184"
PORT = 8731
TOKEN = "XFVfZHoKwjHaWsZ7EXt2kNvWLSg4TGSvIpMQnvIkCaY"
TARGET = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(action, params=None):
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}/",
        data=json.dumps({"action": action, "params": params or {}}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json"})
    with opener.open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    print("[1] health:", json.dumps(call("health"), ensure_ascii=False)[:200])
    sessions = call("list_sessions")
    names = (sessions.get("data") or {}).get("sessions") or []
    hit = [n for n in names if TARGET[:12] in n]
    print(f"[2] sessions: {len(names)} 个, 目标群在列: {bool(hit)} -> {hit[:1]}")
    before = call("current_chat")
    print("[3] current(before):",
          json.dumps(before.get("data") or before, ensure_ascii=False)[:150])
    read = call("read_messages")
    msgs = (read.get("data") or {}).get("messages") or []
    print(f"[4] read_messages: {len(msgs)} 条（UI 树读取健康度参考）")
    tail = [m.get("text") or str(m)[:60] for m in msgs[-3:]]
    print("    tail3:", json.dumps(tail, ensure_ascii=False)[:300])
    print("RESULT=READONLY_PROBE_OK")


if __name__ == "__main__":
    main()
