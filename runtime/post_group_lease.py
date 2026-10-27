"""Original director group leases; lifetime ownership, serialized mutations."""
from contextlib import contextmanager
from datetime import datetime
import errno
import fcntl
import os
from pathlib import Path
import stat
import time
import uuid

from post_lease_file import alive, publish_exclusive, read_owner


@contextmanager
def mutation_guard(path):
    fd = os.open(str(path) + '.guard', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('group-lock-guard-invalid')
        until = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= until:
                    yield False
                    return
                time.sleep(.01)
        yield True
    finally:
        os.close(fd)


def acquire(directory, group, run_id):
    if (not isinstance(group, str) or not group or group in ('.', '..')
            or Path(group).name != group or not isinstance(run_id, str) or not run_id):
        raise ValueError('group-lock-owner-invalid')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (group + '.lock')
    with mutation_guard(path) as held:
        if not held:
            return None
        current = read_owner(path)
        if current is not None:
            if alive(current.get('pid')) is not False:
                return None
            path.unlink()
        owner = {'group': group, 'runId': run_id, 'pid': os.getpid(),
                 'acquiredAt': datetime.now().isoformat(timespec='seconds'),
                 'leaseId': str(uuid.uuid4())}
        if current is not None:
            owner['recovered'] = True
        if not publish_exclusive(path, owner):
            return None
        return {**owner, 'path': path}


def release(lease):
    if not isinstance(lease, dict) or not lease.get('path'):
        return
    path = Path(lease['path'])
    try:
        with mutation_guard(path) as held:
            if not held:
                return
            current = read_owner(path)
            keys = ('group', 'runId', 'pid', 'acquiredAt', 'leaseId')
            if (not current or not isinstance(current.get('leaseId'), str)
                    or not current['leaseId'] or type(current.get('pid')) is not int
                    or current['pid'] != os.getpid() or not current.get('acquiredAt')
                    or any(current.get(key) != lease.get(key) for key in keys)):
                return
            path.unlink()
    except (OSError, ValueError):
        return  # Missing or mismatched ownership never authorizes deletion.
