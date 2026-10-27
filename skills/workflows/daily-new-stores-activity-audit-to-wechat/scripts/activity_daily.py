#!/usr/bin/env python3
"""Audit today's verified Taobao new-store hits for three required activities."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import activity_workflow as activity

# 活动巡检读取开业流当天新店采集结果（跨目录复用，非同一任务）
OPENING_SCRIPTS = Path(__file__).resolve().parents[2] / "daily-new-stores-opening-to-wechat" / "scripts"
if str(OPENING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(OPENING_SCRIPTS))
import workflow as new_stores

SCRIPTS = Path(__file__).resolve().parent


def collect_with_search_recovery(run_dir: Path, name: str) -> dict:
    try:
        return activity.collect(run_dir, name)
    except Exception as error:
        if str(error) != 'activity-collection-skipped:shop-search-timeout':
            raise
        retry_dir = run_dir / 'search-retry-1'
        retry_dir.mkdir(mode=0o700)
        activity.atomic_json(run_dir / 'search-recovery.json', {
            'reason': str(error), 'maxCollectionAttempts': 2, 'sendAttempts': 0,
            'retryDirectory': str(retry_dir)})
        return activity.collect(retry_dir, name)


def todays_source(day: str) -> tuple[Path, list[dict]]:
    candidates: list[tuple[datetime, Path, list[dict]]] = []
    for path in new_stores.RUNTIME.glob(f"{day}-*/collection.json"):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            hits = new_stores.validate_collection(receipt)
            if receipt.get("unresolved"):
                continue
            checked = datetime.fromisoformat(receipt["checkedAt"].replace("Z", "+00:00"))
            if checked.astimezone(activity.LOCAL_TZ).date().isoformat() != day:
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
    """2026-10-11 共享岗复位：巡检采集会把 9230 留在 shop 活动页（chain 前缀之外），
    金鲨下载流的 isTaobaoSeedRecoveryUrl 因此判 0 个 recoverable（当日 13:09 实败）。
    「谁弄脏谁恢复」：巡检收尾把页面导航回 chain 数据中心。尽力而为：失败只记录，不改巡检状态。"""
    env = dict(os.environ, NODE_PATH=activity.NODE_MODULES)
    try:
        proc = subprocess.run([str(activity.NODE), str(SCRIPTS / "reset_chain_seed.mjs")],
                              env=env, capture_output=True, text=True, timeout=60, check=False)
        out = (proc.stdout or "").strip().splitlines()
        payload = json.loads(out[-1]) if out else {}
        if proc.returncode or payload.get("status") == "failed":
            return {"status": "failed", "reason": payload.get("reason") or (proc.stderr or "")[-200:]}
        return payload
    except Exception as error:  # 复位失败不拖垮巡检结果，仅落证据
        return {"status": "failed", "reason": str(error)[:200]}


def run(execute: bool) -> dict:
    day = datetime.now(activity.LOCAL_TZ).date().isoformat()
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
            run_dir = activity.RUNTIME / "runs" / f"{day}-{time.time_ns()}"
            run_dir.mkdir(parents=True, mode=0o700)
            try:
                receipt = collect_with_search_recovery(run_dir, hit["name"])
                body = activity.message(receipt, hit["name"])
                delivery = (activity.deliver(receipt, run_dir, hit["name"]) if execute
                            else {"status": "ready" if body else "no-missing", "sendAttempts": 0})
                shop = {"sourceName": hit["name"], "shopId": receipt["shopId"],
                        "targetStatus": receipt["targetStatus"], "text": body,
                        "runDir": str(run_dir), **delivery}
            except Exception as error:
                # Only explicit nonoperating evidence is a completed skip.
                # Store absence requires its original notice; transient failures remain pending.
                msg = str(error)
                if msg == "activity-collection-skipped:shop-not-found:未搜索到店铺":
                    receipt = activity.not_found_receipt(hit, msg)
                    body = activity.message(receipt, hit["name"])
                    delivery = (activity.deliver(receipt, run_dir, hit["name"]) if execute
                                else {"status": "ready", "sendAttempts": 0})
                    shop = {"sourceName": hit["name"], "days": hit["days"],
                            "inspectionOutcome": receipt["inspectionOutcome"], "recordNote": receipt["recordNote"],
                            "text": body, "runDir": str(run_dir), **delivery}
                    activity.atomic_json(run_dir / "store-not-found.json", receipt)
                elif msg in ('activity-collection-skipped:shop-not-operating:暂停营业',
                             'activity-collection-skipped:shop-not-operating:已下线'):
                    shop = {"sourceName": hit["name"], "status": "skipped", "reason": msg,
                            "sendAttempts": 0, "runDir": str(run_dir)}
                elif msg == 'activity-collection-skipped:shop-search-timeout':
                    shop = {'sourceName': hit['name'], 'status': 'retry-required', 'reason': msg,
                            'sendAttempts': 0, 'runDir': str(run_dir)}
                elif msg == 'activity-collection-skipped:post-lease-busy':
                    shop = {'sourceName': hit['name'], 'status': 'skipped-busy', 'reason': msg,
                            'sendAttempts': 0, 'runDir': str(run_dir)}
                else:
                    shop = {"sourceName": hit["name"], "status": "unknown", "reason": msg,
                            "sendAttempts": 0, "runDir": str(run_dir)}
            activity.atomic_json(run_dir / "summary.json", shop)
            result["shops"].append(shop)
            if shop["status"] not in ("verified", "already_verified", "ready", "no-missing", "skipped", 'retry-required'):
                break
    finally:
        # 只要真正驱动过 9230（≥1 店采集）就复位共享岗，避免污染金鲨下载流的 seed 判据。
        stop_reasons = [s.get('reason', '').lower() for s in result['shops']]
        unsafe_reset = any(any(token in reason for token in ('post-lease-busy', 'login', '验证码', '滑块', '风险', 'risk'))
                           for reason in stop_reasons)
        if result["shops"] and not unsafe_reset:
            result["seedReset"] = reset_chain_seed()
    result["status"] = ("complete" if len(result["shops"]) == len(targets)
                        and all(s["status"] in ("verified", "already_verified", "ready", "no-missing", "skipped")
                                for s in result["shops"]) else "unknown")
    if result['status'] != 'complete':
        finished = {s['sourceName'] for s in result['shops']
            if s['status'] in ('verified', 'already_verified', 'ready', 'no-missing', 'skipped')}
        result['recoveryRequired'] = [hit['name'] for hit in targets if hit['name'] not in finished]
        result['reason'] = next((s.get('reason') or 'inspection-not-complete' for s in result['shops']
            if s['status'] not in ('verified', 'already_verified', 'ready', 'no-missing', 'skipped')), 'inspection-not-complete')
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
