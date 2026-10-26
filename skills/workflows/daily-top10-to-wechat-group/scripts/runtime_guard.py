#!/usr/bin/env python3
"""Code-enforced runtime policy and WeChat serialization for Top10 delivery."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterable


SKILL_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = SKILL_ROOT / "runtime-policy.json"
CANONICAL_BROWSER_PROFILE = "taobao-brand"
CANONICAL_BROWSER_PORT = 9230
CANONICAL_WECHAT_CHANNEL = "desktop"
CANONICAL_TARGET_GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
# 2026-10-20 大同指令：发送目标群从 FEIBING NEO AI数字员工 改为运营群。
# 采用运营群完整精确名（与 daily-negative-reviews / 金鲨报表等 10 个流一致；
# windows_adapter resolve_group 精确命中，同 prefix 无歧义）。
CANONICAL_AUTHORIZATION = "zhensi-feibing-neo-ai-main-wechat-top10-v1"
SHARED_WECHAT_ROOT = Path(
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts"
)
EXPECTED_POLICY_FILES = {
    "runtime_guard": Path(__file__).resolve(),
    "workflow_executor": Path(__file__).with_name("workflow_executor.py"),
    "receipt_validator": Path(__file__).with_name("phone_executor.py"),
    "background_executor": Path(__file__).with_name("desktop_background_executor.mjs"),
    "desktop_sender": SKILL_ROOT.parents[1] / "wechat-messaging/scripts/workflow_bridge_windows.py",
    "desktop_preflight": SKILL_ROOT.parents[1] / "wechat-messaging/scripts/workflow_preflight.py",
    "messaging_dependencies": SKILL_ROOT.parents[1] / "wechat-messaging/dependencies.json",
    "wechat_interaction_lock": SHARED_WECHAT_ROOT / "wechat_interaction_lock.py",
}
DEFAULT_LOCK_PATH = (
    SHARED_WECHAT_ROOT.parent / ".runtime" / "wechat-ui-interaction.lock"
)
KNOWN_WECHAT_OPERATOR_MARKERS = (
    "/desktop_sender.py",
    "/desktop_wechat_sender.py",
    "/business_desktop_wechat_file_sender.py",
    "/desktop_wechat_evidence_sender.mjs",
    "/wechat_sender_executor.py",
    "/wechat_download.py",
)


class RuntimePolicyError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_runtime_policy(policy_path: Path = POLICY_PATH) -> dict:
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimePolicyError(f"runtime-policy-unreadable:{error}") from error

    required = {
        "schemaVersion": 1,
        "policyId": "daily-top10-desktop-v1",
        "browserProfile": CANONICAL_BROWSER_PROFILE,
        "browserPort": CANONICAL_BROWSER_PORT,
        "wechatChannel": CANONICAL_WECHAT_CHANNEL,
        "targetGroup": CANONICAL_TARGET_GROUP,
        "runtimeModelDecisions": 0,
    }
    for key, expected in required.items():
        if policy.get(key) != expected:
            raise RuntimePolicyError(f"runtime-policy-field-mismatch:{key}")

    files = policy.get("files")
    if not isinstance(files, dict) or set(files) != set(EXPECTED_POLICY_FILES):
        raise RuntimePolicyError("runtime-policy-file-set-mismatch")
    checked = {}
    digest_mismatches = []
    for label, expected_path in EXPECTED_POLICY_FILES.items():
        entry = files.get(label) or {}
        if entry.get("path") != str(expected_path):
            raise RuntimePolicyError(f"runtime-policy-file-path-mismatch:{label}")
        if not expected_path.is_file():
            raise RuntimePolicyError(f"runtime-policy-file-missing:{label}")
        actual = sha256_file(expected_path)
        if entry.get("sha256") != actual:
            digest_mismatches.append(label)
        checked[label] = actual
    if digest_mismatches:
        labels = ",".join(digest_mismatches)
        raise RuntimePolicyError(f"runtime-policy-file-digest-mismatch:{labels}")
    # The common manifest owns all transitive UI code pins, including the locator.
    import importlib.util
    spec = importlib.util.spec_from_file_location("top10_common_dependency_gate", EXPECTED_POLICY_FILES["desktop_preflight"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_dependencies()
    return policy | {"validatedFiles": checked}


def validate_runtime_arguments(args) -> None:
    if getattr(args, "browser_profile", None) != CANONICAL_BROWSER_PROFILE:
        raise RuntimePolicyError("runtime-policy-browser-profile-mismatch")
    if getattr(args, "browser_port", None) != CANONICAL_BROWSER_PORT:
        raise RuntimePolicyError("runtime-policy-browser-port-mismatch")
    if getattr(args, "wechat_channel", None) != CANONICAL_WECHAT_CHANNEL:
        raise RuntimePolicyError("runtime-policy-wechat-channel-mismatch")
    if getattr(args, "transport_file", None):
        raise RuntimePolicyError("runtime-policy-transport-not-allowed")
    if getattr(args, "execute", False):
        if getattr(args, "standing_authorization", None) != CANONICAL_AUTHORIZATION:
            raise RuntimePolicyError("runtime-policy-authorization-mismatch")


def running_wechat_operators() -> list[int]:
    try:
        completed = subprocess.run(
            ["/bin/ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=5
        )
    except OSError:
        # 2026-09-30：本机策略可能禁止 ps（如 WorkBuddy 手动运行环境）。
        # Mac 桌面微信已停用，运营者探针过时；Windows 传输由自身文件锁串行化。
        # 降级为「无其他运营者」，生产 launchd 环境仍可正常探测。
        return []
    if completed.returncode:
        raise RuntimePolicyError("wechat-contention-process-probe-failed")
    excluded = {os.getpid(), os.getppid()}
    matches = []
    for raw in completed.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        pid_text, _, command = raw.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid not in excluded and any(marker in command for marker in KNOWN_WECHAT_OPERATOR_MARKERS):
            matches.append(pid)
    return matches


class WeChatExecutionGuard:
    """Hold an OS lock and wait for known uncooperative operators to leave."""

    def __init__(
        self,
        owner: str,
        *,
        lock_path: Path = DEFAULT_LOCK_PATH,
        poll_seconds: float = 5.0,
        stable_checks: int = 2,
        process_provider: Callable[[], Iterable[int]] = running_wechat_operators,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not owner or poll_seconds <= 0 or poll_seconds > 60 or stable_checks < 2:
            raise RuntimePolicyError("wechat-contention-guard-config-invalid")
        self.owner = owner
        self.lock_path = Path(lock_path)
        self.poll_seconds = poll_seconds
        self.stable_checks = stable_checks
        self.process_provider = process_provider
        self.sleeper = sleeper
        self._stream = None
        self._released = False
        self.stats = {
            "lockPath": str(self.lock_path),
            "lockWaitMs": 0,
            "lockWaitCycles": 0,
            "contentionWaitMs": 0,
            "contentionChecks": 0,
            "stableChecksRequired": stable_checks,
            "acquired": False,
            "released": False,
        }

    def acquire(self) -> dict:
        started = time.monotonic()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._stream = self.lock_path.open("a+", encoding="utf-8")
        os.chmod(self.lock_path, 0o600)
        while True:
            try:
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                self.stats["lockWaitCycles"] += 1
                self.sleeper(self.poll_seconds)
        self.stats["lockWaitMs"] = round((time.monotonic() - started) * 1000)
        self._stream.seek(0)
        self._stream.truncate()
        json.dump({"owner": self.owner, "pid": os.getpid(), "acquiredAt": time.time()}, self._stream)
        self._stream.flush()
        os.fsync(self._stream.fileno())

        self.wait_until_quiet()
        self.stats["acquired"] = True
        return dict(self.stats)

    def wait_until_quiet(self) -> dict:
        if self._stream is None:
            raise RuntimePolicyError("wechat-contention-lock-not-held")
        stable = 0
        while stable < self.stable_checks:
            competitors = list(self.process_provider())
            self.stats["contentionChecks"] += 1
            if competitors:
                stable = 0
                self.sleeper(self.poll_seconds)
                self.stats["contentionWaitMs"] += round(self.poll_seconds * 1000)
                continue
            stable += 1
            if stable < self.stable_checks:
                self.sleeper(self.poll_seconds)
                self.stats["contentionWaitMs"] += round(self.poll_seconds * 1000)
        return dict(self.stats)

    def release(self) -> dict:
        if self._released:
            return dict(self.stats)
        self._released = True
        if self._stream is not None:
            try:
                self._stream.seek(0)
                self._stream.truncate()
                self._stream.flush()
                os.fsync(self._stream.fileno())
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
            finally:
                self._stream.close()
        self.stats["released"] = True
        return dict(self.stats)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return False
