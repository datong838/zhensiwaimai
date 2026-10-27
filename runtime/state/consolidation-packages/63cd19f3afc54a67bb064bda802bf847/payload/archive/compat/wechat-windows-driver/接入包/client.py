#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨机器调用 wechat-windows-driver 的极简客户端（纯标准库，任何机器/任何 Python 都能用）。

调用方视角只有几个函数，HTTP / token / JSON 全藏在里面：

    from client import WeChat
    wx = WeChat("192.168.110.185", "<TOKEN>")

    wx.send("群名", "今天的日报")              -> {"ok": True, "data": {...}}
    wx.send_file("群名", "C:\\docs\\a.pdf")    -> 同上
    wx.send_image("群名", "C:\\imgs\\b.png")
    wx.run([{"who":"群名","type":"text","text":"hi"}])   -> 逐条结果 + 汇总
    wx.current() / wx.read() / wx.sessions() / wx.last()

反馈机制（不用额外搭）：
  1) 同步：函数返回值就是回执（推荐，绝大多数场景够用）
  2) 异步兜底：对方机器上随时 wx.last() 查最后一次任务结果
  3) 落盘：wx.run(..., out="result.json") 把结果写文件，方便共享目录/日志追溯

环境变量（可选，省得每次传）：
  export WIN_IP="192.168.110.185"
  export WECHAT_AGENT_TOKEN="..."
  export WECHAT_AGENT_PORT="8731"   # 可选

连接策略（2026-10-06 起，方案 A）：
  **直连优先**——每个请求都先打到 LAN 上的 Windows 驱动 8731，这是常态路径。
  **仅在「直连以本地网络被拦的形态失败」时才回落本机中继**（127.0.0.1:8732，
  localhost_relay.py 转发到同一台 Windows 驱动）。触发条件严格限定为
  `local_network_blocked=True`（Errno 65/51、permission denied、解析失败）——
  这类失败**可证明请求从未发出**（连接都没建立），故重放不会造成重复投递。
  读超时与 HTTP 错误状态**绝不回落**（请求可能已达服务端，重放有双发风险）。
  中继不存在时（自动探测失败），行为与纯直连完全一致——零副作用。
  显式覆盖：`WIN_RELAY_HOST` / `WIN_RELAY_PORT`；发现端口：`WIN_RELAY_DISCOVER_PORT`。

  为什么需要回落：launchd 拉起的 daemon 进程没有 macOS「本地网络」TCC 授权，
  连 LAN 主机直接 Errno 65；而 localhost 不受该 TCC 管辖，中继进程跑在有授权的
  GUI 会话里，由它完成最后一跳。**数据路径仍是 Mac → Windows 网关，语义上仍是直连服务端。**
"""
import json
import os
import socket
import time
import urllib.request
import urllib.error

# Default relay endpoint. A relay listening here lets launchd daemons reach the
# Windows driver without the "Local Network" TCC grant (see localhost_relay.py).
RELAY_DISCOVER_HOST = os.environ.get("WIN_RELAY_DISCOVER_HOST", "127.0.0.1")
RELAY_DISCOVER_PORT = int(os.environ.get("WIN_RELAY_DISCOVER_PORT", "8732"))


def _discover_relay(timeout=0.4):
    """Return (host, port) of a reachable local relay, else (None, None).

    Used so callers don't need to hardcode relay env vars: if a relay is up on
    the well-known localhost port, route through it automatically. Failures are
    silent and cheap (a single non-blocking connect probe).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            if s.connect_ex((RELAY_DISCOVER_HOST, RELAY_DISCOVER_PORT)) == 0:
                return RELAY_DISCOVER_HOST, str(RELAY_DISCOVER_PORT)
    except OSError:
        pass
    return None, None


def _classify_net_error(exc):
    """Classify a connection-level failure reaching the Windows driver.

    Crucially, distinguish a *local* network/permission failure from a genuine
    server-side problem. A macOS launchd daemon lacks the "Local Network" TCC
    grant, so reaching a LAN host surfaces as `No route to host` /
    `Network is unreachable` — the Windows service itself can be perfectly
    healthy. Returning this distinction is what stops `No route to host` from
    being misread as "the Windows service is down" (it is a caller-context
    issue, fixed by routing through the localhost relay).
    """
    reason = getattr(exc, "reason", None)
    msg = str(reason) if reason is not None else str(exc)
    low = msg.lower()
    local_markers = (
        "no route to host",            # Errno 65 EHOSTUNREACH (TCC-gated LAN)
        "network is unreachable",       # Errno 51 ENETUNREACH
        "ehostunreach",
        "enetunreach",
        "permission denied",            # sandbox / TCC deny
        "nodename nor servname",        # local resolution failure
        "can't assign requested address",
    )
    local_blocked = any(m in low for m in local_markers)
    return {
        "ok": False,
        "error": msg,
        "error_kind": "connection",
        "local_network_blocked": local_blocked,
    }


class WeChat:
    # 2026-10-03：发文件需「base64 上传 + 服务端 GUI 自动发送」，原 180s 会在服务端
    # 仍在处理时提前掐断 HTTP，造成消息其实已送达但回执停在 unknown（见 #10 事故）。
    # 放宽到 600s；仅延长等待窗口，不改变连接方式（仍是直连 LAN 驱动 8731）。
    def __init__(self, host=None, token=None, port=None, timeout=600):
        self.host = host or os.environ.get("WIN_IP", "")
        self.token = token or os.environ.get("WECHAT_AGENT_TOKEN", "")
        self.port = str(port or os.environ.get("WECHAT_AGENT_PORT", "8731"))
        self.timeout = timeout
        if not self.host or not self.token:
            raise ValueError("需要 host 和 token（或设置 WIN_IP / WECHAT_AGENT_TOKEN 环境变量）")
        # 2026-10-06（方案 A）：直连仍是唯一常态路径；中继只在直连被本地网络权限
        # 拦死时兜底。`_relay_probed` 做懒探测（一个 0.4s 的 connect 探针），
        # 中继不在则整条回落分支是死的 ⇒ 纯直连行为零变化。
        self._relay_host = os.environ.get("WIN_RELAY_HOST") or None
        self._relay_port = str(os.environ.get("WIN_RELAY_PORT") or RELAY_DISCOVER_PORT)
        self._relay_probed = bool(self._relay_host)
        # Mac 本地适配：绕过系统代理直连局域网（避免被本机翻墙代理截胡返回 502）
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ---------- 底层 ----------
    def _relay_endpoint(self):
        """返回可用中继的 (host, port)，没有则 (None, None)。

        解析优先级：① 显式 `WIN_RELAY_HOST/PORT`；② 自动探测 127.0.0.1:8732。
        结果按实例缓存（一个 WeChat 对象只服务一次发送），探测失败是很便宜的
        0.4s connect——中继不在时整条回落分支是死的，直连行为零变化。
        """
        if self._relay_host:
            return self._relay_host, self._relay_port
        if not self._relay_probed:
            self._relay_probed = True
            host, port = _discover_relay()
            if host:
                self._relay_host, self._relay_port = host, port
        if self._relay_host:
            return self._relay_host, self._relay_port
        return None, None

    def _attempt(self, method, path, body, timeout, auth, base):
        """对指定 (host, port) 做一次 HTTP 尝试。

        返回 `(result_dict, fallback_eligible)`。`fallback_eligible` **只**在失败
        属于「本地网络类、可证明请求从未发出」时为 True —— 这类失败连接都没建立
        （Errno 65/51 / permission / 解析失败），重放到中继不可能造成重复投递。
        读超时、协议错误、HTTP 错误状态一律 False（请求可能已达服务端）。
        """
        host, port = base
        req = urllib.request.Request(f"http://{host}:{port}{path}",
                                     data=body, method=method)
        if auth:
            req.add_header("Authorization", f"Bearer {self.token}")
            req.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8")), False
        except urllib.error.HTTPError as e:
            # 服务端已应答（含 4xx/5xx）：说明链路是通的，回落无意义且危险
            return {"ok": False,
                    "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}"}, False
        except (urllib.error.URLError, OSError) as e:
            info = _classify_net_error(e)
            return info, bool(info.get("local_network_blocked"))
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}, False

    def _call(self, method, path, body=None, timeout=30, auth=False):
        """直连优先；仅对「本地网络被拦」类失败回落到本机中继一次。"""
        result, eligible = self._attempt(method, path, body, timeout, auth,
                                         (self.host, self.port))
        if not isinstance(result, dict):
            result = {"ok": False, "error": str(result)}
        result.setdefault("route", "direct")
        if eligible:
            relay_host, relay_port = self._relay_endpoint()
            if relay_host:
                relayed, _ = self._attempt(method, path, body, timeout, auth,
                                           (relay_host, relay_port))
                if isinstance(relayed, dict):
                    relayed = dict(relayed)
                    relayed["route"] = "relay"
                    # 保留直连失败原因，便于取证「为什么走了中继」
                    relayed["direct_error"] = result.get("error")
                    relayed["direct_local_network_blocked"] = True
                    return relayed
        return result

    def _get(self, path):
        return self._call("GET", path, timeout=30)

    def _post(self, action, params):
        body = json.dumps({"action": action, "params": params or {}},
                          ensure_ascii=False).encode("utf-8")
        return self._call("POST", "/", body=body, timeout=self.timeout, auth=True)

    # ---------- 业务 ----------
    def health(self):
        return self._get("/health")

    def last(self):
        """最后一次任务结果（异步场景兜底查询）。"""
        return self._get("/last")

    def current(self):
        return self._post("current_chat", {})

    def read(self):
        return self._post("read_messages", {})

    def sessions(self):
        return self._post("list_sessions", {})

    def send(self, who, text):
        return self._post("send_message", {"who": who, "text": text})

    def send_file(self, who, path):
        return self._post("send_file", {"who": who, "path": path})

    def send_image(self, who, path):
        return self._post("send_image", {"who": who, "path": path})

    def list_dir(self, path=None, pattern="*"):
        """看看服务端磁盘上有什么（path 省略则看上传目录 inbox）。"""
        return self._post("list_dir", {"path": path, "pattern": pattern})

    def upload(self, local_path):
        """
        把**你自己机器上**的文件传到服务端，返回它在服务端上的路径。
        这样你完全不用知道对方磁盘长什么样。
        """
        import base64
        with open(local_path, "rb") as f:
            raw = f.read()
        res = self._post("upload", {"filename": os.path.basename(local_path),
                                    "content": base64.b64encode(raw).decode()})
        return res

    def send_local_file(self, who, local_path):
        """
        一步到位：把**你自己机器上**的文件发出去（自动上传 + 自动识别图片/文件）。
        这是跨机器最省事的用法。
        """
        up = self.upload(local_path)
        if not up.get("ok"):
            return up
        server_path = up["data"]["path"]
        r = self.send_auto(who, server_path)
        if r.get("ok"):
            r["data"]["uploaded_from"] = local_path
            r["data"]["server_path"] = server_path
        return r

    def send_auto(self, who, content):
        """
        自动识别并发送（推荐）：
          content 是服务端上的图片路径 -> 发图片
          content 是服务端上的其他文件（xlsx/doc/pdf...）-> 发文件
          否则 -> 当文字发
        返回里 data.auto 会说明实际按哪种发的。
        """
        return self._post("auto_send", {"who": who, "content": content})

    def run(self, tasks, dry_run=False, stop_on_error=False, interval=1.0, out=None):
        """批量：tasks = [{who, type: text|file|image, text|path}, ...]，返回逐条结果。"""
        res = self._post("batch", {"tasks": tasks, "dry_run": dry_run,
                                   "stop_on_error": stop_on_error, "interval": interval})
        if out:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
        return res

    def wait_ready(self, timeout=300, poll=3.0):
        """
        等微信就绪（进程在 + 已登录/主窗口出现）。
        服务端重启微信后需要扫码登录，这段时间内调用会失败——先等它就绪。
        返回最后的 health；超时返回 {'ok': False, 'error': '等待超时'}。
        """
        deadline = time.time() + timeout
        last = self.health()
        while time.time() < deadline:
            h = self.health()
            last = h
            if h.get("ready"):
                return h
            time.sleep(poll)
        return {"ok": False, "error": "等待微信就绪超时（可能未启动或未完成扫码登录）", "last": last}

    def wait_until_idle(self, timeout=300, poll=2.0):
        """简单等待：轮询 /last，直到状态更新（配合异步调用方使用）。"""
        start = self.last().get("last", {}).get("at")
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll)
            cur = self.last().get("last", {}).get("at")
            if cur and cur != start:
                return self.last()
        return {"ok": False, "error": "等待超时"}


if __name__ == "__main__":
    import sys
    wx = WeChat()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "health"
    if cmd == "health":
        print(json.dumps(wx.health(), ensure_ascii=False, indent=2))
    elif cmd == "current":
        print(json.dumps(wx.current(), ensure_ascii=False, indent=2))
    elif cmd == "read":
        print(json.dumps(wx.read(), ensure_ascii=False, indent=2))
    elif cmd == "sessions":
        print(json.dumps(wx.sessions(), ensure_ascii=False, indent=2))
    elif cmd == "last":
        print(json.dumps(wx.last(), ensure_ascii=False, indent=2))
    elif cmd == "send" and len(sys.argv) >= 4:
        print(json.dumps(wx.send(sys.argv[2], sys.argv[3]), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
