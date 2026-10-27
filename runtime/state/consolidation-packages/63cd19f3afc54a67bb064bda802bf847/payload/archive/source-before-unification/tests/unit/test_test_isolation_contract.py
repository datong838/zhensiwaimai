#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""CI 门：把《测试隔离契约》的两条防线都钉成回归测试。

   1. 静态审计器对全仓的结果必须是 PASS（BLOCK=0、策略表/豁免核对无误）。
      这保证「测试脚本不得操控线上数据逻辑和线上群」这条铁律，一旦被任何新测试脚本违反，
      将在 CI 直接失败，而不是靠人肉复查。
   2. 进程级守卫必须是**真能拦住**的，而不是空转：
        - 测试进程内连外部地址必须抛错；
        - 测试进程内写生产状态目录必须抛错；
        - 本地/临时目录操作不受影响。
   3. 静态审计规则本身不是空转：对一份含违例的合成文本必须能扫出 BLOCK。
"""
import socket
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_static_audit_passes_on_repo():
    sys.path.insert(0, str(REPO_ROOT))
    from maintenance.audit_test_isolation import audit  # noqa: E402
    report = audit(REPO_ROOT)
    assert report.policy_errors == [], report.policy_errors
    assert report.ok, (
        f"测试隔离契约审计未通过：BLOCK={len(report.blocks)} "
        f"({sorted({f.rule_id for f in report.blocks})})、"
        f"策略错误={report.policy_errors}")


def test_guard_blocks_external_connectivity():
    sys.path.insert(0, str(REPO_ROOT))
    from tests.isolation_guard import TestIsolationViolation, install  # noqa: E402
    install()
    with pytest.raises(TestIsolationViolation):
        socket.getaddrinfo("192.168.110.184", 8731)


def test_guard_allows_loopback():
    sys.path.insert(0, str(REPO_ROOT))
    from tests.isolation_guard import install  # noqa: E402
    install()
    # 回环解析不应被守卫拦截（单元测试/本地服务需要）。
    result = socket.getaddrinfo("127.0.0.1", 0)
    assert result


def test_guard_blocks_production_state_write():
    sys.path.insert(0, str(REPO_ROOT))
    from tests.isolation_guard import TestIsolationViolation, install  # noqa: E402
    install()
    with pytest.raises(TestIsolationViolation):
        with open(str(REPO_ROOT / "records" / "guarded-write-probe.json"), "w") as stream:
            stream.write("{}")


def test_guard_allows_temp_write():
    sys.path.insert(0, str(REPO_ROOT))
    from tests.isolation_guard import install  # noqa: E402
    install()
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "ok.json"
        probe.write_text("{}")
        assert probe.read_text() == "{}"


def test_audit_rules_are_not_vacuous():
    """审计规则必须能扫出违例，否则门形同虚设。"""
    sys.path.insert(0, str(REPO_ROOT))
    from maintenance.audit_test_isolation import build_rules, load_policy  # noqa: E402
    policy = load_policy()
    rules = build_rules(policy)
    findings = []
    text = 'groupName = "李老哈（品牌）💰臻肆外卖运营对接群"\n' \
           'token = "XFVfZHoKwjHaWsZ7EXt2kNvWLSg4TGSvIpMQnvIkCaY"\n'
    for rule in rules:
        for needle in rule.literal_needles:
            if needle in text:
                findings.append(rule.rule_id)
        for pattern in rule.patterns:
            if pattern.search(text):
                findings.append(rule.rule_id)
    assert "T2" in findings, "线上群名规则未生效"
    assert "T1" in findings, "真机令牌规则未生效"
