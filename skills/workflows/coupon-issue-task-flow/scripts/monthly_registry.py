"""Maintain this flow's local monthly roster and SA plan only; never creates coupons."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4]/'runtime'))
from monthly_registry_cli import main
if __name__ == '__main__':
    raise SystemExit(main('coupon-issue-task-flow'))
