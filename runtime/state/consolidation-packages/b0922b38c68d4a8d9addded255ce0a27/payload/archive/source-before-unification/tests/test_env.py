"""环境自检：连接、健康检查、ATX 状态。

用法：python -m tests.test_env
（无需真机也可部分验证：设 SKIP_DEVICE=1 跳过设备相关断言）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from driver import connect, healthcheck, ensure_atx_running  # noqa


def main():
    skip = os.environ.get("SKIP_DEVICE") == "1"
    print("[*] 环境自检开始")

    try:
        import uiautomator2  # noqa
        print("[✓] uiautomator2 已安装")
    except ImportError:
        print("[✗] uiautomator2 未安装，请 pip install uiautomator2")
        return 1

    if skip:
        print("[*] SKIP_DEVICE=1，跳过设备检查")
        return 0

    try:
        d = connect()
        info = healthcheck(d)
        print(f"[✓] 已连接设备: {info}")
        running = ensure_atx_running(d)
        print(f"[{'✓' if running else '✗'}] ATX 守护进程: {'运行中' if running else '未运行，请重跑 init'}")
    except Exception as e:
        print(f"[✗] 设备连接失败: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
