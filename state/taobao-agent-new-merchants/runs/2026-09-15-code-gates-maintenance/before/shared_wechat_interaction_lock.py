#!/usr/bin/env python3
"""Cross-process lease for short desktop-WeChat UI interaction sections."""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path


LOCK_PATH = Path(__file__).resolve().parents[1] / ".runtime" / "wechat-ui-interaction.lock"


class InteractionLockTimeout(RuntimeError):
    pass


class WeChatInteractionLock:
    def __init__(self, owner: str, *, timeout_seconds: float = 900.0,
                 poll_seconds: float = 0.2, lock_path: Path = LOCK_PATH) -> None:
        if not owner or timeout_seconds < 0 or poll_seconds <= 0 or poll_seconds > 5:
            raise ValueError("wechat-interaction-lock-config-invalid")
        self.owner = owner
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.lock_path = Path(lock_path)
        self.stream = None
        self.started = 0.0
        self.wait_cycles = 0
        self.wait_ms = 0
        self.acquired = False
        self.released = False

    def acquire(self):
        self.started = time.monotonic()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.stream = self.lock_path.open("a+", encoding="utf-8")
        os.chmod(self.lock_path, 0o600)
        while True:
            try:
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - self.started >= self.timeout_seconds:
                    self.stream.close()
                    self.stream = None
                    raise InteractionLockTimeout("wechat-interaction-lock-timeout")
                self.wait_cycles += 1
                time.sleep(min(self.poll_seconds, self.timeout_seconds))
        self.wait_ms = round((time.monotonic() - self.started) * 1000)
        self.stream.seek(0); self.stream.truncate()
        json.dump({"owner": self.owner, "pid": os.getpid(), "acquiredAt": time.time()}, self.stream)
        self.stream.flush(); os.fsync(self.stream.fileno())
        self.acquired = True
        return self

    def release(self):
        if self.released:
            return
        self.released = True
        if self.stream is not None:
            try:
                self.stream.seek(0); self.stream.truncate(); self.stream.flush(); os.fsync(self.stream.fileno())
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            finally:
                self.stream.close(); self.stream = None

    def receipt(self) -> dict:
        return {
            "lockPath": str(self.lock_path), "owner": self.owner,
            "waitCycles": self.wait_cycles, "waitMs": self.wait_ms,
            "acquired": self.acquired, "released": self.released,
        }

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return False
