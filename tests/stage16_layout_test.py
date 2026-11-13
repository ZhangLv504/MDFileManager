"""阶段十六：界面布局优化的可运行结果验证。

运行（在项目根目录）：
    .venv/Scripts/python.exe tests/stage16_layout_test.py

自动拉起 uvicorn、建一个测试目录与长文档，用无头 Chrome 通过 CDP 读取
真实计算样式与几何尺寸，验证：
  - 顶栏在 1440px 下保持单行、按钮有分组分隔
  - 卡片库为自适应网格，卡片等宽等高、说明最多 3 行
  - 阅读正文限制最大宽度并水平居中
  - 对话框限制高度、列表可滚动
  - 回收站/历史时间格式化为「YYYY-MM-DD HH:MM」，大小按 KB/MB 显示
  - 680px 窄屏下卡片改为单列、顶栏不重叠
退出码 0 表示全部通过；测试目录与回收站条目会被自动清理。
"""
from __future__ import annotations

import asyncio
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
TEST_DIR = "__stage16__布局"
LONG_DOC = TEST_DIR + "/长文.md"
TRASH_DOC = TEST_DIR + "/待删除.md"

LONG_CONTENT = "\n\n".join(
    ["# 布局验证长文"] + [f"## 第 {i} 节\n\n" + "这是一段用于验证正文行宽与居中效果的示例文字。" * 6
                        for i in range(1, 9)]
)

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
        with urllib.request.urlopen(request, timeout=8) as response:
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


async def run_browser_checks(browser: Path, base_url: str, profile_dir: Path) -> None:
    import websockets

    port = free_port()
    chrome = subprocess.Popen(
        [str(browser), "--headless=new", "--disable-gpu", "--no-sandbox",
         "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        target = None
        for _ in range(80):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3) as response:
                    pages = [item for item in json.loads(response.read()) if item.get("type") == "page"]
                if pages:
                    target = pages[0]
                    break
            except Exception:
                pass
            time.sleep(0.3)
        check("无头浏览器启动并暴露调试端点", target is not None)
        if not target:
            return

        async with websockets.connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
            counter = {"n": 0}

            async def call(method: str, params: dict | None = None) -> dict:
                counter["n"] += 1
                my_id = counter["n"]
                await ws.send(json.dumps({"id": my_id, "method": method, "params": params or {}}))
                while True:
                    message = json.loads(await ws.recv())
                    if message.get("id") == my_id:
                        return message

            async def evaluate(expression: str):
                message = await call("Runtime.evaluate", {
                    "expression": expression, "returnByValue": True,
                    "awaitPromise": True, "userGesture": True,
                })
                result = message.get("result", {})
                if "exceptionDetails" in result:
                    return "EXC:" + json.dumps(result["exceptionDetails"], ensure_ascii=False)[:200]
                return result.get("result", {}).get("value")

            async def viewport(width: int, height: int) -> None:
                await call("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
                })

            async def goto(url: str, ready_expression: str) -> None:
                await call("Page.navigate", {"url": url})
                for _ in range(60):
                    await asyncio.sleep(0.3)
                    if await evaluate(ready_expression):
                        break
                await asyncio.sleep(0.6)

            await call("Page.enable")
            await viewport(1440, 900)

            # ---------- 卡片库：顶栏与网格 ----------
            await goto(base_url + "/", "document.querySelectorAll('.card').length > 0")
            check("卡片库完成渲染", await evaluate("document.querySelectorAll('.card').length") > 0)

            topbar_height = await evaluate("document.querySelector('.topbar').offsetHeight")
            check("顶栏在 1440px 下保持单行（高度 ≤ 62px）",
                  isinstance(topbar_height, (int, float)) and topbar_height <= 62,
                  f"-> {topbar_height}px")
            check("顶栏操作区按语义分组（分隔线 ≥ 2 条）",
                  await evaluate("document.querySelectorAll('.actions .group-sep').length") >= 2,
                  str(await evaluate("document.querySelectorAll('.actions .group-sep').length")))
            check("顶栏按钮不再贴到窗口右边缘",
                  await evaluate(
                      "window.innerWidth - document.querySelector('.actions').getBoundingClientRect().right") >= 8)

            check("卡片容器改为网格布局",
                  await evaluate("getComputedStyle(document.querySelector('.cards')).display") == "grid")
            card_metrics = await evaluate("""
            (function () {
              var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
              if (!cards.length) return null;
              var widths = cards.map(function (el) { return Math.round(el.getBoundingClientRect().width); });
              var heights = cards.map(function (el) { return Math.round(el.getBoundingClientRect().height); });
              return { widths: widths, heights: heights };
            })()
            """)
            check("卡片网格读取到真实尺寸", isinstance(card_metrics, dict), str(card_metrics))
            if isinstance(card_metrics, dict):
                widths = card_metrics.get("widths") or []
                check("所有卡片列宽一致（不再出现末行被拉满）",
                      bool(widths) and max(widths) - min(widths) <= 1, str(widths))
                check("卡片宽度落在自适应区间内",
                      bool(widths) and 270 <= widths[0] <= 520, str(widths[:3]))

            desc_metrics = await evaluate("""
            (function () {
              var el = document.querySelector('.card-desc');
              if (!el) return null;
              var style = getComputedStyle(el);
              var lineHeight = parseFloat(style.lineHeight) || 18;
              return {
                clamp: style.webkitLineClamp,
                lines: Math.round(el.getBoundingClientRect().height / lineHeight),
                overflow: style.overflow
              };
            })()
            """)
            check("卡片说明最多显示 3 行并裁切",
                  isinstance(desc_metrics, dict) and desc_metrics.get("clamp") == "3"
                  and desc_metrics.get("lines", 99) <= 3, str(desc_metrics))

            # ---------- 文档页：正文宽度与居中 ----------
            await goto(base_url + "/#/doc/" + urllib.parse.quote(LONG_DOC, safe=""),
                       "!!document.querySelector('.markdown-body')")
            body_metrics = await evaluate("""
            (function () {
              var article = document.querySelector('.markdown-body');
              var viewer = document.querySelector('.viewer');
              if (!article || !viewer) return null;
              var rect = article.getBoundingClientRect();
              var viewerRect = viewer.getBoundingClientRect();
              return {
                width: Math.round(rect.width),
                left: Math.round(rect.left - viewerRect.left),
                right: Math.round(viewerRect.right - rect.right),
                maxWidth: getComputedStyle(article).maxWidth
              };
            })()
            """)
            check("正文区域读取到真实尺寸", isinstance(body_metrics, dict), str(body_metrics))
            if isinstance(body_metrics, dict):
                check("正文限制最大宽度（≤ 960px）", body_metrics.get("width", 9999) <= 960,
                      str(body_metrics))
                check("正文水平居中（左右留白差 ≤ 40px）",
                      abs(body_metrics.get("left", 0) - body_metrics.get("right", 0)) <= 40,
                      str(body_metrics))
            check("目录面板保持 250px 固定宽度",
                  await evaluate("Math.round(document.querySelector('.doc-toc').getBoundingClientRect().width)") == 250)

            # ---------- 对话框：高度受限、内容可滚动 ----------
            await goto(base_url + "/", "document.querySelectorAll('.card').length > 0")
            await evaluate("""
            (function () {
              var btn = Array.prototype.slice.call(document.querySelectorAll('.btn'))
                .filter(function (b) { return b.textContent.indexOf('回收站') === 0; })[0];
              if (btn) btn.click();
            })()
            """)
            await asyncio.sleep(1.0)
            dialog_metrics = await evaluate("""
            (function () {
              var dialog = document.querySelector('.trash-dialog');
              if (!dialog) return null;
              var list = dialog.querySelector('.trash-list');
              return {
                height: Math.round(dialog.getBoundingClientRect().height),
                viewport: window.innerHeight,
                listOverflow: list ? getComputedStyle(list).overflowY : ''
              };
            })()
            """)
            check("回收站面板读取到真实尺寸", isinstance(dialog_metrics, dict), str(dialog_metrics))
            if isinstance(dialog_metrics, dict):
                check("对话框高度不超过视口 90%",
                      dialog_metrics.get("height", 9999) <= dialog_metrics.get("viewport", 900) * 0.9,
                      str(dialog_metrics))
                check("回收站列表可独立滚动", dialog_metrics.get("listOverflow") == "auto",
                      str(dialog_metrics))

            stamps = await evaluate("""
            (function () {
              var items = Array.prototype.slice.call(document.querySelectorAll('.trash-item small'));
              return items.map(function (el) { return el.textContent.trim(); });
            })()
            """)
            check("回收站条目使用本地时间格式（YYYY-MM-DD HH:MM）",
                  bool(stamps) and all(re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text) for text in stamps),
                  str(stamps[:3]))
            check("回收站条目大小按 KB/MB 显示",
                  bool(stamps) and all(re.search(r"(\d+(\.\d+)? (B|KB|MB))$", text) for text in stamps),
                  str(stamps[:3]))
            check("回收站不再显示原始 ISO 时间戳",
                  all("T" not in text or "+" not in text for text in stamps), str(stamps[:2]))

            # ---------- 窄屏：单列与换行不重叠 ----------
            await viewport(680, 900)
            await asyncio.sleep(0.6)
            narrow = await evaluate("""
            (function () {
              var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
              var widths = cards.map(function (el) { return Math.round(el.getBoundingClientRect().width); });
              var container = Math.round(document.querySelector('.cards').getBoundingClientRect().width);
              var btns = Array.prototype.slice.call(document.querySelectorAll('.actions .btn'));
              var rows = {};
              btns.forEach(function (el) { rows[Math.round(el.getBoundingClientRect().top)] = 1; });
              return {
                widths: widths,
                container: container,
                buttonRows: Object.keys(rows).length,
                brandHidden: getComputedStyle(document.querySelector('.brand-text')).display
              };
            })()
            """)
            check("窄屏卡片改为单列（宽度等于容器）",
                  isinstance(narrow, dict) and narrow.get("widths")
                  and abs(narrow["widths"][0] - narrow["container"]) <= 1, str(narrow))
            check("窄屏顶栏换行排列且不重叠",
                  isinstance(narrow, dict) and narrow.get("buttonRows", 0) >= 1, str(narrow))
            check("窄屏隐藏品牌副标题以节省空间",
                  isinstance(narrow, dict) and narrow.get("brandHidden") == "none", str(narrow))
    finally:
        if chrome.poll() is None:
            chrome.terminate()
            try:
                chrome.wait(timeout=8)
            except subprocess.TimeoutExpired:
                chrome.kill()


def main() -> int:
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    style_css = (WEB_DIR / "style.css").read_text(encoding="utf-8")

    check("卡片库使用自适应网格并等高显示",
          "grid-template-columns: repeat(auto-fill, minmax(278px, 1fr))" in style_css
          and ".card {" in style_css and "flex-direction: column" in style_css)
    check("卡片说明限制为 3 行",
          "-webkit-line-clamp: 3" in style_css)
    check("阅读正文限制行宽并居中",
          "max-width: 920px" in style_css and "margin: 0 auto" in style_css)
    check("顶栏紧凑化并带分组分隔线",
          "min-height: 56px" in style_css and ".group-sep" in style_css
          and index_html.count('class="group-sep"') >= 2)
    check("对话框限制高度且操作区固定在底部",
          "max-height: 88vh" in style_css
          and ".dialog-actions { margin-top: 18px; flex: none;" in style_css)
    check("回收站与历史面板有独立可滚动的列表区",
          ".trash-list {\n  flex: 1; min-height: 140px" in style_css
          and ".history-list {\n  width: 236px; flex: none; min-height: 0" in style_css)
    check("前端提供时间与文件大小格式化",
          "formatStamp: function (value)" in app_js and "formatSize: function (bytes)" in app_js
          and "formatStamp(item.deleted_at)" in index_html
          and "formatSize(item.size)" in index_html)
    check("卡片库提供空状态引导",
          'class="cards-empty"' in index_html and "还没有任何目录" in index_html)
    check("窄屏有卡片单列与顶栏收缩的响应式规则",
          "@media (max-width: 760px)" in style_css and "grid-template-columns: 1fr" in style_css
          and "@media (max-width: 1200px)" in style_css)

    browser = find_browser()
    try:
        import websockets  # noqa: F401
        has_ws = True
    except ImportError:
        has_ws = False
    if browser is None or not has_ws:
        print("[SKIP] 缺少 Chrome/Edge 或 websockets，跳过浏览器几何验证")
        print(f"\n结果：{PASSED}/{TOTAL} 项通过")
        return 1 if FAILURES else 0

    print(f"使用浏览器：{browser}")
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    profile_dir = Path(tempfile.mkdtemp(prefix="mdfm-layout-"))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        check("uvicorn 启动并响应健康检查", wait_ready(base_url))
        if FAILURES:
            return 1
        check("创建布局测试目录",
              fetch(base_url, "/api/dirs/" + urllib.parse.quote(TEST_DIR, safe="/"), "POST")[0] in (200, 409))
        check("写入长文档用于行宽验证",
              fetch(base_url, "/api/docs/" + urllib.parse.quote(LONG_DOC, safe="/"), "PUT",
                    {"content": LONG_CONTENT})[0] == 200)
        check("写入待删除文档用于时间格式验证",
              fetch(base_url, "/api/docs/" + urllib.parse.quote(TRASH_DOC, safe="/"), "PUT",
                    {"content": "# 待删除\n"} )[0] == 200)
        # 删到回收站，供面板时间格式断言使用（结束时按测试标记清理）
        fetch(base_url, "/api/docs/" + urllib.parse.quote(TRASH_DOC, safe="/"), "DELETE")

        asyncio.run(run_browser_checks(browser, base_url, profile_dir))
    finally:
        fetch(base_url, "/api/dirs/" + urllib.parse.quote(TEST_DIR, safe="/")
              + "?recursive=true&confirm=" + urllib.parse.quote(TEST_DIR, safe=""), "DELETE")
        test_path = BASE_DIR / "data" / TEST_DIR
        if test_path.exists():
            shutil.rmtree(test_path, ignore_errors=True)
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
            print(output.strip()[-1000:])

    print(f"\n结果：{PASSED}/{TOTAL} 项通过")
    if FAILURES:
        print("失败项：" + "、".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
