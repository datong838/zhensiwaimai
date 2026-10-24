"""把企业微信界面确认的附件精确绑定到客户端缓存文件。"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from collections import Counter
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path


ATTACHMENT_RE = re.compile(
    r'(?P<filename>[0-9A-Za-z][0-9A-Za-z._ -]*?\.mp4)\s+(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>[KMG]B?)',
    re.IGNORECASE,
)


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Attachment:
    filename: str
    ui_size: str


def parse_attachments(texts: list[str]) -> list[Attachment]:
    seen: set[tuple[str, str]] = set()
    result: list[Attachment] = []
    for text in texts:
        normalized = re.sub(r'\s+', ' ', text).strip()
        for match in ATTACHMENT_RE.finditer(normalized):
            filename = Path(match.group('filename').strip()).name
            unit = match.group('unit').upper()
            if len(unit) == 1:
                unit += 'B'
            ui_size = f"{match.group('size')}{unit}"
            key = (filename, ui_size)
            if key not in seen:
                seen.add(key)
                result.append(Attachment(filename, ui_size))
    return result


def ui_size_range(value: str) -> tuple[int, int]:
    match = re.fullmatch(r'(\d+(?:\.\d+)?)(KB|MB|GB)', value.strip(), re.IGNORECASE)
    if not match:
        raise MediaError(f'无法解析界面大小: {value}')
    number = float(match.group(1))
    factor = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3}[match.group(2).upper()]
    decimals = len(match.group(1).split('.', 1)[1]) if '.' in match.group(1) else 0
    half_step = 0.5 * (10 ** -decimals) * factor
    center = number * factor
    return max(1, int(center - half_step)), int(center + half_step) + 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def cache_roots(home: Path | None = None) -> list[Path]:
    base = (home or Path.home()) / 'Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles'
    if not base.is_dir():
        return []
    return [p for p in base.glob('*/Caches/Files') if p.is_dir()]


def exact_cache_candidates(filename: str, *, home: Path | None = None) -> list[Path]:
    clean = Path(filename).name
    if clean != filename or not clean.lower().endswith('.mp4'):
        raise MediaError(f'非法附件文件名: {filename}')
    found: list[Path] = []
    for root in cache_roots(home):
        found.extend(p for p in root.rglob(clean) if p.is_file())
    return found


def select_exact_cache(filename: str, ui_size: str, *, home: Path | None = None) -> Path:
    lower, upper = ui_size_range(ui_size)
    matches = []
    for path in exact_cache_candidates(filename, home=home):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if lower <= size <= upper:
            matches.append(path)
    if not matches:
        raise MediaError(f'未找到界面已确认的缓存文件: {filename} {ui_size}')
    by_hash: dict[str, list[Path]] = {}
    for path in matches:
        by_hash.setdefault(_sha256(path), []).append(path)
    if len(by_hash) != 1:
        raise MediaError(f'同名同大小缓存内容不唯一: {filename}')
    return max(matches, key=lambda p: p.stat().st_mtime)


def wait_stable(path: Path, *, interval: float = 0.35, samples: int = 2) -> int:
    sizes = []
    for index in range(samples):
        sizes.append(path.stat().st_size)
        if index + 1 < samples:
            time.sleep(interval)
    if not sizes or sizes[-1] <= 0 or len(set(sizes)) != 1:
        raise MediaError(f'文件大小未稳定: {path}')
    return sizes[-1]


def validate_mp4(path: Path) -> None:
    if path.stat().st_size < 32:
        raise MediaError(f'MP4 文件过小: {path}')
    with path.open('rb') as stream:
        head = stream.read(64)
    if b'ftyp' not in head:
        raise MediaError(f'MP4 容器头无效: {path}')


def copy_verified(source: Path, destination: Path) -> dict[str, object]:
    wait_stable(source)
    validate_mp4(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + '.part')
    temp.unlink(missing_ok=True)
    shutil.copy2(source, temp)
    validate_mp4(temp)
    temp.replace(destination)
    return {'localFile': str(destination), 'bytes': destination.stat().st_size, 'sha256': _sha256(destination)}


def make_preview(video: Path, output_dir: Path) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ['qlmanage', '-t', '-s', '900', '-o', str(output_dir), str(video)],
        capture_output=True,
        text=True,
        check=False,
    )
    preview = output_dir / f'{video.name}.png'
    return preview if preview.is_file() else None


def media_duration_seconds(path: Path) -> float:
    proc = subprocess.run(
        ['mdls', '-raw', '-name', 'kMDItemDurationSeconds', str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise MediaError(f'无法读取视频时长: {path}') from exc


def native_video_profiles(home: Path | None = None) -> list[Path]:
    base = (home or Path.home()) / 'Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles'
    return [path for path in base.glob('*/Caches/Videos') if path.is_dir()]


def select_native_batch(
    durations: list[int],
    *,
    after: datetime,
    before: datetime | None = None,
    home: Path | None = None,
) -> list[Path]:
    """按活动 Profile、时间窗、数量和完整时长多重集合绑定无文件名视频批次。"""
    if not durations:
        raise MediaError('原生视频候选为空')
    lower = after.timestamp() - 60
    upper = (before or datetime.now().astimezone()).timestamp() + 300
    expected = Counter(durations)
    matched_profiles: list[list[Path]] = []
    for root in native_video_profiles(home):
        files = []
        for path in root.rglob('*'):
            try:
                if path.is_file() and path.suffix.lower() in ('.mov', '.mp4') and lower <= path.stat().st_mtime <= upper:
                    files.append(path)
            except OSError:
                continue
        if len(files) != len(durations):
            continue
        rounded = Counter(int(media_duration_seconds(path) + 0.5) for path in files)
        if rounded == expected:
            matched_profiles.append(sorted(files, key=lambda path: path.stat().st_mtime))
    if len(matched_profiles) != 1:
        raise MediaError(f'原生视频批次无法唯一绑定: matched_profiles={len(matched_profiles)}')
    files = matched_profiles[0]
    if files[-1].stat().st_mtime - files[0].stat().st_mtime > 20 * 60:
        raise MediaError('原生视频缓存生成时间跨度过大')
    return files
