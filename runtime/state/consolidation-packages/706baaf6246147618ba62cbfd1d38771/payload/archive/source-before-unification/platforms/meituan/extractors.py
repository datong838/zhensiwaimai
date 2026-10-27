from extractors import (
    extract_delivery_fee, extract_delivery_time, extract_distance,
    extract_min_order, extract_monthly_sales, extract_promotions,
    extract_rating, full_text, top_text,
)


def build_shop_info(blocks, rank: int) -> dict:
    text = full_text(blocks)
    return {
        "platform": "meituan", "rank": rank, "shop_name": top_text(blocks),
        "rating": extract_rating(text), "monthly_sales": extract_monthly_sales(text),
        "delivery_fee": extract_delivery_fee(text), "min_order": extract_min_order(text),
        "delivery_time_min": extract_delivery_time(text), "distance_km": extract_distance(text),
        "promotions": extract_promotions(text, ["满减", "折扣", "新品", "特价", "买赠"]),
    }
