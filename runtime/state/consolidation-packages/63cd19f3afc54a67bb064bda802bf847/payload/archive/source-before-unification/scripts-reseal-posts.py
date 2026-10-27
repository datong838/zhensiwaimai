#!/usr/bin/env python3
# 重算 3 个 generated 岗位的 dependencies.json sha256（lease.mjs 修过 fs/promises 后重新钉死）。
# 只改 manifest 哈希，不动任何被钉文件内容。
import os, json, hashlib

BASE = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/posts'
POSTS = ['taobao-brand-post', 'taobao-svc-post', 'meituan-post']
FILES = ['SKILL.md', 'scripts/connect.mjs', 'scripts/lease.mjs', 'scripts/verify_dependencies.mjs']

for name in POSTS:
    pdir = os.path.join(BASE, name)
    manifest_path = os.path.join(pdir, 'dependencies.json')
    manifest = json.load(open(manifest_path, 'r', encoding='utf-8'))
    new_files = {}
    for rel in FILES:
        h = hashlib.sha256(open(os.path.join(pdir, rel), 'rb').read()).digest().hex()
        new_files[rel] = h
    manifest['files'] = new_files
    # 修正此前错误的 sealedAt 占位
    manifest['sealedAt'] = '2026-10-01T00:10+08:00'
    with open(manifest_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    print(f'{name}: resealed {len(new_files)} files')
print('done')
