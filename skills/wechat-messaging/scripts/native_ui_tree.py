"""Native System Events UI tree. No screen-capture or CUA dependency."""
import json
import subprocess
from pathlib import Path
SCRIPT = Path(__file__).with_suffix('.jxa')
SELECTORS = SCRIPT.parents[1] / 'config/native-ui-selectors.json'
ALLOWED = {'activate', 'click', 'key', 'paste'}
KEYS = {'return','escape','down','up','tab','backspace','search','goto','selectall'}

def execute(actions=(), *, max_depth=2, root_path=()):
    for action in actions:
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
    payload = json.dumps({'actions': list(actions), 'maxDepth': max_depth, 'rootPath': list(root_path)}, ensure_ascii=False)
    result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', str(SCRIPT), payload],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'native-ui-failed')
    return json.loads(result.stdout)

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
    for anchor in config['anchors'].values():
        if anchor['path'][:len(old)] != old:
            continue
        anchor['path'] = new + anchor['path'][len(old):]
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
