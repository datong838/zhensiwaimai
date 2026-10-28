"""Original-worker content driver. No CLI, send, or ledger writer."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


class CopyDriver:
    def __init__(self, folder, task, *, queue, native, owner_check, pasteboard=None,
                 runner=subprocess.run, worker_pid=None):
        self.folder = Path(folder).resolve()
        self.queue = Path(queue).resolve()
        self.task = json.loads(json.dumps(task))
        self.native = native
        self.owner_check = owner_check
        self._pasteboard = pasteboard
        self.runner = runner
        self.worker_pid = os.getpid() if worker_pid is None else worker_pid
        self.seed_count = None
        self.copy_confirmed = False

    def owner_active(self, owner):
        return self.owner_check(owner)

    def intent_matches(self, task_id, binding, digest):
        try:
            if (self.folder.parent != self.queue or self.folder.name != task_id
                    or self.task.get('taskId') != task_id
                    or self.task.get('lifetime') != 'owner-process'
                    or self.task.get('owner', {}).get('pid') != self.worker_pid
                    or self.owner_active(self.task['owner']) is not True
                    or (self.folder / 'response.json').exists()):
                return False
            names = ('task.json', 'claim.json', 'send-intent.json')
            paths = [self.folder / n for n in names]
            if any(p.is_symlink() or not p.is_file() for p in paths):
                return False
            task, claim, intent = [json.loads(p.read_text()) for p in paths]
            bare = {k: v for k, v in task.items() if k != 'binding'}
            actual = hashlib.sha256(json.dumps(bare, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            return (task == self.task and task.get('stage') == 'send'
                    and task.get('item', {}).get('type') == 'image'
                    and actual == binding == task.get('binding')
                    and digest == task['item']['sha256']
                    and claim.get('worker') == 'native-system-ui-post'
                    and all(intent.get(k) == v for k, v in
                            {'taskId': task_id, 'binding': binding, 'sha256': digest,
                             'backend': 'system-events-ui-tree'}.items()))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def guard(self):
        t = self.task
        if not self.intent_matches(t['taskId'], t['binding'], t['item']['sha256']):
            raise RuntimeError('candidate-original-intent-mismatch')

    def read_source(self):
        return Path(self.task['item']['path']).read_bytes()

    def snapshot(self):
        self.guard()
        tree, values = self.native.read_anchors('conversationTitle', 'composer', 'messages')
        selectors = json.loads(self.native.SELECTORS.read_text())['anchors']
        rows = [n['path'] for n in self.native.execute(
            root_path=selectors['messages']['path'], max_depth=1)['nodes'] if n['role'] == 'AXRow']
        if not rows:
            raise RuntimeError('candidate-no-message-row')
        local = self.native.execute(root_path=rows[-1], max_depth=3)
        nodes = local['nodes']
        cells = [n for n in nodes if n.get('path') == rows[-1] + [0]]
        # Text/file cards and meeting cards cannot pass on icon/row shape alone.
        file_card = any(n.get('role') in ('AXTextArea', 'AXTextField')
                        and n.get('value') for n in nodes)
        self.paths = {key: selectors[name]['path'] for key, name in
                      [('messagesPath', 'messages'), ('titlePath', 'conversationTitle'),
                       ('composerPath', 'composer')]}
        self.guard()
        return {'groupName': values['conversationTitle']['value'],
                'inputEmpty': values['composer']['value'] == '',
                'frontmost': tree.get('frontmost') is True and local.get('frontmost') is True,
                'rowCount': len(rows), 'rowPath': rows[-1],
                'cellRole': cells[0]['role'] if len(cells) == 1 else None,
                'fileCard': file_card}

    def pb(self):
        if self._pasteboard is None:
            from AppKit import NSPasteboard
            self._pasteboard = NSPasteboard.generalPasteboard()
        return self._pasteboard

    def seed_nonce(self, nonce):
        self.guard()
        if not isinstance(nonce, str) or not nonce.startswith('zhensi-image-readback-'):
            raise ValueError('candidate-nonce-invalid')
        pb = self.pb()
        self.copy_confirmed = False
        pb.clearContents()
        if not pb.setString_forType_(nonce, 'public.utf8-plain-text'):
            raise RuntimeError('candidate-nonce-write-failed')
        self.seed_count = int(pb.changeCount())
        return self.seed_count

    def copy_image(self, row, group):
        self.guard()
        self.copy_confirmed = False
        if self.seed_count is None or group != self.task['request']['groupName']:
            raise RuntimeError('candidate-copy-sequence-invalid')
        payload = {**self.paths, 'rowPath': row, 'groupName': group}
        script = Path(__file__).with_name('native_image_content.jxa')
        try:
            result = self.runner(['/usr/bin/osascript', '-l', 'JavaScript', str(script),
                                  json.dumps(payload, ensure_ascii=False)],
                                 capture_output=True, text=True, check=True, timeout=15)
        except subprocess.CalledProcessError as error:
            detail = error.stderr or ''
            if isinstance(detail, bytes):
                detail = detail.decode('utf-8', errors='replace')
            detail = ' '.join(str(detail).split())[:1000]
            raise RuntimeError('candidate-copy-ui-failed:exit=%s:stderr=%s' %
                               (error.returncode, detail or 'unavailable')) from error
        action = json.loads(result.stdout)
        self.guard()
        self.copy_confirmed = (action.get('copied') is True
                               and action.get('backend') == 'system-events-ui-tree'
                               and action.get('rowPath') == row)
        return action

    def clipboard_image(self):
        self.guard()
        pb = self.pb()
        count = int(pb.changeCount())
        if not self.copy_confirmed or self.seed_count is None or count <= self.seed_count:
            raise RuntimeError('candidate-copy-not-fresh-image')
        self.copy_confirmed = False  # Each successful copy permits only one bounded image read.
        for kind in ('public.png', 'public.tiff', 'NeXT TIFF v4.0 pasteboard type'):
            data = pb.dataForType_(kind)
            if data is not None:
                raw = bytes(data)
                if int(pb.changeCount()) != count:
                    raise RuntimeError('candidate-clipboard-changed-during-read')
                self.guard()
                return {'type': kind, 'changeCount': count, 'data': raw}
        raise RuntimeError('candidate-copy-not-image')
