"""Content-specific evidence gates; no OCR text can authorize an action."""
import math
import re


def retryable_preflight(receipt):
    # Unknown errors and all attempted operations are terminal.
    return (receipt.get('sendAttempts') == 0 and receipt.get('hardGate') is not True
            and receipt.get('reason') in {
                'desktop-chat-input-focus-failed', 'wechat-search-region-contended',
                'ax-exact-header-count:0', 'exact-group-result-count:0'})


def text_proof(item, evidence):
    positions = evidence.get('bubblePositions', [])
    return (evidence.get('ok') is True and evidence.get('composerEmpty') is True
            and evidence.get('copyMenuCount') == 1
            and evidence.get('copiedTextSha256') == item['sha256']
            and len(positions) == 2
            and all(len(p) == 2 for p in positions)
            and all(abs(a - b) <= 6 for a, b in zip(*positions)))


def file_frame_matches(text, name, size):
    # Never correct arbitrary letters or accept a filename prefix.
    compact = re.sub(r'\s+', '', text)
    expected = re.sub(r'\s+', '', name)
    sizes = {f'{size}B', f'{size / 1024:.1f}KB', f'{size / 1024:.1f}K',
             f'{size / (1024 * 1024):.1f}MB', f'{size / (1024 * 1024):.1f}M'}
    sizes = {s for s in sizes if not s.startswith('0.0')}
    pending = ('上传中', '发送中', '发送失败', '重发', '重新发送')
    # Keep separators for exact filename identity: old-report.xlsx is not report.xlsx.
    tokens = text.split()
    full_name = name in tokens or name in text.splitlines()
    observed_sizes = set(re.findall(r'(?<![\d.])\d+(?:\.\d+)?(?:KB|MB|B|K|M)(?![A-Za-z\d.])', compact))
    return (full_name and bool(sizes & observed_sizes)
            and not any(token in compact for token in pending))


def fingerprint(image):
    from PIL import Image
    value = image.convert('L').resize((32, 32), Image.Resampling.LANCZOS)
    values = list(value.getdata())
    mean = sum(values) / len(values)
    return [v - mean for v in values]


def image_distance(left, right):
    a, b = fingerprint(left), fingerprint(right)
    # Flat images have no distinctive content: never accept by similarity alone.
    if min(sum(v*v for v in a), sum(v*v for v in b)) < 1024 * 25:
        return math.inf
    return sum(abs(x-y) for x, y in zip(a, b)) / len(a)


def recovery_decision(*, component, attempted, authorized, other_draft, lock_held, used):
    if attempted:
        return 'reconcile-only'
    if component not in ('wechat-app', 'mobile-service'):
        return 'blocked'
    if not authorized or other_draft or not lock_held or used >= 1:
        return 'blocked'
    return 'one-restart-then-full-preflight'
