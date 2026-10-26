"""Resolve business-owned data roots; migration activation is explicit and read-only here."""
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAYOUT = 'runtime/state/storage-layout-v1.json'


def internal_path(root, relative):
    root = Path(root).resolve()
    value = Path(relative)
    if value.is_absolute() or not value.parts or '..' in value.parts:
        raise ValueError('storage-relative-path-invalid')
    target = root / value
    if target.resolve() != target or not target.is_relative_to(root):
        raise ValueError('storage-path-symlink-or-escape')
    return target


def catalog(root=REPO_ROOT):
    data = json.loads((Path(root) / 'runtime/business_storage_catalog.json').read_text())
    if data.get('schemaVersion') != 1 or not isinstance(data.get('objects'), dict):
        raise ValueError('storage-catalog-invalid')
    for item in data['objects'].values():
        if not Path(item['legacy']).is_absolute():
            raise ValueError('storage-legacy-path-invalid')
        internal_path(root, item['target'])
    return data['objects']


def business_path(key, *, root=REPO_ROOT):
    root = Path(root).resolve()
    objects = catalog(root)
    if key not in objects:
        raise ValueError('storage-key-unknown:' + key)
    item = objects[key]
    path = internal_path(root, LAYOUT)
    if not path.exists():
        return Path(item['legacy'])
    state = json.loads(path.read_text())
    if state.get('schemaVersion') != 1 or state.get('root') != str(root):
        raise ValueError('storage-layout-binding-invalid')
    active = state.get('objects', {}).get(key)
    if active is None:
        return Path(item['legacy'])
    if active.get('target') != item['target']:
        raise ValueError('storage-target-binding-invalid')
    proof_file = internal_path(root, active['proof'])
    proof_bytes = proof_file.read_bytes()
    proof = json.loads(proof_bytes)
    if (hashlib.sha256(proof_bytes).hexdigest() != active['proofSha256']
            or proof.get('phase') != 'activated' or proof.get('root') != str(root)
            or proof.get('id') != active['migrationId']
            or proof.get('objects', {}).get(key, {}).get('target') != item['target']):
        raise ValueError('storage-activation-proof-invalid')
    target = internal_path(root, item['target'])
    if not target.is_dir():
        raise ValueError('storage-active-target-missing')
    return target
