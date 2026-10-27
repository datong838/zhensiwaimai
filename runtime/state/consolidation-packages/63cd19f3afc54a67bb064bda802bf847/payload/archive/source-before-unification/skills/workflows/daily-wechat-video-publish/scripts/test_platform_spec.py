"""三平台合同与调度。"""
from lib.platform_spec import (
    CHANNELS,
    KUAISHOU,
    overall_state,
    poi_allowed,
    resolve_platforms,
    should_skip_platform,
)
from workflow_executor import _bridge_script
from workflow_executor import _receipt_state


def test_resolve_platforms():
    assert resolve_platforms('all') == ('douyin', 'kuaishou', 'channels')
    assert resolve_platforms('kuaishou') == ('kuaishou',)
    assert resolve_platforms('channels') == ('channels',)


def test_channels_button_is_publish_alias_发表():
    assert CHANNELS.publish_button == '发表'
    assert KUAISHOU.publish_button == '发布'
    assert 'channels.weixin.qq.com' in CHANNELS.url_hint
    assert 'cp.kuaishou.com' in KUAISHOU.url_hint
    assert CHANNELS.upload_url.endswith('/platform/post/create')
    assert KUAISHOU.upload_url.endswith('/article/publish/video')
    assert CHANNELS.manage_url.endswith('/platform/post/list')
    assert KUAISHOU.manage_url.endswith('/article/manage')


def test_poi_forbids_baoshan_square():
    assert poi_allowed('红太阳鱼杂王·蜀湘川菜(杨浦保利店)', KUAISHOU)
    assert poi_allowed('辽阳路195号 B1-B106', CHANNELS)
    assert not poi_allowed('红太阳广场(宝山)', KUAISHOU)
    assert not poi_allowed('宝山红太阳广场', CHANNELS)


def test_overall_state():
    assert overall_state({'douyin': 'verified', 'kuaishou': 'verified', 'channels': 'verified'}) == 'verified'
    assert overall_state({'douyin': 'submitted', 'kuaishou': 'verified', 'channels': 'submitted'}) == 'submitted'
    assert overall_state({'kuaishou': 'verified'}) == 'submitted'
    assert overall_state({'douyin': 'verified'}) != 'verified'
    assert overall_state({'douyin': 'publish_unknown', 'kuaishou': 'verified', 'channels': 'verified'}) == 'publish_unknown'
    assert overall_state({'kuaishou': 'publish_pending'}) == 'publish_pending'
    assert overall_state({}) == 'prepared'


def test_skip_already_submitted():
    assert should_skip_platform('submitted')
    assert should_skip_platform('verified')
    assert not should_skip_platform('prepared')
    assert not should_skip_platform('publish_pending')
    assert not should_skip_platform('publish_unknown')


def test_pre_upload_failed_is_distinct_and_retryable():
    assert _receipt_state({'error': 'pre_upload_failed:file-dialog-missing'}) == 'pre_upload_failed'
    assert not should_skip_platform('pre_upload_failed')
    assert overall_state({'channels': 'pre_upload_failed'}) == 'pre_upload_failed'


def test_upload_requires_native_file_dialog_before_path_entry():
    import platform_chrome_bridge as bridge

    spec = CHANNELS
    button = object()
    pressed, picked = [], []
    original = {
        'prepare': bridge.cc.prepare_chrome,
        'goto': bridge.cc.goto,
        'web': bridge.chrome_ax.web_for_title,
        'walk': bridge.chrome_ax.walk,
        'press': bridge.chrome_ax.press,
        'wait_dialog': bridge.cc.wait_for_file_dialog,
        'pick': bridge.cc.pick_file_in_dialog,
    }
    try:
        bridge.cc.prepare_chrome = lambda _spec: ''
        bridge.cc.goto = lambda _url: None
        bridge.chrome_ax.web_for_title = lambda _titles: object()
        bridge.chrome_ax.walk = lambda _web, _pred: [button]
        bridge.chrome_ax.press = lambda target: pressed.append(target)
        bridge.cc.wait_for_file_dialog = lambda: False
        bridge.cc.pick_file_in_dialog = lambda *_args, **_kwargs: picked.append(True)
        try:
            bridge.upload_video(spec, __file__)
            assert False, '缺少文件框必须失败'
        except bridge.BridgeError as exc:
            assert str(exc) == 'pre_upload_failed:file-dialog-missing'
        assert pressed == [button]
        assert not picked
    finally:
        bridge.cc.prepare_chrome = original['prepare']
        bridge.cc.goto = original['goto']
        bridge.chrome_ax.web_for_title = original['web']
        bridge.chrome_ax.walk = original['walk']
        bridge.chrome_ax.press = original['press']
        bridge.cc.wait_for_file_dialog = original['wait_dialog']
        bridge.cc.pick_file_in_dialog = original['pick']


def test_bridge_scripts_exist():
    for name in ('douyin', 'kuaishou', 'channels'):
        path = _bridge_script(name)
        assert path.is_file(), path
        assert path.name == f'{name}_chrome_bridge.py'


def test_taobao_stow_bounds():
    from lib.platform_spec import TAOBAO_STOW_BOUNDS
    assert TAOBAO_STOW_BOUNDS == (1600, 25, 2400, 700)


if __name__ == '__main__':
    test_resolve_platforms()
    test_channels_button_is_publish_alias_发表()
    test_poi_forbids_baoshan_square()
    test_overall_state()
    test_skip_already_submitted()
    test_pre_upload_failed_is_distinct_and_retryable()
    test_upload_requires_native_file_dialog_before_path_entry()
    test_bridge_scripts_exist()
    test_taobao_stow_bounds()
    print('ok')
