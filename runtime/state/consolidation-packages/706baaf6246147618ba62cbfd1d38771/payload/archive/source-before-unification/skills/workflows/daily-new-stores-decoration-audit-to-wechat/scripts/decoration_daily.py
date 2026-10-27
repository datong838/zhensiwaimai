#!/usr/bin/env python3
"""Audit today's verified Taobao new-store hits for decoration (顶部招牌/店内海报)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import decoration_workflow as decoration

# 装修巡检读取开业流当天新店采集结果（跨目录复用，与 activity 流同源，非同一任务）
OPENING_SCRIPTS = Path(__file__).resolve().parents[2] / "daily-new-stores-opening-to-wechat" / "scripts"
if str(OPENING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(OPENING_SCRIPTS))
import workflow as new_stores

SCRIPTS = Path(__file__).resolve().parent

# 自愈闭环地基（2026-10-12 大同批准的下一波次 #1）：「已提醒未配置」跟踪表。
# 只登记不外发；escalation-due 的升级提醒须大同拍板后另行授权（当前无自动外发路径）。
WATCHLIST = decoration.RUNTIME / "watchlist.json"
ESCALATION_AFTER_DAYS = 3


def load_watchlist() -> dict:
    try:
        data = json.loads(WATCHLIST.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"schemaVersion": 1, "updatedDay": None, "entries": []}


def update_watchlist(shops: list[dict], day: str) -> dict:
    """按本次巡检结论增量维护跟踪表：
    - 有缺失且本次 verified/already_verified（或表内已是 alerted）⇒ alerted（firstAlertDay 记首次提醒日）
    - 有缺失但未发送（dry/gate blocked）⇒ pending-alert，不发提醒不计首次提醒日
    - 四项全 configured ⇒ 移出表并记 healed（自愈闭环的「康复」侧）
    - alerted 且距 firstAlertDay ≥3 天仍未配 ⇒ escalation-due（只登记，升级提醒须人工授权）
    - skipped/unknown 店不动表（避免用缺口数据污染跟踪结论）
    """
    data = load_watchlist()
    entries = {e["shopId"]: e for e in data["entries"]}
    summary = {"added": [], "updated": [], "healed": [], "escalationDue": []}
    today = datetime.now(decoration.LOCAL_TZ).date()
    for shop in shops:
        status = shop.get("targetStatus")
        shop_id = shop.get("shopId")
        if not isinstance(status, dict) or not shop_id:
            continue
        missing = [c for c in decoration.COMPONENTS if status.get(c) == "missing"]
        entry = entries.get(shop_id)
        if not missing:
            if entry:
                summary["healed"].append({"shopId": shop_id, "shopName": shop.get("sourceName"),
                                          "firstAlertDay": entry.get("firstAlertDay")})
                del entries[shop_id]
            continue
        alerted = shop.get("status") in ("verified", "already_verified") or (entry and entry.get("state") == "alerted")
        if entry:
            entry.update({"lastSeenMissingDay": day, "lastMissing": missing,
                          "lastSeenStatus": status, "shopName": shop.get("sourceName") or entry.get("shopName"),
                          "state": "alerted" if alerted else entry.get("state", "pending-alert")})
            summary["updated"].append(shop_id)
        else:
            entry = {"shopId": shop_id, "shopName": shop.get("sourceName"),
                     "firstAlertDay": day if alerted else None,
                     "lastSeenMissingDay": day, "lastMissing": missing, "lastSeenStatus": status,
                     "state": "alerted" if alerted else "pending-alert"}
            entries[shop_id] = entry
            summary["added"].append(shop_id)
        if entry["state"] == "alerted" and entry.get("firstAlertDay"):
            first = datetime.fromisoformat(entry["firstAlertDay"]).date()
            if (today - first).days >= ESCALATION_AFTER_DAYS:
                entry["state"] = "escalation-due"
                summary["escalationDue"].append({"shopId": shop_id, "shopName": entry["shopName"],
                                                 "missing": entry["lastMissing"]})
    data["entries"] = sorted(entries.values(), key=lambda e: e["shopId"])
    data["updatedDay"] = day
    decoration.atomic_json(WATCHLIST, data)
    return summary


def todays_source(day: str) -> tuple[Path, list[dict]]:
    candidates: list[tuple[datetime, Path, list[dict]]] = []
    for path in new_stores.RUNTIME.glob(f"{day}-*/collection.json"):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            hits = new_stores.validate_collection(receipt)
            if receipt.get("unresolved"):
                continue
            checked = datetime.fromisoformat(receipt["checkedAt"].replace("Z", "+00:00"))
            if checked.astimezone(decoration.LOCAL_TZ).date().isoformat() != day:
                continue
            candidates.append((checked, path, hits))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not candidates:
        raise ValueError("today-complete-new-store-receipt-missing")
    _, path, hits = max(candidates, key=lambda item: item[0])
    targets = [hit for hit in hits if hit["channel"] == "淘宝" and int(hit["days"].removesuffix("天")) <= 3]
    if len({hit["name"] for hit in targets}) != len(targets):
        raise ValueError("taobao-new-store-name-ambiguous")
    return path, targets


def reset_chain_seed() -> dict:
    """共享岗复位（与 activity 流同理由）：装修巡检会把 9230 留在 shop decorate 页，
    金鲨下载流的 isTaobaoSeedRecoveryUrl 要求页面落在 chain 前缀下才可 recoverable。
    「谁弄脏谁恢复」：巡检收尾把页面导航回 chain 数据中心。失败只记录，不改巡检状态。"""
    env = dict(os.environ, NODE_PATH=decoration.NODE_MODULES)
    try:
        proc = subprocess.run([str(decoration.NODE), str(SCRIPTS / "reset_chain_seed.mjs")],
                              env=env, capture_output=True, text=True, timeout=60, check=False)
        out = (proc.stdout or "").strip().splitlines()
        payload = json.loads(out[-1]) if out else {}
        if proc.returncode or payload.get("status") == "failed":
            return {"status": "failed", "reason": payload.get("reason") or (proc.stderr or "")[-200:]}
        return payload
    except Exception as error:  # 复位失败不拖垮巡检结果，仅落证据
        return {"status": "failed", "reason": str(error)[:200]}


def run(execute: bool) -> dict:
    day = datetime.now(decoration.LOCAL_TZ).date().isoformat()
    try:
        source, targets = todays_source(day)
    except ValueError as error:
        if str(error) != "today-complete-new-store-receipt-missing":
            raise
        scan = subprocess.run(
            [sys.executable, str(OPENING_SCRIPTS / "workflow.py"), "--collect-only"],
            capture_output=True, text=True, timeout=240, check=False,
        )
        if scan.returncode:
            raise RuntimeError(f"today-new-store-read-only-scan-failed:{scan.stdout[-300:]}") from error
        source, targets = todays_source(day)
    result = {"day": day, "source": str(source), "targetCount": len(targets), "shops": []}
    try:
        for hit in targets:
            run_dir = decoration.RUNTIME / "runs" / f"{day}-{time.time_ns()}"
            run_dir.mkdir(parents=True, mode=0o700)
            try:
                receipt = decoration.collect(run_dir, hit["name"])
                body = decoration.message(receipt, hit["name"])
                delivery = (decoration.deliver(receipt, run_dir, hit["name"]) if execute
                            else {"status": "ready" if body else "no-missing", "sendAttempts": 0})
                shop = {"sourceName": hit["name"], "shopId": receipt["shopId"],
                        "targetStatus": receipt["targetStatus"], "text": body,
                        "runDir": str(run_dir), **delivery}
            except Exception as error:
                # 2026-10-12 与 activity 流对齐的 skipped 语义：post-lease-busy / shop-not-operating /
                # shop-not-found / shop-search-timeout 均属业务/工位数据缺口，记 skipped 不算 unknown，
                # 不中断其余门店巡检。
                msg = str(error)
                if msg.startswith("decoration-collection-skipped:"):
                    shop = {"sourceName": hit["name"], "status": "skipped", "reason": msg,
                            "sendAttempts": 0, "runDir": str(run_dir)}
                else:
                    shop = {"sourceName": hit["name"], "status": "unknown", "reason": msg,
                            "sendAttempts": 0, "runDir": str(run_dir)}
            decoration.atomic_json(run_dir / "summary.json", shop)
            result["shops"].append(shop)
            if shop["status"] not in ("verified", "already_verified", "ready", "no-missing", "skipped"):
                break
    finally:
        # 自愈闭环跟踪表（只登记不外发；升级提醒须大同拍板）
        result["watchlist"] = update_watchlist(result["shops"], day)
        # 只要真正驱动过 9230（≥1 店采集）就复位共享岗，避免污染金鲨下载流的 seed 判据。
        if result["shops"]:
            result["seedReset"] = reset_chain_seed()
    result["status"] = ("complete" if len(result["shops"]) == len(targets)
                        and all(s["status"] in ("verified", "already_verified", "ready", "no-missing", "skipped")
                                for s in result["shops"]) else "unknown")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args.execute)
    except Exception as error:
        result = {"status": "unknown", "reason": str(error), "shops": []}
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "complete":
        sys.exit(1)


if __name__ == "__main__":
    main()
