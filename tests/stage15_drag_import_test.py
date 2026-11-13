"""阶段十五：从系统资源管理器直接拖入 .md 文件的端到端验证。

运行（在项目根目录）：
    .venv/Scripts/python.exe tests/stage15_drag_import_test.py

自动拉起 uvicorn，在 data/ 顶层建一个测试目录，然后用无头 Chrome 通过
Chrome DevTools Protocol 真正派发 dragenter / dragover / drop 事件（DataTransfer
里放构造出来的 File 对象），验证：
  - 拖到顶层目录卡片 → 文件写入该目录
  - 拖到目录页空白处 → 写入当前目录
  - 拖到子文件夹 → 写入该子目录
  - 非 .md 文件被忽略并提示
  - 一次拖入多个文件全部写入
  - 按住 Shift 拖入覆盖同名文档
  - 页面提示条、目标高亮等交互状态
没有安装 websockets 时跳过浏览器交互段（其余静态断言照常执行）。
退出码 0 表示全部通过；测试目录、版本历史与回收站条目会被自动清理。
"""
from __future__ import annotations

import asyncio
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
TEST_DIR = "__stage15__拖放"
TEST_SUB = TEST_DIR + "/子目录"
DOC_MAIN = TEST_DIR + "/拖入文档.md"
DOC_SUB = TEST_DIR + "/子目录/子目录文档.md"
DOC_MANY_A = TEST_DIR + "/批量一.md"
DOC_MANY_B = TEST_DIR + "/批量二.md"

BROWSER_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

PASSED = 0
TOTAL = 0
FAILURES: list[str] = []

DROP_JS = """
(function(){
  var dt = new DataTransfer();
  __ADDS__
  var target = __TARGET__;
  if (!target) return 'NO_TARGET';
  ['dragenter', 'dragover', 'drop'].forEach(function (type) {
    target.dispatchEvent(new DragEvent(type, {
      bubbles: true, cancelable: true, dataTransfer: dt, shiftKey: __SHIFT__
    }));
  });
  return 'DISPATCHED';
})()
"""


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


def doc_content(base_url: str, path: str) -> str:
    code, raw = fetch(base_url, "/api/docs/" + urllib.parse.quote(path, safe="/"))
    if code != 200:
        return ""
    try:
        return json.loads(raw.decode("utf-8")).get("content", "")
    except (ValueError, AttributeError):
        return ""


def normalize(text: str) -> str:
    return (text or "").replace("\r\n", "\n").strip()


async def run_browser_checks(browser: Path, base_url: str, profile_dir: Path) -> None:
    import websockets  # 局部导入：未安装时由调用方跳过

    port = free_port()
    chrome = subprocess.Popen(
        [str(browser), "--headless=new", "--disable-gpu", "--no-sandbox",
         "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
         "--window-size=1440,900", "about:blank"],
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
                inner = result.get("result", {})
                return inner.get("value", "UNDEFINED")

            async def goto(url: str, ready_expression: str) -> None:
                await call("Page.navigate", {"url": url})
                for _ in range(60):
                    await asyncio.sleep(0.3)
                    if await evaluate(ready_expression):
                        break
                await asyncio.sleep(0.5)

            async def drop(adds: str, target_expression: str, shift: bool = False) -> str:
                script = (DROP_JS
                          .replace("__ADDS__", adds)
                          .replace("__TARGET__", target_expression)
                          .replace("__SHIFT__", "true" if shift else "false"))
                return await evaluate(script)

            async def notice() -> str:
                return await evaluate(
                    "document.querySelector('.notice')"
                    " ? document.querySelector('.notice').textContent.trim() : ''")

            await call("Page.enable")
            # 记录前端真正发出的导入请求，便于确认只提交一次
            await goto(base_url + "/", "document.querySelectorAll('.card').length > 0")
            check("卡片库正常渲染", await evaluate("document.querySelectorAll('.card').length") > 0)
            await evaluate("""
            window.__importCalls = [];
            (function () {
              var original = window.fetch;
              window.fetch = function (url, options) {
                if (String(url).indexOf('/api/import') >= 0 && options && options.body) {
                  window.__importCalls.push(options.body);
                }
                return original.apply(this, arguments);
              };
            })();
            """)

            card = (f"Array.from(document.querySelectorAll('.card'))"
                    f".find(function (el) {{ return el.textContent.indexOf('{TEST_DIR}') >= 0; }})")

            # 1) 拖一个 .md 到顶层目录卡片
            check("拖拽事件成功派发到目录卡片",
                  await drop("dt.items.add(new File(['# 拖入文档\\n\\n正文'], '拖入文档.md',"
                             " {type: 'text/markdown'}));", card) == "DISPATCHED")
            await asyncio.sleep(1.8)
            check("卡片拖入后提示导入成功", "拖入" in await notice() and "1 篇" in await notice(),
                  await notice())
            check("卡片拖入后文件真实写入 data/", "# 拖入文档" in doc_content(base_url, DOC_MAIN),
                  doc_content(base_url, DOC_MAIN)[:60])
            check("前端只提交一次导入请求", await evaluate("window.__importCalls.length") == 1,
                  str(await evaluate("window.__importCalls.length")))
            await evaluate("Array.from(document.querySelectorAll('.card'))"
                           ".forEach(function (el) { el.dispatchEvent(new MouseEvent('dblclick',"
                           " {bubbles: true})); })")
            check("拖放结束后提示条自动消失",
                  await evaluate("!document.querySelector('.file-drop-hint')"))

            # 2) 目录页空白处拖入 → 当前目录
            await goto(base_url + "/#/dir/" + urllib.parse.quote(TEST_DIR, safe=""),
                       "!!document.querySelector('.dir-view')")
            check("进入测试目录的目录页", await evaluate("!!document.querySelector('.dir-view')"))
            check("目录页拖入空白处成功派发",
                  await drop("dt.items.add(new File(['# 空白处拖入'], '空白处拖入.md'));",
                             "document.querySelector('.main')") == "DISPATCHED")
            await asyncio.sleep(1.8)
            check("空白处拖入写入当前目录",
                  "# 空白处拖入" in doc_content(base_url, TEST_DIR + "/空白处拖入.md"),
                  await notice())

            # 3) 拖到子文件夹 tile → 子目录
            check("拖入子文件夹成功派发",
                  await drop("dt.items.add(new File(['# 子目录文档'], '子目录文档.md'));",
                             "document.querySelector('.dir-tile')") == "DISPATCHED")
            await asyncio.sleep(1.8)
            check("子文件夹拖入写入该子目录",
                  "# 子目录文档" in doc_content(base_url, DOC_SUB), await notice())

            # 4) 非 .md 文件被忽略
            check("非 md 文件拖入派发成功",
                  await drop("dt.items.add(new File(['abc'], '说明.txt', {type: 'text/plain'}));",
                             "document.querySelector('.dir-tile')") == "DISPATCHED")
            await asyncio.sleep(1.2)
            check("非 md 文件给出明确提示", "没有 .md" in await notice(), await notice())

            # 5) 一次拖入多个文件
            check("多文件拖入派发成功",
                  await drop("dt.items.add(new File(['# 批量一'], '批量一.md'));"
                             "dt.items.add(new File(['# 批量二'], '批量二.md'));",
                             "document.querySelector('.main')") == "DISPATCHED")
            await asyncio.sleep(2.0)
            check("多文件全部写入当前目录",
                  "# 批量一" in doc_content(base_url, DOC_MANY_A)
                  and "# 批量二" in doc_content(base_url, DOC_MANY_B), await notice())

            # 6) 按住 Shift 覆盖同名（此时停留在测试目录页，拖到页面空白处）
            check("同名覆盖拖入派发成功",
                  await drop("dt.items.add(new File(['# 覆盖后的内容'], '拖入文档.md'));",
                             "document.querySelector('.main')", shift=True) == "DISPATCHED")
            await asyncio.sleep(2.0)
            check("按住 Shift 拖入覆盖同名文档",
                  normalize(doc_content(base_url, DOC_MAIN)) == "# 覆盖后的内容",
                  normalize(doc_content(base_url, DOC_MAIN))[:60])
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

    check("前端能区分系统文件拖拽与内部拖拽",
          "function isFileDrag" in app_js and "types[i] === 'Files'" in app_js)
    check("支持递归读取拖入的整个文件夹",
          "function readDroppedEntry" in app_js and "createReader" in app_js)
    check("拖入内容经现有导入接口提交",
          "collectDropPayload" in app_js and "'/api/import'" in app_js
          and "target_dir: destination" in app_js)
    check("拖放目标覆盖卡片、文件夹、面包屑与页面空白",
          "onFileDragOver" in app_js and "onMainDragOver" in app_js
          and "fileDropTarget === card.path" in index_html
          and "fileDropTarget === item.path" in index_html
          and "fileDropTarget === crumb.path" in index_html)
    check("页面挂载了拖入提示条与目标高亮样式",
          "file-drop-hint" in index_html and "fileDragActive" in index_html
          and ".file-drop-hint" in style_css and "file-drop-active" in style_css)
    check("全局拦截文件拖放避免浏览器直接打开文件",
          "window.addEventListener('dragover', this.dragOverHandler)" in app_js
          and "window.addEventListener('drop', this.dropHandler)" in app_js)

    browser = find_browser()
    try:
        import websockets  # noqa: F401
        has_ws = True
    except ImportError:
        has_ws = False

    if browser is None:
        print("[SKIP] 未找到 Chrome / Edge，跳过浏览器交互验证")
        print(f"\n结果：{PASSED}/{TOTAL} 项通过")
        return 1 if FAILURES else 0
    if not has_ws:
        print("[SKIP] 未安装 websockets，跳过浏览器交互验证")
        print(f"\n结果：{PASSED}/{TOTAL} 项通过")
        return 1 if FAILURES else 0

    print(f"使用浏览器：{browser}")
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    profile_dir = Path(tempfile.mkdtemp(prefix="mdfm-drop-"))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        check("uvicorn 启动并响应健康检查", wait_ready(base_url))
        if FAILURES:
            return 1
        check("创建顶层测试目录",
              fetch(base_url, "/api/dirs/" + urllib.parse.quote(TEST_DIR, safe="/"), "POST")[0] in (200, 409))
        check("创建测试子目录",
              fetch(base_url, "/api/dirs/" + urllib.parse.quote(TEST_SUB, safe="/"), "POST")[0] in (200, 409))

        asyncio.run(run_browser_checks(browser, base_url, profile_dir))
    finally:
        # 清理：删除测试目录（进回收站后由 trash_cleanup 按标记移除）
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
            print(output.strip()[-1200:])

    print(f"\n结果：{PASSED}/{TOTAL} 项通过")
    if FAILURES:
        print("失败项：" + "、".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
