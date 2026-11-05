# 项目进度与架构契约

> 状态：阶段一～七均已完成并通过验证；七个分支依次为 `stage-1-backend`、`stage-2-frontend`、`stage-3-render-enhancement`、`stage-4-dir-management`、`stage-5-cards-rename`、`stage-6-card-only`、`stage-7-dir-page`。

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
- **机制**：使用 TS/JS 编写交互逻辑；侧边栏展示分类树；主区域用标准解析库渲染 Markdown；保存走无刷新 PUT。
- **输出**：独立的 `index.html`、TS/JS 脚本与本地化渲染依赖。
- **备注**：该阶段的侧栏树在阶段六按用户要求移除，导航改为纯卡片。

### 阶段三：渲染能力增强与真实浏览器验证
- **目标**：补齐 README 提到的数学公式渲染，并用真实浏览器验证端到端渲染效果。
- **机制**：本地化 KaTeX；为 marked 注册 `$...$` / `$$...$$` 扩展（占位符经 DOMPurify 后由 KaTeX 填充）；增加文档深链接 `#/doc/...`；无头 Chrome `--dump-dom` 验证。
- **输出**：`web/math.js`、`web/vendor/katex/`、`tests/browser_smoke_test.py`。

### 阶段四：目录管理与分类新建
- **目标**：让「新建」按当前是否选中目录区分行为。
- **机制**：`POST /api/dirs/{path}` 幂等建目录；目录选中与展开分离；新建对话框按选中状态切换目录/文档；目录深链接 `#/dir/...`。
- **输出**：目录接口、前端分类新建逻辑、三套验证脚本扩充。

### 阶段五：顶层目录卡片与右键重命名
- **目标**：最外层目录改为卡片式浏览，并支持右键重命名文档与目录。
- **机制**：
  - `PATCH /api/rename`（只改名、冲突 409、非法名 400、同名幂等）、`PUT /api/descriptions/{path}`（写 `.description.md`），`GET /api/tree` 返回目录 `description`。
  - 路径校验抽为 `_validate_segment` / `_parse_relative_path`，原子写抽为 `_atomic_write`。
  - 顶层目录卡片（名称/文档数/作用说明，flex 流式，目录在前文档在后，卡片内普通目录递归展开）；右键菜单重命名与编辑说明。
- **输出**：两个新接口、卡片视图与右键菜单、`.description.md` 演示说明、`tests/stage5_smoke_test.py`。

### 阶段六：移除侧栏树，纯卡片导航
- **目标**：有卡片后不再需要树，界面只保留卡片导航。
- **机制**：
  - 删除 `TreeNode` 组件、`#tree-node-tpl` 模板、侧栏 DOM 与全部树相关 CSS/状态（`expanded`、`toggleNode`、expandAll）。
  - 卡片标题可点击选中顶层目录（卡片与条目高亮），卡片内文件夹点击选中并展开；「已选目录」提示移到卡片视图头部。
  - 打开文档后顶栏新增「← 目录」按钮返回卡片视图（保留未保存确认与深链接同步）。
  - 右键重命名与说明编辑仍覆盖卡片头与所有卡片条目。
- **输出**：精简后的 `web/index.html` / `app.js` / `style.css`，四套验证脚本同步更新。后端接口无变化，未引入新依赖。

## 阶段交付契约

1. **接口先行**：必须先完成阶段一，确保能够通过 API 正确读写本地硬盘上的 MD 文件后，再进行界面的开发。
2. **安全第一**：后端在处理 `category` 和 `filename` 参数时，必须过滤 `..` 等路径跳转字符，防止读取或覆盖系统文件。
3. **无缝热更新与渲染**：前端保存操作为无刷新异步提交，更新成功后需同步刷新视图中的 Markdown 渲染效果。

## 交付记录

### 阶段一 · 后端（`stage-1-backend`，提交 `1446cbd`）
- `main.py`：四个 API、目录自动创建、UTF-8 原子写、中文名、路径遍历与符号链接防御；`tests/smoke_test.py` 初版 25/25。

### 阶段二 · 前端（`stage-2-frontend`，提交 `7f5b8af`）
- Vue3 静态页、递归树、双栏编辑、无刷新保存；渲染依赖本地化；`tests/frontend_smoke_test.py` 初版 22/22；新增 `Doc/SETUP.md`（`2dab7e8`）。

### 阶段三 · 渲染增强（`stage-3-render-enhancement`，提交 `c8f3e31`）
- KaTeX 0.16.22 本地化、`web/math.js` 公式扩展、文档深链接、无头 Chrome 验证。

### 阶段四 · 目录管理（`stage-4-dir-management`，提交 `da0bbf6`）
- 清理 `Doc/NEW_CHAT_PROMPT.md` 残留；`POST /api/dirs/{path}`；目录选中与分类新建；目录深链接。三套验证 36/36 + 35/35 + 19/19。

### 阶段五 · 卡片与重命名（`stage-5-cards-rename`，提交 `76cb17c`）
- `PATCH /api/rename`、`PUT /api/descriptions/{path}`、树节点 `description`；顶层卡片视图、右键菜单、目录说明；新增 `tests/stage5_smoke_test.py` 31/31。

### 阶段六 · 纯卡片导航（`stage-6-card-only`）
- 移除侧栏树及全部相关代码/样式；卡片承担选中、展开、右键与说明编辑；新增返回入口。
- 四套验证 36/36 + 37/37 + 21/21 + 33/33；后端零改动。

### 阶段七 · 目录详情页（`stage-7-dir-page`）
- 用户要求「双击卡片进入新的页面，而不是子目录或者文件都在卡片上」。
- 一级卡片只保留名称、文档数、作用描述与「双击进入目录」提示，删除 `CardItem` 递归组件、`card-items` 平铺与 `cardExpanded` 展开状态。
- 新增目录详情页：面包屑、目录名、可编辑说明、文件夹区与文档区（均 flex 流式、文件夹在前）；双击文件夹进入下一级，单击文档打开；右键重命名覆盖卡片、目录条目与文档条目。
- 视图状态由 `activeDirPath` / `currentPath` 推导（卡片库 / 目录页 / 文档页），顶栏「← 返回」逐级回退；`#/dir/...` 改为进入目录页并自动选中，文档深链接自动带出父目录便于返回。
- 四套验证全绿：`tests/smoke_test.py` **36/36**、`tests/frontend_smoke_test.py` **37/37**、`tests/browser_smoke_test.py` **22/22**、`tests/stage5_smoke_test.py` **34/34**；后端零改动。

### 运行方式

```bash
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`，接口文档 `http://127.0.0.1:8000/docs`；完整依赖清单与启动说明见 `Doc/SETUP.md`。修改 `main.py` 后需重启服务，前端静态文件即时生效。

```bash
.venv/Scripts/python.exe tests/smoke_test.py
.venv/Scripts/python.exe tests/frontend_smoke_test.py
.venv/Scripts/python.exe tests/browser_smoke_test.py
.venv/Scripts/python.exe tests/stage5_smoke_test.py
```

## 当前能力边界

- README 列出的标题、表格、代码块高亮、公式已全部覆盖；公式非法时保留原文，不中断页面。
- 重命名只改名称、不移动位置；**不提供目录删除接口**，删除需手动操作文件系统。
- 界面无树形侧栏：一级卡片只作入口，层级浏览靠双击进入目录页，返回用顶栏「← 返回」或面包屑。
- 浏览器验证依赖系统安装 Chrome / Edge（不下载浏览器）；未安装时对应脚本跳过或失败，其余脚本不受影响。
- 未涉及多用户、权限、移动端适配与文档版本历史——按业务定义，同名覆盖即版本更新。
