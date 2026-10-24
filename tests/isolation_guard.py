#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进程级测试隔离守卫（全仓统一、不可绕过）。

大同铁律（2026-09-30）：**所有任务流的测试脚本**都不得操控线上数据逻辑与线上群。

本模块是这条例在测试进程里的**硬防线**——比任何字符串约定都可靠：
    * 它不依赖测试作者"记得不连真机"，而是**让连接本身在测试进程里抛错**；
    * 测试进程里任何指向**生产状态目录**的写操作一律抛错；
    * 并强制 ZHS_TEST_MODE=1，使生产传输层（windows_adapter 等）在测试进程内
      连"构造"都不允许。

接入方式：在每个测试目录的 ``conftest.py`` 里三行即可全量生效——

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # 仓库根
    from tests.isolation_guard import install
    install()

``sys.addaudithook`` 一旦注册便**无法被测试代码移除**，因此即使某处测试忘了打桩、
或桩打在了已废弃的接缝上（2026-09-30 事故根因），也绝无可能驱动真实出站。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 与生产状态目录对应的**绝对路径片段**（单一数据源见 maintenance/test-isolation-policy.json）。
#: 测试产生的账本/收据/缓存必须落在临时目录；这些顶层目录只允许生产执行器写。
PRODUCTION_WRITE_SEGMENTS = (
    "zhensi_waimai_back/records",
    "zhensi_waimai_back/state",
    "zhensi_waimai_back/runs",
    "zhensi_waimai_back/artifacts",
    "zhensi_waimai_back/.runtime",
)

#: 逃生门：只允许生产环境不设置；测试内不得置 0。
TEST_MODE_ENV = "ZHS_TEST_MODE"


class TestIsolationViolation(RuntimeError):
    """测试进程试图触碰线上资源——守卫拦截。"""


_INSTALLED = False


def _is_loopback_host(host) -> bool:
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        try:
            host = host.decode("utf-8", "replace")
        except Exception:
            return False
    text = str(host).strip().lower()
    if text in {"", "localhost", "localhost.localdomain", "ip6-localhost",
                "::1", "::", "0.0.0.0", "unspecified"}:
        return True
    if text.startswith("127."):
        return True
    if text.startswith("/") or text.startswith("\\"):  # AF_UNIX 本地套接字路径
        return True
    return False


def _path_is_production_write(path) -> bool:
    if not path:
        return False
    text = str(path)
    if not text.startswith("/"):
        return False
    return any(seg in text for seg in PRODUCTION_WRITE_SEGMENTS)


def _audit_hook(event: str, args) -> None:
    try:
        if event == "socket.getaddrinfo":
            host = args[0] if args else None
            if not _is_loopback_host(host):
                raise TestIsolationViolation(
                    f"测试进程不得解析外部主机（{host!r}）：{event}")
        elif event == "socket.connect":
            address = args[1] if len(args) > 1 else args[0]
            if isinstance(address, (tuple, list)):
                host = address[0] if address else None
                if not _is_loopback_host(host):
                    raise TestIsolationViolation(
                        f"测试进程不得连接外部地址（{host!r}）：{event}")
            elif isinstance(address, (str, bytes, bytearray)):
                if not _is_loopback_host(address):
                    raise TestIsolationViolation(
                        f"测试进程不得连接外部地址（{address!r}）：{event}")
        elif event == "open":
            path = args[0] if args else None
            mode = args[1] if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 else 0
            writing = (
                isinstance(mode, str) and any(ch in mode for ch in "wax+")
            ) or (isinstance(flags, int) and (flags & (os.O_WRONLY | os.O_RDWR
                                                      | os.O_CREAT | os.O_APPEND)))
            if writing and _path_is_production_write(path):
                raise TestIsolationViolation(
                    f"测试进程不得写生产状态目录（{path!r}）：{event}")
    except TestIsolationViolation:
        raise
    except Exception:
        # 守卫自身异常不得波及无关操作。
        return


def install() -> None:
    """安装进程级隔离守卫（幂等）。"""
    global _INSTALLED
    if _INSTALLED:
        return
    os.environ[TEST_MODE_ENV] = "1"  # 强制开启：生产传输层据此拒绝构造
    if hasattr(sys, "addaudithook"):
        sys.addaudithook(_audit_hook)
    _INSTALLED = True


if __name__ == "__main__":
    install()
    print("isolation guard installed")
