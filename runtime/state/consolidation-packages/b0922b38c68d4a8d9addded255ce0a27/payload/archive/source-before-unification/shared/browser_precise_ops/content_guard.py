#!/usr/bin/env python3
"""content_guard.py — ④ fail-closed 出站内容泄漏闸门（移植自 Easel content_guard.py）.

问题：采集器组装好要发到生产微信群的商家文案后，目前**没有任何过滤**就交给发送层。一旦
上游数据或模板误带入内部信息（密钥、内网路径、代理 IP、内部域名、env 名、.env 真值），
就会**公开发到群里且删不掉**。

本模块是出站文本的唯一真相源扫描器：发布/发送前调用 guard_or_die(text)。分两级强制：
  - BLOCK 级 = 真·内部设置泄露（密钥 / 内网域名 / 代理 IP / 内部绝对路径 / env 名 / .env 真值）
    → **fail-closed 拦发（EXIT_LEAK=7）**，让调用方改稿重发。
  - WARN 级 = AI 措辞（由 AI 生成 / OpenAI / Claude / 大模型）与模型名（claude-* / gpt-*）
    → 这些在运营文案里可能是正常内容，硬拦会误伤 → **只告警、绝不拦截**。

与 executor_integrity 互补：integrity 管「代码完整/锁未被篡改」，本模块管「发出去的内容
不泄密」，是两个维度。

纯 stdlib、可移植、带 selftest；不联网、不改文件（redact 只在显式子命令输出脱敏文本）。

子命令：
  scan   --text "..." | --file PATH     # 有 BLOCK 级命中退出 7；仅 WARN 退出 0
  redact --file PATH [--out PATH]        # 输出脱敏文本
  selftest                              # 正例必抓 / 反例必放行 / 分级正确
作为库：
  from shared.browser_precise_ops.content_guard import scan, redact, guard_or_die, EXIT_LEAK
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# 阻止发布的退出码（区别于一般错误 1；调用方据此判定「被安全闸门拦下」）
EXIT_LEAK = 7

# ── BLOCK 级：真·内部设置泄露，几乎无正当理由出现在对外内容里 ──────────────
BLOCK_PATTERNS = [
    ("api_key", re.compile(r"(?i)(sk-|api[_-]?key|secret|token|access[_-]?key|password)\s*[:=]\s*\S+")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}")),
    ("openai_key", re.compile(r"(?i)sk-(?:proj-)?[A-Za-z0-9]{20,}")),
    ("internal_path", re.compile(r"/Users/ddt/\S+|/home/\w+/\S+|C:\\[\\A-Za-z0-9 ._-]+")),
    ("env_file_value", re.compile(r"(?i)\.env\b.*(=|\b中\b).*(token|key|secret|password|sk-)")),
    ("env_var_name", re.compile(r"(?i)\b(AOS_[A-Z_]+|EASEL_[A-Z_]+|OPENAI_API_KEY|ANTHROPIC_API_KEY|HTTPS?_PROXY)\b")),
    ("proxy_ip", re.compile(r"(?i)\b(proxy|代理)\b[^\n]{0,12}?\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")),
    ("internal_domain", re.compile(r"(?i)\b((?:localhost|127\.0\.0\.1|taobao-agent-service|easel-gateway|openclaw)[.:]\S*)\b")),
]

# ── WARN 级：AI 措辞 / 模型名，可能是正常内容，只告警不拦截 ────────────────
WARN_PATTERNS = [
    ("ai_phrase", re.compile(r"(?i)(由\s?AI\s?生成|AI\s?生成|OpenAI|Claude|Anthropic|system\s?prompt|大模型|人工智能生成)")),
    ("model_name", re.compile(r"(?i)\b(claude-[a-z0-9.-]+|gpt-[a-z0-9.-]+|gpt-image-\d|deepseek-[a-z0-9.-]+)\b")),
]


def _scan_block(text: str) -> list[str]:
    hits = []
    for name, pat in BLOCK_PATTERNS:
        if pat.search(text):
            hits.append(name)
    return hits


def _scan_warn(text: str) -> list[str]:
    hits = []
    for name, pat in WARN_PATTERNS:
        if pat.search(text):
            hits.append(name)
    return hits


def scan(text: str) -> dict:
    """扫描文本，返回 {block: [...], warn: [...]}。block 非空即有泄漏应拦发。"""
    return {"block": _scan_block(text), "warn": _scan_warn(text)}


def redact(text: str) -> str:
    """把命中片段替换为 [已隐藏]（只输出脱敏文本，不动原文）。"""
    out = text
    for _name, pat in BLOCK_PATTERNS:
        out = pat.sub("[已隐藏]", out)
    return out


def guard_or_die(text: str, *, label: str = "outbound") -> dict:
    """出站前调用。BLOCK 级命中直接 SystemExit(EXIT_LEAK)；否则返回扫描结果（含 WARN）。

    返回 dict 供调用方记录；BLOCK 命中不返回而是直接退出（fail-closed）。
    """
    result = scan(text)
    if result["block"]:
        sys.stderr.write(
            f"CONTENT_GUARD BLOCK: {label} 含内部泄露 [{','.join(result['block'])}]，已拦发\n"
        )
        sys.exit(EXIT_LEAK)
    if result["warn"]:
        sys.stderr.write(
            f"CONTENT_GUARD WARN: {label} 含 AI 措辞/模型名 [{','.join(result['warn'])}]，仅告警不拦\n"
        )
    return result


def self_test() -> dict:
    # 正例：含密钥/内网路径必抓（用 in 断言，同文本可命中多个类别）
    b = _scan_block("api_key=sk-abc123def456ghi789jkl")
    assert "api_key" in b and "openai_key" in b
    assert "internal_path" in _scan_block("see /Users/ddt/work/x/secret.txt")
    assert "proxy_ip" in _scan_block("proxy 192.168.1.50")
    assert "env_var_name" in _scan_block("AOS_DATABASE_URL=xxx")
    # 反例：纯运营文案必放行（无 BLOCK）
    assert _scan_block("（商家联系人字段缺失）\n贵州水城羊肉粉\n（商家地址字段缺失）") == []
    # WARN：AI 措辞不拦
    assert _scan_warn("本文由 AI 生成，仅供参考") == ["ai_phrase"]
    # guard_or_die BLOCK 退出 7
    try:
        guard_or_die("token=abcdef1234567890abcdef")
        raise AssertionError("should-block")
    except SystemExit as e:
        assert e.code == EXIT_LEAK
    # guard_or_die 正常文案返回
    r = guard_or_die("（城市字段缺失）\n冰屿季三文鱼")
    assert r["block"] == []
    return {"ok": True, "tests": 6}


def _main() -> int:
    ap = argparse.ArgumentParser(description="出站内容泄漏闸门")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp_scan = sub.add_parser("scan")
    sp_scan.add_argument("--text", default="")
    sp_scan.add_argument("--file", default="")
    sp_redact = sub.add_parser("redact")
    sp_redact.add_argument("--file", required=True)
    sp_redact.add_argument("--out", default="")
    sub.add_parser("selftest")
    args = ap.parse_args()

    if args.cmd == "selftest":
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0 if self_test()["ok"] else 1
    if args.cmd == "scan":
        text = args.text
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8")
        res = scan(text)
        print(json.dumps(res, ensure_ascii=False))
        return EXIT_LEAK if res["block"] else 0
    if args.cmd == "redact":
        text = Path(args.file).read_text(encoding="utf-8")
        out = redact(text)
        if args.out:
            Path(args.out).write_text(out, encoding="utf-8")
        else:
            print(out)
        return 0
    return 2


if __name__ == "__main__":
    from pathlib import Path

    import json

    sys.exit(_main())
