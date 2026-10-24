#!/usr/bin/env python3
"""淘宝闪购「门店经营任务完成率按小组统计」：采集两页 → 按门店ID关联运营人 → 明细 Excel + 统计图 → 发运营群。

数据源（9231 服务商平台 open.shop.ele.me）：
  1) 代运营 → 运营效果分析 → 直接点「数据下载」（不加筛选，全量；含 门店ID、经营任务完成率）
  2) 门店分配 → 外卖店 → 已分配门店 → 选公司级根角色 → 下载数据（含 门店ID、运营人）
关联：以 门店ID 为键 vlookup，把「运营人」并入运营效果数据 → 「<日期>运营-店铺经营任务完成率明细.xlsx」。
统计：按「运营人」分组，对「经营任务完成率」求平均值 → 白底加粗彩色图（同日先发明细、再发图）。
发送：经 Windows 网关发到「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」（与参考流同群）。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))  # stats_card 同目录

SKILL = Path(__file__).resolve().parents[1]
RUNTIME = SKILL / ".runtime" / "taskrate"
EVENTS = RUNTIME / "events"
RUNS = RUNTIME / "runs"
# verified 快照区（2026-10-19 部分送达续传修复）：产物送达 verified 时把字节快照进
# 固定区。openpyxl 的 xlsx 内嵌时间戳 + zipfile 条目时间戳（save 时强制刷新 modified）
# ⇒ 同输入重生成字节必变 ⇒ 与已 verified marker 的 sha256 永远失配 ⇒ 整单
# same-event-payload-conflict 死锁。快照回退是账本语义的正解：当日已 verified 的产物
# 就是当日权威，重生成不算数。
SNAPSHOTS = RUNTIME / "verified-snapshots"
COLLECTOR = Path(__file__).with_name("task_collector.mjs")
NODE = Path("/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
NODE_MODULES = "/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
WINDOWS_SCRIPTS = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts")

GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
WORKFLOW_ID = "daily-store-task-completion-ops"
AUTHORIZATION_REF = "user-20261013-daily-store-task-completion-windows-gateway"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
ARM_FILE = RUNTIME / "SEND_ARMED.json"        # 显式放行（当日有效）
DISARM_FILE = RUNTIME / "SEND_DISARMED.json"  # 制动文件：存在即禁止外发

ID_COLUMN = "门店ID"
RATE_COLUMN = "经营任务完成率"
OWNER_COLUMN = "运营人"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def arm_state() -> dict:
    """发送闸：默认放行；存在 SEND_DISARMED.json 则制动（零外发）。"""
    if DISARM_FILE.exists():
        return {"armed": False, "mode": "disarmed"}
    return {"armed": True, "mode": "default-auto"}


def set_arm(armed: bool) -> dict:
    ARM_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if armed:
        DISARM_FILE.unlink(missing_ok=True)
        atomic_json(ARM_FILE, {"armed": True, "at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds")})
        return {"armed": True, "mode": "armed"}
    ARM_FILE.unlink(missing_ok=True)
    atomic_json(DISARM_FILE, {"armed": False, "at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds")})
    return {"armed": False, "mode": "disarmed"}


# ---------------------------------------------------------------- 采集

def collect(run_dir: Path) -> dict:
    outdir = run_dir / "downloads"
    outdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = dict(os.environ, NODE_PATH=NODE_MODULES)
    # 全量运营效果导出慢，采集超时给足 12 分钟（manifest 侧 timeout 同步放大）。
    proc = subprocess.run([str(NODE), str(COLLECTOR), str(outdir)], env=env,
                          capture_output=True, text=True, timeout=720, check=False)
    payload = {}
    for line in reversed((proc.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    if proc.returncode or payload.get("status") != "complete":
        code = payload.get("code") or "taskrate-collect-unknown"
        reason = payload.get("reason") or (proc.stderr or "")[-250:]
        raise RuntimeError(f"{code}:{reason}")
    return payload


# ---------------------------------------------------------------- 读表

def _norm_id(value) -> str:
    return str(value).strip().strip('"').strip()


def _unzip_if_needed(path: Path) -> Path:
    """站点大数据量导出可能给 zip；解开取第一份表格。"""
    if path.suffix.lower() != ".zip":
        return path
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        for name in names:
            if Path(name).suffix.lower() in (".csv", ".xlsx", ".xls", ".txt"):
                target = path.parent / ("effect_" + Path(name).name)
                target.write_bytes(archive.read(name))
                return target
    raise ValueError("effect-zip-has-no-table")


def read_effect(path: Path) -> tuple[list[str], list[dict]]:
    """读运营效果导出（CSV 多编码 / xlsx 都兜住），返回 (表头, 行字典列表)。"""
    path = _unzip_if_needed(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        import openpyxl
        workbook = openpyxl.load_workbook(path, data_only=True)
        sheet = workbook[workbook.sheetnames[0]]
        rows = [[cell for cell in row] for row in sheet.iter_rows(values_only=True)]
    else:
        raw = path.read_bytes()
        text = None
        for encoding in ("utf-8-sig", "gbk", "utf-16"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("effect-decode-failed")
        rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("effect-empty")
    header = [str(h).strip().strip('"') for h in rows[0]]
    if ID_COLUMN not in header:
        raise ValueError("effect-missing-shop-id-column")
    if RATE_COLUMN not in header:
        raise ValueError("effect-missing-task-completion-column")
    data = []
    for row in rows[1:]:
        if not row or not any(str(cell).strip() for cell in row):
            continue
        padded = list(row) + [""] * (len(header) - len(row))
        data.append(dict(zip(header, padded)))
    return header, data


def read_alloc(path: Path) -> dict[str, str]:
    import openpyxl
    workbook = openpyxl.load_workbook(path, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    iterator = sheet.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(iterator)]
    if ID_COLUMN not in header or OWNER_COLUMN not in header:
        raise ValueError("alloc-missing-required-columns")
    i_id, i_owner = header.index(ID_COLUMN), header.index(OWNER_COLUMN)
    mapping: dict[str, str] = {}
    for row in iterator:
        if not row or row[i_id] is None:
            continue
        mapping[_norm_id(row[i_id])] = (str(row[i_owner]).strip() if row[i_owner] is not None else "")
    return mapping


def _rate_scale(values: list[float]) -> str:
    """站点导出里完成率是小数（0.83）还是百分数（83.3）：按整列最大值判一次，全列同尺。"""
    return "fraction" if values and max(abs(v) for v in values) <= 1.0 else "percent"


def _parse_rate(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "").replace("％", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------- 组装

def build_report(run_dir: Path, day: str) -> dict:
    from stats_card import UNASSIGNED, compute_stats, render_card

    downloads = run_dir / "downloads"
    effect_cands = sorted(downloads.glob("effect.*"))
    alloc_cands = sorted(downloads.glob("alloc.*"))
    if not effect_cands:
        raise ValueError("effect-download-missing")
    if not alloc_cands:
        raise ValueError("alloc-download-missing")
    header, data = read_effect(effect_cands[0])
    alloc = read_alloc(alloc_cands[0])
    if not data:
        return {"rows": 0, "matched": 0, "unmatched": 0, "path": None, "stats": [],
                "statsPath": None, "groups": []}

    # 完成率整列定标一次，再把小数统一换成百分数（避免 0.83 与 83.33 混在一张图里）
    raw_rates = [_parse_rate(row.get(RATE_COLUMN)) for row in data]
    numeric = [value for value in raw_rates if value is not None]
    scale = _rate_scale(numeric)
    rates = [None if value is None else (value * 100.0 if scale == "fraction" else value)
             for value in raw_rates]

    insert_at = header.index("门店名称") + 1 if "门店名称" in header else 1
    out_header = list(header)
    out_header.insert(insert_at, OWNER_COLUMN)

    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    rows: list[tuple[str, float | None]] = []
    unmatched_shops: list[str] = []
    matched = 0
    out_rows = []
    for row, rate in zip(data, rates):
        shop_id = _norm_id(row.get(ID_COLUMN))
        owner = alloc.get(shop_id, "")
        if owner:
            matched += 1
        else:
            unmatched_shops.append(str(row.get("门店名称", "") or shop_id))
        owner_value = owner or UNASSIGNED
        rows.append((owner_value, rate))
        values = [row.get(column, "") for column in header]
        values.insert(insert_at, owner_value)
        out_rows.append(values)

    detail_name = f"{day}运营-店铺经营任务完成率明细.xlsx"
    detail_path = run_dir / detail_name
    stats_name = f"{day}运营-店铺经营任务完成率.png"
    stats_path = run_dir / stats_name
    stats = compute_stats(rows)

    # 补发模式字节一致性（2026-10-19 部分送达续传修复）：--deliver-run 指向的 run 目录
    # 里若已有完整产物，必须**原样复用**。openpyxl 的 xlsx 内嵌时间戳导致重生成字节必变，
    # 会①覆盖已送达文件的字节证据、②与已 verified marker 的 sha256 永远失配 ⇒ 整单
    # same-event-payload-conflict 死锁（12:15 xlsx 已送达、PNG 被网关拒发后重跑 5 连败）。
    # 正常采集模式目录为全新空目录，此分支不触发，行为不变。
    reuse_artifacts = detail_path.exists() and stats_path.exists()
    if not reuse_artifacts:
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "店铺经营任务完成率明细"
        sheet.append(out_header)
        for column in range(1, len(out_header) + 1):
            cell = sheet.cell(row=1, column=column)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="4F81BD")
            cell.alignment = Alignment(vertical="center")
        for row in out_rows:
            sheet.append(row)
        sheet.freeze_panes = "A2"
        workbook.save(detail_path)

    # 覆盖盲区显式回传：门店分配里挂着、但运营效果导出里根本没有的运营人（典型是合同
    # 非「生效中」被站点筛掉的门店）。这些人不会出现在图里，必须上报而不是静默消失。
    covered_ids = {_norm_id(row.get(ID_COLUMN)) for row in data}
    alloc_only: dict[str, int] = {}
    for shop_id, owner in alloc.items():
        if owner and shop_id not in covered_ids:
            alloc_only[owner] = alloc_only.get(owner, 0) + 1
    from stats_card import display_name
    coverage = {
        "allocOnlyGroups": [{"raw": raw, "display": display_name(raw), "shops": count}
                            for raw, count in sorted(alloc_only.items(), key=lambda kv: -kv[1])],
        "allocOnlyShops": sum(alloc_only.values()),
        "allocShopsWithoutEffect": sum(1 for shop_id in alloc if shop_id not in covered_ids),
    }
    # 图尾提示行（大同 10-13 口径：「雷洁老师 23 家无数据未计入」）
    from stats_card import coverage_notes
    notes = coverage_notes(coverage)

    if not reuse_artifacts:
        render_card(stats, stats_path, notes=notes)

    return {"rows": len(out_rows), "matched": matched,
            "unmatched": len(out_rows) - matched, "unmatchedShops": unmatched_shops[:20],
            "path": str(detail_path), "name": detail_name, "header": out_header,
            "rateScale": scale, "ratedShops": len(numeric),
            "stats": stats, "statsPath": str(stats_path), "statsName": stats_name,
            "groups": [item["name"] for item in stats], "coverage": coverage, "notes": notes}


# ---------------------------------------------------------------- 投递

def _confirm_file_in_group(adapter, work: Path) -> dict:
    """发送后独立复核（2026-10-19 12:16 假 verified 事故新增）。

    适配器回执 verified 只证明「尾锚命中」，不证明真投递：主窗口劣化时文件卡
    可在发送侧渲染为 [文件] 却从未入群（红感叹号场景）。本函数用**第二路只读
    回读**独立复核：
      1. 标题互证：current_chat 的 title 与目标群前后缀互证（防错窗）；
      2. 新鲜性复核：重读消息列表，[文件] 卡之后只允许时间戳/系统条目。
    任一不过 ⇒ fail-closed 返回 ok=False（调用方降级 unknown，人工介入）。
    桩件/离线场景（adapter 无 client）由调用方前置跳过。
    已知局限（如实声明）：若发送瞬间本地假卡与真卡同时满足上述两条，本复核仍
    可能放行——窗口级判据无法看穿服务端投递状态；彻底判真依赖隔日群内回看。
    """
    from windows_adapter import _normalize_title, _read_messages, _title_compatible, \
        _anchor_newness

    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence = {"recheckAt": time.time()}
    try:
        current = adapter.client.current()
        title = _normalize_title((current.get("data") or {}).get("title"))
        evidence["currentTitle"] = title
        if not _title_compatible(title, GROUP):
            return {"ok": False, "reason": "recheck-title-mismatch",
                    "evidence": evidence}
        read = adapter.client.read()
        messages = _read_messages(read)
        evidence["messageCount"] = len(messages)
        if not _anchor_newness(messages, "[文件]"):
            return {"ok": False, "reason": "recheck-anchor-not-fresh",
                    "evidence": evidence}
        try:
            atomic_json(work / "post-send-recheck.json", evidence)
        except OSError:
            pass
        return {"ok": True, "reason": None,
                "summary": {"postSendRecheck": "windows-readback-rechecked"},
                "evidence": evidence}
    except Exception as error:  # noqa: BLE001
        evidence["error"] = str(error)[:200]
        return {"ok": False, "reason": "recheck-execution-error",
                "evidence": evidence}


def _deliver_one(adapter, request: dict, item: dict, marker: Path, work: Path,
                 grant: dict, deadline: int, file_sha: str, event: str) -> dict:
    if marker.exists():
        prior = json.loads(marker.read_text(encoding="utf-8"))
        if prior.get("sha256") != file_sha:
            return {"status": "blocked", "reason": "same-event-payload-conflict", "sendAttempts": 0}
        state = prior.get("state")
        if state == "verified":
            return {"status": "already_verified", "sendAttempts": 0, "event": event}
        if state == "blocked":
            # adapter 的 blocked 是**确定没发出去**（确定性拒绝：网关拒绝/闸门拦/未触驱动），
            # 与 unknown（可能已发出、收据不明）性质完全不同，必须区分开：
            # unknown ⇒ 绝不重发，只读对账；blocked ⇒ 可以安全重试。
            pass
        else:
            return {"status": "unknown", "reason": "prior-attempt-requires-read-only-reconciliation",
                    "sendAttempts": 0, "event": event}
    atomic_json(marker, {"state": "attempted", "event": event, "sha256": file_sha,
                         "groupName": GROUP, "name": item.get("name"), "sendAttempts": None})
    try:
        result = adapter.send_one(request, item, work, grant, deadline)
    except Exception as error:  # noqa: BLE001
        atomic_json(marker, {"state": "unknown", "event": event, "sha256": file_sha,
                             "groupName": GROUP, "name": item.get("name"),
                             "reason": str(error), "sendAttempts": None})
        return {"status": "unknown", "reason": f"windows-execution-error:{error}",
                "sendAttempts": None, "event": event}
    if result.get("status") == "verified":
        atomic_json(marker, {"state": "verified", "event": event, "sha256": file_sha,
                             "groupName": GROUP, "name": item.get("name"),
                             "sendAttempts": result.get("sendAttempts"),
                             "verificationLevel": result.get("verificationLevel"),
                             "evidence": result.get("evidence")})
        # 送达即快照：给「同日 sha 失配但快照命中」的续传路径留原字节（见 deliver 前置判读）。
        try:
            snap_dir = SNAPSHOTS / event
            snap_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(item["path"], snap_dir / item["name"])
        except OSError:
            pass  # 快照失败不阻断主流程（发群已 verified），只是关掉一条续传后路
        return {"status": "verified", "sendAttempts": result.get("sendAttempts"),
                "event": event, "verificationLevel": result.get("verificationLevel")}
    # blocked 与 unknown 分开记账，不许把「确定没发」写成「可能发过」。
    final_state = "unknown" if result.get("status") not in ("blocked",) else "blocked"
    atomic_json(marker, {"state": final_state, "event": event, "sha256": file_sha,
                         "groupName": GROUP, "name": item.get("name"),
                         "sendAttempts": result.get("sendAttempts"),
                         "reason": result.get("reason")})
    return {"status": result.get("status", "unknown"), "reason": result.get("reason"),
            "sendAttempts": result.get("sendAttempts"), "event": event}


def deliver(report: dict, run_dir: Path, day: str, adapter=None) -> dict:
    """发两份：明细 Excel 先、统计图后。

    `adapter` 供离线单测注入桩件（不碰真实 Windows 网关）；默认 None 时才现场构造
    WindowsAdapter。**顺序与防重是硬约束**：明细没落群就不许发图；任一件 marker 已
    attempted/verified 都绝不重复外发。
    """
    detail_path = report.get("path")
    rows = report.get("rows", 0)
    stats = report.get("stats") or []
    # 0 行硬闸：明细为空、统计图无任何组 → 一律不产不发。
    if not detail_path or rows == 0 or not stats:
        return {"status": "no-report", "sendAttempts": 0,
                "reason": "zero-rows" if rows == 0 else "zero-stats"}
    gate = arm_state()
    if not gate["armed"]:
        return {"status": "blocked", "reason": "send-disarmed", "sendAttempts": 0}
    # 首跑时 events 目录还不存在是**正常现象**（曾在此误闸 blocked，daemon 首跑必栽）——
    # 账本路径是技能内固定位置、无歧义，直接补建即可，写 marker 时还会再兜一次。
    EVENTS.mkdir(parents=True, exist_ok=True)

    detail_item = {"itemId": "store-task-detail", "type": "file",
                   "name": report["name"], "path": detail_path}
    stats_item = {"itemId": "store-task-stats", "type": "image",
                  "name": report["statsName"], "path": report["statsPath"]}
    detail_event = f"{day}-taobao-store-task-detail"
    stats_event = f"{day}-taobao-store-task-stats"

    if str(WINDOWS_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(WINDOWS_SCRIPTS))
    from contract import Rejected
    if adapter is None:
        from wecom_adapter import WeComAdapter as WindowsAdapter  # 2026-10-23 channel switch
        adapter = WindowsAdapter()

    deadline = int(time.time()) + 600
    request = {"schemaVersion": 1, "groupName": GROUP,
               "items": [detail_item, stats_item],
               "context": {"workflowId": WORKFLOW_ID, "eventId": detail_event,
                           "accountAlias": "main-wechat", "channel": "desktop",
                           "deadlineAt": deadline}}
    grant = {"schemaVersion": 1, "accountAlias": "main-wechat", "groupName": GROUP,
             "channel": "desktop", "expiresAt": deadline, "authorizationRef": AUTHORIZATION_REF}

    outcomes = []
    # 前置 marker 判读（与参考流一致）：当日两件都已 verified ⇒ 直接 already_verified，
    # **连预检都不打**（零网关接触）。sha 不符 = 同日内容变了 ⇒ 硬阻断，绝不覆盖旧账。
    event_names = {"store-task-detail": detail_event, "store-task-stats": stats_event}
    payloads = {"store-task-detail": Path(detail_path),
                "store-task-stats": Path(report["statsPath"])}
    shas = {item_id: hashlib.sha256(path.read_bytes()).hexdigest()
            for item_id, path in payloads.items()}
    marker_paths = {"store-task-detail": EVENTS / f"{detail_event}.json",
                    "store-task-stats": EVENTS / f"{stats_event}.json"}
    states = {}
    for item_id, marker in marker_paths.items():
        if not marker.exists():
            states[item_id] = "absent"
            continue
        prior = json.loads(marker.read_text(encoding="utf-8"))
        if prior.get("sha256") != shas[item_id]:
            # 2026-10-19 快照回退：xlsx 内嵌时间戳导致「同日重生成字节必变」是常态而非
            # 篡改（openpyxl save 时强制刷新 modified）。快照区存有该事件 verified 时的
            # 原字节 ⇒ 命中（sha 一致）就复用原产物，账本与文件恢复字节级一致；
            # 未命中（无快照或快照也对不上）才是真·payload 冲突，维持硬阻断。
            snap_dir = SNAPSHOTS / event_names[item_id]  # 与 _deliver_one 快照路径一致
            snap_file = snap_dir / payloads[item_id].name
            if snap_file.exists() and hashlib.sha256(snap_file.read_bytes()).hexdigest() \
                    == prior.get("sha256"):
                shutil.copyfile(snap_file, payloads[item_id])
                shas[item_id] = prior["sha256"]
                states[item_id] = prior.get("state", "unknown")
                continue
            return {"status": "blocked", "reason": "same-event-payload-conflict",
                    "sendAttempts": 0, "conflictItem": item_id}
        states[item_id] = prior.get("state", "unknown")
    if all(state == "verified" for state in states.values()):
        return {"status": "already_verified", "sendAttempts": 0,
                "items": [{"name": report["name"], "status": "already_verified",
                           "event": detail_event},
                          {"name": report["statsName"], "status": "already_verified",
                           "event": stats_event}]}
    try:
        with adapter.session(request):
            preflight = adapter.preflight(request, run_dir / "windows-preflight")
            # 2026-10-19 对齐 adapter 共享契约：会话列表只是视口（「折叠置顶聊天」挡住
            # 非置顶业务群 ⇒ target-group-not-exactly-listed 假阳性，当日 PNG 续传被卡）。
            # resolve_group 的 server-search 兜底（不在列表 ⇒ 搜索定位 + 发送后标题交叉
            # 验证 + 末条锚点回读）本就是 adapter 作者设计并经 09-30 联测验证的路径，
            # 与金鲨日报/负评跟进等兄弟流一致；此处不再超额强求「必须在会话列表」。
            weak_preflight_ok = (preflight.get("candidateStrategy") == "windows-server-search"
                                 and preflight.get("groupTypeVerified") is True)
            if (not preflight.get("ok")
                    or (preflight.get("resolvedGroup") != GROUP and not weak_preflight_ok)):
                return {"status": "blocked",
                        "reason": preflight.get("reason") or "target-group-not-exactly-listed",
                        "sendAttempts": 0}
            # 顺序铁律：先发明细 Excel，确认落群后才发统计图（大同口径）。
            detail_sha = shas["store-task-detail"]
            outcome = _deliver_one(adapter, request, detail_item,
                                   marker_paths["store-task-detail"],
                                   run_dir / "windows-send-detail",
                                   grant, deadline, detail_sha, detail_event)
            outcomes.append({"name": report["name"], **outcome})
            if outcome["status"] not in ("verified", "already_verified"):
                return {"status": outcome["status"], "reason": outcome.get("reason"),
                        "sendAttempts": outcome.get("sendAttempts"), "items": outcomes}
            # 2026-10-19 假 verified 防御（大同 16:37 指令「下次不要漏」）：明细报
            # verified 后不再无条件信任尾锚——12:16 事故里主窗口劣化，文件卡在本地
            # 渲染为 [文件] 却从未入群，单锚点判 verified 造成漏发一整天。此处对
            # 「sendAttempts≥1 的真实发送」做复核：真实重读消息列表，要求 [文件]
            # 卡之后只有时间戳/系统消息（新鲜性），并留档复核证据。桩件（无
            # client）/already_verified 跳过。
            if outcome.get("sendAttempts", 0) and getattr(adapter, "client", None):
                recheck = _confirm_file_in_group(adapter, run_dir / "windows-send-detail")
                outcomes[-1].update(recheck.get("summary", {}))
                if not recheck.get("ok"):
                    # fail-closed：复核不过 ⇒ 降级 unknown（绝不写 verified），后续
                    # 走只读对账/人工介入，不自动重发（防红感叹号场景重复外发）。
                    atomic_json(marker_paths["store-task-detail"],
                                {"state": "unknown", "event": detail_event,
                                 "sha256": detail_sha, "groupName": GROUP,
                                 "name": report["name"], "sendAttempts": None,
                                 "reason": "post-send-recheck-failed:" +
                                           str(recheck.get("reason"))[:120],
                                 "evidence": recheck.get("evidence")})
                    return {"status": "unknown",
                            "reason": "post-send-recheck-failed:" +
                                      str(recheck.get("reason"))[:120],
                            "sendAttempts": outcome.get("sendAttempts"), "items": outcomes}
            stats_sha = shas["store-task-stats"]
            outcome = _deliver_one(adapter, request, stats_item,
                                   marker_paths["store-task-stats"],
                                   run_dir / "windows-send-stats",
                                   grant, deadline, stats_sha, stats_event)
            outcomes.append({"name": report["statsName"], **outcome})
            # 2026-10-19 同窗劣化回溯（当日事故的直接机检签名）：明细刚在本轮
            # verified（sendAttempts≥1），紧随的统计图却因「主窗口未出现」被拒 ⇒
            # 同一会话窗口状态已劣化 ⇒ 明细那次 verified 不可信（本地渲染假卡）。
            # 回溯降级 unknown（不自动重发，防真投递场景重复外发），等只读对账/
            # 人工裁决。仅在「明细确为本轮新发」时回溯——already_verified 是早前
            # 真投递的账，不因当下窗口劣化连坐。
            if (outcome["status"] not in ("verified", "already_verified")
                    and "主窗口未出现" in str(outcome.get("reason"))):
                prior_detail_sent_this_run = any(
                    o.get("event") == detail_event and o.get("sendAttempts") for o in outcomes[:-1])
                if prior_detail_sent_this_run:
                    atomic_json(marker_paths["store-task-detail"],
                                {"state": "unknown", "event": detail_event,
                                 "sha256": detail_sha, "groupName": GROUP,
                                 "name": report["name"], "sendAttempts": None,
                                 "reason": "batch-window-degraded-retro-suspect",
                                 "evidence": {"statsReason":
                                              str(outcome.get("reason"))[:160]}})
                    outcomes[0] = {**outcomes[0], "status": "unknown",
                                   "reason": "batch-window-degraded-retro-suspect"}
    except Rejected as error:
        return {"status": "blocked", "reason": str(error), "sendAttempts": 0, "items": outcomes}

    statuses = {item["status"] for item in outcomes}
    if statuses <= {"verified", "already_verified"}:
        return {"status": "verified" if "verified" in statuses else "already_verified",
                "sendAttempts": 1, "items": outcomes}
    first_bad = outcomes[-1]
    return {"status": first_bad["status"], "reason": first_bad.get("reason"),
            "sendAttempts": first_bad.get("sendAttempts"), "items": outcomes}


# ---------------------------------------------------------------- 入口

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="允许发群（否则只采集+生成）")
    parser.add_argument("--arm", action="store_true", help="解除发送制动")
    parser.add_argument("--disarm", action="store_true", help="制动发送（写 SEND_DISARMED.json）")
    parser.add_argument("--deliver-run", metavar="RUN_DIR",
                        help="不重新采集，直接用指定 run 目录里的明细+统计图发群"
                             "（大同过目后补发用；run 目录名须以 yyyy-mm-dd 开头）")
    parser.add_argument("--reconcile-run", metavar="RUN_DIR", help="仅核对原文件送达，不采集不发送")
    args = parser.parse_args()
    if args.reconcile_run:
        if str(WINDOWS_SCRIPTS) not in sys.path:
            sys.path.insert(0,str(WINDOWS_SCRIPTS))
        from wecom_file_reconcile import reconcile_run
        result=reconcile_run(args.reconcile_run,runs=RUNS,events=EVENTS,group=GROUP,
                             event_suffix='taobao-store-task-detail',whole_flow=False)
        print(json.dumps(result,ensure_ascii=False))
        if result.get('status') not in ('verified','already_verified','detail-verified-image-pending'):
            raise SystemExit(1)
        return
    if args.arm or args.disarm:
        print(json.dumps(set_arm(bool(args.arm)), ensure_ascii=False))
        return
    day = datetime.now(LOCAL_TZ).date().isoformat()
    run_dir = RUNS / f"{day}-{time.time_ns()}"
    try:
        if args.deliver_run:
            # 补发模式：复用已下载的真实数据重建（确定性：同输入同输出），只走发送。
            run_dir = Path(args.deliver_run).resolve()
            day = run_dir.name[:10]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise ValueError(f"cannot-derive-day-from-run-dir:{run_dir.name}")
            collected: dict = {}
            report = build_report(run_dir, day)
            result = deliver(report, run_dir, day)
        else:
            run_dir.mkdir(parents=True, mode=0o700)
            collected = collect(run_dir)
            report = build_report(run_dir, day)
            result = (deliver(report, run_dir, day) if args.execute
                      else {"status": "ready" if report.get("rows") else "no-report", "sendAttempts": 0})
        result.update({
            "day": day, "rows": report.get("rows"), "matched": report.get("matched"),
            "unmatched": report.get("unmatched"), "report": report.get("name"),
            "reportPath": report.get("path"), "statsImage": report.get("statsName"),
            "statsPath": report.get("statsPath"), "rateScale": report.get("rateScale"),
            "groups": report.get("groups"),
            "coverage": report.get("coverage"), "notes": report.get("notes"),
            "stats": [{"name": s["name"], "raw": s.get("raw"), "avg": round(s["avg"], 2),
                       "shops": s["shops"], "counted": s["counted"], "missing": s["missing"]}
                      for s in (report.get("stats") or [])],
            "runDir": str(run_dir), "armState": arm_state(),
            "mode": "deliver-run" if args.deliver_run else "collect",
            "collected": (None if args.deliver_run else
                          {"effect": collected.get("effect", {}).get("size"),
                           "effectRows": collected.get("effect", {}).get("tableTotal"),
                           "alloc": collected.get("alloc", {}).get("size"),
                           "allocRows": collected.get("alloc", {}).get("tableTotal")}),
        })
    except Exception as error:  # noqa: BLE001
        result = {"status": "unknown", "reason": str(error), "sendAttempts": 0,
                  "runDir": str(run_dir), "day": day}
    atomic_json(run_dir / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] not in ("verified", "already_verified", "ready", "no-report"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()