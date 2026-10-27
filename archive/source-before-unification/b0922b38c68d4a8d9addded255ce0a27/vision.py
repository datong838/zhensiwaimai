"""视觉兜底：截图 + PaddleOCR + 模板匹配。

当 WebView / 自定义控件拿不到 UI 树时用此模块。
OCR 建议在电脑/云端运行，避免在 Kirin 810 上卡顿。
"""
import os
from dataclasses import dataclass
from typing import List, Optional

from PIL import Image

from config import OCR_LANG


@dataclass
class TextBlock:
    text: str
    confidence: float
    x: int
    y: int
    bbox: list


_ocr = None


def get_ocr():
    """懒加载 PaddleOCR（避免每次截图重加载模型）。"""
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(use_angle_cls=True, lang=OCR_LANG,
                         use_gpu=False, show_log=False)
    return _ocr


def screenshot(d, path: str = "screen.png") -> str:
    """截图并保存，返回路径。"""
    d.screenshot(path)
    return path


def ocr_image(image_path: str) -> List[TextBlock]:
    """OCR 识别截图，返回带坐标的文本块列表。"""
    if not os.path.exists(image_path):
        return []
    ocr = get_ocr()
    result = ocr.ocr(image_path, cls=True)
    blocks = []
    for line in result:
        for word_info in line:
            bbox, (text, conf) = word_info
            blocks.append(TextBlock(
                text=text, confidence=float(conf),
                x=int(bbox[0][0]), y=int(bbox[0][1]), bbox=bbox))
    return blocks


def find_text(blocks: List[TextBlock], target: str) -> Optional[TextBlock]:
    """在 OCR 结果中查找包含 target 的文本块。"""
    for b in blocks:
        if target in b.text:
            return b
    return None


def click_by_ocr(d, target: str, image_path: str = "screen.png") -> bool:
    """截图 -> OCR -> 点击目标文本中心。"""
    screenshot(d, image_path)
    blocks = ocr_image(image_path)
    hit = find_text(blocks, target)
    if hit:
        cx = int((hit.bbox[0][0] + hit.bbox[2][0]) / 2)
        cy = int((hit.bbox[0][1] + hit.bbox[2][1]) / 2)
        from human import jitter
        jx, jy = jitter(cx, cy)
        d.click(jx, jy)
        return True
    return False


def crop_ocr(image_path: str, region: tuple) -> list:
    """裁剪指定区域 (left, top, right, bottom) 后 OCR。"""
    img = Image.open(image_path)
    cropped = img.crop(region)
    tmp = "cropped_temp.png"
    cropped.save(tmp)
    return [b.text for b in ocr_image(tmp)]
