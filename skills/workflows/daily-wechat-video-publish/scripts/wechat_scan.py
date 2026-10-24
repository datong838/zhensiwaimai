"""扫描 Mac 桌面微信群聊，按发送人/时间筛选原生纯视频（排除视频号卡片）。"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.history_index import is_processed
from lib.source_guard import cover_off_topic, header_is_target_group, topic_keywords
from lib.time_parse import parse_cutoff, parse_message_time
from lib import wechat_bridge as wb

TIME_RE = re.compile(
    r'^(\d{1,2}:\d{2}|昨天\s*\d{1,2}:\d{2}|(星期|周)[一二三四五六日天]\s*\d{1,2}:\d{2})$'
)
DURATION_RE = re.compile(r'^0:[0-5]\d$')
VIDEO_MARKERS = ('[视频]', '［视频］', '[Video]')
CHANNEL_MARKERS = ('视频号', '［视频号］', '[视频号]', '视频号·')
SKIP_TEXT = ('分割线',)


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def _append_timeline(run: Path, node: str, **extra: Any) -> None:
    _append_jsonl(run / 'timeline.jsonl', {
        'node': node,
        'at': datetime.now(timezone.utc).isoformat(),
        'runtimeModelDecision': False,
        **extra,
    })


def _zh_count(text: str) -> int:
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def _is_sender(h, sender: str) -> bool:
    t = h.text.strip()
    if not (t == sender or (sender in t and len(t) <= len(sender) + 2)):
        return False
    if h.cy < 200 or h.cy > 1400:
        return False
    return h.cx < 420 or t == sender


def _is_duration_hit(h) -> bool:
    t = h.text.strip()
    if not DURATION_RE.match(t):
        return False
    if h.cy < 200 or h.cy > 1400:
        return False
    return h.cx > 700


def _is_time_hit(h) -> bool:
    t = h.text.strip()
    if DURATION_RE.match(t):
        return False
    if not TIME_RE.match(t):
        return False
    if h.cy < 150 or h.cy > 1400:
        return False
    # 只要聊天区中间的时间灰条，不要左侧会话列表钟点
    return h.cx > 900


def _is_native_video_block(block: list) -> bool:
    texts = [h.text.strip() for h in block]
    joined = ''.join(texts)
    if any(m in joined for m in CHANNEL_MARKERS):
        return False
    if any(m in joined for m in VIDEO_MARKERS):
        return True
    # Mac 微信原视频常显示 0:08，没有 [视频] 三个字
    return any(DURATION_RE.match(t) for t in texts)


def _block_time(block: list, now, all_hits) -> datetime | None:
    """只认贴在这条视频上方的聊天区时间；没有就不下。下方时间属于后面的消息。"""
    top = min(h.cy for h in block)
    best = None
    best_dist = 10**9
    for h in all_hits:
        if not _is_time_hit(h):
            continue
        if h.cy > top + 40:
            continue
        dist = top - h.cy
        if dist > 280:
            continue
        t = parse_message_time(h.text.strip(), now=now)
        if t is not None and dist < best_dist:
            best = t
            best_dist = dist
    return best


def _block_click(block: list, sender_hit) -> dict[str, float]:
    durs = [h for h in block if _is_duration_hit(h)]
    if durs:
        return {'cx': durs[0].cx - 90, 'cy': durs[0].cy - 80}
    cover = [h for h in block if h.cx > 430 and _zh_count(h.text) >= 4]
    if cover:
        cx = sum(h.cx for h in cover) / len(cover)
        cy = sum(h.cy for h in cover) / len(cover)
        return {'cx': cx, 'cy': cy}
    return {'cx': max(sender_hit.cx, 500), 'cy': sender_hit.cy + 100}


def _parse_hits(hits, *, group: str, sender: str, cutoff, now) -> list[dict[str, Any]]:
    """右侧聊天区解析；时间戳用全窗 OCR 里居中的「昨天 HH:MM / HH:MM」。"""
    ordered = sorted(
        [h for h in hits if h.cy > 180 and h.cy < 1380 and h.cx > 150],
        key=lambda h: (h.cy, h.cx),
    )
    found: list[dict[str, Any]] = []
    i = 0
    while i < len(ordered):
        h = ordered[i]
        if _is_time_hit(h):
            i += 1
            continue
        # 右侧聊天面板（排除左侧会话列表 cx<550）
        if h.cx < 550 or not _is_sender(h, sender):
            i += 1
            continue
        sender_hit = h
        block = [h]
        for prev in ordered:
            if prev.cx < 550:
                continue
            if sender_hit.cy - 500 <= prev.cy < sender_hit.cy:
                block.append(prev)
        j = i + 1
        while j < len(ordered):
            nxt = ordered[j]
            if nxt.cx < 550:
                j += 1
                continue
            if _is_sender(nxt, sender) and nxt.cy - sender_hit.cy > 60:
                break
            if _is_time_hit(nxt) and nxt.cy - sender_hit.cy > 80:
                break
            if nxt.cy - sender_hit.cy > 560:
                break
            block.append(nxt)
            j += 1
        msg_time = _block_time(block, now, ordered)
        if _is_native_video_block(block) and msg_time and msg_time > cutoff:
            click = _block_click(block, sender_hit)
            cover_hits = [
                x.text for x in block
                if x.cx > 430 and _zh_count(x.text) >= 4 and '分割线' not in x.text
            ]
            durs = [x.text.strip() for x in block if _is_duration_hit(x)]
            found.append({
                'id': str(uuid.uuid4()),
                'source': {
                    'group': group,
                    'sender': sender,
                    'messageTime': msg_time.isoformat(),
                    'coverText': '',
                    'coverPreview': ''.join(cover_hits)[:80],
                    'duration': durs[0] if durs else '',
                },
                'click': click,
                'state': 'download_pending',
            })
        i = j if j > i + 1 else i + 1
    return found


def visible_message_times(hits, now) -> list:
    times = []
    for h in hits:
        if _is_time_hit(h):
            t = parse_message_time(h.text.strip(), now=now)
            if t:
                times.append(t)
    return times


def scan_group(run_dir: Path, *, scroll_rounds: int = 24) -> dict[str, Any]:
    run_meta = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
    group = run_meta['group']
    sender = run_meta['sender']
    cutoff = parse_cutoff(run_meta['cutoff'])
    now = datetime.fromisoformat(run_meta['createdAt']).astimezone()
    artifacts = run_dir / 'artifacts' / 'scan'
    artifacts.mkdir(parents=True, exist_ok=True)

    opened = wb.open_group(group, artifacts, sender=sender)
    if not opened.ok:
        raise RuntimeError(opened.note or '打开群失败')
    if not header_is_target_group(opened.header or '', group):
        raise RuntimeError(f'当前窗口不是指定群，拒绝扫描: {opened.header!r}')

    _append_timeline(run_dir, 'wechat_group_opened', header=opened.header)
    if not wb.jump_to_latest(artifacts, group):
        raise RuntimeError('没能拉到群最新，停止扫描，避免往上翻到上周')

    seen_keys: set[str] = set()
    candidates: list[dict[str, Any]] = []
    keys = topic_keywords(group, run_meta.get('mapping', {}).get('shop', ''))
    if not keys:
        raise RuntimeError(f'群名/店名提不出主题词，拒绝扫描: {group}')

    for round_i in range(scroll_rounds):
        shot = artifacts / f'frame_{round_i:02d}.png'
        hits = wb.screenshot_window(shot)
        for item in _parse_hits(hits, group=group, sender=sender, cutoff=cutoff, now=now):
            key = '|'.join([
                item['source']['messageTime'],
                item['source'].get('coverPreview', ''),
            ])
            if key in seen_keys:
                continue
            if is_processed(item):
                item['state'] = 'skipped_duplicate'
            elif cover_off_topic(item['source'].get('coverPreview', ''), keys):
                # 封面 OCR 可能漏「鱼杂」；仍收下，下载后用首帧主题门决定
                item['note'] = '封面未读到主题词，待下载后首帧复核'
            seen_keys.add(key)
            candidates.append(item)
            _append_jsonl(run_dir / 'candidates.jsonl', item)
        times = visible_message_times(hits, now)
        if times and all(t < cutoff for t in times):
            break
        if round_i + 1 < scroll_rounds:
            wb.scroll_chat_up_small()

    _append_timeline(run_dir, 'wechat_scan_done', count=len(candidates))
    return {'ok': True, 'count': len(candidates), 'candidates': candidates}
