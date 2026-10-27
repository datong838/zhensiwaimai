from extractors import extract_eta, extract_monthly_sales, extract_price, extract_promotions, full_text, top_text


def build_shop_info(blocks, rank: int) -> dict:
    text = full_text(blocks)
    return {
        "platform": "taobao_flash", "rank": rank, "shop_name": top_text(blocks),
        "price": extract_price(text), "sales": extract_monthly_sales(text), "eta": extract_eta(text),
        "promotions": extract_promotions(text, ["百亿补贴", "聚划算", "限时秒杀", "天天特卖"]),
    }
