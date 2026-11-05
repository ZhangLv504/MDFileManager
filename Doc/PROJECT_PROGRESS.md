# 项目进度与架构契约

> 状态：阶段一、二、三均已完成并通过验证；三个分支分别为 `stage-1-backend`、`stage-2-frontend`、`stage-3-render-enhancement`。

## 核心需求与阶段划分

### 阶段一：后端文件系统映射与 API 构建 (Backend)
- **目标**：基于 FastAPI 搭建提供 CRUD 功能的底层接口。
- **机制**：
  - 在项目根目录建立 `data/Projects` 和 `data/Knowledge` 等基础文件夹。
  - **Read**: 提供接口获取整个 `data/` 目录的树形结构 JSON（按分类展示）。
  - **Read Content**: 提供接口读取指定 MD 文件的文本源码。
  - **Create/Update**: 提供接收 Markdown 文本的接口 `PUT /api/docs/{category}/{filename}`，如果文件不存在则新建，存在则覆盖更新。
  - **Delete**: 提供接口 `DELETE /api/docs/{category}/{filename}`。
- **输出**：可直接通过 Swagger UI (`/docs`) 进行完整测试的 FastAPI `main.py` 及相关路由。

### 阶段二：前端文档树与 Markdown 高保真渲染编辑器 (Frontend)
- **目标**：实现浏览器端的展示与编辑，保证格式渲染正确。
- **机制**：
  - **技术栈选型**：使用 TS/JS 编写前端交互逻辑。
  - **侧边栏**：请求分类树 API，使用树形组件渲染（项目、知识点）。
  - **主区域（高保真渲染）**：集成 Markdown 解析引擎与编辑器组件（如 `Vditor`、`markdown-it` + CSS 样式）。确保从接口拿到的纯文本源码能够正确转换为排版规整的 HTML 展示（包含标题、表格、加粗、代码高亮等）。
  - **交互**：点击侧边栏树节点 -> 加载 MD 文本并在主区域正确渲染 -> 进入编辑模式修改 -> 点击保存 -> 调用 PUT 接口无刷新增量/覆盖更新。
- **输出**：独立的 `index.html`，以及对应的 TS/JS 脚本和必要的 Markdown 渲染依赖配置。

### 阶段三：渲染能力增强与真实浏览器验证
- **目标**：补齐 README 提到的数学公式渲染，并用真实浏览器验证端到端渲染效果。
- **机制**：
  - 本地化 KaTeX（JS / CSS / 20 个 woff2 字体），离线可用。
  - 为 marked 注册 `$...$` / `$$...$$` 扩展，公式先转占位符，经 DOMPurify 净化、Vue 挂载后再由 KaTeX 原地填充；代码块中的 `$` 不参与解析。
  - 增加 URL 深链接 `#/doc/...`，打开链接即自动选中并渲染指定文档。
  - 用系统自带无头 Chrome / Edge `--dump-dom` 做真实浏览器验证。
- **输出**：`web/math.js`、`web/vendor/katex/`、`tests/browser_smoke_test.py`。

## 阶段交付契约

1. **接口先行**：必须先完成阶段一，确保能够通过 API 正确读写本地硬盘上的 MD 文件后，再进行界面的开发。
2. **安全第一**：后端在处理 `category` 和 `filename` 参数时，必须过滤 `..` 等路径跳转字符，防止读取或覆盖系统文件。
3. **无缝热更新与渲染**：前端保存操作为无刷新异步提交，更新成功后需同步刷新视图中的 Markdown 渲染效果。

## 交付记录

### 阶段一 · 后端（`stage-1-backend`，提交 `1446cbd`）
- `main.py`：FastAPI 应用；`data/Projects`、`data/Knowledge` 自动创建；`GET /api/tree`、`GET /api/docs/{path}`、`PUT /api/docs/{path}`、`DELETE /api/docs/{path}`；UTF-8 原子写入、中文文件名、路径遍历与符号链接逃逸防御、大小限制。
- `tests/smoke_test.py`：自动拉起 uvicorn 的端到端验证，**25/25 项通过**。

### 阶段二 · 前端（`stage-2-frontend`，提交 `7f5b8af`）
- `web/`：Vue3 + TS/JS 独立静态页；递归文档树、marked + DOMPurify + highlight.js 高保真渲染、源码与实时预览双栏编辑、新建 / 保存 / 删除全部为无刷新异步提交；渲染依赖已本地化到 `web/vendor/`，离线可用。
- `main.py` 追加根路径静态托管，`/api/*` 与 `/docs` 优先匹配。
- `tests/frontend_smoke_test.py`：页面、静态资源、marked 渲染输出、API 联动验证，初版 **22/22 项通过**；阶段一回归 25/25 仍通过。

### 阶段三 · 渲染增强（`stage-3-render-enhancement`）
- KaTeX 0.16.22 本地化；`web/math.js` 公式扩展；`index.html` / `app.js` / `style.css` 接入公式与 URL 深链接；示例文档补充公式段落。
- `tests/frontend_smoke_test.py` 扩充为 **29/29 项通过**（含 JS 语法、marked 与公式扩展探针、KaTeX 静态资源）。
- `tests/browser_smoke_test.py`：无头 Chrome 真实 DOM 验证，**13/13 项通过**（Vue 挂载、文档树、标题表格、代码高亮、KaTeX 行内/块级公式、深链接）。
- 阶段一回归 **25/25**、阶段二/三 HTTP **29/29**、真实浏览器 **13/13**，三套验证全绿。

### 运行方式

```bash
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`，接口文档 `http://127.0.0.1:8000/docs`；完整依赖清单与启动说明见 `Doc/SETUP.md`。

```bash
.venv/Scripts/python.exe tests/smoke_test.py
.venv/Scripts/python.exe tests/frontend_smoke_test.py
.venv/Scripts/python.exe tests/browser_smoke_test.py
```

## 当前能力边界

- README 列出的标题、表格、代码块高亮、公式已全部覆盖；公式非法时保留原文，不中断页面。
- 浏览器验证依赖系统安装 Chrome / Edge（不下载浏览器）；未安装时仅该项验证不可用。
- 未涉及多用户、权限、移动端适配与文档版本历史——按业务定义，同名覆盖即版本更新。
