"""Native System Events UI tree. No screen-capture or CUA dependency."""
import json
import subprocess
from pathlib import Path
SCRIPT = Path(__file__).with_suffix('.jxa')
SELECTORS = SCRIPT.parents[1] / 'config/native-ui-selectors.json'
ALLOWED = {'activate', 'click', 'key', 'paste'}
KEYS = {'return','escape','down','up','tab','backspace','search','goto','selectall'}


class NativeUIActionRejected(RuntimeError):
    """The native interpreter proved no action in this invocation was performed."""


def execute(actions=(), *, max_depth=2, root_path=(), root_paths=None):
    if root_paths is not None:
        if actions or max_depth != 0 or not root_paths:
            raise ValueError('native-ui-multi-anchor-read-only')
        if any(not isinstance(path, list) or any(type(i) is not int or i < 0 for i in path)
               for path in root_paths):
            raise ValueError('native-ui-path-invalid')
    for action in actions:
        if 'waitForValue' in action and (action['waitForValue'] is not True
                or action.get('type') != 'key' or action.get('key') != 'return'
                or action.get('expected', {}).get('role') != 'AXTextField'
                or not action.get('expected', {}).get('value')):
            raise ValueError('native-ui-value-wait-scope-invalid')
        for guard in action.get('guards', []):
            if (set(guard) != {'path', 'expected'} or not guard['expected']
                    or not isinstance(guard['path'], list)
                    or any(type(i) is not int or i < 0 for i in guard['path'])):
                raise ValueError('native-ui-context-guard-invalid')
        if action.get('modifier'):
            raise ValueError('native-ui-modifier-not-allowed')
        if action.get('type') == 'key' and action.get('key') not in KEYS:
            raise ValueError('native-ui-key-not-allowed')
        if action.get('type') not in ALLOWED:
            raise ValueError('native-ui-action-not-allowed')
        if action['type'] != 'activate':
            if not action.get('expected') or not isinstance(action.get('path'), list):
                raise ValueError('native-ui-target-required')
            if any(type(i) is not int or i < 0 for i in action['path']):
                raise ValueError('native-ui-path-invalid')
    config = {'actions': list(actions), 'maxDepth': max_depth, 'rootPath': list(root_path)}
    if root_paths is not None:
        config['rootPaths'] = root_paths
    payload = json.dumps(config, ensure_ascii=False)
    result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', str(SCRIPT), payload],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'native-ui-failed')
    decoded = json.loads(result.stdout)
    if decoded.get('actionRejected') is True:
        if decoded.get('results') == []:
            raise NativeUIActionRejected(decoded.get('error', 'native-ui-action-rejected'))
        raise RuntimeError('native-ui-rejected-after-prior-actions')
    return decoded


def read_anchors(*names):
    """One read-only UI call for exact cached anchors; no activation or input."""
    if not names or len(set(names)) != len(names):
        raise ValueError('native-ui-anchor-names-invalid')
    for attempt in range(2):
        anchors = json.loads(SELECTORS.read_text(encoding='utf-8'))['anchors']
        selected = [anchors[name] for name in names]
        result = execute(root_paths=[anchor['path'] for anchor in selected], max_depth=0)
        nodes = {tuple(node.get('path', [])): node for node in result['nodes']}
        values = [nodes.get(tuple(anchor['path'])) for anchor in selected]
        if all(node and all(node.get(k) == v for k, v in anchor['expected'].items())
               for anchor, node in zip(selected, values)):
            return result, dict(zip(names, values))
        if not attempt and 'main' not in names:
            refresh_chat_cache()
    raise RuntimeError('native-ui-anchor-changed:batch')

def read_anchor(name):
    anchor = json.loads(SELECTORS.read_text(encoding='utf-8'))['anchors'][name]
    for attempt in range(2):
        result = execute(root_path=anchor['path'], max_depth=0)
        node = result['nodes'][0]
        if all(node.get(k) == v for k, v in anchor['expected'].items()):
            return result, node
        if attempt or name == 'main':
            break
        refresh_chat_cache()
        anchor = json.loads(SELECTORS.read_text(encoding='utf-8'))['anchors'][name]
    raise RuntimeError('native-ui-anchor-changed:' + name)


def refresh_chat_cache():
    config = json.loads(SELECTORS.read_text(encoding='utf-8'))
    old = config['anchors']['conversationTitle']['path'][:-1]
    outer = execute(root_path=[0], max_depth=1)['nodes']
    candidates = []
    for n in outer:
        if n.get('role') != 'AXSplitGroup' or len(n.get('path', [])) != 2:
            continue
        path = n['path']
        local = execute(root_path=path, max_depth=1)['nodes']
        roles = {tuple(x['path']): x['role'] for x in local}
        if (roles.get(tuple(path + [1])) == 'AXTextField' and
                roles.get(tuple(path + [5])) == 'AXTextField' and
                roles.get(tuple(path + [9])) == 'AXSplitGroup'):
            candidates.append(path)
    if len(candidates) != 1:
        raise RuntimeError('native-ui-anchor-changed:chat-container-not-unique')
    new = candidates[0]
    for name, anchor in config['anchors'].items():
        if anchor['path'][:len(old)] != old:
            continue
        anchor['path'] = new + anchor['path'][len(old):]
        node = execute(root_path=anchor['path'], max_depth=0)['nodes'][0]
        if name == 'composer' and any(node.get(k) != v for k, v in anchor['expected'].items()):
            region = new + [9, 0]
            local = execute(root_path=region, max_depth=2)['nodes']
            roles = {tuple(n.get('path', [])): n.get('role') for n in local}
            inputs = [n for n in local if len(n.get('path', [])) == len(region) + 2
                      and n['path'][:len(region)] == region
                      and roles.get(tuple(n['path'][:-1])) == 'AXScrollArea'
                      and all(n.get(k) == v for k, v in anchor['expected'].items())]
            if len(inputs) != 1:
                raise RuntimeError('native-ui-anchor-changed:composer-not-unique')
            anchor['path'] = inputs[0]['path']
            node = execute(root_path=anchor['path'], max_depth=0)['nodes'][0]
        if any(node.get(k) != v for k, v in anchor['expected'].items()):
            raise RuntimeError('native-ui-anchor-changed:local-cache-validation-failed')
    temporary = SELECTORS.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(SELECTORS)

def named_action(kind, name, **extra):
    anchor = json.loads(SELECTORS.read_text(encoding='utf-8'))['anchors'][name]
    return {'type': kind, **anchor, **extra}

if __name__ == '__main__':
    print(json.dumps(execute(), ensure_ascii=False))
