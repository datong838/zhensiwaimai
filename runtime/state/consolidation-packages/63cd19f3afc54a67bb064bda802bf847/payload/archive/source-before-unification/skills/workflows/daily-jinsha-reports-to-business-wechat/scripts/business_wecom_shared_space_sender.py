#!/usr/bin/env python3
"""Business pipeline adapter for the fixed WeCom WeDrive shared space."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ENTERPRISE = "上海臻肆文化传播有限公司"
SPACE = "金鲨昨日双平台日报业务群"
AUTHORIZATION = "zhensi-business-wecom-jinsha-daily-v1"
CONTROLLER = Path(__file__).with_name("wecom_shared_space.py")
STATE_ROOT = Path(__file__).resolve().parents[4] / ".local/state/jinsha-report-wecom"
INTERNAL_INVOCATION = "business-workflow-executor-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_items(receipt: Path) -> tuple[str, list[dict]]:
    value = json.loads(receipt.read_text())
    business_date = str(value.get("businessDate") or "")
    items = []
    for platform in ("meituan", "taobao"):
        item = value.get("files", {}).get(platform, {})
        file = Path(item.get("file", "")).resolve()
        name = str(item.get("name") or file.name)
        expected = f"{'美团外卖日报' if platform == 'meituan' else '淘宝闪购日报'}_{business_date}.xlsx"
        if not file.is_file() or name != expected or file.name != expected or item.get("sha256") != sha256(file) or item.get("size") != file.stat().st_size:
            raise RuntimeError(f"wecom-build-file-binding-mismatch:{platform}")
        items.append({"platform": platform, "name": name, "file": str(file), "size": file.stat().st_size, "sha256": sha256(file)})
    return business_date, items


def main() -> int:
    if os.environ.get("JINSHA_WORKFLOW_INTERNAL") != INTERNAL_INVOCATION:
        print(json.dumps({"ok": False, "reason": "direct-stage-invocation-forbidden"}, ensure_ascii=False))
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-receipt", required=True)
    parser.add_argument("--send-receipt", required=True)
    parser.add_argument("--enterprise", required=True)
    parser.add_argument("--space", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--authorization")
    parser.add_argument("--deadline-unix")
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args()
    result = {"ok": False, "channel": "wecom", "targetType": "wedrive-shared-space", "targetName": args.space, "sent": []}
    try:
        if args.enterprise != ENTERPRISE or args.space != SPACE:
            raise RuntimeError("wecom-business-binding-mismatch")
        if args.execute and args.authorization != AUTHORIZATION:
            raise RuntimeError("wecom-standing-authorization-missing")
        business_date, items = load_items(Path(args.build_receipt))
        identity = hashlib.sha256((business_date + "\n" + SPACE + "\n" + "\n".join(item["name"] for item in items)).encode()).hexdigest()
        marker = STATE_ROOT / "attempts" / f"{identity}.json"
        output = Path(args.send_receipt).resolve().parent / "wecom-shared-space"
        mode = "preflight" if args.preflight_only else ("verify" if args.verify_only else "upload")
        command = [sys.executable, str(CONTROLLER), "--mode", mode, "--enterprise", args.enterprise, "--space", args.space,
                   "--attempt-marker", str(marker), "--artifacts", str(output)]
        for item in items:
            command.extend(["--file", item["file"]])
        # Initial conversion plus two deterministic moves can take longer than
        # a read-only replay, but must remain inside the 180-second workflow SLA.
        proc = subprocess.run(command, capture_output=True, text=True, timeout=150)
        controller = json.loads(proc.stdout.strip().splitlines()[-1])
        result.update({"controller": controller, "fileState": controller.get("fileState"), "uploadAttempts": controller.get("uploadAttempts", 0)})
        if proc.returncode or controller.get("ok") is not True:
            raise RuntimeError(controller.get("reason", "wecom-controller-failed"))
        result["ok"] = True
        result["businessDate"] = business_date
        result["sent"] = items if (args.preflight_only or controller.get("confirmed")) else []
        result["deliveryAction"] = "preflight" if args.preflight_only else ("import" if controller.get("uploadAttempts") == 1 else "readback-noop")
        result["preflightOnly"] = args.preflight_only
    except Exception as error:
        result["reason"] = str(error)
    Path(args.send_receipt).parent.mkdir(parents=True, exist_ok=True)
    Path(args.send_receipt).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
