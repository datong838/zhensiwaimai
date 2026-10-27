#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「品牌商运营组织树」采集到的店铺池 JSON 灌进台账 Excel（真数据，无 mock）。

上游：scripts/collect_shop_pool_brand.mjs --out .runtime/store_pool_brand.json
产物：docs/全店铺运营指标商家反馈台账_YYYY-MM.xlsx
  · 店铺池：店铺ID / 店铺名称 / 营业状态 / 运营组织 / 企业微信群名称 / 采集日期 / 备注
  · 指标进度：每店一行（店铺ID/名称/群名 + M01..M20 空格 + 已完成数公式）

口径（2026-10-20 大同定案）：店铺池只认品牌商 9230「运营组织」树下「营业中」的店铺，
不再并入旧系统（wmPoiId）名单。两套 ID 不互通，混用只会制造缺口。

用法：
  env -u PYTHONPATH /Users/ddt/.workbuddy/binaries/python/envs/default/bin/python \
    scripts/store_pool_to_ledger.py --json .runtime/store_pool_brand.json --month 2026-10
参数：
  --include-closed  连带非营业中店铺一起写入（默认只写营业中，非营业中只出现在统计行）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from openpyxl.styles import Font

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_ledger_template import BODY_FONT, BORDER, build  # noqa: E402

NOTE_FONT = Font(name="微软雅黑", size=9, color="993C1D")
OPEN_RE = re.compile(r"营业中")


def to_int(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None


def cn_time(raw: str) -> str:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(raw)[:16].replace("T", " ")


def fill(wb, shops: list[dict], collected: str, include_closed: bool, gmap: dict | None = None) -> tuple[list, dict]:
    pool, prog = wb["店铺池"], wb["指标进度"]
    day = collected.split(" ")[0]
    gmap = gmap or {}

    open_shops = [s for s in shops if OPEN_RE.search(s.get("status") or "")]
    rows = shops if include_closed else open_shops

    seen, dup = set(), []
    for i, s in enumerate(rows, start=2):
        sid = to_int(s.get("shopId"))
        if sid in seen:
            dup.append(sid)
        seen.add(sid)
        name = (s.get("shopName") or "").strip()
        status = (s.get("status") or "").strip() or "—"
        group = (gmap.get(str(sid)) or "").strip() if sid is not None else ""
        vals = [
            sid,
            name,
            status,
            (s.get("orgPath") or s.get("orgLabel") or "").strip() or "—",
            group,                                     # 企业微信群名称：来自 group_map.json
            day,
            "" if group else ("待映射群名" if OPEN_RE.search(status) else "非营业中，本期不发"),
        ]
        for c, v in enumerate(vals, start=1):
            cell = pool.cell(row=i, column=c, value=v)
            cell.font = BODY_FONT
            cell.border = BORDER
            if c == 1:
                cell.number_format = "0"

        for c, v in enumerate([sid, name, ""], start=1):
            cell = prog.cell(row=i, column=c, value=v)
            cell.font = BODY_FONT
            cell.border = BORDER
            if c == 1:
                cell.number_format = "0"
        prog.cell(row=i, column=24, value=f"=COUNTA(D{i}:W{i})").font = BODY_FONT

    dist = {}
    for s in shops:
        k = (s.get("status") or "（空）").strip()
        dist[k] = dist.get(k, 0) + 1

    orgs = sorted({(s.get("orgLabel") or "").strip() for s in shops if (s.get("orgLabel") or "").strip()})
    mapped = sum(1 for r in rows if (gmap.get(str(to_int(r.get("shopId")))) or "").strip())
    note = wb["说明"]
    r = note.max_row + 2
    note.cell(row=r, column=2,
              value=f"本次装载：采集于 {collected}　店铺总数 {len(shops)}　写入 {len(rows)} 行（营业中 {len(open_shops)}）").font = NOTE_FONT
    note.cell(row=r + 1, column=2,
              value="状态分布 " + "、".join(f"{k} {v}" for k, v in sorted(dist.items(), key=lambda x: -x[1]))).font = NOTE_FONT
    note.cell(row=r + 2, column=2,
              value=f"覆盖运营组织 {len(orgs)} 个；企业微信群名已映射 {mapped}/{len(rows)}"
                    + ("（缺群名的店不会发送）" if mapped < len(rows) else "（全部可发送）")).font = NOTE_FONT
    return dup, dist


def main(argv=None):
    here = pathlib.Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--month", default="2026-10")
    ap.add_argument("--out", default="")
    ap.add_argument("--include-closed", action="store_true")
    ap.add_argument("--group-map", default="", help="resolve_group_map.py 产出的 group_map.json，填企业微信群名称列")
    a = ap.parse_args(argv)

    doc = json.loads(pathlib.Path(a.json).read_text())
    shops = doc.get("shops") or doc.get("rows") or []
    if not shops:
        print("ERR empty shops", file=sys.stderr)
        return 3

    gmap = {}
    if a.group_map:
        gp = pathlib.Path(a.group_map)
        if not gp.exists():
            print(f"WARN 群映射文件不存在：{gp}（本次不填群名）", file=sys.stderr)
        else:
            gmap = json.loads(gp.read_text()).get("map") or {}

    out = pathlib.Path(a.out) if a.out else here.parent / "docs" / f"全店铺运营指标商家反馈台账_{a.month}.xlsx"
    build(out, a.month)
    wb = load_workbook(out)
    collected = cn_time(doc.get("collectedAt") or doc.get("collected_at") or "")
    dup, dist = fill(wb, shops, collected, a.include_closed, gmap)
    wb.save(out)

    # 重建是从空白结构起的，『指标字典』只有占位、『规则清单』可能缺失
    # ⇒ 保存后立刻按 catalog 回填，避免「重建一次就把字典清空」这个反复踩的坑
    try:
        from sync_metrics_catalog import sync_one as sync_dict
        from sync_global_rules import write_sheet as sync_rules
        from sync_user_rules import write_sheet as sync_user

        cat = json.loads((here.parent / "docs" / "metrics_catalog.json").read_text())
        by_id = {m["id"]: m for m in cat.get("metrics", [])}
        filled = sync_dict(out, by_id)
        n_rules = sync_rules(out, cat.get("global_rules") or [])
        got, total = sync_user(out, cat.get("user_rules") or [], 20)
        print(f"字典已回填 {filled}/20　规则清单 {n_rules} 条　你的规则 {got}/{total}")
    except Exception as exc:  # 回填失败不能吞掉主产物，但必须喊出来
        print(f"WARN 回填字典/规则失败：{exc}（台账已生成，请手动跑 sync_metrics_catalog.py / sync_global_rules.py / sync_user_rules.py）", file=sys.stderr)

    digest = hashlib.sha256(out.read_bytes()).hexdigest()[:16]
    opens = sum(1 for s in shops if OPEN_RE.search(s.get("status") or ""))
    print(f"OK {out}")
    print(f"shops={len(shops)} open={opens} written={len(shops) if a.include_closed else opens} dup_ids={len(dup)}")
    print("status: " + json.dumps(dist, ensure_ascii=False))
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
