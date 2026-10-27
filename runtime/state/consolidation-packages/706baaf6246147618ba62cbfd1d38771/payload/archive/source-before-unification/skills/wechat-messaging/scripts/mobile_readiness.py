"""Explicit-device read-only probe. Never starts, restarts or sends to WeChat."""
import hashlib
import shutil
import subprocess
from contract import Rejected


def probe(serial, user_id=0):
    if not serial or user_id not in (0,128):
        raise Rejected('mobile-instance-required')
    adb = shutil.which('adb')
    if not adb:
        raise Rejected('adb-missing')
    def call(*args):
        p = subprocess.run([adb, '-s', serial, *args], capture_output=True, timeout=8)
        if p.returncode:
            raise Rejected('mobile-probe-failed')
        return p.stdout
    if call('get-state').strip() != b'device':
        raise Rejected('mobile-device-not-ready')
    emulator = call('shell','getprop','ro.kernel.qemu').strip() == b'1'
    if emulator:
        raise Rejected('physical-device-required')
    image = call('exec-out','screencap','-p')
    if not image.startswith(b'\x89PNG\r\n\x1a\n'):
        raise Rejected('mobile-capture-invalid')
    processes = call('shell','ps','-A','-o','USER,PID,NAME').decode()
    import re
    active = bool(re.search(rf'^u{user_id}_a\d+\s+\d+\s+com\.tencent\.mm$', processes, re.M))
    return {'ok': active, 'deviceHash': hashlib.sha256(serial.encode()).hexdigest()[:12],
            'userId': user_id, 'processPresent': active, 'screenshotAvailable': True,
            'loginVerified': False, 'groupVerified': False, 'sendAttempts': 0}
