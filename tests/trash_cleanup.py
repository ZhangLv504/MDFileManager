"""测试运行数据清理：只移除验证脚本自己产生的回收站条目与版本历史。

判定依据是原路径 / 文档路径是否包含各脚本专用的测试标记，
例如 __smoke__ / __frontend__ / __browser__ / __stage5__。
不会触碰用户的真实删除记录与文档历史。
"""
from __future__ import annotations

import json
import re
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


def cleanup_test_history(base_dir: Path) -> int:
    root = Path(base_dir) / "data" / ".history"
    index_path = root / "index.json"
    if not index_path.is_file():
        return 0
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    docs = index.get("docs") if isinstance(index, dict) else None
    if not isinstance(docs, dict):
        return 0
    removed = 0
    for path in list(docs.keys()):
        if not any(marker in path for marker in MARKERS):
            continue
        for entry in docs.pop(path, []):
            version_id = str(entry.get("id", "")) if isinstance(entry, dict) else ""
            if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", version_id):
                try:
                    (root / "blobs" / (version_id + ".md")).unlink(missing_ok=True)
                except OSError:
                    pass
        removed += 1
    if removed:
        try:
            index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return removed
