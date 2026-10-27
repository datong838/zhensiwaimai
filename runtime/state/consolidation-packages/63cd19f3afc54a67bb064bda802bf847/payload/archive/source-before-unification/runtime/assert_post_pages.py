#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""post-pages-assert: 只读校验 9230/9232/9233 岗位后台 Chrome 的「页面健康」。

背景：各岗位采集流通过 localhost CDP 连「后台专用 Chrome」：
  9230 淘宝品牌商（淘宝闪购商家版） / 9231 淘宝服务商 / 9232 金鲨（臻肆外卖运营） /
  9233 美团（商家IM客服工作台）。
9231 的拉起与页面校验已由 bg-chrome-up.sh + 看护 D 段覆盖；本脚本补齐
**9230/9232/9233 的只读健康断言**（D2），用于每小时看护早发现「页面掉了/被导航走/掉登录」。

判据：每个端口的 /json/list 里，必须存在至少一个 type=page、
标题含期望关键词、URL 含期望片段的目标页。
输出末行恒为 `post-pages-assert: ALL PASS` 或 `post-pages-assert: FAIL ...`。

⚠ 纯只读：只发 HTTP GET /json/list，不点页面、不关页面、不重开、不发送微信、不写台账。
   本脚本**不做任何复位**（复位=对生产页的写操作，须大同裁决；见下）。
复位参考（仅在人工确认后执行，且须确认无流在跑）：
  美团 9233 有专用复位自动化（17:00/15:00 档前 + 台账后），优先用它们。
"""
from __future__ import annotations
import json
import sys
import urllib.request

# 端口 → (期望标题关键词, 期望 URL 片段, 岗位说明)
EXPECTED = {
    9230: ("淘宝闪购商家版", "shop.ele.me", "淘宝品牌商"),
    9232: ("臻肆外卖运营", "guoshuyufen.com", "金鲨"),
    9233: ("美团商家IM客服工作台", "waimaie.meituan.com", "美团"),
}


def _get_json(url: str, timeout: float = 5.0):
    """无代理直连（绕过环境里的 HTTP_PROXY，避免被沙箱代理截胡成 404/502）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def match_page(pages, want_title: str, want_url: str):
    """纯函数：在 /json/list 结果里找目标页。命中返回 (title, url)，否则 None。

    命中条件（三者齐备）：type=='page' 且 标题含 want_title 且 URL 含 want_url。
    """
    if not isinstance(pages, list):
        return None
    for pg in pages:
        if not isinstance(pg, dict) or pg.get("type") != "page":
            continue
        t = str(pg.get("title") or "")
        u = str(pg.get("url") or "")
        if want_title in t and want_url in u:
            return (t, u)
    return None


def page_titles(pages):
    """纯函数：列出全部 type=='page' 的标题（供诊断输出）。"""
    if not isinstance(pages, list):
        return []
    return [str(p.get("title") or "")[:32] for p in pages
            if isinstance(p, dict) and p.get("type") == "page"]


def main() -> int:
    fails = []
    for port, (want_title, want_url, role) in EXPECTED.items():
        url = "http://127.0.0.1:%d/json/list" % port
        try:
            pages = _get_json(url)
        except Exception as exc:  # noqa: BLE001
            print("  [FAIL] %d %s: CDP 不可达 (%s)" % (port, role, type(exc).__name__))
            fails.append("%d(%s):cdp-unreachable" % (port, role))
            continue
        if not isinstance(pages, list):
            print("  [FAIL] %d %s: /json/list 非数组" % (port, role))
            fails.append("%d(%s):bad-json-list" % (port, role))
            continue
        hit = match_page(pages, want_title, want_url)
        if hit:
            print("  [ OK ] %d %s: 标题=%s url=%s" % (port, role, hit[0], hit[1][:60]))
        else:
            print("  [FAIL] %d %s: 未找到期望页（期望 标题~%r url~%r；实际页=%s）"
                  % (port, role, want_title, want_url, page_titles(pages)))
            fails.append("%d(%s):page-mismatch" % (port, role))

    if fails:
        print("\npost-pages-assert: FAIL " + ", ".join(fails))
        print("提示：页面失配先按铁律「关页重开」复位再定性站点改版；"
              "复位属生产页写操作，请先确认无流在跑（runtime/state/live_steps/ 为空）后由人工/专用自动化执行。")
        return 1
    print("\npost-pages-assert: ALL PASS")
    return 0


def _selftest() -> int:
    """hermetic 自测：只验纯函数判据（不打 CDP、不接触真实浏览器）。"""
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  [%s] %s" % ("OK" if good else "FAIL", label))

    # 正例：目标页在
    pages = [
        {"type": "other", "title": "x", "url": "y"},
        {"type": "page", "title": "淘宝闪购商家版", "url": "https://melody.shop.ele.me/app/x"},
        {"type": "page", "title": "别的页", "url": "https://example.com"},
    ]
    check("正例-命中目标页", match_page(pages, "淘宝闪购商家版", "shop.ele.me"),
          ("淘宝闪购商家版", "https://melody.shop.ele.me/app/x"))
    # 负例：标题对但 URL 不对 ⇒ 不命中（防「同标题不同站」误判）
    check("负例-标题对URL不对", match_page(pages, "淘宝闪购商家版", "waimaie.meituan.com"), None)
    # 负例：登录页（标题变了）⇒ 不命中
    login = [{"type": "page", "title": "淘宝闪购服务商平台 - 登录", "url": "https://open.shop.ele.me/login"}]
    check("负例-登录页不误判", match_page(login, "淘宝闪购服务商平台", "open.shop.ele.me/manager/base/home"), None)
    # 负例：非数组 / 空 ⇒ None（不得抛异常）
    check("负例-非数组", match_page({"a": 1}, "x", "y"), None)
    check("负例-空列表", match_page([], "x", "y"), None)
    # page_titles 只列 page
    check("page_titles 只列page", page_titles(pages), ["淘宝闪购商家版", "别的页"])

    print("assert-post-pages selftest: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
