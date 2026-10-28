"""Original-worker content verifier: verify two fresh UI copies; no send or ledger writer.

An original worker must supply the reviewed System Events/pasteboard driver.
This module deliberately has no CLI or default live driver.
"""
import hashlib
import io
import json
import time
import uuid
from PIL import Image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pixels(data):
    with Image.open(io.BytesIO(data)) as source:
        rgba = source.convert('RGBA')
        return {'width': rgba.width, 'height': rgba.height, 'rgbaSha256': sha(rgba.tobytes())}


def verify_copies(task, original, baseline_count, driver, *, expected_path=None):
    bare = {k: v for k, v in task.items() if k != 'binding'}
    binding = sha(json.dumps(bare, sort_keys=True, ensure_ascii=False).encode())
    item = task.get('item', {})
    if (task.get('binding') != binding or task.get('stage') != 'send'
            or item.get('type') != 'image' or task.get('expectedPresentation') != 'inline-image'
            or sha(original) != item.get('sha256') or len(original) != item.get('size')
            or type(baseline_count) is not int or baseline_count < 0):
        raise ValueError('candidate-image-task-or-source-invalid')
    source_pixels = pixels(original)
    group = task['request']['groupName']
    if expected_path is not None and (not isinstance(expected_path, list) or not expected_path
            or any(type(i) is not int or i < 0 for i in expected_path)):
        raise ValueError('candidate-original-image-row-invalid')
    expected_row = list(expected_path) if expected_path is not None else None

    def check():
        nonlocal expected_row
        if driver.owner_active(task['owner']) is not True:
            raise RuntimeError('candidate-owner-inactive')
        if driver.intent_matches(task['taskId'], binding, item['sha256']) is not True:
            raise RuntimeError('candidate-original-intent-mismatch')
        state = driver.snapshot()
        row = state.get('rowPath')
        if (state.get('groupName') != group or state.get('inputEmpty') is not True
                or state.get('frontmost') is not True or state.get('cellRole') != 'AXCell'
                or state.get('fileCard') is not False or type(state.get('rowCount')) is not int
                or state['rowCount'] <= baseline_count or not isinstance(row, list)
                or not row or any(type(i) is not int or i < 0 for i in row)):
            raise RuntimeError('candidate-target-or-new-inline-row-invalid')
        if expected_row is None:
            expected_row = list(row)
        elif row != expected_row:
            raise RuntimeError('candidate-image-row-changed')
        if sha(driver.read_source()) != item['sha256']:
            raise RuntimeError('candidate-source-changed')
        return state

    frames = []
    for _ in range(2):
        check()
        nonce = 'zhensi-image-readback-' + uuid.uuid4().hex
        before = driver.seed_nonce(nonce)  # Write only; never inspect prior clipboard data.
        if type(before) is not int or before < 0:
            raise RuntimeError('candidate-clipboard-count-invalid')
        check()
        action = driver.copy_image(expected_row, group)
        if (action.get('backend') != 'system-events-ui-tree' or action.get('copied') is not True
                or action.get('rowPath') != expected_row or action.get('menuShortcut') != 'C'
                or type(action.get('menuModifiers')) is not int or action['menuModifiers'] != 0):
            raise RuntimeError('candidate-copy-action-not-confirmed')
        check()
        copied = driver.clipboard_image()  # Driver may read only PNG/TIFF after the native copy.
        if (copied.get('type') not in ('public.png', 'public.tiff', 'NeXT TIFF v4.0 pasteboard type')
                or type(copied.get('changeCount')) is not int or copied['changeCount'] <= before
                or not isinstance(copied.get('data'), bytes)):
            raise RuntimeError('candidate-copy-not-fresh-image')
        actual = pixels(copied['data'])
        if actual != source_pixels:
            raise RuntimeError('candidate-copy-pixels-mismatch')
        check()
        frames.append({'groupName': group, 'inputEmpty': True, 'newMessageVisible': True,
                       'presentation': 'inline-image', 'messagePath': list(expected_row),
                       'observedAt': time.time(), 'clipboardNonceSha256': sha(nonce.encode()),
                       'changeCountBefore': before, 'changeCountAfter': copied['changeCount'],
                       'pasteboardType': copied['type'], 'pixels': actual,
                       'visibleImageContent': json.dumps({'copiedPixels': actual, 'pixelComparison': True})})
    return {'status': 'verified', 'sendAttempts': 0, 'newSendAttempts': 0,
            'sha256': item['sha256'], 'resolvedGroup': group, 'observations': frames,
            'verificationLevel': 'candidate-system-events-copy-pixels-two-frame',
            'ledgerModified': False}
