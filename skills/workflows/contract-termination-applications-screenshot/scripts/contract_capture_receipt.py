"""Validate original current-day contract capture; no browser or delivery actions."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROUTE = 'https://open.shop.ele.me/manager/agent/dissolution-task'
HOME = 'https://open.shop.ele.me/manager/base/home'


def require(value, reason):
    if not value:
        raise ValueError('contract-capture-' + reason)


def natural(value):
    return type(value) is int and value >= 0


def capture_images(receipt, day, run_dir, task_status='处理中'):
    require(isinstance(receipt, dict) and receipt.get('ok') is True, 'not-successful')
    require(receipt.get('dryRun') is not True, 'dry-run')
    require(receipt.get('route') == ROUTE and receipt.get('taskStatus') == task_status, 'route-or-status')
    try:
        at = datetime.fromisoformat(receipt['at'].replace('Z', '+00:00'))
        valid_day = at.tzinfo is not None and at.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() == day
    except (KeyError, TypeError, AttributeError, ValueError):
        valid_day = False
    require(valid_day, 'business-date')
    require(receipt.get('reset') == HOME, 'home-reset-unconfirmed')
    pages, pager, rows = receipt.get('pages'), receipt.get('pager'), receipt.get('rows')
    require(isinstance(pages, list) and pages and isinstance(pager, dict) and isinstance(rows, list), 'missing-pagination')
    planned = pager.get('pages')
    require(type(planned) is int and planned > 0 and len(pages) == planned, 'incomplete-pages')
    total = pager.get('total')
    require(total is None or natural(total) and total == len(rows), 'total-mismatch')
    require(all(isinstance(p, dict) and type(p.get('page')) is int and p['page'] == i + 1
                and natural(p.get('rows')) for i, p in enumerate(pages)), 'page-order-or-count')
    require(sum(p['rows'] for p in pages) == len(rows), 'row-count-mismatch')
    require(not rows or all(p['rows'] > 0 for p in pages), 'empty-page-in-nonempty-result')
    require(rows or planned == 1, 'empty-multipage-result')
    headers, status = receipt.get('headers'), receipt.get('statusCheck')
    require(isinstance(headers, list) and all(isinstance(h, str) for h in headers), 'headers')
    indices = [i for i, h in enumerate(headers) if ''.join(h.split()) == '任务状态']
    require(len(indices) == 1 and isinstance(status, dict) and type(status.get('index')) is int
            and status['index'] == indices[0] and type(status.get('bad')) is int and status['bad'] == 0, 'status-check')
    require(all(isinstance(row, list) and len(row) == len(headers)
                and ''.join(str(row[indices[0]]).split()) == task_status for row in rows), 'row-status-or-schema')
    folder = Path(run_dir).resolve()/'shot-out'/day
    require(Path(receipt.get('outDir', '')).resolve() == folder, 'output-directory')
    images = []
    for page in pages:
        require(page.get('innerHScroll') is False, 'horizontal-clipping')
        source = Path(page.get('file', ''))
        expected = folder/f'{day}_合同解约申请_{task_status}_p{page["page"]}.png'
        require(source.is_absolute() and source.resolve() == expected
                and not source.is_symlink() and source.is_file(), 'image-path-or-missing')
        data = source.read_bytes()
        require(type(page.get('bytes')) is int and page['bytes'] == len(data), 'image-size')
        require(len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n'
                and data[12:16] == b'IHDR' and int.from_bytes(data[16:20], 'big') > 0
                and int.from_bytes(data[20:24], 'big') > 0, 'image-format')
        images.append(str(source))
    return images if rows else []


def load_run_images(run_dir, day):
    folder = Path(run_dir).resolve()/'shot-out'/day
    receipts = list(folder.glob(f'{day}_contract-termination_run-*.json'))
    require(len(receipts) == 1 and not receipts[0].is_symlink(), 'unique-original-receipt-required')
    receipt = json.loads(receipts[0].read_text(encoding='utf-8'))
    return capture_images(receipt, day, run_dir), receipt
