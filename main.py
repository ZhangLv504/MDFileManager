"""MDFileManager - 本地 Markdown 文件与目录的 RESTful API。

所有文档以 UTF-8 明文存放在项目根目录的 data/ 下，同名文件覆盖写入即视为版本更新。
本模块只提供纯净的 JSON API，不含任何模板渲染或界面代码。

启动：
    .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
或：
    .venv/Scripts/python.exe main.py

接口文档（可直接完整测试）：
    http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import errno
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_ROOT = (BASE_DIR / "data").resolve()
# 默认把删除内容放在 data/.trash/（隐藏目录，不会出现在目录树）；
# 可用 MDFM_TRASH_DIR 覆盖，便于测试隔离或把回收站放到其他磁盘。
TRASH_ROOT = Path(os.environ.get("MDFM_TRASH_DIR") or str(DATA_ROOT / ".trash")).resolve()
TRASH_META = "meta.json"
TRASH_PAYLOAD = "payload"
DEFAULT_CATEGORIES = ("Projects", "Knowledge")
MAX_DOC_BYTES = 5 * 1024 * 1024
MAX_DESCRIPTION_BYTES = 20 * 1024
DESCRIPTION_CHARS = 500
DESCRIPTION_FILE = ".description.md"
MAX_NAME_BYTES = 200
MAX_RECURSIVE_ITEMS = 2000
MAX_TRASH_ITEMS = 500
# 版本历史：.history/index.json 记录每个文档路径的版本列表，blobs/<id>.md 存快照。
HISTORY_ROOT = Path(
    os.environ.get("MDFM_HISTORY_DIR") or str(DATA_ROOT / ".history")
).resolve()
HISTORY_INDEX = "index.json"
HISTORY_BLOBS = "blobs"
MAX_VERSIONS_PER_DOC = 50
MAX_HISTORY_DOCS = 500
MAX_HISTORY_BYTES = 50 * 1024 * 1024

# Windows / POSIX 文件名非法字符，反斜杠一并禁止，避免 Windows 上被当作分隔符。
_FORBIDDEN_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"|?*\\]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _ensure_data_root() -> None:
    """启动时自动创建数据根目录与基础分类目录。"""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    (HISTORY_ROOT / HISTORY_BLOBS).mkdir(parents=True, exist_ok=True)
    for category in DEFAULT_CATEGORIES:
        (DATA_ROOT / category).mkdir(parents=True, exist_ok=True)


_ensure_data_root()

app = FastAPI(
    title="MDFileManager API",
    version="1.5.0",
    description="本地 Markdown 文档与目录的文件系统映射接口（纯 JSON RESTful API）",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _validate_segment(part: str) -> str:
    """校验单段名称，重命名与路径解析共用同一套规则。"""
    if part in ("", ".", ".."):
        raise _bad_request("名称中包含非法段（空段 / . / ..）")
    if "/" in part or "\\" in part:
        raise _bad_request("名称不能包含路径分隔符")
    if _FORBIDDEN_CHARS.search(part):
        raise _bad_request("名称中包含非法字符")
    if part != part.strip() or part.endswith(".") or part.startswith("."):
        raise _bad_request("名称不能以空格、点开头或结尾")
    if len(part.encode("utf-8")) > MAX_NAME_BYTES:
        raise _bad_request("名称过长")
    if part.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise _bad_request("名称属于系统保留字")
    return part


def _parse_relative_path(
    raw_path: str, *, md_rule: str = "any", min_parts: int = 1, label: str = "路径"
) -> tuple[Path, str]:
    """把 'Projects/子目录/文档.md' 解析为 (绝对路径, 相对 data/ 的 posix 路径)。

    任何可能越出 data/ 的路径都在此被拒绝：空段、`.`、`..`、绝对路径、
    盘符、非法字符、隐藏文件、系统保留名，以及符号链接逃逸。
    md_rule: require=必须是 .md；forbid=禁止 .md；any=不限制。
    """
    if not raw_path or "\x00" in raw_path:
        raise _bad_request(f"{label}路径不能为空")
    if raw_path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw_path):
        raise _bad_request("不接受绝对路径或盘符路径")

    parts = [_validate_segment(part) for part in raw_path.split("/")]
    if len(parts) < min_parts:
        raise _bad_request("路径必须包含分类目录与文件名，例如 Projects/说明.md")
    if md_rule == "require" and not parts[-1].lower().endswith(".md"):
        raise _bad_request("仅支持 .md 文件")
    if md_rule == "forbid" and parts[-1].lower().endswith(".md"):
        raise _bad_request("目录名不应以 .md 结尾")

    rel = Path(*parts)
    target = (DATA_ROOT / rel).resolve()
    try:
        target.relative_to(DATA_ROOT)
    except ValueError:
        raise _bad_request("路径越出 data/ 根目录")
    return target, rel.as_posix()


def _parse_doc_path(doc_path: str) -> tuple[Path, str]:
    return _parse_relative_path(doc_path, md_rule="require", min_parts=2, label="文档")


def _parse_dir_path(dir_path: str) -> tuple[Path, str]:
    return _parse_relative_path(dir_path, md_rule="forbid", min_parts=1, label="目录")


def _parse_entry_path(entry_path: str) -> tuple[Path, str]:
    return _parse_relative_path(entry_path, md_rule="any", min_parts=1, label="条目")


def _parse_target_dir(target_dir: str) -> tuple[Path, str]:
    """目标目录；空串代表 data/ 根，供「移动到顶层」使用。"""
    if not target_dir or not target_dir.strip():
        return DATA_ROOT, ""
    return _parse_dir_path(target_dir.strip())


def _assert_plain_path(target: Path) -> None:
    """路径链上不允许出现符号链接，避免移动/删除越出 data/。"""
    current = target
    while current != DATA_ROOT:
        if current.is_symlink():
            raise _bad_request("路径中含有符号链接，拒绝操作")
        parent = current.parent
        if parent == current:
            raise _bad_request("路径越出 data/ 根目录")
        current = parent


def _scan_recursive_items(directory: Path) -> tuple[list[Path], list[Path]]:
    """删除前完整扫描：返回 (文件列表, 子目录列表)，遇到符号链接直接拒绝。"""
    files: list[Path] = []
    dirs: list[Path] = []
    for entry in directory.iterdir():
        if entry.is_symlink():
            raise _bad_request(f"目录内包含符号链接（{entry.name}），拒绝删除")
        if entry.is_dir():
            sub_files, sub_dirs = _scan_recursive_items(entry)
            files.extend(sub_files)
            dirs.extend(sub_dirs)
            dirs.append(entry)
        else:
            files.append(entry)
    if len(files) + len(dirs) > MAX_RECURSIVE_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"目录内容超过 {MAX_RECURSIVE_ITEMS} 项，请分批清理后再删除",
        )
    return files, dirs


def _iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _read_description(directory: Path) -> str:
    desc_file = directory / DESCRIPTION_FILE
    if not desc_file.is_file():
        return ""
    try:
        return desc_file.read_text(encoding="utf-8")[:DESCRIPTION_CHARS]
    except (OSError, UnicodeDecodeError):
        return ""


def _scan(directory: Path, rel: Path) -> list[dict[str, Any]]:
    """递归构建目录树，只暴露目录与 .md 文件，跳过隐藏项和符号链接。"""
    nodes: list[dict[str, Any]] = []
    try:
        entries = sorted(
            directory.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.casefold()),
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"无法读取目录：{exc}",
        ) from exc

    for entry in entries:
        if entry.name.startswith(".") or entry.is_symlink():
            continue
        entry_rel = rel / entry.name
        if entry.is_dir():
            nodes.append({
                "name": entry.name,
                "path": entry_rel.as_posix(),
                "type": "dir",
                "description": _read_description(entry),
                "children": _scan(entry, entry_rel),
            })
        elif entry.is_file() and entry.suffix.lower() == ".md":
            try:
                stat_result = entry.stat()
            except OSError:
                continue
            nodes.append({
                "name": entry.name,
                "path": entry_rel.as_posix(),
                "type": "file",
                "size": stat_result.st_size,
                "modified": _iso_time(stat_result.st_mtime),
            })
    return nodes


def _atomic_write(target: Path, data: bytes) -> None:
    """同目录临时文件 + 原子替换，避免产生半截文件。"""
    tmp_name = ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".mdfm-", suffix=".tmp", dir=str(target.parent)
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        tmp_name = ""
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"写入失败：{exc}",
        ) from exc
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _move_path(source: Path, destination: Path) -> None:
    """移动文件/目录；跨磁盘（EXDEV / WinError 17）时自动退化为复制 + 删除源。

    Windows 上 os.rename 不能跨盘符，POSIX 上跨文件系统同理。回收站可通过
    MDFM_TRASH_DIR 放到另一块磁盘，因此这一层兜底是必要的。
    """
    try:
        source.rename(destination)
        return
    except OSError as exc:
        cross_device = (
            getattr(exc, "winerror", None) == 17 or exc.errno == errno.EXDEV
        )
        if not cross_device:
            raise
    if source.is_dir():
        shutil.copytree(source, destination)
        shutil.rmtree(source)
    else:
        shutil.copy2(source, destination)
        source.unlink()


HISTORY_LOCK = threading.Lock()


def _history_index_path() -> Path:
    return HISTORY_ROOT / HISTORY_INDEX


def _history_read() -> dict[str, Any]:
    path = _history_index_path()
    if not path.is_file():
        return {"docs": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"docs": {}}
    if not isinstance(data, dict) or not isinstance(data.get("docs"), dict):
        return {"docs": {}}
    return data


def _history_write(index: dict[str, Any]) -> None:
    _atomic_write(_history_index_path(),
                  json.dumps(index, ensure_ascii=False).encode("utf-8"))


def _history_blob_path(version_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", version_id or ""):
        raise _bad_request("版本 ID 非法")
    target = (HISTORY_ROOT / HISTORY_BLOBS / (version_id + ".md")).resolve()
    try:
        target.relative_to((HISTORY_ROOT / HISTORY_BLOBS).resolve())
    except ValueError:
        raise _bad_request("版本文件越出历史目录")
    return target


def _history_drop_entries(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        try:
            _history_blob_path(str(entry.get("id", ""))).unlink(missing_ok=True)
        except (OSError, HTTPException):
            pass


def _history_renumber(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = sorted(entries, key=lambda item: str(item.get("created_at", "")))
    if len(entries) > MAX_VERSIONS_PER_DOC:
        _history_drop_entries(entries[:len(entries) - MAX_VERSIONS_PER_DOC])
        entries = entries[len(entries) - MAX_VERSIONS_PER_DOC:]
    for number, entry in enumerate(entries, start=1):
        entry["version"] = number
    return entries


def _history_prune_global(index: dict[str, Any]) -> None:
    docs = index["docs"]
    while len(docs) > MAX_HISTORY_DOCS:
        oldest = min(docs, key=lambda key: str(docs[key][-1].get("created_at", ""))
                     if docs[key] else "")
        _history_drop_entries(docs.pop(oldest, []))
    total = sum(entry.get("size", 0)
                for entries in docs.values() for entry in entries)
    while total > MAX_HISTORY_BYTES:
        candidates = [(entry.get("created_at", ""), path, entry)
                      for path, entries in docs.items() for entry in entries]
        if not candidates:
            break
        _, path, victim = min(candidates, key=lambda item: str(item[0]))
        docs[path] = [entry for entry in docs[path] if entry is not victim]
        if not docs[path]:
            docs.pop(path, None)
        _history_drop_entries([victim])
        total -= victim.get("size", 0)
    for path, entries in list(docs.items()):
        docs[path] = _history_renumber(entries)


def _history_append(rel: str, content: bytes, *, action: str,
                    from_version: str | None = None) -> dict[str, Any]:
    """把一次保存的内容写成版本快照；同名覆盖即一个版本，重复保存相同内容不新增。"""
    with HISTORY_LOCK:
        index = _history_read()
        version_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            + "-" + uuid.uuid4().hex[:6]
        )
        _atomic_write(_history_blob_path(version_id), content)
        entry: dict[str, Any] = {
            "id": version_id,
            "version": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "size": len(content),
            "action": action,
        }
        if from_version:
            entry["from_version"] = from_version
        entries = list(index["docs"].get(rel, []))
        entries.append(entry)
        index["docs"][rel] = _history_renumber(entries)
        _history_prune_global(index)
        _history_write(index)
        current = index["docs"].get(rel, [])
        result = dict(entry)
        result["count"] = len(current)
        return result


def _history_repath(old_path: str, new_path: str, *, is_dir: bool) -> None:
    """重命名/移动后迁移历史键；目录会连带迁移其下所有文档。"""
    with HISTORY_LOCK:
        index = _history_read()
        docs = index["docs"]
        changed = False
        for path in list(docs.keys()):
            if is_dir:
                if path != old_path and not path.startswith(old_path + "/"):
                    continue
                new_key = new_path + path[len(old_path):]
            else:
                if path != old_path:
                    continue
                new_key = new_path
            if new_key == path:
                continue
            moving = docs.pop(path)
            if new_key in docs:
                docs[new_key] = _history_renumber(docs[new_key] + moving)
            else:
                docs[new_key] = moving
            changed = True
        if changed:
            _history_write(index)


def _history_entries(rel: str) -> list[dict[str, Any]]:
    with HISTORY_LOCK:
        return list(_history_read()["docs"].get(rel, []))


def _trash_item_dir(item_id: str) -> Path:
    """回收站条目 ID 只允许安全字符，且解析后必须仍在 .trash/ 内。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item_id or ""):
        raise _bad_request("回收站条目 ID 非法")
    target = (TRASH_ROOT / item_id).resolve()
    try:
        target.relative_to(TRASH_ROOT.resolve())
    except ValueError:
        raise _bad_request("回收站条目越出 .trash/ 目录")
    return target


def _read_trash_meta(item_dir: Path) -> dict[str, Any]:
    meta_path = item_dir / TRASH_META
    if not meta_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="回收站条目元数据缺失"
        )
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取回收站元数据失败：{exc}",
        ) from exc
    if not isinstance(meta, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="回收站元数据格式错误",
        )
    return meta


def _remove_trash_item(item_dir: Path) -> None:
    try:
        shutil.rmtree(item_dir)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"彻底删除回收站条目失败：{exc}",
        ) from exc


def _trash_move(target: Path, rel: str, *, recursive: bool) -> dict[str, Any]:
    """把条目连同内容整体移入回收站并写入元数据；任何失败都会回滚到原位置。

    回收站布局：.trash/<id>/payload/<原名> 保存原内容，.trash/<id>/meta.json
    保存原路径、类型、删除时间与统计信息，供列表与还原使用。
    """
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    existing = sum(1 for item in TRASH_ROOT.iterdir() if item.is_dir())
    if existing >= MAX_TRASH_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"回收站已满（{MAX_TRASH_ITEMS} 项），请先清空回收站",
        )

    item_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        + "-" + uuid.uuid4().hex[:6]
    )
    item_dir = TRASH_ROOT / item_id
    payload_dir = item_dir / TRASH_PAYLOAD
    try:
        payload_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建回收站条目失败：{exc}",
        ) from exc

    moved = payload_dir / target.name
    try:
        _move_path(target, moved)
    except OSError as exc:
        shutil.rmtree(item_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"移入回收站失败：{exc}",
        ) from exc

    is_file = moved.is_file()
    if is_file:
        files: list[Path] = [moved]
        dirs: list[Path] = []
    else:
        files = [item for item in moved.rglob("*") if item.is_file()]
        dirs = [item for item in moved.rglob("*") if item.is_dir()]
    docs = sum(1 for item in files
               if item.suffix.lower() == ".md" and not item.name.startswith("."))
    try:
        size = sum(item.stat().st_size for item in files)
    except OSError:
        size = 0

    meta: dict[str, Any] = {
        "id": item_id,
        "name": target.name,
        "original_path": rel,
        "type": "file" if is_file else "dir",
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "recursive": recursive,
        "removed_docs": docs,
        "removed_files": len(files),
        "removed_dirs": 0 if is_file else len(dirs) + 1,
        "size": size,
    }
    try:
        _atomic_write(item_dir / TRASH_META,
                      json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    except Exception as exc:
        try:
            _move_path(moved, target)
        except OSError:
            pass
        shutil.rmtree(item_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"写入回收站元数据失败：{exc}",
        ) from exc
    return {**meta, "trashed": True}


class DocPayload(BaseModel):
    content: str = Field(..., description="Markdown 源码，UTF-8 文本")


class RenamePayload(BaseModel):
    path: str = Field(..., description="现有文档或目录的相对路径")
    new_name: str = Field(..., description="新名称，不含路径分隔符")


class MovePayload(BaseModel):
    path: str = Field(..., description="待移动的文档或目录相对路径")
    target_dir: str = Field(..., description="目标目录相对路径；空串代表 data/ 顶层")


class RestorePayload(BaseModel):
    id: str = Field(..., description="回收站条目 ID")


class VersionRestorePayload(BaseModel):
    path: str = Field(..., description="文档相对路径")
    version_id: str = Field(..., description="要还原的版本 ID")


class DescriptionPayload(BaseModel):
    content: str = Field(..., description="目录作用说明文本")


@app.get("/api/health", summary="健康检查")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "data_root": str(DATA_ROOT),
        "categories": list(DEFAULT_CATEGORIES),
    }


@app.get("/api/tree", summary="获取 data/ 目录树（目录节点含说明文字）")
def get_tree() -> dict[str, Any]:
    return {
        "root": "data",
        "tree": _scan(DATA_ROOT, Path()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/versions/{version_id}", summary="读取某个历史版本的 Markdown 源码")
def read_version(version_id: str) -> dict[str, Any]:
    blob = _history_blob_path(version_id)
    if not blob.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    try:
        content = blob.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取版本失败：{exc}",
        ) from exc
    return {"version_id": version_id, "content": content, "size": len(content.encode("utf-8"))}


@app.post("/api/history/restore", summary="把文档还原到指定历史版本（会生成新版本）")
def restore_version(payload: VersionRestorePayload) -> dict[str, Any]:
    target, rel = _parse_doc_path(payload.path)
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"文档不存在：{rel}")
    entries = _history_entries(rel)
    if not any(entry.get("id") == payload.version_id for entry in entries):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该版本不属于此文档或已被清理",
        )
    blob = _history_blob_path(payload.version_id)
    if not blob.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本快照缺失")
    try:
        data = blob.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取版本失败：{exc}",
        ) from exc
    if len(data) > MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="历史版本超过当前文档大小上限",
        )
    _atomic_write(target, data)
    new_version = _history_append(rel, data, action="restore",
                                  from_version=payload.version_id)
    return {
        "path": rel, "restored": True,
        "from_version": payload.version_id,
        "version": new_version["id"], "version_number": new_version["version"],
        "size": len(data),
    }


@app.get("/api/history/{doc_path:path}", summary="列出文档的全部历史版本")
def list_history(doc_path: str) -> dict[str, Any]:
    _, rel = _parse_doc_path(doc_path)
    entries = _history_entries(rel)
    versions = [
        {key: entry.get(key) for key in
         ("id", "version", "created_at", "size", "action", "from_version")}
        for entry in entries
    ]
    versions.sort(key=lambda item: item["version"] or 0, reverse=True)
    return {
        "path": rel, "versions": versions,
        "count": len(versions), "max_versions": MAX_VERSIONS_PER_DOC,
    }


@app.delete("/api/history/{doc_path:path}", summary="清空某篇文档的全部历史版本")
def clear_history(doc_path: str) -> dict[str, Any]:
    _, rel = _parse_doc_path(doc_path)
    with HISTORY_LOCK:
        index = _history_read()
        entries = index["docs"].pop(rel, [])
        _history_drop_entries(entries)
        _history_write(index)
    return {"path": rel, "cleared": len(entries)}


@app.get("/api/trash", summary="列出回收站条目（可还原或彻底删除）")
def list_trash() -> dict[str, Any]:
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for item_dir in sorted(TRASH_ROOT.iterdir(), key=lambda item: item.name, reverse=True):
        if not item_dir.is_dir() or item_dir.name.startswith("."):
            continue
        meta_path = item_dir / TRASH_META
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict):
            meta.setdefault("id", item_dir.name)
            items.append(meta)
    return {"items": items, "count": len(items), "max_items": MAX_TRASH_ITEMS}


@app.post("/api/trash/restore", summary="把回收站条目还原到原位置")
def restore_trash(payload: RestorePayload) -> dict[str, Any]:
    item_dir = _trash_item_dir(payload.id)
    if not item_dir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="回收站条目不存在")
    meta = _read_trash_meta(item_dir)
    name = str(meta.get("name") or "")
    payload_path = item_dir / TRASH_PAYLOAD / name
    if not name or not payload_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="回收站条目内容缺失"
        )
    original = str(meta.get("original_path") or "")
    if meta.get("type") == "file":
        target, rel = _parse_doc_path(original)
    else:
        target, rel = _parse_dir_path(original)
    if target.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"原位置已存在同名条目：{rel}，请先移开或重命名",
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _move_path(payload_path, target)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"还原失败：{exc}",
        ) from exc
    shutil.rmtree(item_dir, ignore_errors=True)
    return {"restored": True, "id": payload.id, "path": rel, "type": meta.get("type")}


@app.delete("/api/trash", summary="清空回收站（全部彻底删除，不可恢复）")
def empty_trash() -> dict[str, Any]:
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    removed = 0
    for item_dir in list(TRASH_ROOT.iterdir()):
        if item_dir.is_dir() and not item_dir.name.startswith("."):
            _remove_trash_item(item_dir)
            removed += 1
    return {"purged": removed, "count": 0}


@app.delete("/api/trash/{item_id}", summary="彻底删除单个回收站条目（不可恢复）")
def purge_trash_item(item_id: str) -> dict[str, Any]:
    item_dir = _trash_item_dir(item_id)
    if not item_dir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="回收站条目不存在")
    _remove_trash_item(item_dir)
    return {"id": item_id, "purged": True}


@app.post("/api/dirs/{dir_path:path}", summary="新建目录（未选中目录时创建顶层目录，选中后创建子目录）")
def create_dir(dir_path: str) -> dict[str, Any]:
    target, rel = _parse_dir_path(dir_path)
    if target.exists():
        if not target.is_dir():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同名路径已是文件，无法创建目录",
            )
        return {"path": rel, "created": False}
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建目录失败：{exc}",
        ) from exc
    return {"path": rel, "created": True}


@app.delete("/api/dirs/{dir_path:path}", summary="删除目录并移入回收站；recursive=true 时需名称确认")
def delete_dir(dir_path: str, recursive: bool = False, confirm: str = "") -> dict[str, Any]:
    target, rel = _parse_dir_path(dir_path)
    if not target.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"目录不存在：{rel}")
    _assert_plain_path(target)

    if recursive:
        if confirm.strip() != target.name:
            raise _bad_request("递归删除需要输入完整的目录名作为二次确认")
        try:
            _scan_recursive_items(target)
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"扫描目录失败：{exc}",
            ) from exc
    else:
        try:
            visible = [item for item in target.iterdir() if not item.name.startswith(".")]
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"读取目录失败：{exc}",
            ) from exc
        if visible:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"目录非空，仍有 {len(visible)} 个子项；可使用「清空并移入回收站」，或先清空内容",
            )

    result = _trash_move(target, rel, recursive=recursive)
    return {
        "path": rel,
        "deleted": True,
        "trashed": True,
        "trash_id": result["id"],
        "recursive": recursive,
        "removed_docs": result["removed_docs"],
        "removed_files": result["removed_files"],
        "removed_dirs": result["removed_dirs"],
    }


@app.patch("/api/rename", summary="重命名文档或目录（只改名，不移动位置）")
def rename_entry(payload: RenamePayload) -> dict[str, Any]:
    target, rel = _parse_entry_path(payload.path)
    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"条目不存在：{rel}")
    if target.is_symlink():
        raise _bad_request("不支持重命名符号链接")
    is_file = target.is_file()
    if not is_file and not target.is_dir():
        raise _bad_request("目标既不是文件也不是目录")

    name = _validate_segment(payload.new_name.strip())
    if is_file and not name.lower().endswith(".md"):
        raise _bad_request("文档名必须以 .md 结尾")
    if not is_file and name.lower().endswith(".md"):
        raise _bad_request("目录名不应以 .md 结尾")

    new_target = target.parent / name
    try:
        new_target.resolve().relative_to(DATA_ROOT)
    except ValueError:
        raise _bad_request("路径越出 data/ 根目录")
    if new_target == target:
        return {
            "old_path": rel, "path": rel,
            "type": "file" if is_file else "dir", "renamed": False,
        }
    if new_target.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同目录下已存在同名文件或目录",
        )
    try:
        target.rename(new_target)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"重命名失败：{exc}",
        ) from exc
    new_rel = (Path(rel).parent / name).as_posix()
    _history_repath(rel, new_rel, is_dir=not is_file)
    return {
        "old_path": rel,
        "path": new_rel,
        "type": "file" if is_file else "dir",
        "renamed": True,
    }


@app.patch("/api/move", summary="移动文档或目录到另一目录（支持拖拽整理）")
def move_entry(payload: MovePayload) -> dict[str, Any]:
    source, rel = _parse_entry_path(payload.path)
    destination, dest_rel = _parse_target_dir(payload.target_dir)
    if not source.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"条目不存在：{rel}")
    if source.is_symlink():
        raise _bad_request("不支持移动符号链接")
    is_file = source.is_file()
    if not is_file and not source.is_dir():
        raise _bad_request("目标既不是文件也不是目录")
    if is_file and not source.name.lower().endswith(".md"):
        raise _bad_request("只能移动 .md 文档")
    _assert_plain_path(source)
    _assert_plain_path(destination)
    if not destination.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"目标目录不存在：{dest_rel or 'data/'}",
        )
    if is_file and not dest_rel:
        raise _bad_request("文档必须移动到某个目录中，不能直接放在 data/ 顶层")

    resolved_source = source.resolve()
    resolved_dest = destination.resolve()
    if not is_file and (resolved_dest == resolved_source or resolved_source in resolved_dest.parents):
        raise _bad_request("不能把目录移动到它自己或它的子目录中")
    if source.parent == destination:
        return {
            "old_path": rel, "path": rel,
            "type": "file" if is_file else "dir", "moved": False,
        }

    new_target = destination / source.name
    if new_target.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="目标目录中已存在同名文件或目录，请先重命名",
        )
    try:
        _move_path(source, new_target)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"移动失败：{exc}",
        ) from exc
    new_rel = new_target.resolve().relative_to(DATA_ROOT).as_posix()
    _history_repath(rel, new_rel, is_dir=not is_file)
    return {
        "old_path": rel,
        "path": new_rel,
        "type": "file" if is_file else "dir",
        "moved": True,
    }


@app.put("/api/descriptions/{dir_path:path}", summary="写入目录作用说明（.description.md）")
def save_description(dir_path: str, payload: DescriptionPayload) -> dict[str, Any]:
    target, rel = _parse_dir_path(dir_path)
    if not target.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"目录不存在：{rel}")
    data = payload.content.encode("utf-8")
    if len(data) > MAX_DESCRIPTION_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"说明超过 {MAX_DESCRIPTION_BYTES // 1024} KB 上限",
        )
    _atomic_write(target / DESCRIPTION_FILE, data)
    return {"path": rel, "size": len(data)}


@app.get("/api/docs/{doc_path:path}", summary="读取指定 MD 文件的源码")
def read_doc(doc_path: str) -> dict[str, Any]:
    target, rel = _parse_doc_path(doc_path)
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"文档不存在：{rel}")
    try:
        content = target.read_text(encoding="utf-8")
        stat_result = target.stat()
    except UnicodeDecodeError as exc:
        raise _bad_request("文件不是有效的 UTF-8 文本") from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取失败：{exc}",
        ) from exc
    return {
        "path": rel,
        "content": content,
        "size": stat_result.st_size,
        "modified": _iso_time(stat_result.st_mtime),
    }


@app.put("/api/docs/{doc_path:path}", summary="保存 MD 文件（不存在则新建，存在则覆盖更新）")
def save_doc(doc_path: str, payload: DocPayload) -> dict[str, Any]:
    target, rel = _parse_doc_path(doc_path)
    data = payload.content.encode("utf-8")
    if len(data) > MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文档超过 {MAX_DOC_BYTES // 1024 // 1024} MB 上限",
        )
    existed = target.exists()
    if existed and not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="目标路径不是文件",
        )
    unchanged = False
    if existed:
        try:
            unchanged = target.read_bytes() == data
        except OSError:
            unchanged = False
    _atomic_write(target, data)
    version = None
    if not unchanged:
        version = _history_append(rel, data,
                                  action="updated" if existed else "created")
    return {
        "path": rel,
        "action": "updated" if existed else "created",
        "size": len(data),
        "version": version["id"] if version else None,
        "version_number": version["version"] if version else None,
    }


@app.delete("/api/docs/{doc_path:path}", summary="删除指定 MD 文件并移入回收站")
def delete_doc(doc_path: str) -> dict[str, Any]:
    target, rel = _parse_doc_path(doc_path)
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"文档不存在：{rel}")
    _assert_plain_path(target)
    result = _trash_move(target, rel, recursive=False)
    return {
        "path": rel,
        "deleted": True,
        "trashed": True,
        "trash_id": result["id"],
    }


# 阶段二：同一进程托管纯静态前端页面。
# 已注册的 /api/*、/docs、/openapi.json 路由优先于该根挂载被匹配。
WEB_DIR = BASE_DIR / "web"
if WEB_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("MDFM_HOST", "127.0.0.1"),
        port=int(os.environ.get("MDFM_PORT", "8000")),
    )
