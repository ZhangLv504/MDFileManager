"""测试用回收站清理工具：只移除验证脚本自己产生的条目，不碰用户真实回收站数据。

判定依据是 meta.json 里的 original_path 是否包含各脚本专用的测试标记，
例如 __smoke__ / __frontend__ / __browser__ / __stage5__。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

MARKERS = ("__smoke__", "__frontend__", "__browser__", "__stage5__")


def cleanup_test_trash(base_dir: Path) -> int:
    trash = Path(base_dir) / "data" / ".trash"
    if not trash.is_dir():
        return 0
    removed = 0
    for item in list(trash.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        meta_path = item / "meta.json"
        original = ""
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                original = str(meta.get("original_path", "")) if isinstance(meta, dict) else ""
            except (OSError, ValueError):
                original = ""
        if any(marker in original for marker in MARKERS):
            shutil.rmtree(item, ignore_errors=True)
            removed += 1
    return removed
