"""Project-wide display quantization and configured upload headroom; no UI effects."""
import re
from decimal import Decimal

_PATTERN = re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*([KMG]?)(?:I?B)?', re.I)
_UNITS = {'':1, 'K':1024, 'M':1024**2, 'G':1024**3}

def displayed_size_matches(actual_bytes, display):
    if type(actual_bytes) is not int or actual_bytes < 0:
        return False
    match = _PATTERN.fullmatch(str(display).strip())
    if match is None:
        return False
    text, unit = match.groups()
    scale = Decimal(_UNITS[unit.upper()])
    decimals = len(text.partition('.')[2])
    quantum = scale / (10 ** decimals)
    return abs(Decimal(actual_bytes) - Decimal(text) * scale) < quantum

def safe_upload_budget(configured_limit_bytes):
    if type(configured_limit_bytes) is not int or configured_limit_bytes <= 0:
        raise ValueError('actual-upload-limit-required')
    return configured_limit_bytes * 95 // 100
