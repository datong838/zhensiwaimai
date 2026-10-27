#!/usr/bin/env python3
"""Read-only visual probe for Jinsha checkbox state."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


def ocr_entries(image: Path, ocr_bin: Path) -> list[dict]:
    output = subprocess.run(
        [str(ocr_bin), str(image), "zh-Hans"], check=True, capture_output=True, text=True
    ).stdout
    entries = []
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            cx, cy, width, height = (int(value) for value in parts[0].split(","))
        except ValueError:
            continue
        entries.append({"x": cx, "y": cy, "w": width, "h": height, "text": parts[2]})
    return entries


def probe(image_path: Path, ocr_bin: Path, labels: list[str]) -> dict:
    entries = ocr_entries(image_path, ocr_bin)
    with Image.open(image_path).convert("RGB") as image:
        results = {}
        for label in labels:
            matches = [entry for entry in entries if label.replace(" ", "") in entry["text"].replace(" ", "")]
            if not matches and label == "单均到手":
                matches = [
                    entry for entry in entries
                    if "单均" in entry["text"].replace(" ", "")
                    and "实付" not in entry["text"].replace(" ", "")
                ]
            if len(matches) != 1:
                results[label] = {"ok": False, "reason": f"ocr-count:{len(matches)}"}
                continue
            entry = matches[0]
            # Jinsha places the square 6-22 px left of the recognized label block.
            left = max(0, entry["x"] - entry["w"] // 2 - 24)
            right = min(image.width, entry["x"] - entry["w"] // 2 + 4)
            top = max(0, entry["y"] - max(10, entry["h"]))
            bottom = min(image.height, entry["y"] + max(10, entry["h"]))
            pixels = list(image.crop((left, top, right, bottom)).getdata())
            colored = sum(1 for red, green, blue in pixels if blue > 120 and blue > red + 15 and blue > green - 10)
            results[label] = {
                "ok": colored >= 8,
                "coloredPixels": colored,
                "entry": entry,
                "click": [max(1, entry["x"] - entry["w"] // 2 - 10), entry["y"]],
            }
    return results


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit("usage: checkbox_probe.py IMAGE OCR_BIN LABEL...")
    print(json.dumps(probe(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]), ensure_ascii=False))
