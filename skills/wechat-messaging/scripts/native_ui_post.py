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
from native_ui_tree import read_anchor, execute, named_action, SELECTORS
from wecom_ui_queue import QUEUE, owner_active, validate_response


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
    live()
    execute([named_action('key', 'search', key='selectall')], max_depth=0)
    subprocess.run(['/usr/bin/pbcopy'], input=group.encode('utf-8'), check=True)
    live()
    execute([named_action('paste', 'search')], max_depth=0)
    _, search = read_anchor('search')
    if search['value'] != group:
        raise RuntimeError('native-ui-search-value-mismatch')
    live()
    execute([named_action('key', 'search', key='return')], max_depth=0)
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
    ensure_group(task['request']['groupName'], task['owner'])
    # Read only the previously discovered precise anchors, not the full UI tree.
    _, title = read_anchor('conversationTitle')
    _, composer = read_anchor('composer')
    if title['value'] != task['request']['groupName'] or composer['value'] != '':
        raise ValueError('native-ui-target-or-draft-mismatch')
    if owner_active(task['owner']) is not True:
        raise ValueError('native-ui-owner-not-active')
    claim = folder / 'claim.json'
    if not claim.exists():
        with claim.open('x') as f:
            json.dump({'worker': 'native-system-ui-post', 'pid': os.getpid(), 'at': time.time()}, f)
    reply = {'taskId': task['taskId'], 'binding': binding,
             'result': {'ok': True, 'resolvedGroup': title['value'], 'inputEmpty': True,
                        'backend': 'system-events-ui-tree', 'observedAt': time.time()}}
    validate_response(task, reply)
    atomic_json(folder / 'response.json', reply)
    return reply


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


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
        subprocess.run(['/usr/bin/pbcopy'], input=text.encode('utf-8'), check=True)
        if owner_active(task['owner']) is not True:
            raise RuntimeError('native-ui-owner-not-active')
        execute([named_action('paste', 'composer')], max_depth=0)
        _, draft = read_anchor('composer')
        _, title = read_anchor('conversationTitle')
        if draft['value'] != text or title['value'] != task['request']['groupName']:
            raise RuntimeError('native-ui-draft-mismatch')
        if owner_active(task['owner']) is not True:
            raise RuntimeError('native-ui-owner-not-active')
        # A thrown final action has an unknown physical outcome; never retry it.
        submitted = True
        execute([named_action('key', 'composer', key='return')], max_depth=0)
        observations = [latest_text_observation(task, baseline_count), latest_text_observation(task, baseline_count)]
        result = {'status': 'verified', 'sendAttempts': 1, 'resolvedGroup': title['value'],
                  'sha256': task['item']['sha256'], 'observations': observations,
                  'backend': 'system-events-ui-tree'}
    except Exception as exc:
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
    _, title = read_anchor('conversationTitle')
    _, composer = read_anchor('composer')
    if title['value'] != task['request']['groupName'] or composer['value'] != '' or not matches:
        raise RuntimeError('native-ui-message-not-confirmed')
    return {'groupName': title['value'], 'inputEmpty': True, 'newMessageVisible': True,
            'observedAt': time.time(), 'visibleText': matches[-1],
            'visibleTextSha256': text_hash(matches[-1]), 'messagePath': rows[-1]}


def ui_action(kind, path, expected, **extra):
    return {'type': kind, 'path': path, 'expected': expected, **extra}


def media_observation(task, baseline_count):
    rows = message_rows()
    if len(rows) <= baseline_count:
        raise RuntimeError('native-ui-no-new-message-row')
    tree = execute(root_path=rows[-1], max_depth=3)
    nodes = tree['nodes']
    _, title = read_anchor('conversationTitle')
    _, composer = read_anchor('composer')
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
            raise RuntimeError('native-ui-inline-image-not-exposed')
        result.update(presentation='inline-image', visibleImageContent=json.dumps(
            {'actualAXImages': images, 'pixelComparison': False}, ensure_ascii=False))
    return result


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
        chat_path = json.loads(SELECTORS.read_text())['anchors']['conversationTitle']['path'][:-1]
        action(ui_action('click', chat_path + [9, 0, 8 if kind == 'file' else 6],
                         {'role': 'AXButton', 'description': '按钮'}), max_depth=0)
        label = '选取文件' if kind == 'file' else '选取图片'
        sheet = execute(root_path=[4], max_depth=2)['nodes']
        if not any(n['path'] == [4, 0, 9] and n.get('name') == label for n in sheet):
            raise RuntimeError('native-ui-media-selector-semantic-mismatch')
        action(ui_action('key', [4], {'role': 'AXSheet', 'description': '打开'}, key='goto'), max_depth=0)
        subprocess.run(['/usr/bin/pbcopy'], input=str(source).encode(), check=True)
        target = {'role': 'AXTextField', 'description': '文本栏'}
        action(ui_action('paste', [4, 1, 2], target), max_depth=0)
        actual = execute(root_path=[4, 1, 2], max_depth=0)['nodes'][0]
        if actual['value'] != str(source):
            raise RuntimeError('native-ui-source-path-mismatch')
        action(ui_action('key', [4, 1, 2], target, key='return'), max_depth=0)
        selected = execute(root_path=[4, 0, 2, 0], max_depth=4)['nodes']
        if not any(n.get('role') == 'AXTextField' and n.get('value') == task['item']['name'] for n in selected):
            raise RuntimeError('native-ui-selected-file-mismatch')
        live()
        with (folder / 'send-intent.json').open('x') as f:
            json.dump({'taskId': task['taskId'], 'binding': binding, 'sha256': task['item']['sha256'],
                       'at': time.time(), 'backend': 'system-events-ui-tree'}, f)
        # The selector normally prepares a draft; failures here remain unknown.
        live()
        submitted = True
        execute([ui_action('click', [4, 0, 9], {'role': 'AXButton', 'name': label})], max_depth=0)
        _, title = read_anchor('conversationTitle')
        if title['value'] != task['request']['groupName']:
            raise RuntimeError('native-ui-target-changed')
        if kind == 'file':
            preview = execute(root_path=[4], max_depth=2)['nodes']
            if not any(n.get('value') == task['item']['name'] for n in preview):
                raise RuntimeError('native-ui-file-preview-mismatch')
            buttons = [n for n in preview if n.get('name') == '使用原文件' and n['role'] == 'AXButton']
            if len(buttons) != 1:
                raise RuntimeError('native-ui-original-file-confirmation-missing')
            submitted = False  # A real unsent confirmation sheet is now proven.
            live()
            submitted = True
            execute([ui_action('click', buttons[0]['path'], {'role': 'AXButton', 'name': '使用原文件'})], max_depth=0)
        else:
            _, draft = read_anchor('composer')
            if draft['value'] != '\ufffc':
                raise RuntimeError('native-ui-image-draft-mismatch')
            submitted = False  # The selected object is proven to remain in composer.
            live()
            submitted = True
            execute([named_action('key', 'composer', key='return')], max_depth=0)
        observations = [media_observation(task, baseline_count), media_observation(task, baseline_count)]
        result = {'status': 'verified', 'sendAttempts': 1, 'resolvedGroup': title['value'],
                  'sha256': task['item']['sha256'], 'observations': observations,
                  'backend': 'system-events-ui-tree'}
    except Exception as exc:
        result = {'status': 'unknown' if submitted else 'blocked', 'sendAttempts': 1 if submitted else 0,
                  'resolvedGroup': title['value'], 'inputEmpty': current_input_empty(), 'reason': str(exc),
                  'backend': 'system-events-ui-tree'}
    reply = {'taskId': task['taskId'], 'binding': binding, 'result': result}
    validate_response(task, reply)
    atomic_json(folder / 'response.json', reply)
    return reply


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
