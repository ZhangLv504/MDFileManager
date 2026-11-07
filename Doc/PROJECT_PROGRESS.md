# 项目进度与架构契约

> 状态：阶段一～十二均已完成并通过验证；十二个分支依次为 `stage-1-backend`、`stage-2-frontend`、`stage-3-render-enhancement`、`stage-4-dir-management`、`stage-5-cards-rename`、`stage-6-card-only`、`stage-7-dir-page`、`stage-8-content-ops`、`stage-9-content-organize`、`stage-10-recycle-bin`、`stage-11-version-history`、`stage-12-diff-restore`。

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
- **备注**：侧栏树在阶段六按用户要求移除。

### 阶段三：渲染能力增强与真实浏览器验证
- **机制**：本地化 KaTeX；为 marked 注册公式扩展；增加文档深链接；无头 Chrome `--dump-dom` 验证。

### 阶段四：目录管理与分类新建
- **机制**：`POST /api/dirs/{path}` 幂等建目录；目录选中与展开分离；新建对话框按选中状态切换；目录深链接 `#/dir/...`。

### 阶段五：顶层目录卡片与右键重命名
- **机制**：`PATCH /api/rename`、`PUT /api/descriptions/{path}`、树节点 `description`；顶层卡片视图、右键菜单、目录说明。

### 阶段六：移除侧栏树，纯卡片导航
- **机制**：删除 `TreeNode` 组件与侧栏；卡片承担选中、展开、右键与说明编辑；新增返回入口。

### 阶段七：双击卡片进入目录详情页
- **机制**：一级卡片只保留概要；新增目录详情页（面包屑、说明、文件夹/文档两区）；三级视图由 `activeDirPath` + `currentPath` 推导。

### 阶段八：内容管理补全
- **目标**：补齐此前一直标注的能力缺口——目录删除，以及目录页内更顺手的新建/打开/删除操作。
- **机制**：
  - 后端新增 `DELETE /api/dirs/{path}`：仅当目录没有可见子项时允许删除，非空返回 409；删除时一并清理 `.gitkeep` 与 `.description.md` 占位文件，避免一级目录因占位文件永远删不掉。
  - 前端右键菜单按类型扩展：目录提供打开、重命名、在此新建文件夹/文档、编辑说明、删除目录；文档提供打开、重命名、删除文档。删除前有确认。
  - 目录页标题栏增加「+ 文件夹」「+ 文档」快捷入口，直接以当前目录为位置，无需先选中。
  - 删除当前文档或当前所在目录后，自动回退到上级目录/卡片库，并同步选中状态与深链接。
- **输出**：`main.py` 目录删除接口、前端菜单与快捷入口、四套验证脚本扩充。未引入新第三方库。

### 阶段九：移动 / 拖拽整理与递归删除
- **目标**：补齐上一阶段留下的两个能力缺口——「移动 / 拖拽整理目录」与「递归删除（带二次确认）」。
- **机制**：
  - 后端 `PATCH /api/move`，请求体 `{path, target_dir}`（`target_dir` 为空表示 `data/` 顶层，仅允许目录）；拒绝循环移动、同名冲突 409、文档移到顶层、路径遍历与符号链接；移动到原目录幂等返回 `moved: false`。
  - 后端 `DELETE /api/dirs/{path}?recursive=true&confirm=目录名`：服务端强制校验目录名作为二次确认；先完整扫描再删除，遇到符号链接直接拒绝，单次上限 2000 项；返回删除的文档数、文件数与目录数。
  - 前端右键菜单增加「移动到…」（目录列表自动排除自身及子目录）与「清空并删除目录…」（输入目录名二次确认）；卡片、文件夹、文档、面包屑、目录页「移动到上级」区域均支持原生 HTML5 拖放。
  - 移动 / 删除后自动同步 `currentPath`、`activeDirPath`、`selectedDir` 与地址栏深链接（`syncHash` 统一以当前文档优先）。
- **输出**：`main.py` 两个新能力、前端拖放与对话框、四套验证脚本扩充。未引入新第三方库。

### 阶段十：回收站与删除可恢复
- **目标**：补齐上一阶段结尾标注的「不可撤销、没有回收站」缺口，让普通删除与递归删除都可还原。
- **机制**：
  - `DELETE /api/docs/{path}` 与 `DELETE /api/dirs/{path}`（含 `recursive=true`）不再直接抹除，而是把整个条目移到 `data/.trash/<id>/payload/<原名>`，并写 `meta.json` 记录原路径、名称、类型、删除时间、是否递归、文档数与大小；返回 `trashed: true` 与 `trash_id`。`.trash` 是隐藏目录，`_scan` 自动跳过，不进目录树、不入库。
  - 新增 `GET /api/trash`（列表）、`POST /api/trash/restore`（还原到原位置，占用时 409）、`DELETE /api/trash/{id}`（彻底删除单条）、`DELETE /api/trash`（清空）。条目 ID 用白名单校验并 `resolve()` 限制在 `.trash/` 内；写元数据失败会自动把内容移回原处。
  - `_move_path` 统一处理移动：`os.rename` 遇到跨盘 / 跨文件系统（WinError 17 / `EXDEV`）时退化为「复制 + 删除源」，因此可用 `MDFM_TRASH_DIR` 把回收站放到其他磁盘。
  - 前端顶栏「回收站」按钮带条目数角标，面板支持列表 / 还原 / 彻底删除 / 清空；删除确认与提示文案改为「先进回收站，可还原」；右键「清空并删除目录…」改为「清空并移入回收站…」。
  - 回收站上限 500 条，满时删除返回 409；`tests/trash_cleanup.py` 只清理带测试标记的条目，不动用户真实记录。
- **输出**：`main.py` 回收站能力、前端面板与文案、四套验证脚本扩充。未引入新第三方库。

### 阶段十一：文档版本历史
- **目标**：补齐上一阶段结尾标注的「文档版本历史仍未实现」，让「同名覆盖即版本更新」真正留下可回溯的快照。
- **机制**：
  - `PUT /api/docs/{path}` 在内容发生变化时自动写一份快照到 `data/.history/blobs/<id>.md`，并在 `data/.history/index.json` 里按文档路径维护版本列表（版本号、时间、大小、动作）；内容完全相同的重复保存不新增版本。索引读写用 `threading.Lock` 串行化，`_atomic_write` 保证不写坏。
  - 新增 `GET /api/history/{path}`（列表）、`GET /api/versions/{id}`（源码）、`POST /api/history/restore`（还原且还原动作自身生成新版本）、`DELETE /api/history/{path}`（清空）。版本 ID 白名单校验并限制在 `blobs/` 内。
  - `PATCH /api/rename` 与 `PATCH /api/move` 成功后调用 `_history_repath` 迁移历史键；目录操作会连带迁移其下所有文档，目标已有历史时按时间合并并重新编号。
  - 每篇文档最多 50 个版本、全局最多 500 篇 / 50 MB，超限自动裁剪最旧版本并删除对应快照；`MDFM_HISTORY_DIR` 可改存储位置（测试用来做隔离）。
  - 前端顶栏「历史」按钮（仅打开文档时可用），面板左侧版本列表、右侧源码预览并标注与当前内容是否一致，可还原或清空；保存后若面板打开会自动刷新。
- **输出**：`main.py` 版本历史能力、前端面板、四套验证脚本扩充。未引入新第三方库。

### 阶段十二：差异对比与回收站定向还原
- **目标**：补齐上一阶段结尾标注的两个缺口——「快照没有 diff 对比」与「回收站不支持还原到新位置」。
- **机制**：
  - 新增 `GET /api/diff/{path}?from=…&to=…`：`from` / `to` 可为版本 ID 或 `current`（当前文档内容）。用标准库 `difflib.SequenceMatcher` 生成结构化行级差异（`equal` / `add` / `del`、新旧行号）、增删统计与 unified diff 文本；版本归属校验、ID 白名单、单侧 3000 行上限。
  - `POST /api/trash/restore` 增加可选 `target_dir`：还原到指定目录（空串为顶层，仅目录可用），目标同名 409、路径遍历拒绝；还原到新路径时调用 `_history_repath` 把文档或整目录的版本历史一并迁移。
  - 前端历史面板增加「源码 / 差异」切换、基准版本下拉（当前内容或任意版本）、行级增删高亮与统计；编辑时若基准是「当前内容」会实时重算差异。回收站每项新增「还原到…」目录选择对话框，复用 `allDirs` 列表。
- **输出**：`main.py` 差异与定向还原能力、前端面板、四套验证脚本扩充。未引入新第三方库。

## 阶段交付契约

1. **接口先行**：必须先完成阶段一，确保能够通过 API 正确读写本地硬盘上的 MD 文件后，再进行界面的开发。
2. **安全第一**：后端在处理 `category` 和 `filename` 参数时，必须过滤 `..` 等路径跳转字符，防止读取或覆盖系统文件。
3. **无缝热更新与渲染**：前端保存操作为无刷新异步提交，更新成功后需同步刷新视图中的 Markdown 渲染效果。

## 交付记录

### 阶段一 · 后端（`stage-1-backend`，提交 `1446cbd`）
- `main.py`：四个 API、目录自动创建、UTF-8 原子写、中文名、路径遍历与符号链接防御；`tests/smoke_test.py` 初版 25/25。

### 阶段二 · 前端（`stage-2-frontend`，提交 `7f5b8af`）
- Vue3 静态页、递归树、双栏编辑、无刷新保存；渲染依赖本地化；新增 `Doc/SETUP.md`（`2dab7e8`）。

### 阶段三 · 渲染增强（`stage-3-render-enhancement`，提交 `c8f3e31`）
- KaTeX 0.16.22 本地化、`web/math.js` 公式扩展、文档深链接、无头 Chrome 验证。

### 阶段四 · 目录管理（`stage-4-dir-management`，提交 `da0bbf6`）
- 清理 `Doc/NEW_CHAT_PROMPT.md` 残留；`POST /api/dirs/{path}`；目录选中与分类新建；目录深链接。

### 阶段五 · 卡片与重命名（`stage-5-cards-rename`，提交 `76cb17c`）
- `PATCH /api/rename`、`PUT /api/descriptions/{path}`、树节点 `description`；顶层卡片视图、右键菜单、目录说明；新增 `tests/stage5_smoke_test.py`。

### 阶段六 · 纯卡片导航（`stage-6-card-only`，提交 `a51d5cf`）
- 移除侧栏树及全部相关代码/样式；卡片承担导航，新增返回入口。后端零改动。

### 阶段七 · 目录详情页（`stage-7-dir-page`，提交 `94efd80`）
- 双击卡片进入独立目录页，卡片不再平铺子目录与文档；面包屑、目录说明、文件夹/文档分区；后端零改动。

### 阶段八 · 内容操作（`stage-8-content-ops`）
- 后端 `DELETE /api/dirs/{path}`（仅空目录、非空 409、清理隐藏占位文件）；前端右键菜单扩展与目录页快捷新建/删除入口。
- 四套验证全绿：`tests/smoke_test.py` **40/40**、`tests/frontend_smoke_test.py` **39/39**、`tests/browser_smoke_test.py` **23/23**、`tests/stage5_smoke_test.py` **37/37**。

### 阶段九 · 内容整理（`stage-9-content-organize`，提交 `2e6fb24`）
- 后端 `PATCH /api/move` 与 `DELETE /api/dirs/{path}?recursive=true&confirm=...`；前端移动到对话框、原生拖放整理、递归删除二次确认与路径自动同步。
- 四套验证全绿：`tests/smoke_test.py` **65/65**、`tests/frontend_smoke_test.py` **47/47**、`tests/browser_smoke_test.py` **27/27**、`tests/stage5_smoke_test.py` **52/52**。

### 阶段十 · 回收站（`stage-10-recycle-bin`，提交 `ee290e9`）
- 删除改为移入 `data/.trash/`，`GET /api/trash` / `POST /api/trash/restore` / `DELETE /api/trash[/{id}]` 四个接口；顶栏回收站面板支持还原、彻底删除与清空；跨盘移动自动回退。
- 四套验证全绿：`tests/smoke_test.py` **87/87**、`tests/frontend_smoke_test.py` **58/58**、`tests/browser_smoke_test.py` **29/29**、`tests/stage5_smoke_test.py` **60/60**。

### 阶段十一 · 版本历史（`stage-11-version-history`，提交 `3038db1`）
- 保存自动快照、版本列表/预览/还原/清空、重命名与移动时迁移历史；`data/.history/` 隐藏目录不入库。
- 四套验证全绿：`tests/smoke_test.py` **110/110**、`tests/frontend_smoke_test.py` **65/65**、`tests/browser_smoke_test.py` **31/31**、`tests/stage5_smoke_test.py` **66/66**。

### 阶段十二 · 差异与定向还原（`stage-12-diff-restore`）
- `GET /api/diff` 行级差异 + 历史面板差异视图；回收站还原到指定目录并迁移历史；FastAPI 版本 1.6.0。
- 四套验证全绿：`tests/smoke_test.py` **135/135**、`tests/frontend_smoke_test.py` **74/74**、`tests/browser_smoke_test.py` **33/33**、`tests/stage5_smoke_test.py` **74/74**。

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
- 重命名只改名称、移动只改位置；移动拒绝循环、同名冲突、文档移到顶层与符号链接；目录删除支持「仅空目录」与「带名称确认的整目录删除」两种模式。
- 删除先进回收站，可还原；**仅「彻底删除」与「清空回收站」不可恢复**。递归删除不跟随符号链接、单次上限 2000 项，回收站上限 500 条；还原只能回原位置，冲突返回 409。
- 版本历史按文档路径归档，重命名 / 移动 / 从回收站定向还原都会迁移；整目录递归删除后若不走回收站还原，其下文档的旧历史仅保留旧路径记录。差异为 `difflib` 逐行对比，单侧上限 3000 行；每篇最多 50 版，全局 500 篇 / 50 MB。
- 界面无树形侧栏：一级卡片只作入口，层级浏览靠双击进入目录页，返回用顶栏「← 返回」或面包屑。
- 浏览器验证依赖系统安装 Chrome / Edge（不下载浏览器）；未安装时对应脚本跳过或失败，其余脚本不受影响。
- 未涉及多用户、权限、移动端适配与文档版本历史——按业务定义，同名覆盖即版本更新。
