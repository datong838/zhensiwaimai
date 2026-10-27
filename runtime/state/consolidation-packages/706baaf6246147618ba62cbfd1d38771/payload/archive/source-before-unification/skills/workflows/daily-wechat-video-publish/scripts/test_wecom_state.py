import json
from pathlib import Path

from wecom_download import download_pending


def test_completed_download_is_idempotent(tmp_path: Path):
    run = tmp_path / 'runs' / '企业甲' / '群甲' / '20260909-01'
    (run / 'videos').mkdir(parents=True)
    video = run / 'videos' / 'one.mov'
    video.write_bytes(b'complete')
    (run / 'run.json').write_text(json.dumps({
        'runId': '20260909-01',
        'enterprise': '企业甲',
        'group': '群甲',
        'source': {'type': 'wecom_desktop', 'expectedCount': 1},
    }, ensure_ascii=False), encoding='utf-8')
    (run / 'candidates.jsonl').write_text(json.dumps({
        'source': {'kind': 'native_video', 'messageTime': '2026-09-09T12:50:00+08:00'},
        'state': 'human_review_pending',
        'localFile': str(video),
        'sha256': 'abc',
    }, ensure_ascii=False) + '\n', encoding='utf-8')
    (run / 'timeline.jsonl').touch()
    result = download_pending(run)
    assert result['ok'] is True
    assert result['downloaded'] == 1
    assert result['downloadedThisCall'] == 0
    assert result['cursor'] == '2026-09-09T12:50:00+08:00'
    checkpoint = tmp_path / 'state' / '企业甲' / '群甲' / 'checkpoint.json'
    assert json.loads(checkpoint.read_text(encoding='utf-8'))['lastMessageTime'] == result['cursor']
    row = json.loads((run / 'candidates.jsonl').read_text(encoding='utf-8'))
    row['state'] = 'prepared'
    (run / 'candidates.jsonl').write_text(json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8')
    assert download_pending(run)['ok'] is True


if __name__ == '__main__':
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        test_completed_download_is_idempotent(Path(directory))
    print('ok')
