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

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_ROOT = (BASE_DIR / "data").resolve()
DEFAULT_CATEGORIES = ("Projects", "Knowledge")
MAX_DOC_BYTES = 5 * 1024 * 1024
MAX_DESCRIPTION_BYTES = 20 * 1024
DESCRIPTION_CHARS = 500
DESCRIPTION_FILE = ".description.md"
MAX_NAME_BYTES = 200
MAX_RECURSIVE_ITEMS = 2000

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
    for category in DEFAULT_CATEGORIES:
        (DATA_ROOT / category).mkdir(parents=True, exist_ok=True)


_ensure_data_root()

app = FastAPI(
    title="MDFileManager API",
    version="1.3.0",
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


def _plan_recursive_delete(directory: Path) -> tuple[list[Path], list[Path]]:
    """先完整扫描再删除：返回 (文件列表, 子目录列表)，遇到符号链接直接拒绝。"""
    files: list[Path] = []
    dirs: list[Path] = []
    for entry in directory.iterdir():
        if entry.is_symlink():
            raise _bad_request(f"目录内包含符号链接（{entry.name}），拒绝递归删除")
        if entry.is_dir():
            sub_files, sub_dirs = _plan_recursive_delete(entry)
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


class DocPayload(BaseModel):
    content: str = Field(..., description="Markdown 源码，UTF-8 文本")


class RenamePayload(BaseModel):
    path: str = Field(..., description="现有文档或目录的相对路径")
    new_name: str = Field(..., description="新名称，不含路径分隔符")


class MovePayload(BaseModel):
    path: str = Field(..., description="待移动的文档或目录相对路径")
    target_dir: str = Field(..., description="目标目录相对路径；空串代表 data/ 顶层")


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


@app.delete("/api/dirs/{dir_path:path}", summary="删除目录；recursive=true 时带名称确认递归删除")
def delete_dir(dir_path: str, recursive: bool = False, confirm: str = "") -> dict[str, Any]:
    target, rel = _parse_dir_path(dir_path)
    if not target.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"目录不存在：{rel}")
    _assert_plain_path(target)

    if recursive:
        if confirm.strip() != target.name:
            raise _bad_request("递归删除需要输入完整的目录名作为二次确认")
        try:
            files, dirs = _plan_recursive_delete(target)
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"扫描目录失败：{exc}",
            ) from exc
        docs = sum(1 for item in files
                   if item.suffix.lower() == ".md" and not item.name.startswith("."))
        try:
            for item in files:
                item.unlink()
            for directory in reversed(dirs):
                directory.rmdir()
            target.rmdir()
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"递归删除失败：{exc}",
            ) from exc
        return {
            "path": rel, "deleted": True, "recursive": True,
            "removed_docs": docs,
            "removed_files": len(files),
            "removed_dirs": len(dirs) + 1,
        }

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
            detail=f"目录非空，仍有 {len(visible)} 个子项；可使用「清空并删除目录」，或先清空内容",
        )
    removed: list[str] = []
    for name in (".gitkeep", DESCRIPTION_FILE):
        hidden = target / name
        if hidden.is_file():
            try:
                hidden.unlink()
                removed.append(name)
            except OSError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"清理占位文件失败：{exc}",
                ) from exc
    try:
        target.rmdir()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除目录失败：{exc}",
        ) from exc
    return {"path": rel, "deleted": True, "recursive": False, "removed_files": removed}


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
        source.rename(new_target)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"移动失败：{exc}",
        ) from exc
    new_rel = new_target.resolve().relative_to(DATA_ROOT).as_posix()
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
    _atomic_write(target, data)
    return {
        "path": rel,
        "action": "updated" if existed else "created",
        "size": len(data),
    }


@app.delete("/api/docs/{doc_path:path}", summary="删除指定 MD 文件")
def delete_doc(doc_path: str) -> dict[str, Any]:
    target, rel = _parse_doc_path(doc_path)
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"文档不存在：{rel}")
    try:
        target.unlink()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除失败：{exc}",
        ) from exc
    return {"path": rel, "deleted": True}


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
