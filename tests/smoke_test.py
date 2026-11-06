"""阶段一/四可运行结果验证：自动拉起 uvicorn，端到端验证文档与目录 API、安全边界。

运行（在项目根目录）：
    .venv/Scripts/python.exe tests/smoke_test.py
退出码 0 表示全部通过；脚本会自动清理自己创建的测试文档与目录。
"""
from __future__ import annotations

import json
import os
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
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trash_cleanup import cleanup_test_history, cleanup_test_trash  # noqa: E402

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


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                return error.code, raw.decode("utf-8", errors="replace")


def wait_ready(client: ApiClient, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            code, _ = client.call("GET", "/api/health")
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


def find_trash_item(items, original_path: str):
    for item in items:
        if item.get("original_path") == original_path:
            return item
    return None


def main() -> int:
    port = free_port()
    client = ApiClient(f"http://127.0.0.1:{port}")
    # 用独立临时目录做回收站与版本历史，隔离本脚本的所有删除/清空操作。
    trash_dir = Path(tempfile.mkdtemp(prefix="mdfm-smoke-trash-"))
    history_dir = Path(tempfile.mkdtemp(prefix="mdfm-smoke-history-"))
    server_env = dict(os.environ)
    server_env["MDFM_TRASH_DIR"] = str(trash_dir)
    server_env["MDFM_HISTORY_DIR"] = str(history_dir)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BASE_DIR),
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    doc_a = "Projects/__smoke__中文文档.md"
    doc_b = "Knowledge/__smoke__前端/__smoke__渲染说明.md"
    test_dir = "Projects/__smoke__目录A/__smoke__子目录B"
    doc_in_dir = test_dir + "/说明.md"
    move_src_dir = "Projects/__smoke__可移动目录"
    move_dst_dir = "Knowledge/__smoke__目标目录"
    move_doc = move_src_dir + "/待移动.md"
    recursive_dir = "Knowledge/__smoke__递归删除"
    trash_doc = "Projects/__smoke__回收站文档.md"
    trash_dir = "Knowledge/__smoke__回收站目录"
    trash_nested_doc = trash_dir + "/子级/笔记.md"
    hist_doc = "Projects/__smoke__历史文档.md"
    hist_renamed = "Projects/__smoke__历史改名.md"
    hist_moved = "Knowledge/__smoke__历史改名.md"
    hist_dir = "Projects/__smoke__历史目录"
    hist_dir_renamed = "Projects/__smoke__历史目录改名"
    hist_nested = hist_dir + "/笔记.md"
    hist_nested_renamed = hist_dir_renamed + "/笔记.md"
    try:
        check("uvicorn 服务启动并响应 /api/health", wait_ready(client))
        if FAILURES:
            return 1

        code, health = client.call("GET", "/api/health")
        check("健康检查返回 ok 与基础分类", code == 200 and health.get("status") == "ok"
              and set(health.get("categories", [])) >= {"Projects", "Knowledge"}, f"-> {code} {health}")

        code, tree = client.call("GET", "/api/tree")
        check("目录树包含 Projects / Knowledge", code == 200
              and find_node(tree.get("tree", []), "Projects") is not None
              and find_node(tree.get("tree", []), "Knowledge") is not None, f"-> {code}")

        content_a = "# 冒烟测试\n\n| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n\n```python\nprint('hello')\n```\n"
        enc_a = urllib.parse.quote(doc_a, safe="/")
        code, created = client.call("PUT", f"/api/docs/{enc_a}", {"content": content_a})
        check("PUT 新建中文文件名文档", code == 200 and created.get("action") == "created",
              f"-> {code} {created}")

        code, read_back = client.call("GET", f"/api/docs/{enc_a}")
        check("GET 读回 Markdown 源码完全一致", code == 200
              and read_back.get("content") == content_a, f"-> {code}")

        content_a2 = "# 已更新\n\n同名覆盖即版本更新。\n"
        code, updated = client.call("PUT", f"/api/docs/{enc_a}", {"content": content_a2})
        check("PUT 同名文件执行覆盖更新", code == 200 and updated.get("action") == "updated",
              f"-> {code} {updated}")

        code, read_back2 = client.call("GET", f"/api/docs/{enc_a}")
        check("覆盖后读回的是新内容", code == 200
              and read_back2.get("content") == content_a2, f"-> {code}")

        code, tree2 = client.call("GET", "/api/tree")
        check("目录树中出现新建文档", code == 200
              and find_node(tree2.get("tree", []), doc_a) is not None, f"-> {code}")

        enc_b = urllib.parse.quote(doc_b, safe="/")
        code, nested = client.call("PUT", f"/api/docs/{enc_b}", {"content": "# 多级目录\n"})
        check("PUT 自动创建多级子目录", code == 200 and nested.get("action") == "created",
              f"-> {code} {nested}")
        code, tree3 = client.call("GET", "/api/tree")
        check("目录树中呈现多级子目录节点", code == 200
              and find_node(tree3.get("tree", []), "Knowledge/__smoke__前端") is not None
              and find_node(tree3.get("tree", []), doc_b) is not None, f"-> {code}")

        enc_dir = urllib.parse.quote(test_dir, safe="/")
        code, made = client.call("POST", f"/api/dirs/{enc_dir}")
        check("POST 创建多级目录（含父目录）", code == 200
              and made and made.get("created") is True, f"-> {code} {made}")
        code, again = client.call("POST", f"/api/dirs/{enc_dir}")
        check("重复创建同一目录幂等返回 created=false", code == 200
              and again and again.get("created") is False, f"-> {code} {again}")
        code, tree4 = client.call("GET", "/api/tree")
        check("目录树中出现新建的空目录节点", code == 200
              and find_node(tree4.get("tree", []), test_dir) is not None, f"-> {code}")
        enc_in_dir = urllib.parse.quote(doc_in_dir, safe="/")
        code, child = client.call("PUT", f"/api/docs/{enc_in_dir}", {"content": "# 目录内文档\n"})
        check("在新建目录下创建 .md 文档", code == 200
              and child and child.get("action") == "created", f"-> {code} {child}")
        code, _ = client.call("POST", "/api/dirs/Projects/%2e%2e%2fescape_dir")
        check("目录接口拒绝路径遍历", code in (400, 403, 404), f"-> {code}")
        check("目录接口未在 data/ 外创建目录", not (BASE_DIR / "escape_dir").exists())
        code, _ = client.call("POST", "/api/dirs/Projects/__smoke__bad.md")
        check("目录接口拒绝以 .md 结尾的目录名", code == 400, f"-> {code}")

        empty_dir = "Projects/__smoke__待删目录"
        enc_empty = urllib.parse.quote(empty_dir, safe="/")
        code, _ = client.call("POST", f"/api/dirs/{enc_empty}")
        check("准备一个空目录", code == 200, f"-> {code}")
        code, removed = client.call("DELETE", f"/api/dirs/{enc_empty}")
        check("DELETE 删除空目录", code == 200 and removed
              and removed.get("deleted") is True, f"-> {code} {removed}")
        code, _ = client.call("DELETE", f"/api/dirs/{enc_empty}")
        check("删除已不存在的目录返回 404", code == 404, f"-> {code}")
        code, _ = client.call("DELETE", f"/api/dirs/{enc_dir}")
        check("非空目录拒绝删除返回 409", code == 409, f"-> {code}")

        # 阶段九：移动（拖拽整理）接口
        enc_src = urllib.parse.quote(move_src_dir, safe="/")
        enc_dst = urllib.parse.quote(move_dst_dir, safe="/")
        code, _ = client.call("POST", f"/api/dirs/{enc_src}")
        check("准备移动来源目录", code == 200, f"-> {code}")
        code, _ = client.call("POST", f"/api/dirs/{enc_dst}")
        check("准备移动目标目录", code == 200, f"-> {code}")
        code, _ = client.call("PUT", f"/api/docs/{urllib.parse.quote(move_doc, safe='/')}",
                              {"content": "# 待移动\n"})
        check("准备待移动文档", code == 200, f"-> {code}")

        code, moved = client.call("PATCH", "/api/move",
                                  {"path": move_doc, "target_dir": move_dst_dir})
        check("PATCH 移动文档到另一目录", code == 200 and moved
              and moved.get("moved") is True and moved.get("type") == "file"
              and moved.get("path") == move_dst_dir + "/待移动.md", f"-> {code} {moved}")
        code, _ = client.call("GET", f"/api/docs/{urllib.parse.quote(move_doc, safe='/')}")
        check("移动后旧文档路径失效", code == 404, f"-> {code}")
        code, _ = client.call("GET", f"/api/docs/{urllib.parse.quote(move_dst_dir + '/待移动.md', safe='/')}")
        check("移动后新文档路径可读", code == 200, f"-> {code}")
        code, same = client.call("PATCH", "/api/move",
                                 {"path": move_dst_dir + "/待移动.md", "target_dir": move_dst_dir})
        check("移动到当前所在目录幂等返回 moved=false", code == 200 and same
              and same.get("moved") is False, f"-> {code} {same}")

        code, _ = client.call("PUT", f"/api/docs/{urllib.parse.quote(move_doc, safe='/')}",
                              {"content": "# 同名冲突\n"})
        code, _ = client.call("PATCH", "/api/move",
                              {"path": move_doc, "target_dir": move_dst_dir})
        check("目标目录存在同名文档时返回 409", code == 409, f"-> {code}")

        code, moved_dir = client.call("PATCH", "/api/move",
                                      {"path": move_src_dir, "target_dir": move_dst_dir})
        moved_src = move_dst_dir + "/__smoke__可移动目录"
        check("PATCH 移动整个目录（含子项）", code == 200 and moved_dir
              and moved_dir.get("type") == "dir" and moved_dir.get("path") == moved_src,
              f"-> {code} {moved_dir}")
        code, _ = client.call("GET", f"/api/docs/{urllib.parse.quote(moved_src + '/待移动.md', safe='/')}")
        check("目录移动后其内部文档仍可访问", code == 200, f"-> {code}")

        code, _ = client.call("POST", f"/api/dirs/{urllib.parse.quote(moved_src + '/子级', safe='/')}")
        check("准备子目录用于循环移动校验", code == 200, f"-> {code}")
        code, _ = client.call("PATCH", "/api/move",
                              {"path": moved_src, "target_dir": moved_src + "/子级"})
        check("拒绝把目录移动到自己的子目录", code == 400, f"-> {code}")
        code, _ = client.call("PATCH", "/api/move",
                              {"path": moved_src, "target_dir": moved_src})
        check("拒绝把目录移动到自己", code == 400, f"-> {code}")
        code, _ = client.call("PATCH", "/api/move",
                              {"path": move_dst_dir + "/待移动.md", "target_dir": ""})
        check("拒绝把文档移动到 data/ 顶层", code == 400, f"-> {code}")
        code, _ = client.call("PATCH", "/api/move",
                              {"path": move_dst_dir + "/待移动.md", "target_dir": "../escape"})
        check("移动接口拒绝路径遍历的目标目录", code in (400, 403, 404), f"-> {code}")
        code, _ = client.call("PATCH", "/api/move",
                              {"path": "Projects/__smoke__不存在.md", "target_dir": move_dst_dir})
        check("移动不存在的条目返回 404", code == 404, f"-> {code}")
        code, tree_moved = client.call("GET", "/api/tree")
        check("目录树反映移动后的路径", code == 200
              and find_node(tree_moved.get("tree", []), moved_src) is not None
              and find_node(tree_moved.get("tree", []), move_src_dir) is None, f"-> {code}")

        # 阶段九：带名称确认的递归删除
        enc_rec = urllib.parse.quote(recursive_dir, safe="/")
        code, _ = client.call("POST", f"/api/dirs/{enc_rec}")
        check("准备递归删除测试目录", code == 200, f"-> {code}")
        code, _ = client.call("POST", f"/api/dirs/{urllib.parse.quote(recursive_dir + '/子目录', safe='/')}")
        check("递归删除目录内创建子目录", code == 200, f"-> {code}")
        code, _ = client.call("PUT", f"/api/docs/{urllib.parse.quote(recursive_dir + '/子目录/笔记.md', safe='/')}",
                              {"content": "# 会被一起删除\n"})
        check("递归删除目录内创建文档", code == 200, f"-> {code}")
        code, _ = client.call("PUT", f"/api/descriptions/{enc_rec}", {"content": "待删除说明"})
        check("递归删除目录写入说明占位文件", code == 200, f"-> {code}")
        code, _ = client.call("DELETE", f"/api/dirs/{enc_rec}?recursive=true&confirm="
                              + urllib.parse.quote("错误名称"))
        check("递归删除缺少正确名称确认时返回 400", code == 400, f"-> {code}")
        code, removed_all = client.call(
            "DELETE", f"/api/dirs/{enc_rec}?recursive=true&confirm="
            + urllib.parse.quote("__smoke__递归删除"))
        check("递归删除目录及其全部内容", code == 200 and removed_all
              and removed_all.get("recursive") is True
              and removed_all.get("removed_docs") == 1
              and removed_all.get("removed_dirs") >= 2, f"-> {code} {removed_all}")
        code, tree_final = client.call("GET", "/api/tree")
        check("递归删除后目录从目录树消失", code == 200
              and find_node(tree_final.get("tree", []), recursive_dir) is None, f"-> {code}")
        code, _ = client.call("DELETE", f"/api/dirs/{enc_rec}")
        check("递归删除后再次删除返回 404", code == 404, f"-> {code}")

        # 阶段十：删除改为移入回收站，可还原 / 彻底删除 / 清空
        enc_tdoc = urllib.parse.quote(trash_doc, safe="/")
        code, _ = client.call("PUT", f"/api/docs/{enc_tdoc}", {"content": "# 回收站测试\n"})
        check("准备删除后进入回收站的文档", code == 200, f"-> {code}")
        code, trashed = client.call("DELETE", f"/api/docs/{enc_tdoc}")
        check("删除文档返回 trashed 与 trash_id", code == 200 and trashed
              and trashed.get("trashed") is True and bool(trashed.get("trash_id")),
              f"-> {code} {trashed}")
        code, listing = client.call("GET", "/api/trash")
        item = find_trash_item((listing or {}).get("items", []), trash_doc)
        check("回收站列表出现该文档且带原路径/类型/时间", code == 200 and item
              and item.get("type") == "file" and item.get("deleted_at")
              and item.get("id") == trashed.get("trash_id"), f"-> {code} {item}")
        code, _ = client.call("GET", f"/api/docs/{enc_tdoc}")
        check("删除后原路径返回 404", code == 404, f"-> {code}")
        code, restored = client.call("POST", "/api/trash/restore", {"id": trashed["trash_id"]})
        check("从回收站还原文档到原路径", code == 200 and restored
              and restored.get("restored") is True and restored.get("path") == trash_doc,
              f"-> {code} {restored}")
        code, raw = client.call("GET", f"/api/docs/{enc_tdoc}")
        check("还原后内容完整可读", code == 200 and raw
              and raw.get("content") == "# 回收站测试\n", f"-> {code}")
        code, _ = client.call("POST", "/api/trash/restore", {"id": trashed["trash_id"]})
        check("重复还原同一条目返回 404", code == 404, f"-> {code}")

        code, second = client.call("DELETE", f"/api/docs/{enc_tdoc}")
        check("再次删除文档生成新回收站条目", code == 200 and second
              and second.get("trash_id") != trashed.get("trash_id"), f"-> {code} {second}")
        code, _ = client.call("PUT", f"/api/docs/{enc_tdoc}", {"content": "# 占用原位置\n"})
        code, _ = client.call("POST", "/api/trash/restore", {"id": second["trash_id"]})
        check("原位置已被占用时还原返回 409", code == 409, f"-> {code}")
        code, purged = client.call("DELETE", "/api/trash/" + second["trash_id"])
        check("彻底删除单个回收站条目", code == 200 and purged
              and purged.get("purged") is True, f"-> {code} {purged}")
        code, listing = client.call("GET", "/api/trash")
        check("彻底删除后回收站不再包含该条目", code == 200
              and not any(i.get("id") == second["trash_id"]
                          for i in (listing or {}).get("items", [])), f"-> {code}")

        enc_tdir = urllib.parse.quote(trash_dir, safe="/")
        code, _ = client.call("POST", f"/api/dirs/{enc_tdir}")
        check("准备带子项的回收站目录", code == 200, f"-> {code}")
        code, _ = client.call("PUT", f"/api/docs/{urllib.parse.quote(trash_nested_doc, safe='/')}",
                              {"content": "# 深层笔记\n"})
        check("回收站目录内创建嵌套文档", code == 200, f"-> {code}")
        code, _ = client.call("PUT", f"/api/descriptions/{enc_tdir}", {"content": "随目录一起还原"})
        code, dir_trashed = client.call("DELETE", f"/api/dirs/{enc_tdir}?recursive=true&confirm="
                                        + urllib.parse.quote("__smoke__回收站目录"))
        check("递归删除目录同样移入回收站", code == 200 and dir_trashed
              and dir_trashed.get("trashed") is True
              and dir_trashed.get("removed_docs") >= 1, f"-> {code} {dir_trashed}")
        code, listing = client.call("GET", "/api/trash")
        dir_item = find_trash_item((listing or {}).get("items", []), trash_dir)
        check("回收站列表包含整个目录", code == 200 and dir_item
              and dir_item.get("type") == "dir" and dir_item.get("recursive") is True,
              f"-> {code} {dir_item}")
        code, restored_dir = client.call("POST", "/api/trash/restore",
                                         {"id": dir_trashed["trash_id"]})
        check("还原整个目录（含子目录与文档）", code == 200 and restored_dir
              and restored_dir.get("path") == trash_dir, f"-> {code} {restored_dir}")
        code, _ = client.call("GET", f"/api/docs/{urllib.parse.quote(trash_nested_doc, safe='/')}")
        check("还原后嵌套文档仍可访问", code == 200, f"-> {code}")
        code, tree_restored = client.call("GET", "/api/tree")
        restored_node = find_node(tree_restored.get("tree", []), trash_dir)
        check("还原后目录说明一并恢复", code == 200 and restored_node
              and restored_node.get("description") == "随目录一起还原", f"-> {code}")

        code, _ = client.call("POST", "/api/trash/restore", {"id": "../evil"})
        check("还原接口拒绝非法条目 ID", code == 400, f"-> {code}")
        code, _ = client.call("DELETE", "/api/trash/__smoke__missing__")
        check("彻底删除不存在的条目返回 404", code == 404, f"-> {code}")
        code, emptied = client.call("DELETE", "/api/trash")
        check("清空回收站返回删除条数", code == 200 and emptied
              and emptied.get("purged") >= 1, f"-> {code} {emptied}")
        code, listing = client.call("GET", "/api/trash")
        check("清空后回收站为空", code == 200
              and (listing or {}).get("count") == 0, f"-> {code} {listing}")

        # 阶段十一：文档版本历史（保存快照、查看、还原、迁移、清空）
        enc_hist = urllib.parse.quote(hist_doc, safe="/")
        enc_hist_renamed = urllib.parse.quote(hist_renamed, safe="/")
        enc_hist_moved = urllib.parse.quote(hist_moved, safe="/")
        code, first = client.call("PUT", f"/api/docs/{enc_hist}", {"content": "# 第一版\n"})
        check("新建文档生成首个历史版本", code == 200 and first
              and first.get("version") and first.get("version_number") == 1,
              f"-> {code} {first}")
        first_id = first["version"]
        code, hist = client.call("GET", f"/api/history/{enc_hist}")
        check("历史列表返回 1 个 created 版本", code == 200 and hist
              and hist.get("count") == 1
              and hist["versions"][0].get("action") == "created", f"-> {code} {hist}")
        code, ver = client.call("GET", "/api/versions/" + first_id)
        check("按版本 ID 读取快照内容", code == 200 and ver
              and ver.get("content") == "# 第一版\n", f"-> {code} {ver}")
        code, same = client.call("PUT", f"/api/docs/{enc_hist}", {"content": "# 第一版\n"})
        check("内容未变化时不再新增历史版本", code == 200 and same
              and same.get("version") is None, f"-> {code} {same}")
        code, hist2 = client.call("GET", f"/api/history/{enc_hist}")
        check("重复保存后历史仍为 1 个版本", code == 200
              and hist2.get("count") == 1, f"-> {code} {hist2}")
        code, second = client.call("PUT", f"/api/docs/{enc_hist}", {"content": "# 第二版\n"})
        check("同名覆盖生成第二个历史版本", code == 200 and second
              and second.get("version_number") == 2, f"-> {code} {second}")
        code, hist3 = client.call("GET", f"/api/history/{enc_hist}")
        check("历史列表按版本倒序返回 2 个版本", code == 200
              and hist3.get("count") == 2
              and hist3["versions"][0].get("version") == 2, f"-> {code} {hist3}")
        code, _ = client.call("GET", "/api/versions/bad.id")
        check("读取非法版本 ID 返回 400", code == 400, f"-> {code}")
        code, _ = client.call("GET", "/api/versions/__smoke__missing__")
        check("读取不存在的版本返回 404", code == 404, f"-> {code}")

        code, rolled = client.call("POST", "/api/history/restore",
                                   {"path": hist_doc, "version_id": first_id})
        check("还原到第一版并生成新版本", code == 200 and rolled
              and rolled.get("restored") is True
              and rolled.get("version_number") == 3
              and rolled.get("from_version") == first_id, f"-> {code} {rolled}")
        code, back = client.call("GET", f"/api/docs/{enc_hist}")
        check("还原后文档内容回到第一版", code == 200 and back
              and back.get("content") == "# 第一版\n", f"-> {code}")
        code, hist4 = client.call("GET", f"/api/history/{enc_hist}")
        check("还原动作本身记为 restore 版本", code == 200
              and hist4.get("count") == 3
              and hist4["versions"][0].get("action") == "restore"
              and hist4["versions"][0].get("from_version") == first_id,
              f"-> {code} {hist4}")
        code, _ = client.call("POST", "/api/history/restore",
                              {"path": hist_doc, "version_id": "__smoke__missing__"})
        check("还原不属于该文档的版本返回 404", code == 404, f"-> {code}")

        code, renamed = client.call("PATCH", "/api/rename",
                                    {"path": hist_doc, "new_name": "__smoke__历史改名.md"})
        check("重命名文档成功", code == 200 and renamed
              and renamed.get("path") == hist_renamed, f"-> {code} {renamed}")
        code, h_old = client.call("GET", f"/api/history/{enc_hist}")
        code, h_new = client.call("GET", f"/api/history/{enc_hist_renamed}")
        check("重命名后历史迁移到新路径", h_old.get("count") == 0
              and h_new.get("count") == 3, f"-> old={h_old.get('count')} new={h_new.get('count')}")
        code, moved = client.call("PATCH", "/api/move",
                                  {"path": hist_renamed, "target_dir": "Knowledge"})
        check("移动文档成功", code == 200 and moved
              and moved.get("path") == hist_moved, f"-> {code} {moved}")
        code, h_moved = client.call("GET", f"/api/history/{enc_hist_moved}")
        check("移动后历史跟随到新路径", h_moved.get("count") == 3,
              f"-> {h_moved.get('count')}")

        code, nested = client.call("PUT",
                                   f"/api/docs/{urllib.parse.quote(hist_nested, safe='/')}",
                                   {"content": "# 目录内笔记\n"})
        check("准备目录内文档用于历史迁移", code == 200, f"-> {code}")
        code, dir_renamed = client.call("PATCH", "/api/rename",
                                        {"path": hist_dir,
                                         "new_name": "__smoke__历史目录改名"})
        check("重命名目录成功", code == 200 and dir_renamed
              and dir_renamed.get("path") == hist_dir_renamed, f"-> {code} {dir_renamed}")
        code, h_nested = client.call(
            "GET", f"/api/history/{urllib.parse.quote(hist_nested_renamed, safe='/')}")
        check("目录改名后其下文档历史一并迁移", h_nested.get("count") == 1,
              f"-> {h_nested.get('count')}")

        code, cleared = client.call("DELETE", f"/api/history/{enc_hist_moved}")
        check("清空文档历史返回清除条数", code == 200 and cleared
              and cleared.get("cleared") == 3, f"-> {code} {cleared}")
        code, h_empty = client.call("GET", f"/api/history/{enc_hist_moved}")
        check("清空后历史列表为空", code == 200 and h_empty.get("count") == 0,
              f"-> {code} {h_empty}")
        code, ver_gone = client.call("GET", "/api/versions/" + first_id)
        check("清空后旧版本快照已删除", code == 404, f"-> {code}")

        from fastapi import HTTPException
        import main as app_module

        for evil in ("../evil.md", "Projects/../../evil.md", "Projects/note.txt",
                     "/etc/passwd.md", "C:/Windows/win.md", "Projects/../.gitkeep",
                     "Projects/..\\evil.md", "", "Projects/.hidden.md"):
            rejected = False
            try:
                app_module._parse_doc_path(evil)
            except HTTPException as error:
                rejected = error.status_code == 400
            except Exception:
                rejected = False
            check(f"路径安全拦截：{evil or '(空路径)'}", rejected)

        for evil_dir in ("../escape", "Projects/../../escape", "Projects/__smoke__bad.md"):
            rejected = False
            try:
                app_module._parse_dir_path(evil_dir)
            except HTTPException as error:
                rejected = error.status_code == 400
            except Exception:
                rejected = False
            check(f"目录路径安全拦截：{evil_dir}", rejected)

        code, _ = client.call("GET", "/api/docs/Projects/%2e%2e%2f%2e%2e%2fsecret.md")
        check("HTTP 层拒绝编码后的路径遍历", code in (400, 403, 404), f"-> {code}")
        code, _ = client.call("PUT", "/api/docs/Projects/%2e%2e%2fescape.md", {"content": "x"})
        check("HTTP 层拒绝越界写入", code >= 400, f"-> {code}")
        check("data/ 之外没有被写入文件",
              not (BASE_DIR / "escape.md").exists() and not (BASE_DIR / "secret.md").exists())

        code, deleted = client.call("DELETE", f"/api/docs/{enc_a}")
        check("DELETE 删除文档", code == 200 and deleted.get("deleted") is True, f"-> {code}")
        code, _ = client.call("GET", f"/api/docs/{enc_a}")
        check("删除后 GET 返回 404", code == 404, f"-> {code}")
        code, _ = client.call("DELETE", f"/api/docs/{enc_b}")
        check("DELETE 删除多级目录下文档", code == 200, f"-> {code}")
        code, _ = client.call("DELETE", f"/api/docs/{enc_in_dir}")
        check("DELETE 删除新建目录下文档", code == 200, f"-> {code}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
        for relative in (doc_a, doc_b, doc_in_dir, trash_doc, hist_doc,
                         hist_renamed, hist_moved):
            target = BASE_DIR / "data" / relative
            try:
                if target.exists():
                    target.unlink()
                parent = target.parent
                while parent != BASE_DIR / "data" and parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            except OSError:
                pass
        for relative in (
            "Projects/__smoke__目录A",
            "Knowledge/__smoke__前端",
            "Knowledge/__smoke__目标目录",
            "Knowledge/__smoke__递归删除",
            "Projects/__smoke__可移动目录",
            "Projects/__smoke__待删目录",
            trash_dir,
            hist_dir,
            hist_dir_renamed,
        ):
            shutil.rmtree(BASE_DIR / "data" / relative, ignore_errors=True)
        shutil.rmtree(trash_dir, ignore_errors=True)
        shutil.rmtree(history_dir, ignore_errors=True)
        cleanup_test_trash(BASE_DIR)
        cleanup_test_history(BASE_DIR)
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
