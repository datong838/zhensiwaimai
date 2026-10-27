#!/usr/bin/env python3

from business_wechat_file_sender import business_search_results
from business_wechat_group_locator import exact_business_group_title


GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"

assert exact_business_group_title("上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰(81)", GROUP)
assert exact_business_group_title("上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰（81）", GROUP)
assert not exact_business_group_title("上海臻肆外卖运营-盯个盯-饭敢当 临时群(81)", GROUP)
assert not exact_business_group_title("上海臻肆外卖运营-盯个盯-饭敢当(81)", GROUP)

entries = [
    {"x": 467, "y": 165, "text": "上海臻肆外卖运营-盯个盯-饭敢当"},
    {"x": 494, "y": 452, "text": "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰（81）"},
    {"x": 552, "y": 1228, "text": "发到 上海臻肆外卖运营-盯个盯-饭敢当 临时群里"},
]
assert business_search_results(entries) == [entries[1]]
duplicates = entries + [{"x": 500, "y": 500, "text": "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰(81)"}]
assert len(business_search_results(duplicates)) == 2
print("business WeChat exact group locator checks passed")
