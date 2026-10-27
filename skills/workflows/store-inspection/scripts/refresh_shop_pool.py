"""Read roster UI through original Jinsha post, without running inspections."""
import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]/'runtime'))
from roster_post_lease import original_post_lease


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--node', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--city-probe')
    a = p.parse_args()
    extra = ['--city-probe', a.city_probe] if a.city_probe else []
    if a.city_probe and not a.inspect:
        raise ValueError('city-probe-inspect-only')
    with original_post_lease('jinsha-9232', 'store-inspection-roster-maintenance', '/tmp/zhensi-jinsha-cua-exam.lock'):
        return subprocess.run([a.node, str(HERE/'collect_monthly_roster.mjs'), '--inspect' if a.inspect else '--collect', '--out', str(a.out), *extra], timeout=480).returncode


if __name__ == '__main__':
    raise SystemExit(main())
