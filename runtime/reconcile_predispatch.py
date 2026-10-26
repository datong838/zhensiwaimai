#!/usr/bin/env python3
"""Reconcile proven pre-dispatch state locally; never imports a UI/sender.

Only two narrow cases are supported. All original bytes are retained.
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from business_storage import business_path, catalog, internal_path


def feedback_ledger(root=ROOT):
    active = business_path('negative-feedback', root=root)
    expected = internal_path(root, catalog(root)['negative-feedback']['target'])
    if Path(active).resolve() != expected.resolve():
        raise ValueError('business-storage-not-activated')
    return expected / 'wechat-attempts'


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def zero(value):
    return (value.get('state', value.get('status')) == 'blocked'
            and type(value.get('sendAttempts')) is int and value['sendAttempts'] == 0
            and value.get('verified') is not True and value.get('attempted') is not True
            and value.get('unknown') is not True
            and value.get('physicalSendAttempts', 0) == 0)


def check(marker, source, event, mode, *, business_root=ROOT):
    prior, receipt = read(marker), read(source)
    if (prior.get('groupName') != receipt.get('groupName')
            or prior.get('payloads') != receipt.get('payloads')
            or receipt.get('attemptMarker') != str(marker)):
        raise ValueError('receipt-binding-mismatch')
    payloads = prior.get('payloads', [])
    feedback_pair = (prior.get('payloadType') == 'file' and len(payloads) == 2
                     and marker.parent.resolve() == feedback_ledger(business_root).resolve())
    if prior.get('payloadType') not in ('image', 'file') or not (len(payloads) == 1 or feedback_pair):
        raise ValueError('unsupported-reconciliation-scope')
    binding = {'groupName': prior['groupName'], 'accountAlias': 'main-wechat',
               'items': [{'itemId': str(index), 'type': prior['payloadType'],
                          **{k: payload[k] for k in ('name', 'size', 'sha256')}}
                         for index, payload in enumerate(payloads)]}
    expected = hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest()
    if read(event / 'binding.json') != {'digest': expected}:
        raise ValueError('event-binding-mismatch')
    deliveries = list(event.glob('*/delivery.json'))
    if mode == 'interrupted-preflight':
        if (set(prior) != {'bridgeVersion', 'state', 'groupName', 'payloadType',
                          'payloads', 'sendAttempts', 'verified'}
                or prior['bridgeVersion'] != 1 or prior['state'] != 'attempted'
                or prior['sendAttempts'] is not None or prior['verified'] is not False):
            raise ValueError('not-initial-bridge-claim')
        common = receipt.get('commonReceipt') or {}
        if not zero(receipt) or common.get('status') != 'blocked' or common.get('items') != []:
            raise ValueError('no-prior-zero-preflight-proof')
        # This journal is fsynced before send_one. Its absence here is the
        # required engine-level evidence, not an inference from an empty UI.
        if deliveries or any(event.glob('*/transport')):
            raise ValueError('item-dispatch-evidence-present')
        return prior, receipt, []
    if not zero(prior) or not deliveries:
        raise ValueError('not-proven-blocked-zero')
    directories = []
    for delivery in deliveries:
        item = read(delivery)
        transport = item.get('transport') or {}
        if (not zero(item) or transport.get('sent') is not False
                or type(transport.get('sendAttempts')) is not int
                or transport['sendAttempts'] != 0):
            raise ValueError('nonzero-or-unknown-item-dispatch')
        keys = sum(len(step.get('send_attempts') or [])
                   for step in (transport.get('receipt') or {}).get('steps', []))
        if mode == 'post-send-unknown' and not keys:
            raise ValueError('no-recorded-send-keys')
        if mode != 'post-send-unknown' and keys:
            raise ValueError('send-keys-already-issued')
        directories.append(delivery.parent)
    return prior, receipt, directories


def reconcile(marker, source, mode, *, apply=False, root=ROOT, business_root=ROOT):
    marker, source, root = Path(marker).absolute(), Path(source).absolute(), Path(root).resolve()
    if marker.is_symlink() or source.is_symlink() or not marker.resolve().is_relative_to(root):
        raise ValueError('unsafe-marker-path')
    receipt = read(source)
    key = (receipt.get('commonReceipt') or {}).get('eventKey', '')
    if not re.fullmatch('[0-9a-f]{64}', key):
        raise ValueError('missing-event-identity')
    event = marker.parent / '.wechat-messaging' / 'events' / key
    if not event.is_dir() or event.is_symlink() or not (event / 'binding.json').is_file():
        raise ValueError('event-journal-unavailable')
    with ExitStack() as stack:
        for path in [marker.with_suffix('.bridge.lock'), event / '.lock']:
            handle = stack.enter_context(path.open('a+'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prior, receipt, directories = check(marker, source, event, mode,
                                            business_root=business_root)
        proof = {'ok': True, 'mode': mode, 'applied': apply, 'sendAttempts': 0,
                 'marker': str(marker), 'sourceReceipt': str(source),
                 'markerSha256': sha(marker), 'sourceReceiptSha256': sha(source),
                 'eventKey': key, 'eventBindingSha256': sha(event / 'binding.json'),
                 'archivedItems': [p.name for p in directories]}
        if not apply:
            return proof
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        audit = marker.parent / 'predispatch-reconciliation' / stamp
        audit.mkdir(parents=True, mode=0o700)
        (audit / 'original-marker.json').write_bytes(marker.read_bytes())
        (audit / 'source-receipt.json').write_bytes(source.read_bytes())
        for path in audit.iterdir():
            path.chmod(0o600)
        archived = []
        try:
            if mode == 'post-send-unknown':
                total = 0
                for directory in directories:
                    item = read(directory / 'delivery.json')
                    (audit / (directory.name + '.delivery.json')).write_bytes((directory / 'delivery.json').read_bytes())
                    keys = sum(len(step.get('send_attempts') or [])
                               for step in item['transport']['receipt'].get('steps', []))
                    total += keys
                    item.update(status='unknown', sendAttempts=keys,
                                reason='send-keys-issued-outcome-unconfirmed')
                    item['transport'].update(sendAttempts=keys, sent=None)
                    temporary = directory / '.delivery-reconciled.tmp'
                    temporary.write_text(json.dumps(item, ensure_ascii=False, indent=2))
                    temporary.chmod(0o600)
                    temporary.replace(directory / 'delivery.json')
                result = {**prior, 'state': 'unknown', 'sendAttempts': total,
                          'physicalSendAttempts': total, 'newSendAttempts': total,
                          'reason': 'send-keys-issued-outcome-unconfirmed',
                          'predispatchReconciliation': str(audit / 'proof.json')}
                result['commonReceipt'] = {**prior.get('commonReceipt', {}), 'ok': False,
                                          'status': 'unknown',
                                          'items': [read(p / 'delivery.json') for p in directories]}
                temporary = marker.with_name('.' + marker.name + '.reconciled.tmp')
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                temporary.chmod(0o600)
                temporary.replace(marker)
                directories = []
            for directory in directories:
                destination = audit / directory.name
                directory.rename(destination)
                archived.append((directory, destination))
            if mode == 'interrupted-preflight':
                result = {**prior, 'state': 'blocked', 'sendAttempts': 0,
                          'newSendAttempts': 0, 'reason': 'interrupted-before-item-dispatch',
                          'predispatchReconciliation': str(audit / 'proof.json')}
                temp = marker.with_name('.' + marker.name + '.predispatch.tmp')
                with temp.open('x') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    json.dump(result, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                temp.replace(marker)
            (audit / 'proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2))
            (audit / 'proof.json').chmod(0o600)
        except Exception:
            for directory, destination in reversed(archived):
                destination.rename(directory)
            if mode == 'interrupted-preflight':
                marker.write_bytes((audit / 'original-marker.json').read_bytes())
            raise
        return proof | {'proof': str(audit / 'proof.json')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--marker', required=True)
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--mode', choices=['interrupted-preflight', 'blocked-zero-refreeze', 'post-send-unknown'], required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(reconcile(args.marker, args.receipt, args.mode, apply=args.apply), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'reason': str(error), 'sendAttempts': 0}, ensure_ascii=False))
        raise SystemExit(1)
