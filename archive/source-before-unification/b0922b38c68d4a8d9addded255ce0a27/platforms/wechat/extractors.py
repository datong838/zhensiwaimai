from extractors import top_text


def build_page_info(blocks, rank: int = 1) -> dict:
    return {"platform": "wechat", "rank": rank, "title": top_text(blocks), "raw_texts": [b.text for b in blocks[:20]]}
