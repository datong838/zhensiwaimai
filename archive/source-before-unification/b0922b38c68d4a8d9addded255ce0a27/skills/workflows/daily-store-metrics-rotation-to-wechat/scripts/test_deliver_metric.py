#!/usr/bin/env python3
"""`deliver_metric.py` 离线单测 —— 全程不碰 Windows 网关、不发任何消息。

覆盖的就是「放量前必须钉死」的几条：缺群名 fail-closed、图太小不发、
marker 三态（verified/unknown/blocked）、同日 sha 冲突硬阻断、闸门制动、无授权不发。

跑法：
    env -u PYTHONPATH <venv>/bin/python scripts/test_deliver_metric.py -v
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import deliver_metric as dm  # noqa: E402


def run(argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            code = dm.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    text = buf.getvalue().strip()
    out = json.loads(text.splitlines()[-1]) if text.startswith("{") else {"raw": text}
    return code, out


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self._saved = (dm.EVENTS, dm.GATE, dm.GROUP_MAP, dm.RUNS)
        dm.EVENTS = self.tmp / "events"
        dm.GATE = self.tmp / "send_gate.json"
        dm.GROUP_MAP = self.tmp / "group_map.json"
        dm.RUNS = self.tmp / "runs"
        self.img = self.tmp / "shot.png"
        self.img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20000)  # 20KB，过 8KB 线

    def tearDown(self):
        dm.EVENTS, dm.GATE, dm.GROUP_MAP, dm.RUNS = self._saved
        self._tmp.cleanup()

    def base_args(self, **kw) -> list[str]:
        args = ["--shop-id", "694471", "--metric", "M01", "--image", str(self.img),
                "--date", "1999-01-01"]
        if kw.get("group"):
            args += ["--group", kw["group"]]
        if kw.get("commit"):
            args += ["--commit"]
        if kw.get("auth"):
            args += ["--authorization-ref", kw["auth"]]
        return args


class TestDelivery(Base):
    def test_planned_with_explicit_group(self):
        code, out = run(self.base_args(group="【测试】群"))
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "planned")
        self.assertFalse((dm.EVENTS / "1999-01-01-metrics-694471-M01.json").exists(),
                         "dry-run 不许写 marker")

    def test_missing_group_fail_closed(self):
        code, out = run(self.base_args())
        self.assertEqual(code, 3)
        self.assertEqual(out["status"], "blocked")
        self.assertIn("group-unresolved", out["reason"])

    def test_group_from_map(self):
        dm.GROUP_MAP.write_text(json.dumps({"map": {"694471": "【映射】群"}}, ensure_ascii=False))
        code, out = run(self.base_args())
        self.assertEqual(code, 0)
        self.assertEqual(out["group"], "【映射】群")
        self.assertEqual(out["groupSource"], "group-map")

    def test_missing_image(self):
        args = self.base_args(group="X")
        args[args.index("--image") + 1] = str(self.tmp / "nope.png")
        code, out = run(args)
        self.assertEqual(code, 3)
        self.assertIn("image-not-found", out["reason"])

    def test_tiny_image_blocked(self):
        self.img.write_bytes(b"tiny")
        code, out = run(self.base_args(group="X"))
        self.assertEqual(code, 3)
        self.assertIn("image-too-small", out["reason"])

    def test_unknown_metric_argument_error(self):
        args = self.base_args(group="X")
        args[args.index("--metric") + 1] = "M12"
        code, out = run(args)
        self.assertEqual(code, 2)

    def test_gate_disarmed_blocks(self):
        dm.GATE.write_text(json.dumps({"armed": False}))
        code, out = run(self.base_args(group="X"))
        self.assertEqual(code, 3)
        self.assertEqual(out["reason"], "send-disarmed")

    def test_commit_without_authorization_blocks(self):
        code, out = run(self.base_args(group="X", commit=True))
        self.assertEqual(code, 3)
        self.assertEqual(out["reason"], "authorization-ref-required")
        self.assertFalse((dm.EVENTS / "1999-01-01-metrics-694471-M01.json").exists(),
                         "没授权就不该留 attempted 痕迹")

    def _marker(self, state: str, sha: str) -> pathlib.Path:
        p = dm.EVENTS / "1999-01-01-metrics-694471-M01.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"state": state, "sha256": sha}), encoding="utf-8")
        return p

    def test_verified_is_idempotent(self):
        import hashlib
        sha = hashlib.sha256(self.img.read_bytes()).hexdigest()
        self._marker("verified", sha)
        code, out = run(self.base_args(group="X"))
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "already_verified")

    def test_unknown_never_resends(self):
        import hashlib
        sha = hashlib.sha256(self.img.read_bytes()).hexdigest()
        self._marker("unknown", sha)
        code, out = run(self.base_args(group="X"))
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "unknown")
        self.assertIn("绝不重发", out["reason"])

    def test_payload_conflict_blocks(self):
        self._marker("verified", "deadbeef" * 8)
        code, out = run(self.base_args(group="X"))
        self.assertEqual(code, 4)
        self.assertEqual(out["status"], "conflict")

    def test_blocked_allows_retry(self):
        import hashlib
        sha = hashlib.sha256(self.img.read_bytes()).hexdigest()
        self._marker("blocked", sha)
        code, out = run(self.base_args(group="X"))
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "planned")
        self.assertEqual(out["retryFrom"], "blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
