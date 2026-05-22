# 任务 003 — 记忆后端 + `MemoryTool`

> 委派给 worktree Claude。动手前先读 `CLAUDE.md` 与 `docs/integration_contract_zh.md`。

## 目标

实现核心功能 #6「持久化个人偏好记忆」：

- **记忆后端** —— 跨会话持久化的偏好存储。
- **`MemoryTool`** —— `Tool` 子类，让 agent 能读写记忆。

## 背景

`Tool` 抽象基类在 `src/tools/base.py`，参考子类见 `src/tools/weather.py`。本任务的记忆是**用户偏好**（如「我住在燕园」「我每天 8 点上课」「提醒用中文」），不是对话历史 —— 对话历史由 `Conversation` 管。

## 交付物

- 新建 `src/rag/memory.py`（或 `src/core/memory.py`，自行选最合理位置）—— 记忆后端：增 / 删 / 改 / 查偏好条目，持久化到本地文件。
- 新建 `src/tools/memory.py` —— `MemoryTool(Tool)`。
- 修改 `src/tools/__init__.py` —— 导出 `MemoryTool`。
- 修改 `src/core/bootstrap.py` —— 在 `_build_tools()` 注册 `MemoryTool`。记忆是纯本地操作，离线安全 —— **在线和离线分支都注册**（放在 `ClockTool` 那一段，不要放进 `if not offline:`）。
- 若新增数据文件目录（如 `data/`），把它加进 `.gitignore`。

## 实现要求

- 持久化用 SQLite 或 JSON 均可；路径放在仓库内一个 gitignored 目录（如 `data/memory.json`）。条目建议结构化：key、value、写入时间。
- `MemoryTool` 用一个 `action` 参数分发 `set` / `get` / `list` / `delete`，`parameters_schema` 明确描述每种 action 的参数；`invoke()` 返回 `ToolResult`。
- 后端与工具分离：后端类不依赖 `Tool`，可被工作流 / 仪表盘直接复用。
- subclass + register 模式；模块导入零副作用。线程安全：`invoke()` 不共享可变状态（集成契约 §5 要求 Tool 线程安全）。
- 「记忆偏好融入响应」是第 3 周的事，本任务只做后端 + 工具。

## 依赖

独立任务。

## 验收

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` 无报错。
- [ ] `ruff check src` 通过。
- [ ] 写入一条偏好 → 新建后端实例 → 能读回（验证持久化）。
- [ ] 直接构造 `MemoryTool`，`set` / `get` / `list` / `delete` 各 `invoke()` 一次均返回预期结果。
- [ ] `python -m src.cli --offline` 启动后，`MemoryTool` 出现在工具列表里。

## 提交与边界

- 用 Conventional Commits 提交到**本 worktree 分支**。
- **不要** push、**不要** merge 回 main、**不要**开 PR —— 整合由 captain 完成（见 `000_delegation_guide.md`）。
- **不要**勾选 `docs/roadmap_zh.md`。
- 收尾前确保所有改动已提交。
