"""Conclude an original unknown image using two fresh native copy proofs. No UI."""
import argparse
import fcntl
import hashlib
import json
import re
import sys
from contextlib import ExitStack
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/wechat-messaging/scripts'))
from image_copy_readback import pixels
from ledger import atomic_json

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read(path):
    return json.loads(path.read_bytes())

def validate(marker, proof, proof_dir):
    source = marker.get('payloads', [])
    if (marker.get('state') != 'unknown' or marker.get('payloadType') != 'image'
            or len(source) != 1 or type(marker.get('sendAttempts')) is not int
            or marker['sendAttempts'] < 1):
        raise ValueError('not-original-unknown-image')
    if (proof.get('ok') is not True or proof.get('sendAttempts') != 0
            or proof.get('reconciledWithoutSend') is not True
            or proof.get('verificationLevel') != 'native-image-copy-pixels-exact-two-frame'
            or proof.get('source') != source[0] or proof.get('groupName') != marker['groupName']):
        raise ValueError('copy-proof-binding-mismatch')
    data = Path(source[0]['path']).read_bytes()
    if sha(data) != source[0]['sha256'] or len(data) != source[0]['size']:
        raise ValueError('source-content-changed')
    expected = pixels(data)
    if proof.get('sourcePixels') != expected or len(proof.get('frames', [])) != 2:
        raise ValueError('copy-proof-frames-invalid')
    nonces = set()
    for frame in proof['frames']:
        path = Path(frame['copiedFile'])
        if path.is_symlink() or path.resolve().parent != proof_dir.resolve():
            raise ValueError('copied-file-outside-proof-directory')
        copied = path.read_bytes()
        nonce = frame.get('clipboardNonceSha256', '')
        if (frame.get('verified') is not True or frame.get('groupBefore') != marker['groupName']
                or frame.get('groupAfter') != marker['groupName']
                or not re.fullmatch('[a-f0-9]{64}', nonce) or nonce in nonces
                or frame['changeCountAfter'] <= frame['changeCountBefore']
                or sha(copied) != frame['copiedEncodedSha256']
                or pixels(copied) != expected or frame.get('pixels') != expected):
            raise ValueError('fresh-native-copy-not-proven')
        nonces.add(nonce)
    return source[0]

def reconcile(proof_path, *, apply=False, root=ROOT.parent):
    proof_path, root = Path(proof_path).absolute(), Path(root).resolve()
    if proof_path.is_symlink() or not proof_path.resolve().is_relative_to(root):
        raise ValueError('unsafe-proof-path')
    proof = read(proof_path)
    marker = Path(proof['marker']).absolute()
    if marker.is_symlink() or not marker.resolve().is_relative_to(root):
        raise ValueError('unsafe-marker-path')
    prior_bytes = marker.read_bytes()
    prior = json.loads(prior_bytes)
    if sha(prior_bytes) != proof['markerSha256']:
        raise ValueError('original-marker-changed')
    key = prior.get('commonReceipt', {}).get('eventKey', '')
    if not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('missing-original-event')
    event = marker.parent / '.wechat-messaging/events' / key
    with ExitStack() as stack:
        for lock_path in [marker.with_suffix('.bridge.lock'), event / '.lock']:
            lock = stack.enter_context(lock_path.open('a+'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if marker.read_bytes() != prior_bytes:
            raise ValueError('marker-changed-under-lock')
        source = validate(prior, proof, proof_path.parent)
        binding = {'groupName': prior['groupName'], 'accountAlias': 'main-wechat',
                   'items': [{'itemId': '0', 'type': 'image', **{k: source[k] for k in ['name', 'size', 'sha256']}}]}
        digest = sha(json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
        if read(event / 'binding.json') != {'digest': digest}:
            raise ValueError('original-event-binding-mismatch')
        deliveries = list(event.glob('*/delivery.json'))
        if len(deliveries) != 1:
            raise ValueError('original-item-not-unique')
        delivery = deliveries[0]
        old_delivery = delivery.read_bytes()
        item = json.loads(old_delivery)
        if (item.get('status') != 'unknown' or item.get('type') != 'image'
                or item.get('sha256') != source['sha256'] or item.get('sendAttempts') != prior['sendAttempts']):
            raise ValueError('original-item-outcome-mismatch')
        result = {'ok': True, 'verified': True, 'applied': apply, 'sendAttempts': 0,
                  'newSendAttempts': 0, 'marker': str(marker), 'proof': str(proof_path)}
        if not apply:
            return result
        audit = marker.parent / 'native-copy-reconciliation' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        audit.mkdir(parents=True, mode=0o700)
        for name, data in [('original-marker.json', prior_bytes), ('original-delivery.json', old_delivery), ('copy-proof.json', proof_path.read_bytes())]:
            path = audit / name
            path.write_bytes(data)
            path.chmod(0o600)
        item.update(status='verified', reason=None, verificationLevel='image-content-match',
                    evidence={'nativeCopyProof': str(proof_path), 'verificationLevel': proof['verificationLevel'],
                              'frames': proof['frames'], 'reconciledWithoutSend': True})
        updated = {**prior, 'state': 'verified', 'ok': True, 'verified': True, 'reason': None,
                   'newSendAttempts': 0, 'reconciledWithoutSend': True, 'nativeCopyProof': str(proof_path)}
        updated['commonReceipt'] = {**prior['commonReceipt'], 'ok': True, 'status': 'verified', 'reason': None, 'items': [item]}
        try:
            atomic_json(delivery, item)
            atomic_json(marker, updated)
            atomic_json(audit / 'receipt.json', result)
        except Exception:
            atomic_json(delivery, json.loads(old_delivery))
            atomic_json(marker, prior)
            raise
        return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--proof', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(reconcile(args.proof, apply=args.apply), ensure_ascii=False))
