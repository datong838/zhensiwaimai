"""Original UI queue execution through visible native System Events controls."""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from ledger import atomic_json
from native_ui_tree import (read_anchor, read_anchors, execute, named_action,
                            SELECTORS, NativeUIActionRejected)
from wecom_ui_queue import QUEUE, owner_active, validate_response
from native_image_content_hook import submitted_image_observations


def ensure_group(group, owner=None):
    def live():
        if owner is not None and owner_active(owner) is not True:
            raise RuntimeError('native-ui-owner-not-active')
    live()
    _, title = read_anchor('conversationTitle')
    _, composer = read_anchor('composer')
    if composer['value'] != '':
        raise RuntimeError('native-ui-existing-draft-do-not-overwrite')
    if title['value'] == group:
        return title['value']
    live()
    execute([{'type': 'activate'}, named_action('key', 'main', key='search')], max_depth=0)
    read_anchor('search')  # Search animation can move the cached chat container.
    subprocess.run(['/usr/bin/pbcopy'], input=group.encode('utf-8'), check=True)
    live()
    submit = named_action('key', 'search', key='return')
    submit['expected'] = dict(submit['expected'], value=group)
    submit['waitForValue'] = True
    execute([named_action('click', 'search'),
             named_action('key', 'search', key='selectall'),
             named_action('paste', 'search'), submit], max_depth=0)
    _, title = read_anchor('conversationTitle')
    _, composer = read_anchor('composer')
    if title['value'] != group or composer['value'] != '':
        raise RuntimeError('native-ui-target-or-draft-mismatch')
    return title['value']


def preflight(folder):
    folder = Path(folder).resolve()
    if folder.parent != QUEUE.resolve():
        raise ValueError('native-ui-task-root-invalid')
    task = json.loads((folder / 'task.json').read_text())
    bare = {k: v for k, v in task.items() if k != 'binding'}
    binding = hashlib.sha256(json.dumps(bare, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if binding != task['binding'] or task['stage'] != 'preflight':
        raise ValueError('native-ui-task-invalid')
    if (folder / 'response.json').exists():
        return json.loads((folder / 'response.json').read_text())
    if task.get('lifetime') != 'owner-process' or owner_active(task['owner']) is not True:
        raise ValueError('native-ui-owner-not-active')
    # ensure_group already verified exact title + empty input on both paths.
    recovery_attempts = 0
    try:
        resolved_group = ensure_group(task['request']['groupName'], task['owner'])
    except RuntimeError as error:
        # A group-search preflight has no send permission. Retry only this exact
        # transient focus failure, before any claim/intent, under the same owner.
        if (not re.search(r'native-ui-focus-mismatch(?: \(-2700\))?\s*$', str(error))
                or owner_active(task['owner']) is not True
                or any((folder / name).exists() for name in
                       ('claim.json', 'send-intent.json', 'response.json'))):
            raise
        recovery_attempts = 1
        resolved_group = ensure_group(task['request']['groupName'], task['owner'])
    if owner_active(task['owner']) is not True:
        raise ValueError('native-ui-owner-not-active')
    claim = folder / 'claim.json'
    if not claim.exists():
        with claim.open('x') as f:
            json.dump({'worker': 'native-system-ui-post', 'pid': os.getpid(), 'at': time.time()}, f)
    reply = {'taskId': task['taskId'], 'binding': binding,
             'result': {'ok': True, 'resolvedGroup': resolved_group, 'inputEmpty': True,
                        'backend': 'system-events-ui-tree', 'observedAt': time.time(),
                        'preflightRecoveryAttempts': recovery_attempts}}
    validate_response(task, reply)
    atomic_json(folder / 'response.json', reply)
    return reply


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def composer_submit_action(group, value):
    anchors = json.loads(SELECTORS.read_text())['anchors']
    composer, title = anchors['composer'], anchors['conversationTitle']
    return {'type': 'key', 'key': 'return', 'path': composer['path'],
            'expected': composer['expected'] | {'value': value},
            'guards': [{'path': title['path'], 'expected': title['expected'] | {'value': group}}]}


def current_input_empty():
    try:
        return read_anchor('composer')[1]['value'] == ''
    except Exception:
        return False  # Unconfirmed; never grants another send.


def matching_texts(task):
    anchor = json.loads(SELECTORS.read_text())['anchors']['messages']
    tree = execute(root_path=anchor['path'], max_depth=4)
    texts = [re.sub(r'\[(\d+)\]\(tel:\d+\)', r'\1', n.get('value') or '')
             for n in tree['nodes'] if n.get('role') == 'AXTextArea']
    return [s for s in texts if text_hash(s) == task['item']['sha256']]


def message_observation(task, baseline_count=0):
    _, title = read_anchor('conversationTitle')
    _, composer = read_anchor('composer')
    matches = matching_texts(task)
    if title['value'] != task['request']['groupName'] or composer['value'] != '' or len(matches) <= baseline_count:
        raise RuntimeError('native-ui-message-not-confirmed')
    return {'groupName': title['value'], 'inputEmpty': True, 'newMessageVisible': True,
            'observedAt': time.time(), 'visibleText': matches[-1],
            'visibleTextSha256': text_hash(matches[-1])}


def send_text(folder):
    folder = Path(folder).resolve()
    if folder.parent != QUEUE.resolve():
        raise ValueError('native-ui-task-root-invalid')
    task = json.loads((folder / 'task.json').read_text())
    bare = {k: v for k, v in task.items() if k != 'binding'}
    binding = text_hash(json.dumps(bare, sort_keys=True, ensure_ascii=False))
    if binding != task['binding'] or task['stage'] != 'send' or task.get('item', {}).get('type') != 'text':
        raise ValueError('native-ui-text-task-invalid')
    if (folder / 'response.json').exists():
        return json.loads((folder / 'response.json').read_text())
    if (folder / 'send-intent.json').exists():
        raise ValueError('native-ui-existing-intent-readback-only')
    if task.get('lifetime') != 'owner-process' or owner_active(task['owner']) is not True:
        raise ValueError('native-ui-owner-not-active')
    text = task['item']['text']
    if text_hash(text) != task['item']['sha256'] or '\n' in text or '\r' in text:
        raise ValueError('native-ui-text-digest-or-line-invalid')
    _, title = read_anchor('conversationTitle')
    _, composer = read_anchor('composer')
    if title['value'] != task['request']['groupName'] or composer['value'] != '':
        raise ValueError('native-ui-target-or-draft-mismatch')
    # Repeated empty notices need a genuinely added matching row, not an old one.
    baseline_count = len(message_rows())
    if (folder / 'claim.json').exists():
        raise ValueError('native-ui-task-already-claimed')
    with (folder / 'claim.json').open('x') as f:
        json.dump({'worker': 'native-system-ui-post', 'pid': os.getpid(), 'at': time.time()}, f)
    with (folder / 'send-intent.json').open('x') as f:
        json.dump({'taskId': task['taskId'], 'binding': binding, 'sha256': task['item']['sha256'],
                   'at': time.time(), 'backend': 'system-events-ui-tree'}, f)
    submitted = False
    try:
        if owner_active(task['owner']) is not True:
            raise RuntimeError('native-ui-owner-not-active')
        execute([{'type': 'activate'}, named_action('click', 'composer')], max_depth=0)
        time.sleep(0.2)  # Native focus settles asynchronously; the guard remains mandatory.
        _, focused_title = read_anchor('conversationTitle')
        _, focused_draft = read_anchor('composer')
        if (focused_title['value'] != task['request']['groupName']
                or focused_draft['value'] != ''):
            raise RuntimeError('native-ui-focused-draft-not-empty-or-target-changed')
        subprocess.run(['/usr/bin/pbcopy'], input=text.encode('utf-8'), check=True)
        if owner_active(task['owner']) is not True:
            raise RuntimeError('native-ui-owner-not-active')
        execute([named_action('paste', 'composer')], max_depth=0)
        if owner_active(task['owner']) is not True:
            raise RuntimeError('native-ui-owner-not-active')
        # A thrown final action has an unknown physical outcome; never retry it.
        submitted = True
        execute([composer_submit_action(task['request']['groupName'], text)], max_depth=0)
        observations = [latest_text_observation(task, baseline_count), latest_text_observation(task, baseline_count)]
        result = {'status': 'verified', 'sendAttempts': 1, 'resolvedGroup': title['value'],
                  'sha256': task['item']['sha256'], 'observations': observations,
                  'backend': 'system-events-ui-tree'}
    except Exception as exc:
        if isinstance(exc, NativeUIActionRejected):
            submitted = False
        result = {'status': 'unknown' if submitted else 'blocked', 'sendAttempts': 1 if submitted else 0,
                  'resolvedGroup': title['value'], 'inputEmpty': current_input_empty(),
                  'reason': str(exc), 'backend': 'system-events-ui-tree'}
    reply = {'taskId': task['taskId'], 'binding': binding, 'result': result}
    validate_response(task, reply)
    atomic_json(folder / 'response.json', reply)
    return reply


def message_rows():
    path = json.loads(SELECTORS.read_text())['anchors']['messages']['path']
    return [n['path'] for n in execute(root_path=path, max_depth=1)['nodes']
            if n['role'] == 'AXRow']


def latest_text_observation(task, baseline_count):
    rows = message_rows()
    if len(rows) <= baseline_count:
        raise RuntimeError('native-ui-no-new-message-row')
    nodes = execute(root_path=rows[-1], max_depth=3)['nodes']
    texts = [re.sub(r'\[(\d+)\]\(tel:\d+\)', r'\1', n.get('value') or '')
             for n in nodes if n['role'] == 'AXTextArea']
    matches = [s for s in texts if text_hash(s) == task['item']['sha256']]
    _, state = read_anchors('conversationTitle', 'composer')
    title, composer = state['conversationTitle'], state['composer']
    if title['value'] != task['request']['groupName'] or composer['value'] != '' or not matches:
        raise RuntimeError('native-ui-message-not-confirmed')
    return {'groupName': title['value'], 'inputEmpty': True, 'newMessageVisible': True,
            'observedAt': time.time(), 'visibleText': matches[-1],
            'visibleTextSha256': text_hash(matches[-1]), 'messagePath': rows[-1]}


def ui_action(kind, path, expected, **extra):
    return {'type': kind, 'path': path, 'expected': expected, **extra}


class NativeImageObservationPending(RuntimeError):
    def __init__(self, reason, message_path):
        super().__init__(reason)
        self.message_path = list(message_path)


def media_observation(task, baseline_count, *, expected_path=None):
    rows = message_rows()
    if len(rows) <= baseline_count:
        raise RuntimeError('native-ui-no-new-message-row')
    if expected_path is not None and rows[-1] != expected_path:
        raise RuntimeError('native-ui-image-row-changed-during-readback')
    tree = execute(root_path=rows[-1], max_depth=3)
    nodes = tree['nodes']
    _, state = read_anchors('conversationTitle', 'composer')
    title, composer = state['conversationTitle'], state['composer']
    if title['value'] != task['request']['groupName'] or composer['value'] != '':
        raise RuntimeError('native-ui-target-or-draft-mismatch')
    result = {'groupName': title['value'], 'inputEmpty': True, 'newMessageVisible': True,
              'observedAt': time.time(), 'messagePath': rows[-1]}
    if task['item']['type'] == 'file':
        values = [n.get('value') for n in nodes]
        sizes = [s for s in values if isinstance(s, str) and re.fullmatch(r'\d+(?:\.\d+)?K', s)]
        if task['item']['name'] not in values or len(sizes) != 1:
            raise RuntimeError('native-ui-file-card-not-confirmed')
        result.update(visibleFileName=task['item']['name'], visibleFileSize=sizes[0])
    else:
        images = [n for n in nodes if n['role'] == 'AXImage' and
                  not (n.get('description') or '').startswith('file ')]
        if not images:
            raise NativeImageObservationPending('native-ui-inline-image-not-exposed', rows[-1])
        result.update(presentation='inline-image', visibleImageContent=json.dumps(
            {'actualAXImages': images, 'pixelComparison': False}, ensure_ascii=False))
    return result


def wait_image_observations(task, baseline_count, live, *, wait_seconds=15):
    """Wait on one submitted candidate, without any UI action or new send."""
    if task['item']['type'] != 'image' or type(wait_seconds) not in (int, float) or not 0 < wait_seconds <= 15:
        raise ValueError('native-ui-image-observation-wait-scope-invalid')
    stop = time.monotonic() + wait_seconds
    expected_path = None
    observations = []
    pending = RuntimeError('native-ui-inline-image-two-observations-unavailable')
    while True:
        live()
        try:
            observed = media_observation(task, baseline_count, expected_path=expected_path)
            if expected_path is None:
                expected_path = list(observed['messagePath'])
            observations.append(observed)
            if len(observations) == 2:
                return observations
        except NativeImageObservationPending as error:
            if expected_path is not None and error.message_path != expected_path:
                raise RuntimeError('native-ui-image-row-changed-during-readback') from error
            expected_path = error.message_path
            observations.clear()
            pending = error
        except RuntimeError as error:
            if str(error) != 'native-ui-no-new-message-row' or expected_path is not None:
                raise
            observations.clear()
            pending = error
        remaining = stop - time.monotonic()
        if remaining <= 0:
            raise pending
        time.sleep(min(0.25, remaining))


def media_toolbar_path(kind, anchors):
    if kind not in ('file', 'image'):
        raise ValueError('native-ui-media-kind-invalid')
    title, composer = anchors['conversationTitle'], anchors['composer']
    chat = title['path'][:-1]
    region = chat + [9, 0]
    path = composer['path']
    if (title['expected'].get('role') != 'AXTextField'
            or composer['expected'] != {'role': 'AXTextArea', 'description': '文本输入区'}
            or len(path) != len(region) + 2 or path[:len(region)] != region
            or path[-1] != 0 or type(path[-2]) is not int or not 2 <= path[-2] <= 16):
        raise ValueError('native-ui-media-toolbar-layout-invalid')
    return region + [path[-2] + (6 if kind == 'file' else 4)]


def send_media(folder):
    folder = Path(folder).resolve()
    if folder.parent != QUEUE.resolve():
        raise ValueError('native-ui-task-root-invalid')
    task = json.loads((folder / 'task.json').read_text())
    bare = {k: v for k, v in task.items() if k != 'binding'}
    binding = text_hash(json.dumps(bare, sort_keys=True, ensure_ascii=False))
    kind = task.get('item', {}).get('type')
    if binding != task['binding'] or task['stage'] != 'send' or kind not in ('file', 'image'):
        raise ValueError('native-ui-media-task-invalid')
    if (folder / 'response.json').exists():
        return json.loads((folder / 'response.json').read_text())
    if (folder / 'send-intent.json').exists() or (folder / 'claim.json').exists():
        raise ValueError('native-ui-existing-intent-or-claim-readback-only')
    def live():
        if task.get('lifetime') != 'owner-process' or owner_active(task['owner']) is not True:
            raise RuntimeError('native-ui-owner-not-active')
    def action(a, **kwargs):
        live()
        return execute([a], **kwargs)
    live()
    source = Path(task['item']['path'])
    if hashlib.sha256(source.read_bytes()).hexdigest() != task['item']['sha256']:
        raise ValueError('native-ui-source-sha-mismatch')
    _, title = read_anchor('conversationTitle')
    _, composer = read_anchor('composer')
    if title['value'] != task['request']['groupName'] or composer['value'] != '':
        raise ValueError('native-ui-target-or-draft-mismatch')
    baseline_count = len(message_rows())
    with (folder / 'claim.json').open('x') as f:
        json.dump({'worker': 'native-system-ui-post', 'at': time.time()}, f)
    submitted = False
    try:
        action({'type': 'activate'}, max_depth=0)
        _, current = read_anchors('conversationTitle', 'composer')
        if current['conversationTitle']['value'] != task['request']['groupName'] or current['composer']['value'] != '':
            raise RuntimeError('native-ui-target-or-draft-mismatch')
        anchors = json.loads(SELECTORS.read_text())['anchors']
        action(ui_action('click', media_toolbar_path(kind, anchors),
                         {'role': 'AXButton', 'description': '按钮'}, guards=[
                             {'path': anchors['conversationTitle']['path'], 'expected':
                              {'role': 'AXTextField', 'description': '文本栏', 'value': task['request']['groupName']}},
                             {'path': anchors['composer']['path'], 'expected':
                              {'role': 'AXTextArea', 'description': '文本输入区', 'value': ''}}]), max_depth=0)
        label = '选取文件' if kind == 'file' else '选取图片'
        sheet_path, select_path = wait_media_selector(label, live)
        action(ui_action('key', sheet_path, {'role': 'AXSheet', 'description': '打开'}, key='goto'), max_depth=0)
        subprocess.run(['/usr/bin/pbcopy'], input=str(source).encode(), check=True)
        target = {'role': 'AXTextField', 'description': '文本栏'}
        action(ui_action('paste', sheet_path + [1, 2], target), max_depth=0)
        actual = execute(root_path=sheet_path + [1, 2], max_depth=0)['nodes'][0]
        if actual['value'] != str(source):
            raise RuntimeError('native-ui-source-path-mismatch')
        action(ui_action('key', sheet_path + [1, 2], target, key='return'), max_depth=0)
        selected = execute(root_path=sheet_path + [0, 2, 0], max_depth=4)['nodes']
        if not any(n.get('role') == 'AXTextField' and n.get('value') == task['item']['name'] for n in selected):
            raise RuntimeError('native-ui-selected-file-mismatch')
        live()
        with (folder / 'send-intent.json').open('x') as f:
            json.dump({'taskId': task['taskId'], 'binding': binding, 'sha256': task['item']['sha256'],
                       'at': time.time(), 'backend': 'system-events-ui-tree'}, f)
        # The selector normally prepares a draft; failures here remain unknown.
        live()
        submitted = True
        execute([ui_action('click', select_path, {'role': 'AXButton', 'name': label})], max_depth=0)
        _, title = read_anchor('conversationTitle')
        if title['value'] != task['request']['groupName']:
            raise RuntimeError('native-ui-target-changed')
        if kind == 'file':
            confirm_selected_file(task, baseline_count, live)
        else:
            _, draft = read_anchor('composer')
            if draft['value'] != '\ufffc':
                raise RuntimeError('native-ui-image-draft-mismatch')
            submitted = False  # The selected object is proven to remain in composer.
            live()
            submitted = True
            execute([composer_submit_action(task['request']['groupName'], '\ufffc')], max_depth=0)
        observations = (submitted_image_observations(task, folder, baseline_count, live, original_wait=wait_image_observations, pending_type=NativeImageObservationPending, native=sys.modules['native_ui_tree'], queue=QUEUE, owner_check=owner_active) if kind == 'image'
                        else [media_observation(task, baseline_count), media_observation(task, baseline_count)])
        result = {'status': 'verified', 'sendAttempts': 1, 'resolvedGroup': title['value'],
                  'sha256': task['item']['sha256'], 'observations': observations,
                  'backend': 'system-events-ui-tree'}
    except Exception as exc:
        if isinstance(exc, NativeUIActionRejected):
            submitted = False
        result = {'status': 'unknown' if submitted else 'blocked', 'sendAttempts': 1 if submitted else 0,
                  'resolvedGroup': title['value'], 'inputEmpty': current_input_empty(), 'reason': str(exc),
                  'backend': 'system-events-ui-tree'}
    reply = {'taskId': task['taskId'], 'binding': binding, 'result': result}
    validate_response(task, reply)
    atomic_json(folder / 'response.json', reply)
    return reply


def wait_media_selector(label, live):
    """Wait on real native state, not a fixed execution deadline or coordinates."""
    while True:
        live()
        roots = execute(max_depth=1)['nodes']
        sheets = [n for n in roots if n.get('role') == 'AXSheet' and n.get('description') == '打开']
        if len(sheets) > 1:
            raise RuntimeError('native-ui-media-selector-not-unique')
        if sheets:
            path = sheets[0]['path']
            nodes = execute(root_path=path, max_depth=2)['nodes']
            buttons = [n for n in nodes if n.get('role') == 'AXButton' and n.get('name') == label]
            if len(buttons) == 1:
                return path, buttons[0]['path']
            if len(buttons) > 1 or any(n.get('name') in ('选取文件', '选取图片') for n in nodes):
                raise RuntimeError('native-ui-media-selector-semantic-mismatch')
        time.sleep(0.15)  # UI animation settling, not an execution expiry.


def confirm_selected_file(task, baseline_count, live):
    """Only called after exact file/SHA selection and original intent persisted."""
    _, title = read_anchor('conversationTitle')
    _, draft = read_anchor('composer')
    if title['value'] != task['request']['groupName']:
        raise RuntimeError('native-ui-target-changed')
    if draft['value'] == '\ufffc':
        # The native file picker can prepare an attachment instead of a preview.
        # Exact filename and source were already verified in that picker.
        live()
        execute([composer_submit_action(task['request']['groupName'], '\ufffc')], max_depth=0)
        return
    if draft['value'] != '':
        raise RuntimeError('native-ui-file-draft-mismatch')
    try:
        media_observation(task, baseline_count)
        return  # Selector already sent: never click/Return a second time.
    except RuntimeError as error:
        if str(error) not in ('native-ui-no-new-message-row', 'native-ui-file-card-not-confirmed'):
            raise
    preview = execute(root_path=[4], max_depth=2)['nodes']
    if not any(n.get('value') == task['item']['name'] for n in preview):
        raise RuntimeError('native-ui-file-preview-mismatch')
    buttons = [n for n in preview if n.get('name') == '使用原文件' and n['role'] == 'AXButton']
    if len(buttons) != 1:
        raise RuntimeError('native-ui-original-file-confirmation-missing')
    live()
    execute([ui_action('click', buttons[0]['path'], {'role': 'AXButton', 'name': '使用原文件'})], max_depth=0)


def dispatch(folder):
    folder = Path(folder).resolve()
    if folder.parent != QUEUE.resolve():
        raise ValueError('native-ui-task-root-invalid')
    task = json.loads((folder / 'task.json').read_text())
    if task['stage'] == 'preflight':
        return preflight(folder)
    if task['stage'] == 'send':
        return (send_text if task.get('item', {}).get('type') == 'text' else send_media)(folder)
    bare = {k: v for k, v in task.items() if k != 'binding'}
    if text_hash(json.dumps(bare, sort_keys=True, ensure_ascii=False)) != task['binding']:
        raise ValueError('native-ui-task-invalid')
    if (folder / 'response.json').exists():
        return json.loads((folder / 'response.json').read_text())
    reply = {'taskId': task['taskId'], 'binding': task['binding'], 'result': {
        'status': 'blocked', 'sendAttempts': 0, 'reason': 'native-ui-stage-unsupported:' + task['stage'],
        'resolvedGroup': None, 'inputEmpty': False, 'backend': 'system-events-ui-tree'}}
    atomic_json(folder / 'response.json', reply)
    return reply


if __name__ == '__main__':
    print(json.dumps(dispatch(sys.argv[1]), ensure_ascii=False))
