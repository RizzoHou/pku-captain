# 任务 005 — `LectureTool`

> 委派给 worktree Claude。动手前先读 `CLAUDE.md` 与 `docs/integration_contract_zh.md`。

## 目标

实现 `LectureTool` —— 让 agent 能查询北大近期讲座信息（标题、时间、地点、主讲人）。属核心功能 #3 工具集的一员，也是 `MorningBriefingWorkflow`（任务 007）的数据来源之一。

## 背景

`Tool` 抽象基类在 `src/tools/base.py`，网络型参考子类见 `src/tools/weather.py`（`requests`、超时、`requests.RequestException` 兜底成 `ToolResult(success=False, ...)`）。

## 交付物

- 新建 `src/tools/lecture.py` —— `LectureTool(Tool)`。
- 修改 `src/tools/__init__.py` —— 导出 `LectureTool`。
- 修改 `src/core/bootstrap.py` —— 在 `_build_tools()` 的 `if not offline:` 分支注册 `LectureTool`（联网工具，离线子集不含它）。

## 实现要求

- `parameters_schema` 可收可选过滤参数（如 `limit`、日期范围 / 关键词）；`invoke()` 返回 `ToolResult`，`data` 为讲座列表，每条含标题、时间、地点、主讲人、链接。
- 网络错误、超时、空结果都要兜底成 `ToolResult(success=False, error=...)` 或 `success=True` + 空列表，不要让异常冒泡（参考 `WeatherTool` 的 `try/except`）。
- 数据源自行调研北大讲座信息的公开来源。**若找不到稳定可用的公开接口**：先把工具实现为读取仓库内一份固定 JSON（保留 `Tool` 接口与 `parameters_schema` 不变），并在本文件「实现备注」处写明所用数据源与限制，captain 后续接真实源。功能完整性优先于数据真实性。
- subclass + register 模式；模块导入零副作用；`invoke()` 线程安全（集成契约 §5）。

## 依赖

独立任务。任务 007 会编排本工具，但本任务不依赖 007。

## 验收

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` 无报错。
- [ ] `ruff check src` 通过。
- [ ] 直接构造 `LectureTool` 并 `invoke({})`，返回结构化讲座列表（或按上面的备选方案）。
- [ ] 断网 / 数据源不可用时，`invoke()` 返回 `ToolResult`（不抛异常）。
- [ ] `python -m src.cli --offline` 仍能启动（离线下该工具不注册，属预期）。

## 提交与边界

- 用 Conventional Commits 提交到**本 worktree 分支**。
- **不要** push、**不要** merge 回 main、**不要**开 PR —— 整合由 captain 完成（见 `000_delegation_guide.md`）。
- **不要**勾选 `docs/roadmap_zh.md`。
- 收尾前确保所有改动已提交。
