# 任务 006 — `PKU3bAnnouncementsTool`

> 委派给 worktree Claude。动手前先读 `CLAUDE.md`（尤其 `pku3b` 那几段）与 `docs/integration_contract_zh.md`。

## 目标

实现 `PKU3bAnnouncementsTool` —— 通过 `pku3b` CLI 拉取 PKU 教学网（Blackboard）课程通知 / 公告。属核心功能 #3 工具集的一员，也是 `MorningBriefingWorkflow`（任务 007）的数据来源之一。

## 背景

`pku3b` 子进程封装已存在于 `src/tools/pku3b.py`（`run_pku3b()`、`strip_ansi()`、`Pku3bNotFoundError` / `Pku3bTimeoutError`，**不是** Tool 子类）。**直接复用它，不要重写子进程逻辑。** 同目录的 `src/tools/pku3b_assignments.py`（`PKU3bAssignmentsTool`）是最贴近的参考实现 —— 它调用 `pku3b assignment list --format json` 并 `json.loads` 结构化输出。本任务是它的「公告」版。

`pku3b` 已装在 `~/.local/bin/pku3b`（在 PATH 上，worktree 里可直接用），是我们 fork 的 v0.13.0+。

## 交付物

- 新建 `src/tools/pku3b_announcements.py` —— `PKU3bAnnouncementsTool(Tool)`。
- 修改 `src/tools/__init__.py` —— 导出 `PKU3bAnnouncementsTool`。
- 修改 `src/core/bootstrap.py` —— 在 `_build_tools()` 的 `if not offline:` 分支注册 `PKU3bAnnouncementsTool`（走子进程，离线子集不含它）。

## 实现要求

- **先运行 `pku3b --help`（及相关子命令的 `--help`）确认公告 / 通知子命令的确切名称与参数。** 优先使用 `--format json` 结构化输出 + `json.loads`；若该子命令尚不支持 JSON，则用文本输出 + `strip_ansi()` 解析，并在本文件「实现备注」处写明限制（captain 决定是否扩展 fork）。
- 错误处理对齐 `PKU3bAssignmentsTool`：捕获 `Pku3bNotFoundError` / `Pku3bTimeoutError`，非零返回码转成 `ToolResult(success=False, error=...)`，JSON 解析失败给出可操作的报错。
- 提示一条已知坑（`CLAUDE.md` 有记）：`pku3b` 输出重定向到普通文件会失败，但管道正常 —— `subprocess.run(capture_output=True)` 用的是管道，`run_pku3b()` 不受影响，照常用即可。
- `parameters_schema` 描述清楚（可加按课程过滤等可选参数）；`data` 为结构化通知列表。
- subclass + register 模式；模块导入零副作用；`invoke()` 线程安全（集成契约 §5）。

## 依赖

独立任务。任务 007 会编排本工具，但本任务不依赖 007。

## 验收

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` 无报错。
- [ ] `ruff check src` 通过。
- [ ] 直接构造 `PKU3bAnnouncementsTool` 并 `invoke({})`，返回结构化通知（首次可能需要 `pku3b` 登录态 —— 见 `docs/setup_zh.md`）。
- [ ] `pku3b` 不存在 / 超时 / 返回非零时，`invoke()` 返回 `ToolResult(success=False, ...)`，不抛异常。
- [ ] `python -m src.cli --offline` 仍能启动（离线下该工具不注册，属预期）。

## 提交与边界

- 用 Conventional Commits 提交到**本 worktree 分支**。
- **不要** push、**不要** merge 回 main、**不要**开 PR —— 整合由 captain 完成（见 `000_delegation_guide.md`）。
- **不要**勾选 `docs/roadmap_zh.md`。
- 收尾前确保所有改动已提交。
