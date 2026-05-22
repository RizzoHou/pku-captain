# 任务 007 — `MorningBriefingWorkflow`

> 委派给 worktree Claude。动手前先读 `CLAUDE.md` 与 `docs/integration_contract_zh.md`。
>
> **B 波任务**：本任务编排任务 005（`LectureTool`）、006（`PKU3bAnnouncementsTool`）产出的工具。委派本任务前，005、006（建议加 001）应已合并进 `main` —— 否则你的 worktree 里这些工具不存在，无法端到端自测。

## 目标

完整实现 `MorningBriefingWorkflow` —— 把多个工具的结果合成一份「晨间简报」：今日 DDL、课程通知、近期讲座、天气。属核心功能 #4 多步骤工作流。

## 背景

`Workflow` 抽象基类在 `src/workflows/base.py`：构造时收一个 `ToolRegistry`（存为 `self.tools`），实现 `run()` 返回 `WorkflowResult`（`success / summary / details / error`）。参考子类 `src/workflows/hello.py`（`HelloWorkflow`）演示了最简的「取一个工具 → 包成结果」。本任务把它扩展成多工具编排。

可用工具（按 `name` 从 `self.tools` 取）：

- `pku3b_assignments` —— 作业 / DDL（已存在）。
- `weather` —— 天气（已存在）。
- `pku3b_announcements` —— 课程通知（任务 006）。
- `lecture` —— 讲座（任务 005）。
- `clock` —— 当前时间（已存在）。

## 交付物

- 新建 `src/workflows/morning_briefing.py` —— `MorningBriefingWorkflow(Workflow)`。
- 修改 `src/workflows/__init__.py` —— 导出 `MorningBriefingWorkflow`。
- 修改 `src/core/bootstrap.py` —— 在 `_build_workflows()` 注册 `MorningBriefingWorkflow`。

## 实现要求

- `run()` 依次调用上述工具的 `invoke()`，把结果聚合进 `WorkflowResult`：`summary` 是一段人类可读的中文简报，`details` 按工具名分键存原始结果。
- **优雅降级**：用 `self.tools` 取工具前先判断是否注册（`offline` 模式下 `weather` / `pku3b_*` / `lecture` 都不在）；某个工具缺失或 `invoke()` 返回 `success=False` 时，跳过该板块并在简报里注明，**不要**让整个工作流失败。只有全部数据源都拿不到时才返回 `success=False`。
- `ToolRegistry` 只有 `get(name)`(命中失败会 `KeyError`)、`all()`、`get`。判断是否存在可用 `any(t.name == "lecture" for t in self.tools.all())` 之类的方式。
- subclass + register 模式；模块导入零副作用。
- 「时间感知」可借 `clock` 工具拿当前日期，用于筛「今日」DDL / 「近期」讲座。

## 依赖

依赖任务 005、006 已合并（建议 001 也已合并）。002 / 003 / 004 与本任务无关。

## 验收

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` 无报错。
- [ ] `ruff check src` 通过。
- [ ] 用一个注册了全部工具的 `ToolRegistry` 构造工作流，`run()` 返回 `success=True` 且 `summary` 含各板块。
- [ ] 用一个**只注册了部分工具**的 `ToolRegistry` 构造，`run()` 仍优雅返回，缺失板块有注明、不抛异常。
- [ ] `python -m src.cli --offline` 仍能启动。

## 提交与边界

- 用 Conventional Commits 提交到**本 worktree 分支**。
- **不要** push、**不要** merge 回 main、**不要**开 PR —— 整合由 captain 完成（见 `000_delegation_guide.md`）。
- **不要**勾选 `docs/roadmap_zh.md`。
- 收尾前确保所有改动已提交。
