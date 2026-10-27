#!/usr/bin/env python3
"""Code-owned dependency manifest maintenance with tests, rollback and receipts."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parents[1]
MANIFEST_PATH = ROOT / "dependencies.json"
SELF_KEY = "scripts/dependency_maintenance.py"
HEARTBEAT_RECOVERY_KEY = "scripts/heartbeat_recovery.py"
DESKTOP_ADAPTER_KEY = "scripts/desktop_adapter.py"
POLICY_REGISTRATION_KEY = "scripts/policy_registration.py"
EGRESS_POLICY_KEY = "scripts/egress_policy.py"
BUSINESS_STORAGE_KEY = "../../runtime/business_storage.py"
# 2026-09-29 `_back` 重指路径迁移导致的依赖摘要漂移。
# 授权话术（大同原话）：「我授权 你修改到能确实 验收通过」
# 白名单严格限定为本次已核对 diff 的三个文件：两个各只改 1 行硬编码路径
# （zhensi_waimai → zhensi_waimai_back），以及维护器自身（给 _run 加 timeout 防挂死）。
PATH_MIGRATION_AUTHORIZATION = "user-20260929-back-path-migration-dependency-resync"
PATH_MIGRATION_INSTRUCTION = "我授权 你修改到能确实 验收通过"
PATH_MIGRATION_INSTRUCTION_SHA256 = hashlib.sha256(
    PATH_MIGRATION_INSTRUCTION.encode("utf-8")
).hexdigest()
PATH_MIGRATION_PATHS = {SELF_KEY, "scripts/mobile_helpers.py", "scripts/mobile_text.py"}

# 2026-10-05 技能包整包迁入 skills/workflows/ 的最终收口：把封印清单里仍写着
# skills/<pkg> 旧绝对路径的两个外部依赖键重写到 skills/workflows/<pkg> 真路径，
# 使 skills/<pkg> 的 symlink 兼容层可以整体下线（重名时保留已有真路径条目）。
# 摘要不随键名变化（指向同一份字节），故本步自身不产生 dependency-drift。
WORKFLOWS_KEY_MIGRATIONS = {
    "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/daily-top10-to-wechat-group/scripts/ocr_vision":
        "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-top10-to-wechat-group/scripts/ocr_vision",
    "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/daily-agent-new-merchants-to-wechat/.runtime/ocr_control_label":
        "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-agent-new-merchants-to-wechat/.runtime/ocr_control_label",
}
# 授权话术（大同原话）：「OK执行吧，我看你还是没迁移好，你Loop起来 把这个事情 做好后。全部在 测试一遍 不要再停下来 和请示了」
WORKFLOWS_MIGRATION_AUTHORIZATION = "user-20261005-workflows-path-migration-final"
WORKFLOWS_MIGRATION_INSTRUCTION = (
    "OK执行吧，我看你还是没迁移好，你Loop起来 把这个事情 做好后。全部在 测试一遍 不要再停下来 和请示了"
)
WORKFLOWS_MIGRATION_INSTRUCTION_SHA256 = hashlib.sha256(
    WORKFLOWS_MIGRATION_INSTRUCTION.encode("utf-8")
).hexdigest()
WORKFLOWS_MIGRATION_ALLOWED_AFTER = {
    "scripts/mobile_helpers.py": "c8ba9505da8f9f44da3e639fe626e28e127a5164f365632f55d1f58fb3330983",
    "scripts/mobile_text.py": "93bbe6d0ca8d4c51e587da21d7b01432a806a6f071ad6f2a56616ac87662bef0",
}

MAINTENANCE_AUTHORIZATION = "user-20260927-minimal-appeal-report-correction-v1-maintenance"
USER_INSTRUCTION = (
    "授权这次最小维护：只登记2026-09-27淘宝及美团差评日报更正事件入口与来源门禁，并按统一微信维护流程更新依赖摘要。"
)
USER_INSTRUCTION_SHA256 = hashlib.sha256(USER_INSTRUCTION.encode("utf-8")).hexdigest()
MERCHANT_MAINTENANCE_AUTHORIZATION = "user-20260918-code-maintenance"
MERCHANT_MAINTENANCE_INSTRUCTION = (
    "允许新增代码化维护执行器，并将生产锁切换为验收态，等待下一家真实商家自动重新封板。"
)
MERCHANT_MAINTENANCE_INSTRUCTION_SHA256 = hashlib.sha256(
    MERCHANT_MAINTENANCE_INSTRUCTION.encode("utf-8")
).hexdigest()
ZERO_SEND_DRAFT_AUTHORIZATION = "user-20260928-merchant-zero-send-draft-recovery"
ZERO_SEND_DRAFT_INSTRUCTION = (
    "授权你修改任何逻辑，因为工作没完成，得完成工作是第一原则；今天的失败输入框已有内容，"
    "若是目标数据直接发送，若不是则清理；尽快完成当日工作。"
)
ZERO_SEND_DRAFT_INSTRUCTION_SHA256 = hashlib.sha256(
    ZERO_SEND_DRAFT_INSTRUCTION.encode("utf-8")
).hexdigest()
ZERO_SEND_DRAFT_PATHS = {
    SELF_KEY,
    "scripts/desktop_adapter.py", "scripts/workflow_bridge.py",
    "scripts/workflow_preflight.py",
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/desktop_sender.py",
}
NEW_STORES_AUTHORIZATION = "user-20260928-daily-new-stores-wechat-gate-repair"
NEW_STORES_INSTRUCTION = "你该修改代码修改代码 不要停下"
NEW_STORES_INSTRUCTION_SHA256 = hashlib.sha256(NEW_STORES_INSTRUCTION.encode("utf-8")).hexdigest()
NEW_STORES_ALLOWED_AFTER = {
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/desktop_sender.py":
        "507934aca54bac903fd2a41501b8e2fc5ba944dd04e7ff616ebf7a330ee931c1",
    "scripts/desktop_adapter.py":
        "9176e880572955f731a97ce367d39468ceb172d34359673dd96431bfc32d08a1",
    "scripts/desktop_text_readback.py":
        "aa80f3648414f7eb37561f54c72747d325791175d761a0eb402badbf6c03ff84",
    "scripts/workflow_bridge.py":
        "26ed0feb549277b440f5390490bc70ce55d942160de6a89eda4764abbb60d20b",
    "scripts/workflow_preflight.py":
        "6340a77b63f400216460ba1aaded0556238a77d54ff3e655b9cd87985c162d58",
}
# One pre-registered shared locator may be synchronized for the merchant
# workflow only when its exact reviewed bytes are present. This is not a
# general-purpose shared dependency allowlist.
MERCHANT_SHARED_LOCATOR_PATH = (
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/wechat_desktop.py"
)
# 2026-09-29 大同授权「可修改任何门禁 优先确保今日工作完成」：
# 微信抓取管线去 TCC 化重写（AX/AppKit/Quartz + 像素级遮挡门禁）后的精确字节快照。
MERCHANT_SHARED_LOCATOR_SHA256 = (
    "4b8d95a1c998edb89976774ff041c6907034e4d3bcc4517a60e8b02122dd12b8"
)
# 同一次重写中的桌面发送层（输入框/发送按钮 AX 化）：与 locator 成对登记，
# 仍只认这一份精确审阅字节，不构成通用漂移白名单。
MERCHANT_SHARED_SENDER_PATH = (
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/desktop_sender.py"
)
MERCHANT_SHARED_SENDER_SHA256 = (
    "d75890a3aeceefcf105c047a2e5ce73894f84e110d9ceffa0f47e41a9ee1aa10"
)
# 2026-09-29 运行时不兼容修复：生产守护进程用 /usr/bin/python3 = 3.9.6，
# PEP 604 联合类型（`diagnostics: dict | None`）在 def 期即抛 TypeError，
# 使 mobile_helpers 整个模块无法导入。逐文件钉死修复后的精确字节。
MERCHANT_SHARED_COMPAT_SHA256 = {
    "scripts/mobile_helpers.py":
        "bc2606cf3ffa8cd7c65f4d2ecb1a310600b27a03b30f103e56d783601083bf61",
}
# 2026-09-30 大同逐字授权（Windows 通道联调当晚）：9-29 晚桌面管线「去 TCC 化重写」的
# 两个外部文件在 18:19/18:52 又迭代过最终字节但从未登记，dependency-drift 硬挡所有
# 桥接发送。本次再封印严格钉死当前实测字节，仅限这 2 个文件加维护器自身。
DESKTOP_REWRITE_AUTHORIZATION = "user-20260930-desktop-pipeline-rewrite-dependency-resync"
DESKTOP_REWRITE_INSTRUCTION = (
    "授权 2026-09-30 依赖维护：把 9-29 晚桌面管线重写后的 wechat_desktop.py 与 "
    "desktop_preflight.py 当前字节登记进依赖清单（仅限这 2 个文件加维护器自身），恢复统一微信发送可用。"
)
DESKTOP_REWRITE_INSTRUCTION_SHA256 = hashlib.sha256(
    DESKTOP_REWRITE_INSTRUCTION.encode("utf-8")
).hexdigest()
DESKTOP_REWRITE_LOCATOR_PATH = (
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/wechat_desktop.py"
)
DESKTOP_REWRITE_PREFLIGHT_PATH = (
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts/desktop_preflight.py"
)
DESKTOP_REWRITE_ALLOWED_AFTER = {
    DESKTOP_REWRITE_LOCATOR_PATH:
        "89c3e5c63be82bb3f4fc142aaf8a6f31b9d5f7670acfa6aab8ddb833de6e3362",
    DESKTOP_REWRITE_PREFLIGHT_PATH:
        "ffd1b8fe68ce0750a3508632fb83b95b6c0128bf871cbcf2173c9a0489564f14",
}
# 2026-09-30 群名归一化修复：微信会话列表项带 '已置顶' / 'N条新消息' 尾部修饰，
# windows_adapter 归一化缺失 → 把列表名当群名发给驱动 → 驱动按目标名比对失败
# （500「打开会话失败，当前标题='…💰 (81)'，目标='…💰已置顶'」，零发送、可安全重试）。
GROUP_TITLE_NORMALIZE_AUTHORIZATION = "user-20260930-windows-adapter-group-title-normalize-resync"
GROUP_TITLE_NORMALIZE_INSTRUCTION = (
    "授权 2026-09-30 依赖再封印：windows_adapter.py 补齐微信会话列表名尾部修饰"
    "（已置顶 / N条新消息）的归一化，修复 Windows 通道按目标群名打开会话失败。"
)
GROUP_TITLE_NORMALIZE_INSTRUCTION_SHA256 = hashlib.sha256(
    GROUP_TITLE_NORMALIZE_INSTRUCTION.encode("utf-8")
).hexdigest()
GROUP_TITLE_NORMALIZE_ALLOWED_AFTER = {
    "scripts/windows_adapter.py":
        "4b54cb8d9de9f3219be444806f06d2d10586646c7d1d8ead1eeb3c68648cc4a5",
}
# 2026-09-30 驱动搜索键修复（B1 根因定案）：Windows 驱动的**发送**路径是「搜索框 +
# SendKeys 逐字敲群名」，非 BMP 字符（emoji，如 💰 U+1F4B0）经键盘注入敲不进去 →
# 搜索词残缺 → 搜索落空 → 停在旧会话 → 驱动回 500「打开会话失败，当前标题=<别的会话>」。
# 实测同一群名：全名（含 emoji）连续 2 轮共 ≤6 次尝试全失败；剥掉 emoji 的主名一次成功
# （current_chat 回读到 '…💰发财精英荟💰 (81)'）。注意 read_messages 走的是另一条
# （会话列表匹配）路径，所以一直是好的，这也是早前把根因误判成"驱动打不开 emoji 群"的原因。
# 修法：windows_adapter 发送时改用「首个非 BMP 字符处截断」的等价搜索键——必须截断而非
# 剔除，因为驱动内部按「打开后标题 startswith 目标名」判命中，键必须保持全名前缀。
# 业务身份、去重台账、回读校验（_verify_sent/_title_compatible）仍一律用完整群名。
DRIVER_SEARCH_KEY_AUTHORIZATION = "user-20260930-windows-adapter-driver-search-key-resync"
DRIVER_SEARCH_KEY_INSTRUCTION = (
    "授权 2026-09-30 依赖再封印：windows_adapter.py 发送时改用驱动搜索框可逐字输入的"
    "等价搜索键（在首个非 BMP 字符处截断、保持完整群名前缀），修复含 emoji 群名经 "
    "Windows 通道打开会话失败。"
)
DRIVER_SEARCH_KEY_INSTRUCTION_SHA256 = hashlib.sha256(
    DRIVER_SEARCH_KEY_INSTRUCTION.encode("utf-8")
).hexdigest()
DRIVER_SEARCH_KEY_ALLOWED_AFTER = {
    "scripts/windows_adapter.py":
        "aa10412c3ce475468e5551373de1a760b422dc49a26b324d9f7177f51ee1dac0",
}
# 2026-09-30 回读锚点换行压平（D15）：驱动 read_messages 把一条消息的换行**整体删除**
# （'a\nb' -> 'ab'），而业务锚点是多行通知正文；再叠加 json.dumps 会把残留换行转义成
# 两字符 '\n'，导致任何**多行**载荷的回读校验永远不可能通过。实测现场：#9 品牌差评
# 申诉跟进第 1 条实际已送达（只读 read_messages 在该群末条读到通知全文），却被判
# windows-readback-anchor-not-trailing + reconcile-anchor-missing → 业务日无法收口。
# 修法：比较前对锚点与回读**双方**做同样的换行压平，判定强度不降（仍要求精确全文锚点
# + 锚点处于尾部），只是把换行表示差异归一化。仅动只读校验路径，不碰发送路径。
READBACK_FLATTEN_AUTHORIZATION = "user-20260930-windows-adapter-readback-anchor-flatten-resync"
READBACK_FLATTEN_INSTRUCTION = (
    "授权 2026-09-30 依赖再封印：windows_adapter.py 回读校验在比较锚点前对锚点与回读"
    "双方做同样的换行压平，修复多行载荷回读被判 unknown（发送状态未知）而业务日无法收口。"
)
READBACK_FLATTEN_INSTRUCTION_SHA256 = hashlib.sha256(
    READBACK_FLATTEN_INSTRUCTION.encode("utf-8")
).hexdigest()
READBACK_FLATTEN_ALLOWED_AFTER = {
    "scripts/windows_adapter.py":
        "b43e99838e81b2fc304dcc3e79e0d893ae8fe2b4a155cfbf7af7d4fb805f05cf",
}
# 2026-09-30 出站闸门（大同铁律）：「测试数据/测试脚本永远只能发测试群，不允许发线上
# 业务群，也不允许驱动线上业务逻辑。」事故背景：⑨ 品牌申诉跟进的**测试套件**每次运行
# 都把夹具图真发到线上群 `李老哈（品牌）💰臻肆外卖运营对接群`（夹具 `aaaa…(64a).png`
# =3570B、`bbbb…(64b).png`=4140B，与本机 render_png("正文甲"/"正文乙") 字节一致）。
# 本次改动两处，互为独立防线：
#   ① 新增 scripts/egress_policy.py —— 纯函数闸门（载荷分类 + 测试群集合 fail-closed）；
#   ② windows_adapter.py —— send_one 在**调驱动之前**过闸门，命中即 blocked 并写
#      `egress-denied.json` 留痕；并在 __init__ 加**进程级守卫**：测试进程内直接拒绝
#      构造适配器（连驱动都碰不到）。②即使某处桩再打错也发不出去。
EGRESS_POLICY_AUTHORIZATION = "user-20260930-egress-policy-guard"
EGRESS_POLICY_INSTRUCTION = (
    "测试数据/测试脚本永远只能发测试群，不允许发线上业务群，也不允许驱动线上业务逻辑。"
)
EGRESS_POLICY_INSTRUCTION_SHA256 = hashlib.sha256(
    EGRESS_POLICY_INSTRUCTION.encode("utf-8")
).hexdigest()
EGRESS_POLICY_ALLOWED_AFTER = {
    "scripts/windows_adapter.py":
        "2e531b06e48a6e654e47d030d0a4e2586f8db641d7e9f7a9e47ce48efe9452cd",
    "scripts/egress_policy.py":
        "6a75604d709a93999c1de0f542c32ab08c3eed9fc05dab9147f4774ccdeb8775",
}
# 2026-09-30 D14 收口（⑧ 差评分析产物与台账从旧根 ai_agent 迁到 _back）：
# workflow_bridge.py REGISTRY 的 negative-reviews 台账路径从 WORKSPACE（旧根）迁到
# PROJECT（zhensi_waimai_back），否则 ⑧ 传入新路径被 `workflow-ledger-mismatch` 拒发。
# 大同授权链：AskUserQuestion 明确「按第1→2→3步推进（推荐）」（第1步含收口 D14），
# 数据核对后明确「发（数据已核对）」。
BRIDGE_LEDGER_MIGRATION_AUTHORIZATION = "user-20260930-negative-reviews-bridge-ledger-path-resync"
BRIDGE_LEDGER_MIGRATION_INSTRUCTION = (
    "按第1→2→3步推进（推荐）；发（数据已核对）"
)
BRIDGE_LEDGER_MIGRATION_INSTRUCTION_SHA256 = hashlib.sha256(
    BRIDGE_LEDGER_MIGRATION_INSTRUCTION.encode("utf-8")
).hexdigest()
BRIDGE_LEDGER_MIGRATION_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "4fbe39c012e3c9a12be4abb4004a9b0140bc9c9d05ab52976c2c785845853cb0",
}
# 2026-09-30 ⑬ D14 同源收口（淘宝闪购申诉报表从旧根 ai_agent/zhensi_waimai 迁到 _back）：
# workflow_bridge.py 的 taobao-flash-appeals 报表期望路径钉死 WORKSPACE/'zhensi_waimai'/'outputs'，
# 而 ⑬ 报表实际落在 zhensi_waimai_back/outputs ⇒ 被 workflow-taobao-flash-appeals-path-mismatch 拒发。
# 大同授权链：已批准「按第1→2→3步推进（推荐）」第3步=修⑬→跑⑬；运行前数据已核对。
BRIDGE_TAOBAO_REPORT_MIGRATION_AUTHORIZATION = "user-20260930-taobao-flash-appeals-bridge-report-path-resync"
BRIDGE_TAOBAO_REPORT_MIGRATION_INSTRUCTION = (
    "按第1→2→3步推进（推荐）；发（数据已核对）"
)
BRIDGE_TAOBAO_REPORT_MIGRATION_INSTRUCTION_SHA256 = hashlib.sha256(
    BRIDGE_TAOBAO_REPORT_MIGRATION_INSTRUCTION.encode("utf-8")
).hexdigest()
BRIDGE_TAOBAO_REPORT_MIGRATION_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "b10233119b1d637671e28951ee1d374eda8488df58b17af4a14ce6dafc980d66",
}
# 2026-10-01 大同授权「授权新登记+再封印」：workflow_bridge.py REGISTRY 新增
# `meituan-customer-reply-daily` 条目（美团客户回复记录 Excel 每日 17:00 落群），
# 并配套 prepare() 严格校验（报表名/路径/台账 marker 正则）。仅 workflow_bridge.py
# 字节漂移，维护器自身（SELF_KEY）按惯例豁免 after-sha 比对。
MEITUAN_REPLY_DAILY_AUTHORIZATION = "user-20261001-meituan-customer-reply-daily-registry"
MEITUAN_REPLY_DAILY_INSTRUCTION = "授权新登记+再封印"
MEITUAN_REPLY_DAILY_INSTRUCTION_SHA256 = hashlib.sha256(
    MEITUAN_REPLY_DAILY_INSTRUCTION.encode("utf-8")
).hexdigest()
MEITUAN_REPLY_DAILY_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "6f6ce7307fb9ebd87b337c8a524e9e0cd81a161e8e4aeb679743a0faf4ef9ebc",
}
# 2026-10-03 大同授权「方案 B：开搞」（⑤ 只补缺失图改造，方案文档
# docs/2026-10-03/20261003-⑤只补缺失图改造方案-待授权.md，授权原话：
# 「你可以改造，我怕的是你会不会把它流程改坏了 你要小心」「方案 B：开搞，我倾向于提前做好准备」）：
# workflow_bridge.py 的 taobao-evidence 条目 count 由 2 改为 (1,2) 区间，
# 证据图名称校验放宽为保序子集（只补缺失图），授权话术按实际张数生成
# （两张时与旧格式逐字节一致）。仅 workflow_bridge.py 字节漂移，
# 维护器自身（SELF_KEY）按惯例豁免 after-sha 比对。
JINSHA_PARTIAL_RESEND_AUTHORIZATION = "user-20261003-jinsha-evidence-partial-resend"
JINSHA_PARTIAL_RESEND_INSTRUCTION = (
    "你可以改造，我怕的是你会不会把它流程改坏了 你要小心；方案 B：开搞，我倾向于提前做好准备"
)
JINSHA_PARTIAL_RESEND_INSTRUCTION_SHA256 = hashlib.sha256(
    JINSHA_PARTIAL_RESEND_INSTRUCTION.encode("utf-8")
).hexdigest()
JINSHA_PARTIAL_RESEND_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "52a587d030d1aeb5d362d7370716eea92fefb1166470e43626ce64d68d63ebd6",
}
# 2026-10-03 大同全权授权（自进化 W1-W6 之夜，授权原话：
# 「好的 我全授权给你，你大胆开发（趁晚上没有任务执行，从w1写到 w6 还有别的什么吗
# 全部开发完，因为你一旦有遗留 明天早上新的一轮 10任务流 就要开始了，所以你全部开发
# 测试验证完 即使有改动也是小改）+ 小心谨慎的验证测试 验收。」）：
# workflow_bridge.py REGISTRY 的「落群路由」（group/kind/count）外置为
# config/registry-routing.json 数据文件（P0-2 演进补丁）；授权串与防重台账路径
# 留在封印代码内。外置后已逐条目验证与原 REGISTRY 等价（9/9 条目）。
# 仅 workflow_bridge.py 字节漂移，维护器自身（SELF_KEY）按惯例豁免 after-sha 比对。
W6_REGISTRY_EXTERNALIZE_AUTHORIZATION = "user-20261003-selfevolve-w1-w6-full-dev-night"
W6_REGISTRY_EXTERNALIZE_INSTRUCTION = (
    "好的 我全授权给你，你大胆开发（趁晚上没有任务执行，从w1写到 w6 还有别的什么吗 "
    "全部开发完，因为你一旦有遗留 明天早上新的一轮 10任务流 就要开始了，所以你全部开发"
    "测试验证完 即使有改动也是小改）+ 小心谨慎的验证测试 验收。"
)
W6_REGISTRY_EXTERNALIZE_INSTRUCTION_SHA256 = hashlib.sha256(
    W6_REGISTRY_EXTERNALIZE_INSTRUCTION.encode("utf-8")
).hexdigest()
W6_REGISTRY_EXTERNALIZE_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "e4ae8d13e9165879d612194ae8500612a95b37b56a693651fb76e51bda5023fb",
}
# 2026-10-04 大同授权（美团回复日报 marker 轮次戳修复，授权原话：
# 「当天当次数据、不限次数、没有重复门禁」(2026-10-03) + 「15点档的那个是可以汇总发群的」
# (2026-10-04)）：step4 的 marker 已按 10-03 指令改为每轮唯一（带 -HHMMSS 轮次戳），
# 但桥的 meituan-customer-reply-daily 正则只认纯日期 marker，真实外发一律
# marker-mismatch，发送链路自 10-03 起静默断裂。放行可选轮次戳后缀；
# 日期锚定、当日报表路径与授权串校验全部不变。
# 仅 workflow_bridge.py 字节漂移，维护器自身（SELF_KEY）按惯例豁免 after-sha 比对。
MEITUAN_ROUND_MARKER_AUTHORIZATION = "user-20261004-meituan-reply-round-marker"
MEITUAN_ROUND_MARKER_INSTRUCTION = (
    "当天当次数据、不限次数、没有重复门禁；15点档的那个是可以汇总发群的"
)
MEITUAN_ROUND_MARKER_INSTRUCTION_SHA256 = hashlib.sha256(
    MEITUAN_ROUND_MARKER_INSTRUCTION.encode("utf-8")
).hexdigest()
MEITUAN_ROUND_MARKER_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "a22ccc5662d6906f88d0e3e0c0f8774772ec0505ecc24831091827d0a79710a9",
}
# 2026-10-05 受控维护：智能客服技能包迁入 skills/workflows/ 后，桥内 expected_report
# 仍锚在 SKILLS/'meituan-intelligent-customer-service'/...，与真实落盘路径差一层，
# 导致 17:00 档真实外发一律 workflow-meituan-customer-reply-path-mismatch（verified=false 未外发）。
# 依据大同 2026-10-05 指令「17:00 档的完成即可 最新数据 检查执行实操一轮」——修此锚点是完成该轮的必要条件。
# 仅校正路径锚点，不动命名/marker/授权契约；仅 workflow_bridge.py 字节漂移，SELF_KEY 按惯例豁免。
MEITUAN_REPLY_PKG_PATH_AUTHORIZATION = "user-20261005-meituan-reply-package-path-resync"
MEITUAN_REPLY_PKG_PATH_INSTRUCTION = (
    "美团商家中心智能客服 17:00 档的 完成即可 最新数据 检查执行实操一轮 就可以 "
    "（历史档 已经过期没有意义）"
)
MEITUAN_REPLY_PKG_PATH_INSTRUCTION_SHA256 = hashlib.sha256(
    MEITUAN_REPLY_PKG_PATH_INSTRUCTION.encode("utf-8")
).hexdigest()
MEITUAN_REPLY_PKG_PATH_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "9ca48fa78cc76639088fe0e72e9a7c6ea8a4f052fd257f94a82266f71ac19ab0",
}
# 2026-10-06 大同授权（负反馈列表申诉工作流上线，授权原话「现在干完（推荐）」）：
# workflow_bridge.py REGISTRY 新增 `negative-feedback-appeals` 条目——负反馈申诉汇总
# 双 Excel（美团五维 + 淘宝分类）发 FEIBING NEO AI数字员工群，授权串
# user-20261006-negative-feedback-list-appeals、独立防重台账 WORKSPACE/state/
# negative-feedback-list-appeals/wechat-attempts。仅 workflow_bridge.py 字节漂移，
# 维护器自身（SELF_KEY）按惯例豁免 after-sha 比对。
NEGATIVE_FEEDBACK_APPEALS_AUTHORIZATION = "user-20261006-negative-feedback-list-appeals-registry"
NEGATIVE_FEEDBACK_APPEALS_INSTRUCTION = "现在干完（推荐）"
NEGATIVE_FEEDBACK_APPEALS_INSTRUCTION_SHA256 = hashlib.sha256(
    NEGATIVE_FEEDBACK_APPEALS_INSTRUCTION.encode("utf-8")
).hexdigest()
NEGATIVE_FEEDBACK_APPEALS_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "7cb3aef17bb51837adc34b050cdd82a2c07a7cf5c826ba7223a02d33fadabc2b",
}
# 2026-10-09 大同授权（监理铁律升级：任何影响工作流执行的问题当场解决；封印不是完成工作的理由，
# 可修改一切逻辑）：workflow_bridge.py 新增「unknown 但传输层显式确认发出（transport.data.sent=true）
# 按已送达复用」分支，破除「已知发出却永久卡死」死结（疆麦尔实证：relay 返回 data.sent=true，仅因
# 会话不在目标群、标题校验 title-mismatch 导致读回落 unknown）。判据严格限定传输层显式确认，避免把
# "真未发出"的 unknown 误判为已发。
UNKNOWN_REUSE_AUTHORIZATION = "user-20261009-unknown-sent-reuse-bridge"
UNKNOWN_REUSE_INSTRUCTION = (
    "授权修改桥逻辑：unknown 但传输层显式确认发出的标记按已送达复用，破除永久卡死；"
    "任何影响工作流执行的问题当场解决，封印不是完成工作的理由，可修改一切逻辑。"
)
UNKNOWN_REUSE_INSTRUCTION_SHA256 = hashlib.sha256(
    UNKNOWN_REUSE_INSTRUCTION.encode("utf-8")
).hexdigest()
UNKNOWN_REUSE_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "3c2736b2b41e5c8f9926b233c20b8c692051f14df5598544c0539b8ed0455b9e",
}
# 2026-10-09 晚 大同授权（当场处置铁律延续）：workflow_bridge.py check_old() 对「从未发出」
# （state=blocked ∧ sendAttempts=0 ∧ 无 physicalSendAttempts）的标记允许重绑重生成产物
# （size/sha256 漂移），名字/顺序/类型仍须一致；attempted 后漂移仍拒绝（防换文件重发）。
# 实证：淘宝闪购流 marker 钉 09:20 旧 sha，step1 每轮重生成 xlsx，整天 legacy-marker-binding-mismatch 卡死。
LEGACY_REBIND_AUTHORIZATION = "user-20261009-legacy-rebind-never-sent"
LEGACY_REBIND_INSTRUCTION = (
    "授权修改桥 check_old：从未发出的 blocked 标记允许重绑重生成产物字节（名字/顺序/类型不变），"
    "破除产物重生成导致的 legacy-marker-binding-mismatch 全天卡死；attempted 后漂移仍拒绝。"
)
LEGACY_REBIND_INSTRUCTION_SHA256 = hashlib.sha256(
    LEGACY_REBIND_INSTRUCTION.encode("utf-8")
).hexdigest()
LEGACY_REBIND_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "7de46297c23e4697d5f536730a0b99c404faff58cca4b10ad6b7d840edef03c0",
}
# 2026-10-09 深夜 大同授权（当场处置铁律，事件层第三层同源卡点）：闪购 22:41 档实测 check_old 放行后
# 仍卡 ledger.event_lock 的 binding.json（09:20 钉死旧内容摘要）→ event-payload-conflict。修法：
# ledger.event_lock(+rebind 参数)/executor.deliver(+rebind_event)/workflow_bridge（never_sent 助手，
# deliver 传 rebind_event）——从未发出的事件允许刷新绑定，attempted 仍拒。
EVENT_REBIND_AUTHORIZATION = "user-20261009-event-rebind-never-sent"
EVENT_REBIND_INSTRUCTION = (
    "授权修改桥/执行器/账本三件：从未发出的 blocked 标记允许刷新事件层 binding（与 check_old 的 "
    "never_sent 判据同源），破除产物重生成导致的 event-payload-conflict；attempted 后仍拒绝。"
)
EVENT_REBIND_INSTRUCTION_SHA256 = hashlib.sha256(
    EVENT_REBIND_INSTRUCTION.encode("utf-8")
).hexdigest()
EVENT_REBIND_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "93febd28315922bc3a2730581410cd963f6be0ccd6018b7bc541ddbb249e1cdb",
    "scripts/executor.py":
        "23a1b7b7bc7e4b377c85ea2f03d1048c6ca36064ec6ff3ff709baa9c1ea6c36c",
    "scripts/ledger.py":
        "b42b2a1f3b4e689246779ff3558c062c76bcf223ddb66419101490fd19857fa6",
}
# 2026-10-09 深夜 大同授权（当场处置铁律，第四层同源卡点）：闪购 23:10 实测事件层放行后仍卡
# freeze_item——早前失败档（09:20 preflight 失败）留下的旧冻结字节（0400 只读）与新请求 sha 不符
# → frozen-payload-mismatch。修法：executor.freeze_item(+allow_refreeze)，仅当 prior/delivery.json
# 不存在（零发送历史）时重冻结为当前请求字节；attempted/verified 保持钉死。
REFREEZE_AUTHORIZATION = "user-20261009-refreeze-never-sent"
REFREEZE_INSTRUCTION = (
    "授权修改 executor.freeze_item：事件从未发出（delivery.json 不存在）时允许重冻结产物字节，"
    "破除早前失败档残留冻结导致的 frozen-payload-mismatch；attempted/verified 一律保持钉死。"
)
REFREEZE_INSTRUCTION_SHA256 = hashlib.sha256(
    REFREEZE_INSTRUCTION.encode("utf-8")
).hexdigest()
REFREEZE_ALLOWED_AFTER = {
    "scripts/executor.py":
        "07f508be539076abf796c11a70ae7980a28645b1704849189baa1e487e0dd720",
}
MEITUAN_BRIDGE_BACK_TREE_AUTHORIZATION = "user-20261013-meituan-bridge-back-tree"
MEITUAN_BRIDGE_BACK_TREE_INSTRUCTION = (
    "审批同意对 workflow_bridge.py 走受控再封印：把美团差评申诉桥的路径锚点从旧树 zhensi_waimai "
    "迁移到线上权威树 zhensi_waimai_back，与 deliver_batch.mjs 实际落盘路径一致；你继续推进。"
)
MEITUAN_BRIDGE_BACK_TREE_INSTRUCTION_SHA256 = hashlib.sha256(
    MEITUAN_BRIDGE_BACK_TREE_INSTRUCTION.encode("utf-8")
).hexdigest()
MEITUAN_BRIDGE_BACK_TREE_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "cd71c7dc54055f2a83d054000646d8844c04b1ff6faeb74bc6886607a0d6cc40",
}
BUSINESS_STORAGE_BRIDGE_AUTHORIZATION = "user-20261027-business-storage-bridge-gate"
BUSINESS_STORAGE_BRIDGE_INSTRUCTION = (
    "授权最小修复共享workflow bridge与负反馈维护工具：业务台账必须经business_storage resolver"
    "绑定已激活仓内目录，坏证据fail-closed，并按共享依赖维护规则准备摘要重绑；不部署、不发送。"
)
BUSINESS_STORAGE_BRIDGE_INSTRUCTION_SHA256 = hashlib.sha256(
    BUSINESS_STORAGE_BRIDGE_INSTRUCTION.encode("utf-8")
).hexdigest()
BUSINESS_STORAGE_BRIDGE_ALLOWED_AFTER = {
    "scripts/workflow_bridge.py":
        "d2f92dc26761edc1bfceff5c22b04da9d419eb87353b3fa9c7a2ceec82e65b44",
    BUSINESS_STORAGE_KEY:
        "42e1a1b0b821d2f9eed5082f0748966aad15c651bdd0cbd62fecbc462cdfcaee",
}
MAINTENANCE_AUTHORIZATIONS = {
    'user-20261025-pending-image-continue': {'instructionSha256': 'cb4e3f301ab836e49183049acc1da46992342dc41c3edc1c3514b32c0e336149', 'allowedChangePaths': {SELF_KEY, 'scripts/executor.py'}, 'allowedAfterSha256': {'scripts/executor.py': '8ac898329e252cf44b6ea96693f6c0eafa2efde9ac5fe8aff7b546a30c3a4522'}},
    'user-20261025-ui-no-wall-clock': {"instructionSha256": '6b18bd5262a9a9e0533d983c60dce4cbb755881a1333e3c630469199a891b5f5', "allowedChangePaths": {SELF_KEY, "scripts/contract.py", "scripts/executor.py"}, "allowedAfterSha256": {'scripts/contract.py': 'c37b410fb4d98ff9745dde3a95dc4098ae23e4d9913725ef5ca5e7c208cb7393', 'scripts/executor.py': '8a900b25e79aca47eb9ae077e94dc374f9c66a3358694c3fc5979399d4741461'}},
    MAINTENANCE_AUTHORIZATION: {
        "instructionSha256": USER_INSTRUCTION_SHA256,
        "allowedChangePaths": None,
    },
    MERCHANT_MAINTENANCE_AUTHORIZATION: {
        "instructionSha256": MERCHANT_MAINTENANCE_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, MERCHANT_SHARED_LOCATOR_PATH,
                               MERCHANT_SHARED_SENDER_PATH,
                               *MERCHANT_SHARED_COMPAT_SHA256},
    },
    PATH_MIGRATION_AUTHORIZATION: {
        "instructionSha256": PATH_MIGRATION_INSTRUCTION_SHA256,
        "allowedChangePaths": PATH_MIGRATION_PATHS,
    },
    WORKFLOWS_MIGRATION_AUTHORIZATION: {
        "instructionSha256": WORKFLOWS_MIGRATION_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *WORKFLOWS_MIGRATION_ALLOWED_AFTER},
        "allowedAfterSha256": WORKFLOWS_MIGRATION_ALLOWED_AFTER,
    },
    ZERO_SEND_DRAFT_AUTHORIZATION: {
        "instructionSha256": ZERO_SEND_DRAFT_INSTRUCTION_SHA256,
        "allowedChangePaths": ZERO_SEND_DRAFT_PATHS,
    },
    NEW_STORES_AUTHORIZATION: {
        "instructionSha256": NEW_STORES_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *NEW_STORES_ALLOWED_AFTER},
        "allowedAfterSha256": NEW_STORES_ALLOWED_AFTER,
    },
    DESKTOP_REWRITE_AUTHORIZATION: {
        "instructionSha256": DESKTOP_REWRITE_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, DESKTOP_REWRITE_LOCATOR_PATH,
                               DESKTOP_REWRITE_PREFLIGHT_PATH},
        "allowedAfterSha256": DESKTOP_REWRITE_ALLOWED_AFTER,
    },
    GROUP_TITLE_NORMALIZE_AUTHORIZATION: {
        "instructionSha256": GROUP_TITLE_NORMALIZE_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *GROUP_TITLE_NORMALIZE_ALLOWED_AFTER},
        "allowedAfterSha256": GROUP_TITLE_NORMALIZE_ALLOWED_AFTER,
    },
    DRIVER_SEARCH_KEY_AUTHORIZATION: {
        "instructionSha256": DRIVER_SEARCH_KEY_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *DRIVER_SEARCH_KEY_ALLOWED_AFTER},
        "allowedAfterSha256": DRIVER_SEARCH_KEY_ALLOWED_AFTER,
    },
    READBACK_FLATTEN_AUTHORIZATION: {
        "instructionSha256": READBACK_FLATTEN_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *READBACK_FLATTEN_ALLOWED_AFTER},
        "allowedAfterSha256": READBACK_FLATTEN_ALLOWED_AFTER,
    },
    EGRESS_POLICY_AUTHORIZATION: {
        "instructionSha256": EGRESS_POLICY_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, EGRESS_POLICY_KEY, *EGRESS_POLICY_ALLOWED_AFTER},
        "allowedAfterSha256": EGRESS_POLICY_ALLOWED_AFTER,
    },
    BRIDGE_LEDGER_MIGRATION_AUTHORIZATION: {
        "instructionSha256": BRIDGE_LEDGER_MIGRATION_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *BRIDGE_LEDGER_MIGRATION_ALLOWED_AFTER},
        "allowedAfterSha256": BRIDGE_LEDGER_MIGRATION_ALLOWED_AFTER,
    },
    BRIDGE_TAOBAO_REPORT_MIGRATION_AUTHORIZATION: {
        "instructionSha256": BRIDGE_TAOBAO_REPORT_MIGRATION_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *BRIDGE_TAOBAO_REPORT_MIGRATION_ALLOWED_AFTER},
        "allowedAfterSha256": BRIDGE_TAOBAO_REPORT_MIGRATION_ALLOWED_AFTER,
    },
    MEITUAN_REPLY_DAILY_AUTHORIZATION: {
        "instructionSha256": MEITUAN_REPLY_DAILY_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *MEITUAN_REPLY_DAILY_ALLOWED_AFTER},
        "allowedAfterSha256": MEITUAN_REPLY_DAILY_ALLOWED_AFTER,
    },
    JINSHA_PARTIAL_RESEND_AUTHORIZATION: {
        "instructionSha256": JINSHA_PARTIAL_RESEND_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *JINSHA_PARTIAL_RESEND_ALLOWED_AFTER},
        "allowedAfterSha256": JINSHA_PARTIAL_RESEND_ALLOWED_AFTER,
    },
    W6_REGISTRY_EXTERNALIZE_AUTHORIZATION: {
        "instructionSha256": W6_REGISTRY_EXTERNALIZE_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *W6_REGISTRY_EXTERNALIZE_ALLOWED_AFTER},
        "allowedAfterSha256": W6_REGISTRY_EXTERNALIZE_ALLOWED_AFTER,
    },
    MEITUAN_ROUND_MARKER_AUTHORIZATION: {
        "instructionSha256": MEITUAN_ROUND_MARKER_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *MEITUAN_ROUND_MARKER_ALLOWED_AFTER},
        "allowedAfterSha256": MEITUAN_ROUND_MARKER_ALLOWED_AFTER,
    },
    MEITUAN_REPLY_PKG_PATH_AUTHORIZATION: {
        "instructionSha256": MEITUAN_REPLY_PKG_PATH_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *MEITUAN_REPLY_PKG_PATH_ALLOWED_AFTER},
        "allowedAfterSha256": MEITUAN_REPLY_PKG_PATH_ALLOWED_AFTER,
    },
    NEGATIVE_FEEDBACK_APPEALS_AUTHORIZATION: {
        "instructionSha256": NEGATIVE_FEEDBACK_APPEALS_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *NEGATIVE_FEEDBACK_APPEALS_ALLOWED_AFTER},
        "allowedAfterSha256": NEGATIVE_FEEDBACK_APPEALS_ALLOWED_AFTER,
    },
    UNKNOWN_REUSE_AUTHORIZATION: {
        "instructionSha256": UNKNOWN_REUSE_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *UNKNOWN_REUSE_ALLOWED_AFTER},
        "allowedAfterSha256": UNKNOWN_REUSE_ALLOWED_AFTER,
    },
    LEGACY_REBIND_AUTHORIZATION: {
        "instructionSha256": LEGACY_REBIND_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *LEGACY_REBIND_ALLOWED_AFTER},
        "allowedAfterSha256": LEGACY_REBIND_ALLOWED_AFTER,
    },
    EVENT_REBIND_AUTHORIZATION: {
        "instructionSha256": EVENT_REBIND_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *EVENT_REBIND_ALLOWED_AFTER},
        "allowedAfterSha256": EVENT_REBIND_ALLOWED_AFTER,
    },
    REFREEZE_AUTHORIZATION: {
        "instructionSha256": REFREEZE_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *REFREEZE_ALLOWED_AFTER},
        "allowedAfterSha256": REFREEZE_ALLOWED_AFTER,
    },
    MEITUAN_BRIDGE_BACK_TREE_AUTHORIZATION: {
        "instructionSha256": MEITUAN_BRIDGE_BACK_TREE_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *MEITUAN_BRIDGE_BACK_TREE_ALLOWED_AFTER},
        "allowedAfterSha256": MEITUAN_BRIDGE_BACK_TREE_ALLOWED_AFTER,
    },
    BUSINESS_STORAGE_BRIDGE_AUTHORIZATION: {
        "instructionSha256": BUSINESS_STORAGE_BRIDGE_INSTRUCTION_SHA256,
        "allowedChangePaths": {SELF_KEY, *BUSINESS_STORAGE_BRIDGE_ALLOWED_AFTER},
        "allowedAfterSha256": BUSINESS_STORAGE_BRIDGE_ALLOWED_AFTER,
    },
}
MAX_AUTHORIZATION_AGE = timedelta(days=7)


class MaintenanceError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(name: str, root: Path = ROOT) -> Path:
    path = Path(name)
    return path if path.is_absolute() else root / path


def _read_manifest(path: Path = MANIFEST_PATH) -> tuple[bytes, dict]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise MaintenanceError(f"dependency-manifest-invalid:{error}") from error
    if value.get("schemaVersion") != 1 or not isinstance(value.get("files"), dict):
        raise MaintenanceError("dependency-manifest-schema-mismatch")
    return raw, value


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


def _candidate(manifest: dict, root: Path = ROOT, *,
               include_business_storage: bool = False) -> tuple[dict, list[dict]]:
    candidate = copy.deepcopy(manifest)
    files = candidate["files"]
    for legacy_key, current_key in WORKFLOWS_KEY_MIGRATIONS.items():
        if legacy_key in files and current_key not in files:
            files[current_key] = files.pop(legacy_key)
    files.setdefault(SELF_KEY, "0" * 64)
    # The bounded heartbeat repair state machine is executable production
    # control logic, so it must be covered by the same digest gate as the
    # total executor instead of relying on its prose documentation.
    files.setdefault(HEARTBEAT_RECOVERY_KEY, "0" * 64)
    # The adapter implements the production desktop preflight and must be
    # digest-covered before the merchant executor can accept a repair.
    files.setdefault(DESKTOP_ADAPTER_KEY, "0" * 64)
    files.setdefault(POLICY_REGISTRATION_KEY, "0" * 64)
    # The egress gate is production enforcement of the 2026-09-30 rule
    # (test payloads may only ever enter test groups / test scripts may not drive
    # production business logic), so it must be digest-covered like the executor.
    files.setdefault(EGRESS_POLICY_KEY, "0" * 64)
    if include_business_storage:
        files.setdefault(BUSINESS_STORAGE_KEY, "0" * 64)
    changes = []
    for name in sorted(files):
        expected = files[name]
        if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            raise MaintenanceError(f"dependency-entry-invalid:{name}")
        path = _resolve(name, root)
        if not path.is_file():
            raise MaintenanceError(f"dependency-file-missing:{path}")
        actual = sha256(path)
        if actual != expected:
            changes.append({"path": name, "before": expected, "after": actual})
            files[name] = actual
    return candidate, changes


def inspect(manifest_path: Path = MANIFEST_PATH, root: Path = ROOT) -> dict:
    _, manifest = _read_manifest(manifest_path)
    candidate, changes = _candidate(manifest, root)
    return {
        "ok": True,
        "action": "inspect",
        "status": "clean" if not changes else "drift",
        "changes": changes,
        "candidateFileCount": len(candidate["files"]),
        "sendAttempts": 0,
        "runtimeModelDecisions": 0,
    }


def _run(command: list[str], cwd: Path = WORKSPACE_ROOT, timeout: int = 300) -> dict:
    started = time.monotonic()
    try:
        process = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        label = Path(command[1]).name if len(command) > 1 else command[0]
        raise MaintenanceError(f"maintenance-command-timeout:{label}:{timeout}s") from exc
    output = (process.stdout or "") + (process.stderr or "")
    if process.returncode:
        raise MaintenanceError(f"maintenance-command-failed:{Path(command[1]).name if len(command) > 1 else command[0]}")
    match = re.search(r"Ran\s+(\d+)\s+tests", output)
    return {
        "ok": True,
        "elapsedMs": round((time.monotonic() - started) * 1000),
        "testCount": int(match.group(1)) if match else None,
    }


def _review(result: dict) -> dict:
    return {
        "schemaVersion": 1,
        "ok": result.get("ok") is True,
        "action": result.get("action"),
        "rows": result.get("review") or [],
        "sendAttempts": 0,
        "runtimeModelDecisions": 0,
    }


def _render(review: dict) -> str:
    lines = ["# 统一微信依赖维护复盘", "", "| 项目 | 耗时 | 结果 | 踩坑点 |", "|---|---:|---|---|"]
    for row in review["rows"]:
        elapsed = "—" if row.get("elapsedMs") is None else f"{row['elapsedMs']/1000:.3f}秒"
        pitfalls = "；".join(row.get("pitfalls") or []) or "无"
        lines.append(f"| {row['label']} | {elapsed} | {row['status']} | {pitfalls} |")
    return "\n".join(lines) + "\n"


def prepare(authorization: str, expires_at: str, output_dir: Path,
            manifest_path: Path = MANIFEST_PATH, root: Path = ROOT,
            run_command=_run) -> dict:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    result = {"ok": False, "action": "prepare", "status": "blocked", "review": [],
              "sendAttempts": 0, "runtimeModelDecisions": 0}

    def stage(label, fn):
        tick = time.monotonic()
        row = {"label": label, "status": "FAIL", "pitfalls": []}
        result["review"].append(row)
        try:
            value = fn()
            row["status"] = "PASS"
            return value
        except Exception as error:
            row["pitfalls"] = [str(error)]
            raise
        finally:
            row["elapsedMs"] = round((time.monotonic() - tick) * 1000)

    original = b""
    wrote = False
    try:
        authorization_profile = stage("维护授权", lambda: (
            MAINTENANCE_AUTHORIZATIONS.get(authorization)
            or (_ for _ in ()).throw(MaintenanceError("maintenance-authorization-mismatch"))
        ))
        expiry = stage("授权有效期", lambda: _validate_expiry(expires_at))
        original, manifest = stage("读取依赖清单", lambda: _read_manifest(manifest_path))
        candidate, changes = stage("计算候选摘要", lambda: _candidate(
            manifest, root,
            include_business_storage=authorization == BUSINESS_STORAGE_BRIDGE_AUTHORIZATION,
        ))
        def validate_change_scope():
            allowed = authorization_profile["allowedChangePaths"]
            if not changes or allowed is None:
                return True
            changed_paths = {change["path"] for change in changes}
            if not changed_paths <= allowed:
                raise MaintenanceError("maintenance-scope-disallows-dependency-changes")
            if authorization == PATH_MIGRATION_AUTHORIZATION:
                approved = authorization_profile.get("allowedAfterSha256") or {}
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("path-migration-unreviewed-dependency-bytes")
            if authorization == WORKFLOWS_MIGRATION_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("workflows-migration-unreviewed-dependency-bytes")
            if authorization == NEW_STORES_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("new-stores-unreviewed-dependency-bytes")
            if authorization == DESKTOP_REWRITE_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("desktop-rewrite-unreviewed-dependency-bytes")
            if authorization == GROUP_TITLE_NORMALIZE_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("group-title-normalize-unreviewed-dependency-bytes")
            if authorization == DRIVER_SEARCH_KEY_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("driver-search-key-unreviewed-dependency-bytes")
            if authorization == READBACK_FLATTEN_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("readback-flatten-unreviewed-dependency-bytes")
            if authorization == EGRESS_POLICY_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("egress-policy-unreviewed-dependency-bytes")
            if authorization == BRIDGE_LEDGER_MIGRATION_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("bridge-ledger-migration-unreviewed-dependency-bytes")
            if authorization == BRIDGE_TAOBAO_REPORT_MIGRATION_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("bridge-taobao-report-migration-unreviewed-dependency-bytes")
            if authorization == MEITUAN_REPLY_DAILY_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("meituan-reply-daily-unreviewed-dependency-bytes")
            if authorization == JINSHA_PARTIAL_RESEND_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("jinsha-partial-resend-unreviewed-dependency-bytes")
            if authorization == W6_REGISTRY_EXTERNALIZE_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("w6-registry-externalize-unreviewed-dependency-bytes")
            if authorization == MEITUAN_ROUND_MARKER_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("meituan-round-marker-unreviewed-dependency-bytes")
            if authorization == MEITUAN_REPLY_PKG_PATH_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("meituan-reply-package-path-unreviewed-dependency-bytes")
            if authorization == NEGATIVE_FEEDBACK_APPEALS_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("negative-feedback-appeals-unreviewed-dependency-bytes")
            if authorization == UNKNOWN_REUSE_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("unknown-reuse-unreviewed-dependency-bytes")
            if authorization == LEGACY_REBIND_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("legacy-rebind-unreviewed-dependency-bytes")
            if authorization == EVENT_REBIND_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("event-rebind-unreviewed-dependency-bytes")
            if authorization == REFREEZE_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("refreeze-unreviewed-dependency-bytes")
            if authorization == MEITUAN_BRIDGE_BACK_TREE_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("meituan-bridge-back-tree-unreviewed-dependency-bytes")
            if authorization == BUSINESS_STORAGE_BRIDGE_AUTHORIZATION:
                approved = authorization_profile["allowedAfterSha256"]
                if any(change["path"] != SELF_KEY and
                       change["after"] != approved.get(change["path"])
                       for change in changes):
                    raise MaintenanceError("business-storage-bridge-unreviewed-dependency-bytes")
            if authorization == 'user-20261025-pending-image-continue':
                approved = authorization_profile['allowedAfterSha256']
                if any(change['path'] != SELF_KEY and change['after'] != approved.get(change['path']) for change in changes):
                    raise MaintenanceError('pending-image-unreviewed-dependency-bytes')
            if authorization == 'user-20261025-ui-no-wall-clock':
                approved = authorization_profile['allowedAfterSha256']
                if any(change['path'] != SELF_KEY and change['after'] != approved.get(change['path']) for change in changes):
                    raise MaintenanceError('ui-owner-lifetime-unreviewed-dependency-bytes')
            if authorization == MERCHANT_MAINTENANCE_AUTHORIZATION:
                locator_changed = MERCHANT_SHARED_LOCATOR_PATH in changed_paths
                if locator_changed:
                    # Require the target to have been explicitly registered before
                    # this run and to match the single reviewed byte snapshot.
                    if MERCHANT_SHARED_LOCATOR_PATH not in manifest["files"]:
                        raise MaintenanceError("merchant-shared-locator-not-pre-registered")
                    change = next(item for item in changes
                                  if item["path"] == MERCHANT_SHARED_LOCATOR_PATH)
                    if change["after"] != MERCHANT_SHARED_LOCATOR_SHA256:
                        raise MaintenanceError("merchant-shared-locator-digest-not-authorized")
                # 2026-09-29 授权：与 locator 同批重写的桌面发送层，同样要求预先登记
                # 且字节精确匹配，逐文件钉死。
                if MERCHANT_SHARED_SENDER_PATH in changed_paths:
                    if MERCHANT_SHARED_SENDER_PATH not in manifest["files"]:
                        raise MaintenanceError("merchant-shared-sender-not-pre-registered")
                    sender_change = next(item for item in changes
                                         if item["path"] == MERCHANT_SHARED_SENDER_PATH)
                    if sender_change["after"] != MERCHANT_SHARED_SENDER_SHA256:
                        raise MaintenanceError("merchant-shared-sender-digest-not-authorized")
                # 运行时不兼容修复（Python 3.9 下 PEP 604）同样要求预先登记 + 字节钉死。
                for compat_path, compat_digest in MERCHANT_SHARED_COMPAT_SHA256.items():
                    if compat_path not in changed_paths:
                        continue
                    if compat_path not in manifest["files"]:
                        raise MaintenanceError("merchant-shared-compat-not-pre-registered")
                    compat_change = next(item for item in changes if item["path"] == compat_path)
                    if compat_change["after"] != compat_digest:
                        raise MaintenanceError("merchant-shared-compat-digest-not-authorized")
                if changed_paths - {SELF_KEY, MERCHANT_SHARED_LOCATOR_PATH,
                                    MERCHANT_SHARED_SENDER_PATH,
                                    *MERCHANT_SHARED_COMPAT_SHA256}:
                    raise MaintenanceError("maintenance-scope-disallows-dependency-changes")
            if authorization == ZERO_SEND_DRAFT_AUTHORIZATION and not changed_paths <= ZERO_SEND_DRAFT_PATHS:
                raise MaintenanceError("maintenance-scope-disallows-dependency-changes")
            return True

        stage("授权范围", validate_change_scope)
        tests = stage("统一微信完整离线测试", lambda: run_command([
            sys.executable, "-m", "unittest", "discover", "-s",
            str(root / "tests"), "-p", "test_*.py",
        ]))
        stage("原子写入依赖清单", lambda: _atomic_bytes(manifest_path, _json_bytes(candidate)))
        wrote = True
        verified = stage("依赖清单回读", lambda: inspect(manifest_path, root))
        if verified["status"] != "clean":
            raise MaintenanceError("dependency-manifest-postwrite-drift")
        capability = stage("统一入口完整性回读", lambda: run_command([
            sys.executable, str(root / "scripts/executor.py"), "capabilities",
        ]))
        result.update(
            ok=True,
            status="prepared",
            authorization=authorization,
            expiresAt=expiry.isoformat(),
            userInstructionSha256=authorization_profile["instructionSha256"],
            dependencyManifestPath=str(manifest_path.resolve()),
            dependencyManifestBeforeSha256=hashlib.sha256(original).hexdigest(),
            dependencyManifestAfterSha256=sha256(manifest_path),
            changes=changes,
            tests=tests,
            capabilityCheck=capability,
            candidateFileCount=len(candidate["files"]),
        )
    except Exception as error:
        result["reason"] = str(error)
        if wrote and original:
            _atomic_bytes(manifest_path, original)
            result["rollback"] = "restored"
    finally:
        result["elapsedMs"] = round((time.monotonic() - started) * 1000)
        receipt_path = output_dir / "receipt.json"
        _atomic_bytes(receipt_path, _json_bytes(result))
        review = _review(result)
        _atomic_bytes(output_dir / "review.json", _json_bytes(review))
        _atomic_bytes(output_dir / "review.md", _render(review).encode("utf-8"))
        result["receiptPath"] = str(receipt_path.resolve())
        result["receiptSha256"] = sha256(receipt_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inspect", "prepare"))
    parser.add_argument("--authorization")
    parser.add_argument("--expires-at")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            result = inspect()
        else:
            if not args.output_dir or not args.expires_at:
                raise MaintenanceError("maintenance-output-and-expiry-required")
            result = prepare(args.authorization or "", args.expires_at, Path(args.output_dir))
    except Exception as error:
        result = {"ok": False, "action": args.action, "status": "blocked", "reason": str(error),
                  "sendAttempts": 0, "runtimeModelDecisions": 0}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
