"""从 OCR 文本块中抽取结构化字段（评分/销量/配送/价格等）。"""
import re
from typing import List, Dict, Optional

from vision import TextBlock


def full_text(blocks: List[TextBlock]) -> str:
    return "\n".join(b.text for b in blocks)


def top_text(blocks: List[TextBlock], max_y: int = 200) -> Optional[str]:
    """取顶部区域（y < max_y）的最长有意义文本，用作标题/店名。"""
    cands = [b for b in blocks if b.y < max_y and len(b.text) >= 2]
    if not cands:
        return None
    return max(cands, key=lambda b: len(b.text)).text


def extract_rating(text: str) -> Optional[float]:
    """评分：4.8分 / 4.8。"""
    m = re.search(r"(\d\.\d)\s*分", text)
    return float(m.group(1)) if m else None


def extract_monthly_sales(text: str) -> Optional[str]:
    """月售：月售9999+。"""
    m = re.search(r"(?:月售|已售)\s*(\d+[\+万]*)", text)
    return m.group(1) if m else None


def extract_delivery_fee(text: str) -> Optional[int]:
    """配送费：配送¥5 / 配送费5元。"""
    m = re.search(r"配送费?\s*[¥￥]\s*(\d+)", text)
    return int(m.group(1)) if m else None


def extract_min_order(text: str) -> Optional[int]:
    """起送价：起送¥20。"""
    m = re.search(r"起送\s*[¥￥]\s*(\d+)", text)
    return int(m.group(1)) if m else None


def extract_delivery_time(text: str) -> Optional[int]:
    """配送时间：30分钟。"""
    m = re.search(r"(\d+)\s*分钟", text)
    return int(m.group(1)) if m else None


def extract_distance(text: str) -> Optional[float]:
    """距离：1.2km。"""
    m = re.search(r"(\d+\.?\d*)\s*[kK][mM]", text)
    return float(m.group(1)) if m else None


def extract_price(text: str) -> Optional[float]:
    """价格：¥29.9。"""
    m = re.search(r"[¥￥]\s*(\d+\.?\d*)", text)
    return float(m.group(1)) if m else None


def extract_eta(text: str) -> Optional[str]:
    """即时零售时效：30分钟达 / 1小时达。"""
    m = re.search(r"\d+\s*(?:分钟|小时)达", text)
    return m.group(0) if m else None


def extract_promotions(text: str, keywords: List[str]) -> List[str]:
    return [k for k in keywords if k in text]


def build_shop_info(blocks: List[TextBlock], platform: str, rank: int) -> Dict:
    """统一构建店铺/商品信息字典。"""
    text = full_text(blocks)
    info = {"platform": platform, "rank": rank}

    if platform == "meituan":
        info.update({
            "shop_name": top_text(blocks),
            "rating": extract_rating(text),
            "monthly_sales": extract_monthly_sales(text),
            "delivery_fee": extract_delivery_fee(text),
            "min_order": extract_min_order(text),
            "delivery_time_min": extract_delivery_time(text),
            "distance_km": extract_distance(text),
            "promotions": extract_promotions(
                text, ["满减", "折扣", "新品", "特价", "买赠"]),
        })
    elif platform == "taobao_flash":
        info.update({
            "shop_name": top_text(blocks),
            "price": extract_price(text),
            "sales": extract_monthly_sales(text),
            "eta": extract_eta(text),
            "promotions": extract_promotions(
                text, ["百亿补贴", "聚划算", "限时秒杀", "天天特卖"]),
        })
    else:  # wechat
        info.update({
            "title": top_text(blocks),
            "raw_texts": [b.text for b in blocks[:20]],
        })
    return info
