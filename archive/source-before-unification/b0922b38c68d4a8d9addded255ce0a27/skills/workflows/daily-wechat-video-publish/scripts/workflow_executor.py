#!/usr/bin/env python3
"""企业微信群视频 → 抖音/快手/视频号：固定执行器（企业微信 + 已登录 Chrome）。"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from lib.storage_paths import video_root
ROOT = video_root()
MAPPING = ROOT / '微信群-店铺名-店铺地址.xlsx'
RUN_ID_RE = re.compile(r'^(\d{8})-(\d{2})$')
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
PYTHON = sys.executable
AX_PYTHON = Path('/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python')


def read_mapping(path: Path) -> dict[str, dict[str, str]]:
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('m:si', NS):
                shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % NS['m'])))
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        relmap = {x.attrib['Id']: x.attrib['Target'] for x in rels}
        out = {}
        for sh in wb.find('m:sheets', NS):
            target = relmap[sh.attrib['{%s}id' % NS['r']]]
            if not target.startswith('xl/'):
                target = 'xl/' + target
            root = ET.fromstring(z.read(target))
            for row in root.findall('.//m:sheetData/m:row', NS):
                vals = {}
                for c in row.findall('m:c', NS):
                    v = c.find('m:v', NS)
                    val = '' if v is None else (v.text or '')
                    if c.attrib.get('t') == 's' and val:
                        val = shared[int(val)]
                    vals[c.attrib.get('r', '')[:1]] = val
                group, shop, address = vals.get('A', ''), vals.get('B', ''), vals.get('C', '')
                if group and shop and address:
                    out[group] = {'shop': shop, 'address': address}
        return out


def make_caption(cover_text: str, shop: str, address: str, ad: str) -> str:
    cover = re.sub(r'\s+', '', cover_text).strip('。！!')
    return f'{cover}，{ad}｜{shop}｜地址：{address}'


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def append_jsonl(path: Path, obj: object) -> None:
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def next_run_id(now: datetime | None = None, *, runs_dir: Path | None = None) -> str:
    """当天下一批：20260906-01、20260906-02。不带平台名。"""
    day = (now or datetime.now()).strftime('%Y%m%d')
    runs = runs_dir or (ROOT / 'runs')
    n = 0
    if runs.is_dir():
        for p in runs.iterdir():
            m = RUN_ID_RE.fullmatch(p.name)
            if m and m.group(1) == day:
                n = max(n, int(m.group(2)))
    return f'{day}-{n + 1:02d}'


def run_dir_for(args: argparse.Namespace) -> Path:
    from lib.wecom_config import namespace_dir

    rid = args.run_id
    if not rid:
        raise SystemExit('需要 --run-id')
    if args.enterprise and args.group:
        exact = namespace_dir(ROOT, args.enterprise, args.group) / rid
        if exact.is_dir():
            return exact
    candidates = []
    legacy = ROOT / 'runs' / rid
    if legacy.is_dir():
        candidates.append(legacy)
    candidates.extend(p for p in (ROOT / 'runs').glob(f'*/*/{rid}') if p.is_dir())
    if not candidates:
        raise SystemExit(f'批次不存在: {rid}')
    if len(candidates) > 1:
        raise SystemExit('批次号在多个企业/群中重复，请同时传 --enterprise 和 --group')
    return candidates[0]


def init_run(args: argparse.Namespace) -> Path:
    from lib.time_parse import parse_cutoff
    from lib.wecom_config import namespace_dir, require_name, state_dir

    enterprise = require_name(args.enterprise, 'enterprise')
    group = require_name(args.group, 'group')
    namespace = namespace_dir(ROOT, enterprise, group)
    run_id = args.run_id or next_run_id(runs_dir=namespace)
    if args.run_id and not RUN_ID_RE.fullmatch(run_id):
        raise SystemExit(f'run_id 须为 YYYYMMDD-序号，例如 20260906-01，收到: {run_id}')
    run = namespace / run_id
    run.mkdir(parents=True, exist_ok=False)
    mapping = read_mapping(Path(args.mapping))
    mapped = mapping.get(group, {})
    if args.shop:
        mapped['shop'] = args.shop
    if args.address:
        mapped['address'] = args.address
    if args.cutoff:
        cutoff_iso = parse_cutoff(args.cutoff).isoformat()
        cutoff_source = 'explicit'
    else:
        checkpoint = state_dir(ROOT, enterprise, group) / 'checkpoint.json'
        if checkpoint.is_file():
            saved = json.loads(checkpoint.read_text(encoding='utf-8'))
            cutoff_iso = parse_cutoff(saved['lastMessageTime']).isoformat()
            cutoff_source = 'enterprise_group_checkpoint'
        else:
            cutoff_iso = parse_cutoff('昨天 19:00').isoformat()
            cutoff_source = 'default_yesterday_1900'
    now = datetime.now(timezone.utc).isoformat()
    write_json(run / 'run.json', {
        'runId': run_id,
        'createdAt': now,
        'timezone': 'Asia/Shanghai',
        'enterprise': enterprise,
        'group': group,
        'sender': args.sender or '',
        'cutoff': cutoff_iso,
        'cutoffSource': cutoff_source,
        'source': {
            'type': 'wecom_desktop',
            'enterpriseMarker': (args.enterprise_marker or enterprise).strip(),
            'expectedCount': args.expected_count,
            'extensions': ['.mp4'],
        },
        'platform': 'all',
        'runtimeModelDecisions': 0,
        'mapping': mapped,
        'state': 'initialized',
    })
    for name in ('candidates.jsonl', 'timeline.jsonl', 'publish-receipts.jsonl'):
        (run / name).touch()
    (run / 'videos').mkdir(exist_ok=True)
    (run / 'artifacts').mkdir(exist_ok=True)
    append_jsonl(run / 'timeline.jsonl', {
        'node': 'run_initialized',
        'at': now,
        'runtimeModelDecision': False,
    })
    return run


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        import ApplicationServices  # noqa: F401
    except ImportError:
        if not AX_PYTHON.is_file() or Path(sys.executable).resolve() == AX_PYTHON.resolve():
            raise SystemExit('缺少 macOS Accessibility Python 运行环境')
        os.execv(str(AX_PYTHON), [str(AX_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
    from wecom_download import scan_group

    run = run_dir_for(args)
    result = scan_group(run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 1


def cmd_download(args: argparse.Namespace) -> int:
    from wecom_download import download_pending

    run = run_dir_for(args)
    result = download_pending(run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 1


def _thumb_for_video(video: Path) -> Path:
    from lib.cover_ocr import find_thumbnail_for_video
    import shutil

    thumb = find_thumbnail_for_video(video)
    if thumb:
        return thumb
    out = video.with_suffix('.jpg')
    if not out.exists() and shutil.which('ffmpeg'):
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-i', str(video), '-vframes', '1', str(out)],
                capture_output=True,
                check=False,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            pass
    if out.exists():
        return out
    preview_dir = video.parent.parent / 'artifacts' / 'previews'
    preview_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ['qlmanage', '-t', '-s', '900', '-o', str(preview_dir), str(video)],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pass
    preview = preview_dir / f'{video.name}.png'
    return preview if preview.exists() else video


def cmd_prepare(args: argparse.Namespace) -> int:
    from lib.cover_ocr import extract_cover_text

    run = run_dir_for(args)
    meta = json.loads((run / 'run.json').read_text(encoding='utf-8'))
    shop = meta.get('mapping', {}).get('shop') or ''
    address = meta.get('mapping', {}).get('address') or ''
    if not shop or not address:
        raise SystemExit('prepare 需要群映射中的店铺和地址；可在 init 传 --shop 与 --address')
    if not args.confirm_reviewed:
        raise SystemExit('下载后须人工检查视频内容；确认无误后用 prepare --confirm-reviewed')
    ad = args.ad
    rows = []
    for line in (run / 'candidates.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('state') not in ('downloaded', 'human_review_pending'):
            rows.append(row)
            continue
        video = Path(row['localFile'])
        if not video.is_file():
            row['state'] = 'rejected_wrong_source'
            row['note'] = '本地文件不存在，禁止发布'
            rows.append(row)
            continue
        thumb = _thumb_for_video(video)
        cover = row.get('source', {}).get('coverTextCorrected', '') or extract_cover_text(thumb)
        if not cover:
            cover = row.get('source', {}).get('coverPreview', '') or row.get('source', {}).get('coverText', '')
        from lib.source_guard import matches_topic, topic_keywords
        keys = topic_keywords(meta['group'], shop)
        if not matches_topic(cover, keys) and not matches_topic(str(cover) + str(row.get('source', {}).get('coverPreview', '')), keys):
            row['state'] = 'review_required'
            row['note'] = 'prepare 主题门无法确认，保留原文件并禁止发布'
            rows.append(row)
            continue
        row.setdefault('source', {})['coverText'] = cover
        row['coverThumb'] = str(thumb)
        row['caption'] = make_caption(cover, shop, address, ad)
        row['captionVersion'] = 1
        row['captionSource'] = 'ai_corrected' if row['source'].get('coverTextCorrected') else 'ocr_draft'
        row['location'] = address
        row['state'] = 'prepared'
        rows.append(row)
    (run / 'candidates.jsonl').write_text(
        ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8'
    )
    prepared = [r for r in rows if r.get('state') == 'prepared']
    append_jsonl(run / 'timeline.jsonl', {
        'node': 'captions_prepared',
        'at': datetime.now(timezone.utc).isoformat(),
        'count': len(prepared),
        'runtimeModelDecision': False,
    })
    plan = [{
        'localFile': r.get('localFile'),
        'sha256': r.get('sha256'),
        'caption': r.get('caption'),
        'captionVersion': r.get('captionVersion'),
        'captionSource': r.get('captionSource'),
        'location': r.get('location'),
        'messageTime': r.get('source', {}).get('messageTime'),
        'platforms': ['douyin', 'kuaishou', 'channels'],
    } for r in prepared]
    write_json(run / 'publish-plan.json', {'items': plan, 'platform': 'all'})
    meta['state'] = 'captions_prepared'
    write_json(run / 'run.json', meta)
    print(json.dumps({'ok': True, 'prepared': len(prepared), 'plan': str(run / 'publish-plan.json')}, ensure_ascii=False))
    return 0


def _bridge_script(platform: str) -> Path:
    if platform == 'douyin':
        return SCRIPTS / 'douyin_chrome_bridge.py'
    if platform == 'kuaishou':
        return SCRIPTS / 'kuaishou_chrome_bridge.py'
    if platform == 'channels':
        return SCRIPTS / 'channels_chrome_bridge.py'
    raise SystemExit(f'unknown-platform:{platform}')


def _publish_one(row: dict, platform: str, *, confirm: bool) -> dict:
    from lib.platform_spec import SPECS

    spec = SPECS[platform]
    cmd = [
        PYTHON, str(_bridge_script(platform)),
        '--video', row['localFile'],
        '--caption', row['caption'],
        '--location', row.get('location') or spec.poi_query,
    ]
    if confirm:
        cmd.append('--confirm-publish')
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'publish-timeout', 'platform': platform,
                'candidateId': row.get('id'), 'state': 'publish_unknown'}
    out = (proc.stdout or proc.stderr).strip()
    receipt = None
    # Bridges may print deterministic click traces before a pretty-printed JSON
    # receipt. Parse the final complete JSON object instead of only its last line.
    for offset, char in enumerate(out):
        if char != '{':
            continue
        try:
            candidate = json.loads(out[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            receipt = candidate
            break
    if receipt is None:
        receipt = {'ok': False, 'error': out}
    receipt['platform'] = platform
    receipt['candidateId'] = row.get('id')
    return receipt


def _receipt_state(receipt: dict) -> str:
    """保留上传前失败，使其不与发布结果未知混为一谈。"""
    if str(receipt.get('error') or '').startswith('pre_upload_failed:'):
        return 'pre_upload_failed'
    return receipt.get('state') or 'publish_unknown'


def cmd_publish(args: argparse.Namespace) -> int:
    from lib.platform_spec import overall_state, resolve_platforms, should_skip_platform

    run = run_dir_for(args)
    platforms = resolve_platforms(args.platform)
    rows = [json.loads(l) for l in (run / 'candidates.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    receipts = []
    aborted = False
    prepared = [r for r in rows if r.get('state') in ('prepared', 'publish_pending', 'submitted', 'verified')]
    for i, row in enumerate(prepared, 1):
        row.setdefault('platforms', {})
        for platform in platforms:
            prev = row['platforms'].get(platform) or {}
            if should_skip_platform(prev.get('state') or ''):
                continue
            receipt = _publish_one(row, platform, confirm=args.confirm_publish)
            receipt['index'] = i
            receipt['total'] = len(prepared)
            append_jsonl(run / 'publish-receipts.jsonl', receipt)
            receipts.append(receipt)
            row['platforms'][platform] = {
                'state': _receipt_state(receipt),
                'ok': receipt.get('ok'),
                'verified': receipt.get('verified'),
                'error': receipt.get('error'),
            }
            if not receipt.get('ok'):
                aborted = True
                break
        row['state'] = overall_state({k: v.get('state', '') for k, v in row['platforms'].items()})
        if aborted:
            break
    (run / 'candidates.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    if receipts:
        ok = all(r.get('ok') for r in receipts)
    else:
        ok = bool(prepared) and all(
            should_skip_platform((r.get('platforms') or {}).get(p, {}).get('state') or '')
            for r in prepared
            for p in platforms
        )
    print(json.dumps({
        'ok': ok,
        'platforms': list(platforms),
        'published': len(receipts),
        'receipts': receipts,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_reply(args: argparse.Namespace) -> int:
    raise SystemExit('评论回复尚未迁移到 control-existing-chrome；请手动在创作者中心回复')


def main() -> int:
    p = argparse.ArgumentParser(description='企业微信群视频 → 抖音/快手/视频号 工作流')
    p.add_argument('--mapping', default=str(MAPPING))
    p.add_argument('--enterprise')
    p.add_argument('--enterprise-marker')
    p.add_argument('--group')
    p.add_argument('--sender')
    p.add_argument('--cutoff')
    p.add_argument('--run-id')
    p.add_argument('--expected-count', type=int, default=0, help='0=扫描后冻结实际候选数')
    p.add_argument('--shop')
    p.add_argument('--address')
    p.add_argument('--ad', default='😋鱼杂王中王，舌尖上的鲜，从这锅鱼杂开始')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('init')
    s = sub.add_parser('scan')
    sub.add_parser('download')
    pr = sub.add_parser('prepare')
    pr.add_argument('--ad', default='😋鱼杂王中王，舌尖上的鲜，从这锅鱼杂开始')
    pr.add_argument('--confirm-reviewed', action='store_true')
    pub = sub.add_parser('publish')
    pub.add_argument('--confirm-publish', action='store_true')
    pub.add_argument('--platform', default='all', help='all|douyin|kuaishou|channels')
    rep = sub.add_parser('reply-comment')
    rep.add_argument('--work-title', required=True)
    rep.add_argument('--comment-snippet', required=True)
    rep.add_argument('--text', required=True)
    rep.add_argument('--confirm-reply', action='store_true')

    args = p.parse_args()
    if args.cmd == 'init':
        if not all([args.enterprise, args.group]):
            raise SystemExit('init 需要 --enterprise 和 --group')
        if args.expected_count < 0:
            raise SystemExit('--expected-count 不能小于 0')
        run = init_run(args)
        print(json.dumps({'ok': True, 'runDir': str(run), 'runId': run.name}, ensure_ascii=False))
        return 0
    if args.cmd == 'scan':
        return cmd_scan(args)
    if args.cmd == 'download':
        return cmd_download(args)
    if args.cmd == 'prepare':
        return cmd_prepare(args)
    if args.cmd == 'publish':
        return cmd_publish(args)
    if args.cmd == 'reply-comment':
        return cmd_reply(args)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
