"""确定性动作收据。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import ActionResult


def write_receipt(result: ActionResult, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["receiptSha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path = output_dir / f"{result.action_id}.action-receipt.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
