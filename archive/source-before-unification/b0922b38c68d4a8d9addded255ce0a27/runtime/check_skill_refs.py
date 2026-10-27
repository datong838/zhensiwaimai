#!/usr/bin/env python3
"""技能引用后置检查（搬迁/重构后必跑）。

扫描 skills/workflows 与 skills/posts 下所有 .mjs/.js/.py，解析：
  1) JS 相对 import/require/export-from 的路径是否真实存在；
  2) Python `Path(__file__)...parents[N] / "..."` 解析目标是否存在；
  3) 间接基准（如 THIS_DIR.parents[N]）标注出来供人工确认。
退出码：0=无 MISS，1=有 MISS。

用法：
  env -u PYTHONPATH python3 runtime/check_skill_refs.py
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = [ROOT / 'skills' / 'workflows', ROOT / 'skills' / 'posts']
JS_EXT = {'.mjs', '.js', '.cjs'}
PY_EXT = {'.py'}

RE_JS = [
    re.compile(r"""\bfrom\s+['"](\.[^'"]+)['"]"""),
    re.compile(r"""\bimport\s*\(\s*['"](\.[^'"]+)['"]\s*\)"""),
    re.compile(r"""\brequire\s*\(\s*['"](\.[^'"]+)['"]\s*\)"""),
    re.compile(r"""\bimport\s+['"](\.[^'"]+)['"]"""),
]


def _rel(p):
    try:
        return str(Path(p).relative_to(ROOT))
    except ValueError:
        return str(p)


def resolve_js(base, spec):
    p = base / spec
    cands = [p]
    if not p.suffix:
        cands = [Path(str(p) + e) for e in ('.mjs', '.js', '.cjs', '.json')] + [
            p / 'index.mjs', p / 'index.js']
    for c in cands:
        if c.exists():
            return True, c
    return False, p


def main():
    miss = []
    manual = []
    checked = 0
    for scan in SCAN:
        if not scan.exists():
            continue
        for f in sorted(scan.rglob('*')):
            if not f.is_file():
                continue
            if f.suffix in JS_EXT:
                txt = f.read_text(errors='replace')
                for rx in RE_JS:
                    for m in rx.finditer(txt):
                        spec = m.group(1)
                        checked += 1
                        ok, resolved = resolve_js(f.parent, spec)
                        if not ok:
                            line = txt[:m.start()].count('\n') + 1
                            miss.append((_rel(f), line, 'JS', spec, _rel(resolved)))
            elif f.suffix in PY_EXT:
                txt = f.read_text(errors='replace')
                lines = txt.split('\n')
                for i, ln in enumerate(lines, 1):
                    pat = r"""(__file__)\)?\.resolve\(\)\.parents\[(\d+)\]((?:\s*/\s*["'][^"']+["'])*)"""
                    for m in re.finditer(pat, ln):
                        n = int(m.group(2))
                        segs = re.findall(r"""["']([^"']+)["']""", m.group(3))
                        base = f.parent
                        for _ in range(n):
                            base = base.parent
                        target = base
                        for s in segs:
                            target = target / s
                        checked += 1
                        if segs and not target.exists():
                            miss.append((_rel(f), i, f'PY parents[{n}]', '/'.join(segs), _rel(target)))
                    if 'parents[' in ln and '__file__' not in ln:
                        m = re.search(r"""parents\[(\d+)\]((?:\s*/\s*["'][^"']+["'])*)""", ln)
                        if m and m.group(2).strip():
                            checked += 1
                            manual.append((_rel(f), i,
                                           'PY parents[%s] (间接基准·待人工)' % m.group(1),
                                           m.group(2).strip(), ''))

    print(f'checked={checked}  MISS={len(miss)}  MANUAL={len(manual)}')
    for f, line, kind, spec, resolved in miss:
        print(f'  [{kind}] {f}:{line}  spec={spec}  ->  {resolved}')
    for f, line, kind, spec, resolved in manual:
        print(f'  (人工) [{kind}] {f}:{line}  spec={spec}')
    return 1 if miss else 0


if __name__ == '__main__':
    sys.exit(main())
