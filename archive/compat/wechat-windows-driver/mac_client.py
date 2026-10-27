#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mac 侧指挥客户端：从 Mac 直连 Windows 上的 wechat-windows-agent，发送指令。
纯标准库（urllib），无需 pip install，用 Mac 自带或 WorkBuddy 的 python3 即可运行。

用法（先设环境变量）：
  export WIN_IP="192.168.x.x"            # Windows 局域网 IP
  export WECHAT_AGENT_TOKEN="与 Windows 端一致的强随机串"
  export WECHAT_AGENT_PORT="8731"        # 可选，默认 8731

  python mac_client.py health                       # 探活
  python mac_client.py dump [depth=7]              # 打印微信 UI 树（校准用）
  python mac_client.py chats                        # 列出左侧会话名
  python mac_client.py send "文件传输助手" "hello from mac"   # 发消息
"""
import json
import os
import sys
import urllib.request
import urllib.error

PORT = os.environ.get("WECHAT_AGENT_PORT", "8731")
TOKEN = os.environ.get("WECHAT_AGENT_TOKEN", "")
WIN_IP = os.environ.get("WIN_IP", "")


def _post(action, params=None):
    if not WIN_IP:
        sys.exit("✗ 请先设置环境变量 WIN_IP（Windows 局域网 IP）")
    if not TOKEN:
        sys.exit("✗ 请先设置环境变量 WECHAT_AGENT_TOKEN（需与 Windows 端一致）")
    url = f"http://{WIN_IP}:{PORT}/"
    body = json.dumps({"action": action, "params": params or {}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _health():
    if not WIN_IP:
        sys.exit("✗ 请先设置 WIN_IP")
    try:
        with urllib.request.urlopen(f"http://{WIN_IP}:{PORT}/health", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "health":
        print(json.dumps(_health(), ensure_ascii=False, indent=2))
    elif cmd == "dump":
        depth = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        res = _post("dump_tree", {"depth": depth})
        if res.get("ok"):
            print(res["data"]["tree"])
        else:
            print(json.dumps(res, ensure_ascii=False, indent=2))
    elif cmd == "chats":
        print(json.dumps(_post("list_chats"), ensure_ascii=False, indent=2))
    elif cmd == "send":
        if len(sys.argv) < 4:
            sys.exit('用法: python mac_client.py send "<who>" "<text>"')
        who, text = sys.argv[2], " ".join(sys.argv[3:])
        print(json.dumps(_post("send_message", {"who": who, "text": text}), ensure_ascii=False, indent=2))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
