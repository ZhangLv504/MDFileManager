"""阶段五/六：右键重命名、目录说明与纯卡片导航的可运行结果验证。

运行（在项目根目录）：
    .venv/Scripts/python.exe tests/stage5_smoke_test.py

自动拉起 uvicorn，验证重命名与说明接口、目录树描述字段、卡片视图静态结构，
并用系统自带的无头 Chrome / Edge 检查卡片真实渲染（找不到浏览器时跳过该段）。
退出码 0 表示全部通过；测试目录与文档会被自动清理。
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trash_cleanup import cleanup_test_history, cleanup_test_trash  # noqa: E402

WEB_DIR = BASE_DIR / "web"
TEST_DIR = "Projects/__stage5__目录"
RENAMED_DIR = "Projects/__stage5__已改名"
TEST_DOC = TEST_DIR + "/笔记.md"
RENAMED_DOC = TEST_DIR + "/已改名笔记.md"
CONFLICT_DOC = RENAMED_DIR + "/冲突.md"
MOVE_TARGET = "Projects/__stage5__移动目标"
MOVE_DOC = RENAMED_DIR + "/移动测试.md"
DESCRIPTION = "阶段五卡片验证说明：用于验证目录作用描述与右键重命名。"

BROWSER_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

PASSED = 0
TOTAL = 0
FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    global PASSED, TOTAL
    TOTAL += 1
    if condition:
        PASSED += 1
        print(f"[PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label} {extra}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch(base_url: str, path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        base_url + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def as_json(raw: bytes):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def quote(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


def wait_ready(base_url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            code, _ = fetch(base_url, "/api/health")
            if code == 200:
                return True
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.3)
    return False


def find_node(nodes, path: str):
    for node in nodes:
        if node.get("path") == path:
            return node
        found = find_node(node.get("children", []), path)
        if found:
            return found
    return None


def find_browser() -> Path | None:
    for candidate in BROWSER_CANDIDATES:
        if candidate.is_file():
            return candidate
    for name in ("chrome", "msedge", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def dump_dom(browser: Path, profile_dir: Path, url: str) -> str:
    command = [
        str(browser), "--headless=new", "--disable-gpu", "--no-sandbox",
        "--no-first-run", "--no-default-browser-check", "--disable-dev-shm-usage",
        "--hide-scrollbars", "--virtual-time-budget=12000", "--dump-dom",
        f"--user-data-dir={profile_dir}", url,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
        return result.stdout or ""
    except subprocess.TimeoutExpired:
        return ""


def main() -> int:
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    style_css = (WEB_DIR / "style.css").read_text(encoding="utf-8")

    check("页面包含卡片入口与目录详情页",
          'class="cards"' in index_html and "dir-view" in index_html
          and '@dblclick="openDir(card.path)"' in index_html)
    check("一级卡片不再平铺子目录与文档",
          "card-item" not in index_html and "card-items" not in index_html
          and "tree-node" not in index_html and "sidebar" not in index_html
          and "TreeNode" not in app_js and "CardItem" not in app_js)
    check("页面包含右键菜单与重命名/说明对话框",
          'class="context-menu"' in index_html and "showRename" in index_html
          and "showDescription" in index_html and "@contextmenu.prevent" in index_html)
    check("交互逻辑调用重命名与说明接口",
          "'/api/rename'" in app_js and "'PATCH'" in app_js
          and "'/api/descriptions/'" in app_js and "openContextMenu" in app_js)
    check("目录页数据保证文件夹在前、文档在后",
          "activeDirs" in app_js and "activeFiles" in app_js
          and "sortNodes" in app_js and "a.type === 'dir' ? -1 : 1" in app_js)
    check("卡片与目录页条目为流式布局",
          ".cards {" in style_css and "flex-wrap: wrap" in style_css
          and ".tiles {" in style_css)
    check("页面提供移动到对话框与递归删除菜单",
          "showMove" in index_html and "dir-list" in index_html
          and "清空并移入回收站" in index_html and 'draggable="true"' in index_html)
    check("页面提供回收站面板与角标入口",
          ">回收站<" in index_html and "showTrash" in index_html
          and "trash-badge" in index_html and "restoreTrash(item.id)" in index_html
          and "emptyTrash" in index_html)
    check("交互逻辑接入回收站接口",
          "'/api/trash'" in app_js and "'/api/trash/restore'" in app_js
          and "refreshTrashCount" in app_js and "loadTrash" in app_js)
    check("页面提供版本历史面板与还原入口",
          ">历史<" in index_html and "showHistory" in index_html
          and "history-dialog" in index_html and "restoreVersion" in index_html
          and "clearHistory" in index_html and ".history-dialog" in style_css)
    check("交互逻辑接入版本历史接口",
          "'/api/history/'" in app_js and "'/api/versions/'" in app_js
          and "loadHistory" in app_js and "previewVersion" in app_js)
    check("交互逻辑接入移动与拖拽整理",
          "'/api/move'" in app_js and "moveEntry" in app_js
          and "recursive=true" in app_js and "onDrop" in app_js
          and "onDragStart" in app_js)
    check("样式提供拖拽与放置目标反馈",
          ".dragging" in style_css and ".drop-target" in style_css
          and ".dir-list" in style_css and ".drop-zone" in style_css)

    node_path = shutil.which("node")
    if node_path:
        syntax = subprocess.run(
            [node_path, "--check", str(WEB_DIR / "app.js")],
            capture_output=True, text=True,
        )
        check("app.js 通过 Node 语法检查", syntax.returncode == 0, syntax.stderr[:300])
    else:
        print("[SKIP] 未安装 Node.js，跳过 JS 语法检查")

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    profile_dir = Path(tempfile.mkdtemp(prefix="mdfm-stage5-"))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        check("uvicorn 启动并响应健康检查", wait_ready(base_url))
        if FAILURES:
            return 1

        code, _ = fetch(base_url, "/api/dirs/" + quote(TEST_DIR), "POST")
        check("创建测试目录", code == 200, f"-> {code}")
        code, raw = fetch(base_url, "/api/docs/" + quote(TEST_DOC), "PUT", {"content": "# 笔记\n"})
        check("创建测试文档", code == 200, f"-> {code}")
        code, raw = fetch(base_url, "/api/history/" + quote(TEST_DOC))
        hist = as_json(raw) or {}
        first_version = (hist.get("versions") or [{}])[0].get("id", "")
        check("新建文档自动生成历史快照", code == 200
              and hist.get("count") == 1 and bool(first_version),
              f"-> {code} {raw[:150]}")
        code, raw = fetch(base_url, "/api/versions/" + first_version)
        check("按版本 ID 读取历史源码", code == 200
              and (as_json(raw) or {}).get("content") == "# 笔记\n", f"-> {code}")

        code, raw = fetch(base_url, "/api/descriptions/" + quote(TEST_DIR),
                          "PUT", {"content": DESCRIPTION})
        check("写入目录作用说明", code == 200, f"-> {code} {raw[:120]}")
        code, raw = fetch(base_url, "/api/tree")
        dir_node = find_node((as_json(raw) or {}).get("tree", []), TEST_DIR)
        check("目录树返回正确的说明文字", code == 200 and dir_node
              and dir_node.get("description") == DESCRIPTION, f"-> {code}")
        check("说明文件不出现在文档列表中",
              find_node((as_json(raw) or {}).get("tree", []), TEST_DIR + "/.description.md") is None)

        code, raw = fetch(base_url, "/api/rename", "PATCH",
                          {"path": TEST_DOC, "new_name": "已改名笔记.md"})
        renamed = as_json(raw)
        check("重命名文档成功", code == 200 and renamed
              and renamed.get("renamed") is True and renamed.get("type") == "file"
              and renamed.get("path") == RENAMED_DOC, f"-> {code} {raw[:160]}")
        code, _ = fetch(base_url, "/api/docs/" + quote(RENAMED_DOC))
        check("新文档路径可读", code == 200, f"-> {code}")
        code, _ = fetch(base_url, "/api/docs/" + quote(TEST_DOC))
        check("旧文档路径已失效", code == 404, f"-> {code}")
        code, raw = fetch(base_url, "/api/history/" + quote(RENAMED_DOC))
        code_old, raw_old = fetch(base_url, "/api/history/" + quote(TEST_DOC))
        check("重命名后历史迁移到新文档路径",
              (as_json(raw) or {}).get("count") == 1
              and (as_json(raw_old) or {}).get("count") == 0,
              f"-> new={(as_json(raw) or {}).get('count')} old={(as_json(raw_old) or {}).get('count')}")

        code, raw = fetch(base_url, "/api/rename", "PATCH",
                          {"path": TEST_DIR, "new_name": "__stage5__已改名"})
        renamed_dir = as_json(raw)
        check("重命名目录成功", code == 200 and renamed_dir
              and renamed_dir.get("type") == "dir"
              and renamed_dir.get("path") == RENAMED_DIR, f"-> {code} {raw[:160]}")
        code, _ = fetch(base_url, "/api/docs/" + quote(RENAMED_DIR + "/已改名笔记.md"))
        check("目录改名后其下文档仍可访问", code == 200, f"-> {code}")
        code, raw = fetch(base_url, "/api/history/" + quote(RENAMED_DIR + "/已改名笔记.md"))
        check("目录改名后其下文档历史一并迁移",
              (as_json(raw) or {}).get("count") == 1, f"-> {code} {raw[:120]}")
        code, raw = fetch(base_url, "/api/tree")
        check("目录树呈现改名后的目录",
              find_node((as_json(raw) or {}).get("tree", []), RENAMED_DIR) is not None
              and find_node((as_json(raw) or {}).get("tree", []), TEST_DIR) is None, f"-> {code}")

        code, _ = fetch(base_url, "/api/docs/" + quote(CONFLICT_DOC), "PUT", {"content": "x"})
        code, _ = fetch(base_url, "/api/rename", "PATCH",
                        {"path": RENAMED_DIR + "/已改名笔记.md", "new_name": "冲突.md"})
        check("重命名为已存在名称返回 409", code == 409, f"-> {code}")

        code, raw = fetch(base_url, "/api/rename", "PATCH",
                          {"path": RENAMED_DIR + "/已改名笔记.md",
                           "new_name": "已改名笔记.md"})
        again = as_json(raw)
        check("重命名为同名时幂等返回 renamed=false", code == 200
              and again and again.get("renamed") is False, f"-> {code} {raw[:160]}")

        for bad in ("../evil.md", "a/b.md", ".hidden.md", "noext", "CON"):
            code, _ = fetch(base_url, "/api/rename", "PATCH",
                            {"path": RENAMED_DIR + "/已改名笔记.md", "new_name": bad})
            check(f"重命名拒绝非法名称：{bad}", code == 400, f"-> {code}")
        code, _ = fetch(base_url, "/api/rename", "PATCH",
                        {"path": RENAMED_DIR, "new_name": "像文档.md"})
        check("重命名拒绝目录使用 .md 名称", code == 400, f"-> {code}")

        empty_del_dir = "Projects/__stage5__空目录"
        code, _ = fetch(base_url, "/api/dirs/" + quote(empty_del_dir), "POST")
        check("准备一个空目录", code == 200, f"-> {code}")
        code, raw = fetch(base_url, "/api/dirs/" + quote(empty_del_dir), "DELETE")
        deleted = as_json(raw)
        check("删除空目录接口可用", code == 200 and deleted
              and deleted.get("deleted") is True, f"-> {code} {raw[:120]}")
        check("删除空目录返回回收站编号", bool(deleted)
              and deleted.get("trashed") is True and bool(deleted.get("trash_id")),
              f"-> {raw[:120]}")
        code, raw = fetch(base_url, "/api/trash")
        listing = as_json(raw) or {}
        check("回收站列表包含该空目录", code == 200
              and any(item.get("original_path") == empty_del_dir
                      for item in listing.get("items", [])), f"-> {code} {raw[:150]}")
        check("回收站列表返回条目总数", isinstance(listing.get("count"), int), f"-> {raw[:80]}")
        code, raw = fetch(base_url, "/api/trash/restore", "POST", {"id": deleted["trash_id"]})
        restored = as_json(raw)
        check("还原空目录到原位置", code == 200 and restored
              and restored.get("path") == empty_del_dir, f"-> {code} {raw[:150]}")
        code, _ = fetch(base_url, "/api/trash/restore", "POST", {"id": "../evil"})
        check("还原接口拒绝非法条目 ID", code == 400, f"-> {code}")
        code, raw = fetch(base_url, "/api/dirs/" + quote(empty_del_dir), "DELETE")
        second = as_json(raw) or {}
        code, raw = fetch(base_url, "/api/trash/" + second.get("trash_id", "__none__"), "DELETE")
        check("彻底删除单个回收站条目", code == 200
              and (as_json(raw) or {}).get("purged") is True, f"-> {code} {raw[:120]}")
        code, _ = fetch(base_url, "/api/dirs/" + quote(RENAMED_DIR), "DELETE")
        check("非空目录拒绝删除返回 409", code == 409, f"-> {code}")

        # 阶段九：拖拽整理（移动）与递归删除接口
        code, _ = fetch(base_url, "/api/dirs/" + quote(MOVE_TARGET), "POST")
        check("准备移动目标目录", code == 200, f"-> {code}")
        code, _ = fetch(base_url, "/api/docs/" + quote(MOVE_DOC), "PUT", {"content": "# 移动测试\n"})
        check("准备待移动文档", code == 200, f"-> {code}")
        code, raw = fetch(base_url, "/api/move", "PATCH",
                          {"path": MOVE_DOC, "target_dir": MOVE_TARGET})
        moved = as_json(raw)
        moved_path = MOVE_TARGET + "/移动测试.md"
        check("移动文档到目标目录", code == 200 and moved
              and moved.get("moved") is True and moved.get("path") == moved_path,
              f"-> {code} {raw[:160]}")
        code, _ = fetch(base_url, "/api/docs/" + quote(MOVE_DOC))
        check("移动后旧路径失效", code == 404, f"-> {code}")
        code, _ = fetch(base_url, "/api/docs/" + quote(moved_path))
        check("移动后新路径可读", code == 200, f"-> {code}")
        code, raw = fetch(base_url, "/api/move", "PATCH",
                          {"path": moved_path, "target_dir": MOVE_TARGET})
        check("移动到当前目录幂等返回 moved=false", code == 200
              and (as_json(raw) or {}).get("moved") is False, f"-> {code} {raw[:120]}")
        code, _ = fetch(base_url, "/api/move", "PATCH",
                        {"path": moved_path, "target_dir": "../escape"})
        check("移动接口拒绝路径遍历目标", code in (400, 403, 404), f"-> {code}")
        code, _ = fetch(base_url, "/api/docs/" + quote(MOVE_TARGET + "/子级/笔记.md"),
                        "PUT", {"content": "# 深层\n"})
        check("递归删除前准备嵌套文档", code == 200, f"-> {code}")
        rec_url = ("/api/dirs/" + quote(MOVE_TARGET)
                   + "?recursive=true&confirm=" + urllib.parse.quote("__stage5__移动目标"))
        code, raw = fetch(base_url, rec_url, "DELETE")
        removed = as_json(raw)
        check("带名称确认递归删除目录及其内容", code == 200 and removed
              and removed.get("recursive") is True
              and removed.get("removed_docs") >= 1, f"-> {code} {raw[:160]}")
        code, raw = fetch(base_url, "/api/tree")
        check("递归删除后目标目录从树中消失", code == 200
              and find_node((as_json(raw) or {}).get("tree", []), MOVE_TARGET) is None,
              f"-> {code}")
        code, _ = fetch(base_url, "/api/dirs/" + quote(MOVE_TARGET)
                        + "?recursive=true&confirm=" + urllib.parse.quote("错误"), "DELETE")
        check("递归删除不存在的目录返回 404", code == 404, f"-> {code}")

        browser = find_browser()
        if browser:
            print(f"使用浏览器：{browser}")
            dom = dump_dom(browser, profile_dir, base_url + "/")
            check("无头浏览器返回卡片页面 DOM", len(dom) > 2000 and "<html" in dom.lower(),
                  f"-> {len(dom)} 字符")
            check("顶层目录以卡片形式渲染",
                  "文档库" in dom and 'class="card"' in dom and "card-desc" in dom)
            check("卡片页不再包含侧栏树", "tree-row" not in dom and "sidebar" not in dom)
            check("卡片只展示概要，不罗列子目录与文档",
                  "card-items" not in dom and "chip dir" not in dom
                  and "双击进入目录" in dom)
            dir_dom = dump_dom(browser, profile_dir, base_url + "/#/dir/Projects")
            check("目录深链接打开独立目录页",
                  "dir-view" in dir_dom and "breadcrumb" in dir_dom
                  and "编辑说明" in dir_dom)
            check("目录页文件夹在前、文档在后",
                  dir_dom.find("dir-tile") >= 0
                  and dir_dom.find("doc-tile") > dir_dom.find("dir-tile"),
                  f"-> dir={dir_dom.find('dir-tile')} doc={dir_dom.find('doc-tile')}")
            check("目录页真实 DOM 含可拖拽条目与移动放置区",
                  'draggable="true"' in dir_dom and "移动到上级" in dir_dom)
            check("卡片提供说明编辑入口", "编辑说明" in dom)
        else:
            print("[SKIP] 未找到 Chrome / Edge，跳过卡片真实渲染检查")
    finally:
        for relative in (RENAMED_DIR, TEST_DIR, MOVE_TARGET, "Projects/__stage5__空目录"):
            shutil.rmtree(BASE_DIR / "data" / relative, ignore_errors=True)
        cleanup_test_trash(BASE_DIR)
        cleanup_test_history(BASE_DIR)
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)
        output = server.stdout.read() if server.stdout else ""
        if output.strip():
            print("--- uvicorn 输出 ---")
            print(output.strip()[-1500:])

    print(f"\n结果：{PASSED}/{TOTAL} 项通过")
    if FAILURES:
        print("失败项：" + "、".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
