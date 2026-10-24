"""仓库根 conftest：自动为所有被测进程安装《测试隔离守卫》。

详见 tests/isolation_guard.py —— 测试进程内禁止任何非回环出站、禁止写生产状态目录。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests.isolation_guard import install as _install  # noqa: E402

_install()
