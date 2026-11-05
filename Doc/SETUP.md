# 开发环境依赖与启动指南

> 记录本项目开发过程中**安装 / 下载的全部第三方库、安装命令、各库的作用**，以及**如何启动当前项目**。
> 对应代码状态：阶段一 `stage-1-backend`（`1446cbd`）+ 阶段二 `stage-2-frontend`（`7f5b8af`）。
> 本文命令均在 Windows + Git Bash 下验证通过；CMD / PowerShell 中把 `.venv/Scripts/` 换成 `.venv\Scripts\` 即可。

---

## 一、运行环境

| 项 | 版本 | 说明 |
| --- | --- | --- |
| Python | **3.12.7** | 项目指定版本，本机通过 `py -3.12` 选择（`E:\Software\Python3127\python.exe`） |
| Node.js | v22.22.2（可选） | **仅**用于开发期校验 `web/app.js` 语法与 marked 渲染输出，项目运行不需要 |
| 浏览器 | 现代浏览器 | 访问前端页面，无需构建工具、无需联网 |
| 操作系统 | Windows | 命令示例为 Git Bash 风格 |

> 本机默认的 `python` 是 3.13.14，务必用 `py -3.12` 或虚拟环境里的解释器，避免版本不一致。

---

## 二、Python 依赖

### 2.1 安装命令（推荐，一条命令复现）

```bash
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install --disable-pip-version-check --upgrade pip
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

> 本机开发时实际执行的是 `.venv/Scripts/python.exe -m pip install -q --disable-pip-version-check -r requirements.txt`（`-q` 只减少输出），随后用 `pip list` 得到下方实测版本。

`requirements.txt` 内容：

```text
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
```

逐个安装（与上等价）：

```bash
.venv/Scripts/python.exe -m pip install "fastapi>=0.115,<1.0" "uvicorn[standard]>=0.30,<1.0"
```

按本次开发的实测版本精确复现：

```bash
.venv/Scripts/python.exe -m pip install "fastapi==0.162.0" "uvicorn[standard]==0.54.0"
```

### 2.2 直接依赖

| 库 | 安装命令 | 实测版本 | 作用 |
| --- | --- | --- | --- |
| **fastapi** | `pip install "fastapi>=0.115,<1.0"` | 0.162.0 | Web 框架。声明 `/api/*` 路由、用 Pydantic 模型校验 PUT 请求体、自动生成 OpenAPI 文档与 Swagger UI（`/docs`）。本项目只用它输出 JSON，不使用模板引擎。 |
| **uvicorn[standard]** | `pip install "uvicorn[standard]>=0.30,<1.0"` | 0.54.0 | ASGI 服务器，把 HTTP 请求交给 FastAPI 应用。`[standard]` 额外装上 httptools、watchfiles、websockets、python-dotenv、PyYAML 等可选组件，用于更快的 HTTP 解析、`--reload` 热重载与配置读取。 |

### 2.3 传递依赖（随直接依赖自动安装，无需手动执行）

| 库 | 版本 | 作用 | 引入者 |
| --- | --- | --- | --- |
| starlette | 1.10.0 | FastAPI 底层 ASGI 框架；本项目用到 `StaticFiles` 静态托管与 `CORSMiddleware` | fastapi |
| pydantic | 2.14.3 | 请求体模型 `DocPayload` 的校验与序列化 | fastapi |
| pydantic_core | 2.50.4 | Pydantic 的 Rust 校验内核 | pydantic |
| annotated-doc | 0.0.5 | 参数注解的文档元数据 | fastapi |
| annotated-types | 0.8.0 | 类型注解约束（如 `Field` 的元数据） | pydantic |
| typing-inspection | 0.4.5 | 运行时解析类型注解 | fastapi / pydantic |
| typing_extensions | 4.16.0 | 新版本类型特性向后兼容 | 多个库 |
| opentelemetry-api | 1.45.2 | 可观测性 / 链路追踪 API（仅接入 OTel 时生效） | fastapi |
| anyio | 4.16.0 | 异步运行时抽象，支撑 Starlette 并发与后台任务 | starlette |
| idna | 3.20 | 国际化域名编码 | anyio |
| click | 8.5.0 | uvicorn 命令行参数解析 | uvicorn |
| h11 | 0.16.0 | HTTP/1.1 协议实现 | uvicorn |
| httptools | 0.9.0 | 高性能 HTTP 解析器（`uvicorn[standard]` 自动启用） | uvicorn[standard] |
| watchfiles | 1.3.0 | 监听文件变更，`--reload` 热重载依赖它 | uvicorn[standard] |
| websockets | 17.4 | WebSocket 协议支持 | uvicorn[standard] |
| python-dotenv | 1.2.4 | 从 `.env` 读取环境变量 | uvicorn[standard] |
| PyYAML | 6.0.3 | 解析 YAML 日志配置 | uvicorn[standard] |
| pip | 24.2 | 包管理器（venv 自带，**非项目依赖**） | Python 3.12 venv |

完整冻结清单（`.venv/Scripts/python.exe -m pip list --format=freeze`）：

```text
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.16.0
click==8.5.0
fastapi==0.162.0
h11==0.16.0
httptools==0.9.0
idna==3.20
opentelemetry-api==1.45.2
pip==24.2
pydantic==2.14.3
pydantic_core==2.50.4
python-dotenv==1.2.4
PyYAML==6.0.3
starlette==1.10.0
typing_extensions==4.16.0
typing-inspection==0.4.5
uvicorn==0.54.0
watchfiles==1.3.0
websockets==17.4
```

需要导出锁定文件时执行：`.venv/Scripts/python.exe -m pip freeze > requirements.lock.txt`。

---

## 三、前端本地化库（`web/vendor/`）

这些库**不是 pip / npm install 安装的**，而是从 jsDelivr 下载后随仓库提交，目的是让页面在**完全离线**环境下也能正确渲染 Markdown。开发时执行的下载命令如下（在 `web/vendor/` 目录内）：

```bash
mkdir -p web/vendor && cd web/vendor

curl -fsSL -o vue.global.prod.js          "https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.prod.js"
curl -fsSL -o marked.min.js               "https://cdn.jsdelivr.net/npm/marked/marked.min.js"
curl -fsSL -o purify.min.js               "https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"
curl -fsSL -o highlight.min.js            "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11/highlight.min.js"
curl -fsSL -o highlight-light.css         "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11/styles/github.css"
curl -fsSL -o github-markdown-light.css   "https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-light.css"
```

| 文件 | 库 / 版本 | 作用 |
| --- | --- | --- |
| `vue.global.prod.js` | Vue **3.5.44** | 视图层框架（含模板编译器的全局构建版）。负责递归文档树组件、响应式状态、新建/编辑/保存等交互；无需打包工具。 |
| `marked.min.js` | marked **15.0.12** | 标准 Markdown 解析引擎，把源码转成 HTML，支持 GFM 标题、表格、列表、代码块等。 |
| `purify.min.js` | DOMPurify **3.4.17** | 净化 marked 输出的 HTML，过滤脚本与危险属性，防止文档内容引发 XSS。 |
| `highlight.min.js` | highlight.js **11.12.0** | 对 `pre code` 代码块做语法高亮（`hljs.highlightElement`）。 |
| `github-markdown-light.css` | github-markdown-css **5.9.0** | GitHub 风格 Markdown 排版样式，保证标题、表格、引用、间距、字体正确。 |
| `highlight-light.css` | highlight.js **11.12.0** 的 github 主题 | 代码高亮配色（浅色），配合上面的 Markdown 样式使用。 |

引用顺序见 `web/index.html`：先加载 4 个 JS 库，最后加载 `web/app.js`；渲染链为 **marked → DOMPurify → highlight.js**。

---

## 四、启动当前项目

### 4.1 首次启动（完整步骤）

```bash
# 1. 进入项目根目录
cd D:/AiProjs/TwoProjs/CustomProjs/MDFileManager

# 2. 用 Python 3.12.7 创建虚拟环境（只需一次）
py -3.12 -m venv .venv

# 3. 安装后端依赖（只需一次）
.venv/Scripts/python.exe -m pip install -r requirements.txt

# 4. 启动服务（data/ 及基础分类目录会在启动时自动创建）
.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

等价的简写启动方式（使用 `main.py` 内置的 `__main__` 入口）：

```bash
.venv/Scripts/python.exe main.py
# 可用环境变量调整：MDFM_HOST / MDFM_PORT
```

前台运行时按 `Ctrl+C` 停止。开发期如需热重载：`--reload`（依赖 watchfiles）。

### 4.2 访问地址

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:8000/` | 前端页面：文档树、Markdown 渲染、编辑与保存 |
| `http://127.0.0.1:8000/docs` | Swagger UI，可直接测试四个后端接口 |
| `http://127.0.0.1:8000/api/health` | 健康检查，返回 `data/` 路径与基础分类 |
| `http://127.0.0.1:8000/api/tree` | `data/` 目录树 JSON |
| `http://127.0.0.1:8000/api/docs/{分类}/{文件名}.md` | GET 读取 / PUT 保存 / DELETE 删除 |

前端页面与 API 由**同一个 uvicorn 进程**提供，因此不存在跨域问题；页面里的 `fetch` 全部走相对路径 `/api/...`。

### 4.3 验证是否正常运行

```bash
.venv/Scripts/python.exe tests/smoke_test.py            # 阶段一：25/25 项通过
.venv/Scripts/python.exe tests/frontend_smoke_test.py  # 阶段二：22/22 项通过
```

两个脚本会自行拉起一个临时端口的 uvicorn、跑完全部用例后关闭并清理测试文档，**不需要先手动启动服务**。若装有 Node.js，第二个脚本还会额外做 `app.js` 语法检查与 marked 渲染输出探针。

### 4.4 关键目录

```text
MDFileManager/
├── main.py                 # FastAPI 应用：四个 API + 静态托管
├── requirements.txt        # Python 直接依赖
├── data/                   # 用户文档（.md 不入库，仅保留 .gitkeep）
│   ├── Projects/
│   └── Knowledge/
├── web/                    # 纯静态前端
│   ├── index.html / app.js / style.css
│   └── vendor/             # 已本地化的前端库
├── tests/                  # 两个阶段的可运行验证脚本
└── Doc/                    # 需求、协作约定、进度与本指南
```

### 4.5 常见情况

- **端口被占用**：换端口 `--port 8001`，或简写启动时设置 `MDFM_PORT=8001`。
- **换机器 / 依赖缺失**：重新执行 `py -3.12 -m venv .venv` 与 `pip install -r requirements.txt`；`.venv/` 被 `.gitignore` 忽略，不随仓库分发。
- **离线使用**：前端库已全部放在 `web/vendor/`，启动与渲染都无需联网；只有首次安装 Python 依赖时需要网络。
- **新增文档**：页面点「新建」，填 `分类/文件名.md`（如 `Knowledge/前端/渲染说明.md`），父目录会自动创建；同名保存即覆盖更新。
- **数据备份**：直接复制 `data/` 目录即可，没有数据库。

---

## 五、依赖与阶段的对应关系

| 阶段 | 用到的库 | 交付结果 |
| --- | --- | --- |
| 阶段一 · 后端 | fastapi、uvicorn[standard]、pydantic、starlette、httptools、h11、click | 纯 JSON API + Swagger UI，`tests/smoke_test.py` 25/25 |
| 阶段二 · 前端 | Vue、marked、DOMPurify、highlight.js、github-markdown-css（均为本地静态文件） | 文档树 + 高保真渲染编辑器，`tests/frontend_smoke_test.py` 22/22 |
| 开发期校验（可选） | Node.js | `node --check web/app.js`、marked 渲染探针 |

## 六、尚未接入的部分

- README 提到的**数学公式渲染**未实现，需要时再引入 KaTeX（JS + CSS + 字体）并加入渲染链。
- 前端尚未做真实浏览器自动化验证，现有验证覆盖 HTTP 层、静态资源、JS 语法与渲染引擎输出。
