import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent.parent / "wechat-messaging" / "scripts"))

import prepare_delivery as prepare
import delivery_executor as delivery
from contract import event_key, item_key, normalize

# 2026-09-30 事故（夹具被真实投递到线上业务群）后的**结构性隔离**。
# 事故三要素：① 夹具用真品牌名 ⇒ 模块常量 GROUP 解析到线上群；
# ② run() 的传输点是 _windows_run，而测试打桩打在了已被弃用的
# heartbeat_recovery.run 上 ⇒ 桩失效、真发；③ 无任何出站守卫。
# 下面三道锁必须同时存在，缺一即可能再次把垃圾发进线上群。
TEST_BRAND = "__TEST__"
TEST_GROUP = "__TEST__群"


def setUpModule():
    """出站硬闸门：测试进程内不允许构造任何真实的 Windows 驱动适配器。

    delivery_executor._windows_run 在函数体内 `from windows_adapter import
    WindowsAdapter`，故在此把模块属性换成抛异常的哨兵即可覆盖所有调用路径。
    """
    import windows_adapter

    def _forbidden(*_args, **_kwargs):
        raise AssertionError(
            "offline-test-violation: 测试不得构造真实 WindowsAdapter（会真发到线上群）")

    windows_adapter.WindowsAdapter = _forbidden


class DeliveryExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "brand"
        self.wechat = Path(self.tmp.name) / "wechat-messaging"
        (self.root / "outputs").mkdir(parents=True)
        (self.wechat / ".runtime" / "events").mkdir(parents=True)
        prepare.ROOT = self.root
        prepare.WECHAT = self.wechat
        delivery.ROOT = self.root
        delivery.WECHAT = self.wechat
        # 群身份隔离：ROOT/WECHAT 只隔离文件，隔离不了模块常量里的目标群。
        # 夹具若不改写成保留品牌，就会解析到线上业务群。
        prepare.SEARCH = TEST_BRAND
        prepare.GROUP = TEST_GROUP
        # 授权时钟桩：夹具授权用假纪元 now=1000 造出（expiresAt=4600），
        # 「过期视为事件关闭」守卫若读真实时间会把所有夹具判为过期。统一钉到 1500。
        epoch_patcher = patch("delivery_executor._epoch_now", lambda: 1500)
        epoch_patcher.start()
        self.addCleanup(epoch_patcher.stop)
        self.date = "2026-09-24"
        self.rows = [
            {"记录键": "a" * 64, "品牌": TEST_BRAND, "平台": "淘宝闪购", "门店": "门店甲",
             "评价时间": self.date, "评价等级": "1星", "申诉结果": "未申诉", "评价内容": "差评甲",
             "通知正文": "正文甲", "群检索结果": "已核验群", "发送状态": "未发送", "备注": ""},
            {"记录键": "b" * 64, "品牌": TEST_BRAND, "平台": "淘宝闪购", "门店": "门店乙",
             "评价时间": self.date, "评价等级": "2星", "申诉结果": "申诉中", "评价内容": "差评乙",
             "通知正文": "正文乙", "群检索结果": "已核验群", "发送状态": "未发送", "备注": ""},
        ]
        path = self.root / "outputs" / f"{self.date}差评申诉跟进.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=prepare.FIELDS)
            writer.writeheader()
            writer.writerows(self.rows)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_delivery(self, request, item, status, attempts):
        directory = self.wechat / ".runtime" / "events" / event_key(request) / item_key(request, item)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "delivery.json").write_text(json.dumps({
            "itemId": item["itemId"], "sha256": item["sha256"],
            "status": status, "sendAttempts": attempts,
        }))

    def test_verified_item_is_excluded_and_continuation_is_reused(self):
        initial = prepare.prepare_next(business_date=self.date, now=1000)
        request = normalize(json.loads(Path(initial["request"]).read_text()))
        self._write_delivery(request, request["items"][0], "verified", 1)
        continuation = prepare.prepare_next(business_date=self.date, now=1100)
        continuation_request = normalize(json.loads(Path(continuation["request"]).read_text()))
        self.assertEqual([item["itemId"] for item in continuation_request["items"]],
                         [f"appeal-{'b' * 20}"])
        self.assertNotEqual(request["context"]["eventId"], continuation_request["context"]["eventId"])
        again = prepare.prepare_next(business_date=self.date, now=1200)
        self.assertEqual(again["request"], continuation["request"])
        self.assertEqual(again["status"], "reused")

    def test_unknown_item_blocks_any_new_continuation(self):
        initial = prepare.prepare_next(business_date=self.date, now=1000)
        request = normalize(json.loads(Path(initial["request"]).read_text()))
        self._write_delivery(request, request["items"][0], "unknown", 1)
        with self.assertRaisesRegex(ValueError, "prior-attempts-require-reconcile"):
            prepare.prepare_next(business_date=self.date, now=1100)

    def test_csv_projection_updates_only_verified_and_keeps_unknown(self):
        initial = prepare.prepare_next(business_date=self.date, now=1000)
        request = normalize(json.loads(Path(initial["request"]).read_text()))
        self._write_delivery(request, request["items"][0], "verified", 1)
        self._write_delivery(request, request["items"][1], "unknown", 1)
        projection = delivery.project_csv(self.date)
        self.assertEqual(projection["counts"], {"已发送": 1, "核验未知": 1, "未发送": 0})
        self.assertEqual(projection["evidenceCounts"], {
            "machineVerified": 1, "humanConfirmedDelivered": 0,
            "needsReconcile": 1, "untouched": 0,
        })
        with (self.root / "outputs" / f"{self.date}差评申诉跟进.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["发送状态"] for row in rows], ["已发送", "核验未知"])
        self.assertEqual([row["通知正文"] for row in rows], ["正文甲", "正文乙"])

    def test_csv_projection_does_not_trust_stale_sent_mark_without_ledger(self):
        path = self.root / "outputs" / f"{self.date}差评申诉跟进.csv"
        self.rows[0]["发送状态"] = "已发送"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=prepare.FIELDS)
            writer.writeheader()
            writer.writerows(self.rows)
        delivery.project_csv(self.date)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["发送状态"] for row in rows], ["未发送", "未发送"])

    def test_csv_projection_rejects_postwrite_field_mismatch(self):
        path = self.root / "outputs" / f"{self.date}差评申诉跟进.csv"
        replace = delivery.os.replace

        def replace_then_corrupt(source, target):
            replace(source, target)
            if Path(target) == path:
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                rows[0]["通知正文"] = "被篡改正文"
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=prepare.FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)

        with patch.object(delivery.os, "replace", side_effect=replace_then_corrupt):
            with self.assertRaisesRegex(ValueError, "daily-csv-projection-readback-mismatch"):
                delivery.project_csv(self.date)

    def test_completion_summaries_are_archived_per_run(self):
        legacy = self.root / ".runtime" / f"delivery-{self.date}-workflow-summary.json"
        legacy.parent.mkdir(parents=True)
        legacy_payload = b'{"status":"legacy-summary","review":[{"stage":"old-run"}]}\n'
        legacy.write_bytes(legacy_payload)
        first = delivery._finish({"ok": True, "status": "complete", "businessDate": self.date,
                                  "review": [], "csv": {"evidenceCounts": {"machineVerified": 1}}},
                                 0, lambda: 1)
        archived = list((self.root / ".runtime" / "delivery-run-history" / self.date).glob("legacy-*.json"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), legacy_payload)
        first_archive = Path(first["summaryArchivePath"])
        first_contents = first_archive.read_text(encoding="utf-8")
        second = delivery._finish({"ok": True, "status": "complete", "businessDate": self.date,
                                   "review": [], "csv": {"evidenceCounts": {"machineVerified": 2}}},
                                  0, lambda: 2)
        self.assertNotEqual(first["summaryArchivePath"], second["summaryArchivePath"])
        self.assertEqual(first_archive.read_text(encoding="utf-8"), first_contents)
        latest = json.loads(Path(second["summaryPath"]).read_text(encoding="utf-8"))
        self.assertEqual(latest["csv"]["evidenceCounts"]["machineVerified"], 2)
        self.assertEqual(json.loads(first_contents)["csv"]["evidenceCounts"]["machineVerified"], 1)

    def test_preflight_zero_requires_explicit_batch_and_item_counts(self):
        self.assertTrue(delivery._explicit_zero({"sendAttempts": 0, "items": [{"sendAttempts": 0, "status": "blocked"}]}))
        self.assertFalse(delivery._explicit_zero({"sendAttempts": 0, "items": [{"sendAttempts": None, "status": "unknown"}]}))
        self.assertFalse(delivery._explicit_zero({"items": []}))

    def test_controller_reconciles_before_registering_continuation_policy(self):
        original_register = delivery._register_policy
        original_transport = delivery._windows_run
        policy_events = []
        actions = []

        def register(request_path, _authorization_path):
            event_id = normalize(json.loads(Path(request_path).read_text()))["context"]["eventId"]
            policy_events.append(event_id)
            return {"ok": True, "status": "prepared"}

        def recovery(action, request_path, _authorization_path):
            request = normalize(json.loads(Path(request_path).read_text()))
            actions.append((action, request["context"]["eventId"]))
            item = request["items"][0]
            status = "unknown" if action == "execute" and len(actions) == 1 else "verified"
            attempts = 1
            self._write_delivery(request, item, status, attempts)
            return {"ok": status == "verified", "status": status,
                    "sendAttempts": attempts,
                    "items": [{"itemId": item["itemId"], "status": status, "sendAttempts": attempts}],
                    "requestDigest": __import__("contract").request_digest(request)}

        # Patch the ACTUAL transport seam used by run()（_windows_run）。
        # 2026-09-30 前这里 patch 的是 heartbeat_recovery.run —— run() 早已不调用
        # 它，桩失效导致测试真发到线上业务群。改桩即为本次根治。
        delivery._register_policy = register
        delivery._windows_run = recovery
        tick = iter(range(1000))
        try:
            result = delivery.run(business_date=self.date, clock=lambda: next(tick) / 1000)
        finally:
            delivery._register_policy = original_register
            delivery._windows_run = original_transport
        self.assertTrue(result["ok"])
        self.assertEqual([action for action, _ in actions], ["execute", "reconcile", "execute"])
        self.assertEqual(policy_events[0], actions[0][1])
        self.assertEqual(policy_events[1], actions[2][1])
        self.assertNotEqual(policy_events[0], policy_events[1])
        statuses = result["csv"]["counts"]
        self.assertEqual(statuses["已发送"], 2)
        self.assertEqual(result["completionReview"]["deliveryEvidenceCounts"]["machineVerified"], 2)
        self.assertEqual(result["completionReview"]["unresolvedPitfalls"], [], json.dumps(result, ensure_ascii=False))
        self.assertEqual(len(result["completionReview"]["recoveredPitfalls"]), 1)
        execute_review = next(row for row in result["review"] if row["stage"].startswith("总执行器执行:"))
        self.assertEqual(execute_review["status"], "failed")
        self.assertTrue(execute_review["recoveredBy"].startswith("只读对账:"))
        self.assertTrue(result["completionReview"]["businessWorkComplete"])

    def test_controller_stops_after_reconcile_still_unknown_without_new_event(self):
        original_register = delivery._register_policy
        original_transport = delivery._windows_run
        actions = []

        def register(_request_path, _authorization_path):
            return {"ok": True, "status": "prepared"}

        def recovery(action, request_path, _authorization_path):
            request = normalize(json.loads(Path(request_path).read_text()))
            actions.append(action)
            item = request["items"][0]
            self._write_delivery(request, item, "unknown", 1)
            return {"ok": False, "status": "unknown", "reason": "copy-readback-unknown",
                    "sendAttempts": 1,
                    "items": [{"itemId": item["itemId"], "status": "unknown", "sendAttempts": 1}]}

        delivery._register_policy = register
        delivery._windows_run = recovery
        tick = iter(range(1000))
        try:
            result = delivery.run(business_date=self.date, clock=lambda: next(tick) / 1000)
        finally:
            delivery._register_policy = original_register
            delivery._windows_run = original_transport
        self.assertEqual(actions, ["execute", "reconcile"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["completionReview"]["recoveredPitfalls"], [])
        self.assertFalse(result["completionReview"]["businessWorkComplete"])
        self.assertEqual(result["csv"]["evidenceCounts"]["needsReconcile"], 1)

    def test_all_expired_grants_close_business_day_as_skipped(self):
        # 2026-09-30 大同授权「过期视为事件关闭」：全部事件授权过期 → 该轮
        # ok=True/status=skipped 收口（不计 FAILED），不再对账也不再重放。
        initial = prepare.prepare_next(business_date=self.date, now=1000)
        request = normalize(json.loads(Path(initial["request"]).read_text()))
        self._write_delivery(request, request["items"][0], "unknown", 1)
        # 授权窗口 9h（expiresAt=1000+32400=33400）：桩时间拨到 40000 才算全部过期。
        with patch("delivery_executor._epoch_now", lambda: 40000):
            result = delivery.run(business_date=self.date, clock=lambda: next(iter(range(10))) / 1000)
        self.assertTrue(result["ok"], json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "prior-event-authorization-expired-event-closed")
        self.assertEqual(result["closedEvents"], [request["context"]["eventId"]])
        self.assertEqual(result["sendAttempts"], 0)

    def test_fresh_grant_does_not_trigger_closure(self):
        # 授权仍在窗口内（_epoch_now=1500 < expiresAt=4600）→ 不触发关闭守卫。
        prepare.prepare_next(business_date=self.date, now=1000)
        with patch("delivery_executor._epoch_now", lambda: 1500):
            prepared = prepare.prepare_next(business_date=self.date, now=1100)
        self.assertEqual(prepared["status"], "reused")

    def test_explicit_user_audit_excludes_delivered_unknown_and_continues_untouched_item(self):
        initial = prepare.prepare_next(business_date=self.date, now=1000)
        request = normalize(json.loads(Path(initial["request"]).read_text()))
        item = request["items"][0]
        work = self.wechat / ".runtime" / "events" / event_key(request) / item_key(request, item)
        work.mkdir(parents=True, exist_ok=True)
        (work / "delivery.json").write_text(json.dumps({
            "itemId": item["itemId"], "sha256": item["sha256"], "status": "unknown",
            "sendAttempts": 0, "transport": {"sendAttempts": 1},
        }))
        (work / "transport-ledger").mkdir()
        (work / "transport-ledger" / "attempt.json").write_text(json.dumps({"sendAttempts": 1}))
        evidence = Path(self.tmp.name) / "user-confirmation.png"
        evidence.write_bytes(b"evidence bytes for offline test")

        audit = delivery._record_human_audits(
            self.date, [item["itemId"]], str(evidence))
        self.assertTrue(audit["ok"])
        row = self.rows[0]
        state, record = prepare.delivery_state(row, prepare._requests_for_day(self.date))
        self.assertEqual(state, "human-confirmed-delivered")
        self.assertTrue(record["confirmedDelivered"])

        continuation = prepare.prepare_next(business_date=self.date, now=1100)
        continuation_request = normalize(json.loads(Path(continuation["request"]).read_text()))
        self.assertEqual([entry["itemId"] for entry in continuation_request["items"]],
                         [f"appeal-{'b' * 20}"])

        projected = delivery.project_csv(self.date)
        self.assertEqual(projected["counts"], {"已发送": 0, "核验未知": 1, "未发送": 1})
        self.assertEqual(projected["evidenceCounts"], {
            "machineVerified": 0, "humanConfirmedDelivered": 1,
            "needsReconcile": 0, "untouched": 1,
        })
        with (self.root / "outputs" / f"{self.date}差评申诉跟进.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["发送状态"], "核验未知")
        self.assertIn("人工核验", rows[0]["备注"])

        reused = delivery._record_human_audits(self.date, [item["itemId"]], str(evidence))
        self.assertTrue(reused["ok"])
        self.assertEqual(reused["items"][0]["status"], "reused")

    def test_human_audit_rejects_unknown_without_transport_attempt_proof(self):
        initial = prepare.prepare_next(business_date=self.date, now=1000)
        request = normalize(json.loads(Path(initial["request"]).read_text()))
        item = request["items"][0]
        self._write_delivery(request, item, "unknown", 0)
        evidence = Path(self.tmp.name) / "user-confirmation.png"
        evidence.write_bytes(b"evidence bytes for offline test")
        result = delivery._record_human_audits(self.date, [item["itemId"]], str(evidence))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "human-audit-attempt-not-proven")


if __name__ == "__main__":
    unittest.main()
