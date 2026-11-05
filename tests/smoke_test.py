"""阶段一可运行结果验证：自动拉起 uvicorn，端到端验证四个 API 与安全边界。

运行（在项目根目录）：
    .venv/Scripts/python.exe tests/smoke_test.py
退出码 0 表示全部通过；脚本会自动清理自己创建的测试文档。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

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


def main() -> int:
    port = free_port()
    client = ApiClient(f"http://127.0.0.1:{port}")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    doc_a = "Projects/__smoke__中文文档.md"
    doc_b = "Knowledge/__smoke__前端/__smoke__渲染说明.md"
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
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
        for relative in (doc_a, doc_b):
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
