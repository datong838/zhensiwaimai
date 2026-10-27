#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_login 状态判定 + 监理闭环看板解析（纯文件/字符串处理，不触网）。
入参: 4 个端口的 /json/list 抓取文件(顺序 9230 9231 9232 9233) + war_room.json 路径
      ENUM_FAIL 或空文件 => 该端口浏览器挂。
输出: 一行 JSON 摘要（stations / browser_down / login_red / war_* / summary）。
"""
import json, sys, datetime, os


def load_list(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except Exception:
        return None
    if not raw or raw == "ENUM_FAIL":
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict):
        data = data.get("result", data.get("data", []))
    if not isinstance(data, list):
        return None
    urls = []
    for t in data:
        if isinstance(t, dict) and t.get("type") == "page":
            u = t.get("url", "")
            if u:
                urls.append(u)
    return urls


def judge(port, urls):
    if urls is None:
        return "DOWN", "枚举失败/浏览器挂（curl 不可达）"
    if port == "9230":
        dash = any("melody.shop.ele.me" in u and ("activity__myActivity" in u or "dashboard" in u or "app/chain" in u) and "/login" not in u for u in urls)
        login = any("melody.shop.ele.me" in u and "/login" in u for u in urls)
        if dash:
            return "GREEN", "melody.shop.ele.me 商家版主页在位"
        if login:
            return "RED", "melody.shop.ele.me/login 在位且无 dashboard（疑似掉登录）"
        return "CHECK", "无 melody dashboard 也无 /login（疑似被导航离开，需人工确认）"
    if port == "9231":
        dash = any("open.shop.ele.me" in u and "/manager" in u and "/login" not in u for u in urls)
        login = any("open.shop.ele.me" in u and "/login" in u for u in urls)
        if dash:
            return "GREEN", "open.shop.ele.me/manager 服务商后台在位"
        if login:
            return "RED", "open.shop.ele.me/login 在位且无 manager（疑似掉登录）"
        return "CHECK", "无 open.shop.ele.me manager 也无 /login"
    if port == "9232":
        dash = any("data.guoshuyufen.com" in u and "/login" not in u for u in urls)
        login = any("data.guoshuyufen.com" in u and "/login" in u for u in urls)
        if dash:
            return "GREEN", "data.guoshuyufen.com 金鲨业务后台在位"
        if login:
            return "RED", "data.guoshuyufen.com/login 在位且无后台（疑似掉登录）"
        return "CHECK", "无 guoshuyufen 后台也无 /login"
    if port == "9233":
        dash = any("waimaie.meituan.com" in u and "imworkbench" in u and "/login" not in u for u in urls)
        login = any("waimaie.meituan.com" in u and "/login" in u for u in urls)
        stray = any("workbuddy.cn" in u for u in urls)
        note = "；含 workbuddy.cn 异物残留页(可按手册清理)" if stray else ""
        if dash:
            return "GREEN", "waimaie.meituan.com/imworkbench 美团IM在位" + note
        if login:
            return "RED", "waimaie.meituan.com/login 在位且无 imworkbench（疑似掉登录）"
        return "CHECK", "无 meituan imworkbench 也无 /login"
    return "CHECK", "未知端口"


def main():
    argv = sys.argv[1:]
    port_files = argv[:4]
    war_path = argv[4] if len(argv) > 4 else ""
    ports = ["9230", "9231", "9232", "9233"]
    names = {"9230": "taobao-brand", "9231": "taobao-agent-service", "9232": "jinsha", "9233": "meituan-im"}
    stations = {}
    browser_down = []
    login_red = []
    for i, p in enumerate(ports):
        urls = load_list(port_files[i]) if i < len(port_files) else None
        st, detail = judge(p, urls)
        stations[p] = {"name": names[p], "status": st, "detail": detail}
        if st == "DOWN":
            browser_down.append(p)
        elif st == "RED":
            login_red.append(p)

    war_breached = []
    war_overdue = []
    if war_path and os.path.exists(war_path):
        try:
            with open(war_path, encoding="utf-8") as f:
                war = json.load(f)
            items = war.get("items", {})
            now = datetime.datetime.now()
            for k, v in items.items():
                stt = v.get("status")
                ask = (v.get("ask") or "")[:240]
                if stt == "breached":
                    war_breached.append({"key": k, "ask": ask})
                elif stt == "awaiting_you":
                    dl = v.get("sla_deadline")
                    if dl:
                        try:
                            dlt = datetime.datetime.fromisoformat(dl)
                            if dlt < now:
                                war_overdue.append({"key": k, "ask": ask, "sla": dl})
                        except Exception:
                            pass
        except Exception as e:
            stations["_war_error"] = str(e)

    # 汇总行
    parts = []
    for p in ports:
        s = stations[p]
        parts.append(f"{p}({s['name']}):{s['status']}")
    summary = " | ".join(parts)
    if browser_down:
        summary += f" | BROWSER_DOWN={','.join(browser_down)}"
    if login_red:
        summary += f" | LOGIN_RED={','.join(login_red)}"
    if war_breached:
        summary += f" | WAR_BREACHED={len(war_breached)}"
    if war_overdue:
        summary += f" | WAR_OVERDUE={len(war_overdue)}"

    out = {
        "stations": stations,
        "browser_down": browser_down,
        "login_red": login_red,
        "war_breached": war_breached,
        "war_overdue": war_overdue,
        "summary": summary,
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
