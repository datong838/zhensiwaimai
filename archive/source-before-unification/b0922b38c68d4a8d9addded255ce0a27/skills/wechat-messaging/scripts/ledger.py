"""Durable event binding and cross-process claim; no business cursor writes."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from contract import Rejected, content_binding, digest, event_key


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        d = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else None


@contextmanager
def event_lock(root, request, *, rebind=False):
    directory = Path(root) / 'events' / event_key(request)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / '.lock').open('a+') as handle:
        os.chmod(handle.name, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Rejected('event-busy') from error
        try:
            binding = {'digest': digest(content_binding(request))}
            prior = read_json(directory / 'binding.json')
            if prior is not None and prior != binding:
                # 上游产物每轮重生成（xlsx 内嵌时间戳）导致内容摘要漂移是常态；
                # 调用方仅在对「从未发出」的事件重试时才允许 rebind（与桥层
                # never_sent 判据同源），attempted 事件仍拒绝，防换文件重发。
                if not rebind:
                    raise Rejected('event-payload-conflict')
                atomic_json(directory / 'binding.json', binding)
            if prior is None:
                atomic_json(directory / 'binding.json', binding)
            yield directory
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
