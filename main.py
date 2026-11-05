"""MDFileManager - 阶段一：本地 Markdown 文件的 RESTful API。

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
MAX_NAME_BYTES = 200

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
    version="1.0.0",
    description="本地 Markdown 文档的文件系统映射接口（阶段一：纯 JSON RESTful API）",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_doc_path(doc_path: str) -> tuple[Path, str]:
    """把 'Projects/子目录/文档.md' 解析为 (绝对路径, 相对 data/ 的 posix 路径)。

    任何可能越出 data/ 的路径都在此被拒绝：空段、`.`、`..`、绝对路径、
    盘符、非法字符、隐藏文件、系统保留名、非 .md 后缀，以及符号链接逃逸。
    """
    if not doc_path or "\x00" in doc_path:
        raise _bad_request("文档路径不能为空")
    if doc_path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", doc_path):
        raise _bad_request("不接受绝对路径或盘符路径")

    parts: list[str] = []
    for part in doc_path.split("/"):
        if part in ("", ".", ".."):
            raise _bad_request("路径中包含非法段（空段 / . / ..）")
        if _FORBIDDEN_CHARS.search(part):
            raise _bad_request("路径中包含非法字符")
        if part != part.strip() or part.endswith(".") or part.startswith("."):
            raise _bad_request("名称不能以空格、点开头或结尾")
        if len(part.encode("utf-8")) > MAX_NAME_BYTES:
            raise _bad_request("名称过长")
        if part.split(".")[0].upper() in _WINDOWS_RESERVED:
            raise _bad_request("名称属于系统保留字")
        parts.append(part)

    if len(parts) < 2:
        raise _bad_request("路径必须包含分类目录与文件名，例如 Projects/说明.md")
    if not parts[-1].lower().endswith(".md"):
        raise _bad_request("仅支持 .md 文件")

    rel = Path(*parts)
    target = (DATA_ROOT / rel).resolve()
    try:
        target.relative_to(DATA_ROOT)
    except ValueError:
        raise _bad_request("路径越出 data/ 根目录")
    return target, rel.as_posix()


def _iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


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


class DocPayload(BaseModel):
    content: str = Field(..., description="Markdown 源码，UTF-8 文本")


@app.get("/api/health", summary="健康检查")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "data_root": str(DATA_ROOT),
        "categories": list(DEFAULT_CATEGORIES),
    }


@app.get("/api/tree", summary="获取 data/ 目录的树形结构")
def get_tree() -> dict[str, Any]:
    return {
        "root": "data",
        "tree": _scan(DATA_ROOT, Path()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


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

    # 先写同目录临时文件再原子替换，避免保存过程中产生半截文件。
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
