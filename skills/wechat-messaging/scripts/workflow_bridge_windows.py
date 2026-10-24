#!/usr/bin/env python3
"""Windows-driver transport bridge: workflow_bridge business contract, swapped transport.

Orthogonal addition — desktop/mobile channels and every sealed file stay untouched.
Same CLI args, same REGISTRY authorization, same ledgers/markers as workflow_bridge.py:
the ONLY difference is the adapter (WindowsAdapter instead of DesktopAdapter), i.e.
where the physical WeChat UI automation runs (Windows 10 driver host, not this Mac).

Because ledgers are shared and keyed by event identity, a send verified on either
transport blocks a duplicate on the other (cross-transport dedup for free).

Known limitation: text reconcile (legacy_text_reconcile) inside the sealed bridge
proves bubbles via Mac-native copy readback; when invoked through this bridge that
proof path cannot run on the Windows transport and will fail honestly (not verified).
Fresh sends + file/image reconcile are fully supported here.

Usage: identical to workflow_bridge.py, e.g.
  python3 workflow_bridge_windows.py \
    --workflow-id negative-reviews --group '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰' \
    --payload-type file --authorization <token> --ledger <ledger> \
    --marker-name <marker.json> --output-dir <dir> --item /path/to/report.xlsx --execute
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_bridge
from windows_adapter import WindowsAdapter

# Per-route transport switch (2026-10-23): registry-routing.json
# routes.<workflow-id>.channel == "wecom" sends through the local Mac WeCom
# desktop UI (wecom_adapter). Absent field => Windows driver, unchanged.
ROUTING = Path(__file__).resolve().parent.parent / 'config' / 'registry-routing.json'


def _route_channel(workflow_id: str) -> str:
    try:
        data = json.loads(ROUTING.read_text(encoding='utf-8'))
        return str((data.get('routes') or {}).get(workflow_id, {}).get('channel') or 'windows')
    except Exception:
        return 'windows'  # fail-open to the battle-tested default transport


def main():
    parser = workflow_bridge.argparse.ArgumentParser(
        description='workflow_bridge with Windows-driver transport')
    for name in ('workflow-id', 'group', 'payload-type', 'authorization',
                 'ledger', 'marker-name', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--item', action='append', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--reconcile', action='store_true')
    parser.add_argument('--correction-v1', action='store_true')
    parser.add_argument('--resume-blocked-zero-marker')
    parser.add_argument('--deadline-unix', type=float)
    args = parser.parse_args()
    try:
        if _route_channel(args.workflow_id) == 'wecom':
            from wecom_adapter import WeComAdapter
            result = workflow_bridge.execute(args, adapter_factory=WeComAdapter)
        else:
            result = workflow_bridge.execute(args, adapter_factory=WindowsAdapter)
    except Exception as error:
        result = workflow_bridge.exception_receipt(error)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
