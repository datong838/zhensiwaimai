#!/usr/bin/env python3
"""单店单指标投递器 —— 把已采到的截图发进该店的企业微信群。

设计红线（每一条都对应一次真实事故或铁律）
------------------------------------------
1. **默认不发**：不带 `--commit` 只打印计划，零网关接触（连 WindowsAdapter 都不构造）。
2. **fail-closed**：群名缺失 / 发送闸制动 / 无授权引用 ⇒ `blocked`，**绝不猜群、绝不改投**。
   错发的代价是「A 店数据进了 B 店群」（生产事故），比漏发严重得多。
3. **三态分明**：`verified`（可结束）/ `unknown`（可能已发，**禁重发**）/ `blocked`（确定没发，可重试）。
   把 blocked 写成 unknown 会让干净失败被永久卡死；反过来更危险。
4. **marker 事件账本**：`.runtime/events/{day}-metrics-{shopId}-{metric}.json`。
   verified 后重跑直接 `already_verified`，连网关都不碰。
5. **送达才记账**：只有 verified 才回写台账（`ledger_ops record --apply`），
   避免「发了没记账」和「记了没发」两种假账。

用法
----
    # 1) 先看计划（默认，不发）
    python scripts/deliver_metric.py --shop-id 694471 --metric M01 \
        --image .runtime/captures/M01_shop694471_20261020105905.png

    # 2) 真发（必须显式带授权引用，闸门默认放行但可一键制动）
    python scripts/deliver_metric.py --shop-id 694471 --metric M01 --image ... \
        --commit --authorization-ref "大同-2026-10-21-指标流灰度"

    # 3) 一键制动 / 恢复
    echo '{"armed": false}' > .runtime/send_gate.json

退出码
------
    0  正常（already_verified / planned / verified / unknown 均为 0，区别看 JSON）
    2  参数错误
    3  blocked（未覆盖 / 闸门制动 / 无授权 / 网关确定拒绝）——可修可重试
    4  marker 与当前载荷冲突（同店同指标同日内容变了），硬阻断
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
WF = HERE.parent
RUNTIME = WF / ".runtime"
EVENTS = RUNTIME / "events"
RUNS = RUNTIME / "runs"
GATE = RUNTIME / "send_gate.json"
GROUP_MAP = RUNTIME / "group_map.json"
CATALOG = WF / "docs" / "metrics_catalog.json"

WINDOWS_SCRIPTS = WF.parents[1] / "wechat-messaging" / "scripts"  # skills/wechat-messaging/scripts
WORKFLOW_ID = "daily-store-metrics-rotation-to-wechat"
DEFAULT_DEADLINE = 600


def atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def gate_state() -> dict:
    """发送闸。默认放行（铁律：默认放行可一键制动），文件存在且 armed=false 则制动。"""
    if not GATE.exists():
        return {"armed": True, "source": "default"}
    try:
        doc = json.loads(GATE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"armed": False, "source": "unreadable", "reason": str(exc)}
    return {"armed": bool(doc.get("armed", True)), "source": str(GATE)}


def metric_of(mid: str) -> dict:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    for m in cat.get("metrics", []):
        if m.get("id") == mid:
            return m
    print(f"{mid} 未在指标字典登记，拒绝投递（现有：{[m.get('id') for m in cat.get('metrics', [])]}）",
          file=sys.stderr)
    raise SystemExit(2)

def resolve_group(shop_id: str, explicit: str) -> tuple[str, str]:
    """返回 (群名, 来源)。三档：命令行 > group_map.json。都没有返回 ('', 'missing')。"""
    if explicit.strip():
        return explicit.strip(), "cli"
    if not GROUP_MAP.exists():
        return "", "missing:no-group-map"
    doc = json.loads(GROUP_MAP.read_text(encoding="utf-8"))
    hit = (doc.get("map") or {}).get(str(shop_id))
    if hit:
        return str(hit).strip(), "group-map"
    return "", "missing:not-mapped"


def marker_path(day: str, shop_id: str, mid: str) -> pathlib.Path:
    return EVENTS / f"{day}-metrics-{shop_id}-{mid}.json"


def ledger_record(shop_id: str, shop_name: str, mid: str, group: str,
                  image: pathlib.Path, receipt: str, day: str) -> dict:
    """verified 之后回写台账。失败只告警，不回滚已送达的事实。"""
    cmd = [sys.executable, str(HERE / "ledger_ops.py"), "record",
           "--store-id", str(shop_id), "--metric", mid, "--result", "verified",
           "--group", group, "--shot", str(image), "--date", day, "--apply"]
    if shop_name:
        cmd += ["--store-name", shop_name]
    if receipt:
        cmd += ["--receipt", receipt]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}  # 防 shim 劫持（教训 #16/#71）
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = (proc.stdout or "").strip().splitlines()
    return {"exit": proc.returncode,
            "decision": json.loads(out[-1]) if out and out[-1].startswith("{") else (out[-1] if out else ""),
            "stderr": (proc.stderr or "").strip()[:300]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="单店单指标投递（默认 dry-run）")
    ap.add_argument("--shop-id", required=True)
    ap.add_argument("--shop-name", default="")
    ap.add_argument("--metric", required=True, help="M01..M20")
    ap.add_argument("--image", required=True)
    ap.add_argument("--group", default="", help="企业微信群名；省略则查 .runtime/group_map.json")
    ap.add_argument("--date", default="", help="业务日期 YYYY-MM-DD，默认今天")
    ap.add_argument("--commit", action="store_true", help="真正发送（默认只出计划）")
    ap.add_argument("--authorization-ref", default="", help="授权引用（谁在何时批的），--commit 必填")
    ap.add_argument("--force-blocked", action="store_true", help="marker=blocked 时允许重试（默认也允许）")
    ap.add_argument("--deadline", type=int, default=DEFAULT_DEADLINE)
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    a = ap.parse_args(argv)

    sid = str(a.shop_id).strip()
    mid = a.metric.strip().upper()
    day = a.date or date.today().isoformat()
    image = pathlib.Path(a.image).expanduser()
    out = {"shopId": sid, "metric": mid, "day": day, "image": str(image), "commit": a.commit}

    if not image.exists():
        out |= {"status": "blocked", "reason": f"image-not-found:{image}"}
        print(json.dumps(out, ensure_ascii=False))
        return 3
    size = image.stat().st_size
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    out |= {"imageBytes": size, "sha256": sha[:16]}
    if size < 8 * 1024:
        out |= {"status": "blocked", "reason": f"image-too-small:{size}B（疑似截图失败，缺图不硬发）"}
        print(json.dumps(out, ensure_ascii=False))
        return 3

    metric = metric_of(mid)
    group, group_src = resolve_group(sid, a.group)
    out |= {"group": group, "groupSource": group_src, "metricName": metric.get("name")}

    # ---- 幂等：先看账本，后做任何事 ----
    marker = marker_path(day, sid, mid)
    if marker.exists():
        prior = json.loads(marker.read_text(encoding="utf-8"))
        out["priorState"] = prior.get("state")
        prior_sha = prior.get("sha256")
        if prior_sha and prior_sha != sha:
            # 同一天同一店同一指标，图变了：不是「已发」也不是「可重发」，必须人看。
            out |= {"status": "conflict", "reason": "same-day-payload-conflict",
                    "priorSha256": str(prior_sha)[:16]}
            print(json.dumps(out, ensure_ascii=False))
            return 4
        if prior.get("state") == "verified":
            out |= {"status": "already_verified", "reason": "当日已送达，不重发"}
            print(json.dumps(out, ensure_ascii=False))
            return 0
        if prior.get("state") == "unknown":
            out |= {"status": "unknown",
                    "reason": "此前尝试可能已发出但无回执 ⇒ 绝不重发，只做只读对账"}
            print(json.dumps(out, ensure_ascii=False))
            return 0
        # attempted / blocked ⇒ 允许继续（blocked 是确定没发）
        out["retryFrom"] = prior.get("state")

    if not group:
        out |= {"status": "blocked", "reason": f"group-unresolved:{group_src}",
                "hint": "先在 docs/店铺群映射_待填_2026-10.xlsx 填群名，或传 --group"}
        print(json.dumps(out, ensure_ascii=False))
        return 3

    gate = gate_state()
    out["gate"] = gate
    if not gate["armed"]:
        out |= {"status": "blocked", "reason": "send-disarmed"}
        print(json.dumps(out, ensure_ascii=False))
        return 3

    if not a.commit:
        out |= {"status": "planned",
                "action": f"image → 群「{group}」",
                "nextCommand": (f"python scripts/deliver_metric.py --shop-id {sid} --metric {mid} "
                                f"--image {image} --commit --authorization-ref \"<谁批的>\""),
                "note": "dry-run：未接触网关，未写 marker"}
        print(json.dumps(out, ensure_ascii=False))
        return 0

    if not a.authorization_ref.strip():
        out |= {"status": "blocked", "reason": "authorization-ref-required",
                "hint": "真发必须写明授权引用（谁在何时批的），不许匿名外发"}
        print(json.dumps(out, ensure_ascii=False))
        return 3

    # ---- 真发：复用技能内既有 WindowsAdapter（不另造发送链路）----
    if str(WINDOWS_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(WINDOWS_SCRIPTS))
    try:
        from windows_adapter import WindowsAdapter  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        out |= {"status": "blocked", "reason": f"adapter-unavailable:{exc}"}
        print(json.dumps(out, ensure_ascii=False))
        return 3

    run_dir = RUNS / f"{day}-{sid}-{mid}"
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = int(time.time()) + a.deadline
    item = {"itemId": f"metrics-{sid}-{mid}", "type": "image",
            "name": image.name, "path": str(image)}
    request = {"schemaVersion": 1, "groupName": group, "items": [item],
               "context": {"workflowId": WORKFLOW_ID,
                           "eventId": f"{day}-metrics-{sid}-{mid}",
                           "accountAlias": "main-wechat", "channel": "desktop",
                           "deadlineAt": deadline}}
    grant = {"schemaVersion": 1, "accountAlias": "main-wechat", "groupName": group,
             "channel": "desktop", "expiresAt": deadline,
             "authorizationRef": a.authorization_ref.strip()}

    atomic_json(marker, {"state": "attempted", "event": f"{day}-metrics-{sid}-{mid}",
                         "sha256": sha, "groupName": group, "metric": mid,
                         "image": str(image), "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    try:
        adapter = WindowsAdapter()
        result = adapter.send_one(request, item, run_dir, grant, deadline)
    except Exception as exc:  # noqa: BLE001  异常=可能已发出，按 unknown 记账，绝不重试
        atomic_json(marker, {"state": "unknown", "sha256": sha, "groupName": group,
                             "metric": mid, "reason": f"exception:{exc}",
                             "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        out |= {"status": "unknown", "reason": f"exception:{exc}"}
        print(json.dumps(out, ensure_ascii=False))
        return 0

    status = result.get("status")
    evidence = result.get("evidence") or {}
    receipt = str(evidence.get("messageId") or evidence.get("anchor") or "")
    if status == "verified":
        atomic_json(marker, {"state": "verified", "event": f"{day}-metrics-{sid}-{mid}",
                             "sha256": sha, "groupName": group, "metric": mid,
                             "image": str(image), "sendAttempts": result.get("sendAttempts"),
                             "verificationLevel": result.get("verificationLevel"),
                             "receipt": receipt,
                             "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        out |= {"status": "verified", "sendAttempts": result.get("sendAttempts"),
                "verificationLevel": result.get("verificationLevel"), "receipt": receipt}
        out["ledger"] = ledger_record(sid, a.shop_name, mid, group, image, receipt, day)
        print(json.dumps(out, ensure_ascii=False))
        return 0

    state = "blocked" if status == "blocked" else "unknown"
    atomic_json(marker, {"state": state, "sha256": sha, "groupName": group, "metric": mid,
                         "reason": result.get("reason"),
                         "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    out |= {"status": status or "unknown", "reason": result.get("reason"),
            "sendAttempts": result.get("sendAttempts")}
    print(json.dumps(out, ensure_ascii=False))
    return 3 if state == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
