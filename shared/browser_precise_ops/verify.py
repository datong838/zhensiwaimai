#!/usr/bin/env python3
"""verify.py — ② 成功校验 + 超时重试（移植自 Easel xhs_publish.py 的成功双校验纪律）.

核心纪律：浏览器精确操作不能「点了就当成了」。必须**断言结果态**——要么页面/数据出现了
预期变化，要么在超时内重试。对应 Easel 里 URL 离开 /publish + toast 的双校验，以及
merchant_collector_executor.mjs 的 pollState。

本模块给 Python 侧的旧桥（chrome_desktop_bridge.py 等无 pollState 的路径）补上等价能力：
  - wait_until(predicate, timeout_s, poll_s, label)：轮询直到 predicate 为真或超时。
  - verify_state(before, after, changed_pred, label)：断言动作后状态确实变了（消除假成功）。

纯 stdlib，可移植，带 selftest。
"""
from __future__ import annotations

import time


class VerifyTimeout(RuntimeError):
    """wait_until 超时仍不满足条件。"""


def wait_until(
    predicate,
    *,
    timeout_s: float = 10.0,
    poll_s: float = 0.3,
    label: str = "condition",
    sleep_fn=time.sleep,
    now_fn=time.monotonic,
) -> object:
    """轮询 predicate() 直到返回真值；超时抛 VerifyTimeout。

    predicate 返回真值即作为结果返回（便于顺便取数据）。predicate 抛异常按「未满足」处理，
    不向上传播——长流程里偶发抖动应继续等，而非立即失败。
    """
    deadline = now_fn() + timeout_s
    last = None
    while now_fn() < deadline:
        try:
            last = predicate()
        except Exception:
            last = None
        if last:
            return last
        sleep_fn(poll_s)
    raise VerifyTimeout(f"wait_until-timeout:{label}:>{timeout_s}s")


def verify_state(
    before,
    after,
    changed_pred,
    *,
    label: str = "state-change",
) -> object:
    """断言动作后状态确实满足 changed_pred(after, before)。

    用于「点了详情 → 详情弹层确实出现」「填了日期 → 输入框 Value 确实变成目标值」这类
    双校验。不满足即抛 VerifyTimeout（消除「点了但页面没反应」的假成功）。
    """
    if changed_pred(after, before):
        return after
    raise VerifyTimeout(f"verify_state-failed:{label}:state-not-changed")


def self_test() -> dict:
    # 1) 正常满足（谓词自增到 3）
    n = {"v": 0}

    def cond():
        n["v"] += 1
        return n["v"] >= 3

    r = wait_until(cond, timeout_s=2, poll_s=0.05, label="incr")
    assert r is True
    # 2) 超时
    try:
        wait_until(lambda: False, timeout_s=0.3, poll_s=0.05, label="never")
        raise AssertionError("should-have-timed-out")
    except VerifyTimeout:
        pass
    # 3) 异常按未满足处理
    def boom():
        raise RuntimeError("x")

    try:
        wait_until(boom, timeout_s=0.3, poll_s=0.05, label="boom")
        raise AssertionError("boom-should-timeout")
    except VerifyTimeout:
        pass
    # 4) verify_state 通过
    verify_state({"open": False}, {"open": True}, lambda a, b: a["open"] and not b["open"], label="opened")
    # 5) verify_state 失败
    try:
        verify_state({"open": False}, {"open": False}, lambda a, b: a["open"], label="still-closed")
        raise AssertionError("should-fail")
    except VerifyTimeout:
        pass
    return {"ok": True, "tests": 5}


if __name__ == "__main__":
    import json

    print(json.dumps(self_test(), ensure_ascii=False, indent=2))
