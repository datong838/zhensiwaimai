#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wxsend —— 微信发送包装器（Mac 侧一键发文字/文件到微信）

自动从同目录「接入包/连接信息.txt」解析服务地址和 TOKEN，无需设置环境变量。
内置重试（兜住服务端偶发的「打开会话失败」）。

用法：
    python3 wxsend.py "臻肆测试群" "消息文字"
    python3 wxsend.py --file "臻肆测试群" /path/to/文件.xlsx
    python3 wxsend.py --status          # 探活
    python3 wxsend.py --sessions        # 列会话
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

INFO_FILE = os.path.join(HERE, "接入包", "连接信息.txt")
GATEWAY_CONFIG_FILE = os.path.join(HERE, "gateway.json")

_GATEWAY_CFG_CACHE = {}


def load_gateway_config():
    """读取 gateway.json（网关地址配置项，2026-10-10 大同要求配置化）。

    返回 {"port": int, "relay_port": int, "candidates": [str]}；文件缺失/损坏时
    返回内置兜底默认（与配置文件同值），保证零配置也能跑。结果按 mtime 缓存。
    """
    mtime = None
    try:
        mtime = os.path.getmtime(GATEWAY_CONFIG_FILE)
    except OSError:
        pass
    if mtime is not None and _GATEWAY_CFG_CACHE.get("mtime") == mtime:
        return _GATEWAY_CFG_CACHE["cfg"]
    cfg = {"port": 8731, "relay_port": 8732, "token_fallbacks": [],
           "candidates": ["192.168.110.184", "192.168.0.3", "192.168.0.2", "192.168.0.5", "172.16.8.157"]}
    try:
        with open(GATEWAY_CONFIG_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw.get("candidates"), list) and raw["candidates"]:
            cfg["candidates"] = [str(c).strip() for c in raw["candidates"] if str(c).strip()]
        cfg["port"] = int(raw.get("port", cfg["port"]))
        cfg["relay_port"] = int(raw.get("relay_port", cfg["relay_port"]))
        if isinstance(raw.get("token_fallbacks"), list):
            cfg["token_fallbacks"] = [str(t) for t in raw["token_fallbacks"] if str(t).strip()]
    except (OSError, ValueError, TypeError):
        pass  # 配置不可用 → 用内置兜底，行为与旧版硬编码一致
    _GATEWAY_CFG_CACHE["mtime"] = mtime
    _GATEWAY_CFG_CACHE["cfg"] = cfg
    return cfg


def _health_ok(ip, token, timeout=3.0, port=8731):
    """/health 身份校验：必须返回 ok=true 且 agent up 才算我们那台主机（/health 不校验 token，
    因此命中后仍要求 token 非空——token 只来自本地连接信息.txt，不会被外部注入）。"""
    try:
        import urllib.request
        req = urllib.request.Request(f"http://{ip}:{port}/health",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return bool(data.get("ok")) and "agent up" in str(data.get("msg", ""))
    except Exception:
        return False


def _auth_ok(ip, token, timeout=4.0, port=8731):
    """鉴权探针（只读，无副作用）：/health **不校验 token**，因此「health 通」并不能说明 token 可用。

    2026-10-22 实战：Windows 侧重启丢了 WECHAT_AGENT_TOKEN 环境变量，进程实际生效默认 token，
    而 Mac 侧连接信息.txt 仍是强 token ⇒ health 通、list_sessions 401，全部业务流判
    `windows-sessions-unavailable:HTTP 401`。这里用只读动作 current_chat 真正验证 token；
    401 时服务端未执行任何动作，切换/重试都安全。
    """
    try:
        import urllib.request
        body = json.dumps({"action": "current_chat"}).encode("utf-8")
        req = urllib.request.Request(f"http://{ip}:{port}/", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return bool(data.get("ok"))
    except Exception:
        return False


def load_config():
    """从连接信息.txt 解析 IP 和 TOKEN，避免 token 二次落盘。

    2026-10-06 晚升级（有线 .2 宕、无线 .5 活的实战教训）：不再信任单一 IP，
    改为「候选 + /health 身份校验」——候选顺序 有线.2 优先、无线.5 兜底
    （连接信息.txt 解析出的地址排最前），取第一个通过身份校验者。
    与 localhost_relay.py 的候选哲学一致：不硬编码可达性，实测为准。
    """
    cfg = load_gateway_config()
    gw_port = cfg["port"]
    ip, token = cfg["candidates"][0], ""
    with open(INFO_FILE, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"http://([\d.]+):(\d+)", text)
    if m:
        ip = m.group(1)  # 连接信息.txt 仍解析为首选（人工即时改地址的快捷口）
    m = re.search(r"TOKEN\s+([A-Za-z0-9+/=_\-]{16,})", text)
    if m:
        token = m.group(1)
    if not token:
        raise SystemExit(f"[!] 未能从 {INFO_FILE} 解析出 TOKEN")
    # 候选 + 身份校验：★2026-10-10 全部收敛到 gateway.json 配置项（改 IP 只动那一个文件）；
    # 连接信息.txt 解析出的地址排最前，其余按配置顺序（去重）；取第一个 /health 通过者
    candidates = [ip] + [c for c in cfg["candidates"] if c != ip]
    # token 回退（2026-10-22）：主 token 被 401 时依次试 gateway.json token_fallbacks。
    # 场景=Windows 服务重启丢 env ⇒ 实际生效默认 token；客户端不该因此全线瘫掉，
    # 也不该把强 token 从配置里删掉（对端修好后应自动回到主 token）。
    fallbacks = [t for t in cfg.get("token_fallbacks") or [] if t and t != token]
    for cand in candidates:
        if _health_ok(cand, token, port=gw_port):
            if cand != ip:
                # 2026-10-07：必须走 stderr——windows_adapter 在 sender 进程内 import
                # 本函数，stdout 是下游 pipeline 的 JSON 通道，任何 print 污染都会
                # 炸掉解析（当日 15:06 jinsha 流 desktop-preflight-retry-limit 4 连败根因）。
                print(f"[!] 首选 {ip} 不可达，回落候选 {cand}（/health 身份校验通过）",
                      file=sys.stderr)
            if not fallbacks or _auth_ok(cand, token, port=gw_port):
                return cand, token
            for alt in fallbacks:
                if _auth_ok(cand, alt, port=gw_port):
                    print("[!] 主 token 鉴权失败(401)，已回落到 gateway.json token_fallbacks 中的备用 token"
                          "（对端恢复强 token 后会自动回到主 token）", file=sys.stderr)
                    return cand, alt
            # 所有 token 都被拒：维持旧行为，让上层报原始 401
            return cand, token
    # 全部候选失败：维持旧行为返回解析 IP，让上层给出原始连接错误
    return ip, token


def send_with_retry(wx, who, payload, is_file=False, attempts=3, gap=6):
    """带重试的发送；服务端偶发「打开会话失败」重试即可过。"""
    last = None
    for i in range(1, attempts + 1):
        last = wx.send_auto(who, payload) if not is_file else wx.send_local_file(who, payload)
        if last.get("ok"):
            if i > 1:
                print(f"    (第{i}次重试成功)", file=sys.stderr)
            return last
        err = str(last.get("error", ""))
        print(f"    第{i}次失败: {err[:120]}", file=sys.stderr)
        if i < attempts:
            time.sleep(gap)
    return last


def main(argv):
    from client import WeChat

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    ip, token = load_config()
    wx = WeChat(ip, token)

    if argv[0] == "--status":
        print(wx.health())
        return 0
    if argv[0] == "--sessions":
        r = wx.sessions()
        for n in (r.get("data") or {}).get("sessions", []):
            print(" -", n)
        return 0

    is_file = argv[0] == "--file"
    # 模式开关（--file 等）占 argv[0] 时，who 从 argv[1] 开始；否则 argv[0] 就是 who
    args = argv[1:] if argv[0].startswith("--") else argv
    if len(args) < 2:
        print(__doc__)
        return 1
    who, payload = args[0], args[1]

    r = send_with_retry(wx, who, payload, is_file=is_file)
    if r.get("ok"):
        d = r.get("data", {})
        print(f"[OK] 已发送 -> {who}  (类型: {d.get('auto', 'text')})")
        if d.get("server_path"):
            print(f"     服务端路径: {d['server_path']}")
        return 0
    print(f"[FAIL] {r.get('error')}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
