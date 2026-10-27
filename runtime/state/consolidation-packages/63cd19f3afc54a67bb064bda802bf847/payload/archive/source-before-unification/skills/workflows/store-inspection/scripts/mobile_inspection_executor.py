#!/usr/bin/env python3
"""物理安卓手机巡店的确定性底层动作；业务事实仍以保存的截图为准。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OCR = SKILL_DIR.parent / "daily-top10-to-wechat-group" / "scripts" / "ocr_vision"
ROUTES_PATH = SKILL_DIR / "references" / "verified-store-routes.json"
PLATFORM_APP_PACKAGES = {
    "美团外卖": "com.sankuai.meituan",
}


def run(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=capture)


def physical_devices() -> list[str]:
    rows = run("adb", "devices", "-l").stdout.splitlines()[1:]
    return [row.split()[0] for row in rows if " device" in f" {row}" and not row.startswith("emulator-")]


def require_physical_device() -> str:
    devices = physical_devices()
    if len(devices) != 1:
        raise RuntimeError(f"physical-device-count:{len(devices)}")
    return devices[0]


def adb(serial: str, *args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return run("adb", "-s", serial, *args, capture=capture)


def normalize_text(value: str) -> str:
    table = str.maketrans({"（": "(", "）": ")", "·": "", "•": "", ".": "", " ": "", "　": ""})
    return str(value).translate(table).lower()


def load_verified_routes(route_path: Path = ROUTES_PATH) -> dict:
    return json.loads(route_path.read_text(encoding="utf-8"))


def validate_verified_route(
    *,
    platform: str,
    city: str,
    poi: str,
    roster_store_name: str,
    consumer_store_name: str,
    merchant_address: str,
    route_path: Path = ROUTES_PATH,
) -> dict:
    routes = load_verified_routes(route_path)
    if normalize_text(city) != normalize_text(routes["city"]):
        raise RuntimeError(f"route-city-mismatch:{city}")
    if normalize_text(poi) != normalize_text(routes["poi"]):
        raise RuntimeError(f"route-poi-mismatch:{poi}")
    candidates = [
        item for item in routes["routes"]
        if item["platform"] == platform and normalize_text(item["rosterStoreName"]) == normalize_text(roster_store_name)
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"route-match-count:{len(candidates)}:{platform}:{roster_store_name}")
    route = candidates[0]
    allowed_names = [route["consumerStoreName"], *route.get("aliases", [])]
    if not any(normalize_text(consumer_store_name) == normalize_text(name) for name in allowed_names):
        raise RuntimeError(f"route-store-mismatch:{consumer_store_name}")
    if normalize_text(routes["merchantAddressAnchor"]) not in normalize_text(merchant_address):
        raise RuntimeError(f"route-address-mismatch:{merchant_address}")
    return {"ok": True, "route": route, "safetyMode": "READ_ONLY"}


def validate_mobile_module_plan(
    *,
    plan_path: Path,
    platform: str,
    city: str,
    roster_store_name: str,
    module: str,
) -> dict:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("policyVersion") not in {1, 2} or plan.get("currentStage") != "mobile":
        raise RuntimeError("hybrid-plan-state-invalid")
    store = plan.get("store", {})
    for key, actual in (("platform", platform), ("city", city), ("rosterStoreName", roster_store_name)):
        if normalize_text(store.get(key, "")) != normalize_text(actual):
            raise RuntimeError(f"hybrid-plan-store-mismatch:{key}:{actual}")
    modules = {item.get("module"): item for item in plan.get("mobileChecklist", [])}
    if module not in modules:
        raise RuntimeError(f"mobile-module-not-planned:{module}")
    rows = modules[module].get("rows", [])
    if not rows:
        raise RuntimeError(f"mobile-module-empty:{module}")
    return {"ok": True, "module": module, "rows": rows, "safetyMode": "READ_ONLY"}


def has_focused_input(hierarchy: str) -> bool:
    root = ElementTree.fromstring(hierarchy)
    return any(node.attrib.get("focused") == "true" and node.attrib.get("enabled", "true") == "true" for node in root.iter("node"))


@dataclass(frozen=True)
class OcrItem:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    text: str


def parse_ocr(output: str) -> list[OcrItem]:
    items: list[OcrItem] = []
    for line in output.splitlines():
        match = re.match(r"^(\d+),(\d+),(\d+),(\d+)\t([0-9.]+)\t(.+)$", line)
        if not match:
            continue
        x, y, width, height, confidence, text = match.groups()
        items.append(OcrItem(int(x), int(y), int(width), int(height), float(confidence), text.strip()))
    return items


def capture_screen(serial: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], check=True, capture_output=True)
    output.write_bytes(completed.stdout)


def ocr_items(image: Path, ocr_binary: Path = DEFAULT_OCR) -> list[OcrItem]:
    if not ocr_binary.is_file():
        raise RuntimeError(f"ocr-binary-missing:{ocr_binary}")
    return parse_ocr(run(str(ocr_binary), str(image)).stdout)


def resolve_text(items: list[OcrItem], query: str) -> OcrItem:
    normalized = normalize_text(query)
    exact = [item for item in items if normalize_text(item.text) == normalized]
    matches = exact or [item for item in items if normalized in normalize_text(item.text)]
    if len(matches) != 1:
        raise RuntimeError(f"ocr-match-count:{len(matches)}:{query}")
    return matches[0]


def current_package(serial: str) -> str:
    text = adb(serial, "shell", "dumpsys", "window").stdout
    match = re.search(r"mCurrentFocus=.*? ([\w.]+)/", text)
    return match.group(1) if match else ""


def platform_app_package(platform: str) -> str:
    try:
        return PLATFORM_APP_PACKAGES[platform]
    except KeyError as exc:
        raise RuntimeError(f"platform-app-not-configured:{platform}") from exc


def u2_device(serial: str):
    try:
        import uiautomator2 as u2
    except ImportError as exc:
        raise RuntimeError("uiautomator2-missing:install requirements-mobile.txt before business execution") from exc
    return u2.connect(serial)


def command_preflight(args: argparse.Namespace) -> dict:
    serial = require_physical_device()
    if not DEFAULT_OCR.is_file():
        raise RuntimeError(f"ocr-binary-missing:{DEFAULT_OCR}")
    device = u2_device(serial)
    return {
        "ok": True,
        "deviceModel": device.info.get("productName"),
        "foregroundPackage": current_package(serial),
        "ocrBinary": str(DEFAULT_OCR),
        "safetyMode": "READ_ONLY",
    }


def command_start_app(args: argparse.Namespace) -> dict:
    serial = require_physical_device()
    adb(serial, "shell", "monkey", "-p", args.package, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(args.wait)
    actual = current_package(serial)
    if actual != args.package:
        raise RuntimeError(f"foreground-package-mismatch:{actual}:{args.package}")
    return {"ok": True, "package": actual}


def command_start_platform_app(args: argparse.Namespace) -> dict:
    package = platform_app_package(args.platform)
    serial = require_physical_device()
    adb(serial, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(args.wait)
    actual = current_package(serial)
    if actual != package:
        raise RuntimeError(f"foreground-package-mismatch:{actual}:{package}")
    return {"ok": True, "platform": args.platform, "package": actual, "entryPolicy": "NATIVE_APP_ONLY"}


def command_capture(args: argparse.Namespace) -> dict:
    serial = require_physical_device()
    output = Path(args.output).resolve()
    capture_screen(serial, output)
    items = ocr_items(output)
    output.with_suffix(".ocr.txt").write_text("\n".join(f"{i.x},{i.y},{i.width},{i.height}\t{i.confidence:.3f}\t{i.text}" for i in items) + "\n", encoding="utf-8")
    return {"ok": True, "output": str(output), "ocrItems": len(items), "foregroundPackage": current_package(serial)}


def command_tap_text(args: argparse.Namespace) -> dict:
    serial = require_physical_device()
    temp = Path(args.snapshot).resolve()
    capture_screen(serial, temp)
    item = resolve_text(ocr_items(temp), args.text)
    adb(serial, "shell", "input", "tap", str(item.x), str(item.y))
    time.sleep(args.wait)
    if args.expect:
        verify = temp.with_name(f"{temp.stem}.after{temp.suffix}")
        capture_screen(serial, verify)
        resolve_text(ocr_items(verify), args.expect)
    return {"ok": True, "matched": asdict(item), "coordinatesFresh": True, "expected": args.expect or None}


def command_set_text(args: argparse.Namespace) -> dict:
    serial = require_physical_device()
    device = u2_device(serial)
    if not has_focused_input(device.dump_hierarchy(compressed=False)):
        raise RuntimeError("text-input-not-focused")
    device.send_keys(args.text, clear=args.clear)
    if args.enter:
        device.press("enter")
    time.sleep(args.wait)
    return {"ok": True, "textLength": len(args.text), "enter": args.enter}


def command_swipe(args: argparse.Namespace) -> dict:
    serial = require_physical_device()
    adb(serial, "shell", "input", "swipe", str(args.x1), str(args.y1), str(args.x2), str(args.y2), str(args.duration_ms))
    time.sleep(args.wait)
    return {"ok": True, "safeAreaConfirmedByCaller": True}


def command_assert_text(args: argparse.Namespace) -> dict:
    serial = require_physical_device()
    snapshot = Path(args.snapshot).resolve()
    capture_screen(serial, snapshot)
    item = resolve_text(ocr_items(snapshot), args.text)
    return {"ok": True, "matched": asdict(item), "snapshot": str(snapshot)}


def command_validate_route(args: argparse.Namespace) -> dict:
    return validate_verified_route(
        platform=args.platform,
        city=args.city,
        poi=args.poi,
        roster_store_name=args.roster_store_name,
        consumer_store_name=args.consumer_store_name,
        merchant_address=args.merchant_address,
    )


def command_validate_mobile_module(args: argparse.Namespace) -> dict:
    return validate_mobile_module_plan(
        plan_path=Path(args.plan).resolve(),
        platform=args.platform,
        city=args.city,
        roster_store_name=args.roster_store_name,
        module=args.module,
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight").set_defaults(func=command_preflight)

    start = commands.add_parser("start-app")
    start.add_argument("--package", required=True)
    start.add_argument("--wait", type=float, default=3)
    start.set_defaults(func=command_start_app)

    platform_start = commands.add_parser("start-platform-app")
    platform_start.add_argument("--platform", required=True)
    platform_start.add_argument("--wait", type=float, default=3)
    platform_start.set_defaults(func=command_start_platform_app)

    capture = commands.add_parser("capture")
    capture.add_argument("--output", required=True)
    capture.set_defaults(func=command_capture)

    tap = commands.add_parser("tap-text")
    tap.add_argument("--text", required=True)
    tap.add_argument("--snapshot", required=True)
    tap.add_argument("--expect")
    tap.add_argument("--wait", type=float, default=1.5)
    tap.set_defaults(func=command_tap_text)

    set_text = commands.add_parser("set-text")
    set_text.add_argument("--text", required=True)
    set_text.add_argument("--clear", action="store_true")
    set_text.add_argument("--enter", action="store_true")
    set_text.add_argument("--wait", type=float, default=1.5)
    set_text.set_defaults(func=command_set_text)

    swipe = commands.add_parser("swipe")
    for name in ("x1", "y1", "x2", "y2"):
        swipe.add_argument(f"--{name}", type=int, required=True)
    swipe.add_argument("--duration-ms", type=int, default=450)
    swipe.add_argument("--wait", type=float, default=1.5)
    swipe.set_defaults(func=command_swipe)

    check = commands.add_parser("assert-text")
    check.add_argument("--text", required=True)
    check.add_argument("--snapshot", required=True)
    check.set_defaults(func=command_assert_text)

    route = commands.add_parser("validate-route")
    route.add_argument("--platform", required=True)
    route.add_argument("--city", required=True)
    route.add_argument("--poi", required=True)
    route.add_argument("--roster-store-name", required=True)
    route.add_argument("--consumer-store-name", required=True)
    route.add_argument("--merchant-address", required=True)
    route.set_defaults(func=command_validate_route)

    mobile_module = commands.add_parser("validate-mobile-module")
    mobile_module.add_argument("--plan", required=True)
    mobile_module.add_argument("--platform", required=True)
    mobile_module.add_argument("--city", required=True)
    mobile_module.add_argument("--roster-store-name", required=True)
    mobile_module.add_argument("--module", choices=("search", "products", "reviews", "merchant"), required=True)
    mobile_module.set_defaults(func=command_validate_mobile_module)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        print(json.dumps(args.func(args), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
