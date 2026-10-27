"""Maintenance holds original director post mutex; never steals a live owner."""
import contextlib
import json
import os
from pathlib import Path
import run_all


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
    assert_no_live_owner(run_all.POST_GROUP_LOCK_DIR/(group+'.lock'))
    assert_no_live_owner(physical_lock)
    lease = run_all.acquire_post_group_lock(group, flow)
    if lease is None:
        raise ValueError('post-lease-busy')
    try:
        yield
    finally:
        run_all.release_post_group_lock(lease)
