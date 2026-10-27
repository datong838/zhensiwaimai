from pathlib import Path

from lib.wecom_media import MediaError, parse_attachments, select_exact_cache, ui_size_range


def _mp4(size: int, marker: bytes = b'a') -> bytes:
    head = b'\x00\x00\x00\x18ftypmp42' + marker
    return head + b'\x00' * (size - len(head))


def test_parse_and_size():
    rows = parse_attachments([
        'e2d103450815d38e8c3fcbb90a45167e.mp4\n1.50M',
        'e224b7ea677e328a4f20e1f13d44ebae.mp4 1.55 MB',
    ])
    assert [(x.filename, x.ui_size) for x in rows] == [
        ('e2d103450815d38e8c3fcbb90a45167e.mp4', '1.50MB'),
        ('e224b7ea677e328a4f20e1f13d44ebae.mp4', '1.55MB'),
    ]
    low, high = ui_size_range('1.50MB')
    assert low <= 1_576_196 <= high


def test_exact_cache_and_ambiguity(tmp_path: Path):
    root = tmp_path / 'Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/p/Caches/Files/2026-09'
    root.mkdir(parents=True)
    name = 'wanted.mp4'
    (root / name).write_bytes(_mp4(1_576_196))
    assert select_exact_cache(name, '1.50MB', home=tmp_path).name == name
    other = tmp_path / 'Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/q/Caches/Files/x'
    other.mkdir(parents=True)
    (other / name).write_bytes(_mp4(1_576_196, b'b'))
    try:
        select_exact_cache(name, '1.50MB', home=tmp_path)
    except MediaError as exc:
        assert '不唯一' in str(exc)
        return
    raise AssertionError('不同内容的同名缓存必须失败关闭')


if __name__ == '__main__':
    import tempfile
    test_parse_and_size()
    with tempfile.TemporaryDirectory() as directory:
        test_exact_cache_and_ambiguity(Path(directory))
    print('ok')
