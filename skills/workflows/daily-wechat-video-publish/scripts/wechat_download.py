"""下载 scan 阶段记录的原生视频到 runs/<run_id>/videos/。"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.history_index import record_entry
from lib.source_guard import (
    choose_new_mp4,
    header_is_target_group,
    matches_topic,
    stable_video_filename,
    topic_keywords,
)
from lib import wechat_bridge as wb
from wechat_scan import DURATION_RE

import sys

WECHAT_SKILL = Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/wechat-desktop-control/scripts')
sys.path.insert(0, str(WECHAT_SKILL))
import wechat_desktop as wd  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _load_candidates(run_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for line in (run_dir / 'candidates.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return [r for r in rows if r.get('state') == 'download_pending']


def _write_candidates(run_dir: Path, all_rows: list[dict[str, Any]]) -> None:
    path = run_dir / 'candidates.jsonl'
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in all_rows), encoding='utf-8')


WECHAT_CACHE = Path.home() / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'


def _video_mp4s() -> dict[Path, float]:
    out: dict[Path, float] = {}
    try:
        for path in WECHAT_CACHE.glob('**/msg/video/**/*.mp4'):
            if path.name.endswith('_raw.mp4'):
                continue
            try:
                out[path] = path.stat().st_mtime
            except OSError:
                pass
    except (InterruptedError, OSError):
        pass
    return out


def _pick_new_mp4(
    before: dict[Path, float],
    since_epoch: float,
    *,
    exclude: set[Path] | None = None,
) -> Path | None:
    return choose_new_mp4(before, _video_mp4s(), since_epoch=since_epoch, exclude=exclude or set())


def _click_screen_ocr(cx: float, cy: float) -> None:
    from lib.focus import seize_wechat
    seize_wechat()
    scale = wd.screen_scale()
    wd.click(cx / scale, cy / scale, activate=False, scale=1.0)
    time.sleep(0.2)


def _locate_video(hits, row: dict[str, Any]) -> tuple[float, float] | None:
    """点封面正中（下载箭头）。优先时长徽章，不要点分割线。"""
    want = (row.get('source') or {}).get('duration') or ''
    click = row.get('click') or {}
    durs = [h for h in hits if DURATION_RE.match(h.text.strip()) and h.cx > 700]
    if want:
        matched = [h for h in durs if h.text.strip() == want]
        if matched:
            durs = matched
    if durs:
        target_cy = click.get('cy')
        pick = min(durs, key=lambda h: abs(h.cy - target_cy)) if target_cy is not None else durs[0]
        return pick.cx - 90, pick.cy - 80
    cover = (row.get('source', {}).get('coverPreview') or '').strip()
    if len(cover) >= 4 and '分割线' not in cover:
        key = cover[:6]
        cands = [h for h in hits if key in h.text and h.cx > 550 and 200 < h.cy < 1300]
        if cands:
            return cands[0].cx, cands[0].cy + 40
    if click.get('cx') is not None and click.get('cy') is not None:
        return float(click['cx']), float(click['cy'])
    return None


def _escape_menu() -> None:
    subprocess.run(['osascript', '-e', 'tell application "System Events" to key code 53'], check=False)
    time.sleep(0.2)


def _click_save_as_menu_ax() -> bool:
    script = '''
tell application "System Events"
  tell process "WeChat"
    set frontmost to true
  end tell
  delay 0.2
  repeat with m in (every menu of process "WeChat")
    try
      repeat with mi in menu items of m
        set n to name of mi as text
        if n contains "另存为" or n contains "另存為" or n contains "Save As" then
          click mi
          return "ok"
        end if
      end repeat
    end try
  end repeat
  return "miss"
end tell
'''
    proc = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    return proc.returncode == 0 and (proc.stdout or '').strip() == 'ok'


def _click_save_as_menu_ocr(artifacts: Path) -> bool:
    shot = artifacts / 'save_as_menu.png'
    hits = wb.screenshot_screen(shot)
    menu = next(
        (
            h for h in hits
            if '另存为' in h.text or '另存為' in h.text
            or h.text.strip() in ('保存', 'Save As…', 'Save As', 'Save as')
        ),
        None,
    )
    if menu is None:
        return False
    _click_screen_ocr(menu.cx, menu.cy)
    return True


def _complete_save_dialog(dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    time.sleep(0.8)
    subprocess.run(['osascript', '-e', 'tell application "System Events" to keystroke "g" using {command down, shift down}'], check=False)
    time.sleep(0.45)
    subprocess.run(['pbcopy'], input=str(dest.resolve()).encode('utf-8'), check=True)
    time.sleep(0.15)
    subprocess.run(['osascript', '-e', 'tell application "System Events" to keystroke "v" using command down'], check=True)
    time.sleep(0.35)
    subprocess.run(['osascript', '-e', 'tell application "System Events" to key code 36'], check=True)
    time.sleep(0.45)
    subprocess.run(['osascript', '-e', 'tell application "System Events" to key code 36'], check=True)
    for _ in range(20):
        if dest.exists() and dest.stat().st_size > 1000:
            return True
        time.sleep(0.4)
    return dest.exists() and dest.stat().st_size > 1000


def _save_visible_video(
    hits,
    row: dict[str, Any],
    dest: Path,
    artifacts: Path,
    *,
    exclude_mp4: set[Path] | None = None,
) -> bool:
    """图1有下载箭头：先点视频让微信自己下；图2右键出现另存为再保存。"""
    del exclude_mp4
    pos = _locate_video(hits, row)
    if pos is None:
        click = row.get('click') or {}
        if click.get('cx') is None:
            return False
        pos = (click['cx'], click['cy'])
    _escape_menu()
    wb.click_window_local(pos[0], pos[1])
    for attempt in range(5):
        time.sleep(2.0 if attempt == 0 else 1.4)
        wb.right_click_window_local(pos[0], pos[1])
        time.sleep(0.45)
        if _click_save_as_menu_ax() or _click_save_as_menu_ocr(artifacts):
            if _complete_save_dialog(dest):
                return True
            _escape_menu()
            continue
        _escape_menu()
        wb.click_window_local(pos[0], pos[1])
    return False


def _locate_and_save(row: dict[str, Any], dest: Path, artifacts: Path) -> bool:
    artifacts.mkdir(parents=True, exist_ok=True)
    for i in range(6):
        shot = artifacts / f'locate_{i:02d}.png'
        hits = wb.screenshot_window(shot)
        if _save_visible_video(hits, row, dest, artifacts):
            return True
        wb.scroll_chat_up_small()
    return False


def _try_download_at(
    click: dict[str, float],
    dest: Path,
    *,
    exclude_mp4: set[Path] | None = None,
    row: dict[str, Any] | None = None,
    artifacts: Path | None = None,
) -> tuple[bool, Path | None]:
    if row is not None and artifacts is not None:
        if _locate_and_save(row, dest, artifacts):
            return True, dest
    before = _video_mp4s()
    since = time.time()
    cx, cy = click['cx'], click['cy']
    for offset in (0, 80, 120):
        wb.click_window_local(cx, min(cy + offset, 1200), activate=offset == 0)
        time.sleep(0.7 if offset == 0 else 0.5)
    time.sleep(2.0)
    for _ in range(12):
        mp4 = _pick_new_mp4(before, since, exclude=exclude_mp4)
        if mp4 and mp4.exists():
            shutil.copy2(mp4, dest)
            return True, mp4
        time.sleep(0.8)
    dest.unlink(missing_ok=True)
    return False, None


def _assert_target_group(group: str, sender: str, artifacts: Path) -> None:
    opened = wb.open_group(group, artifacts, sender=sender)
    if not opened.ok:
        raise RuntimeError(opened.note or '打开群失败')
    if not header_is_target_group(opened.header or '', group):
        raise RuntimeError(f'当前窗口不是指定群，拒绝下载: {opened.header!r}')


def _video_ocr_text(video: Path) -> str:
    from lib.cover_ocr import extract_cover_text, ocr_image

    out_dir = video.parent
    subprocess.run(
        ['qlmanage', '-t', '-s', '800', '-o', str(out_dir), str(video)],
        capture_output=True,
        text=True,
        check=False,
    )
    thumb = out_dir / f'{video.name}.png'
    if not thumb.exists():
        return ''
    rows = [t for t, _ in ocr_image(thumb)]
    rows.append(extract_cover_text(thumb))
    thumb.unlink(missing_ok=True)
    return ''.join(rows)


def _existing_video_names(videos_dir: Path) -> set[str]:
    names = {p.name for p in videos_dir.glob('*.mp4')}
    runs = videos_dir.parent.parent
    if runs.is_dir():
        for p in runs.glob('*/videos/*.mp4'):
            names.add(p.name)
    return names


def harvest_from_latest(run_dir: Path, *, max_steps: int = 80) -> dict[str, Any]:
    """拉到最新，小步上翻，下到早于 checkpoint 为止；文件名固定防重复。"""
    from lib.time_parse import parse_cutoff
    from wechat_scan import _parse_hits, visible_message_times

    run_meta = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
    group = run_meta['group']
    sender = run_meta['sender']
    keys = topic_keywords(group, run_meta.get('mapping', {}).get('shop', ''))
    if not keys:
        raise RuntimeError(f'群名/店名提不出主题词，拒绝下载: {group}')
    cutoff = parse_cutoff(run_meta['cutoff'])
    now = datetime.fromisoformat(run_meta['createdAt']).astimezone()
    videos_dir = run_dir / 'videos'
    videos_dir.mkdir(parents=True, exist_ok=True)
    artifacts = run_dir / 'artifacts' / 'download'
    existing = _existing_video_names(videos_dir)
    _assert_target_group(group, sender, artifacts)
    if not wb.jump_to_latest(artifacts, group):
        raise RuntimeError('没能拉到群最新，停止下载，避免往上翻到上周')

    all_rows: list[dict[str, Any]] = []
    seen_names: set[str] = set(existing)
    used_mp4: set[Path] = set()
    downloaded = 0
    skipped_dup = 0
    failed = 0

    for step in range(max_steps):
        hits = wb.screenshot_window(artifacts / f'harvest_{step:02d}.png')
        chat_blob = ' '.join(h.text for h in hits if h.cx > 900)
        if any(k in chat_blob for k in ('星期六', '星期日', '星期五')):
            print(f'[harvest] step={step} weekday_before_cutoff stop {chat_blob[:80]!r}', flush=True)
            break
        times = visible_message_times(hits, now)
        if not times:
            print(f'[harvest] step={step} no_chat_time skip_download', flush=True)
            wb.scroll_chat_up_small()
            continue
        if max(times) < cutoff:
            print(
                f'[harvest] step={step} past_cutoff '
                f'{max(times).strftime("%Y-%m-%d %H:%M")} stop',
                flush=True,
            )
            break
        items = _parse_hits(hits, group=group, sender=sender, cutoff=cutoff, now=now)
        print(
            f'[harvest] step={step} chat_times='
            f'{[t.strftime("%Y-%m-%d %H:%M") for t in sorted(times)]} '
            f'videos={len(items)}',
            flush=True,
        )
        for row in items:
            src = row['source']
            try:
                msg_dt = datetime.fromisoformat(src['messageTime'])
            except ValueError:
                msg_dt = cutoff
            if msg_dt <= cutoff:
                continue
            name = stable_video_filename(
                src['messageTime'],
                src.get('coverPreview', ''),
                src.get('duration', ''),
            )
            dest = videos_dir / name
            row['stableName'] = name
            if name in seen_names or dest.exists():
                row['state'] = 'skipped_duplicate'
                row['note'] = '文件名已存在，跳过'
                row['localFile'] = str(dest) if dest.exists() else ''
                skipped_dup += 1
                all_rows.append(row)
                seen_names.add(name)
                continue
            if _save_visible_video(hits, row, dest, artifacts, exclude_mp4=used_mp4):
                digest = sha256(dest)
                if any(
                    r.get('sha256') == digest
                    for r in all_rows
                    if r.get('state') == 'downloaded'
                ):
                    dest.unlink(missing_ok=True)
                    row['state'] = 'skipped_duplicate'
                    row['note'] = '内容与已下文件相同，跳过'
                    skipped_dup += 1
                    all_rows.append(row)
                    seen_names.add(name)
                    continue
                ocr_blob = _video_ocr_text(dest)
                preview = src.get('coverPreview', '')
                row['localFile'] = str(dest)
                row['sha256'] = digest
                row['state'] = 'downloaded'
                row['downloadedAt'] = datetime.now(timezone.utc).isoformat()
                if matches_topic(ocr_blob, keys) or matches_topic(preview, keys):
                    row['note'] = '已落盘，主题门通过'
                else:
                    row['note'] = '已落盘，首帧未读到鱼杂，留待人工检查'
                record_entry(row, run_id=run_meta['runId'], state='downloaded')
                seen_names.add(name)
                downloaded += 1
                all_rows.append(row)
                hits = wb.screenshot_window(artifacts / f'harvest_{step:02d}b.png')
            else:
                row['state'] = 'download_unknown'
                row['note'] = '当前屏另存为失败，继续小步上翻'
                failed += 1
                all_rows.append(row)
        times = visible_message_times(hits, now)
        if times and max(times) < cutoff:
            break
        wb.scroll_chat_up_small()

    prev = []
    cand_path = run_dir / 'candidates.jsonl'
    if cand_path.exists():
        for line in cand_path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                prev.append(json.loads(line))
    _write_candidates(run_dir, prev + all_rows)

    max_time = None
    for row in prev + all_rows:
        if row.get('state') in ('downloaded', 'prepared', 'submitted', 'verified'):
            mt = row['source']['messageTime']
            if max_time is None or mt > max_time:
                max_time = mt
    with (run_dir / 'timeline.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({
            'node': 'wechat_harvest_done',
            'at': datetime.now(timezone.utc).isoformat(),
            'downloaded': downloaded,
            'skippedDuplicate': skipped_dup,
            'failed': failed,
            'checkpoint': max_time,
            'runtimeModelDecision': False,
        }, ensure_ascii=False) + '\n')
    return {
        'ok': downloaded > 0,
        'downloaded': downloaded,
        'skippedDuplicate': skipped_dup,
        'failed': failed,
        'checkpoint': max_time,
    }


def download_pending(run_dir: Path) -> dict[str, Any]:
    return harvest_from_latest(run_dir)
