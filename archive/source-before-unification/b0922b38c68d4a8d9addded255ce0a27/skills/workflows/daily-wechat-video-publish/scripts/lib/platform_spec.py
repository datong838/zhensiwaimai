"""平台发布合同：URL、按钮、本店 POI。

2026-09-30 岗位实体化：每个平台按约定独占一个端口（即独立 Chrome 实例的标识）。
抖音 9222 / 快手 9224 / 视频号 9225 / 小红书 9226。视频发布走 macOS 辅助功能(AX)树，
非 CDP；`port` 在物理上对应「一个以 --user-data-dir + --remote-debugging-port=PORT 单独
启动的 Chrome 实例」。三平台目前复用同一 Chrome（按 window_title 区分），每端口独立实例的
拉起命令已固化在 README，需在 GUI 环境（带 AX/TCC 授权）下执行，无头环境无法验证。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    port: int
    url_hint: str
    upload_url: str
    manage_url: str
    window_title: tuple[str, ...]
    publish_button: str
    upload_button: str
    poi_query: str
    poi_must: tuple[str, ...]
    poi_forbid: tuple[str, ...]
    edit_url_bits: tuple[str, ...]
    edit_text_bits: tuple[str, ...]
    implemented: bool = True


TAOBAO_STOW_BOUNDS = (1600, 25, 2400, 700)

DOUYIN = PlatformSpec(
    name='douyin',
    port=9222,
    url_hint='creator.douyin.com',
    upload_url='https://creator.douyin.com/creator-micro/content/upload',
    manage_url='https://creator.douyin.com/creator-micro/content/manage',
    window_title=('抖音', 'creator'),
    publish_button='发布',
    upload_button='上传视频',
    poi_query='红太阳鱼杂王杨浦保利店',
    poi_must=('红太阳鱼杂王(杨浦店)', '杨浦店'),
    poi_forbid=('宝山', '红太阳广场', '九亭'),
    edit_url_bits=('content/post/video', 'content/upload'),
    edit_text_bits=('作品描述',),
)

KUAISHOU = PlatformSpec(
    name='kuaishou',
    port=9224,
    url_hint='cp.kuaishou.com',
    upload_url='https://cp.kuaishou.com/article/publish/video',
    manage_url='https://cp.kuaishou.com/article/manage',
    window_title=('快手', 'kuaishou', 'Kuaishou'),
    publish_button='发布',
    upload_button='上传视频',
    poi_query='红太阳鱼杂王·蜀湘川菜',
    poi_must=('杨浦保利', '辽阳路195'),
    poi_forbid=('宝山', '红太阳广场'),
    edit_url_bits=('article/publish',),
    edit_text_bits=('作品描述', '添加位置', '标题'),
)

CHANNELS = PlatformSpec(
    name='channels',
    port=9225,
    url_hint='channels.weixin.qq.com',
    upload_url='https://channels.weixin.qq.com/platform/post/create',
    manage_url='https://channels.weixin.qq.com/platform/post/list',
    window_title=('视频号', 'channels'),
    publish_button='发表',
    upload_button='发表视频',
    poi_query='红太阳鱼杂王·蜀湘川菜',
    poi_must=('杨浦保利', '辽阳路195'),
    poi_forbid=('宝山', '红太阳广场'),
    edit_url_bits=('platform/post/create', 'platform/post'),
    edit_text_bits=('描述', '位置', '发表'),
)

XHS = PlatformSpec(
    name='xhs',
    port=9226,
    url_hint='creator.xiaohongshu.com',
    upload_url='https://creator.xiaohongshu.com/publish/publish',
    manage_url='https://creator.xiaohongshu.com/creator/home',
    window_title=('小红书', 'Xiaohongshu', 'RED'),
    publish_button='发布',
    upload_button='上传视频',
    poi_query='红太阳鱼杂王·蜀湘川菜',
    poi_must=('杨浦保利', '辽阳路195'),
    poi_forbid=('宝山', '红太阳广场'),
    edit_url_bits=('publish/publish',),
    edit_text_bits=('填写标题', '添加地点'),
    implemented=False,
)

SPECS = {'douyin': DOUYIN, 'kuaishou': KUAISHOU, 'channels': CHANNELS, 'xhs': XHS}
ALL_PLATFORMS = ('douyin', 'kuaishou', 'channels')
# 小红书端口已占位（9226），上线需先在 GUI 环境拉起其独立 Chrome 实例并补 bridge，故暂不纳入默认全集。
ALL_PLATFORMS_WITH_XHS = ('douyin', 'kuaishou', 'channels', 'xhs')


def resolve_platforms(name: str) -> tuple[str, ...]:
    if name in ('all', '', None):
        return ALL_PLATFORMS
    if name not in SPECS:
        raise ValueError(f'unknown-platform:{name}')
    return (name,)


def poi_allowed(text: str, spec: PlatformSpec) -> bool:
    if any(bad in text for bad in spec.poi_forbid):
        return False
    return any(good in text for good in spec.poi_must)


def should_skip_platform(prev_state: str) -> bool:
    return prev_state in ('submitted', 'verified')


def overall_state(platform_states: dict[str, str], required: tuple[str, ...] | None = None) -> str:
    """总 state 仅当 required 内全部 verified 才升 verified；缺平台不算完成。"""
    needed = required or ALL_PLATFORMS
    values = [platform_states.get(p, '') for p in needed]
    if any(v == 'publish_unknown' for v in values):
        return 'publish_unknown'
    if any(v == 'pre_upload_failed' for v in values):
        return 'pre_upload_failed'
    if all(v == 'verified' for v in values):
        return 'verified'
    filled = [v for v in values if v]
    if not filled:
        return 'prepared'
    if all(v in ('verified', 'submitted') for v in values):
        return 'submitted'
    if any(v == 'publish_pending' for v in values):
        return 'publish_pending'
    if any(v in ('submitted', 'verified') for v in values):
        return 'submitted'
    return filled[-1]
