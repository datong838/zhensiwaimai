"""Pure request/authorization contract. No UI imports or business dependencies."""
from __future__ import annotations
import hashlib
import json
import math
import time
from pathlib import Path

class Rejected(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def exact_keys(value, allowed, required):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise Rejected('contract-fields-invalid')


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise Rejected(name + '-invalid')
    return value


def timestamp(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise Rejected(name + '-invalid')
    return value


def normalize(request):
    exact_keys(request, ('schemaVersion', 'operation', 'groupName', 'items', 'context'),
               ('schemaVersion', 'groupName', 'items', 'context'))
    if type(request['schemaVersion']) is not int or request['schemaVersion'] != 1 or request.get('operation', 'send') != 'send':
        raise Rejected('unsupported-operation')
    group = nonempty(request['groupName'], 'group')
    if group != group.strip() or '\n' in group or '\r' in group:
        raise Rejected('group-invalid')
    context = request['context']
    fields = ('workflowId', 'eventId', 'accountAlias', 'channel', 'deadlineAt', 'searchGroupName')
    exact_keys(context, fields, fields[:-1])
    for key in fields[:4]:
        nonempty(context[key], key)
    if 'searchGroupName' in context:
        search_group = nonempty(context['searchGroupName'], 'search-group')
        if search_group != search_group.strip() or '\n' in search_group or '\r' in search_group:
            raise Rejected('search-group-invalid')
    if context['channel'] not in ('desktop', 'mobile'):
        raise Rejected('unsupported-channel')
    timestamp(context['deadlineAt'], 'deadline')
    if not isinstance(request['items'], list) or not 1 <= len(request['items']) <= 20:
        raise Rejected('items-count-invalid')
    items, seen = [], set()
    for original in request['items']:
        exact_keys(original, ('itemId', 'type', 'text', 'path'), ('itemId', 'type'))
        item_id = nonempty(original['itemId'], 'item-id')
        if item_id in seen:
            raise Rejected('duplicate-item-id')
        seen.add(item_id)
        kind = original['type']
        if kind not in ('text', 'image', 'file', 'video'):
            raise Rejected('unsupported-payload')
        item = {'itemId': item_id, 'type': kind}
        if kind == 'text':
            if 'path' in original:
                raise Rejected('text-with-path')
            value = nonempty(original.get('text'), 'text')
            if len(value) > 20000:
                raise Rejected('text-too-long')
            item.update(text=value, sha256=hashlib.sha256(value.encode()).hexdigest())
        else:
            if 'text' in original:
                raise Rejected('file-with-text')
            p = Path(nonempty(original.get('path'), 'path')).expanduser()
            if not p.is_absolute() or not p.is_file():
                raise Rejected('payload-file-missing')
            p = p.resolve()
            size = p.stat().st_size
            if not 0 < size <= 100 * 1024 * 1024:
                raise Rejected('payload-size-invalid')
            if kind == 'image':
                from PIL import Image
                with Image.open(p) as image:
                    image.verify()
            item.update(path=str(p), name=p.name, size=size, sha256=file_hash(p))
        items.append(item)
    return {'schemaVersion': 1, 'operation': 'send', 'groupName': group,
            'items': items, 'context': dict(context)}


def content_binding(request):
    # Paths, channel and deadlines are execution details, not business identity.
    return {'groupName': request['groupName'],
            'accountAlias': request['context']['accountAlias'],
            'items': [{k: v for k, v in item.items() if k != 'path'} for item in request['items']]}


def request_digest(request):
    return digest(content_binding(request) | {'context': request['context']})


def event_key(request):
    c = request['context']
    return digest([c['accountAlias'], request['groupName'], c['workflowId'], c['eventId']])


def item_key(request, item):
    return digest([event_key(request), item['itemId']])


def check_grant(request, grant, now=None, *, enforce_expiry=True):
    now = time.time() if now is None else now
    fields = ('schemaVersion', 'requestDigest', 'accountAlias', 'groupName', 'channel',
              'expiresAt', 'authorizationRef')
    exact_keys(grant, fields, fields)
    c = request['context']
    if type(grant['schemaVersion']) is not int or grant['schemaVersion'] != 1 or grant['requestDigest'] != request_digest(request):
        raise Rejected('authorization-content-mismatch')
    for k, expected in (('accountAlias', c['accountAlias']), ('groupName', request['groupName']),
                        ('channel', c['channel'])):
        if grant[k] != expected:
            raise Rejected('authorization-' + k + '-mismatch')
    nonempty(grant['authorizationRef'], 'authorization-reference')
    expiry = timestamp(grant['expiresAt'], 'authorization-expiry')
    if enforce_expiry and (not now < expiry or not now < c['deadlineAt']):
        raise Rejected('authorization-or-request-expired')
    return grant
