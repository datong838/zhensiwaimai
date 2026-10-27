#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染台账：图片条目的**身份**来源。

为什么必须有它（这是改图片投递最容易踩的坑）：
`contract.normalize` 对非文本条目记录的是**文件摘要**，不是正文摘要。所以
「这条记录对应的载荷是否就是当初发出去的那张图」不能再靠正文 sha256 判断。
若不立台账而改为「校验时现场重渲染」，那么日后一旦调整版式常量，历史待核项
的摘要就会变化 → 被误判成 `ledger-payload-digest-conflict`（"载荷被篡改"）而
假报警，甚至阻断收口。

台账内容（`{root}/.runtime/render/{业务日}/index.json`）：

    { "schemaVersion": 1,
      "styleSha256": "...", "font": {"path": "...", "sha256": "..."},
      "items": { "<记录键>": {"itemId", "fileName", "path", "sha256",
                              "bytes", "styleSha256", "fontSha256",
                              "renderedAtUtc"} } }

纪律：
- **幂等**：已登记且版式未变 ⇒ 直接复用，不重渲染、不重写文件、不刷新时间戳。
- **fail-closed**：已登记但重渲染结果与登记摘要不符（版式/字体真的变了）⇒ 抛
  `render-style-changed-for-existing-row`，交人判断，绝不静默改写身份。
- 所有函数都收显式 `root`（不读模块级常量），便于调用方复用同一根、也便于
  单测把根指到临时目录。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from render_notice import FONT_PATH, font_digest, render_png, style_digest

SCHEMA_VERSION = 1
INDEX_NAME = "index.json"


def render_dir(root, business_date: str) -> Path:
    return Path(root) / ".runtime" / "render" / business_date


def index_path(root, business_date: str) -> Path:
    return render_dir(root, business_date) / INDEX_NAME


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read_index(root, business_date: str) -> dict:
    path = index_path(root, business_date)
    if not path.is_file():
        return {"schemaVersion": SCHEMA_VERSION, "styleSha256": style_digest(),
                "font": {"path": FONT_PATH, "sha256": font_digest()}, "items": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != SCHEMA_VERSION or not isinstance(value.get("items"), dict):
        raise ValueError("render-index-schema-mismatch")
    return value


def _write_index(root, business_date: str, index: dict) -> None:
    payload = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_bytes(index_path(root, business_date), payload.encode("utf-8"))
    if json.loads(index_path(root, business_date).read_text(encoding="utf-8")) != index:
        raise ValueError("render-index-readback-mismatch")


def _store(root, business_date: str, record_key: str, item_id: str, blob: bytes) -> dict:
    # 2026-10-18 短名修复：64 字符完整记录键作文件名传 Windows 微信时过长，
    # 「发送给」确认框挂掉（当日第 3 张图反复失败根因）。改用 12 字符前缀短名；
    # sha256 完整保留在 index/请求里做身份绑定，文件名只是传输载体。
    path = render_dir(root, business_date) / f"notice-{record_key[:12]}.png"
    if not path.is_file() or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(blob).digest():
        _atomic_bytes(path, blob)
    # 迁移清理：同键旧长名文件（若存在）在内容一致时移除，避免双份残留
    legacy = render_dir(root, business_date) / f"{record_key}.png"
    if legacy.is_file() and hashlib.sha256(legacy.read_bytes()).digest() == hashlib.sha256(blob).digest():
        legacy.unlink()
    return {"itemId": item_id, "fileName": path.name, "path": str(path),
            "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
            "styleSha256": style_digest(), "fontSha256": font_digest(),
            "renderedAtUtc": datetime.now(timezone.utc).isoformat()}


def ensure(root, business_date: str, rows: list[dict], *, item_id_for) -> dict:
    """确保每行的通知图片已渲染并登记，返回 `{记录键: entry}`。

    `item_id_for(row)` 由调用方传入，避免本模块依赖 prepare_delivery 的命名规则。
    """
    index = _read_index(root, business_date)
    registered = index["items"]
    current_style = style_digest()
    changed = False
    for row in rows:
        record_key = row["记录键"]
        existing = registered.get(record_key)
        if existing is not None and existing.get("styleSha256") == current_style:
            # 版式未变 ⇒ 字节必然相同，复用登记（不重渲染、不刷新时间戳）。
            if not Path(existing["path"]).is_file():
                raise ValueError("render-file-missing-for-registered-row:" + record_key)
            continue
        blob = render_png(row["通知正文"])
        digest = hashlib.sha256(blob).hexdigest()
        if existing is not None:
            if existing.get("sha256") != digest:
                raise ValueError("render-style-changed-for-existing-row:" + record_key)
            # 版式摘要变了但字节一致（改动不影响输出）⇒ 只前滚摘要，不改身份。
            existing["styleSha256"] = current_style
            existing["fontSha256"] = font_digest()
            changed = True
            continue
        registered[record_key] = _store(root, business_date, record_key,
                                        item_id_for(row), blob)
        changed = True
    index["styleSha256"] = current_style
    index["font"] = {"path": FONT_PATH, "sha256": font_digest()}
    if changed or not index_path(root, business_date).is_file():
        _write_index(root, business_date, index)
    return registered


def lookup(root, business_date: str, record_key: str) -> dict | None:
    """只读查询已登记条目；不存在返回 None（调用方决定是否重渲染）。"""
    if not index_path(root, business_date).is_file():
        return None
    return _read_index(root, business_date)["items"].get(record_key)


def self_test() -> dict:
    """自证：幂等（两次 ensure 结果一致且不刷新时间戳）+ 登记可回读 + 文件摘要吻合。"""
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        business_date = "1970-01-01"
        rows = [{"记录键": "a" * 64, "通知正文":
                 "--- 通知 ---\n店(测试)\n【美团】\n评价时间: 2026-01-01\n"
                 "评价等级: 1星\n申诉结果：---申诉中---\n评价内容: 测试"}]
        naming = lambda row: "appeal-" + row["记录键"][:20]  # noqa: E731
        first = ensure(root, business_date, rows, item_id_for=naming)["a" * 64]
        second = ensure(root, business_date, rows, item_id_for=naming)["a" * 64]
        if first != second:
            raise AssertionError("render-manifest-not-idempotent")
        if lookup(root, business_date, "a" * 64) is None or lookup(root, business_date, "b" * 64) is not None:
            raise AssertionError("render-manifest-lookup-broken")
        if hashlib.sha256(Path(first["path"]).read_bytes()).hexdigest() != first["sha256"]:
            raise AssertionError("render-file-digest-mismatch")
        # 新业务日不得复用他人根目录
        if index_path(root, "1970-01-02").exists():
            raise AssertionError("render-index-leaked-across-dates")
    return {"ok": True, "styleSha256": style_digest(), "runtimeModelDecisions": 0}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False))
