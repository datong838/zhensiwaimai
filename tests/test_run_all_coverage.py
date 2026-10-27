#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_all.py 全面单元测试 + 覆盖率（≥98% 代码 + 逻辑覆盖率）。

设计：所有测试均离线、零生产副作用。通过 monkeypatch 把 STATE_DIR / 锁目录 /
熔断文件 / posts.json 指向临时目录，并对 skill_runner、auth_watch、subprocess
做 mock，避免触碰真实微信 / 浏览器 / 调度器。
"""
import os
import json
import sys
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

RUNTIME_DIR = Path(__file__).resolve().parent.parent / "runtime"
sys.path.insert(0, str(RUNTIME_DIR))
import run_all as ra  # noqa: E402
import skill_runner as sr  # noqa: E402

REPO_ROOT = ra.REPO_ROOT


def _minimal_manifest():
    return {
        "skills": [
            {"name": "s-active", "order": 1, "enabled": True, "dev_state": "active",
             "cadence_hours": 24, "earliest_hour": 8, "needs_adapter": False,
             "steps": [{"argv": ["echo", "x"]}]},
            {"name": "s-blocked", "order": 2, "enabled": True, "dev_state": "blocked",
             "cadence_hours": 24, "earliest_hour": 8, "needs_adapter": True, "steps": []},
            {"name": "s-dev", "order": 3, "enabled": True, "dev_state": "developing",
             "cadence_hours": 24, "earliest_hour": 8, "needs_adapter": False, "steps": []},
            {"name": "s-pending", "order": 4, "enabled": False, "dev_state": "pending",
             "cadence_hours": 24, "earliest_hour": 8, "needs_adapter": False, "steps": []},
        ],
        "ledger_template": [
            {"row": 1, "dev_state": "active", "skill": "s-active", "ledger_name": "活跃流程", "schedule": "每日"},
            {"row": 2, "dev_state": "blocked", "skill": "s-blocked", "ledger_name": "阻塞流程", "schedule": "每日"},
            {"row": 3, "dev_state": "developing", "skill": "s-dev", "ledger_name": "开发流程", "schedule": "每日"},
            {"row": 4, "dev_state": "pending", "skill": None, "ledger_name": "待开发流程", "schedule": "每日"},
        ],
        "ledger_output_dir": "work",
    }


class RunAllCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ra-cov-"))
        cls.state = cls.tmp / "state"
        cls.state.mkdir(parents=True, exist_ok=True)
        # 把所有派生路径都重定向到临时目录，确保测试完全封闭、不碰真实 runtime/state，
        # 也避免 coverage 因真实文件存在与否而抖动（如 765 飘移）。
        ra.REPO_ROOT = cls.tmp
        ra.STATE_DIR = cls.state
        ra.POST_GROUP_LOCK_DIR = cls.state / "locks"
        ra.FAILURE_WATCH_FILE = cls.state / "failure_watch.json"
        ra.POSTS_JSON = cls.tmp / "posts.json"
        ra.CONTROL_FILE = cls.state / "control.json"
        ra.SENT_TODAY = cls.state / "sent_today.json"
        ra.LOGIN_CHECK_MARKER = cls.state / "login_check_last.json"
        ra.DAEMON_HEARTBEAT = cls.state / "daemon.json"
        ra.LAST_CYCLE = cls.state / "last_cycle.json"
        ra.ALERTS_LOG = cls.state / "alerts.jsonl"
        cls.alert_store_paths = (
            ra.alert_store.STATE_DIR,
            ra.alert_store.ALERTS_RAW,
            ra.alert_store.ALERTS_SUMMARY,
            ra.alert_store.ALERTS_ARCHIVE,
        )
        ra.alert_store.STATE_DIR = cls.state
        ra.alert_store.ALERTS_RAW = cls.state / "alerts.jsonl"
        ra.alert_store.ALERTS_SUMMARY = cls.state / "alerts_summary.json"
        ra.alert_store.ALERTS_ARCHIVE = cls.state / "alerts_archive.jsonl"
        ra.SCREEN_GATE = cls.state / "screen_recording_gate.json"
        # 干净一份 posts.json：把 s-active 映射到 9232 互斥组；
        # 另含一个无 port 的岗（wechat-messaging），用于覆盖 resolve_mutex_group 的
        # `if "port" not in post: continue`（line 97）。
        posts = {
            "posts": {
                "jinsha-business": {
                    "port": 9232, "mutexGroup": "jinsha-9232",
                    "usedBy": ["s-active", "daily-negative-reviews"],
                    "lockPath": "runtime/state/locks/jinsha-9232.lock",
                },
                "wechat-messaging": {
                    "mutexGroup": None, "usedBy": ["__never_matches__"],
                    "lockPath": None,
                },
            }
        }
        ra.POSTS_JSON.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
        cls.good_posts = json.dumps(posts, ensure_ascii=False)
        ra._posts_cache.clear()

    def setUp(self):
        # 每个用例开始时复位临时 posts.json，避免被前序用例破坏后污染后续（含 cmd_selftest）
        ra.POSTS_JSON.write_text(self.good_posts, encoding="utf-8")
        ra._posts_cache.clear()

    @classmethod
    def tearDownClass(cls):
        (ra.alert_store.STATE_DIR,
         ra.alert_store.ALERTS_RAW,
         ra.alert_store.ALERTS_SUMMARY,
         ra.alert_store.ALERTS_ARCHIVE) = cls.alert_store_paths
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- W1 / 登记表 ----
    def test_load_posts_cache_and_parse_error(self):
        ra._posts_cache.clear()
        d = ra.load_posts()
        self.assertIn("posts", d)
        # 二次读取走缓存
        self.assertIs(ra.load_posts(), d)
        # 损坏 json → 返回 {}
        ra.POSTS_JSON.write_text("{bad json", encoding="utf-8")
        ra._posts_cache.clear()
        self.assertEqual(ra.load_posts(), {})
        # 恢复（setUp 会在下个用例自动复位；此处显式复位本用例现场）
        ra.POSTS_JSON.write_text(self.good_posts, encoding="utf-8")
        ra._posts_cache.clear()

    def test_resolve_mutex_group(self):
        self.assertEqual(ra.resolve_mutex_group("s-active"), "jinsha-9232")
        # 无 port 的岗（wechat-messaging）不参与互斥
        self.assertIsNone(ra.resolve_mutex_group("anything-not-listed"))
        # 不存在的 skill → None
        self.assertIsNone(ra.resolve_mutex_group("__no_such_skill__"))

    # ---- W2 / 工位互斥锁 ----
    def test_acquire_release_busy_stale(self):
        g = "cov-w2"
        l1 = ra.acquire_post_group_lock(g, "A")
        self.assertIsNotNone(l1)
        # 同组新鲜占用 → None（SKIPPED_BUSY）
        self.assertIsNone(ra.acquire_post_group_lock(g, "B"))
        ra.release_post_group_lock(l1)
        # 释放后再获取成功
        l2 = ra.acquire_post_group_lock(g, "C")
        self.assertIsNotNone(l2)
        ra.release_post_group_lock(l2)
        # 确认死亡的过期锁 → 原子回收
        lock = ra.POST_GROUP_LOCK_DIR / ("%s.lock" % g)
        lock.write_text(json.dumps({"group": g, "runId": "old", "pid": 999999999,
                                    "acquiredAt": "2000-01-01T00:00:00"}, ensure_ascii=False),
                        encoding="utf-8")
        l3 = ra.acquire_post_group_lock(g, "D")
        self.assertIsNotNone(l3)
        ra.release_post_group_lock(l3)

    def test_acquire_corrupt_lock_preserved(self):
        g = "cov-w2-corrupt"
        ra.POST_GROUP_LOCK_DIR.mkdir(parents=True, exist_ok=True)
        lock = ra.POST_GROUP_LOCK_DIR / ("%s.lock" % g)
        lock.write_text("not-json{{", encoding="utf-8")
        # 无法证明旧owner死亡：保留原件，不能按坏JSON抢锁。
        self.assertIsNone(ra.acquire_post_group_lock(g, "A"))
        self.assertEqual(lock.read_text(), "not-json{{")

    def test_release_variants(self):
        # 空 lease
        ra.release_post_group_lock(None)
        # runId 不匹配 → 不删
        g = "cov-w2-rel"
        l = ra.acquire_post_group_lock(g, "A")
        ra.release_post_group_lock({"path": l["path"], "runId": "OTHER"})
        self.assertTrue(ra.POST_GROUP_LOCK_DIR.exists())
        # 正常释放
        ra.release_post_group_lock(l)
        self.assertFalse((ra.POST_GROUP_LOCK_DIR / ("%s.lock" % g)).exists())

    # ---- W4 / 现场维护（2026-10-02 取代原熔断：失败绝不停排，纯观测） ----
    def test_record_outcome_lifecycle(self):
        ra.clear_failures("ALL")
        for _ in range(5):
            e = ra.record_outcome("cov-cb", sr.CAT_UNKNOWN, ra._now_iso())
        self.assertEqual(e["consecutive_failures"], 5)
        # 关键回归：连败再多也**不得**产生停排/熔断状态（"state" 字段已废除）
        for _ in range(10):
            e = ra.record_outcome("cov-cb", sr.CAT_UNKNOWN, ra._now_iso())
        self.assertEqual(e["consecutive_failures"], 15)
        self.assertNotIn("state", e)
        # SUCCESS 清零
        e7 = ra.record_outcome("cov-cb", sr.CAT_SUCCESS, ra._now_iso())
        self.assertEqual(e7["consecutive_failures"], 0)
        self.assertIsNone(e7["last_failure_at"])
        # SKIPPED_BUSY 中性
        e8 = ra.record_outcome("cov-cb2", "SKIPPED_BUSY", ra._now_iso())
        self.assertEqual(e8["consecutive_failures"], 0)
        # 缺失 entry 默认从 1 起计
        e9 = ra.record_outcome("cov-new", sr.CAT_UNKNOWN, ra._now_iso())
        self.assertEqual(e9["consecutive_failures"], 1)
        # 持久化可见
        watch = ra.load_failure_watch()
        self.assertEqual(watch["cov-cb"]["consecutive_failures"], 0)
        self.assertEqual(watch["cov-cb2"]["consecutive_failures"], 0)
        self.assertEqual(watch["cov-new"]["consecutive_failures"], 1)

    def test_clear_failures_variants(self):
        ra.record_outcome("cov-clr-a", sr.CAT_UNKNOWN, ra._now_iso())
        ra.record_outcome("cov-clr-b", sr.CAT_UNKNOWN, ra._now_iso())
        ra.clear_failures("cov-clr-a")
        self.assertNotIn("cov-clr-a", ra.load_failure_watch())
        self.assertIn("cov-clr-b", ra.load_failure_watch())
        ra.clear_failures("ALL")
        self.assertEqual(ra.load_failure_watch(), {})

    def test_failure_watch_load_corrupt(self):
        ra.FAILURE_WATCH_FILE.write_text("bad", encoding="utf-8")
        self.assertEqual(ra.load_failure_watch(), {})
        ra.clear_failures("ALL")

    # ---- 强制运行 / 熔断重置 ----
    def test_pop_forced_runs(self):
        self.assertEqual(ra.pop_forced_runs(), ([], None))
        ra.CONTROL_FILE.write_text(json.dumps({"force_run": "x", "reset_circuit": "y"}), encoding="utf-8")
        self.assertEqual(ra.pop_forced_runs(), (["x"], "y"))
        self.assertFalse(ra.CONTROL_FILE.exists())
        # 字符串形态
        ra.CONTROL_FILE.write_text(json.dumps({"force_run": "single"}), encoding="utf-8")
        self.assertEqual(ra.pop_forced_runs(), (["single"], None))

    # ---- cadence 门控（tuple API：返回 (skip, reason)，"只认当天成功"铁律） ----
    def test_cadence_gate(self):
        skill = {"name": "x", "earliest_hour": 9, "cadence_hours": 24}
        self.assertEqual(ra._cadence_gate(skill, datetime(2026, 1, 1, 8, 0)),
                         (True, "not_due"))    # 早于 earliest
        skill2 = dict(skill, earliest_hour=0, cadence_hours=0)
        self.assertEqual(ra._cadence_gate(skill2, datetime(2026, 1, 1, 12, 0)),
                         (True, "no_schedule"))  # cadence<=0（oneshot）
        # 无 last_success → 不跳过
        with mock.patch.object(sr, "get_last_success", return_value=""):
            self.assertEqual(ra._cadence_gate(skill, datetime(2026, 1, 1, 12, 0)),
                             (False, ""))
        now = datetime(2026, 1, 1, 12, 0)
        # 当天已成功且在 cadence 内 → 唯一可记"已完成"的跳过
        within = (now - timedelta(hours=2)).isoformat()
        with mock.patch.object(sr, "get_last_success", return_value=within):
            self.assertEqual(ra._cadence_gate(skill, now), (True, "done_today"))
        # 昨日（48h 前）成功 → 历史作废，必须重跑（反虚高 SUCCESS）
        old = (now - timedelta(hours=48)).isoformat()
        with mock.patch.object(sr, "get_last_success", return_value=old):
            self.assertEqual(ra._cadence_gate(skill, now), (False, ""))
        # 时段门槛：当天成功但早于排班时点（01:28 的成功不顶 9 点档）→ 必须重跑
        early_today = datetime(2026, 1, 1, 1, 28).isoformat()
        with mock.patch.object(sr, "get_last_success", return_value=early_today):
            self.assertEqual(ra._cadence_gate(skill, now), (False, ""))
        # cadence 超时（同日内不可能，构造跨 cadence 的当天后半夜场景）
        late = datetime(2026, 1, 1, 23, 0)
        stale = (late - timedelta(hours=25)).isoformat()  # 前一天 → 已被"只认当天"拦截
        with mock.patch.object(sr, "get_last_success", return_value=stale):
            self.assertEqual(ra._cadence_gate(skill, late), (False, ""))

    def test_pseudo_record(self):
        r = ra._pseudo_record({"name": "x"})
        self.assertEqual(r["category"], sr.CAT_SUCCESS)
        self.assertEqual(r["status"], "SUCCESS")

    # ---- 台账行生成（覆盖所有 dev_state 分支） ----
    def test_build_ledger_rows_all_states(self):
        data = _minimal_manifest()
        records = {
            "s-active": {"category": sr.CAT_SUCCESS, "finished_at": "2026-01-01T09:00:00"},
        }
        rows = ra.build_ledger_rows(data, records)
        self.assertEqual(len(rows), 4)
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["活跃流程"]["done"], "是")
        self.assertEqual(by_name["阻塞流程"]["done"], "阻塞")
        self.assertEqual(by_name["开发流程"]["done"], "开发中")
        self.assertEqual(by_name["待开发流程"]["done"], "待开发")

    def test_build_ledger_rows_active_needs_adapter(self):
        # 覆盖 active + needs_adapter 分支（520-522）
        data = {
            "skills": [
                {"name": "s-adapt", "order": 1, "enabled": True, "dev_state": "active",
                 "needs_adapter": True, "steps": []},
            ],
            "ledger_template": [
                {"row": 1, "dev_state": "active", "skill": "s-adapt",
                 "ledger_name": "适配流程", "schedule": "每日"},
            ],
        }
        rows = ra.build_ledger_rows(data, {})
        self.assertEqual(rows[0]["done"], "否")
        self.assertIn("Phase 2", rows[0]["note"])

    # ---- 台账写出 ----
    def test_write_ledger_csv(self):
        rows = ra.build_ledger_rows(_minimal_manifest(),
                                    {"s-active": {"category": sr.CAT_SUCCESS,
                                                  "finished_at": "2026-01-01T09:00:00"}})
        out = self.tmp / "ledger.csv"
        ok = ra.write_ledger_csv(rows, out, "2026-01-01")
        self.assertTrue(ok)
        self.assertTrue(out.exists())

    def test_write_ledger_xlsx_real(self):
        rows = ra.build_ledger_rows(_minimal_manifest(),
                                    {"s-active": {"category": sr.CAT_SUCCESS,
                                                  "finished_at": "2026-01-01T09:00:00"}})
        out = self.tmp / "ledger.xlsx"
        ok = ra.write_ledger_xlsx(rows, out, "2026-01-01")
        self.assertTrue(ok)
        self.assertTrue(out.exists())

    def test_write_ledger_xlsx_fallback_csv(self):
        # 强制 openpyxl 不可导入 → 走 csv 兜底分支；传入「active 未全绿」行 → all_green=False
        rows = [{"name": "x", "dev_state": "active", "done": "否",
                 "exec_time": "", "note": "未执行"}]
        saved = sys.modules.pop("openpyxl", None)
        sys.modules["openpyxl"] = None
        try:
            out = self.tmp / "ledger-fallback.xlsx"
            ok = ra.write_ledger_xlsx(rows, out, "2026-01-01")
            self.assertFalse(ok)
            self.assertTrue(out.with_suffix(".csv").exists())
        finally:
            if saved is not None:
                sys.modules["openpyxl"] = saved
            else:
                sys.modules.pop("openpyxl", None)

    # ---- 发送门 ----
    def test_maybe_send_ledger(self):
        path = self.tmp / "ledger.xlsx"
        path.write_text("x")
        # 未全绿 → 不发送
        ra._maybe_send_ledger(path, False, False, "2026-01-01")
        # 全绿 + 今日已发 → 跳过
        ra.SENT_TODAY.write_text(json.dumps({"2026-01-01": ra._now_iso()}), encoding="utf-8")
        ra._maybe_send_ledger(path, True, True, "2026-01-01")
        # 全绿 + 未发 + do_send → 触发发送（返回 False，dry 不真发）
        ra.SENT_TODAY.write_text("{}", encoding="utf-8")
        ra._maybe_send_ledger(path, True, True, "2026-01-01")
        # 全绿 + 未发 + 无 do_send → 仅落盘提示
        ra.SENT_TODAY.write_text("{}", encoding="utf-8")
        ra._maybe_send_ledger(path, True, False, "2026-01-01")

    def test_send_ledger_via_wechat(self):
        self.assertFalse(ra.send_ledger_via_wechat(self.tmp / "x.xlsx"))

    # ---- run_one ----
    def test_run_one_skipped_busy(self):
        data = _minimal_manifest()
        # 预先占用 s-active 所属互斥组
        ra.acquire_post_group_lock("jinsha-9232", "OTHER")
        try:
            with mock.patch.object(sr, "run_skill", side_effect=AssertionError("不应被调用")):
                rec = ra.run_one(data, "s-active", {})
            self.assertEqual(rec.get("status"), "SKIPPED_BUSY")
        finally:
            ra.release_post_group_lock({"path": str(ra.POST_GROUP_LOCK_DIR / "jinsha-9232.lock"),
                                        "runId": "OTHER"})

    def test_run_one_success_and_alert(self):
        data = _minimal_manifest()
        # s-active 不占互斥组（wechat-messaging 无 port；这里 s-active 映射到 jinsha-9232 有 port！
        # 为避免互斥，临时把 s-active 从 posts 移除）
        ra._posts_cache.clear()
        posts = json.loads(ra.POSTS_JSON.read_text(encoding="utf-8"))
        posts["posts"]["jinsha-business"]["usedBy"] = ["daily-negative-reviews"]
        ra.POSTS_JSON.write_text(json.dumps(posts), encoding="utf-8")
        ra._posts_cache.clear()

        rec_ok = {"status": "SUCCESS", "category": sr.CAT_SUCCESS, "attempts": 1,
                  "next_action": "none", "finished_at": "2026-01-01T09:00:00", "logs": [None]}
        with mock.patch.object(ra, "probe_wechat_foreground", return_value={}), \
             mock.patch.object(sr, "run_skill", return_value=rec_ok), \
             mock.patch.object(sr, "update_last_success") as m_upd:
            ra.run_one(data, "s-active", {})
            m_upd.assert_called_once()

        rec_fail = {"status": "FAIL", "category": sr.CAT_UNKNOWN, "attempts": 1,
                    "next_action": "retry", "finished_at": "", "logs": ["err"]}
        with mock.patch.object(ra, "probe_wechat_foreground", return_value={}), \
             mock.patch.object(sr, "run_skill", return_value=rec_fail), \
             mock.patch.object(ra, "append_alert") as m_alert:
            ra.run_one(data, "s-active", {})
            m_alert.assert_called()

    def test_run_one_no_steps(self):
        data = _minimal_manifest()
        data["skills"].append({"name": "lib-only", "enabled": True, "steps": None})
        with mock.patch.object(ra, "append_alert") as m_alert:
            ra.run_one(data, "lib-only", {})
            m_alert.assert_not_called()

    # ---- daemon_cycle ----
    def test_daemon_cycle_branches(self):
        data = _minimal_manifest()
        # 让 s-active 不占互斥组
        ra._posts_cache.clear()
        posts = json.loads(ra.POSTS_JSON.read_text(encoding="utf-8"))
        posts["posts"]["jinsha-business"]["usedBy"] = ["daily-negative-reviews"]
        ra.POSTS_JSON.write_text(json.dumps(posts), encoding="utf-8")
        ra._posts_cache.clear()

        rec_ok = {"status": "SUCCESS", "category": sr.CAT_SUCCESS, "attempts": 1,
                  "next_action": "none", "finished_at": "2026-01-01T09:00:00", "logs": [None]}
        with mock.patch.object(ra.aw, "run_auth_watch", return_value=[]), \
             mock.patch.object(ra, "pop_forced_runs", return_value=([], None)), \
             mock.patch.object(ra, "login_health_gate") as m_gate, \
             mock.patch.object(ra, "probe_wechat_foreground", return_value={}), \
             mock.patch.object(sr, "run_skill", return_value=rec_ok), \
             mock.patch.object(ra, "write_ledger_xlsx", return_value=True), \
             mock.patch.object(ra, "_maybe_send_ledger") as m_send, \
             mock.patch.object(ra, "write_last_cycle") as m_last:
            ra.daemon_cycle(data, {}, False, force_all=True)
            m_gate.assert_called()
            m_send.assert_called()
            m_last.assert_called()

    def test_daemon_cycle_cadence_skips(self):
        # done_today → pseudo SUCCESS 记录；无成功 → 真跑。失败绝不停排（熔断已废除）。
        data = _minimal_manifest()
        ra._posts_cache.clear()
        posts = json.loads(ra.POSTS_JSON.read_text(encoding="utf-8"))
        posts["posts"]["jinsha-business"]["usedBy"] = ["daily-negative-reviews"]
        ra.POSTS_JSON.write_text(json.dumps(posts), encoding="utf-8")
        ra._posts_cache.clear()
        # s-blocked 当天已有成功 → done_today 走 pseudo；s-active 无成功 → 真跑
        with mock.patch.object(sr, "DEFAULT_HISTORY", self.state / "run_history"), \
             mock.patch.object(sr, "get_last_success",
                              side_effect=lambda n: ra._now_iso() if n == "s-blocked" else ""), \
             mock.patch.object(ra, "_cadence_gate",
                              side_effect=lambda s, now: ((True, "done_today") if s["name"] == "s-blocked" else (False, "due"))), \
             mock.patch.object(ra, "pop_forced_runs", return_value=([], None)), \
             mock.patch.object(ra.aw, "run_auth_watch", return_value=[]), \
             mock.patch.object(ra, "login_health_gate"), \
             mock.patch.object(ra, "probe_wechat_foreground", return_value={}), \
             mock.patch.object(sr, "run_skill", return_value={"status": "SUCCESS",
                                  "category": sr.CAT_SUCCESS, "attempts": 1,
                                  "next_action": "none", "finished_at": ra._now_iso(),
                                  "logs": [None]}) as m_run, \
             mock.patch.object(ra, "write_ledger_xlsx", return_value=True), \
             mock.patch.object(ra, "_maybe_send_ledger"), \
             mock.patch.object(ra, "write_last_cycle") as m_last:
            ra.daemon_cycle(data, {}, False, force_all=False)
            # s-blocked 被门控跳过（不真跑），s-active 真跑
            self.assertEqual(m_run.call_count, 1)
            records = m_last.call_args[0][0]
            self.assertIn("s-active", records)
            self.assertIn("s-blocked", records)
            self.assertEqual(records["s-active"]["status"], "SUCCESS")
            self.assertEqual(records["s-blocked"]["status"], "SUCCESS")  # pseudo
            self.assertIn("cadence 内", records["s-blocked"].get("note", ""))

    # ---- 状态/心跳/告警 写入 ----
    def test_state_writers(self):
        ra.write_daemon_heartbeat("running", "2099-01-01T00:00:00")
        self.assertTrue(ra.DAEMON_HEARTBEAT.exists())
        ra.write_last_cycle({"x": {"status": "SUCCESS"}}, True)
        self.assertTrue(ra.LAST_CYCLE.exists())

    def test_append_alert_writes_jsonl_and_summary(self):
        # 隔离到临时目录：**绝不允许测试写生产 alerts.jsonl**。
        # 历史教训：本用例曾直写生产流，造出 skill='svc'/'k' 的假告警 16 条，
        # 被 triage 当成真故障采信 → 污染 dev_backlog 与看护判断（自污染）。
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            tdp = _P(td)
            orig = (ra.alert_store.ALERTS_SUMMARY,
                    ra.alert_store.ALERTS_ARCHIVE,
                    ra.alert_store.ALERTS_RAW,
                    ra.ALERTS_LOG)
            try:
                ra.alert_store.ALERTS_SUMMARY = tdp / "alerts_summary.json"
                ra.alert_store.ALERTS_ARCHIVE = tdp / "alerts_archive.jsonl"
                ra.alert_store.ALERTS_RAW = tdp / "alerts.jsonl"
                ra.ALERTS_LOG = tdp / "alerts.jsonl"
                ra.append_alert("t-selftest", sr.CAT_UNKNOWN, "detail", "log.txt")
                self.assertTrue(ra.ALERTS_LOG.exists())
                rows = [json.loads(x) for x in
                        ra.ALERTS_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
                self.assertTrue(any(r.get("skill") == "t-selftest" for r in rows))
            finally:
                (ra.alert_store.ALERTS_SUMMARY, ra.alert_store.ALERTS_ARCHIVE,
                 ra.alert_store.ALERTS_RAW, ra.ALERTS_LOG) = orig
        # 生产流不得出现测试痕迹
        prod = ra.ALERTS_LOG.read_text(encoding="utf-8") if ra.ALERTS_LOG.exists() else ""
        self.assertNotIn("t-selftest", prod)

    # ---- selftest（覆盖 classify / RunnerLock / prune / manifest / W2 / W4 / login gate） ----
    def test_cmd_selftest(self):
        self.assertEqual(ra.cmd_selftest(), 0)

    # ---- cmd_list / cmd_dry_run ----
    def test_cmd_list(self):
        self.assertEqual(ra.cmd_list(_minimal_manifest()), 0)

    def test_cmd_dry_run(self):
        data = _minimal_manifest()
        data["skills"][0]["steps"] = [{"argv": ["echo", "hi"]}]
        self.assertEqual(ra.cmd_dry_run(data, {}), 0)

    # ---- 微信前台探针 / 屏幕录制门禁 ----
    def test_probe_wechat_foreground_missing(self):
        # 用全新临时目录，避免被其它用例遗留的探针脚本干扰（line 381）
        fresh = Path(tempfile.mkdtemp(prefix="ra-probe-"))
        try:
            with mock.patch.object(ra, "RUNTIME_DIR", fresh):
                self.assertEqual(ra.probe_wechat_foreground("x", {}), {})
        finally:
            shutil.rmtree(fresh, ignore_errors=True)

    def test_probe_wechat_foreground_reads(self):
        # 探针把证据写到 STATE_DIR / "wechat_foreground_probe.last.jsonl"（见 run_all.py:386）。
        # 注意探针会先 unlink 该文件再"执行"探针脚本；这里让 mock 的 subprocess.run 重写它。
        out = ra.STATE_DIR / "wechat_foreground_probe.last.jsonl"
        def _fake_run(*a, **k):
            out.write_text(json.dumps({"at": "t", "diagnosis": "ok"}), encoding="utf-8")
            return mock.Mock(returncode=0)
        with mock.patch.object(ra.subprocess, "run", side_effect=_fake_run):
            res = ra.probe_wechat_foreground("x", {"python": sys.executable})
            self.assertIn("diagnosis", res)

    def test_probe_wechat_foreground_bad_output(self):
        # 探针脚本"执行"成功但输出无法解析 → 399-400（OSError/IndexError/ValueError 兜底返回 {}）
        out = ra.STATE_DIR / "wechat_foreground_probe.last.jsonl"
        def _fake_run(*a, **k):
            out.write_text("not-json-at-all", encoding="utf-8")
            return mock.Mock(returncode=0)
        with mock.patch.object(ra.subprocess, "run", side_effect=_fake_run):
            res = ra.probe_wechat_foreground("x", {"python": sys.executable})
            self.assertEqual(res, {})

    def test_escalate_screen_recording_gate(self):
        # 无证据
        ra.escalate_screen_recording_gate({})
        # captureUnavailable
        with mock.patch.object(ra, "append_alert") as m:
            ra.escalate_screen_recording_gate({"captureUnavailable": True, "diagnosis": "no-tcc"})
            self.assertTrue(m.called)
        # 像素不匹配
        with mock.patch.object(ra, "append_alert") as m:
            ra.escalate_screen_recording_gate({"diagnosis": "pixel", "pixels": {"captured": True, "verified": False}})
            self.assertTrue(m.called)
        # 正常 ok
        with mock.patch.object(ra, "append_alert") as m:
            ra.escalate_screen_recording_gate({"diagnosis": "ok", "pixels": {"captured": True, "verified": True}})
            self.assertFalse(m.called)

    # ---- 防睡 / 预热 ----
    def test_ensure_caffeinate(self):  # pragma: no cover (平台相关)
        with mock.patch.object(ra.shutil, "which", return_value="caffeinate"), \
             mock.patch.object(ra.subprocess, "Popen") as m_pop:
            ra.ensure_caffeinate()
            m_pop.assert_called_once()
        with mock.patch.object(ra.shutil, "which", return_value="caffeinate"), \
             mock.patch.object(ra.subprocess, "Popen", side_effect=FileNotFoundError):
            ra.ensure_caffeinate()  # 静默降级

    def test_preflight_warmup(self):
        with mock.patch.object(ra.shutil, "which", return_value=None):
            ra.preflight_warmup()  # adb 不存在 → 直接返回
        with mock.patch.object(ra.shutil, "which", return_value="/bin/adb"), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(ra.subprocess, "run") as m_run:
            os.environ.pop("ZENSI_ADB_SERIAL", None)
            st = mock.Mock(); st.stdout = "device\n"; m_run.return_value = st
            ra.preflight_warmup()  # 仅探测，不 connect
            st2 = mock.Mock(); st2.stdout = "offline\n"; m_run.return_value = st2
            os.environ["ZENSI_ADB_SERIAL"] = "emulator-5554"
            ra.preflight_warmup()  # 触发 connect（offline 不含 device 子串）
        # 异常路径：adb 探测抛错 → 静默降级
        with mock.patch.object(ra.shutil, "which", return_value="/bin/adb"), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(ra.subprocess, "run", side_effect=RuntimeError("boom")):
            os.environ.pop("ZENSI_ADB_SERIAL", None)
            ra.preflight_warmup()

    def test_login_health_gate(self):
        # 全程 mock subprocess，避免真实执行 login_health_check.py
        # 非巡检小时 → no-op（不写 marker）
        before = ra.LOGIN_CHECK_MARKER.exists()
        with mock.patch.object(ra.subprocess, "run") as m_run:
            ra.login_health_gate(datetime(2026, 1, 1, 9, 0))
            self.assertFalse(m_run.called)
        self.assertEqual(ra.LOGIN_CHECK_MARKER.exists(), before)
        # 巡检小时 + 首次 → 调用脚本
        with mock.patch.object(ra.subprocess, "run") as m_run:
            m_run.return_value = mock.Mock(stdout=json.dumps({"ok": True, "problems": []}),
                                           returncode=0)
            ra.login_health_gate(datetime(2026, 6, 1, 8, 0))
            self.assertTrue(m_run.called)
        # 巡检小时 + 同一 key 已处理 → 699 去重早退（不再调脚本）
        with mock.patch.object(ra.subprocess, "run") as m_run:
            ra.login_health_gate(datetime(2026, 6, 1, 8, 0))
            self.assertFalse(m_run.called)
        # 巡检小时 + 异常 → append_alert
        with mock.patch.object(ra.subprocess, "run", side_effect=RuntimeError("boom")), \
             mock.patch.object(ra, "append_alert") as m_alert:
            ra.login_health_gate(datetime(2026, 6, 2, 8, 0))
            self.assertTrue(m_alert.called)
        # 巡检小时 + 发现问题 → append_alert
        with mock.patch.object(ra.subprocess, "run") as m_run, \
             mock.patch.object(ra, "append_alert") as m_alert:
            m_run.return_value = mock.Mock(stdout=json.dumps({"ok": False, "problems": ["x"]}),
                                           returncode=0)
            ra.login_health_gate(datetime(2026, 6, 3, 8, 0))
            self.assertTrue(m_alert.called)

    # ---- main / CLI ----
    def test_main_cli(self):
        # _with_lock 用 sr.RunnerLock()（默认锁文件在真实 runtime/ 下，可能被常驻 daemon 占用）。
        # 单测里用始终可获取的假锁替代，避免误触「已有实例」分支；该分支另有专门用例覆盖。
        class _FakeLock:
            def __init__(self, *a, **k):
                pass
            def acquire(self):
                return True
            def release(self):
                pass

        with mock.patch.object(ra.sr, "RunnerLock", _FakeLock):
            # 2026-10-21 修正：--selftest 必须用**真实** append_alert（自己会往临时审计流
            # 写 suppressed 记录并在随后回读），被 mock 掉会 FileNotFoundError ⇒ 假红。
            with mock.patch.object(sys, "argv", ["prog", "--selftest"]):
                self.assertEqual(ra.main(), 0)
            for argv, expect in [
                (["prog", "--list"], 0),
                (["prog", "--dry-run"], 0),
                (["prog", "--status"], 0),
                (["prog", "--once", "s-active"], 0),
                (["prog", "--auth-watch"], 0),
                (["prog", "--cycle-once"], 0),
            ]:
                with mock.patch.object(sys, "argv", argv), \
                     mock.patch.object(ra, "daemon_cycle", return_value=0) as m_dc, \
                     mock.patch.object(ra, "cmd_once", return_value=0), \
                     mock.patch.object(ra, "append_alert"):
                    self.assertEqual(ra.main(), expect, msg=argv)
            # --daemon 走 daemon_loop（mock 掉避免常驻）→ 967-968
            with mock.patch.object(sys, "argv", ["prog", "--daemon"]), \
                 mock.patch.object(ra, "daemon_loop", return_value=0) as m_dl, \
                 mock.patch.object(ra, "append_alert"):
                self.assertEqual(ra.main(), 0)
                m_dl.assert_called_once()
            # 默认分支（legacy careloop，mock）→ 971
            with mock.patch.object(sys, "argv", ["prog"]), \
                 mock.patch.object(ra, "_legacy_careloop", return_value=0) as m_lc, \
                 mock.patch.object(ra, "append_alert"):
                self.assertEqual(ra.main(), 0)
                m_lc.assert_called_once()

    def test_with_lock_acquire_fails(self):
        # 覆盖 _with_lock 的「已有实例持有锁 → 拒绝并发」（976-980）
        class _FailLock:
            def __init__(self, *a, **k):
                pass
            def acquire(self):
                return False
            def release(self):
                pass

        with mock.patch.object(ra.sr, "RunnerLock", _FailLock), \
             mock.patch.object(sys, "argv", ["prog", "--once", "x"]), \
             mock.patch.object(ra, "cmd_once", return_value=0), \
             mock.patch.object(ra, "append_alert"):
            self.assertEqual(ra.main(), 1)

    def test_legacy_careloop(self):
        data = _minimal_manifest()
        rec_ok = {"status": "SUCCESS", "category": sr.CAT_SUCCESS, "attempts": 1,
                  "next_action": "none", "finished_at": "2026-01-01T09:00:00", "logs": [None]}
        with mock.patch.object(ra, "probe_wechat_foreground", return_value={}), \
             mock.patch.object(sr, "run_skill", return_value=rec_ok), \
             mock.patch.object(ra, "write_ledger_xlsx", return_value=True), \
             mock.patch.object(ra, "_maybe_send_ledger"), \
             mock.patch.object(ra, "write_last_cycle"):
            ra._legacy_careloop(data, {}, False)

    # ---- 边界 / 防御性分支 ----
    def test_cmd_once(self):
        data = _minimal_manifest()
        rec = {"status": "SUCCESS", "category": sr.CAT_SUCCESS, "attempts": 1,
               "next_action": "none", "finished_at": "t", "logs": [None]}
        with mock.patch.object(ra, "run_one", return_value=rec):
            self.assertEqual(ra.cmd_once(data, "s-active", {}), 0)

    def test_run_one_missing_skill(self):
        with self.assertRaises(SystemExit):
            ra.run_one(_minimal_manifest(), "does-not-exist", {})

    def test_release_no_path(self):
        # 无 path 的 lease → 150 提前 return
        ra.release_post_group_lock({"runId": "x"})

    def test_cadence_gate_bad_last_success(self):
        skill = {"name": "x", "earliest_hour": 0, "cadence_hours": 24}
        with mock.patch.object(sr, "get_last_success", return_value="not-a-date"):
            self.assertEqual(ra._cadence_gate(skill, datetime(2026, 1, 1, 12, 0)),
                             (False, ""))

    def test_pop_forced_runs_corrupt(self):
        ra.CONTROL_FILE.write_text("bad json{{{", encoding="utf-8")
        self.assertEqual(ra.pop_forced_runs(), ([], None))

    def test_release_corrupt_lock(self):
        lock = ra.POST_GROUP_LOCK_DIR / "corrupt.lock"
        lock.write_text("not-json", encoding="utf-8")
        # 读取损坏 → except → 776-777
        self.assertFalse(ra.release_post_group_lock({"path": str(lock), "runId": "x"}))

    def test_maybe_send_ledger_corrupt_sent_today(self):
        path = self.tmp / "ledger.xlsx"
        path.write_text("x")
        ra.SENT_TODAY.write_text("bad json{{", encoding="utf-8")
        with mock.patch.object(ra, "send_ledger_via_wechat", return_value=False):
            ra._maybe_send_ledger(path, True, True, "2026-01-01")  # 867-868

    def test_probe_foreground_subprocess_failure(self):
        with mock.patch.object(ra, "RUNTIME_DIR", self.tmp), \
             mock.patch.object(ra.subprocess, "run", side_effect=RuntimeError("boom")):
            (self.tmp / "wechat_foreground_probe.py").write_text("pass")
            self.assertEqual(ra.probe_wechat_foreground("x", {}), {})  # 394-396

    def test_login_health_gate_corrupt_marker(self):
        ra.LOGIN_CHECK_MARKER.write_text("bad json{{{", encoding="utf-8")
        with mock.patch.object(ra.subprocess, "run") as m_run:
            m_run.return_value = mock.Mock(
                stdout=json.dumps({"ok": True, "problems": []}), returncode=0)
            ra.login_health_gate(datetime(2026, 7, 1, 8, 0))  # 426-427

    def test_cmd_selftest_manifest_load_failure(self):
        with mock.patch.object(sr, "load_manifest", side_effect=RuntimeError("boom")):
            self.assertEqual(ra.cmd_selftest(), 1)  # 299-301

    def test_cmd_dry_run_no_enabled(self):
        data = {"skills": [{"name": "x", "order": 1, "enabled": False, "steps": []}],
                "ledger_template": []}
        self.assertEqual(ra.cmd_dry_run(data, {}), 0)  # 252

    def test_daemon_cycle_auth_watch_alert(self):
        data = _minimal_manifest()
        # s-active 无 steps 之外的 enabled；用空 enabled 简化，仅验证 auth_watch 循环
        data["skills"] = [s for s in data["skills"] if s["name"] != "s-active"]
        rec_ok = {"status": "SUCCESS", "category": sr.CAT_SUCCESS, "attempts": 1,
                  "next_action": "none", "finished_at": "2026-01-01T09:00:00", "logs": [None]}
        with mock.patch.object(ra.aw, "run_auth_watch",
                              return_value=[{"key": "k", "status": "NEEDS_HUMAN", "detail": "d"}]), \
             mock.patch.object(ra, "pop_forced_runs", return_value=([], None)), \
             mock.patch.object(ra, "login_health_gate"), \
             mock.patch.object(ra, "write_ledger_xlsx", return_value=True), \
             mock.patch.object(ra, "_maybe_send_ledger"), \
             mock.patch.object(ra, "write_last_cycle"):
            ra.daemon_cycle(data, {}, False, force_all=True)  # 818

    def test_main_auth_watch_loop(self):
        with mock.patch.object(sys, "argv", ["prog", "--auth-watch"]), \
             mock.patch.object(ra.aw, "run_auth_watch",
                              return_value=[{"key": "k", "status": "NEEDS_HUMAN", "detail": "d"}]), \
             mock.patch.object(ra, "append_alert") as m_alert:
            self.assertEqual(ra.main(), 0)
            self.assertTrue(m_alert.called)  # 946-948

    def test_main_status_heartbeat(self):
        # 1) 心跳文件存在且可读 → 956-957
        ra.DAEMON_HEARTBEAT.write_text('{"state":"running"}', encoding="utf-8")
        with mock.patch.object(sys, "argv", ["prog", "--status"]), \
             mock.patch.object(sr, "summarize_today", return_value={}), \
             mock.patch.object(ra, "append_alert"):
            self.assertEqual(ra.main(), 0)
        # 2) 心跳文件存在但读取抛 OSError → 958-959（用假对象替换，避免 patch 只读实例方法）
        fake = mock.MagicMock()
        fake.exists.return_value = True
        fake.read_text.side_effect = OSError("boom")
        with mock.patch.object(sys, "argv", ["prog", "--status"]), \
             mock.patch.object(sr, "summarize_today", return_value={}), \
             mock.patch.object(ra, "append_alert"), \
             mock.patch.object(ra, "DAEMON_HEARTBEAT", fake):
            self.assertEqual(ra.main(), 0)
        # 3) 心跳文件缺失 → 961
        ra.DAEMON_HEARTBEAT.unlink(missing_ok=True)
        with mock.patch.object(sys, "argv", ["prog", "--status"]), \
             mock.patch.object(sr, "summarize_today", return_value={}), \
             mock.patch.object(ra, "append_alert"):
            self.assertEqual(ra.main(), 0)

    # ---- 补充覆盖：剩余分支 ----
    def test_failure_watch_missing(self):
        # 失败看门文件不存在 → 空 dict
        ra.FAILURE_WATCH_FILE.unlink(missing_ok=True)
        self.assertEqual(ra.load_failure_watch(), {})

    def test_acquire_lock_recreate_race(self):
        # 独占发布发现其它文件已占用：保留原忙语义。
        import post_group_lease
        with mock.patch.object(post_group_lease, "publish_exclusive", return_value=False):
            self.assertIsNone(ra.acquire_post_group_lock("cov-w2-race", "A"))

    def test_acquire_corrupt_lock_unlink_fail(self):
        # 损坏锁解析失败(125-126) → unlink 抛 OSError(129-130) → 文件残留→重建仍冲突→返回 None(SKIPPED_BUSY)
        g = "cov-w2-unlink-fail"
        ra.POST_GROUP_LOCK_DIR.mkdir(parents=True, exist_ok=True)
        lock = ra.POST_GROUP_LOCK_DIR / ("%s.lock" % g)
        lock.write_text("not-json{{", encoding="utf-8")
        with mock.patch.object(ra.Path, "unlink", side_effect=OSError("locked")):
            self.assertIsNone(ra.acquire_post_group_lock(g, "A"))

    def test_pop_forced_runs_unlink_fail(self):
        # CONTROL_FILE 存在但 unlink 抛 OSError → 776-777（防御性）
        ra.CONTROL_FILE.write_text(json.dumps({"force_run": "x"}), encoding="utf-8")
        with mock.patch.object(ra.Path, "unlink", side_effect=OSError("locked")):
            self.assertEqual(ra.pop_forced_runs(), ([], None))

    def test_selftest_classify_failure(self):
        # selftest 分类误判 → 271（classify 返回 (category, detail) 二元组）
        with mock.patch.object(ra.sr, "classify", return_value=("WRONG", "d")):
            self.assertEqual(ra.cmd_selftest(), 1)

    def test_selftest_w2_exception(self):
        # 互斥组锁异常 → 330-332
        with mock.patch.object(ra, "acquire_post_group_lock", side_effect=RuntimeError("boom")):
            self.assertEqual(ra.cmd_selftest(), 1)

    def test_selftest_maintenance_exception(self):
        # 现场维护（record_outcome）异常 → cmd_selftest 返回 1
        with mock.patch.object(ra, "record_outcome", side_effect=RuntimeError("boom")):
            self.assertEqual(ra.cmd_selftest(), 1)

    def test_selftest_login_gate_exception(self):
        # login_health_gate 异常 → 360-362
        with mock.patch.object(ra, "login_health_gate", side_effect=RuntimeError("boom")):
            self.assertEqual(ra.cmd_selftest(), 1)

    def test_escalate_corrupt_screen_gate(self):
        # SCREEN_GATE 存在但内容损坏 → 426-427（except 兜底为空 dict）
        ra.SCREEN_GATE.write_text("bad json{{{", encoding="utf-8")
        with mock.patch.object(ra, "append_alert"):
            ra.escalate_screen_recording_gate({"captureUnavailable": True, "diagnosis": "no-tcc"})

    def test_run_one_escalates_on_evidence(self):
        # probe 返回非空证据 → 479 触发 escalate
        data = _minimal_manifest()
        ra._posts_cache.clear()
        posts = json.loads(ra.POSTS_JSON.read_text(encoding="utf-8"))
        posts["posts"]["jinsha-business"]["usedBy"] = ["daily-negative-reviews"]
        ra.POSTS_JSON.write_text(json.dumps(posts), encoding="utf-8")
        ra._posts_cache.clear()
        rec_ok = {"status": "SUCCESS", "category": sr.CAT_SUCCESS, "attempts": 1,
                  "next_action": "none", "finished_at": "2026-01-01T09:00:00", "logs": [None]}
        with mock.patch.object(ra, "probe_wechat_foreground",
                              return_value={"diagnosis": "ok", "pixels": {"captured": True, "verified": True}}), \
             mock.patch.object(ra, "escalate_screen_recording_gate") as m_esc, \
             mock.patch.object(sr, "run_skill", return_value=rec_ok), \
             mock.patch.object(sr, "update_last_success"):
            ra.run_one(data, "s-active", {})
            m_esc.assert_called_once()

    def test_write_ledger_xlsx_negative(self):
        # active 但 needs_adapter（done="否"）→ 592 红色字体分支
        data = {
            "skills": [
                {"name": "s-adapt", "order": 1, "enabled": True, "dev_state": "active",
                 "needs_adapter": True, "steps": []},
            ],
            "ledger_template": [
                {"row": 1, "dev_state": "active", "skill": "s-adapt",
                 "ledger_name": "适配流程", "schedule": "每日"},
            ],
        }
        rows = ra.build_ledger_rows(data, {})
        self.assertEqual(rows[0]["done"], "否")
        out = self.tmp / "ledger-neg.xlsx"
        ok = ra.write_ledger_xlsx(rows, out, "2026-01-01")
        self.assertFalse(ok)
        self.assertTrue(out.exists())

    def test_daemon_cycle_resets_failures(self):
        # control.json 携带 reset_circuit → daemon_cycle 触发 clear_failures
        data = _minimal_manifest()
        ra._posts_cache.clear()
        posts = json.loads(ra.POSTS_JSON.read_text(encoding="utf-8"))
        posts["posts"]["jinsha-business"]["usedBy"] = ["daily-negative-reviews"]
        ra.POSTS_JSON.write_text(json.dumps(posts), encoding="utf-8")
        ra._posts_cache.clear()
        with mock.patch.object(ra.aw, "run_auth_watch", return_value=[]), \
             mock.patch.object(ra, "pop_forced_runs", return_value=([], "s-active")), \
             mock.patch.object(ra, "clear_failures") as m_clear, \
             mock.patch.object(ra, "login_health_gate"), \
             mock.patch.object(ra, "probe_wechat_foreground", return_value={}), \
             mock.patch.object(sr, "run_skill", return_value={"status": "SUCCESS",
                                  "category": sr.CAT_SUCCESS, "attempts": 1,
                                  "next_action": "none", "finished_at": "t", "logs": [None]}), \
             mock.patch.object(ra, "write_ledger_xlsx", return_value=True), \
             mock.patch.object(ra, "_maybe_send_ledger"), \
             mock.patch.object(ra, "write_last_cycle"):
            ra.daemon_cycle(data, {}, False, force_all=True)
            m_clear.assert_called_once_with("s-active")


    # ---- 补充覆盖：单向分支（逻辑覆盖率）----
    def test_load_posts_no_file(self):
        # POSTS_JSON 不存在 → 79->84（跳过读取，返回空）
        ra.POSTS_JSON.unlink(missing_ok=True)
        ra._posts_cache.clear()
        self.assertEqual(ra.load_posts(), {})

    def test_escalate_no_screen_gate(self):
        # SCREEN_GATE 不存在 → 423->428（跳过读取历史）
        ra.SCREEN_GATE.unlink(missing_ok=True)
        with mock.patch.object(ra, "append_alert"):
            ra.escalate_screen_recording_gate({"diagnosis": "ok",
                                               "pixels": {"captured": True, "verified": True}})

    def test_run_one_recoverable_no_alert(self):
        # 分类为可恢复（非 SUCCESS 也非 alert_on）→ 490->495（不告警）
        data = _minimal_manifest()
        ra._posts_cache.clear()
        posts = json.loads(ra.POSTS_JSON.read_text(encoding="utf-8"))
        posts["posts"]["jinsha-business"]["usedBy"] = ["daily-negative-reviews"]
        ra.POSTS_JSON.write_text(json.dumps(posts), encoding="utf-8")
        ra._posts_cache.clear()
        rec = {"status": "FAIL", "category": sr.CAT_RECOVERABLE, "attempts": 1,
               "next_action": "retry", "finished_at": "", "logs": ["err"]}
        with mock.patch.object(ra, "probe_wechat_foreground", return_value={}), \
             mock.patch.object(sr, "run_skill", return_value=rec), \
             mock.patch.object(ra, "append_alert") as m_alert:
            ra.run_one(data, "s-active", {})
            m_alert.assert_not_called()

    def test_pop_forced_runs_list_form(self):
        # force_run 已是列表 → 771->773（不包成单元素列表）
        ra.CONTROL_FILE.write_text(json.dumps({"force_run": ["a", "b"]}), encoding="utf-8")
        self.assertEqual(ra.pop_forced_runs(), (["a", "b"], None))

    def test_maybe_send_ledger_no_sent_file(self):
        # SENT_TODAY 不存在 → 864->869（跳过读取，sent={}）
        ra.SENT_TODAY.unlink(missing_ok=True)
        path = self.tmp / "ledger.xlsx"
        path.write_text("x")
        ra._maybe_send_ledger(path, True, False, "2026-01-01")


if __name__ == "__main__":
    unittest.main(verbosity=2)
