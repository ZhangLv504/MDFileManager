# 开发环境依赖与启动指南

> 记录本项目开发过程中**安装 / 下载的全部第三方库、安装命令、各库的作用**，以及**如何启动当前项目**。
> 对应代码状态：阶段一 `stage-1-backend`（`1446cbd`）+ 阶段二 `stage-2-frontend`（`7f5b8af`）+ 阶段三 `stage-3-render-enhancement`（`c8f3e31`）+ 阶段四 `stage-4-dir-management`（`da0bbf6`）+ 阶段五 `stage-5-cards-rename`（`76cb17c`）+ 阶段六 `stage-6-card-only`（`a51d5cf`）+ 阶段七 `stage-7-dir-page`（`94efd80`）+ 阶段八内容操作 `stage-8-content-ops` + 阶段九内容整理 `stage-9-content-organize`。
> 本文命令均在 Windows + Git Bash 下验证通过；CMD / PowerShell 中把 `.venv/Scripts/` 换成 `.venv\Scripts\` 即可。

---

## 一、运行环境

| 项 | 版本 | 说明 |
| --- | --- | --- |
| Python | **3.12.7** | 项目指定版本，本机通过 `py -3.12` 选择（`E:\Software\Python3127\python.exe`） |
| Node.js | v22.22.2（可选） | **仅**用于开发期的 `node --check` 语法校验、marked / KaTeX 渲染探针，以及 `npm pack` 下载 KaTeX；项目运行不需要 |
| Chrome / Edge | 系统自带（可选） | **仅**用于 `tests/browser_smoke_test.py` 与 `tests/stage5_smoke_test.py` 的真实无头浏览器验证；不下载浏览器，项目运行不需要 |
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
| **fastapi** | `pip install "fastapi>=0.115,<1.0"` | 0.162.0 | Web 框架。声明 `/api/*` 路由、用 Pydantic 模型校验请求体、自动生成 OpenAPI 文档与 Swagger UI（`/docs`）。本项目只用它输出 JSON，不使用模板引擎。 |
| **uvicorn[standard]** | `pip install "uvicorn[standard]>=0.30,<1.0"` | 0.54.0 | ASGI 服务器，把 HTTP 请求交给 FastAPI 应用。`[standard]` 额外装上 httptools、watchfiles、websockets、python-dotenv、PyYAML 等可选组件，用于更快的 HTTP 解析、`--reload` 热重载与配置读取。 |

### 2.3 传递依赖（随直接依赖自动安装，无需手动执行）

| 库 | 版本 | 作用 | 引入者 |
| --- | --- | --- | --- |
| starlette | 1.10.0 | FastAPI 底层 ASGI 框架；本项目用到 `StaticFiles` 静态托管与 `CORSMiddleware` | fastapi |
| pydantic | 2.14.3 | 请求体模型（文档、重命名、移动、说明）的校验与序列化 | fastapi |
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

这些库**不是 pip install 安装的**，而是从 jsDelivr 下载、或从 npm 发行包中取出后随仓库提交，目的是让页面在**完全离线**环境下也能正确渲染 Markdown 与公式。项目本体不需要 Node.js、npm 或构建步骤。

### 3.1 基础渲染库（jsDelivr 下载）

开发时执行的命令（在 `web/vendor/` 目录内）：

```bash
mkdir -p web/vendor && cd web/vendor

curl -fsSL -o vue.global.prod.js          "https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.prod.js"
curl -fsSL -o marked.min.js               "https://cdn.jsdelivr.net/npm/marked/marked.min.js"
curl -fsSL -o purify.min.js               "https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"
curl -fsSL -o highlight.min.js            "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11/highlight.min.js"
curl -fsSL -o highlight-light.css         "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11/styles/github.css"
curl -fsSL -o github-markdown-light.css   "https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-light.css"
```

### 3.2 数学公式库 KaTeX（npm 发行包）

KaTeX 除 JS/CSS 外还依赖一批字体文件，逐个用 curl 下载很繁琐，因此用 `npm pack` 取整包后只保留需要的文件：

```bash
mkdir -p /tmp/mdfm-katex && cd /tmp/mdfm-katex
npm pack katex@0.16.22 --silent
tar -xzf katex-0.16.22.tgz

# 回到项目根目录后执行
mkdir -p web/vendor/katex/fonts
cp /tmp/mdfm-katex/package/dist/katex.min.js  web/vendor/katex/
cp /tmp/mdfm-katex/package/dist/katex.min.css web/vendor/katex/
cp /tmp/mdfm-katex/package/dist/fonts/*.woff2 web/vendor/katex/fonts/
```

> 本机 npm registry 指向 `registry.npmmirror.com` 镜像。只保留 20 个 `woff2`（约 296 KB）：现代浏览器会优先使用 CSS 中排在首位的 woff2，不会去请求同目录的 woff / ttf 备用格式。

### 3.3 库清单与作用

| 文件 | 库 / 版本 | 作用 |
| --- | --- | --- |
| `vue.global.prod.js` | Vue **3.5.44** | 视图层框架（含模板编译器的全局构建版）。负责卡片视图、目录页、右键菜单、拖拽整理、新建/编辑/保存等交互；无需打包工具。 |
| `marked.min.js` | marked **15.0.12** | 标准 Markdown 解析引擎，把源码转成 HTML，支持 GFM 标题、表格、列表、代码块等。 |
| `purify.min.js` | DOMPurify **3.4.17** | 净化 marked 输出的 HTML，过滤脚本与危险属性，防止文档内容引发 XSS。 |
| `highlight.min.js` | highlight.js **11.12.0** | 对 `pre code` 代码块做语法高亮（`hljs.highlightElement`）。 |
| `github-markdown-light.css` | github-markdown-css **5.9.0** | GitHub 风格 Markdown 排版样式，保证标题、表格、引用、间距、字体正确。 |
| `highlight-light.css` | highlight.js **11.12.0** 的 github 主题 | 代码高亮配色（浅色）。 |
| `katex/katex.min.js` | KaTeX **0.16.22** | 把 LaTeX 公式渲染成 HTML + CSS，支持行内 `$...$` 与块级 `$$...$$`。 |
| `katex/katex.min.css` | KaTeX **0.16.22** | 公式排版样式，引用同目录 `fonts/*.woff2`。 |
| `katex/fonts/*.woff2` | KaTeX **0.16.22**，20 个文件 | 数学符号与字形字体，离线渲染公式必需。 |
| `../math.js`（项目自写，非第三方） | — | 为 marked 注册公式扩展：先把公式换成占位 `span`，等 DOMPurify 净化、Vue 挂载后再由 KaTeX 原地填充，避免 marked 的反斜杠转义破坏公式。 |

引用顺序见 `web/index.html`；完整渲染链为 **marked（含公式扩展）→ DOMPurify 净化 → Vue `v-html` → highlight.js 代码高亮 + KaTeX 公式填充**。代码块里的 `$` 不参与公式解析。阶段四～九均未引入新第三方库：拖拽整理使用浏览器原生 HTML5 Drag & Drop API，无额外依赖。

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

前台运行时按 `Ctrl+C` 停止。开发期如需热重载：`--reload`（依赖 watchfiles）。**修改 `main.py` 后必须重启服务**；前端静态文件则是即时生效的。

### 4.2 访问地址与接口

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:8000/` | 前端页面：卡片库 → 目录详情页 → 文档页 的三级导航 |
| `http://127.0.0.1:8000/#/doc/分类%2F文档.md` | 文档深链接，打开即自动渲染指定文档（路径需 URL 编码） |
| `http://127.0.0.1:8000/#/dir/分类%2F子目录` | 目录深链接，打开即进入该目录详情页 |
| `http://127.0.0.1:8000/docs` | Swagger UI，可直接测试全部后端接口 |
| `http://127.0.0.1:8000/api/health` | 健康检查，返回 `data/` 路径与基础分类 |
| `GET /api/tree` | 目录树 JSON，目录节点含 `description` 字段 |
| `POST /api/dirs/{目录路径}` | 新建目录（可含多级父目录），已存在时幂等返回 `created: false` |
| `DELETE /api/dirs/{目录路径}` | 删除空目录（非空返回 409）；加 `?recursive=true&confirm=目录名` 时带名称确认递归删除全部内容 |
| `PATCH /api/rename` | 重命名文档或目录，请求体 `{path, new_name}`，只改名不移动 |
| `PATCH /api/move` | 移动文档或目录，请求体 `{path, target_dir}`；`target_dir` 为空表示 `data/` 顶层（只允许目录） |
| `PUT /api/descriptions/{目录路径}` | 写入目录作用说明，请求体 `{content}`，保存到该目录的 `.description.md` |
| `GET / PUT / DELETE /api/docs/{分类}/{文件名}.md` | 读取 / 保存（覆盖）/ 删除 Markdown 文档 |

前端页面与 API 由**同一个 uvicorn 进程**提供，因此不存在跨域问题；页面里的 `fetch` 全部走相对路径 `/api/...`。

### 4.3 验证是否正常运行

```bash
.venv/Scripts/python.exe tests/smoke_test.py            # 后端文档/目录/移动/递归删除 API：65/65
.venv/Scripts/python.exe tests/frontend_smoke_test.py  # 前端 HTTP 层与三级导航：47/47
.venv/Scripts/python.exe tests/browser_smoke_test.py   # 真实浏览器渲染与拖拽 DOM：27/27
.venv/Scripts/python.exe tests/stage5_smoke_test.py    # 重命名/说明/删除/移动/卡片：52/52
```

四个脚本都会自行拉起一个临时端口的 uvicorn、跑完全部用例后关闭并清理测试文档与目录，**不需要先手动启动服务**。若装有 Node.js，第二个脚本会额外做 JS 语法检查、marked 渲染探针与公式扩展探针；第三、四个脚本调用系统自带的无头 Chrome / Edge `--dump-dom`，分别验证文档页与目录页/卡片库的真实 DOM，不下载浏览器。

### 4.4 关键目录

```text
MDFileManager/
├── main.py                 # FastAPI 应用：文档 CRUD + 目录增删 + 重命名 + 移动 + 递归删除 + 说明 + 静态托管
├── requirements.txt        # Python 直接依赖
├── data/                   # 用户文档（.md 不入库，仅保留 .gitkeep）
│   ├── Projects/
│   │   └── .description.md # 可选的目录说明（隐藏文件，不出现在文档列表）
│   └── Knowledge/
├── web/                    # 纯静态前端（无侧栏树、无递归卡片组件）
│   ├── index.html          # 卡片库 / 目录页 / 文档页 + 对话框 + 右键菜单 + 拖放目标
│   ├── app.js              # 交互逻辑（双击进入 / 面包屑 / 返回 / 右键 / 拖拽移动 / 增删 / 编辑 / 深链接）
│   ├── math.js             # marked 公式扩展 + KaTeX 填充
│   ├── style.css
│   └── vendor/             # 已本地化的前端库（含 katex/fonts/*.woff2）
├── tests/                  # 四个可运行验证脚本
└── Doc/                    # 需求、协作约定、进度、新会话指令与本指南
```

### 4.5 交互说明与常见情况

- **三级视图**：一级「文档库」只显示目录卡片（名称、文档数、作用描述）；**双击卡片进入该目录的独立详情页**；在目录页单击文档进入文档页。顶栏「← 返回」按层级逐级回退，面包屑可直接跳到任一级。
- **卡片不罗列内容**：一级卡片里不再平铺子目录和 `.md` 文档；子目录与文档只在各自的目录页中展示，分「文件夹」「文档」两区，均为 flex 流式布局，**文件夹在前、文档在后**。
- **目录页**：显示面包屑、目录名、作用说明（可点「编辑说明」修改）与内容分块；双击文件夹进入下一级，单击文档打开；标题栏有「+ 文件夹」「+ 文档」快捷入口，直接以当前目录为位置新建。
- **右键菜单**：目录可用「打开目录 / 重命名 / 移动到… / 在此新建文件夹 / 在此新建文档 / 编辑说明 / 删除目录 / 清空并删除目录…」；文档可用「打开文档 / 重命名 / 移动到… / 删除文档」。删除前有确认弹窗。
- **移动与拖拽整理**：把目录页里的文件夹或文档**拖到另一个文件夹、面包屑上的任一级、目录页上方「移动到上级」区域，或卡片库的另一张卡片**上即可完成移动；也可右键「移动到…」在目录列表里选择目标（自动排除自身及其子目录）。移动成功后当前文档、所在目录、选中目录与地址栏深链接会自动同步。
- **删除规则**：文档可直接删除；「删除目录」**仅空目录可删**（非空返回 409 并提示先清空或用递归删除）；「清空并删除目录…」用于递归删除，需**手动输入完整目录名**作为二次确认，后端也会再次校验该名称。递归删除会连同子目录、文档、`.description.md` 一起移除，且**不跟随符号链接**（发现符号链接直接拒绝），单次上限 2000 项。删除当前文档或当前所在目录后，视图自动回退到上级。
- **选中目录**：单击卡片或目录页里的文件夹可选中（高亮），「已选目录」显示在页面头部；未选中目录时顶栏「新建」只能建顶层目录，选中后可建子目录或 `.md` 文档。
- **重命名**：文档名需 `.md` 结尾（省略自动补全），目录名不能以 `.md` 结尾；同名冲突返回 409，非法名称返回 400。重命名后当前目录、当前文档、选中目录与深链接会自动同步。
- **端口被占用**：换端口 `--port 8001`，或简写启动时设置 `MDFM_PORT=8001`。
- **换机器 / 依赖缺失**：重新执行 `py -3.12 -m venv .venv` 与 `pip install -r requirements.txt`；`.venv/` 被 `.gitignore` 忽略，不随仓库分发。前端库已随仓库提交，无需重新安装。
- **离线使用**：前端库（含 KaTeX 字体）全部本地化，启动与渲染都无需联网；只有首次安装 Python 依赖时需要网络。
- **分享链接**：进入文档或目录后地址栏会带上 `#/doc/...` 或 `#/dir/...`，复制即可直接打开。
- **数据备份**：直接复制 `data/` 目录即可，没有数据库；递归删除不可撤销，重要内容请先备份。

---

## 五、依赖与阶段的对应关系

| 阶段 | 用到的库 | 交付结果 |
| --- | --- | --- |
| 阶段一 · 后端 | fastapi、uvicorn[standard]、pydantic、starlette、httptools、h11、click | 纯 JSON API + Swagger UI；`tests/smoke_test.py` 现为 65/65 |
| 阶段二 · 前端 | Vue、marked、DOMPurify、highlight.js、github-markdown-css | 文档树 + 高保真渲染编辑器；`tests/frontend_smoke_test.py` 现为 47/47 |
| 阶段三 · 渲染增强 | KaTeX 0.16.22（JS + CSS + 20 个 woff2 字体）、系统 Chrome / Edge | 数学公式 + 文档深链接；`tests/browser_smoke_test.py` 现为 27/27 |
| 阶段四 · 目录管理 | 无新增第三方库 | `POST /api/dirs` + 目录选中 + 分类新建 |
| 阶段五 · 卡片与重命名 | 无新增第三方库 | 顶层卡片视图 + 右键重命名 + 目录说明 |
| 阶段六 · 纯卡片导航 | 无新增第三方库 | 移除侧栏树 |
| 阶段七 · 目录详情页 | 无新增第三方库 | 双击卡片进入独立目录页，卡片不再平铺内容 |
| 阶段八 · 内容操作 | 无新增第三方库 | 空目录删除 + 右键菜单/目录页新建与删除 |
| 阶段九 · 内容整理 | 无新增第三方库（原生 HTML5 Drag & Drop） | `PATCH /api/move` 移动 + 拖拽整理 + 带名称确认的递归删除；`tests/stage5_smoke_test.py` 52/52 |
| 开发期校验（可选） | Node.js 22、npm 10 | `node --check`、marked / KaTeX 渲染探针、`npm pack` 下载 KaTeX |

## 六、当前能力边界

- 公式支持行内 `$...$` 与块级 `$$...$$`；代码块中的 `$` 不解析；KaTeX 以 `throwOnError: false` 渲染，非法公式保留原文不中断页面。
- 重命名只改名称、移动只改位置，两者都不改文件内容；移动会拒绝循环（目录移入自身或后代）、同名冲突 409、文档移到 `data/` 顶层、路径遍历与符号链接。
- 递归删除需要输入完整目录名二次确认，且不跟随符号链接、单次上限 2000 项；**没有回收站与撤销**，删除后只能从备份恢复。
- 界面无树形侧栏：一级卡片只作入口，层级浏览通过双击进入目录页；深链接仍可直达文档或目录。
- 浏览器验证脚本依赖系统已安装 Chrome 或 Edge；未安装时对应脚本会跳过或失败，但其余脚本与项目本身不受影响。
- 未涉及多用户、权限、移动端适配与文档版本历史——按需求，同名覆盖即视为版本更新，数据完全落在本地 `data/`。
