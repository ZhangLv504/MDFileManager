"""真实浏览器端到端验证（系统自带无头 Chrome / Edge，不下载浏览器）。

运行（在项目根目录）：
    .venv/Scripts/python.exe tests/browser_smoke_test.py

脚本临时启动 uvicorn、写入一篇含公式的测试文档，用无头浏览器分别打开
「文档深链接」与「目录深链接」并 dump 渲染后的 DOM，检查 Vue 挂载、卡片导航、
表格、代码高亮、KaTeX 公式以及目录选中状态，最后清理测试文档与临时目录。
"""
from __future__ import annotations

import json
import re
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
TEST_DOC = "Projects/__browser__渲染验证.md"
TEST_CONTENT = r"""# 浏览器渲染验证

行内公式 $E = mc^2$。

| 列A | 列B |
| --- | --- |
| 1 | 2 |

$$
\int_0^1 x^2 \, dx = \frac{1}{3}
$$

```python
price = $5
print(price)
```
"""

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


def find_browser() -> Path | None:
    for candidate in BROWSER_CANDIDATES:
        if candidate.is_file():
            return candidate
    for name in ("chrome", "msedge", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def dump_dom(browser: Path, profile_dir: Path, url: str, label: str) -> str:
    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--virtual-time-budget=12000",
        "--dump-dom",
        f"--user-data-dir={profile_dir}",
        url,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
        dom = result.stdout or ""
    except subprocess.TimeoutExpired:
        dom = ""
    check(f"无头浏览器返回{label}的完整 DOM", len(dom) > 2000 and "<html" in dom.lower(),
          f"-> {len(dom)} 字符")
    return dom


def main() -> int:
    browser = find_browser()
    if browser is None:
        print("[FAIL] 未找到 Chrome / Edge，无法执行真实浏览器验证")
        return 1
    print(f"使用浏览器：{browser}")

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    encoded = urllib.parse.quote(TEST_DOC, safe="/")
    profile_dir = Path(tempfile.mkdtemp(prefix="mdfm-browser-"))

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        check("uvicorn 启动并响应健康检查", wait_ready(base_url))
        if FAILURES:
            return 1

        code, _ = fetch(base_url, f"/api/docs/{encoded}", "PUT", {"content": TEST_CONTENT})
        check("写入含公式与代码块的测试文档", code == 200, f"-> {code}")

        doc_url = base_url + "/#/doc/" + urllib.parse.quote(TEST_DOC, safe="")
        dom = dump_dom(browser, profile_dir, doc_url, "文档深链接")
        check("Vue 完成挂载且后端连通", "后端已连接" in dom and "MDFileManager" in dom)
        check("顶栏呈现当前文档路径", "__browser__" in dom and ".md" in dom)
        check("URL 深链接自动打开指定文档", TEST_DOC in dom)
        check("打开文档后提供返回入口", "← 返回" in dom)
        check("Markdown 标题与表格正确渲染", "<h1" in dom and "<table" in dom)
        check("代码块语法高亮生效", "hljs" in dom or "language-python" in dom)
        check("KaTeX 行内公式渲染", "katex-html" in dom)
        check("KaTeX 块级公式渲染", "katex-display" in dom)
        check("所有公式占位符均被替换", "math-placeholder" not in dom)
        check("KaTeX 公式数量精确（行内 1 + 块级 1）", dom.count("katex-html") == 2,
              f"-> {dom.count('katex-html')} 个")
        code_blocks = re.findall(r"<pre[^>]*>[\s\S]*?</pre>", dom)
        code_text = "".join(code_blocks)
        check("代码块保留原始 $ 且未被插入公式", bool(code_blocks)
              and "katex" not in code_text and "$" in code_text,
              code_text[:200])

        dir_url = base_url + "/#/dir/" + urllib.parse.quote("Projects", safe="")
        dom_dir = dump_dom(browser, profile_dir, dir_url, "目录深链接")
        check("目录深链接自动选中目录", "已选目录" in dom_dir and "Projects" in dom_dir)
        check("目录深链接打开独立目录页", "dir-view" in dom_dir and "breadcrumb" in dom_dir)
        check("面包屑可返回文档库", "文档库" in dom_dir)
        check("页面不再包含侧栏树", "tree-row" not in dom_dir and "sidebar" not in dom_dir)
        check("目录页给出双击与右键提示", "双击文件夹进入下一级" in dom_dir)
        check("顶栏新建按钮可用", ">新建<" in dom_dir)
        check("目录页以文档分区展示内容", "dir-view" in dom_dir and "doc-tile" in dom_dir)
        check("目录页提供新建快捷按钮", "+ 文件夹" in dom_dir and "+ 文档" in dom_dir)
    finally:
        try:
            fetch(base_url, f"/api/docs/{encoded}", "DELETE")
        except Exception:
            pass
        target = BASE_DIR / "data" / TEST_DOC
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
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
