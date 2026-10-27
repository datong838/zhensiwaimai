#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
联调自检脚本 —— 填好下面的 IP 和 TOKEN，直接运行即可。

    python example.py

会依次验证：探活 → 看当前会话 → 列会话 → 发一条文字 → 批量空跑。
默认发给「文件传输助手」（微信自带的自存聊天，不会打扰任何人）。

成功标志：每一步都打印 [OK]。
"""
import sys

# ===== 只需要改这两行 ==========================================
WIN_IP = "192.168.110.185"          # 服务端局域网 IP
TOKEN = "<把 TOKEN 填在这里>"        # 向服务端持有人索取
# ==============================================================

from client import WeChat   # noqa: E402  (同目录下)


def step(no, title):
    print(f"\n[{no}] {title}")


def main():
    if "<" in TOKEN:
        print("请先把 example.py 里的 TOKEN 填上再运行")
        return 1

    wx = WeChat(WIN_IP, TOKEN)

    # 1. 探活
    step(1, "探活 wx.health()")
    h = wx.health()
    print("   ", h)
    if not h.get("ok"):
        print("    [FAIL] 连不上：检查 IP / 网络 / 服务端是否在线")
        return 1
    if not h.get("ready"):
        print(f"    [WARN] 微信未就绪 wechat_running={h.get('wechat_running')} "
              f"logged_in={h.get('logged_in')}（未登录需服务端扫码）")
        print("    等待就绪（最多 3 分钟）...")
        h = wx.wait_ready(timeout=180)
        print("   ", h)
        if not h.get("ready"):
            print("    [FAIL] 仍未就绪")
            return 1
    print("    [OK] 服务在线且微信已登录")

    # 2. 当前会话
    step(2, "看服务端当前打开的是哪个会话 wx.current()")
    print("   ", wx.current())

    # 3. 会话列表
    step(3, "列会话 wx.sessions()（确认群名真实写法）")
    s = wx.sessions()
    names = s.get("data", {}).get("sessions", [])
    print(f"    共 {len(names)} 个，前 10 个：")
    for n in names[:10]:
        print("      -", n)
    if not names:
        print("    [WARN] 没读到会话列表")

    # 4. 发一条文字（发给文件传输助手，安全）
    step(4, "发一条文字 wx.send('文件传输助手', ...)")
    r = wx.send("文件传输助手", "联调自检：来自另一台机器")
    print("   ", r)
    print("    [OK] 发送成功" if r.get("ok") else "    [FAIL] 发送失败")

    # 5. 回读确认
    step(5, "回读消息 wx.read()")
    rd = wx.read()
    msgs = rd.get("data", {}).get("messages", [])
    print("    最近 5 条：")
    for m in msgs[-5:]:
        print("      -", m)

    # 6. 批量空跑（不真发）
    step(6, "批量空跑 wx.run(..., dry_run=True)")
    tasks = [
        {"who": "文件传输助手", "type": "text", "text": "批量空跑测试"},
        {"who": "文件传输助手", "type": "file", "path": "C:\\no\\such\\file.xlsx"},
    ]
    br = wx.run(tasks, dry_run=True)
    d = br.get("data", {})
    print(f"    total={d.get('total')} ok={d.get('ok')} failed={d.get('failed')}")
    for it in d.get("results", []):
        print(f"      #{it['index']} {it['who']} {it['type']} -> {it['status']} "
              f"{it.get('error', '')}")
    print("    [OK] 第二条应为 error（路径不存在，说明校验生效）")

    print("\n=== 自检完成 ===")
    print("接下来把你自己的文件发出去：")
    print('    wx.send_local_file("群名", "/你机器上的路径/日报.xlsx")')
    return 0


if __name__ == "__main__":
    sys.exit(main())
