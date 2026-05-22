# 任务 004 — `ReminderTool`

> 委派给 worktree Claude。动手前先读 `CLAUDE.md` 与 `docs/integration_contract_zh.md`。

## 目标

实现 `ReminderTool` —— 让 agent 能创建、列出、删除提醒事项（如「明天 10 点交作业」「周五前看讲座」）。属核心功能 #3 工具集的一员。

## 背景

`Tool` 抽象基类在 `src/tools/base.py`，参考子类见 `src/tools/weather.py`（网络型）与 `src/tools/clock.py`（无参型）。`ToolResult` 字段为 `success / data / error`。

## 交付物

- 新建 `src/tools/reminder.py` —— `ReminderTool(Tool)`，以及背后的提醒持久化存储（可在同文件内放一个小后端类）。
- 修改 `src/tools/__init__.py` —— 导出 `ReminderTool`。
- 修改 `src/core/bootstrap.py` —— 在 `_build_tools()` 注册 `ReminderTool`。提醒是纯本地操作，离线安全 —— **在线和离线分支都注册**（与 `ClockTool` 同段，不要放进 `if not offline:`）。
- 若新增数据文件目录（如 `data/`），把它加进 `.gitignore`。

## 实现要求

- 提醒条目至少含：文本、触发时间（ISO-8601）、创建时间、完成 / 未完成状态。持久化到仓库内一个 gitignored 路径（如 `data/reminders.json`）。
- `ReminderTool` 用 `action` 参数分发 `add` / `list` / `done` / `delete`，`parameters_schema` 明确每种 action 的参数；时间参数收 ISO-8601 字符串。`invoke()` 返回 `ToolResult`。
- v1 不要求后台定时弹通知 —— 只做存储 + 查询；「到点提醒」的触达是后续议题。`list` 应支持「只看未来的 / 未完成的」。
- subclass + register 模式；模块导入零副作用；`invoke()` 线程安全（集成契约 §5）。
- 注意与任务 003（记忆）职责区分：记忆存**长期偏好**，提醒存**带时间的待办**。两者独立，各自持久化。

## 依赖

独立任务。

## 验收

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` 无报错。
- [ ] `ruff check src` 通过。
- [ ] `add` 一条提醒 → 新建工具实例 → `list` 能读回（验证持久化）。
- [ ] `add` / `list` / `done` / `delete` 各 `invoke()` 一次均返回预期结果。
- [ ] `python -m src.cli --offline` 启动后，`ReminderTool` 出现在工具列表里。

## 提交与边界

- 用 Conventional Commits 提交到**本 worktree 分支**。
- **不要** push、**不要** merge 回 main、**不要**开 PR —— 整合由 captain 完成（见 `000_delegation_guide.md`）。
- **不要**勾选 `docs/roadmap_zh.md`。
- 收尾前确保所有改动已提交。
