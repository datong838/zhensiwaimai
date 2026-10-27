#!/usr/bin/env python3
"""WoL 唤醒 Windows 网关机（DESKTOP-TH91SO5 / 192.168.110.184）。

用法:
  wol_windows.py            # 发魔术包 + 轮询等网关回来（最长 wait 秒）
  wol_windows.py --fire     # 只发包不等（launchd 定时用，零输出快进快出）
  wol_windows.py --check    # 只探测网关健康，不发包

魔术包 = 6×0xFF + 16×MAC，UDP 广播到 192.168.110.255 的 7/9 端口。
发包对已开机机器无害（幂等）。网关判据 = /health 回 JSON（data.logged_in 双字段见 #53）。
"""
import argparse
import json
import socket
import sys
import time
import urllib.request

MAC = "84:5c:f3:f0:90:6"
IP = "192.168.110.184"
SUBNET_BROADCAST = "192.168.110.255"
TOKEN = "XFVfZHoKwjHaWsZ7EXt2kNvWLSg4TGSvIpMQnvIkCaY"
PORTS = (9, 7)


def build_magic_packet(mac: str) -> bytes:
    mac_bytes = bytes(int(x, 16) for x in mac.split(":"))
    if len(mac_bytes) != 6:
        raise SystemExit(f"bad mac: {mac}")
    return b"\xff" * 6 + mac_bytes * 16


def fire() -> int:
    pkt = build_magic_packet(MAC)
    sent = 0
    # 关键：SO_BROADCAST，否则 UDP 广播被拒
    for port in PORTS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(pkt, (SUBNET_BROADCAST, port))
                sent += 1
        except OSError as e:
            print(f"[wol] port {port} send failed: {e}", file=sys.stderr)
    return sent


def gateway_alive(timeout: float = 3.0) -> dict | None:
    """网关判据：/health 回 JSON（双字段判据见 MEMORY #53）。"""
    try:
        req = urllib.request.Request(
            f"http://{IP}:8731/health",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        data = d.get("data", d)
        return {"logged_in": data.get("logged_in"), "ready": data.get("ready")}
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", action="store_true", help="只发包不等待")
    ap.add_argument("--check", action="store_true", help="只探测不发包")
    ap.add_argument("--wait", type=int, default=180, help="发包后最长等待秒数")
    args = ap.parse_args()

    if args.check:
        h = gateway_alive()
        print(json.dumps({"alive": h is not None, "health": h}, ensure_ascii=False))
        return 0 if h else 1

    n = fire()
    print(f"[wol] magic packet sent to {SUBNET_BROADCAST} ports={PORTS} ok={n}/{len(PORTS)}")
    if args.fire:
        return 0 if n else 1

    deadline = time.time() + args.wait
    while time.time() < deadline:
        time.sleep(10)
        h = gateway_alive()
        if h:
            print(f"[wol] gateway UP after wake: {json.dumps(h)}")
            return 0
        print("[wol] waiting gateway ...")
    print("[wol] TIMEOUT: gateway not back yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
