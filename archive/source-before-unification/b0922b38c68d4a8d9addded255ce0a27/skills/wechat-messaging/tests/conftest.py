"""测试目录 conftest：保证守卫在任意运行入口（即便 cd 进本目录单独跑）都生效。"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from tests.isolation_guard import install as _install  # noqa: E402

_install()
