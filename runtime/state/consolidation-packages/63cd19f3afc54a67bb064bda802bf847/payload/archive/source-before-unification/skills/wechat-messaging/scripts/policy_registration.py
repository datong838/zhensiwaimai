#!/usr/bin/env python3
"""Atomically register one explicitly authorized, short-lived executor scope."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from contract import Rejected, check_grant, normalize, request_digest
from ledger import atomic_json, read_json


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "runtime-policy.json"
MAX_SCOPE_SECONDS = 2 * 60 * 60


def prepare(request_path: Path, authorization_path: Path, output_dir: Path) -> dict:
    """Register exactly one validated request. This function never opens WeChat."""
    started = time.monotonic()
    result = {"ok": False, "action": "prepare-policy", "status": "blocked",
              "sendAttempts": 0, "runtimeModelDecisions": 0, "review": []}

    def stage(name, fn):
        tick = time.monotonic()
        row = {"stage": name, "status": "running", "pitfalls": []}
        result["review"].append(row)
        try:
            value = fn()
            row["status"] = "completed"
            return value
        except Exception as error:
            row.update(status="failed", pitfalls=[str(error)])
            raise
        finally:
            row["elapsedMs"] = round((time.monotonic() - tick) * 1000)

    try:
        request = stage("请求规范化", lambda: normalize(read_json(request_path)))
        grant = stage("授权摘要核验", lambda: check_grant(request, read_json(authorization_path)))
        expiry = grant["expiresAt"]
        now = time.time()
        if expiry - now > MAX_SCOPE_SECONDS or request["context"]["deadlineAt"] > expiry:
            raise Rejected("policy-scope-expiry-invalid")
        current = stage("读取当前策略", lambda: read_json(POLICY))
        if not isinstance(current, dict):
            raise Rejected("runtime-policy-invalid")
        policy = current | {
            "schemaVersion": 1,
            "mode": "acceptance",
            "groupName": request["groupName"],
            "requestDigests": [request_digest(request)],
            "authorizationRef": grant["authorizationRef"],
            "expiresAt": expiry,
        }
        stage("原子登记策略", lambda: atomic_json(POLICY, policy))
        stored = stage("策略回读", lambda: read_json(POLICY))
        expected = (policy["groupName"], policy["requestDigests"], policy["authorizationRef"], policy["expiresAt"])
        actual = (stored.get("groupName"), stored.get("requestDigests"), stored.get("authorizationRef"), stored.get("expiresAt"))
        if actual != expected:
            raise Rejected("runtime-policy-readback-mismatch")
        result.update(ok=True, status="prepared", requestDigest=request_digest(request),
                      groupName=request["groupName"], expiresAt=expiry)
    except Exception as error:
        result["reason"] = str(error)
    finally:
        result["elapsedMs"] = round((time.monotonic() - started) * 1000)
        output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        receipt = output_dir / "receipt.json"
        atomic_json(receipt, result)
        result["receiptPath"] = str(receipt)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prepare")
    parser.add_argument("--request", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.prepare != "prepare":
        parser.error("action must be prepare")
    result = prepare(Path(args.request), Path(args.authorization), Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
