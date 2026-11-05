"""前端可运行结果验证：静态页面、渲染依赖、公式扩展、卡片导航与 API 联动。

运行（在项目根目录）：
    .venv/Scripts/python.exe tests/frontend_smoke_test.py
退出码 0 表示全部通过；脚本会自动清理自己创建的测试文档与目录。
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trash_cleanup import cleanup_test_trash  # noqa: E402

WEB_DIR = BASE_DIR / "web"
STATIC_ASSETS = (
    "/app.js",
    "/math.js",
    "/style.css",
    "/vendor/vue.global.prod.js",
    "/vendor/marked.min.js",
    "/vendor/purify.min.js",
    "/vendor/highlight.min.js",
    "/vendor/highlight-light.css",
    "/vendor/github-markdown-light.css",
    "/vendor/katex/katex.min.js",
    "/vendor/katex/katex.min.css",
    "/vendor/katex/fonts/KaTeX_Main-Regular.woff2",
)
TEST_DOC = "Projects/__frontend__渲染验证.md"
TEST_DIR = "Projects/__frontend__新目录"

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
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers.get("Content-Type", "")


def as_json(raw: bytes):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def wait_ready(base_url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            code, _, _ = fetch(base_url, "/api/health")
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


def main() -> int:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    node_path = shutil.which("node")
    if node_path:
        for script in ("app.js", "math.js"):
            result = subprocess.run(
                [node_path, "--check", str(WEB_DIR / script)],
                capture_output=True, text=True,
            )
            check(f"{script} 通过 Node 语法检查", result.returncode == 0, result.stderr[:300])

        render_probe = r"""
const marked = require(process.argv[1]);
const out = marked.parse('# 标题\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```python\nprint(1)\n```\n');
if (!out.includes('<h1') || !out.includes('<table>') || !out.includes('language-python')) {
  process.exit(2);
}
console.log('rendered');
"""
        probe = subprocess.run(
            [node_path, "-e", render_probe, str(WEB_DIR / "vendor" / "marked.min.js")],
            capture_output=True, text=True,
        )
        check("marked 正确输出标题、表格与代码块 HTML", probe.returncode == 0,
              (probe.stdout + probe.stderr)[:300])

        math_probe = r"""
const root = process.argv[1];
const marked = require(root + '/web/vendor/marked.min.js');
const katex = require(root + '/web/vendor/katex/katex.min.js');
const math = require(root + '/web/math.js');
const renderer = math.install(marked, katex);
const src = '# 标题\n\n行内 $E=mc^2$\n\n$$\n\\int_0^1 x^2 dx = \\frac{1}{3}\n$$\n\n```python\nprice = $5\n```\n';
renderer.reset();
const out = marked.parse(src);
if ((out.match(/math-placeholder/g) || []).length !== 2) process.exit(2);
if (!out.includes('$5') || !out.includes('<h1')) process.exit(3);
if (!katex.renderToString('E=mc^2').includes('katex')) process.exit(4);
console.log('math-ok');
"""
        math_result = subprocess.run(
            [node_path, "-e", math_probe, str(BASE_DIR)],
            capture_output=True, text=True,
        )
        check("公式扩展识别行内/块级公式且不误伤代码块", math_result.returncode == 0,
              (math_result.stdout + math_result.stderr)[:300])
    else:
        print("[SKIP] 未安装 Node.js，跳过前端语法与渲染探针")

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        check("uvicorn 启动并响应健康检查", wait_ready(base_url))
        if FAILURES:
            return 1

        code, index_bytes, content_type = fetch(base_url, "/")
        index_html = index_bytes.decode("utf-8", errors="replace")
        check("根路径返回前端页面 index.html",
              code == 200 and "text/html" in content_type and 'id="app"' in index_html,
              f"-> {code} {content_type}")
        check("页面挂载卡片入口与 v-html 渲染区",
              'class="cards"' in index_html and 'v-html="renderedHtml"' in index_html
              and '@dblclick="openDir(card.path)"' in index_html)
        check("页面引用标准解析库、样式表与 KaTeX",
              all(token in index_html for token in (
                  "vendor/marked.min.js", "vendor/purify.min.js",
                  "vendor/highlight.min.js", "github-markdown-light.css",
                  "vendor/katex/katex.min.js", "vendor/katex/katex.min.css", "/math.js",
              )))
        check("新建对话框区分目录/文档且未选目录时禁用文档",
              "kind-switch" in index_html and 'newKind === \'doc\'' in index_html
              and ':disabled="!selectedDir"' in index_html)
        check("一级卡片不再平铺子目录与文档",
              "card-item" not in index_html and "card-items" not in index_html
              and "tree-node" not in index_html and "sidebar" not in index_html)
        check("目录详情页与返回/面包屑齐备",
              "dir-view" in index_html and "breadcrumb" in index_html
              and "goBack" in index_html and "← 返回" in index_html
              and '@dblclick="openDir(item.path)"' in index_html)
        check("右键菜单提供打开/新建/删除等操作",
              "openFromMenu" in index_html and "startNewInMenu" in index_html
              and "deleteFromMenu" in index_html and "删除目录" in index_html)
        check("目录页提供新建文件夹与文档快捷入口",
              "createIn(activeDirPath, 'dir')" in index_html
              and "createIn(activeDirPath, 'doc')" in index_html)
        check("页面提供移动到对话框、拖拽与放置目标",
              "showMove" in index_html and "dir-list" in index_html
              and 'draggable="true"' in index_html and "drop-target" in index_html
              and '@drop.prevent="onDrop' in index_html)
        check("右键菜单提供移动与递归删除入口",
              "openMoveDialog" in index_html and "清空并移入回收站" in index_html
              and "deleteFromMenu(true)" in index_html)
        check("页面提供回收站入口与还原/彻底删除面板",
              ">回收站<" in index_html and "openTrash" in index_html
              and "showTrash" in index_html and "restoreTrash(item.id)" in index_html
              and "purgeTrash(item.id)" in index_html and "emptyTrash" in index_html)

        for asset in STATIC_ASSETS:
            code, raw, _ = fetch(base_url, asset)
            check(f"静态资源可访问 {asset}", code == 200 and len(raw) > 1000,
                  f"-> {code} {len(raw)} bytes")

        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        check("交互逻辑使用标准解析库并做 XSS 净化",
              "marked.parse" in app_js and "DOMPurify.sanitize" in app_js
              and "hljs.highlightElement" in app_js)
        check("交互逻辑接入 KaTeX 公式渲染与深链接",
              "MDFMMath.install" in app_js and "renderInto" in app_js
              and "openFromHash" in app_js)
        check("交互逻辑按卡片页/目录页/文档页三级组织",
              "activeDirPath" in app_js and "openDir" in app_js and "goBack" in app_js
              and "TreeNode" not in app_js and "CardItem" not in app_js)
        check("未选目录只建目录、选中目录可建目录或文档",
              "selectDir" in app_js and "newKind" in app_js and "createEntry" in app_js
              and "'/api/dirs/'" in app_js and "'POST'" in app_js)
        check("交互逻辑调用 Fetch 完成无刷新保存",
              "fetch(" in app_js and "'PUT'" in app_js and "refreshTree()" in app_js)
        check("交互逻辑调用移动接口并处理递归删除确认",
              "'/api/move'" in app_js and "moveEntry" in app_js
              and "recursive=true" in app_js and "confirm=" in app_js)
        check("拖拽事件链路完整（dragstart / dragover / drop / dragend）",
              all(token in app_js for token in
                  ("onDragStart", "onDragOver", "onDrop", "onDragEnd", "draggingPath")))
        check("交互逻辑调用回收站列表/还原/清空接口",
              "'/api/trash'" in app_js and "'/api/trash/restore'" in app_js
              and "refreshTrashCount" in app_js and "loadTrash" in app_js)
        style_css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
        check("样式提供回收站面板与角标", ".trash-dialog" in style_css
              and ".trash-list" in style_css and ".trash-badge" in style_css)

        code, raw, ctype = fetch(base_url, "/docs")
        check("Swagger UI 仍可访问（接口先行契约）",
              code == 200 and "text/html" in ctype, f"-> {code} {ctype}")

        enc_dir = urllib.parse.quote(TEST_DIR, safe="/")
        code, raw, _ = fetch(base_url, f"/api/dirs/{enc_dir}", "POST")
        made = as_json(raw)
        check("目录创建接口 POST /api/dirs 可用", code == 200
              and made and made.get("created") is True, f"-> {code} {raw[:120]}")
        code, raw, _ = fetch(base_url, f"/api/dirs/{enc_dir}", "POST")
        again = as_json(raw)
        check("重复创建目录幂等返回 created=false", code == 200
              and again and again.get("created") is False, f"-> {code} {raw[:120]}")
        code, raw, _ = fetch(base_url, "/api/tree")
        check("新建目录出现在目录树中", code == 200
              and find_node((as_json(raw) or {}).get("tree", []), TEST_DIR) is not None,
              f"-> {code}")

        encoded = urllib.parse.quote(TEST_DOC, safe="/")
        content = "# 渲染验证\n\n| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n\n```python\nprint('hello')\n```\n"
        code, raw, _ = fetch(base_url, f"/api/docs/{encoded}", "PUT", {"content": content})
        created = as_json(raw)
        check("前端保存链路 PUT 创建中文文档", code == 200
              and created and created.get("action") == "created", f"-> {code} {raw[:120]}")

        code, raw, _ = fetch(base_url, "/api/tree")
        tree = as_json(raw)
        check("保存后目录树即时出现该文档", code == 200
              and find_node((tree or {}).get("tree", []), TEST_DOC) is not None, f"-> {code}")

        code, raw, _ = fetch(base_url, f"/api/docs/{encoded}")
        doc = as_json(raw)
        check("预览链路 GET 读回完整 Markdown 源码", code == 200
              and doc and doc.get("content") == content, f"-> {code}")

        code, raw, _ = fetch(base_url, "/api/move", "PATCH",
                             {"path": TEST_DOC, "target_dir": TEST_DIR})
        moved = as_json(raw)
        moved_path = TEST_DIR + "/__frontend__渲染验证.md"
        check("前端整理链路 PATCH /api/move 移动文档", code == 200
              and moved and moved.get("moved") is True
              and moved.get("path") == moved_path, f"-> {code} {raw[:120]}")
        code, _, _ = fetch(base_url, f"/api/docs/{encoded}")
        check("移动后旧路径返回 404", code == 404, f"-> {code}")
        code, raw, _ = fetch(base_url, f"/api/docs/{urllib.parse.quote(moved_path, safe='/')}")
        check("移动后新路径可读取源码", code == 200
              and (as_json(raw) or {}).get("content") == content, f"-> {code}")

        nested = TEST_DIR + "/嵌套/深层.md"
        code, _, _ = fetch(base_url, f"/api/docs/{urllib.parse.quote(nested, safe='/')}",
                           "PUT", {"content": "# 深层文档\n"})
        check("递归删除前准备嵌套文档", code == 200, f"-> {code}")
        rec_url = (f"/api/dirs/{enc_dir}?recursive=true&confirm="
                   + urllib.parse.quote("__frontend__新目录"))
        code, raw, _ = fetch(base_url, rec_url, "DELETE")
        removed = as_json(raw)
        check("前端整理链路递归删除目录及内容", code == 200
              and removed and removed.get("recursive") is True
              and removed.get("removed_docs") >= 1, f"-> {code} {raw[:150]}")
        code, raw, _ = fetch(base_url, "/api/tree")
        check("递归删除后目录树中不再有该目录", code == 200
              and find_node((as_json(raw) or {}).get("tree", []), TEST_DIR) is None,
              f"-> {code}")

        # 阶段十：回收站列表、还原与彻底删除
        code, raw, _ = fetch(base_url, "/api/trash")
        listing = as_json(raw) or {}
        dir_item = next((item for item in listing.get("items", [])
                         if item.get("original_path") == TEST_DIR), None)
        check("回收站列表返回被删除的目录条目", code == 200 and dir_item
              and dir_item.get("type") == "dir"
              and dir_item.get("removed_docs") >= 1, f"-> {code} {raw[:150]}")
        code, raw, _ = fetch(base_url, "/api/trash/restore", "POST", {"id": dir_item["id"]})
        restored = as_json(raw)
        check("回收站还原目录到原位置", code == 200 and restored
              and restored.get("restored") is True
              and restored.get("path") == TEST_DIR, f"-> {code} {raw[:150]}")
        code, raw, _ = fetch(base_url, "/api/tree")
        check("还原后目录重新出现在目录树", code == 200
              and find_node((as_json(raw) or {}).get("tree", []), TEST_DIR) is not None,
              f"-> {code}")
        code, raw, _ = fetch(base_url, f"/api/docs/{urllib.parse.quote(nested, safe='/')}")
        check("还原后目录内嵌套文档仍可读", code == 200, f"-> {code}")
        code, raw, _ = fetch(base_url, "/api/trash/restore", "POST", {"id": "../evil"})
        check("还原接口拒绝非法条目 ID", code == 400, f"-> {code}")
        code, raw, _ = fetch(base_url, rec_url, "DELETE")
        again = as_json(raw) or {}
        check("再次递归删除生成新回收站条目", code == 200 and bool(again.get("trash_id")),
              f"-> {code} {raw[:120]}")
        code, raw, _ = fetch(base_url, "/api/trash/" + again["trash_id"], "DELETE")
        check("彻底删除该回收站条目", code == 200
              and (as_json(raw) or {}).get("purged") is True, f"-> {code} {raw[:120]}")
        code, raw, _ = fetch(base_url, "/api/trash")
        check("彻底删除后列表不再含该条目", code == 200
              and not any(item.get("id") == again["trash_id"]
                          for item in (as_json(raw) or {}).get("items", [])), f"-> {code}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
        target = BASE_DIR / "data" / TEST_DOC
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
        shutil.rmtree(BASE_DIR / "data" / TEST_DIR, ignore_errors=True)
        cleanup_test_trash(BASE_DIR)
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
