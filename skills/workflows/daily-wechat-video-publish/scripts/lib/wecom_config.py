"""企业微信运行参数与企业/群隔离路径。"""
from __future__ import annotations

import re
from pathlib import Path


class ConfigError(ValueError):
    pass


def require_name(value: str | None, label: str) -> str:
    value = (value or '').strip()
    if not value:
        raise ConfigError(f'{label}不能为空')
    if value in ('.', '..') or '/' in value or '\\' in value or '\x00' in value:
        raise ConfigError(f'{label}包含非法路径字符')
    return value


def stable_key(value: str) -> str:
    value = require_name(value, '名称')
    key = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff_-]+', '_', value).strip('_')
    if not key:
        raise ConfigError('名称不能生成有效隔离键')
    return key[:80]


def namespace_dir(root: Path, enterprise: str, group: str) -> Path:
    return root / 'runs' / stable_key(enterprise) / stable_key(group)


def state_dir(root: Path, enterprise: str, group: str) -> Path:
    return root / 'state' / stable_key(enterprise) / stable_key(group)

