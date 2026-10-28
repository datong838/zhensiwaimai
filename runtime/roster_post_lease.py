"""Maintenance holds original director post mutex; never steals a live owner."""
import contextlib
import json
import os
import re
from pathlib import Path
import run_all


def registered_group(group, physical_lock):
    posts = json.loads(Path(__file__).with_name('posts.json').read_text())['posts']
    candidates = ([posts[group]] if group in posts else
                  [post for post in posts.values() if post.get('mutexGroup') == group])
    if len(candidates) != 1:
        raise ValueError('maintenance-post-not-unique')
    post = candidates[0]
    port, canonical = post.get('port'), post.get('mutexGroup')
    if (type(port) is not int or port not in (9230, 9231, 9232, 9233)
            or not isinstance(canonical, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', canonical)):
        raise ValueError('maintenance-post-invalid')
    expected = ('/tmp/zhensi-jinsha-cua-exam.lock' if port == 9232
                else f'/tmp/zhensi-post-{port}.lock')
    if str(physical_lock) != expected:
        raise ValueError('maintenance-physical-lock-mismatch')
    return canonical


def assert_no_live_owner(path):
    path = Path(path)
    if not path.exists():
        return
    data = json.loads(path.read_text())
    pid = data.get('pid')
    if type(pid) is not int or pid <= 0:
        raise ValueError('post-owner-invalid')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    raise ValueError('post-live-owner-busy')


@contextlib.contextmanager
def original_post_lease(group, flow, physical_lock):
    group = registered_group(group, physical_lock)
    assert_no_live_owner(run_all.POST_GROUP_LOCK_DIR/(group+'.lock'))
    assert_no_live_owner(physical_lock)
    lease = run_all.acquire_post_group_lock(group, flow)
    if lease is None:
        raise ValueError('post-lease-busy')
    try:
        yield
    finally:
        run_all.release_post_group_lock(lease)
