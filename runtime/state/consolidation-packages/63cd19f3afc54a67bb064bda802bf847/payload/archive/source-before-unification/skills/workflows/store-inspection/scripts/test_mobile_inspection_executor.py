import importlib.util
import json
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("mobile_inspection_executor.py")
SPEC = importlib.util.spec_from_file_location("mobile_inspection_executor", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def main():
    assert MODULE.platform_app_package("美团外卖") == "com.sankuai.meituan"
    try:
        MODULE.platform_app_package("微信美团小程序")
    except RuntimeError as exc:
        assert "platform-app-not-configured:微信美团小程序" in str(exc)
    else:
        raise AssertionError("Meituan WeChat mini-program entry must fail closed")
    assert MODULE.normalize_text("陶姥姥砂锅· 广式啫啫煲（金谊广场店）") == MODULE.normalize_text("陶姥姥砂锅•广式啫啫煲(金谊广场店)")
    rows = MODULE.parse_ocr("100,200,30,40\t0.500\t评价 63\n300,400,50,60\t1.000\t商家\n")
    assert MODULE.resolve_text(rows, "商家").x == 300
    assert MODULE.resolve_text(rows, "评价").y == 200
    try:
        MODULE.resolve_text(rows + [MODULE.OcrItem(500, 600, 1, 1, 1.0, "商家")], "商家")
    except RuntimeError as exc:
        assert "ocr-match-count:2" in str(exc)
    else:
        raise AssertionError("duplicate OCR target must fail closed")
    assert MODULE.has_focused_input('<hierarchy><node focused="true" enabled="true" /></hierarchy>')
    assert not MODULE.has_focused_input('<hierarchy><node focused="false" enabled="true" /></hierarchy>')
    accepted = MODULE.validate_verified_route(
        platform="美团外卖",
        city="上海市",
        poi="中房金谊广场",
        roster_store_name="陶姥姥砂锅·广式啫啫煲（金谊广场店）",
        consumer_store_name="陶姥姥砂锅菜（金谊广场店）",
        merchant_address="上海市浦东新区上南路4467弄73号401室-2铺",
    )
    assert accepted["ok"]
    routes = MODULE.load_verified_routes()
    assert len(routes["routes"]) == 4
    for route in routes["routes"]:
        checked = MODULE.validate_verified_route(
            platform=route["platform"],
            city=routes["city"],
            poi=routes["poi"],
            roster_store_name=route["rosterStoreName"],
            consumer_store_name=route["consumerStoreName"],
            merchant_address=f"上海市浦东新区{routes['merchantAddressAnchor']}弄73号",
        )
        assert checked["ok"]
    try:
        MODULE.validate_verified_route(
            platform="美团外卖",
            city="保定市",
            poi="中房金谊广场",
            roster_store_name="9家湘菜（金谊广场店）",
            consumer_store_name="9家湘菜（上南路店）",
            merchant_address="上海市浦东新区上南路4467号",
        )
    except RuntimeError as exc:
        assert "route-city-mismatch" in str(exc)
    else:
        raise AssertionError("wrong city must fail closed")
    with tempfile.TemporaryDirectory() as temp_dir:
        plan_path = Path(temp_dir) / "plan.json"
        plan = {
            "policyVersion": 1,
            "currentStage": "mobile",
            "store": {"platform": "淘宝闪购", "city": "上海市", "rosterStoreName": "9家湘菜（金谊广场店）"},
            "mobileChecklist": [{"module": "search", "rows": [2, 21, 23]}],
        }
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        module = MODULE.validate_mobile_module_plan(
            plan_path=plan_path,
            platform="淘宝闪购",
            city="上海市",
            roster_store_name="9家湘菜（金谊广场店）",
            module="search",
        )
        assert module["rows"] == [2, 21, 23]

        plan["policyVersion"] = 2
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        module_v2 = MODULE.validate_mobile_module_plan(
            plan_path=plan_path,
            platform="淘宝闪购",
            city="上海市",
            roster_store_name="9家湘菜（金谊广场店）",
            module="search",
        )
        assert module_v2["rows"] == [2, 21, 23]

        plan["policyVersion"] = 3
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        try:
            MODULE.validate_mobile_module_plan(
                plan_path=plan_path,
                platform="淘宝闪购",
                city="上海市",
                roster_store_name="9家湘菜（金谊广场店）",
                module="search",
            )
        except RuntimeError as exc:
            assert "hybrid-plan-state-invalid" in str(exc)
        else:
            raise AssertionError("unknown policy version must fail closed")

        plan["policyVersion"] = 1
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        try:
            MODULE.validate_mobile_module_plan(
                plan_path=plan_path,
                platform="淘宝闪购",
                city="上海市",
                roster_store_name="9家湘菜（金谊广场店）",
                module="reviews",
            )
        except RuntimeError as exc:
            assert "mobile-module-not-planned:reviews" in str(exc)
        else:
            raise AssertionError("unplanned mobile module must fail closed")
    print('{"ok": true, "tests": 17}')


if __name__ == "__main__":
    main()
