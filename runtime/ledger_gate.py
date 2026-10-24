#!/usr/bin/env python3
"""台账发出前强制核对门（只读，不碰执行链路）。

用法:
    python3 runtime/ledger_gate.py 2026-10-04

铁律（2026-10-04 大同确认）:
  当日工作台账发出前必须跑本脚本；
  A 清单（enabled 日定时技能当日无任何 SUCCESS 记录）非空 → 不发台账；
  B 清单（当日有 FAILED 的技能）逐条看护定性后才可发。

判定口径:
  - 只认当天 record.json（runtime/run_history/<date>/）。
  - 成功等价（2026-10-06 对齐 E5 口径）:
      1) status == SUCCESS；或
      2) category == SKIPPED_IDEMPOTENT，且 fail_signal.idempotent_evidence 指向的
         marker 存在、state/verified 为真、交付时刻（收据 claimedAt/readbackAt，
         缺则文件 mtime）落在门检日期当天 —— 即「当日已 verified 外发、防重拒发」。
    证据链任一环不成立 ⇒ 不算成功（默认拒绝、失败关门），照常进 A 清单，
    绝不静默放行（防 marker 绑陈旧/占位载荷的真故障被当良性跳过）。
  - 每小时级技能（cadence_hours<=1）只要求当日至少一档成功等价。
  - 日定时技能（cadence_hours>1）同样只要求当日至少一档成功等价（防重拦截
    造成的当日后段 FAILED 不算缺口，由看护按 B 清单定性）。
"""
import glob
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "runtime", "skills_manifest.json")


def _load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _evidence_delivery_day(marker_path: str):
    """从 marker 收据提取交付时刻（epoch 秒）。优先收据时间戳，缺则文件 mtime。"""
    try:
        d = _load_json(marker_path)
    except Exception:
        return None
    ts = None
    items = (d.get("commonReceipt") or {}).get("items") or []
    for it in items:
        for key in ("readbackAt", "claimedAt", "verifiedAt"):
            v = it.get(key)
            if isinstance(v, (int, float)) and v > 0:
                ts = max(ts or 0, v)
    if not ts:
        ts = d.get("readbackAt") or d.get("claimedAt")
        if not isinstance(ts, (int, float)) or ts <= 0:
            import time
            try:
                ts = os.path.getmtime(marker_path)
            except OSError:
                return None
    from datetime import datetime as _dt
    return _dt.fromtimestamp(ts).strftime("%Y-%m-%d")


def _is_success_equivalent(record: dict, date_str: str) -> bool:
    """E5 口径成功等价：SUCCESS 直接过；SKIPPED_IDEMPOTENT 须验证当日 verified 证据。

    证据链（任一环不成立即 False，默认拒绝）:
      1. fail_signal.idempotent_evidence 指向的 marker 文件存在且可读；
      2. marker 的 state == "verified" 或 verified is True；
      3. 交付时刻（收据 readbackAt/claimedAt，缺则 mtime）的日期 == 门检日期。
    """
    status = str(record.get("status", "")).upper()
    if status == "SUCCESS":
        return True
    if str(record.get("category", "")).upper() != "SKIPPED_IDEMPOTENT":
        return False
    fs = record.get("fail_signal") or {}
    marker = fs.get("idempotent_evidence")
    if not marker or not isinstance(marker, str):
        return False
    if not os.path.isfile(marker):
        return False
    try:
        d = _load_json(marker)
    except Exception:
        return False
    state = d.get("state")
    verified = d.get("verified")
    if state != "verified" and verified is not True:
        return False
    return _evidence_delivery_day(marker) == date_str


def main(date_str: str) -> int:
    now = datetime.now()
    manifest = json.load(open(MANIFEST))
    skills = manifest.get("skills") or []
    if isinstance(skills, dict):
        skills = list(skills.values())
    enabled = [s for s in skills if s.get("enabled") and s.get("dev_state") == "active"]

    records = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "runtime", "run_history", date_str, "*--record.json"))):
        name = os.path.basename(p).replace("--record.json", "")
        skill = re.sub(r"--\d{8}-\d{6}$", "", name)
        try:
            d = json.load(open(p))
        except Exception:
            continue
        records.setdefault(skill, []).append(d)

    a_list, b_list, ok_list = [], [], []
    for s in sorted(enabled, key=lambda x: x.get("order", 99)):
        name = s["name"]
        cadence = s.get("cadence_hours", 24)
        rs = records.get(name, [])
        succ = [r for r in rs if _is_success_equivalent(r, date_str)]
        fails = [r for r in rs if str(r.get("status", "")).upper() == "FAILED"]
        row = {
            "skill": name,
            "cadence_hours": cadence,
            "runs": len(rs),
            "success": len(succ),
            "failed": len(fails),
        }
        via_e5 = sum(1 for r in succ if str(r.get("status", "")).upper() != "SUCCESS")
        if via_e5:
            row["via_e5_idempotent_evidence"] = via_e5
        if succ:
            ok_list.append(row)
        else:
            # 全天零成功：真红灯（防重拦截的前提是至少有一档历史成功被门控拒绝，
            # 但那种情况下 record 里也会有 SUCCESS 或无档；零成功零档也进 A）
            a_list.append(row)
        for r in fails:
            b_list.append({
                "skill": name,
                "time": (r.get("finished_at") or "")[11:16],
                "code": (r.get("fail_signal") or {}).get("code") or str(r.get("detail") or "")[:60],
            })

    extra_fails = sorted(set(records) - {s["name"] for s in enabled})

    verdict = "NO-GO" if a_list else "GO"
    report = {
        "date": date_str,
        "checkedAt": now.strftime("%H:%M:%S"),
        "verdict": verdict,
        "A_no_success_all_day": a_list,
        "B_failed_needs_triage": b_list,
        "C_ok": [
            {k: v for k, v in (("skill", r["skill"]), ("runs", r["runs"]),
                               ("via_e5_idempotent_evidence", r.get("via_e5_idempotent_evidence")))}
            for r in ok_list
        ],
        "D_nonenabled_records": extra_fails,
        "rule": "A 非空→不发台账；B 逐条定性（防重拦截/真故障）后才可发",
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    sys.exit(main(date))
