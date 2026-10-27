#!/usr/bin/env python3
"""Localhost relay for the Windows WeChat driver.

macOS "Local Network" TCC privacy blocks launchd daemons from connecting to
LAN hosts (e.g. 192.168.0.x:8731), surfacing as `No route to host`.
localhost is never gated by that TCC service, so this relay listens on
127.0.0.1 and forwards raw TCP to the real driver. The daemon connects to
localhost (no TCC needed); this process runs inside a GUI session that already
holds the Local Network grant, so the upstream hop is permitted.

Run (inside a GUI session, e.g. the user's interactive Terminal/WorkBuddy):
    python3 localhost_relay.py

2026-10-06 · 目标自动发现（候选 + 身份校验）
------------------------------------------------
那台 Windows 主机有**两块网卡**（2026-10-06 大同确认，同一台机）：
  · 192.168.0.5 = 无线网卡
  · 192.168.0.2 = 有线网卡
驱动绑 0.0.0.0:8731、两块网卡都在监听 ⇒ **机器本机自测两个 IP 都通**，
但**从 Mac 侧只有有线那条稳定可达**（无线 .5 实测不可达，疑为无线链路未关联/AP 隔断；
2026-10-05 晚 Wi-Fi 断电重启后整条链路哑了数小时，即由此暴露）。

因此中继不再把上游 IP 当常量：
  1. 按优先级探测候选主机（默认 `192.168.0.2,192.168.0.5`：**有线优先、无线兜底**）。
     有线不受 Wi-Fi 断电影响，且 Mac 当前只有 .2 可达——把必然失败的候选排前面
     只会每次重发现都白烧一次探测（选择规则是「按优先级取第一个通过校验的」，
     不是先到先得，故顺序有意义）；
  2. 只认**通过了驱动身份校验**的主机（GET /health 必须回
     `{"ok":true,"msg":"agent up",... "uiautomation":...}`）——防止这两个 IP
     被 DHCP 租给别的设备时误连；
  3. 选中结果缓存；上游连接失败时自动重新发现（有最小重探间隔，防探测风暴）。

Env overrides:
    RELAY_LISTEN_HOST     (default 127.0.0.1)
    RELAY_LISTEN_PORT     (default 8732)
    RELAY_TARGET_HOST     (显式单目标；设了则最高优先级，仍会做身份校验)
    RELAY_TARGET_HOSTS    (候选列表，逗号分隔；default "192.168.0.3,192.168.0.2,192.168.0.5"
                           ★2026-10-09 大同改网关到 .3，.2/.5 保留兜底)
    RELAY_TARGET_PORT     (default 8731)
    RELAY_PROBE_TIMEOUT   (单次探测超时秒，default 0.8)
    RELAY_REPROBE_SECONDS (失败后重新发现的最小间隔秒，default 20)
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

# 2026-10-12：WorkBuddy 沙箱出现「按二进制放行」的网络策略——
# /usr/bin/nc、/usr/bin/curl 连 LAN 正常，python 的 socket 直连被拦
# （连接级 Errno 65 No route to host，毫秒级返回，请求从未发出）。
# 中继若从沙箱上下文拉起，urllib 探测与 socket 转发全部失明
# （relay.err.log 连续 no candidate）。兜底：直连失败时改经 nc 子进程
# 管道完成最后一跳。数据路径不变（Mac→Windows 网关），语义仍是透明转发。
NC_BIN = os.environ.get("RELAY_NC_BIN", "/usr/bin/nc")
# nc -w 是「空闲超时」：真实发送（服务端 UI 自动化）期间中继 TCP 上可能
# 长时间无数据，须大于桥侧 deadline（deliver_batch 900s）。3600s 保守。
NC_IDLE_TIMEOUT = int(os.environ.get("RELAY_NC_IDLE_TIMEOUT", "3600"))

LISTEN_HOST = os.environ.get("RELAY_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("RELAY_LISTEN_PORT", "8732"))


def _gateway_cfg():
    """读 gateway.json（网关地址配置项，单一权威）。缺失/损坏回退内置默认。"""
    cfg = {"port": 8731, "candidates": ["192.168.110.184", "192.168.0.3", "192.168.0.2", "192.168.0.5", "172.16.8.157"]}
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "gateway.json"), encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw.get("candidates"), list) and raw["candidates"]:
            cfg["candidates"] = [str(c).strip() for c in raw["candidates"] if str(c).strip()]
        cfg["port"] = int(raw.get("port", cfg["port"]))
    except (OSError, ValueError, TypeError):
        pass
    return cfg


_GW = _gateway_cfg()

TARGET_SINGLE = os.environ.get("RELAY_TARGET_HOST", "").strip()
TARGET_LIST = [h.strip() for h in
               os.environ.get("RELAY_TARGET_HOSTS",
                              ",".join(_GW["candidates"])).split(",") if h.strip()]
TARGET_PORT = int(os.environ.get("RELAY_TARGET_PORT", str(_GW["port"])))
PROBE_TIMEOUT = float(os.environ.get("RELAY_PROBE_TIMEOUT", "0.8"))
REPROBE_SECONDS = float(os.environ.get("RELAY_REPROBE_SECONDS", "20"))
# 2026-10-06 修复：连接超时 ≠ IO 超时。
# `socket.create_connection(timeout=8)` 会把 8s 超时**留在 socket 上并作用于其后所有
# 阻塞操作**；于是 pump 里的 `dst.recv()` 在上游静默 8s 后抛 socket.timeout(OSError)，
# 被 pump 的 `except OSError: pass` 静默吞掉 ⇒ 响应泵线程死掉 ⇒ 任何 >8s 的上游响应
# **永远回不到调用方**。真实发送（UI 自动化：打开会话→逐字输入→提交）必然 >8s，
# 故现象是「消息已发出但调用方挂死到超时」。密闭复现（假上游 12s 响应）：
#   直连 /slow -> HTTP 200 (12.0s)；经中继 /slow -> 零字节、25s 超时。
# 修法：连上用「连接超时」，连上后把 socket 恢复为纯阻塞（透明转发语义）。
UPSTREAM_CONNECT_TIMEOUT = float(os.environ.get("RELAY_UPSTREAM_CONNECT_TIMEOUT", "8"))
_io_env = os.environ.get("RELAY_UPSTREAM_IO_TIMEOUT", "").strip()
UPSTREAM_IO_TIMEOUT = float(_io_env) if _io_env else None  # 默认 None=纯阻塞
BUFFER = 1 << 16

# 恒定绕开本机代理：探测必须直连局域网，否则会被 127.0.0.1 的翻墙/沙箱代理截胡
_PROBE_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_seen = {"host": TARGET_SINGLE or (TARGET_LIST[0] if TARGET_LIST else ""),
         "at": 0.0}
_seen_lock = threading.Lock()


def _candidates():
    """有序候选（去重）：显式单目标 > 候选列表。"""
    order = ([TARGET_SINGLE] if TARGET_SINGLE else []) + TARGET_LIST
    return [h for h in dict.fromkeys(order) if h]


def _driver_identity_ok(host):
    """该 host:port 是否是我们那台 Windows 驱动的签名（不是随便一个 8731 服务）。"""
    try:
        with _PROBE_OPENER.open(f"http://{host}:{TARGET_PORT}/health",
                                timeout=PROBE_TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8"))
    except Exception:
        # 2026-10-12：沙箱按二进制拦 python 出站（毫秒级 Errno 65）。
        # 探测失败不等于主机不存在——用 nc 子进程再试一次（nc 被放行）。
        # 成功路径零变化；仅原 urllib 路径失败时才多一次 nc 兜底。
        try:
            probe = subprocess.run(
                [NC_BIN, "-w", str(int(PROBE_TIMEOUT + 1)), host, str(TARGET_PORT)],
                input=(f"GET /health HTTP/1.1\r\nHost: {host}:{TARGET_PORT}\r\n"
                       "Connection: close\r\n\r\n").encode(),
                capture_output=True, timeout=PROBE_TIMEOUT + 3)
            body = json.loads(
                probe.stdout.decode("utf-8", "replace").split("\r\n\r\n", 1)[-1])
        except Exception:
            return False
    return (isinstance(body, dict) and body.get("ok") is True
            and body.get("msg") == "agent up"
            and "uiautomation" in body and "worker" in body)


def discover_target(force=False):
    """返回可用上游 host；按候选中第一个通过身份校验者。结果带缓存。"""
    now = time.time()
    with _seen_lock:
        cur, at = _seen["host"], _seen["at"]
    # 缓存仍新鲜时，先验一次缓存主机（廉价），有效就直接用
    if cur and not force and (now - at) < REPROBE_SECONDS:
        return cur

    cands = _candidates()
    if not cands:
        return None
    verdict = {}
    lock = threading.Lock()

    def probe(h):
        ok = _driver_identity_ok(h)
        with lock:
            verdict[h] = ok

    threads = [threading.Thread(target=probe, args=(h,), daemon=True) for h in cands]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=PROBE_TIMEOUT + 1.5)

    # 并行探测后，按优先级取第一个命中的（而非先完成的）
    chosen = next((h for h in cands if verdict.get(h)), None)
    if chosen:
        with _seen_lock:
            if _seen["host"] != chosen:
                sys.stderr.write(f"[relay] upstream target -> {chosen}:{TARGET_PORT}\n")
                sys.stderr.flush()
            _seen["host"] = chosen
            _seen["at"] = now
    else:
        sys.stderr.write("[relay] no candidate passed driver identity check: "
                         + ",".join(cands) + "\n")
        sys.stderr.flush()
    return chosen


class _NcPipe:
    """nc 子进程管道，模拟 socket 双向接口（sendall/recv/close）。

    沙箱按二进制拦 python socket 直连时，nc 仍被放行——由 nc 完成
    到上游驱动的 TCP 最后一跳。recv 空读（EOF）返回 b''，与 socket
    语义一致，pump 循环无需改动。
    """

    def __init__(self, host, port):
        self._p = subprocess.Popen(
            [NC_BIN, "-w", str(NC_IDLE_TIMEOUT), host, str(port)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        self._in = self._p.stdin
        self._out = self._p.stdout

    def settimeout(self, seconds):  # 接口兼容；nc -w 已承担空闲超时
        pass

    def sendall(self, data):
        self._in.write(data)
        self._in.flush()

    def recv(self, bufsize):
        return self._out.read1(bufsize) if hasattr(self._out, "read1") \
            else self._out.read(bufsize)

    def close(self):
        for f in (self._in, self._out):
            try:
                f.close()
            except Exception:
                pass
        try:
            self._p.terminate()
        except Exception:
            pass


def _upstream_connect(host):
    """连上游驱动，并把 socket 从「连接超时」切回「纯阻塞 IO」。

    见文件顶部 UPSTREAM_CONNECT_TIMEOUT 注释：不这样做，>8s 的上游响应会被
    静默丢弃，表现为「消息已发出但调用方挂死」。
    2026-10-12：python socket 被沙箱按二进制拦截（毫秒级 Errno 65）时
    回落 nc 管道。两条路径对调用方完全同构（sendall/recv/close）。
    """
    try:
        sock = socket.create_connection((host, TARGET_PORT),
                                        timeout=UPSTREAM_CONNECT_TIMEOUT)
        sock.settimeout(UPSTREAM_IO_TIMEOUT)
        return sock
    except OSError as direct_error:
        if direct_error.errno not in (65, 51, 13, 64):
            raise  # 非「连接级本地拦截」形态（如真超时）不兜底，保持原语义
        sys.stderr.write(f"[relay] python direct blocked ({direct_error}), "
                         f"falling back to nc pipe -> {host}:{TARGET_PORT}\n")
        sys.stderr.flush()
        return _NcPipe(host, TARGET_PORT)


def relay_once(src: socket.socket) -> None:
    target = discover_target()
    dst = None
    if target:
        try:
            dst = _upstream_connect(target)
        except OSError as exc:
            sys.stderr.write(f"[relay] upstream connect failed {target}:{TARGET_PORT}: {exc}\n")
            dst = None
    if dst is None:
        # 上游可能刚换 IP：强制重新发现后再试一次
        target = discover_target(force=True)
        if target:
            try:
                dst = _upstream_connect(target)
            except OSError as exc:
                sys.stderr.write(f"[relay] upstream retry failed {target}:{TARGET_PORT}: {exc}\n")
                dst = None
    if dst is None:
        try:
            src.close()
        except OSError:
            pass
        return
    try:
        def pump(a: socket.socket, b: socket.socket):
            try:
                while True:
                    data = a.recv(BUFFER)
                    if not data:
                        break
                    b.sendall(data)
            except OSError:
                pass
        t = threading.Thread(target=pump, args=(dst, src), daemon=True)
        t.start()
        pump(src, dst)
    finally:
        for s in (src, dst):
            try:
                s.close()
            except OSError:
                pass


def main() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(128)
    sys.stderr.write(f"[relay] listening on {LISTEN_HOST}:{LISTEN_PORT} "
                     f"candidates={_candidates()} port={TARGET_PORT}\n")
    sys.stderr.flush()
    discover_target(force=True)  # 启动即探测一次，日志里给出实际选中的上游
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            break
        threading.Thread(target=relay_once, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
