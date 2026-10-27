# -*- coding: utf-8 -*-
"""F10-2 · 文件气泡文件名提取器（纯函数，无 Windows 依赖）

背景（2026-10-07）：
  驱动 read_messages 对文件类消息只回 "[文件]" 占位符，文件类发送（如每日台账 xlsx）
  的核验只能靠「时刻+气泡+上传路径」三联间接证据，做不到文件名级锚点。
  本模块给 Windows 真身驱动的 read 层用：从消息区控件提取文件名，拼进消息文本。

设计约束（与消费方的兼容契约）：
  1. 消费方 windows_adapter.py `_anchor_newness` 是**子串匹配**（needle in flattened），
     现役文件锚点是 '[文件]'。⇒ 增强形态必须**保留 '[文件]' 前缀**，例如：
       '[文件] 2026-10-07臻肆工作台账.xlsx'
     这样新旧消费方都命中（旧锚点 '[文件]' 仍是子串）。
  2. fail-soft：任何提取失败/形态不识别 → 返回 None，调用方回退原文本，绝不抛异常
     （取证增强不能成为 read 链路的故障源）。
  3. 纯函数：不 import uiautomation、不碰窗口、无 IO——可在 Mac 侧完整自测。

已知/假设的消息形态（驱动 read 层实际产出以明早取回 Windows 真身为准，逐条校准）：
  A. '[文件]'                          —— 现役形态（21:18 台账回读实证），无文件名
  B. '[文件] 名字.xlsx'                 —— 目标形态①：同控件 Name 含文件名
  C. '[文件:名字.xlsx]'                 —— 目标形态②：占位符带参
  D. dump_tree 行："[ListItemControl] name='名字.xlsx' cls=..." —— 树行形态（明早重 dump 校准）
  E. '[图片]' / '[图片]xxx.png'          —— 图片类，同样适用（send_file 的 auto=image 路径）
"""
import re

# 现役占位符（驱动侧硬编码，见 2026-10-07 21:18 回读实证）
FILE_PLACEHOLDER = '[文件]'
IMAGE_PLACEHOLDER = '[图片]'

# 文件名启发式：含扩展名且不像纯时间戳/普通话术。
# 扩展名白名单对齐业务实际发送物（xlsx/docx/pdf/zip/png 等），避免把普通文本误判成文件名。
_EXT_RE = re.compile(
    r'[\w\u4e00-\u9fff][\w\u4e00-\u9fff ()（）\[\]【】.-]*'
    r'\.(xlsx|xls|docx|doc|pdf|zip|rar|7z|csv|txt|png|jpg|jpeg|gif|bmp|webp|pptx|ppt)\b',
    re.IGNORECASE,
)
# 形态 C：占位符带参 '[文件:xxx]' / '[图片:xxx]'
_PARAM_RE = re.compile(r'^\[(文件|图片)[:：]\s*(.+?)\]\s*$')
# 树行形态 D：name='...' 里直接就是文件名
_DUMP_NAME_RE = re.compile(r"name='([^']+)'")
_DUMP_LINE_RE = re.compile(r'^\s*\[.*Control\]')


def _looks_like_filename(text):
    """启发式：文本中是否含像文件名的片段（有扩展名、非纯时间戳）。"""
    if not text:
        return None
    hit = _EXT_RE.search(text)
    return hit.group(0).strip() if hit else None


def extract_from_message_text(message_text):
    """从 read_messages 的单条消息文本提取文件名。

    返回：文件名 str；不是文件类或提取不到 → None（调用方回退原文本）。
    """
    if not message_text:
        return None
    text = str(message_text).strip()

    # 形态 C：'[文件:名字]' —— 占位符带参，最显式
    m = _PARAM_RE.match(text)
    if m:
        name = m.group(2).strip()
        return name or None

    # 形态 A/B：'[文件]' / '[文件] 名字.xlsx' / '[图片] xxx.png'
    if text.startswith(FILE_PLACEHOLDER) or text.startswith(IMAGE_PLACEHOLDER):
        rest = text[len(FILE_PLACEHOLDER):] if text.startswith(FILE_PLACEHOLDER) \
            else text[len(IMAGE_PLACEHOLDER):]
        return _looks_like_filename(rest)  # A → None，B → 文件名

    return None


def extract_from_dump_line(line):
    """从 dump_tree 的单行控件描述提取文件名（形态 D）。

    输入形如： "[ListItemControl] name='2026-10-07臻肆工作台账.xlsx' cls='...' id='...'"
    返回：文件名 str；非控件行 / name 不是文件名 → None。
    """
    if not line or not _DUMP_LINE_RE.match(line):
        return None
    m = _DUMP_NAME_RE.search(line)
    if not m:
        return None
    return _looks_like_filename(m.group(1))


def enrich(message_text, filename):
    """把提取到的文件名拼回消息文本（兼容契约：保留占位符前缀）。

    '[文件]' + '台账.xlsx' → '[文件] 台账.xlsx'（旧锚点 '[文件]' 仍是子串，消费方零改动兼容）
    文本已有文件名 / filename 为空 → 原样返回。
    """
    if not filename:
        return message_text
    text = str(message_text or '').strip()
    if _looks_like_filename(text):
        return text  # 已含文件名，幂等
    if text.startswith(FILE_PLACEHOLDER) or text.startswith(IMAGE_PLACEHOLDER):
        return f'{text} {filename}'
    return text


def process_messages(messages):
    """read 层批处理入口：messages 为消息文本列表，返回增强后的新列表（原列表不动）。

    任何一条处理失败不影响其余条目（fail-soft per item）。
    """
    out = []
    for m in (messages or []):
        try:
            out.append(enrich(m, extract_from_message_text(m)))
        except Exception:
            out.append(m)
    return out
