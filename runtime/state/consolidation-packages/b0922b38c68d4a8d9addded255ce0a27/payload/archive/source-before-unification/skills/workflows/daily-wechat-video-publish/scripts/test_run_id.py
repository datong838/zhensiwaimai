"""批次号 YYYYMMDD-序号。"""
from datetime import datetime
from pathlib import Path
from typing import Optional

from workflow_executor import next_run_id


def test_next_run_id(tmp_path: Optional[Path] = None):
    root = tmp_path or Path('/tmp/zhensi-run-id-test')
    if tmp_path is None:
        if root.exists():
            for p in root.iterdir():
                p.rmdir() if p.is_dir() else p.unlink()
        root.mkdir(parents=True, exist_ok=True)
    day = datetime(2026, 9, 6)
    assert next_run_id(day, runs_dir=root) == '20260906-01'
    (root / '20260906-01').mkdir()
    assert next_run_id(day, runs_dir=root) == '20260906-02'
    (root / '20260907-01').mkdir()
    assert next_run_id(day, runs_dir=root) == '20260906-02'


if __name__ == '__main__':
    test_next_run_id()
    print('ok')
