"""测试目录 conftest：保证《测试隔离守卫》在任意运行入口都生效。"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from tests.isolation_guard import install as _install  # noqa: E402

_install()
