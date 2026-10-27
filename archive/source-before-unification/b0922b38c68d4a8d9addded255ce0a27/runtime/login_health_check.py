#!/usr/bin/env python3
"""登录态保活巡检：桌面微信 + 4 个专用 Chrome profile（CDP 存活 + 目标页登录态）。
⚠️ Mac 桌面微信已于 2026-09-30 停用：本巡检的「桌面微信」探测项为历史遗留，Mac 桌面微信进程将始终判定为未运行；禁止据此门禁阻断任何发送或看护动作，实际微信发送改走 Windows 网关/手机微信。
纯 stdlib，只读探测（不点击、不新开窗口、不自动登录）。exit 0=全部正常, 1=有异常。
"""
import json
import subprocess
import sys
import urllib.request
from datetime import datetime

TARGETS = [
    {"name": "品牌商", "port": 9230, "host": "melody.shop.ele.me"},
    {"name": "服务商", "port": 9231, "host": "open.shop.ele.me"},
    {"name": "金鲨",   "port": 9232, "host": "data.guoshuyufen.com"},
    {"name": "美团",   "port": 9233, "host": "waimaie.meituan.com"},
]
LOGIN_HINTS = ("login", "passport", "signin", "sso", "oauth")


def http_json(port: int, path: str, timeout: float = 4.0):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", headers={"Connection": "close"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def check_browser(target: dict) -> dict:
    res = {
        "name": target["name"], "port": target["port"],
        "alive": False, "target_tab": False, "login_ok": None, "detail": "",
    }
    try:
        http_json(target["port"], "/json/version")
        res["alive"] = True
    except Exception as e:  # 端口没起 / profile 没跑
        res["detail"] = f"CDP 端口不可达: {type(e).__name__}"
        return res
    try:
        tabs = http_json(target["port"], "/json/list")
        pages = [t for t in tabs if t.get("type") == "page"]
        res["pages"] = [
            {"title": (p.get("title") or "")[:60], "url": (p.get("url") or "")[:120]}
            for p in pages
        ][:8]
        hits = [p for p in pages if target["host"] in (p.get("url") or "")]
        if hits:
            res["target_tab"] = True
            # 只要存在一个非登录页的目标页标签即视为登录态可用；
            # 全部命中都是登录页才判掉登录（陈旧登录标签不算故障，仅提示）。
            good = [p for p in hits if not any(
                h in (p.get("url") or "").lower() for h in LOGIN_HINTS)]
            stale_login = len(good) < len(hits)
            if good:
                res["login_ok"] = True
                res["detail"] = f"目标页: {(good[0].get('url') or '')[:100]}"
                if stale_login:
                    # 2026-10-12 事故回写：旧逻辑把「陈旧登录标签」判为"不影响可用性"，
                    # 结果当天 08:29 误报 ok=true —— 而新会话早已被 302 到登录页：
                    # 陈旧登录标签是已渲染的 SPA，看着完好，实际不证明任何新会话可用。
                    # 按教训#1「保守排除盲区」：宁可提前报，不可漏报。
                    res["staleLoginTabs"] = len(hits) - len(good)
                    res["detail"] += f"（另有 {res['staleLoginTabs']} 个陈旧登录页标签）"
            else:
                res["login_ok"] = False
                res["detail"] = f"目标页全部为登录页: {(hits[0].get('url') or '')[:100]}"
        else:
            res["login_ok"] = False
            res["detail"] = f"无 {target['host']} 标签页（被关闭或掉登录后跳转）"
    except Exception as e:
        res["detail"] = f"列标签失败: {type(e).__name__}"
    return res


def check_wechat() -> dict:
    try:
        # -x 精确匹配主进程名，避免 WeChatAppEx 等助手进程造成假阳性
        out = subprocess.run(
            ["pgrep", "-x", "WeChat"], capture_output=True, text=True, timeout=5
        )
        running = out.returncode == 0
        pids = out.stdout.strip().splitlines()[:3]
        return {
            "name": "桌面微信", "alive": running,
            "detail": f"pid: {pids}" if running else "WeChat 主进程未运行",
        }
    except Exception as e:
        return {"name": "桌面微信", "alive": False, "detail": f"检查失败: {type(e).__name__}"}


def main() -> int:
    report = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "wechat": check_wechat(),
        "browsers": [check_browser(t) for t in TARGETS],
    }
    problems = []
    if not report["wechat"]["alive"]:
        problems.append("桌面微信进程未运行（登录态无法确认）")
    for b in report["browsers"]:
        if not b["alive"]:
            problems.append(f"{b['name']}(:{b['port']}) CDP 不可达")
        elif not b["target_tab"]:
            problems.append(f"{b['name']}(:{b['port']}) 无目标域名标签页")
        elif b["login_ok"] is False:
            problems.append(f"{b['name']}(:{b['port']}) 疑似掉登录（跳到登录页）")
        elif b.get("staleLoginTabs"):
            problems.append(
                f"{b['name']}(:{b['port']}) 存在 {b['staleLoginTabs']} 个陈旧登录页标签"
                f"——新会话可能已掉登录（建议跑 runtime/auth_keepalive.mjs 深度确认）")
    report["problems"] = problems
    report["ok"] = not problems
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
