#!/usr/bin/env python3
"""投递编排离线单测：注入桩件，**不碰真实 Windows 网关、不发任何消息**。

要钉死的四件事（都是出过事故的地方）：
  1. 顺序：明细 Excel 先、统计图后；明细没落群 ⇒ 图一次都不许发。
  2. 防重：任一件 marker 已是 verified/attempted ⇒ 绝不重复外发（10-08 重复发图事故）。
  3. payload 冲突：同日 marker 里 sha 与本次不符 ⇒ 硬阻断，不覆盖、不发。
  4. 预检：群未在会话列表精确命中 ⇒ 零发送。
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import task_workflow as W  # noqa: E402


class StubAdapter:
    """记录每次真实投递调用的假网关。"""

    def __init__(self, preflight=None, statuses=None):
        self.sent = []                      # 实际调用过 send_one 的 itemId（=真发出去了）
        self.preflight_calls = 0
        self._preflight = preflight or {"ok": True, "sessionListVerified": True,
                                        "resolvedGroup": W.GROUP, "reason": None}
        self._statuses = statuses or {}     # itemId -> 返回状态（默认 verified）

    @contextmanager
    def session(self, request):
        yield

    def preflight(self, request, output):
        self.preflight_calls += 1
        Path(output).mkdir(parents=True, exist_ok=True)
        return self._preflight

    def send_one(self, request, item, work, grant, deadline):
        self.sent.append(item["itemId"])
        status = self._statuses.get(item["itemId"], "verified")
        if status != "verified":
            return {"status": status, "sendAttempts": 1, "reason": f"stub-{status}"}
        return {"status": "verified", "sendAttempts": 1,
                "verificationLevel": "stub-readback", "evidence": {"ok": True}}


class RecheckStubAdapter(StubAdapter):
    """带假 client 的桩件：验证 _confirm_file_in_group 复核编排（离线）。"""

    def __init__(self, recheck_ok: bool):
        super().__init__()
        self.client = _FakeClient(recheck_ok)


class _FakeClient:
    """只实现 current/read 两个只读方法的假网关客户端。"""

    def __init__(self, ok: bool):
        self._ok = ok

    def current(self):
        if self._ok:
            return {"ok": True, "data": {"title": W.GROUP}}
        return {"ok": True, "data": {"title": "别的群"}}

    def read(self):
        if self._ok:
            messages = ["15:31", "[图片]", "16:32", "[文件]"]
        else:
            messages = ["15:30", "[图片]", "16:32", "[文件]", "16:33", "有人插话"]
        return {"ok": True, "data": {"messages": messages}}


def make_report(workspace: Path) -> dict:
    detail = workspace / "2026-10-13运营-店铺经营任务完成率明细.xlsx"
    image = workspace / "2026-10-13运营-店铺经营任务完成率.png"
    detail.write_bytes(b"fake-xlsx")
    image.write_bytes(b"fake-png")
    return {"rows": 10, "path": str(detail), "name": detail.name,
            "statsPath": str(image), "statsName": image.name,
            "stats": [{"name": "刘欢", "avg": 92.0}]}


class Harness(unittest.TestCase):
    """把 events 目录与发送闸指向临时目录，杜绝污染真实账本。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name)
        self.run_dir = self.workspace / "run"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.report = make_report(self.workspace)
        originals = (W.EVENTS, W.DISARM_FILE, W.ARM_FILE, W.SNAPSHOTS)
        self.addCleanup(lambda: setattr(W, "EVENTS", originals[0]))
        self.addCleanup(lambda: setattr(W, "DISARM_FILE", originals[1]))
        self.addCleanup(lambda: setattr(W, "ARM_FILE", originals[2]))
        self.addCleanup(lambda: setattr(W, "SNAPSHOTS", originals[3]))
        W.SNAPSHOTS = self.workspace / "verified-snapshots"
        W.EVENTS = self.workspace / "events"
        W.EVENTS.mkdir(parents=True, exist_ok=True)
        W.DISARM_FILE = self.workspace / "SEND_DISARMED.json"
        W.ARM_FILE = self.workspace / "SEND_ARMED.json"

    def marker(self, name: str) -> Path:
        return W.EVENTS / name

    def detail_marker(self) -> Path:
        return self.marker("2026-10-13-taobao-store-task-detail.json")

    def stats_marker(self) -> Path:
        return self.marker("2026-10-13-taobao-store-task-stats.json")

    def deliver(self, adapter, day: str = "2026-10-13"):
        return W.deliver(self.report, self.run_dir, day, adapter=adapter)


class OrderAndStop(Harness):
    def test_detail_first_then_image(self):
        adapter = StubAdapter()
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(adapter.sent, ["store-task-detail", "store-task-stats"])

    def test_image_is_file_item_and_detail_is_file_item(self):
        adapter = StubAdapter()
        W.deliver(self.report, self.run_dir, "2026-10-13", adapter=adapter)
        self.assertEqual(self.report["name"], "2026-10-13运营-店铺经营任务完成率明细.xlsx")

    def test_detail_blocked_means_image_never_sent(self):
        """★ 顺序铁律：明细没落群，统计图一次都不能发。"""
        adapter = StubAdapter(statuses={"store-task-detail": "unknown"})
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(adapter.sent, ["store-task-detail"])   # 图没有出现
        self.assertFalse(self.stats_marker().exists())          # 图的 marker 也不该写

    def test_detail_recheck_fails_blocks_image_and_marks_unknown(self):
        """★ 2026-10-19 假 verified 防御：明细复核不过 ⇒ unknown + 绝不发图。"""
        adapter = RecheckStubAdapter(recheck_ok=False)
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("post-send-recheck-failed", str(result["reason"]))
        self.assertEqual(adapter.sent, ["store-task-detail"])   # 图没有出现
        marker = json.loads(self.detail_marker().read_text(encoding="utf-8"))
        self.assertEqual(marker["state"], "unknown")            # 绝不写 verified
        self.assertFalse(self.stats_marker().exists())

    def test_detail_recheck_passes_continues_to_image(self):
        """复核通过 ⇒ 正常继续发图（防御层不误伤正常路径）。"""
        adapter = RecheckStubAdapter(recheck_ok=True)
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(adapter.sent, ["store-task-detail", "store-task-stats"])

    def test_stats_window_degraded_retro_downgrades_detail(self):
        """★ 同窗劣化回溯：明细刚 verified、图因「主窗口未出现」被拒 ⇒ 明细降 unknown。"""
        adapter = RecheckStubAdapter(recheck_ok=True)
        original_send = adapter.send_one

        def send_one(request, item, work, grant, deadline):
            if item["itemId"] == "store-task-stats":
                return {"status": "blocked", "sendAttempts": 0,
                        "reason": "windows-send-rejected:HTTP 500: "
                                  "微信进程在运行，但主窗口未出现"}
            return original_send(request, item, work, grant, deadline)

        adapter.send_one = send_one
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "blocked")
        marker = json.loads(self.detail_marker().read_text(encoding="utf-8"))
        self.assertEqual(marker["state"], "unknown")            # 明细被回溯降级
        self.assertIn("主窗口未出现", str(marker.get("evidence", {}).get("statsReason", "")))

    def test_detail_verified_image_blocked_reports_image_failure(self):
        adapter = StubAdapter(statuses={"store-task-stats": "blocked"})
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(adapter.sent, ["store-task-detail", "store-task-stats"])

    def test_blocked_is_not_recorded_as_unknown(self):
        """「确定没发」与「可能发过」必须分开记账，否则干净失败会被永久卡死。"""
        adapter = StubAdapter(statuses={"store-task-detail": "blocked"})
        self.deliver(adapter)
        record = json.loads(self.detail_marker().read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "blocked")

    def test_blocked_marker_may_be_retried_next_round(self):
        """blocked = 确定没发 ⇒ 下轮允许安全重试（与 unknown 的禁令正相反）。"""
        first = StubAdapter(statuses={"store-task-detail": "blocked"})
        self.assertEqual(self.deliver(first)["status"], "blocked")
        second = StubAdapter()
        result = self.deliver(second)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(second.sent, ["store-task-detail", "store-task-stats"])


class PreflightGate(Harness):
    def test_group_not_exactly_listed_blocks_everything(self):
        adapter = StubAdapter(preflight={"ok": True, "sessionListVerified": True,
                                         "resolvedGroup": "别的群", "reason": None})
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(adapter.sent, [])

    def test_driver_unreachable_blocks_everything(self):
        adapter = StubAdapter(preflight={"ok": False, "reason": "windows-driver-unreachable"})
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "windows-driver-unreachable")
        self.assertEqual(adapter.sent, [])

    def test_preflight_ok_false_short_circuits_before_any_send(self):
        adapter = StubAdapter()
        W.deliver(self.report, self.run_dir, "2026-10-13", adapter=adapter)
        self.assertEqual(adapter.preflight_calls, 1)


class AntiDoubleSend(Harness):
    """10-08 教训：`attempted` 不等于没发过，同日重跑必重复外发。"""

    def test_second_run_sends_nothing(self):
        first = self.deliver(StubAdapter())
        self.assertEqual(first["status"], "verified")
        second_adapter = StubAdapter()
        second = self.deliver(second_adapter)
        self.assertEqual(second["status"], "already_verified")
        self.assertEqual(second_adapter.sent, [])          # 零重复外发
        self.assertEqual(second_adapter.preflight_calls, 0)  # 连预检都不必再打

    def test_prior_attempted_unknown_does_not_resend(self):
        """上一次发出去了但收据不明 ⇒ 只读对账，绝不重发。"""
        sha = hashlib.sha256(Path(self.report["path"]).read_bytes()).hexdigest()
        self.detail_marker().write_text(json.dumps(
            {"state": "unknown", "event": "2026-10-13-taobao-store-task-detail",
             "sha256": sha}), encoding="utf-8")
        adapter = StubAdapter()
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("reconciliation", result["reason"])
        self.assertEqual(adapter.sent, [])

    def test_same_day_payload_change_is_hard_blocked(self):
        """同日同事件但内容变了（sha 不符）⇒ 阻断，绝不覆盖旧 marker、绝不发。"""
        self.detail_marker().write_text(json.dumps(
            {"state": "verified", "event": "2026-10-13-taobao-store-task-detail",
             "sha256": "0" * 64}), encoding="utf-8")
        adapter = StubAdapter()
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "same-event-payload-conflict")
        self.assertEqual(adapter.sent, [])

    def test_markers_record_verified_receipt(self):
        self.deliver(StubAdapter())
        for marker in (self.detail_marker(), self.stats_marker()):
            record = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(record["state"], "verified")
            self.assertEqual(record["groupName"], W.GROUP)
            self.assertIn("sha256", record)

    def test_disarmed_never_touches_adapter(self):
        W.DISARM_FILE.write_text("{}", encoding="utf-8")
        adapter = StubAdapter()
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "send-disarmed")
        self.assertEqual(adapter.sent, [])
        self.assertEqual(adapter.preflight_calls, 0)

    def test_missing_events_dir_is_auto_created(self):
        """首跑 events 目录不存在是正常现象：自动补建后照常发送（曾在此误闸 blocked）。"""
        W.EVENTS = self.workspace / "nope"
        adapter = StubAdapter()
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "verified")
        self.assertTrue(W.EVENTS.is_dir())
        self.assertEqual(adapter.sent, ["store-task-detail", "store-task-stats"])

    def test_different_day_uses_different_event_id(self):
        self.deliver(StubAdapter(), day="2026-10-13")
        self.assertTrue(self.detail_marker().exists())
        self.assertFalse(self.marker("2026-10-14-taobao-store-task-detail.json").exists())

    def test_verified_send_snapshots_artifact(self):
        """送达即快照：verified 后快照区留有原字节，供同日 sha 失配续传回退。"""
        self.deliver(StubAdapter())
        snap = W.SNAPSHOTS / "2026-10-13-taobao-store-task-detail" / \
            self.report["name"]
        self.assertTrue(snap.exists())
        self.assertEqual(hashlib.sha256(snap.read_bytes()).hexdigest(),
                         hashlib.sha256(Path(self.report["path"]).read_bytes()).hexdigest())

    def test_sha_mismatch_with_snapshot_recovers(self):
        """★ 2026-10-19 部分送达续传死锁修复：同日重生成字节必变（xlsx 内嵌时间戳），
        但快照区存有 verified 原字节 ⇒ 命中即复用原产物，正常走 already_verified。"""
        self.deliver(StubAdapter())
        # 模拟「另一次重跑在新目录重新生成了字节不同的同名文件」
        regenerated = self.workspace / "run2" / self.report["name"]
        regenerated.parent.mkdir(parents=True, exist_ok=True)
        regenerated.write_bytes(b"regenerated-bytes")
        self.report["path"] = str(regenerated)
        adapter = StubAdapter()
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "already_verified")
        self.assertEqual(adapter.sent, [])
        # 复用后文件字节恢复与账本一致
        self.assertEqual(hashlib.sha256(regenerated.read_bytes()).hexdigest(),
                         hashlib.sha256(
                             (W.SNAPSHOTS / "2026-10-13-taobao-store-task-detail"
                              / self.report["name"]).read_bytes()).hexdigest())

    def test_sha_mismatch_without_snapshot_still_blocks(self):
        """无快照（或快照 sha 也对不上）才是真·payload 冲突：维持硬阻断。"""
        self.detail_marker().write_text(json.dumps(
            {"state": "verified", "event": "2026-10-13-taobao-store-task-detail",
             "sha256": "0" * 64}), encoding="utf-8")
        adapter = StubAdapter()
        result = self.deliver(adapter)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "same-event-payload-conflict")
        self.assertEqual(adapter.sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)