"""阶段十四：阅读视图默认在左侧显示文档目录（TOC）的可运行结果验证。

运行（在项目根目录）：
    .venv/Scripts/python.exe tests/stage14_toc_test.py

自动拉起 uvicorn，写入一篇含多级标题的测试文档与一篇无标题文档，
用系统自带的无头 Chrome / Edge 打开文档深链接并 dump DOM，检查：
  - 阅读视图左侧默认渲染目录面板，且排在正文之前
  - 目录条目与文档标题一一对应，并带层级缩进
  - 标题自动获得稳定 id（marked v15 默认不生成）
  - 无标题文档给出「还没有标题」的空状态提示
  - 顶栏「目录」开关存在且可点击
退出码 0 表示全部通过；测试文档、版本历史与回收站条目会被自动清理。
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trash_cleanup import cleanup_test_history, cleanup_test_trash  # noqa: E402

WEB_DIR = BASE_DIR / "web"
TEST_DIR = "Projects/__stage14__目录验证"
TEST_DOC = TEST_DIR + "/多级标题.md"
PLAIN_DOC = TEST_DIR + "/无标题.md"

TEST_CONTENT = """# 阶段十四目录验证

导语段落，用于确认正文渲染正常。

## 第一节

### 小节 1.1

正文内容一。

### 小节 1.2

正文内容二。

## 第二节

正文内容三。

#### 深层小节 2.1.1

正文内容四。
"""

PLAIN_CONTENT = """这是一篇没有任何标题的文档。

只有段落文本，用来验证目录面板的空状态提示。
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


def toc_section(dom: str) -> str:
    match = re.search(r'<aside class="doc-toc".*?</aside>', dom, re.S)
    return match.group(0) if match else ""


def main() -> int:
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    style_css = (WEB_DIR / "style.css").read_text(encoding="utf-8")

    check("页面结构包含左侧目录面板", 'class="doc-toc"' in index_html
          and "toc-item" in index_html and "docOutline" in index_html)
    check("目录条目支持点击跳转与层级缩进",
          "scrollToHeading(item.id)" in index_html and "'depth-' + item.depth" in index_html)
    check("顶栏提供目录显示开关", "toggleToc" in index_html)
    check("目录条目带折叠箭头与全部折叠开关",
          "toc-caret" in index_html and "toggleHeading(item.id)" in index_html
          and "collapseAll" in index_html and "expandAll" in index_html)
    check("前端实现标题 id 注入与目录抽取",
          "function buildOutline" in app_js and "slugifyHeading" in app_js
          and "MAX_OUTLINE_ITEMS" in app_js)
    check("目录按标题层级建立父子关系",
          "parentId" in app_js and "hasChildren" in app_js)
    check("折叠逻辑按可见性过滤目录条目",
          "visibleOutline" in app_js and "collapsedHeadings" in app_js
          and "resolveVisibleHeading" in app_js)
    check("目录默认展开且记忆用户选择",
          "readTocVisible" in app_js and "mdfm:toc-visible" in app_js
          and "return saved === null ? true" in app_js)
    check("样式定义目录面板与高亮态",
          ".doc-toc" in style_css and ".toc-item.active" in style_css
          and "depth-2" in style_css and ".toc-caret.open" in style_css)

    browser = find_browser()
    if browser is None:
        print("[FAIL] 未找到 Chrome / Edge，无法执行真实浏览器验证")
        return 1
    print(f"使用浏览器：{browser}")

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    encoded = urllib.parse.quote(TEST_DOC, safe="/")
    plain_encoded = urllib.parse.quote(PLAIN_DOC, safe="/")
    profile_dir = Path(tempfile.mkdtemp(prefix="mdfm-toc-"))

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        check("uvicorn 启动并响应健康检查", wait_ready(base_url))
        if FAILURES:
            return 1

        code, _ = fetch(base_url, f"/api/dirs/{urllib.parse.quote(TEST_DIR, safe='/')}", "POST")
        check("创建阶段十四测试目录", code in (200, 409), f"-> {code}")
        code, _ = fetch(base_url, f"/api/docs/{encoded}", "PUT", {"content": TEST_CONTENT})
        check("写入含多级标题的测试文档", code == 200, f"-> {code}")
        code, _ = fetch(base_url, f"/api/docs/{plain_encoded}", "PUT", {"content": PLAIN_CONTENT})
        check("写入无标题测试文档", code == 200, f"-> {code}")

        doc_url = base_url + "/#/doc/" + urllib.parse.quote(TEST_DOC, safe="")
        dom = dump_dom(browser, profile_dir, doc_url, "文档深链接")
        check("Vue 完成挂载且文档已打开", "后端已连接" in dom and TEST_DOC in dom)
        check("阅读视图出现左侧目录面板", 'class="doc-toc"' in dom)
        check("目录面板排在正文之前",
              dom.find('class="doc-toc"') > 0
              and dom.find('class="doc-toc"') < dom.find('class="markdown-body"'))
        check("正文仍在可滚动区域中", 'class="viewer"' in dom and "doc-split" in dom)

        aside = toc_section(dom)
        check("目录标题头显示条目计数", "目录" in aside and "toc-count" in aside)
        # 文档共 6 个标题：h1 一个、h2 两个、h3 两个、h4 一个
        check("目录条目数量与标题数量一致", aside.count('class="toc-item') == 6,
              f"-> {aside.count('class=\"toc-item')} 条")
        check("目录条目呈现三级缩进层级",
              "depth-0" in aside and "depth-1" in aside and "depth-2" in aside,
              aside[:220])
        # 6 个标题里 h1、两个 h2 有子标题，共 3 个可折叠节点
        check("每个条目都有折叠箭头占位，仅父级可点",
              aside.count('class="toc-caret') == 6
              and aside.count("toc-caret leaf") == 3
              and aside.count("toc-caret open") == 3,
              f"-> caret={aside.count('class=\"toc-caret')} leaf={aside.count('toc-caret leaf')}")
        check("目录头部提供折叠全部/展开全部按钮",
              'class="toc-tool"' in aside and "折叠全部标题" in aside,
              aside[:200])
        check("目录条目文本与标题文本一致",
              "阶段十四目录验证" in aside and "小节 1.1" in aside and "深层小节 2.1.1" in aside)
        check("目录默认展开（无 tbody 兜底文案）", "还没有标题" not in aside)

        article_match = re.search(
            r'<article class="markdown-body"[^>]*>([\s\S]*?)</article>', dom)
        article = article_match.group(1) if article_match else ""
        check("正文渲染为独立的 markdown-body 容器", bool(article))
        headings = re.findall(r"<h([1-4])[^>]*id=\"([^\"]+)\"[^>]*>", article)
        check("渲染后的标题自动带上 id 锚点", len(headings) == 6, f"-> {len(headings)} 个")
        ids = [item[1] for item in headings]
        check("标题 id 唯一且可读", len(set(ids)) == len(ids) and all(ids),
              f"-> {ids}")
        heading_texts = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", body)).strip()
            for body in re.findall(r"<h[1-6][^>]*>([\s\S]*?)</h[1-6]>", article)
        ]
        toc_texts = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", body)).strip()
            for body in re.findall(r'<span class="toc-text">([\s\S]*?)</span>', aside)
        ]
        check("目录条目顺序与正文标题顺序一致",
              bool(toc_texts) and toc_texts == heading_texts,
              f"-> toc={toc_texts[:3]} headings={heading_texts[:3]}")

        toc_buttons = re.findall(r"<button[^>]*>目录</button>", dom)
        check("顶栏目录开关在阅读态可用",
              bool(toc_buttons) and "disabled" not in toc_buttons[0],
              f"-> {toc_buttons[:1]}")

        plain_url = base_url + "/#/doc/" + urllib.parse.quote(PLAIN_DOC, safe="")
        dom_plain = dump_dom(browser, profile_dir, plain_url, "无标题文档")
        plain_aside = toc_section(dom_plain)
        check("无标题文档仍显示目录面板", 'class="doc-toc"' in dom_plain)
        check("无标题文档给出空状态提示",
              "还没有标题" in plain_aside and "toc-empty" in plain_aside, plain_aside[:200])
    finally:
        for path in (encoded, plain_encoded):
            try:
                fetch(base_url, f"/api/docs/{path}", "DELETE")
            except Exception:
                pass
        for name in (TEST_DOC, PLAIN_DOC):
            target = BASE_DIR / "data" / name
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass
        test_dir = BASE_DIR / "data" / TEST_DIR
        try:
            if test_dir.is_dir() and not any(test_dir.iterdir()):
                test_dir.rmdir()
        except OSError:
            pass
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)
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
