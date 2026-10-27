from pathlib import Path

from lib.wecom_config import ConfigError, namespace_dir, stable_key


def test_isolated_paths():
    root = Path('/tmp/root')
    a = namespace_dir(root, '上海臻肆文化传播有限公司', '临时测试群')
    b = namespace_dir(root, '其他企业微信', '临时测试群')
    assert a != b
    assert a == root / 'runs' / '上海臻肆文化传播有限公司' / '临时测试群'


def test_bad_name():
    try:
        stable_key('../逃逸')
    except ConfigError:
        return
    raise AssertionError('路径逃逸必须拒绝')


if __name__ == '__main__':
    test_isolated_paths()
    test_bad_name()
    print('ok')

