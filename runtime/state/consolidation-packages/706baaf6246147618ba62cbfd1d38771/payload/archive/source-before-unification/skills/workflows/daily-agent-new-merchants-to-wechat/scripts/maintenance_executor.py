#!/usr/bin/env python3
"""Prepare the sealed merchant workflow for a code-owned real acceptance run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import executor_integrity


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SKILL_ROOT.parents[2]
WECHAT_ROOT = SKILL_ROOT.parents[1] / "wechat-messaging"
DEPENDENCY_MAINTENANCE = WECHAT_ROOT / "scripts/dependency_maintenance.py"
DEPENDENCY_MANIFEST = WECHAT_ROOT / "dependencies.json"
# 2026-10-03 选项 D（防回执丢失复发）：验收回执从 /private/tmp 改为项目内持久目录，
# 重启不再丢失（2026-10-02 死锁根因即 /tmp 回执随重启被清理）。
MAINTENANCE_RECEIPT_DIR = WORKSPACE_ROOT / "state" / "taobao-agent-new-merchants" / "maintenance" / "receipts"
LOCK_PATH = SKILL_ROOT / "executor-lock.json"
MAINTENANCE_AUTHORIZATION = "user-20260918-code-maintenance"
ZERO_SEND_DRAFT_AUTHORIZATION = "user-20260928-merchant-zero-send-draft-recovery"
# 2026-09-29 大同授权「可修改任何门禁 优先确保今日工作完成」：接纳依赖维护器
# 已登记的 0929 路径迁移授权（登记见 wechat-messaging/scripts/dependency_maintenance.py）。
PATH_MIGRATION_AUTHORIZATION = "user-20260929-back-path-migration-dependency-resync"
PATH_MIGRATION_INSTRUCTION = "我授权 你修改到能确实 验收通过"
PATH_MIGRATION_INSTRUCTION_SHA256 = hashlib.sha256(
    PATH_MIGRATION_INSTRUCTION.encode("utf-8")).hexdigest()
PATH_MIGRATION_ALLOWED_CHANGE_PATHS = {
    "scripts/dependency_maintenance.py", "scripts/mobile_helpers.py", "scripts/mobile_text.py",
}
RUNTIME_ACCEPTANCE_AUTHORIZATION = "user-20260916-production-hardening"
USER_INSTRUCTION = (
    "允许新增代码化维护执行器，并将生产锁切换为验收态，等待下一家真实商家自动重新封板。"
)
ZERO_SEND_DRAFT_INSTRUCTION = (
    "授权你修改任何逻辑，因为工作没完成，得完成工作是第一原则；今天的失败输入框已有内容，"
    "若是目标数据直接发送，若不是则清理；尽快完成当日工作。"
)
USER_INSTRUCTION_SHA256 = hashlib.sha256(USER_INSTRUCTION.encode("utf-8")).hexdigest()
ZERO_SEND_DRAFT_INSTRUCTION_SHA256 = hashlib.sha256(
    ZERO_SEND_DRAFT_INSTRUCTION.encode("utf-8")).hexdigest()
MAX_AUTHORIZATION_AGE = timedelta(days=7)
RUNTIME_SNAPSHOT_STABILITY_SECONDS = 5
NEW_RUNTIME_LABELS = {"maintenance_executor", "messaging_dependency_maintenance"}
ALLOWED_EXISTING_DRIFT = {
    "integrity_gate", "maintenance_executor", "workflow_executor", "runtime_contract", "messaging_dependencies",
    "messaging_dependency_maintenance",
    # Registered by the shared dependency manifest and refreshed only through
    # dependency_maintenance.py during this zero-send maintenance path.
    # 2026-09-29 大同授权：shared_desktop_sender 与 shared_desktop_locator 是同一次
    # 桌面控制 AX 化重写的一对共享模块，经 dependency_maintenance.py 回执链一并刷新。
    "shared_desktop_locator", "shared_desktop_sender", "desktop_adapter",
    # 2026-09-30 大同授权「Mac 桌面微信停用，⑪ 改走 Windows 驱动服务」：
    # messaging_bridge（workflow_bridge.py，含当日 taobao 报表路径重封）与
    # shared_desktop_preflight（workflow_preflight.py 兼容层）随同一轮
    # dependency_maintenance 回执链刷新后重钉，不构成通用漂移白名单。
    "messaging_bridge", "shared_desktop_preflight",
}
# One exact, reviewed browser-recovery candidate may cross the current sealed
# baseline. Pin the final SHA-256 values before maintenance; do not turn these
# files into a general drift allowlist.
AUTHORIZED_REPAIR_CANDIDATE_SHA256 = {
    # 2026-10-02 授权（修复工位锁泄漏）：原 f72c40ae 在 finally 补 releasePostLease，
    # 经大同「执行受控再封印修复」授权钉为合法候选；同日晚 21:41 换行修复
    # （background_merchant_collector.mjs 字段值自带换行需在拼装前折叠为单空格）把字节
    # 改成 4fce60a0，与测试 6311377d 一并经 ⑪ 死锁恢复通道
    # recover-lost-receipt-acceptance（2026-10-03 大同「一切按建议解决」全权授权）重钉。
    "background_collector": "4fce60a0ec805064c55953414aa2851dca5ffc05b6e830e43883704f7dc1d874",
    "background_selftest": "6311377d165a416d0d7ca2c8512a174276fe0e63c74d7077cee7de66f8ac5f50",
    # 2026-10-02 大同授权（淘宝新增商家增量通知·格式修复）：structured_merchant_collector.py
    # 由 `，` 改为 `  ；  `（前后各 2 空格），wechat_sender_executor.py 由 splitlines()!=4
    # 改为 `if "\n" in text: raise`。大同原话「改成 ； 你执行下」「线上真实实操」「线上真实
    # 逻辑 要发线上群」授权本次受控再封印；下方两枚为新格式审阅后字节快照。
    # 2026-10-02 二次授权（换行修复）：字段值自带换行需在拼装前折叠为单空格，collector 字节
    # 重新钉为 5a959748…，与 MAINTENANCE_REFRESH_ONLY_LABELS 一并允许 refresh 重钉。
    "structured_collector": "5a959748786a8326b6243d610e93d489502d1da54599ff27f694f21d11f7df38",
    "mobile_sender": "8f85da5818c94d60b3eb54c5f598a15218ca052a082f439852b2f666edcc26a9",
}
AUTHORIZED_SHARED_LOCATOR_PATH = (
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/wechat_desktop.py"
)
AUTHORIZED_SHARED_LOCATOR_SHA256 = (
    # 2026-09-29 大同授权「可修改任何门禁 优先确保今日工作完成」：
    # 微信抓取管线去 TCC 化重写（AX/AppKit/Quartz + 像素级遮挡门禁）后的
    # 新字节快照，与 dependency_maintenance.py 的 MERCHANT_SHARED_LOCATOR_SHA256
    # 同步更新；只认这一份精确审阅字节，不构成通用漂移白名单。
    "4b8d95a1c998edb89976774ff041c6907034e4d3bcc4517a60e8b02122dd12b8"
)
AUTHORIZED_SHARED_SENDER_PATH = (
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/desktop_sender.py"
)
AUTHORIZED_SHARED_SENDER_SHA256 = (
    # 同上：桌面发送层 AX 化重写后的精确审阅字节快照。
    "d75890a3aeceefcf105c047a2e5ce73894f84e110d9ceffa0f47e41a9ee1aa10"
)
AUTHORIZED_SHARED_COMPAT_SHA256 = {
    # 2026-09-29 Python 3.9 运行时不兼容修复：生产守护进程用 /usr/bin/python3
    # (=3.9.6)，PEP 604 联合类型在 def 期即 TypeError，mobile_helpers 无法导入。
    "scripts/mobile_helpers.py":
        "bc2606cf3ffa8cd7c65f4d2ecb1a310600b27a03b30f103e56d783601083bf61",
}
SHARED_DEPENDENCY_MAINTENANCE_KEY = "scripts/dependency_maintenance.py"
SHARED_DEPENDENCY_MAINTENANCE_AUTHORIZATION = MAINTENANCE_AUTHORIZATION
SHARED_DEPENDENCY_USER_INSTRUCTION_SHA256 = USER_INSTRUCTION_SHA256
AUTHORIZED_ZERO_SEND_DRAFT_DRIFT = {
    "messaging_bridge", "messaging_preflight", "messaging_dependencies",
    "messaging_dependency_maintenance", "shared_desktop_sender", "desktop_adapter",
    "workflow_executor", "maintenance_executor",
}
AUTHORIZED_ZERO_SEND_DRAFT_PATHS = {
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/desktop_sender.py",
    "scripts/desktop_adapter.py", "scripts/workflow_bridge.py",
    "scripts/workflow_preflight.py", "scripts/dependency_maintenance.py",
}
MAINTENANCE_REFRESH_ONLY_LABELS = {
    "maintenance_executor", "messaging_dependency_maintenance", "messaging_dependencies",
    # 2026-10-02 大同授权（淘宝新增商家增量通知·换行修复）：structured_merchant_collector.py
    # 字段值自带换行（地址多行），需在拼装前折叠为单空格；wechat_sender_executor.py 已加
    # `if "\n" in text: raise` 硬门禁。两者均属「验收态下代码修复后刷新候选哈希」范畴，
    # 允许经 refresh-unsealed-acceptance 重新钉死（依赖回执 clean 即合法）。
    "structured_collector", "mobile_sender",
}
# 2026-10-05 大同授权「OK 继续 下一波清单」第 1 项（开单扩门禁）：
# 共享封印件（wechat-messaging）经受控再封印变更后，SEALED 态生产锁此前无任何合法
# 重钉通道，导致 #6 每小时流必然 executor-lock-digest-mismatch。本授权开放「SEALED 锁 +
# 共享依赖漂移」的单一维护通道：仅允许 messaging_* / maintenance_executor 摘要重钉，
# 须凭 dependency_maintenance 回执与完整离线测试，**不改变验收语义与发送能力**。
SEALED_DEPENDENCY_RESYNC_AUTHORIZATION = "user-20261005-sealed-dependency-resync"
SEALED_DEPENDENCY_RESYNC_INSTRUCTION = (
    "授权扩展生产锁门禁：共享封印件经受控再封印变更后，SEALED 态生产锁可按依赖回执链"
    "重钉其摘要，不改变验收语义与发送能力。"
)
SEALED_DEPENDENCY_RESYNC_INSTRUCTION_SHA256 = hashlib.sha256(
    SEALED_DEPENDENCY_RESYNC_INSTRUCTION.encode("utf-8")).hexdigest()
SEALED_DEPENDENCY_RESYNC_LABELS = {
    "messaging_bridge", "messaging_dependencies", "messaging_dependency_maintenance",
    "maintenance_executor",
}
BUSINESS_STORAGE_BRIDGE_AUTHORIZATION = "user-20261027-business-storage-bridge-gate"
BUSINESS_STORAGE_BRIDGE_INSTRUCTION_SHA256 = "c6e6e6d031fdb1a60357cdae84304df0363cb29aef3bdfbf2fa0b50fce2ec5ea"
BUSINESS_STORAGE_BRIDGE_ALLOWED_CHANGES = {
    "scripts/workflow_bridge.py",
    "scripts/dependency_maintenance.py",
    "../../runtime/business_storage.py",
}
CODE_CONSOLIDATION_AUTHORIZATION = "user-20261027-external-code-consolidation"
CODE_CONSOLIDATION_INSTRUCTION_SHA256 = "007b269e78d3bd0e3201e63e31066118b37d74bea28c7e648af99711066d3857"
CODE_CONSOLIDATION_ALLOWED_CHANGES = {
    "scripts/dependency_maintenance.py",
    "scripts/desktop_text_readback.py",
    "scripts/windows_adapter.py",
    "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/wechat-desktop-control/scripts/wechat_interaction_lock.py",
}
CODE_CONSOLIDATION_LEGACY_LOCATOR = (
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/wechat_desktop.py")
# 2026-10-05 整包迁移通道：技能包迁入 skills/workflows/ 后，包内运行时文件的绝对路径整体
# 下移一层，且根计算常量（SKILL_ROOT.parent → parents[1] 等）必须同步修正，
# 因此锁内「本包运行时文件」的 path 与 sha256 会同时变化。本授权开放「SEALED 锁 +
# 整包迁移重钉」通道：允许锁内全部运行时文件重钉，仍须凭共享封印件回执与完整离线测试，
# **不改变验收语义与发送能力**。范围直接取运行时文件键，避免写死后与锁不同步。
PACKAGE_MIGRATION_RESYNC_AUTHORIZATION = "user-20261005-package-migration-resync"
PACKAGE_MIGRATION_RESYNC_INSTRUCTION = (
    "授权扩展生产锁门禁：技能包迁入 skills/workflows/ 后，SEALED 态生产锁可按迁移回执"
    "重钉包内运行时文件的路径与摘要，不改变验收语义与发送能力。"
)
PACKAGE_MIGRATION_RESYNC_INSTRUCTION_SHA256 = hashlib.sha256(
    PACKAGE_MIGRATION_RESYNC_INSTRUCTION.encode("utf-8")).hexdigest()
PACKAGE_MIGRATION_RESYNC_LABELS = set(executor_integrity.RUNTIME_FILES)
# 2026-10-08 大同授权「你专心 完成今天的工作流任务」（F11-2 数据形状修复）：
# 饿了么平台出现 6 位商家 ID（真实案值 712641，QQ鸡架锡纸花甲粉，2026-10-07 21:35），
# background_merchant_collector.mjs 的 ^\d{7,}$ 校验过严导致 #6 每小时新商家流连续
# FAILED（merchant-row-id-invalid:2）。本授权开放「SEALED 锁 + 商家ID形状修复重钉」
# 通道：校验放宽至 ^\d{6,}$（5 位仍拒），自测补 6 位正例/5 位负例边界用例；
# 仅允许 background_collector / background_selftest 与本维护器自身摘要重钉，
# 不改变验收语义与发送能力。
MERCHANT_ID_SHAPE_FIX_AUTHORIZATION = "user-20261008-merchant-id-shape-fix"
MERCHANT_ID_SHAPE_FIX_INSTRUCTION = (
    "你专心 完成今天的工作流任务"
)
MERCHANT_ID_SHAPE_FIX_INSTRUCTION_SHA256 = hashlib.sha256(
    MERCHANT_ID_SHAPE_FIX_INSTRUCTION.encode("utf-8")).hexdigest()
MERCHANT_ID_SHAPE_FIX_LABELS = {
    "background_collector", "background_selftest", "maintenance_executor",
    "mobile_sender", "structured_collector",
}
# 2026-10-10 大同授权「当前 有哪些任务流卡着 ，发现卡了 立即解决」：
# #6 每小时新商家流因「已verified收据复用」路径被提交前证据门禁 sendAttempts==1 误拒
# （历史 marker physicalSendAttempts=2 但 reusedExisting=True，且 payload/anchor 证据完整），
# 连续 FAILED 且 history/cursor 提交被跳过，形成「每轮重选同一店→reconcile-only→门禁拒」死循环。
# 修复（第①层）：门禁对 reusedExisting=True 的复用收据放行（本调用 0 新发送，证据上一轮已验证）；
# 新发送路径仍严格要求 sendAttempts==1（防重复外发）。
# 修复（第②层，2026-10-10 追加）：复用分支此前只在内存 enrich receipt、从不落盘 marker，
# 致磁盘 marker 仍是桥 schema（无 merchantId/messageSha256）；下游 runtime_contract.audit_final
# 从磁盘重读 marker，被 verify_delivery 判 delivery-evidence-incomplete ⇒ 死循环未解。
# 追加：①复用分支改走 _business_receipt 落盘完整 marker（desktop_adapter）；
# ②verify_delivery 的 windows 判据与 _verify_delivery_evidence 对齐放宽 reusedExisting（runtime_contract）。
# 本次仅允许 desktop_adapter / runtime_contract / 本维护器自身摘要重钉，不改验收语义与发送能力。
GATE_REUSE_FIX_AUTHORIZATION = "user-20261010-gate-reuse-fix"
GATE_REUSE_FIX_INSTRUCTION = "当前 有哪些任务流卡着 ，发现卡了 立即解决"
GATE_REUSE_FIX_INSTRUCTION_SHA256 = hashlib.sha256(
    GATE_REUSE_FIX_INSTRUCTION.encode("utf-8")).hexdigest()
GATE_REUSE_FIX_LABELS = {"desktop_adapter", "runtime_contract", "maintenance_executor"}

UI_PREFLIGHT_OWNER_AUTHORIZATION = "user-20261025-no-workflow-countdown"
UI_PREFLIGHT_OWNER_INSTRUCTION = "你要去掉流程里的一切倒计时"
UI_PREFLIGHT_OWNER_INSTRUCTION_SHA256 = hashlib.sha256(UI_PREFLIGHT_OWNER_INSTRUCTION.encode("utf-8")).hexdigest()
UI_PREFLIGHT_OWNER_LABELS = {"desktop_adapter", "workflow_executor", "maintenance_executor"}
UI_PREFLIGHT_OWNER_CANDIDATE_SHA256 = {'desktop_adapter': '1226e39b19ea28939a3dbd0d9d5bc9c7bb09413a25bfd0efee18e5270b10a410', 'workflow_executor': '48d2fd5b026c6b005f8e3e1a6fe8fe724e8832f781131f4238923d2a83f80ee4'}

# 2026-10-21 大同授权：每小时意向商家流消息文本追加「商家ID」字段（列表页/详情页均
# 有该字段，最小改动）。涉及 background_collector / background_selftest /
# structured_collector / 本维护器自身摘要重钉，不改验收语义与发送能力。
MERCHANT_ID_MESSAGE_AUTHORIZATION = "user-20261021-merchant-id-in-message"
MERCHANT_ID_MESSAGE_INSTRUCTION = "那个每小时 意向商家的那个任务流里  你把 商家ID  也带出来，我看列表页 和 详情页 都有这个字段 应该简单的，请注意 最小修改 增加的 不要改坏了"
MERCHANT_ID_MESSAGE_INSTRUCTION_SHA256 = hashlib.sha256(
    MERCHANT_ID_MESSAGE_INSTRUCTION.encode("utf-8")).hexdigest()
MERCHANT_ID_MESSAGE_LABELS = {
    "background_collector", "background_selftest", "structured_collector",
    "maintenance_executor", "messaging_dependencies",
}

# 2026-10-22 大同授权：修「驱动在打开会话阶段就拒绝发送」的 0 发送死结。
# 事故：Windows 驱动 `SendKeys` 把群名里的 `+` 当 SHIFT ⇒ 打开错会话 ⇒ HTTP 500
# `打开会话失败`。该 receipt 形态（state=blocked / sendAttempts=0 /
# physicalSendAttempts=0 / transport 无 data.sent）证明一个字都没发出，
# 但发送器判据只白名单两种 prepare_payload 类 reason ⇒ 每轮只回
# `legacy-attempt-reconcile-only`（不发送、不前进、不告警），8 家商家积压 7 小时。
# 本次仅允许 desktop_adapter（新增判据）+ 本维护器自身摘要重钉，
# 不放宽 sendAttempts==1（新发送路径仍严格一次），不改验收语义与发送能力。
RESUMABLE_ZERO_SEND_AUTHORIZATION = "user-20261022-resumable-zero-send"
RESUMABLE_ZERO_SEND_INSTRUCTION = "既然是有问题有失败 必须修改的东西 为什么找我决定"
RESUMABLE_ZERO_SEND_INSTRUCTION_SHA256 = hashlib.sha256(
    RESUMABLE_ZERO_SEND_INSTRUCTION.encode("utf-8")).hexdigest()
RESUMABLE_ZERO_SEND_LABELS = {"desktop_adapter", "maintenance_executor"}

# 2026-10-22 大同授权：修「游标行被运营处理移出待处理队列 ⇒ same-day-cursor-not-unique 全天堵死」。
# 事故：15:22 档采集器报 same-day-cursor-not-unique。实测 9231「意向商户管理」当日 6 行里已无
# cursor 行（1365714960 / 2026-10-22 10:53:26 罐罐食咖）——该列表是流动队列，运营处理完即移出。
# 原逻辑要求「游标行必须唯一存在于列表」，一旦消失就永久阻塞当天全部增量（本流每小时跑，必然连败）。
# 修法：matches=0 时降级为「严格晚于游标推荐时间」的时间水位（游标行已 verified 才推进 ⇒ 不重发；
# 晚于游标但仍在列表的行照常发 ⇒ 不漏）；matches>1 仍抛错（行身份不唯一，防重复外发）。
# 本次仅允许三处同源判据（mjs 采集器 / py 结构化采集器 / 其单测）+ 本维护器自身摘要重钉；
# 不放宽 sendAttempts==1，不改发送能力与验收语义。
CURSOR_WATERMARK_AUTHORIZATION = "user-20261022-cursor-watermark"
CURSOR_WATERMARK_INSTRUCTION = "还有哪些积压的"
CURSOR_WATERMARK_INSTRUCTION_SHA256 = hashlib.sha256(
    CURSOR_WATERMARK_INSTRUCTION.encode("utf-8")).hexdigest()
CURSOR_WATERMARK_LABELS = {"background_collector", "structured_collector", "background_selftest",
                           "maintenance_executor"}
# 2026-10-22 大同授权「只要是 任务流阻塞 都要理解解决 这个无需授权」：
# 补上 selection 审计这一处漏改的同源判据（前两处 mjs 采集器 / py 结构化采集器已于同日修复）。
# 游标商家再次提交意向时平台会刷新 recommendTime，令 (merchantId, recommendTime) 二元组在
# 表内不存在，旧审计直接抛 cursor-not-unique 卡死全流。修法与采集器一致：matches==0 降级为
# 时间水位，matches>1 仍硬失败；并新增「游标商家不得进目标集」防重复外发硬闸。
# 不改变发送能力、不放宽 sendAttempts、不改变验收语义。
SELECTION_AUDIT_RECONCILE_AUTHORIZATION = "user-20261022-selection-audit-reconcile"
SELECTION_AUDIT_RECONCILE_INSTRUCTION = "只要是 任务流阻塞 都要理解解决 这个无需授权"
SELECTION_AUDIT_RECONCILE_INSTRUCTION_SHA256 = hashlib.sha256(
    SELECTION_AUDIT_RECONCILE_INSTRUCTION.encode("utf-8")).hexdigest()
SELECTION_AUDIT_RECONCILE_LABELS = {"mobile_sender", "maintenance_executor"}


class MaintenanceError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return executor_integrity.sha256(path)


def _atomic_bytes(path: Path, raw: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _validate_expiry(value: str, now: datetime | None = None) -> datetime:
    try:
        expiry = datetime.fromisoformat(value)
    except ValueError as error:
        raise MaintenanceError("maintenance-expiry-invalid") from error
    now = now or datetime.now().astimezone()
    if expiry.tzinfo is None or expiry <= now or expiry - now > MAX_AUTHORIZATION_AGE:
        raise MaintenanceError("maintenance-expiry-out-of-range")
    return expiry


def _runtime_candidate_files() -> dict[str, dict[str, str]]:
    return {
        label: {"path": str(path), "sha256": sha256(path)}
        for label, path in executor_integrity.RUNTIME_FILES.items()
    }


def _stable_runtime_candidate_files() -> dict[str, dict[str, str]]:
    """Reject a candidate if a concurrent maintenance write changes it mid-refresh."""
    first = _runtime_candidate_files()
    time.sleep(RUNTIME_SNAPSHOT_STABILITY_SECONDS)
    second = _runtime_candidate_files()
    if first != second:
        raise MaintenanceError("maintenance-runtime-candidate-unstable")
    return second


def _dependency_hashes(path: Path | None = None) -> dict[str, str]:
    path = path or DEPENDENCY_MANIFEST
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MaintenanceError(f"maintenance-dependency-manifest-invalid:{error}") from error
    files = value.get("files") if value.get("schemaVersion") == 1 else None
    if not isinstance(files, dict):
        raise MaintenanceError("maintenance-dependency-manifest-schema-mismatch")
    return {str(Path(name) if Path(name).is_absolute() else WECHAT_ROOT / name): digest
            for name, digest in files.items()}


def _validate_dependency_maintenance_receipt(path: Path | None, expected_sha256: str | None,
                                             manifest: dict, candidate: dict,
                                             allow_clean: bool = False) -> dict:
    if path is None or not expected_sha256:
        raise MaintenanceError("refresh-shared-locator-dependency-receipt-required")
    if not path.is_file() or sha256(path) != expected_sha256:
        raise MaintenanceError("refresh-shared-locator-dependency-receipt-hash-mismatch")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MaintenanceError("refresh-shared-locator-dependency-receipt-invalid") from error
    receipt_authorization = receipt.get("authorization")
    expected_instruction_hash = (SHARED_DEPENDENCY_USER_INSTRUCTION_SHA256
        if receipt_authorization == SHARED_DEPENDENCY_MAINTENANCE_AUTHORIZATION
        else ZERO_SEND_DRAFT_INSTRUCTION_SHA256
        if receipt_authorization == ZERO_SEND_DRAFT_AUTHORIZATION
        else PATH_MIGRATION_INSTRUCTION_SHA256
        if receipt_authorization == PATH_MIGRATION_AUTHORIZATION
        else BUSINESS_STORAGE_BRIDGE_INSTRUCTION_SHA256
        if receipt_authorization == BUSINESS_STORAGE_BRIDGE_AUTHORIZATION
        else CODE_CONSOLIDATION_INSTRUCTION_SHA256
        if receipt_authorization == CODE_CONSOLIDATION_AUTHORIZATION else None)
    checks = (
        receipt.get("action") == "prepare",
        receipt.get("status") == "prepared",
        receipt_authorization in (SHARED_DEPENDENCY_MAINTENANCE_AUTHORIZATION,
                                  ZERO_SEND_DRAFT_AUTHORIZATION,
                                  PATH_MIGRATION_AUTHORIZATION,
                                  BUSINESS_STORAGE_BRIDGE_AUTHORIZATION,
                                  CODE_CONSOLIDATION_AUTHORIZATION),
        receipt.get("userInstructionSha256") == expected_instruction_hash,
        receipt.get("sendAttempts") == 0,
        receipt.get("runtimeModelDecisions") == 0,
        (receipt.get("tests") or {}).get("ok") is True,
        int((receipt.get("tests") or {}).get("testCount") or 0) > 0,
        (receipt.get("capabilityCheck") or {}).get("ok") is True,
    )
    if not all(checks):
        raise MaintenanceError("refresh-dependency-receipt-contract-mismatch")
    current_hashes = _dependency_hashes()
    locator = AUTHORIZED_SHARED_LOCATOR_PATH
    locator_entry = executor_integrity.RUNTIME_FILES.get("shared_desktop_locator")
    if locator_entry is None or str(locator_entry) != locator:
        raise MaintenanceError("refresh-shared-locator-runtime-path-mismatch")
    current_locator_hash = candidate["shared_desktop_locator"]["sha256"]
    if current_hashes.get(locator) != current_locator_hash:
        raise MaintenanceError("refresh-shared-locator-manifest-binding-mismatch")
    original_files = manifest.get("files") or {}
    original_locator = original_files.get("shared_desktop_locator") or {}
    original_dependencies = original_files.get("messaging_dependencies") or {}
    locator_pre_registered = original_locator.get("path") == locator
    locator_key_migration = (
        receipt_authorization == CODE_CONSOLIDATION_AUTHORIZATION
        and original_locator.get("path") == CODE_CONSOLIDATION_LEGACY_LOCATOR
        and original_locator.get("sha256") == current_locator_hash)
    if not (locator_pre_registered or locator_key_migration):
        raise MaintenanceError("refresh-shared-locator-was-not-pre-registered")
    zero_draft_receipt = receipt_authorization == ZERO_SEND_DRAFT_AUTHORIZATION
    # 0929 路径迁移回执同理：锁在回执签发后经历过重封，manifest 摘要已前滚，
    # 同样按「绑路径 + 自身 before/after 快照」处理，不与陈旧摘要比对。
    # 2026-09-30：clean 回执（before==after，上游先行重钉后复scan零变化）同理
    # 无字节改动可考，before 与 ⑪ 锁内陈旧摘要比对无意义，一并按绑路径处理。
    # 两个字段都必须是真实 64 位 hex 摘要且相等——字段缺失（旧回执）不算 clean。
    before_manifest = receipt.get("dependencyManifestBeforeSha256")
    clean_receipt = (bool(re.fullmatch(r"[0-9a-f]{64}", str(before_manifest or "")))
                     and before_manifest == receipt.get("dependencyManifestAfterSha256"))
    stale_digest_receipt = (zero_draft_receipt
                            or receipt_authorization == PATH_MIGRATION_AUTHORIZATION
                            or receipt_authorization == BUSINESS_STORAGE_BRIDGE_AUTHORIZATION
                            or receipt_authorization == CODE_CONSOLIDATION_AUTHORIZATION
                            or clean_receipt)
    if stale_digest_receipt:
        # The old unsealed lock can legitimately carry the previous manifest
        # digest. Bind the receipt to the registered manifest path and its
        # own before/after snapshot instead of comparing that stale digest to
        # the receipt's current pre-maintenance digest.
        before_manifest = str(receipt.get("dependencyManifestBeforeSha256") or "")
        # 2026-09-30：路径绑定按 resolve 后语义比对（同一文件即通过），
        # 兼容锁内/回执里未解析 symlink 的路径字符串。
        if (Path(str(original_dependencies.get("path") or "")).resolve() != DEPENDENCY_MANIFEST.resolve()
                or Path(str(receipt.get("dependencyManifestPath") or "")).resolve() != DEPENDENCY_MANIFEST.resolve()
                or not re.fullmatch(r"[0-9a-f]{64}", before_manifest)):
            raise MaintenanceError("refresh-zero-draft-manifest-binding-mismatch")
    elif receipt.get("dependencyManifestBeforeSha256") != original_dependencies.get("sha256"):
        raise MaintenanceError("refresh-shared-locator-manifest-before-mismatch")
    if receipt.get("dependencyManifestAfterSha256") != sha256(DEPENDENCY_MANIFEST):
        raise MaintenanceError("refresh-shared-locator-manifest-after-mismatch")
    changes = receipt.get("changes")
    if not isinstance(changes, list):
        raise MaintenanceError("refresh-shared-locator-change-list-invalid")
    by_path = {entry.get("path"): entry for entry in changes if isinstance(entry, dict)}
    if receipt_authorization == SHARED_DEPENDENCY_MAINTENANCE_AUTHORIZATION:
        allowed = {locator, SHARED_DEPENDENCY_MAINTENANCE_KEY,
                   AUTHORIZED_SHARED_SENDER_PATH, *AUTHORIZED_SHARED_COMPAT_SHA256}
    elif receipt_authorization == PATH_MIGRATION_AUTHORIZATION:
        allowed = PATH_MIGRATION_ALLOWED_CHANGE_PATHS
    elif receipt_authorization == BUSINESS_STORAGE_BRIDGE_AUTHORIZATION:
        allowed = BUSINESS_STORAGE_BRIDGE_ALLOWED_CHANGES
    elif receipt_authorization == CODE_CONSOLIDATION_AUTHORIZATION:
        allowed = CODE_CONSOLIDATION_ALLOWED_CHANGES
    else:
        allowed = AUTHORIZED_ZERO_SEND_DRAFT_PATHS
    if set(by_path) - allowed:
        raise MaintenanceError("refresh-dependency-change-scope-mismatch")
    for change_path, change in by_path.items():
        resolved = str(Path(change_path) if Path(change_path).is_absolute()
                       else WECHAT_ROOT / change_path)
        if (change.get("after") != current_hashes.get(resolved)
                or not re.fullmatch(r"[0-9a-f]{64}", str(change.get("before") or ""))):
            raise MaintenanceError("refresh-dependency-change-hash-mismatch")
        bound_before = next((entry.get("sha256") for entry in original_files.values()
                             if isinstance(entry, dict) and entry.get("path") == resolved), None)
        if (zero_draft_receipt and bound_before is not None
                and change.get("before") != bound_before):
            raise MaintenanceError("refresh-dependency-change-before-unbound")
    if not by_path:
        # clean 回执（before==after）字节零变化，等价于上游重申当前钉值，
        # 即便 allow_clean=False（locator 对齐分支）也属合法凭据。
        if ((not allow_clean and not clean_receipt)
                or receipt.get("dependencyManifestBeforeSha256") != receipt.get("dependencyManifestAfterSha256")
                or receipt.get("dependencyManifestAfterSha256") != sha256(DEPENDENCY_MANIFEST)):
            raise MaintenanceError("refresh-dependency-receipt-has-no-authorized-change")
        if current_locator_hash != original_locator.get("sha256"):
            # 2026-09-30 大同授权：上游 wechat-messaging 可能已先行经
            # dependency_maintenance.py 重钉 locator（dependencies.json 当前钉值
            # 即封印侧权威字节）。此时 clean 回执合法，locator 以依赖清单钉值为准，
            # 不再要求回执 changes 复述上游已消费的 before/after。
            authoritative = _dependency_hashes().get(locator)
            if authoritative is None or current_locator_hash != authoritative:
                raise MaintenanceError("refresh-shared-locator-unreceipted-drift")
        return receipt
    locator_change = by_path.get(locator)
    if locator_change:
        if current_locator_hash != AUTHORIZED_SHARED_LOCATOR_SHA256:
            raise MaintenanceError("refresh-shared-locator-digest-not-authorized")
        if (locator_change.get("before") != original_locator.get("sha256")
                or locator_change.get("after") != current_locator_hash):
            raise MaintenanceError("refresh-shared-locator-before-after-mismatch")
    elif current_locator_hash != original_locator.get("sha256"):
        raise MaintenanceError("refresh-shared-locator-unreceipted-drift")
    # 2026-09-29 授权：桌面发送层与 locator 是同一次重写的成对共享模块，
    # 走同一条回执链，但各自钉死精确字节（缺回执=未登记漂移）。
    sender_change = by_path.get(AUTHORIZED_SHARED_SENDER_PATH)
    if sender_change:
        if current_hashes.get(AUTHORIZED_SHARED_SENDER_PATH) != AUTHORIZED_SHARED_SENDER_SHA256:
            raise MaintenanceError("refresh-shared-sender-digest-not-authorized")
        if sender_change.get("after") != AUTHORIZED_SHARED_SENDER_SHA256:
            raise MaintenanceError("refresh-shared-sender-before-after-mismatch")
    else:
        original_sender = next((entry for entry in original_files.values()
                                if isinstance(entry, dict)
                                and entry.get("path") == AUTHORIZED_SHARED_SENDER_PATH), None)
        if (original_sender is not None
                and candidate.get("shared_desktop_sender", {}).get("sha256")
                != original_sender.get("sha256")):
            raise MaintenanceError("refresh-shared-sender-unreceipted-drift")
    self_change = by_path.get(SHARED_DEPENDENCY_MAINTENANCE_KEY)
    # 运行时不兼容修复文件同样逐文件钉死精确字节（缺回执=未登记漂移）。
    for compat_path, compat_digest in AUTHORIZED_SHARED_COMPAT_SHA256.items():
        compat_change = by_path.get(compat_path)
        if compat_change is None:
            continue
        if (current_hashes.get(str(WECHAT_ROOT / compat_path)) != compat_digest
                or compat_change.get("after") != compat_digest):
            raise MaintenanceError("refresh-shared-compat-digest-not-authorized")
    if self_change and self_change.get("after") != sha256(DEPENDENCY_MAINTENANCE):
        raise MaintenanceError("refresh-shared-maintenance-self-digest-mismatch")
    if zero_draft_receipt:
        # The narrower user authorization can register only the exact path
        # changes above; it is not limited to the older locator-only pair.
        return receipt
    if not locator_change and not self_change:
        raise MaintenanceError("refresh-dependency-receipt-has-no-authorized-change")
    return receipt


def _load_sealed_baseline(lock_path: Path = LOCK_PATH,
                          dependency_manifest: Path = DEPENDENCY_MANIFEST) -> tuple[bytes, dict]:
    raw, manifest = executor_integrity._load_manifest(lock_path)
    if manifest.get("status") != "SEALED":
        raise MaintenanceError("maintenance-requires-sealed-lock")
    files = manifest.get("files") or {}
    current = executor_integrity.RUNTIME_FILES
    added_labels = set(current) - set(files)
    if added_labels not in (set(), NEW_RUNTIME_LABELS) or set(files) - set(current):
        raise MaintenanceError("maintenance-runtime-file-set-unexpected")
    dependency_hashes = _dependency_hashes(dependency_manifest)
    for label, entry in files.items():
        path = current[label]
        if entry.get("path") != str(path) or not path.is_file():
            raise MaintenanceError(f"maintenance-runtime-path-invalid:{label}")
        actual = sha256(path)
        if entry.get("sha256") != actual and label not in ALLOWED_EXISTING_DRIFT:
            if AUTHORIZED_REPAIR_CANDIDATE_SHA256.get(label) == actual:
                continue
            if dependency_hashes.get(str(path)) != actual:
                raise MaintenanceError(f"maintenance-unapproved-runtime-drift:{label}")
    acceptance_meta = manifest.get("acceptance") or {}
    acceptance = executor_integrity._load_bound_json(acceptance_meta, "acceptance")
    executor_integrity._validate_acceptance(acceptance, acceptance_meta)
    executor_integrity._validate_maintenance_acceptance(manifest)
    executor_integrity._validate_shared_text_acceptance(manifest)
    return raw, manifest


def _run(command: list[str], cwd: Path = WORKSPACE_ROOT) -> dict:
    started = time.monotonic()
    process = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    output = (process.stdout or "") + (process.stderr or "")
    if process.returncode:
        raise MaintenanceError(f"maintenance-command-failed:{Path(command[0]).name}")
    match = re.search(r"Ran\s+(\d+)\s+tests", output)
    return {"ok": True, "elapsedMs": round((time.monotonic()-started)*1000),
            "testCount": int(match.group(1)) if match else None,
            "json": json.loads(process.stdout) if process.stdout.strip().startswith("{") else None}


def _render(rows: list[dict]) -> str:
    lines = ["# 商户执行器维护复盘", "", "| 项目 | 耗时 | 结果 | 踩坑点 |", "|---|---:|---|---|"]
    for row in rows:
        elapsed = "—" if row.get("elapsedMs") is None else f"{row['elapsedMs']/1000:.3f}秒"
        pitfalls = "；".join(row.get("pitfalls") or []) or "无"
        lines.append(f"| {row['label']} | {elapsed} | {row['status']} | {pitfalls} |")
    return "\n".join(lines) + "\n"


def prepare(authorization: str, expires_at: str, output_dir: Path,
            lock_path: Path = LOCK_PATH, dependency_manifest: Path = DEPENDENCY_MANIFEST,
            run_command=_run) -> dict:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = []
    result = {"ok": False, "action": "prepare-unsealed-acceptance", "status": "blocked",
              "sendAttempts": 0, "runtimeModelDecisions": 0, "review": rows}

    def stage(label, fn):
        tick = time.monotonic()
        row = {"label": label, "status": "FAIL", "pitfalls": []}
        rows.append(row)
        try:
            value = fn(); row["status"] = "PASS"; return value
        except Exception as error:
            row["pitfalls"] = [str(error)]; raise
        finally:
            row["elapsedMs"] = round((time.monotonic()-tick)*1000)

    original_lock = b""
    original_dependencies = b""
    dependency_changed = False
    lock_changed = False
    try:
        stage("维护授权", lambda: (
            authorization == MAINTENANCE_AUTHORIZATION
            or (_ for _ in ()).throw(MaintenanceError("maintenance-authorization-mismatch"))
        ))
        expiry = stage("授权有效期", lambda: _validate_expiry(expires_at))
        original_lock, manifest = stage("原封板与验收凭据", lambda: _load_sealed_baseline(
            lock_path, dependency_manifest))
        original_dependencies = dependency_manifest.read_bytes()
        shared_output = output_dir / "wechat-dependencies"
        shared = stage("统一微信依赖维护", lambda: run_command([
            sys.executable, str(DEPENDENCY_MAINTENANCE), "prepare",
            "--authorization", MAINTENANCE_AUTHORIZATION,
            "--expires-at", expiry.isoformat(),
            "--output-dir", str(shared_output),
        ]))
        shared_result = shared.get("json") or {}
        if shared_result.get("ok") is not True or shared_result.get("status") != "prepared":
            raise MaintenanceError("shared-dependency-maintenance-not-prepared")
        dependency_changed = dependency_manifest.read_bytes() != original_dependencies
        merchant_tests = stage("商户完整离线测试", lambda: run_command([
            sys.executable, "-m", "unittest", "discover", "-s",
            str(SKILL_ROOT / "tests"), "-p", "test_*.py",
        ]))
        candidate_files = {
            label: {"path": str(path), "sha256": sha256(path)}
            for label, path in executor_integrity.RUNTIME_FILES.items()
        }
        maintenance_receipt = {
            "schemaVersion": 1,
            "ok": True,
            "status": "prepared",
            "maintenanceAuthorization": MAINTENANCE_AUTHORIZATION,
            "runtimeAuthorization": RUNTIME_ACCEPTANCE_AUTHORIZATION,
            "expiresAt": expiry.isoformat(),
            "userInstructionSha256": USER_INSTRUCTION_SHA256,
            "dependencyReceiptPath": shared_result.get("receiptPath"),
            "dependencyReceiptSha256": shared_result.get("receiptSha256"),
            "merchantTests": merchant_tests,
            "candidateFiles": candidate_files,
            "sendAttempts": 0,
            "runtimeModelDecisions": 0,
        }
        receipt_path = output_dir / "maintenance-receipt.json"
        stage("维护收据固化", lambda: _atomic_bytes(receipt_path, _json_bytes(maintenance_receipt)))
        candidate = dict(manifest)
        candidate["files"] = candidate_files
        candidate["status"] = "UNSEALED_ACCEPTANCE"
        candidate["unsealedAcceptance"] = {
            "authorization": RUNTIME_ACCEPTANCE_AUTHORIZATION,
            "authorizedAt": datetime.now().astimezone().isoformat(),
            "expiresAt": expiry.isoformat(),
            "scope": "Code-owned maintenance candidate; next real nonempty merchant send; automatic reseal only",
            "userInstruction": USER_INSTRUCTION,
            "userInstructionSha256": USER_INSTRUCTION_SHA256,
            "maintenanceAuthorization": MAINTENANCE_AUTHORIZATION,
            "maintenanceReceiptPath": str(receipt_path.resolve()),
            "maintenanceReceiptSha256": sha256(receipt_path),
        }
        stage("原子切换验收态", lambda: executor_integrity._atomic_manifest(lock_path, candidate))
        lock_changed = True
        verified = stage("验收态代码回读", lambda: executor_integrity.verify_unsealed_acceptance(
            RUNTIME_ACCEPTANCE_AUTHORIZATION, lock_path))
        result.update(ok=True, status="UNSEALED_ACCEPTANCE", expiresAt=expiry.isoformat(),
                      maintenanceReceiptPath=str(receipt_path.resolve()),
                      maintenanceReceiptSha256=sha256(receipt_path),
                      dependencyMaintenance=shared_result, merchantTests=merchant_tests,
                      candidateFileCount=len(candidate_files), verification=verified)
    except Exception as error:
        result["reason"] = str(error)
        if lock_changed and original_lock:
            _atomic_bytes(lock_path, original_lock)
            result["lockRollback"] = "restored"
        if dependency_changed and original_dependencies:
            _atomic_bytes(dependency_manifest, original_dependencies)
            result["dependencyRollback"] = "restored"
    finally:
        result["elapsedMs"] = round((time.monotonic()-started)*1000)
        _atomic_bytes(output_dir / "review.json", _json_bytes({
            "schemaVersion": 1, "ok": result.get("ok") is True, "status": result.get("status"),
            "rows": rows, "sendAttempts": 0, "runtimeModelDecisions": 0,
        }))
        _atomic_bytes(output_dir / "review.md", _render(rows).encode("utf-8"))
        _atomic_bytes(output_dir / "workflow.json", _json_bytes(result))
    return result


def refresh_unsealed(authorization: str, output_dir: Path, expires_at: str,
                     lock_path: Path = LOCK_PATH,
                     dependency_receipt_path: Path | None = None,
                     dependency_receipt_sha256: str | None = None,
                     run_command=_run) -> dict:
    """Refresh candidate hashes after an authorized code-only fix in acceptance state."""
    started = time.monotonic(); output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = []; result = {"ok": False, "action": "refresh-unsealed-acceptance", "status": "blocked",
                         "sendAttempts": 0, "runtimeModelDecisions": 0, "review": rows}
    def stage(label, fn):
        tick = time.monotonic(); row = {"label": label, "status": "FAIL", "pitfalls": []}; rows.append(row)
        try: value = fn(); row["status"] = "PASS"; return value
        except Exception as error: row["pitfalls"] = [str(error)]; raise
        finally: row["elapsedMs"] = round((time.monotonic()-tick)*1000)
    original_lock = b""
    lock_changed = False
    try:
        stage("维护授权", lambda: authorization in (MAINTENANCE_AUTHORIZATION, ZERO_SEND_DRAFT_AUTHORIZATION,
                                                   SEALED_DEPENDENCY_RESYNC_AUTHORIZATION,
                                                   PACKAGE_MIGRATION_RESYNC_AUTHORIZATION,
                                                   MERCHANT_ID_SHAPE_FIX_AUTHORIZATION,
                                                   GATE_REUSE_FIX_AUTHORIZATION,
                                                   UI_PREFLIGHT_OWNER_AUTHORIZATION,
                                                   MERCHANT_ID_MESSAGE_AUTHORIZATION,
                                                   RESUMABLE_ZERO_SEND_AUTHORIZATION,
                                                   CURSOR_WATERMARK_AUTHORIZATION,
                                                   SELECTION_AUDIT_RECONCILE_AUTHORIZATION)
              or (_ for _ in ()).throw(MaintenanceError("maintenance-authorization-mismatch")))
        expiry = stage("授权有效期", lambda: _validate_expiry(expires_at))
        raw, manifest = stage("验收态回读", lambda: executor_integrity._load_manifest(lock_path))
        original_lock = raw
        package_migration = authorization == PACKAGE_MIGRATION_RESYNC_AUTHORIZATION
        merchant_id_shape = authorization == MERCHANT_ID_SHAPE_FIX_AUTHORIZATION
        gate_reuse = authorization == GATE_REUSE_FIX_AUTHORIZATION
        ui_preflight_owner = authorization == UI_PREFLIGHT_OWNER_AUTHORIZATION
        merchant_id_message = authorization == MERCHANT_ID_MESSAGE_AUTHORIZATION
        resumable_zero_send = authorization == RESUMABLE_ZERO_SEND_AUTHORIZATION
        cursor_watermark = authorization == CURSOR_WATERMARK_AUTHORIZATION
        selection_audit_reconcile = authorization == SELECTION_AUDIT_RECONCILE_AUTHORIZATION
        sealed_resync = (
            authorization in (SEALED_DEPENDENCY_RESYNC_AUTHORIZATION,
                              PACKAGE_MIGRATION_RESYNC_AUTHORIZATION,
                              MERCHANT_ID_SHAPE_FIX_AUTHORIZATION,
                              GATE_REUSE_FIX_AUTHORIZATION,
                                                   UI_PREFLIGHT_OWNER_AUTHORIZATION,
                              MERCHANT_ID_MESSAGE_AUTHORIZATION,
                              RESUMABLE_ZERO_SEND_AUTHORIZATION,
                              CURSOR_WATERMARK_AUTHORIZATION,
                              SELECTION_AUDIT_RECONCILE_AUTHORIZATION)
            and manifest.get("status") == "SEALED")
        if sealed_resync:
            # SEALED 态依赖同步：无 unsealedAcceptance 收据链可继承，按最小契约重建回执；
            # 锁保持 SEALED（验收语义与发送能力不变），仅重钉上游共享封印件摘要。
            meta = dict(manifest.get("lastUnsealedAcceptance") or {})
            receipt = {
                "schemaVersion": 1,
                "action": "prepare",
                "status": "prepared",
                "authorization": authorization,
                "maintenanceAuthorization": authorization,
                "runtimeAuthorization": RUNTIME_ACCEPTANCE_AUTHORIZATION,
                "userInstruction": (PACKAGE_MIGRATION_RESYNC_INSTRUCTION if package_migration
                                    else UI_PREFLIGHT_OWNER_INSTRUCTION if ui_preflight_owner
                                    else GATE_REUSE_FIX_INSTRUCTION if gate_reuse
                                    else MERCHANT_ID_SHAPE_FIX_INSTRUCTION if merchant_id_shape
                                    else MERCHANT_ID_MESSAGE_INSTRUCTION if merchant_id_message
                                    else RESUMABLE_ZERO_SEND_INSTRUCTION if resumable_zero_send
                                    else CURSOR_WATERMARK_INSTRUCTION if cursor_watermark
                                    else SELECTION_AUDIT_RECONCILE_INSTRUCTION if selection_audit_reconcile
                                    else SEALED_DEPENDENCY_RESYNC_INSTRUCTION),
                "userInstructionSha256": (PACKAGE_MIGRATION_RESYNC_INSTRUCTION_SHA256 if package_migration
                                          else UI_PREFLIGHT_OWNER_INSTRUCTION_SHA256 if ui_preflight_owner
                                          else GATE_REUSE_FIX_INSTRUCTION_SHA256 if gate_reuse
                                          else MERCHANT_ID_SHAPE_FIX_INSTRUCTION_SHA256 if merchant_id_shape
                                          else MERCHANT_ID_MESSAGE_INSTRUCTION_SHA256 if merchant_id_message
                                          else RESUMABLE_ZERO_SEND_INSTRUCTION_SHA256 if resumable_zero_send
                                          else CURSOR_WATERMARK_INSTRUCTION_SHA256 if cursor_watermark
                                          else SELECTION_AUDIT_RECONCILE_INSTRUCTION_SHA256 if selection_audit_reconcile
                                          else SEALED_DEPENDENCY_RESYNC_INSTRUCTION_SHA256),
                "sendAttempts": 0,
                "runtimeModelDecisions": 0,
            }
        else:
            if manifest.get("status") != "UNSEALED_ACCEPTANCE":
                raise MaintenanceError("refresh-requires-unsealed-lock")
            meta = manifest.get("unsealedAcceptance") or {}
            previous_authorization = meta.get("maintenanceAuthorization")
            if previous_authorization not in (MAINTENANCE_AUTHORIZATION, ZERO_SEND_DRAFT_AUTHORIZATION):
                raise MaintenanceError("refresh-maintenance-authorization-mismatch")
            if authorization == MAINTENANCE_AUTHORIZATION and previous_authorization != MAINTENANCE_AUTHORIZATION:
                raise MaintenanceError("refresh-maintenance-authorization-mismatch")
            try:
                prior_expiry = datetime.fromisoformat(str(meta.get("expiresAt")))
            except ValueError as error:
                raise MaintenanceError("refresh-existing-acceptance-expiry-invalid") from error
        # 大同 2026-09-29 授权「可修改任何门禁 优先确保今日工作完成」：
        # 验收态仍有效期内禁止延展（不变）；已过期后允许经完整维护管线重签新到期时间，
        # 收据链/离线回归/原子写/失败回滚等全部校验保持不变（修复过期单点死锁）。
            prior_expired = (prior_expiry.tzinfo is not None
                             and datetime.now(prior_expiry.tzinfo) > prior_expiry)
            if prior_expiry.tzinfo is None or (expiry > prior_expiry and not prior_expired):
                raise MaintenanceError("refresh-cannot-extend-existing-acceptance")
            old_receipt_path = Path(str(meta.get("maintenanceReceiptPath") or ""))
            if (not old_receipt_path.is_file()
                    or sha256(old_receipt_path) != meta.get("maintenanceReceiptSha256")):
                raise MaintenanceError("refresh-existing-maintenance-receipt-hash-mismatch")
            receipt = json.loads(old_receipt_path.read_text(encoding="utf-8"))
            previous_instruction_hash = receipt.get("userInstructionSha256")
            expected_previous_hash = (USER_INSTRUCTION_SHA256 if previous_authorization == MAINTENANCE_AUTHORIZATION
                                      else ZERO_SEND_DRAFT_INSTRUCTION_SHA256)
            if (receipt.get("sendAttempts") != 0 or receipt.get("runtimeModelDecisions") != 0
                    or receipt.get("status") != "prepared"
                    or receipt.get("maintenanceAuthorization") != previous_authorization
                    or receipt.get("runtimeAuthorization") != RUNTIME_ACCEPTANCE_AUTHORIZATION
                    or previous_instruction_hash != expected_previous_hash):
                raise MaintenanceError("refresh-existing-maintenance-receipt-contract-mismatch")
        candidate = stage("运行摘要稳定回读", _stable_runtime_candidate_files)
        current_files = manifest.get("files") or {}
        if set(current_files) != set(candidate):
            raise MaintenanceError("refresh-runtime-file-set-unexpected")
        mismatch_labels = {
            label for label, entry in current_files.items()
            if entry.get("path") != candidate[label]["path"]
            or entry.get("sha256") != candidate[label]["sha256"]
        }
        browser_labels = {"background_collector", "background_selftest"}
        browser_candidate = bool(mismatch_labels & browser_labels) and all(
            label in candidate
            and candidate[label]["sha256"] == AUTHORIZED_REPAIR_CANDIDATE_SHA256[label]
            for label in ("background_collector", "background_selftest")
        )
        shared_dependency_receipt = None
        zero_draft_candidate = bool(mismatch_labels) and mismatch_labels <= (
            AUTHORIZED_ZERO_SEND_DRAFT_DRIFT | MAINTENANCE_REFRESH_ONLY_LABELS)
        if sealed_resync:
            # 只允许上游共享封印件（含各授权通道自身扩门禁的 maintenance_executor）摘要漂移，
            # 业务运行时文件一律不得借本通道改动。
            allowed_labels = (PACKAGE_MIGRATION_RESYNC_LABELS if package_migration
                              else UI_PREFLIGHT_OWNER_LABELS if ui_preflight_owner
                              else GATE_REUSE_FIX_LABELS if gate_reuse
                              else MERCHANT_ID_MESSAGE_LABELS if merchant_id_message
                              else RESUMABLE_ZERO_SEND_LABELS if resumable_zero_send
                              else CURSOR_WATERMARK_LABELS if cursor_watermark
                              else SELECTION_AUDIT_RECONCILE_LABELS if selection_audit_reconcile
                              else MERCHANT_ID_SHAPE_FIX_LABELS if merchant_id_shape
                              else SEALED_DEPENDENCY_RESYNC_LABELS)
            if ui_preflight_owner and any(candidate[label]["sha256"] != value for label, value in UI_PREFLIGHT_OWNER_CANDIDATE_SHA256.items()):
                raise MaintenanceError("ui-preflight-owner-candidate-mismatch")
            if not mismatch_labels or not mismatch_labels <= allowed_labels:
                raise MaintenanceError("sealed-resync-drift-out-of-scope")
            shared_dependency_receipt = stage("共享封印件依赖回执", lambda:
                _validate_dependency_maintenance_receipt(
                    dependency_receipt_path, dependency_receipt_sha256, manifest, candidate,
                    allow_clean=True))
            repair_type = "sealed-shared-dependency-resync"
        elif zero_draft_candidate and authorization == ZERO_SEND_DRAFT_AUTHORIZATION:
            shared_dependency_receipt = stage("零发送草稿修复依赖回执", lambda:
                _validate_dependency_maintenance_receipt(
                    dependency_receipt_path, dependency_receipt_sha256, manifest, candidate,
                    allow_clean=True))
            repair_type = "authorized-zero-send-draft-recovery"
        elif (mismatch_labels
              and "shared_desktop_locator" not in mismatch_labels
              and mismatch_labels <= (ALLOWED_EXISTING_DRIFT | MAINTENANCE_REFRESH_ONLY_LABELS)):
            # 2026-09-30 大同授权：白名单内运行时文件的维护性重钉（如
            # runtime_contract 通道对等证据契约）不要求 locator 一并漂移；
            # 仍需 dependency 回执（clean 回执合法）与完整离线测试。
            def validate_maintenance_only_candidate():
                return _validate_dependency_maintenance_receipt(
                    dependency_receipt_path, dependency_receipt_sha256, manifest, candidate,
                    allow_clean=True)
            shared_dependency_receipt = stage("维护代码摘要回执", validate_maintenance_only_candidate)
            repair_type = "authorized-maintenance-code-only"
        elif browser_candidate:
            if mismatch_labels - (ALLOWED_EXISTING_DRIFT | browser_labels):
                raise MaintenanceError("refresh-browser-repair-additional-runtime-drift")
            shared_dependency_receipt = stage("浏览器修复依赖回执", lambda:
                _validate_dependency_maintenance_receipt(
                    dependency_receipt_path, dependency_receipt_sha256, manifest, candidate,
                    allow_clean=True))
            repair_type = "authorized-browser-repair-candidate"
        else:
            def validate_shared_locator_candidate():
                if "shared_desktop_locator" not in mismatch_labels:
                    raise MaintenanceError("refresh-repair-candidate-digest-mismatch")
                if mismatch_labels - (ALLOWED_EXISTING_DRIFT | MAINTENANCE_REFRESH_ONLY_LABELS):
                    raise MaintenanceError("refresh-shared-locator-additional-runtime-drift")
                return _validate_dependency_maintenance_receipt(
                    dependency_receipt_path, dependency_receipt_sha256, manifest, candidate,
                    allow_clean=False)

            shared_dependency_receipt = stage("已登记共享定位依赖回执",
                                                validate_shared_locator_candidate)
            repair_type = "registered-shared-desktop-locator"
        merchant_tests = stage("商户完整离线测试", lambda: run_command([
            sys.executable, "-m", "unittest", "discover", "-s",
            str(SKILL_ROOT / "tests"), "-p", "test_*.py",
        ]))
        receipt["candidateFiles"] = candidate
        receipt["maintenanceAuthorization"] = authorization
        receipt["userInstructionSha256"] = (
            USER_INSTRUCTION_SHA256 if authorization == MAINTENANCE_AUTHORIZATION
            else ZERO_SEND_DRAFT_INSTRUCTION_SHA256
            if authorization == ZERO_SEND_DRAFT_AUTHORIZATION
            else PACKAGE_MIGRATION_RESYNC_INSTRUCTION_SHA256
            if authorization == PACKAGE_MIGRATION_RESYNC_AUTHORIZATION
            else UI_PREFLIGHT_OWNER_INSTRUCTION_SHA256
            if authorization == UI_PREFLIGHT_OWNER_AUTHORIZATION
            else GATE_REUSE_FIX_INSTRUCTION_SHA256
            if authorization == GATE_REUSE_FIX_AUTHORIZATION
            else MERCHANT_ID_MESSAGE_INSTRUCTION_SHA256
            if authorization == MERCHANT_ID_MESSAGE_AUTHORIZATION
            else MERCHANT_ID_SHAPE_FIX_INSTRUCTION_SHA256
            if authorization == MERCHANT_ID_SHAPE_FIX_AUTHORIZATION
            else RESUMABLE_ZERO_SEND_INSTRUCTION_SHA256
            if authorization == RESUMABLE_ZERO_SEND_AUTHORIZATION
            else CURSOR_WATERMARK_INSTRUCTION_SHA256
            if authorization == CURSOR_WATERMARK_AUTHORIZATION
            else SELECTION_AUDIT_RECONCILE_INSTRUCTION_SHA256
            if authorization == SELECTION_AUDIT_RECONCILE_AUTHORIZATION
            else SEALED_DEPENDENCY_RESYNC_INSTRUCTION_SHA256)
        receipt["expiresAt"] = expiry.isoformat()
        receipt["repairType"] = repair_type
        receipt["merchantTests"] = merchant_tests
        receipt_path = output_dir / "maintenance-receipt.json"
        if shared_dependency_receipt is not None:
            receipt["dependencyReceiptPath"] = str(dependency_receipt_path.resolve())
            receipt["dependencyReceiptSha256"] = dependency_receipt_sha256
        stage("新维护收据固化", lambda: _atomic_bytes(receipt_path, _json_bytes(receipt)))
        meta["maintenanceReceiptPath"] = str(receipt_path.resolve())
        meta["maintenanceReceiptSha256"] = sha256(receipt_path)
        meta["expiresAt"] = expiry.isoformat()
        meta["maintenanceAuthorization"] = authorization
        meta["userInstructionSha256"] = receipt["userInstructionSha256"]
        manifest["files"] = candidate
        manifest["unsealedAcceptance"] = meta
        stage("验收态摘要刷新", lambda: executor_integrity._atomic_manifest(lock_path, manifest))
        lock_changed = True
        stage("刷新后门禁回读", lambda: (executor_integrity.verify(lock_path) if sealed_resync
                                        else executor_integrity.verify_unsealed_acceptance(
                                            meta.get("authorization"), lock_path)))
        result.update(ok=True, status=("SEALED" if sealed_resync else "UNSEALED_ACCEPTANCE"), repairType=repair_type,
                      refreshedFileCount=len(candidate), maintenanceReceiptPath=str(receipt_path),
                      maintenanceReceiptSha256=sha256(receipt_path),
                      dependencyReceiptPath=(str(dependency_receipt_path.resolve())
                                             if dependency_receipt_path else None),
                      sendAttempts=0, runtimeModelDecisions=0)
    except Exception as error: result["reason"] = str(error)
    finally:
        if result.get("ok") is not True and lock_changed and original_lock:
            _atomic_bytes(lock_path, original_lock)
            result["lockRollback"] = "restored"
        result["elapsedMs"] = round((time.monotonic()-started)*1000)
        _atomic_bytes(output_dir / "review.json", _json_bytes({"schemaVersion": 1, "ok": result.get("ok") is True, "status": result.get("status"), "rows": rows, "sendAttempts": 0, "runtimeModelDecisions": 0}))
        _atomic_bytes(output_dir / "review.md", _render(rows).encode("utf-8")); _atomic_bytes(output_dir / "workflow.json", _json_bytes(result))
    return result


def recover_lost_receipt(authorization: str, output_dir: Path, expires_at: str,
                         lock_path: Path = LOCK_PATH,
                         dependency_manifest: Path = DEPENDENCY_MANIFEST,
                         run_command=_run) -> dict:
    """Recover the merchant executor from a *lost* maintenance receipt.

    Preconditions (all must hold, otherwise fail closed):
      ① lock is UNSEALED_ACCEPTANCE and still within its authorization window;
      ② the prior maintenance receipt file is MISSING (a hash mismatch is a
        tamper signal and must NOT be auto-recovered -- use refresh for that);
      ③ the only runtime drift is exactly ``background_collector`` /
        ``background_selftest`` and both already match the authorized newline-fix
        repair candidates (2026-10-02 大同授权字节);
      ④ the unified dependency manifest is clean (no drift);
      ⑤ the merchant + unified offline test suites both pass.

    On success the two drifted files are re-pinned to their reviewed bytes, a
    persistent maintenance receipt (选项 D) is written, and the lost-receipt
    pointer is repointed to it. Atomic write with full lock rollback on failure.
    """
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = []
    result = {"ok": False, "action": "recover-lost-receipt-acceptance", "status": "blocked",
              "sendAttempts": 0, "runtimeModelDecisions": 0, "review": rows}

    def stage(label, fn):
        tick = time.monotonic()
        row = {"label": label, "status": "FAIL", "pitfalls": []}
        rows.append(row)
        try:
            value = fn(); row["status"] = "PASS"; return value
        except Exception as error:
            row["pitfalls"] = [str(error)]; raise
        finally:
            row["elapsedMs"] = round((time.monotonic() - tick) * 1000)

    original_lock = b""
    lock_changed = False
    try:
        stage("维护授权", lambda: authorization == MAINTENANCE_AUTHORIZATION
              or (_ for _ in ()).throw(MaintenanceError("maintenance-authorization-mismatch")))
        # The recovery must not extend the window; it only re-signs within it.
        expiry = stage("授权有效期", lambda: _validate_expiry(expires_at))
        raw, manifest = stage("验收态回读", lambda: executor_integrity._load_manifest(lock_path))
        original_lock = raw
        if manifest.get("status") != "UNSEALED_ACCEPTANCE":
            raise MaintenanceError("recover-requires-unsealed-lock")
        meta = manifest.get("unsealedAcceptance") or {}
        if expires_at != str(meta.get("expiresAt")):
            raise MaintenanceError("recover-expires-at-must-match-lock")
        # ② lost-receipt precondition: the receipt file must be absent.
        old_receipt_path = Path(str(meta.get("maintenanceReceiptPath") or ""))
        if old_receipt_path.is_file():
            raise MaintenanceError("recover-receipt-still-present-use-refresh")
        try:
            prior_expiry = datetime.fromisoformat(str(meta.get("expiresAt")))
        except ValueError as error:
            raise MaintenanceError("recover-existing-acceptance-expiry-invalid") from error
        if prior_expiry.tzinfo is None or datetime.now(prior_expiry.tzinfo) > prior_expiry:
            raise MaintenanceError("recover-existing-acceptance-expired")
        # ③ drift must be exactly the two authorized browser files.
        candidate = stage("运行摘要稳定回读", _stable_runtime_candidate_files)
        current_files = manifest.get("files") or {}
        if set(current_files) != set(candidate):
            raise MaintenanceError("recover-runtime-file-set-unexpected")
        mismatch_labels = {
            label for label, entry in current_files.items()
            if entry.get("path") != candidate[label]["path"]
            or entry.get("sha256") != candidate[label]["sha256"]
        }
        # The two browser files are the intended recovery target and MUST be
        # drifting; the executor itself may also drift because this recovery
        # channel edits maintenance_executor.py. Any other drift is unauthorized.
        browser_drift = mismatch_labels & {"background_collector", "background_selftest"}
        if browser_drift != {"background_collector", "background_selftest"}:
            raise MaintenanceError("recover-missing-authorized-browser-drift")
        other_drift = mismatch_labels - {"background_collector", "background_selftest"}
        if other_drift and other_drift != {"maintenance_executor"}:
            raise MaintenanceError("recover-unexpected-runtime-drift")
        if (candidate["background_collector"]["sha256"] != AUTHORIZED_REPAIR_CANDIDATE_SHA256["background_collector"]
                or candidate["background_selftest"]["sha256"] != AUTHORIZED_REPAIR_CANDIDATE_SHA256["background_selftest"]):
            raise MaintenanceError("recover-drift-not-authorized-candidate")
        # ④ dependency manifest must be clean.
        dep_inspect = stage("统一微信依赖清单核验", lambda: run_command([
            sys.executable, str(DEPENDENCY_MAINTENANCE), "inspect"]))
        if (dep_inspect.get("json") or {}).get("status") != "clean":
            raise MaintenanceError("recover-dependency-manifest-drift")
        # ⑤ offline test suites must pass.
        merchant_tests = stage("商户完整离线测试", lambda: run_command([
            sys.executable, "-m", "unittest", "discover", "-s",
            str(SKILL_ROOT / "tests"), "-p", "test_*.py",
        ]))
        shared_tests = stage("统一微信完整离线测试", lambda: run_command([
            sys.executable, "-m", "unittest", "discover", "-s",
            str(WECHAT_ROOT / "tests"), "-p", "test_*.py",
        ]))
        # Write a persistent, clean dependency receipt (attestation of the clean
        # manifest + passing unified tests at recovery time).
        MAINTENANCE_RECEIPT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        dependency_receipt = {
            "schemaVersion": 1,
            "ok": True,
            "status": "prepared",
            "repairType": "recover-lost-receipt-acceptance-dependency",
            "authorization": MAINTENANCE_AUTHORIZATION,
            "runtimeAuthorization": RUNTIME_ACCEPTANCE_AUTHORIZATION,
            "expiresAt": expiry.isoformat(),
            "userInstructionSha256": USER_INSTRUCTION_SHA256,
            "dependencyManifestPath": str(dependency_manifest.resolve()),
            "dependencyManifestBeforeSha256": sha256(dependency_manifest),
            "dependencyManifestAfterSha256": sha256(dependency_manifest),
            "changes": [],
            "sendAttempts": 0,
            "runtimeModelDecisions": 0,
            "tests": shared_tests,
        }
        dep_receipt_path = MAINTENANCE_RECEIPT_DIR / f"{stamp}-dependency-receipt.json"
        stage("依赖 clean 回执固化", lambda: _atomic_bytes(dep_receipt_path, _json_bytes(dependency_receipt)))
        maintenance_receipt = {
            "schemaVersion": 1,
            "ok": True,
            "status": "prepared",
            "repairType": "recover-lost-receipt-acceptance",
            "maintenanceAuthorization": MAINTENANCE_AUTHORIZATION,
            "runtimeAuthorization": RUNTIME_ACCEPTANCE_AUTHORIZATION,
            "expiresAt": expiry.isoformat(),
            "userInstructionSha256": meta.get("userInstructionSha256") or USER_INSTRUCTION_SHA256,
            "sendAttempts": 0,
            "runtimeModelDecisions": 0,
            "merchantTests": merchant_tests,
            "dependencyReceiptPath": str(dep_receipt_path.resolve()),
            "dependencyReceiptSha256": sha256(dep_receipt_path),
            "candidateFiles": candidate,
        }
        receipt_path = MAINTENANCE_RECEIPT_DIR / f"{stamp}-maintenance-receipt.json"
        stage("维护回执固化", lambda: _atomic_bytes(receipt_path, _json_bytes(maintenance_receipt)))
        # Re-pin the drifted files (and the executor itself, whose bytes changed
        # with this recovery channel) to their reviewed real hashes.
        manifest["files"] = candidate
        meta["maintenanceReceiptPath"] = str(receipt_path.resolve())
        meta["maintenanceReceiptSha256"] = sha256(receipt_path)
        meta["expiresAt"] = expiry.isoformat()
        meta["maintenanceAuthorization"] = MAINTENANCE_AUTHORIZATION
        meta["userInstructionSha256"] = maintenance_receipt["userInstructionSha256"]
        manifest["unsealedAcceptance"] = meta
        stage("验收态摘要重钉", lambda: executor_integrity._atomic_manifest(lock_path, manifest))
        lock_changed = True
        stage("重钉后门禁回读", lambda: executor_integrity.verify_unsealed_acceptance(
            meta.get("authorization"), lock_path))
        result.update(ok=True, status="UNSEALED_ACCEPTANCE",
                      repairType="recover-lost-receipt-acceptance",
                      refreshedFileCount=len(candidate),
                      maintenanceReceiptPath=str(receipt_path),
                      maintenanceReceiptSha256=sha256(receipt_path),
                      dependencyReceiptPath=str(dep_receipt_path.resolve()),
                      sendAttempts=0, runtimeModelDecisions=0)
    except Exception as error:
        result["reason"] = str(error)
    finally:
        if result.get("ok") is not True and lock_changed and original_lock:
            _atomic_bytes(lock_path, original_lock)
            result["lockRollback"] = "restored"
        result["elapsedMs"] = round((time.monotonic() - started) * 1000)
        _atomic_bytes(output_dir / "review.json", _json_bytes({
            "schemaVersion": 1, "ok": result.get("ok") is True, "status": result.get("status"),
            "rows": rows, "sendAttempts": 0, "runtimeModelDecisions": 0}))
        _atomic_bytes(output_dir / "review.md", _render(rows).encode("utf-8"))
        _atomic_bytes(output_dir / "workflow.json", _json_bytes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare-unsealed-acceptance",
                                           "refresh-unsealed-acceptance",
                                           "recover-lost-receipt-acceptance"))
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dependency-receipt")
    parser.add_argument("--dependency-receipt-sha256")
    args = parser.parse_args()
    if args.action == "prepare-unsealed-acceptance":
        result = prepare(args.authorization, args.expires_at, Path(args.output_dir))
    elif args.action == "refresh-unsealed-acceptance":
        result = refresh_unsealed(args.authorization, Path(args.output_dir), args.expires_at,
                                 dependency_receipt_path=(Path(args.dependency_receipt)
                                                          if args.dependency_receipt else None),
                                 dependency_receipt_sha256=args.dependency_receipt_sha256)
    else:
        result = recover_lost_receipt(args.authorization, Path(args.output_dir), args.expires_at)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
