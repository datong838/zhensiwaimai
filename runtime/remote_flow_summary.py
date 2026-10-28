#!/usr/bin/env python3
"""Read a formally provided cross-machine three-flow summary without side effects."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EFFECTIVE_DATE = "2026-10-29"
OWNER = "另一台电脑"
GLOBAL_TOTAL = 27
LOCAL_LEDGER_IDENTITIES = 24
REMOTE_FLOWS = {
    "daily-store-metrics-rotation-to-wechat": "商家经营指标互动",
    "coupon-issue-task-flow": "精准营销发优惠券",
    "store-inspection": "每周外卖巡店",
}
ALLOWED_STATUSES = {"completed", "pending", "failed", "unknown"}
MAX_FILE_BYTES = 64 * 1024
MAX_TEXT_LENGTH = 500


def summary_path(day: str, root: Path = ROOT) -> Path:
    return Path(root) / "runtime/state/remote-flow-summary" / f"{day}.json"


def _placeholder_rows(reason: str) -> list[dict]:
    return [
        {
            "name": name,
            "ledger_name": ledger_name,
            "owner": OWNER,
            "status": "unknown",
            "done": False,
            "mark": "❔",
            "state": "异机摘要未核实",
            "evidence_summary": "",
            "reason": reason,
        }
        for name, ledger_name in REMOTE_FLOWS.items()
    ]


def _display_text(value: str) -> str:
    return " ".join(value.replace("|", "\\|").splitlines()).strip()


def _base(day: str, state: str, rows: list[dict], *, source: str = "", errors=None) -> dict:
    done = sum(row["done"] for row in rows)
    return {
        "business_date": day,
        "effective": day >= EFFECTIVE_DATE,
        "global_total": GLOBAL_TOTAL if day >= EFFECTIVE_DATE else LOCAL_LEDGER_IDENTITIES,
        "local_ledger_identities": LOCAL_LEDGER_IDENTITIES,
        "remote_flow_count": len(rows),
        "remote_done": done,
        "remote_state": state,
        "nonblocking_local_execution": True,
        "source": source,
        "errors": list(errors or []),
        "rows": rows,
    }


def _validate(value, day: str) -> list[str]:
    errors = []
    if not isinstance(value, dict):
        return ["summary-not-object"]
    if value.get("schemaVersion") != 1:
        errors.append("schema-version-invalid")
    if value.get("businessDate") != day:
        errors.append("business-date-mismatch")
    if value.get("owner") != OWNER:
        errors.append("owner-mismatch")
    provided_at = value.get("providedAt")
    if not isinstance(provided_at, str) or not provided_at.strip():
        errors.append("provided-at-missing")
    else:
        try:
            dt.datetime.fromisoformat(provided_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("provided-at-invalid")
    flows = value.get("flows")
    if not isinstance(flows, list):
        return errors + ["flows-not-list"]
    names = [flow.get("name") for flow in flows if isinstance(flow, dict)]
    if len(flows) != len(REMOTE_FLOWS):
        errors.append("flow-count-invalid")
    if len(names) != len(flows):
        errors.append("flow-not-object")
    if len(names) != len(set(names)):
        errors.append("flow-name-duplicate")
    if set(names) != set(REMOTE_FLOWS):
        errors.append("flow-set-mismatch")
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        name = flow.get("name")
        status = flow.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"status-invalid:{name}")
        evidence = flow.get("evidenceSummary")
        if status == "completed" and (not isinstance(evidence, str) or not evidence.strip()):
            errors.append(f"completed-evidence-missing:{name}")
        if evidence is not None and not isinstance(evidence, str):
            errors.append(f"evidence-summary-invalid:{name}")
        if isinstance(evidence, str) and len(evidence) > MAX_TEXT_LENGTH:
            errors.append(f"evidence-summary-too-long:{name}")
        note = flow.get("note")
        if note is not None and not isinstance(note, str):
            errors.append(f"note-invalid:{name}")
        if isinstance(note, str) and len(note) > MAX_TEXT_LENGTH:
            errors.append(f"note-too-long:{name}")
    return errors


def read_customer_scope(day: str, root: Path = ROOT) -> dict:
    """Return a display-only global scope; missing/invalid summaries never raise."""
    try:
        dt.date.fromisoformat(day)
    except (TypeError, ValueError):
        raise ValueError("day-must-be-iso-date")
    if day < EFFECTIVE_DATE:
        return _base(day, "not_applicable", [])
    path = summary_path(day, root)
    if not path.exists() and not path.is_symlink():
        return _base(
            day,
            "missing_nonblocking",
            _placeholder_rows("对方摘要未提供；不阻断本机24流到点执行"),
            source=str(path),
        )
    if path.is_symlink():
        return _base(
            day,
            "invalid_nonblocking",
            _placeholder_rows("对方摘要路径不得为符号链接；不推测完成"),
            source=str(path),
            errors=["summary-symlink-rejected"],
        )
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return _base(
                day,
                "invalid_nonblocking",
                _placeholder_rows("对方摘要文件超出上限；不推测完成"),
                source=str(path),
                errors=["summary-file-too-large"],
            )
    except OSError as exc:
        return _base(
            day,
            "invalid_nonblocking",
            _placeholder_rows("对方摘要文件无法读取；不推测完成"),
            source=str(path),
            errors=[f"summary-stat-invalid:{type(exc).__name__}"],
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _base(
            day,
            "invalid_nonblocking",
            _placeholder_rows("对方摘要无法解析；不推测完成"),
            source=str(path),
            errors=[f"json-invalid:{type(exc).__name__}"],
        )
    errors = _validate(value, day)
    if errors:
        return _base(
            day,
            "invalid_nonblocking",
            _placeholder_rows("对方摘要未通过契约校验；不推测完成"),
            source=str(path),
            errors=errors,
        )
    by_name = {flow["name"]: flow for flow in value["flows"]}
    rows = []
    for name, ledger_name in REMOTE_FLOWS.items():
        flow = by_name[name]
        status = flow["status"]
        done = status == "completed"
        rows.append(
            {
                "name": name,
                "ledger_name": ledger_name,
                "owner": OWNER,
                "status": status,
                "done": done,
                "mark": "✅" if done else "❌" if status == "failed" else "⏳" if status == "pending" else "❔",
                "state": {
                    "completed": "对方摘要已完成",
                    "pending": "对方摘要待完成",
                    "failed": "对方摘要失败",
                    "unknown": "对方摘要未知",
                }[status],
                "evidence_summary": _display_text(flow.get("evidenceSummary") or ""),
                "reason": _display_text(flow.get("note") or flow.get("evidenceSummary") or "对方未附加说明"),
            }
        )
    return _base(day, "provided_valid", rows, source=str(path))


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    print(json.dumps(read_customer_scope(day), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
