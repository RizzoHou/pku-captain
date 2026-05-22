# 任务 001 — `DeanSource` + `CalendarSource`（Source 子类）

> 委派给 worktree Claude。动手前先读 `CLAUDE.md` 与 `docs/integration_contract_zh.md` §5。

## 目标

实现两个 `Source` 子类，让 RAG 知识库与仪表盘能从 PKU 官方信息源取数据：

- `DeanSource` —— 北大教务部通知 / 公告。
- `CalendarSource` —— 北大校历（学期周次、假期、考试周等）。

## 背景

`Source` 抽象基类与 `SourceRegistry` 已存在于 `src/rag/source.py`，离线参考子类 `StaticSource` 在 `src/rag/static.py`。`Source.fetch()` 返回 `Iterable[Chunk]`，`Chunk` 字段为 `source_name / identifier / text / metadata`。RAG 管线负责下游的哈希、嵌入、存储 —— Source 只管抓取并切成 chunk。

## 交付物

- 新建 `src/rag/dean.py` —— `DeanSource(Source)`。
- 新建 `src/rag/calendar.py` —— `CalendarSource(Source)`。
- 修改 `src/rag/__init__.py` —— 导出 `DeanSource`、`CalendarSource`。
- 修改 `src/core/bootstrap.py` —— 新增工厂函数 `build_source_registry() -> SourceRegistry`，在其中 `register()` 这两个 Source。仪表盘（GUI lane）将通过它取 `SourceRegistry`（见集成契约 §5）。

## 实现要求

- 继承 `Source`，设 `name`、`refresh_interval`（秒；教务通知建议 ~1h，校历建议 ~24h），实现 `fetch()`。
- `fetch()` 把抓取内容切成语义合理的 `Chunk`：`identifier` 在源内稳定且唯一（便于下游 SHA 差分），`metadata` 放标题、URL、发布日期等。
- 网络失败应抛异常或返回空，不要静默吞掉成 `Chunk`。
- subclass + register 模式；模块导入零副作用 —— 注册只在 `build_source_registry()` 调用点发生。
- 若某个源没有稳定的公开数据接口，可先实现为读取仓库内固定数据文件（保留 `fetch()` 形态不变），并在本文件「实现备注」处记录，captain 后续接真实源。

## 依赖

独立任务。不要依赖任务 002 —— 002 用 `StaticSource` 自测。

## 验收

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` 无报错。
- [ ] `ruff check src` 通过。
- [ ] 能构造 `DeanSource()` / `CalendarSource()` 并调用 `fetch()`，返回非空 `Chunk` 序列（或在数据源不可用时按上面的备选方案）。
- [ ] `build_source_registry().all()` 返回这两个 Source。
- [ ] `python -m src.cli --offline` 仍能启动。

## 提交与边界

- 用 Conventional Commits 提交到**本 worktree 分支**。
- **不要** push、**不要** merge 回 main、**不要**开 PR —— 整合由 captain 完成（见 `000_delegation_guide.md`）。
- **不要**勾选 `docs/roadmap_zh.md`。
- 收尾前确保所有改动已提交，避免 worktree 清理时丢失。
