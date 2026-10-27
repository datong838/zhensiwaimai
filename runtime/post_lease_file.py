"""Serialized physical post lease mutations; no browser, business data or services."""
import errno
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import uuid


def alive(pid):
    if type(pid) is not int or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # EPERM or other uncertainty never authorizes takeover.
    return True


def read_owner(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        return {}  # Unreadable/symlink owner remains busy.
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return {}
        data = os.read(fd, 65537)
        if len(data) > 65536:
            return {}
        owner = json.loads(data)
        return owner if isinstance(owner, dict) else {}
    except (OSError, ValueError):
        return {}
    finally:
        os.close(fd)


def valid_time(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def publish_exclusive(path, payload):
    # Publish complete JSON atomically; a killed writer cannot leave an empty lease.
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            return False
        return True
    finally:
        Path(temporary).unlink(missing_ok=True)


def mutate(request):
    path = Path(request['path'])
    if not path.is_absolute() or request.get('operation') not in ('acquire', 'release'):
        raise ValueError('post-lease-request-invalid')
    try:
        guard = os.open(str(path) + '.guard', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except FileNotFoundError:
        if request['operation'] == 'release':
            return {'status': 'absent'}
        raise
    try:
        if not stat.S_ISREG(os.fstat(guard).st_mode):
            raise ValueError('post-lease-guard-invalid')
        until = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= until:
                    return {'status': 'busy', 'reason': 'guard-busy'}
                time.sleep(.01)
        existing = read_owner(path)
        if request['operation'] == 'release':
            if existing is None:
                return {'status': 'absent'}
            lease = request.get('lease')
            keys = ('runId', 'pid', 'acquiredAt', 'leaseId')
            if (not isinstance(lease, dict) or not existing.get('runId')
                    or type(existing.get('pid')) is not int or existing['pid'] <= 0
                    or not valid_time(existing.get('acquiredAt'))
                    or any(existing.get(key) != lease.get(key) for key in keys)):
                return {'status': 'mismatch'}
            path.unlink()
            return {'status': 'released'}
        run_id, pid = request.get('runId'), request.get('pid')
        if not isinstance(run_id, str) or not run_id or alive(pid) is not True:
            raise ValueError('post-lease-owner-invalid')
        if existing is not None:
            owner_alive = alive(existing.get('pid'))
            if owner_alive is not False:
                if (request.get('reentrant') is True and owner_alive is True
                        and existing.get('pid') == pid and existing.get('runId') == run_id
                        and valid_time(existing.get('acquiredAt'))):
                    return {'status': 'acquired', 'lease': existing}
                return {'status': 'busy', 'reason': 'owner-active-or-unconfirmed',
                        'ownerRunId': existing.get('runId') or 'unknown'}
            # Only ESRCH proves the old process has exited, independent of TTL.
            path.unlink()
        payload = {'runId': run_id, 'pid': pid, 'acquiredAt': time.time_ns() // 1_000_000,
                   'leaseId': str(uuid.uuid4())}
        if request.get('style') == 'post':
            payload['leasePath'] = str(path)
        if not publish_exclusive(path, payload):
            return {'status': 'busy', 'reason': 'exclusive-create-race'}
        return {'status': 'acquired', 'lease': payload}
    finally:
        os.close(guard)  # Kernel releases the guard even after process death.


if __name__ == '__main__':
    try:
        print(json.dumps(mutate(json.load(sys.stdin))))
    except Exception as error:
        print(json.dumps({'status': 'error', 'reason': str(error)}))
        raise SystemExit(1)
