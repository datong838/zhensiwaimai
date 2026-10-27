#!/usr/bin/env python3
"""Daily Jinsha new-store collection, record, and bounded WeChat delivery."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "records" / "new-store-identification"
RUNTIME = SKILL / ".runtime" / "runs"
WECHAT = ROOT / "skills" / "wechat-messaging" / "scripts"
WECHAT_POLICY = WECHAT.parent / "runtime-policy.json"
ADB = shutil.which("adb") or "adb"
PYTHON = Path("/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python")
GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
WORKFLOW_ID = "daily-new-stores-opening-to-wechat"
AUTHORIZATION_REF = "user-20260928-daily-new-stores-feibing-neo-ai"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DAY_RE = re.compile(r"^([0-3])\s*天$")


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def node_binary() -> Path:
    choices = []
    configured = os.environ.get('ZENSI_NODE')
    if configured:
        choices.append(Path(configured))
    try:
        director = json.loads((ROOT / 'runtime/skills_manifest.json').read_text())['interpreters']['node']
        if isinstance(director, str) and director:
            choices.append(Path(director))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    choices += [
        Path("/Users/ddt/.nvm/versions/node/v20.20.2/bin/node"),
        Path("/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"),
    ]
    found = shutil.which("node")
    if found:
        choices.append(Path(found))
    seen = set()
    for candidate in choices:
        if str(candidate) in seen:
            continue
        seen.add(str(candidate))
        if candidate.is_file():
            try:
                probe = subprocess.run([str(candidate), '--eval', 'process.stdout.write(typeof globalThis.WebSocket)'],
                                       capture_output=True, text=True, timeout=5, check=False)
                if probe.returncode == 0 and probe.stdout.strip() == 'function':
                    return candidate
            except (OSError, subprocess.TimeoutExpired):
                continue
    raise RuntimeError("node-websocket-runtime-unavailable")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate_collection(receipt: dict) -> list[dict]:
    if receipt.get("status") != "complete":
        raise ValueError("collection-not-complete")
    platforms = (("meituan", "美团"), ("taobao", "淘宝"))
    for key, label in platforms:
        item = receipt.get(key)
        if not isinstance(item, dict) or item.get("channel") != label:
            raise ValueError(f"channel-missing:{label}")
        total, size, pages = item.get("total"), item.get("size"), item.get("pages")
        if not all(type(value) is int and value >= 0 for value in (total, size, pages)) or size < 1:
            raise ValueError(f"pagination-invalid:{label}")
        if pages != (total + size - 1) // size or len(item.get("visited", [])) != pages:
            raise ValueError(f"pagination-incomplete:{label}")
        if sum(page.get("count", -1) for page in item["visited"]) != total:
            raise ValueError(f"row-count-incomplete:{label}")
        if label == "淘宝" and size != 50:
            raise ValueError("taobao-not-50-per-page")
    passes = receipt.get("taobaoPasses")
    if not isinstance(passes, list) or not 2 <= len(passes) <= 3:
        raise ValueError("taobao-recheck-missing")
    prior, current = passes[-2:]
    def identities(item: dict) -> set[tuple[str, str, str]]:
        return {(hit["channel"], hit["name"], hit["days"]) for hit in item["hits"]}
    def unresolved_identities(item: dict) -> set[tuple[str, str]]:
        return {(row["channel"], row["name"]) for row in item.get("unresolved", [])}
    if prior["total"] != current["total"] or identities(prior) != identities(current) or \
       unresolved_identities(prior) != unresolved_identities(current) or \
       current["total"] != receipt["taobao"]["total"] or identities(current) != identities(receipt["taobao"]):
        raise ValueError("taobao-recheck-unstable")
    hits = receipt.get("hits")
    if not isinstance(hits, list):
        raise ValueError("hits-invalid")
    source_hits = receipt["meituan"].get("hits", []) + receipt["taobao"].get("hits", [])
    if hits != source_hits:
        raise ValueError("hits-source-mismatch")
    unresolved = receipt.get("unresolved", [])
    if not isinstance(unresolved, list) or unresolved != receipt["meituan"].get("unresolved", []) + receipt["taobao"].get("unresolved", []):
        raise ValueError("unresolved-source-mismatch")
    if unresolved_identities(current) != unresolved_identities(receipt["taobao"]):
        raise ValueError("taobao-unresolved-source-mismatch")
    seen = set()
    for hit in hits:
        channel, name, days = hit.get("channel"), hit.get("name"), hit.get("days")
        if channel not in ("淘宝", "美团") or not isinstance(name, str) or not name.strip() or \
           not isinstance(days, str) or not DAY_RE.fullmatch(days.strip()):
            raise ValueError("hit-invalid")
        source = receipt["taobao" if channel == "淘宝" else "meituan"]
        page = hit.get("page")
        if type(page) is not int or not 1 <= page <= source["pages"]:
            raise ValueError("hit-page-invalid")
        identity = (channel, name.strip(), days.strip())
        if identity in seen:
            raise ValueError("hit-identity-ambiguous")
        seen.add(identity)
    for row in unresolved:
        channel, name, days = row.get("channel"), row.get("name"), row.get("days")
        source = receipt["taobao" if channel == "淘宝" else "meituan"] if channel in ("淘宝", "美团") else {}
        if channel not in ("淘宝", "美团") or not isinstance(name, str) or not name.strip() or days != "" or \
           type(row.get("page")) is not int or not 1 <= row["page"] <= source.get("pages", 0):
            raise ValueError("unresolved-row-invalid")
    return hits


def message_lines(hits: list[dict]) -> list[str]:
    return [f"{hit['channel']}  {hit['name'].strip()}  新店铺（开业{DAY_RE.fullmatch(hit['days'].strip()).group(1)}天）"
            for hit in hits]


def message_body(hits: list[dict]) -> str:
    """拼接**实际发送**的正文。

    必须用「  ；  」（中文全角分号、前后各 2 空格）而不是换行分隔：换行符会在 **Windows
    服务网关** 上被弄丢（不是微信输入框吞掉），多条命中到达对端后挤成一行、两家店首尾
    相连看不出边界——2026-10-02 大同实测反馈即为此问题。按大同最终要求用「  ；  」（中文
    全角分号）分隔后每条命中边界清晰、有分割感，且正文不再依赖换行符（网关丢换行属运输层
    问题，正文里不能出现 \\n）。
    """
    return "  ；  ".join(message_lines(hits))


def md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_report(day: str, receipt: dict, send: dict) -> str:
    hits = validate_collection(receipt)
    lines = [f"# {day} 新开店铺识别", "", "## 使用的 Rules", "",
             "- 美团先选「新店」，再逐店核对「店铺头像」列的开业天数；淘宝不设「新店」，按 50 条/页检查全部分页。",
             "- 仅开业 0、1、2、3 天命中；后续新发送每家一行，格式为「渠道  店铺名称  新店铺（开业X天）」。",
             "- 页面、分页、字段或发送结果不明时保留阻断与证据，不把未知写成无店或已发送。", "",
             "## 本日命中", "",
             "| 渠道 | 店铺名称 | 开业天数 | 来源页 |", "| --- | --- | --- | --- |"]
    lines += [f"| {hit['channel']} | {md_cell(hit['name'])} | {hit['days']} | 第{hit['page']}页 |" for hit in hits]
    if not hits:
        if receipt.get("unresolved"):
            lines.append("| — | 存在开业天数字段缺失，暂不能判断是否有新店 | — | — |")
        else:
            lines.append("| — | 本轮完整核验后无 0–3 天店铺 | — | — |")
    unresolved = receipt.get("unresolved") or []
    if unresolved:
        lines += ["", "## 待核对：开业天数为空", "",
                  "| 渠道 | 店铺名称 | 来源页 | 行 |", "| --- | --- | ---: | ---: |"]
        lines += [f"| {row['channel']} | {md_cell(row['name'])} | 第{row['page']}页 | {row['row']} |" for row in unresolved]
    suspended = receipt.get("suspended") or []
    if suspended:
        lines += ["", "## 已排除：暂停营业（确定性非新店，不计入待核对、不阻断发送）", "",
                  "| 渠道 | 店铺名称 | 来源页 | 行 |", "| --- | --- | ---: | ---: |"]
        lines += [f"| {row['channel']} | {md_cell(row['name'])} | 第{row['page']}页 | {row['row']} |" for row in suspended]
    lines += ["", "## 覆盖", "",
              "| 渠道 | 总行数 | 每页 | 已核页数 | 命中 |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for key, label in (("meituan", "美团"), ("taobao", "淘宝")):
        item = receipt[key]
        lines.append(f"| {label} | {item['total']} | {item['size']} | {item['pages']}/{item['pages']} | {len(item['hits'])} |")
    lines += ["", "## 微信发送", "",
              f"- 目标群：{GROUP}",
              f"- 通道：{send.get('channel', 'Windows 网关（main-wechat）')}",
              f"- 状态：{send.get('status', '未执行')}",
              f"- 正文：{(message_body(hits) if hits else '无命中，不发送')}",
              f"- 核验时间：{receipt.get('checkedAt', '未知')}（机器收据 UTC 时间）",
              "- 实时列表可能在翻页期间变动；本报告只代表该轮页面观察。"]
    if send.get("reason"):
        lines.append(f"- 阻断：{send['reason']}")
    return "\n".join(lines) + "\n"


def command_json(command: list[str], timeout: int) -> dict:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    try:
        output = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError) as error:
        raise RuntimeError(f"subprocess-no-json:{Path(command[1]).name}:{completed.returncode}") from error
    if not isinstance(output, dict):
        raise RuntimeError("subprocess-result-invalid")
    return output


def verified_send_counts(result: dict) -> dict:
    items = result.get("items") or []
    item = items[0] if items else {}
    transport = item.get("transport") or {}
    physical = transport.get("sendAttempts")
    if type(physical) is not int:
        physical = item.get("sendAttempts")
    return {"sendAttempts": physical,
            "reconcileSendAttempts": item.get("sendAttempts") if item.get("reconciled") else None}


def discover_mobile_device(run_dir: Path) -> tuple[Path, str]:
    """Bind this run to the sole currently discovered, policy-accepted phone."""
    current_policy = json.loads(WECHAT_POLICY.read_text(encoding="utf-8"))
    expected_hash = current_policy.get("deviceHash")
    if current_policy.get("userId") != 0 or not isinstance(expected_hash, str):
        raise RuntimeError("mobile-main-device-policy-missing")
    listed = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=15, check=False)
    if listed.returncode:
        raise RuntimeError("adb-device-discovery-failed")
    candidates = []
    for line in listed.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device" and not fields[0].startswith("emulator-"):
            if hashlib.sha256(fields[0].encode()).hexdigest()[:12] == expected_hash:
                candidates.append(fields[0])
    if len(candidates) != 1:
        raise RuntimeError("accepted-mobile-device-not-unique")
    serial = candidates[0]
    model = subprocess.run([ADB, "-s", serial, "shell", "getprop", "ro.product.model"],
                           capture_output=True, text=True, timeout=10, check=False)
    if model.returncode or model.stdout.strip() != "HLK-AL00":
        raise RuntimeError("accepted-mobile-model-mismatch")
    sys_path = str(WECHAT)
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import mobile_readiness
    ready = mobile_readiness.probe(serial, user_id=0)
    if not ready.get("ok") or ready.get("deviceHash") != expected_hash:
        raise RuntimeError("main-wechat-mobile-readiness-failed")
    serial_file = run_dir / "device.serial"
    with serial_file.open("x", encoding="utf-8") as stream:
        os.chmod(serial_file, 0o600)
        stream.write(serial)
        stream.flush()
        os.fsync(stream.fileno())
    return serial_file, expected_hash


def prior_day_send(day: str, digest: str | None = None) -> dict | None:
    """Read only canonical same-day text facts; never infer zero sends."""
    ledger = SKILL / '.runtime' / 'new-stores-send-ledger'
    channel = 'Windows 网关（main-wechat）'
    def blocked(reason):
        return {'status': 'blocked', 'reason': reason, 'sendAttempts': 0, 'channel': channel}
    if ledger.is_symlink():
        return blocked('prior-send-ledger-binding-mismatch')
    try:
        paths = sorted(p for p in ledger.iterdir() if p.name.startswith(day + '-') and p.suffix == '.json')
    except FileNotFoundError:
        return None
    except OSError:
        return blocked('prior-send-ledger-unreadable')
    if not paths:
        return None
    if len(paths) != 1:
        return blocked('same-day-payload-conflict-or-multiple-events')
    marker = paths[0]
    if marker.is_symlink():
        return blocked('prior-send-ledger-binding-mismatch')
    try:
        prior = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return blocked('prior-send-ledger-unreadable')
    if not isinstance(prior, dict):
        return blocked('prior-send-ledger-binding-mismatch')
    payloads = prior.get('payloads')
    if (prior.get('groupName') != GROUP or not isinstance(payloads, list) or len(payloads) != 1
            or not isinstance(payloads[0], dict) or not isinstance(payloads[0].get('text'), str)
            or not payloads[0]['text']):
        return blocked('prior-send-ledger-binding-mismatch')
    actual = hashlib.sha256(payloads[0]['text'].encode('utf-8')).hexdigest()
    if payloads[0].get('sha256') != actual or marker.name != f'{day}-{actual[:16]}.json':
        return blocked('prior-send-ledger-binding-mismatch')
    if digest is not None and digest != actual:
        return blocked('same-day-payload-conflict-or-multiple-events')
    if prior.get('verified') is True and prior.get('state') == 'verified':
        return {'status': '既有发送已验证', 'sendAttempts': 0,
                'priorSendAttempts': prior.get('sendAttempts'), 'channel': channel,
                'eventKey': marker.name, 'policyRestored': True}
    return {'status': 'unknown', 'reason': 'prior-attempt-requires-read-only-reconciliation',
            'sendAttempts': 0, 'channel': channel, 'eventKey': marker.name}


def run_send(hits: list[dict], day: str, run_dir: Path) -> dict:
    """Deliver the day's new-store hits to the FEIBING NEO AI数字员工 group via the
    Windows 10 driver gateway HTTP service (main-wechat desktop client on the Windows host).

    通道决策（大同 2026-09-30）：Mac 桌面微信停用、手机主微信不动 → 统一走 Windows 网关
    HTTP（与 jinsha / negative-reviews / top10 / taobao-appeals / ⑪ 共用同一条 WindowsAdapter
    出站通道）。本技能 workflow.py 不在封印清单内，直接复用 WindowsAdapter（正交补强，不触碰
    任何封印文件），用本技能 .runtime 下的「日级 + 载荷 sha256」去重台账保证幂等，落 receipt
    即视为已发送，后续同日本轮重跑不会再发。
    """
    runtime_path = str(Path(__file__).resolve().parents[4] / 'runtime')
    if runtime_path not in sys.path: sys.path.insert(0, runtime_path)
    from authorized_supplement import deliver_once
    supplement = deliver_once(WORKFLOW_ID, run_dir)
    if supplement is not None:
        return supplement | {'status': '已验证发送' if supplement.get('status') in ('verified','already_verified') else supplement.get('status','unknown')}
    text = message_body(hits)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ledger = SKILL / ".runtime" / "new-stores-send-ledger"
    ledger.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = ledger / f"{day}-{digest[:16]}.json"
    channel_label = "Windows 网关（main-wechat）"

    def existing_day_result() -> dict | None:
        return prior_day_send(day, digest)

    prior_result = existing_day_result()
    if prior_result is not None:
        return prior_result

    sys_path = str(WECHAT)
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    try:
        from wecom_adapter import WeComAdapter as WindowsAdapter  # 2026-10-23 channel switch
        from contract import Rejected
    except Exception as error:
        return {"status": "blocked", "reason": f"windows-adapter-import-failed:{error}",
                "sendAttempts": 0, "channel": channel_label}

    deadline = int(time.time()) + 600
    request = {"schemaVersion": 1, "groupName": GROUP,
               "items": [{"itemId": "new-stores", "type": "text", "text": text, "sha256": digest}],
               "context": {"workflowId": WORKFLOW_ID, "eventId": day, "accountAlias": "main-wechat",
                           "channel": "desktop", "deadlineAt": deadline}}
    grant = {"schemaVersion": 1, "accountAlias": "main-wechat", "groupName": GROUP,
             "channel": "desktop", "expiresAt": deadline, "authorizationRef": AUTHORIZATION_REF}
    try:
        adapter = WindowsAdapter()
        with adapter.session(request):
            prior_result = existing_day_result()
            if prior_result is not None:
                return prior_result
            preflight = adapter.preflight(request, run_dir / "windows-preflight")
            if not preflight.get("ok"):
                return {"status": "blocked", "reason": preflight.get("reason", "windows-preflight-failed"),
                        "sendAttempts": 0, "channel": channel_label}
            atomic_json(marker, {"bridgeVersion": 1, "state": "attempted", "groupName": GROUP,
                                "payloadType": "text", "payloads": [{"text": text, "sha256": digest}],
                                "sendAttempts": None, "verified": False})
            item = request["items"][0]
            result = adapter.send_one(request, item, run_dir / "windows-send", grant, deadline)
    except Rejected as error:
        return {"status": "blocked", "reason": f"windows-rejected:{error}",
                "sendAttempts": 0, "channel": channel_label}
    except Exception as error:
        return {"status": "unknown", "reason": f"windows-execution-error:{error}",
                "sendAttempts": None, "channel": channel_label}

    attempts = result.get("sendAttempts")
    if result.get("status") == "verified":
        receipt = {"bridgeVersion": 1, "ok": True, "verified": True, "state": "verified",
                   "groupName": GROUP, "payloadType": "text",
                   "payloads": [{"text": text, "sha256": digest}],
                   "sendAttempts": attempts, "newSendAttempts": 0, "reason": None,
                   "transport": result.get("transport"), "evidence": result.get("evidence"),
                   "verificationLevel": result.get("verificationLevel")}
        atomic_json(marker, receipt)
        return {"status": "已验证发送", "sendAttempts": attempts, "channel": channel_label,
                "eventKey": marker.name, "policyRestored": True}
    if result.get("status") == "unknown":
        return {"status": "unknown", "reason": result.get("reason", "windows-result-unknown"),
                "sendAttempts": attempts, "channel": channel_label, "eventKey": marker.name,
                "policyRestored": True}
    return {"status": "blocked", "reason": result.get("reason", "微信结果未通过验证"),
            "sendAttempts": attempts, "channel": channel_label, "eventKey": marker.name,
            "policyRestored": True}


def run(execute: bool) -> dict:
    day = now_local().date().isoformat()
    run_dir = RUNTIME / f"{day}-{time.time_ns()}"
    run_dir.mkdir(parents=True, mode=0o700)
    started = time.monotonic()
    receipt_path = run_dir / "collection.json"
    summary: dict = {"day": day, "status": "blocked", "sendAttempts": 0,
                     "runDir": str(run_dir), "reportPath": str(RECORDS / f"{day}_新开店铺识别.md")}
    try:
        if execute:
            runtime_path = str(ROOT / 'runtime')
            if runtime_path not in sys.path:
                sys.path.insert(0, runtime_path)
            from authorized_supplement import load_grant
            if load_grant(WORKFLOW_ID) is None:
                prior = prior_day_send(day)
                if prior is not None:
                    summary.update(status='complete' if prior['status'] == '既有发送已验证' else 'blocked',
                                   send=prior, reason=prior.get('reason'), stage='existing-delivery-readonly',
                                   elapsedMs=round((time.monotonic() - started) * 1000))
                    atomic_json(run_dir / 'workflow-summary.json', summary)
                    return summary
        collection = command_json([str(node_binary()), str(SKILL / "scripts" / "collector.mjs"),
                                   str(receipt_path)], 360)
        if collection.get("status") != "complete":
            detail = json.loads(receipt_path.read_text()) if receipt_path.is_file() else collection
            raise RuntimeError(detail.get("reason", "collection-blocked"))
        receipt = json.loads(receipt_path.read_text())
        hits = validate_collection(receipt)
        unresolved = receipt.get("unresolved") or []
        suspended = receipt.get("suspended") or []
        send = {"status": ("字段缺失，暂缓发送" if unresolved else ("无命中，不发送" if not hits else "待发送"))}
        report_path = Path(summary["reportPath"])
        atomic_text(report_path, render_report(day, receipt, send))
        summary.update(status="collected", hits=len(hits), unresolved=len(unresolved),
                       suspended=len(suspended), totalRows={
            "美团": receipt["meituan"]["total"], "淘宝": receipt["taobao"]["total"]})
        if unresolved:
            summary.update(status="blocked", reason="opening-days-missing", unresolvedRows=unresolved)
            atomic_text(report_path, render_report(day, receipt, send))
        elif hits and execute:
            send = run_send(hits, day, run_dir)
            atomic_text(report_path, render_report(day, receipt, send))
            summary.update(send=send, sendAttempts=send.get("sendAttempts"),
                           status="complete" if send["status"] in ("已验证发送", "既有发送已验证") else "blocked")
        elif not hits:
            summary["status"] = "complete"
        else:
            summary["status"] = "collected-only"
    except Exception as error:
        summary["reason"] = str(error)
        report_path = Path(summary["reportPath"])
        old = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
        history = f"\n## 既往阻断记录\n\n{old.strip()}\n" if old and "检查未完成" in old else ""
        atomic_text(report_path, f"# {day} 新开店铺识别\n\n检查未完成：{error}\n\n不得把未核验记为无新店。\n{history}")
    summary["elapsedMs"] = round((time.monotonic() - started) * 1000)
    atomic_json(run_dir / "workflow-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--execute", action="store_true")
    group.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    lock_path = SKILL / ".runtime" / "workflow.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "blocked", "reason": "workflow-already-running", "sendAttempts": 0}, ensure_ascii=False))
            return 1
        result = run(execute=args.execute)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in ("complete", "collected-only") else 1


if __name__ == "__main__":
    raise SystemExit(main())
