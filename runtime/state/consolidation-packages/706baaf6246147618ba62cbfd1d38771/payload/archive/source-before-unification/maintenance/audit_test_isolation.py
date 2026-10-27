#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《测试隔离契约》全仓静态审计器。

大同铁律（2026-09-30）：
    所有任务流的测试脚本，要求**完全一致** ——
    **测试脚本不得操控线上数据逻辑，也不得操控线上群。**

本审计器把这条铁律变成**可执行、可回归、能被 CI 拦住**的检查，而不是一句口号。
它扫描仓库内**全部**测试工件（代码 + 夹具 + 数据，不只某一个技能），逐条核对 T1–T6：

    T1   不连真机        测试脚本里不得出现真机地址/端口/驱动令牌        BLOCK
    T2   不新增线上群名  线上群名/搜索键**不得新增**（存量冻结，只减不增） BLOCK(新增)
    T2b  业务数据脱敏    真实门店/品牌名给出清偿清单                      WARN
    T3   不驱动线上逻辑  不得连 CDP / launch 浏览器 / import 真实驱动客户端 BLOCK
    T3b  不构造真适配器  构造出站适配器给出清偿清单（运行时已被硬拦）       WARN
    T4   不写生产状态   不得出现指向生产 records/state/runs/artifacts 的绝对路径 BLOCK
    T5   不直调生产入口  不得在测试里真跑生产执行入口（--execute 等）      BLOCK
    T6   不关隔离开关    不得在测试里把 ZHS_TEST_MODE 置 0                 BLOCK

**负向断言不算违规**：`assertNotIn('--execute', …)`、`assertRaises(WindowsAdapter)` 这类
「证明危险动作被拒绝」的写法是契约的盟友，不是违例。

用法：
    python3 maintenance/audit_test_isolation.py                  # 报告；有 BLOCK 则退出码 1
    python3 maintenance/audit_test_isolation.py --json out.json  # 另落机器可读报告
    python3 maintenance/audit_test_isolation.py --update-baseline # 收紧/刷新 T2 存量基线（需人工复核）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path(__file__).resolve().with_name("test-isolation-policy.json")

BLOCK = "BLOCK"
WARN = "WARN"

WAIVER_RE = re.compile(r"ISOLATION-WAIVER:\s*(T[0-9]+b?)\b\s*[—\-:：]?\s*(.*)$")

TEXT_SUFFIXES = {".py", ".mjs", ".js", ".json", ".txt", ".md", ".sh", ".yaml", ".yml", ".csv"}
EXCLUDED_DIRS = {"node_modules", "__pycache__", ".git", ".pytest_cache", ".venv", "venv"}
#: 只扫描"测试工件"；maintenance/ 是审计器与策略表自己的家。
UNSCANNED_TOP_DIRS = {"maintenance", "docs"}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: str
    title: str
    guidance: str
    patterns: tuple[re.Pattern, ...] = ()
    literal_needles: tuple[str, ...] = ()
    #: 命中行若同时匹配其中之一，视为"负向断言"，判为盟友而非违例。
    negative_context: tuple[re.Pattern, ...] = ()


NEGATIVE_CONTEXT = (
    re.compile(r"assertNotIn|assertNotEqual|assertFalse|doesNotThrow"),
    re.compile(r"assert\.rejects|assert\.throws|assertRaises|with\s+self\.assertRaises"),
    re.compile(r"\bnot\s+in\b"),
)


@dataclass
class Finding:
    rule_id: str
    severity: str
    path: str
    line: int
    needle: str
    snippet: str

    def as_dict(self) -> dict:
        return {"rule": self.rule_id, "severity": self.severity, "path": self.path,
                "line": self.line, "needle": self.needle, "snippet": self.snippet}


@dataclass
class Report:
    scanned: int = 0
    waivers: dict[str, dict[str, str]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    policy_errors: list[str] = field(default_factory=list)
    stock: dict[str, int] = field(default_factory=dict)
    baseline: dict[str, int] = field(default_factory=dict)

    @property
    def blocks(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == BLOCK]

    @property
    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARN]

    @property
    def ok(self) -> bool:
        return not self.blocks and not self.policy_errors


def load_policy(path: Path = POLICY_PATH) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def verify_policy(policy: dict) -> list[str]:
    """策略表自洽性 + 与生产配置的防漂移核对。"""
    errors: list[str] = []
    if policy.get("schemaVersion") != 1:
        errors.append("policy-schema-version-mismatch")
    test_groups = set(policy.get("testGroupNames") or ())
    online_groups = set(policy.get("onlineGroupNames") or ())
    overlap = test_groups & online_groups
    if overlap:
        errors.append("policy-test-group-collides-with-online-group:" + ",".join(sorted(overlap)))
    if not test_groups:
        errors.append("policy-test-group-set-empty")
    for key in ("onlineGroupNames", "forbiddenHosts", "forbiddenTokens",
                "forbiddenAbsolutePathSegments"):
        if not policy.get(key):
            errors.append(f"policy-list-empty:{key}")
    for entry in policy.get("derivations") or ():
        source = REPO_ROOT / entry["file"]
        if not source.is_file():
            errors.append(f"derivation-source-missing:{entry['file']}")
            continue
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"derivation-source-unreadable:{entry['file']}:{error}")
            continue
        value = data.get(entry["pointer"])
        if not value:
            errors.append(f"derivation-pointer-missing:{entry['file']}#{entry['pointer']}")
        elif value not in online_groups:
            errors.append(f"policy-drift:{entry['file']}#{entry['pointer']}={value!r} "
                          f"未登记在 onlineGroupNames（生产改名后必须同步本表）")
    return errors


def build_rules(policy: dict) -> list[Rule]:
    hosts = [re.escape(h) for h in policy["forbiddenHosts"]]
    tokens = [re.escape(t) for t in policy["forbiddenTokens"]]
    online = tuple(policy["onlineGroupNames"] + policy["onlineSearchKeys"])
    paths = [re.escape(p) for p in policy["forbiddenAbsolutePathSegments"]]
    business = tuple(policy.get("businessDataTokens") or ())

    rules = [
        Rule("T1", BLOCK, "测试脚本不得连接真机",
             "真机端点/令牌只属于生产配置；测试要触达它必须打桩。",
             (re.compile("|".join(hosts + tokens), re.I),)),
        Rule("T2", BLOCK, "测试脚本不得新增线上群名",
             "线上群名只能留在生产配置；测试要真实身份请从生产配置只读引用，或改用测试群/合成群名。",
             literal_needles=online),
        Rule("T3", BLOCK, "测试脚本不得驱动线上业务逻辑",
             "不得连 CDP、不得 launch 真浏览器、不得 import 真实驱动客户端。",
             (re.compile(r"connectOverCDP\s*\("),
              re.compile(r"chromium\.launch\s*\("),
              re.compile(r"puppeteer\.launch\s*\("),
              re.compile(r"^\s*import\s+wxsend\b", re.M),
              re.compile(r"from\s+client\s+import\s+WeChat\b"),
              re.compile(r"\bclient\.WeChat\s*\(")),
             negative_context=NEGATIVE_CONTEXT),
        Rule("T3b", WARN, "测试脚本构造了真实出站适配器",
             "运行时守卫已在测试进程内拒绝构造；此处只作清偿清单。",
             (re.compile(r"\b(?:Windows|Mobile|Desktop)Adapter\s*\("),),
             negative_context=NEGATIVE_CONTEXT),
        Rule("T4", BLOCK, "测试脚本不得写生产状态目录",
             "测试产生的账本/收据/缓存必须落在临时目录。",
             (re.compile("|".join(paths)),)),
        Rule("T6", BLOCK, "测试脚本不得关闭隔离开关",
             "ZHS_TEST_MODE 只允许生产环境不设置；测试内不得置 0。",
             (re.compile(r"ZHS_TEST_MODE['\"]?\s*[,:]\s*['\"]0['\"]"),
              re.compile(r"ZHS_TEST_MODE\s*=\s*0")),
             negative_context=NEGATIVE_CONTEXT),
        Rule("T5", BLOCK, "测试脚本不得真跑生产执行入口",
             "测试只能打桩或调纯函数；不得真执行 --execute / auto_send / 真发文件。",
             (re.compile(r"['\"]--execute['\"]"),
              re.compile(r"\bauto_send\b"),
              re.compile(r"\bsend_file\s*\(|\bsend_image\s*\(")),
             negative_context=NEGATIVE_CONTEXT),
    ]
    if business:
        rules.append(Rule("T2b", WARN, "真实业务数据建议改合成数据",
                          "门店名/评价原文属于线上数据，测试应使用合成夹具。",
                          literal_needles=business))
    return rules


def discover(repo_root: Path = REPO_ROOT, exempt: set[str] | None = None) -> list[Path]:
    """发现全部测试工件。"""
    exempt = exempt or set()
    found: set[Path] = set()
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        rel = path.relative_to(repo_root)
        if rel.parts and rel.parts[0] in UNSCANNED_TOP_DIRS:
            continue
        if rel.as_posix() in exempt:
            continue  # 执行器自身的测试/策略表/守卫，不在"任务流测试脚本"范围内
        if path.suffix.lower() == ".md" and not path.name.startswith("test_"):
            continue  # 记录/说明类文档不是测试工件
        if "tests" in rel.parts or path.name.startswith("test_") or path.name.endswith("_test.py"):
            found.add(rel)
    return sorted(found)


def _scan(text: str, rules: list[Rule], rel: str, report: Report) -> None:
    lines = text.splitlines()

    def line_of(index: int) -> int:
        return text.count("\n", 0, index) + 1

    def snippet(line_no: int) -> str:
        return lines[line_no - 1].strip()[:180] if 1 <= line_no <= len(lines) else ""

    def allowed(rule: Rule, line_no: int) -> bool:
        if not rule.negative_context:
            return False
        raw = snippet(line_no)
        return any(pattern.search(raw) for pattern in rule.negative_context)

    claimed: set[tuple[int, int]] = set()
    for rule in rules:
        hits: list[tuple[int, str]] = []
        for needle in rule.literal_needles:
            start = 0
            while True:
                index = text.find(needle, start)
                if index < 0:
                    break
                start = index + 1
                hits.append((line_of(index), needle))
        for pattern in rule.patterns:
            for match in pattern.finditer(text):
                hits.append((line_of(match.start()), match.group(0)))
        for line_no, needle in sorted(hits):
            span = (line_no, len(needle))
            if span in claimed:
                continue
            claimed.add(span)
            if allowed(rule, line_no):
                continue
            report.findings.append(Finding(rule.rule_id, rule.severity, rel, line_no,
                                           needle, snippet(line_no)))


def _collect_waivers(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = WAIVER_RE.search(line)
        if match:
            found[match.group(1)] = match.group(2).strip()
    return found


def audit(repo_root: Path = REPO_ROOT, policy: dict | None = None) -> Report:
    policy = policy if policy is not None else load_policy()
    report = Report()
    report.policy_errors = verify_policy(policy)
    rules = build_rules(policy)
    registered = {(w["file"], w["rule"]): w.get("reason", "") for w in policy.get("waivers") or ()}
    report.baseline = dict(policy.get("frozenOnlineNameOccurrences") or {})
    exempt = set(policy.get("auditExemptPaths") or ())

    waived_spans: dict[str, set[str]] = {}
    for rel_path in discover(repo_root, exempt=exempt):
        rel = str(rel_path)
        try:
            text = (repo_root / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        report.scanned += 1
        declared = _collect_waivers(text)
        if declared:
            report.waivers.setdefault(rel, {}).update(declared)
            waived_spans[rel] = set(declared)
        _scan(text, rules, rel, report)

    # 双向核对：文件里的豁免声明必须登记在策略表，且必须写理由；反之亦然。
    for rel, declared in report.waivers.items():
        for rule_id, reason in declared.items():
            if (rel, rule_id) not in registered:
                report.policy_errors.append(f"waiver-unregistered:{rel}:{rule_id}")
            elif not reason:
                report.policy_errors.append(f"waiver-without-reason:{rel}:{rule_id}")
    for (rel, rule_id) in registered:
        if rule_id not in report.waivers.get(rel, {}):
            report.policy_errors.append(f"waiver-registered-but-absent:{rel}:{rule_id}")

    # 已登记豁免的规则在该文件内不再上报。
    report.findings = [f for f in report.findings
                       if f.rule_id not in waived_spans.get(f.path, set())]

    # T2 存量冻结：基线内 = 待清偿存量；超出基线 = 新增，降级为 BLOCK。
    adjusted: list[Finding] = []
    stock: dict[str, int] = {}
    for finding in report.findings:
        if finding.rule_id != "T2":
            adjusted.append(finding)
            continue
        stock[finding.path] = stock.get(finding.path, 0) + 1
    report.stock = stock
    for finding in report.findings:
        if finding.rule_id != "T2":
            continue
        if stock.get(finding.path, 0) > report.baseline.get(finding.path, 0):
            adjusted.append(Finding(finding.rule_id, BLOCK, finding.path, finding.line,
                                    finding.needle, finding.snippet))
        else:
            adjusted.append(Finding("T2", WARN, finding.path, finding.line,
                                    finding.needle, finding.snippet))
    report.findings = adjusted
    return report


def render(report: Report, quiet: bool = False) -> str:
    out: list[str] = []
    if not quiet:
        out.append("《测试隔离契约》全仓审计")
        out.append(f"  已扫描测试工件：{report.scanned}")
        out.append(f"  已登记豁免：{sum(len(v) for v in report.waivers.values())}")
        out.append("")
    if report.policy_errors:
        out.append("策略表 / 豁免核对错误：")
        out.extend(f"  - {item}" for item in report.policy_errors)
        out.append("")
    if report.stock:
        out.append("T2 线上群名存量（冻结基线 / 实计 / 净增）：")
        for path in sorted(report.stock):
            base = report.baseline.get(path, 0)
            now = report.stock[path]
            flag = "▲新增" if now > base else ("▼可下调" if now < base else "·")
            out.append(f"    {flag} {base:3d} / {now:3d}  {path}")
        out.append("")

    grouped: dict[str, dict[str, list[Finding]]] = {}
    for finding in report.findings:
        grouped.setdefault(finding.rule_id, {}).setdefault(finding.path, []).append(finding)
    for rule_id in sorted(grouped):
        severity = grouped[rule_id][sorted(grouped[rule_id])[0]][0].severity
        total = sum(len(v) for v in grouped[rule_id].values())
        out.append(f"[{severity}] {rule_id} × {total}（{len(grouped[rule_id])} 个文件）")
        if not quiet:
            for path in sorted(grouped[rule_id]):
                items = grouped[rule_id][path]
                out.append(f"    {path}  × {len(items)}")
                if severity == BLOCK:
                    for item in items[:10]:
                        out.append(f"        L{item.line}: «{item.needle}»")
                        out.append(f"            {item.snippet}")
                    if len(items) > 10:
                        out.append(f"        … 另有 {len(items) - 10} 处")
        out.append("")
    out.append(f"结论：BLOCK {len(report.blocks)} / WARN {len(report.warns)} "
               f"/ {'PASS' if report.ok else 'FAIL'}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="《测试隔离契约》全仓静态审计")
    parser.add_argument("--repo", default=str(REPO_ROOT))
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--update-baseline", action="store_true",
                        help="把当前 T2 存量写回策略表基线（须人工复核后提交）")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    policy = load_policy()
    report = audit(repo, policy)
    if args.update_baseline:
        policy["frozenOnlineNameOccurrences"] = dict(sorted(report.stock.items()))
        POLICY_PATH.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print(f"已刷新 T2 存量基线：{len(report.stock)} 个文件 / {sum(report.stock.values())} 处")
        return 0
    print(render(report, quiet=args.quiet))
    if args.json_path:
        Path(args.json_path).write_text(json.dumps({
            "ok": report.ok,
            "scanned": report.scanned,
            "policyErrors": report.policy_errors,
            "waivers": report.waivers,
            "baseline": report.baseline,
            "stock": report.stock,
            "findings": [f.as_dict() for f in report.findings],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
