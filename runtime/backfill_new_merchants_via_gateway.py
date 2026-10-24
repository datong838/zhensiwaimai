#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经 Windows 网关补发「新增商家」待发消息（不触碰 Mac 微信）。

背景：2026-10-09 新商家流被头 marker(疆麦尔椒麻鸡 unknown) 堵住，桥拒动后续 15 条。
大同 21:14 指令：走 Windows 服务网关完成工作。
证据前提：群回读已证实疆麦尔那条已发出（群成员称"截止到早上8点后面的都没推送"），故跳过它。

只做三件事：①按流程原 text 逐条发；②落证据 JSONL；③打印汇总。不改 cursor/不写 marker。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time

WXDIR = "/Users/ddt/work/projects/ai_agent/wechat-windows-driver"
sys.path.insert(0, WXDIR)

import wxsend  # noqa: E402
from client import WeChat  # noqa: E402

GROUP = "电销+直播攻坚组"
COLL = ("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/state/runs/"
        "daily-agent-new-merchants-to-wechat/20261009-210823/output/collection.json")
OUT = ("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/.local/runs/"
       "manual-gateway-backfill-20261009")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    msgs = json.load(open(COLL, encoding="utf-8"))["messages"]
    ip, token = wxsend.load_config()
    wx = WeChat(ip, token)
    h = wx.health()
    print("[gateway] %s route=%s ok=%s" % (ip, (h or {}).get("route"), (h or {}).get("ok")))
    if not (isinstance(h, dict) and h.get("ok")):
        print("[ABORT] 网关未就绪")
        return 2

    log_path = os.path.join(OUT, "evidence.jsonl")
    log = open(log_path, "a", encoding="utf-8")
    sent_ok = 0
    total = 0
    for i, m in enumerate(msgs):
        now = dt.datetime.now().isoformat(timespec="seconds")
        if i == 0:
            rec = {"idx": i, "merchantId": m["merchantId"], "name": m["merchantName"],
                   "action": "skip-already-delivered", "reason": "群回读证实 8:21 已落群",
                   "at": now, "text": m["text"]}
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.flush()
            print("[skip] %s —— 已发出，跳过（防重复）" % m["merchantName"])
            continue
        total += 1
        r = wxsend.send_with_retry(wx, GROUP, m["text"], is_file=False)
        ok = bool(r.get("ok"))
        sent_ok += 1 if ok else 0
        rec = {"idx": i, "merchantId": m["merchantId"], "name": m["merchantName"],
               "sha256": m.get("sha256"), "ok": ok, "receipt": r, "at": now,
               "text": m["text"], "channel": "windows-gateway", "route": (h or {}).get("route")}
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()
        print("[%s] %2d/%2d %s %s" % ("OK" if ok else "FAIL", total, len(msgs) - 1,
                                      m["merchantName"], "" if ok else str(r.get("error"))[:90]))
        time.sleep(2)
    log.close()
    print("\n== 汇总：成功 %d / 待发 %d ==" % (sent_ok, len(msgs) - 1))
    print("证据：%s" % log_path)
    return 0 if sent_ok == len(msgs) - 1 else 1


if __name__ == "__main__":
    sys.exit(main())
