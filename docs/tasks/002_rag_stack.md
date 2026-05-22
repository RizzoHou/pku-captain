# 任务 002 — RAG 栈：BGE 嵌入器 + `KnowledgeBase` + `KnowledgeSearchTool`

> 委派给 worktree Claude。动手前先读 `CLAUDE.md` 与 `docs/integration_contract_zh.md`。

## 目标

实现知识库检索的完整一条链，对外暴露为一个可被 agent 调用的工具：

1. **BGE 嵌入器** —— 用 `BAAI/bge-large-zh-v1.5` 把中文文本编码成向量。
2. **`KnowledgeBase`** —— SQLite 存 chunk + 向量，numpy 做余弦相似度检索。
3. **`KnowledgeSearchTool`** —— `Tool` 子类，把检索能力暴露给 LLM。

这三件由你一个人按上述顺序串行完成；对外是一个独立任务。

## 背景

`Tool` 抽象基类在 `src/tools/base.py`，参考子类见 `src/tools/weather.py`。`Source` / `Chunk` 在 `src/rag/source.py`，离线参考源 `StaticSource` 在 `src/rag/static.py`。技术栈已定：SQLite + numpy 存向量、BGE-large-zh 嵌入。

## 交付物

- 新建 `src/rag/embedder.py` —— BGE 嵌入器（建议一个小类，`encode(texts) -> np.ndarray`）。
- 新建 `src/rag/knowledge_base.py` —— `KnowledgeBase`：建表、`index(chunks)`、`search(query, top_k) -> list[结果]`。
- 新建 `src/tools/knowledge_search.py` —— `KnowledgeSearchTool(Tool)`。
- 修改 `src/rag/__init__.py`、`src/tools/__init__.py` —— 导出新符号。
- 修改 `src/core/bootstrap.py` —— 在 `_build_tools()` 的 `if not offline:` 分支注册 `KnowledgeSearchTool`（嵌入模型加载慢，离线 GUI 开发不应触发，故仅在线注册）。
- 修改 `pyproject.toml` —— 加嵌入所需依赖（如 `sentence-transformers` 或 `transformers`+`torch`），放进 `dependencies`。

## 实现要求

- 嵌入模型**懒加载**：首次 `encode()` 时再加载权重，不要在模块导入或对象构造时加载（首次加载耗时 / 占内存是已登记风险）。
- `KnowledgeBase` 用 SQLite 持久化 chunk 文本、metadata、向量（向量可存 BLOB）；检索时载入 numpy 做余弦相似度。SHA-256 增量差分是最终提交窗口的事，本任务做到「能 index、能 search」即可。
- `KnowledgeSearchTool`：`parameters_schema` 收 `query`（必填）与可选 `top_k`；`invoke()` 返回 `ToolResult`，`data` 为命中 chunk 列表（含文本、来源、相似度分数）。
- subclass + register 模式；模块导入零副作用。
- **用 `StaticSource` 自测，不要依赖任务 001。** bootstrap 里 `KnowledgeSearchTool` 背后的 `KnowledgeBase` 先用一份内置示例 chunk（或 `StaticSource`）建库即可；captain 会在整合期把 `DeanSource` / `CalendarSource` 接进来。

## 依赖

独立任务。

## 验收

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` 无报错。
- [ ] `ruff check src` 通过。
- [ ] 能用一批示例 `Chunk` 建库，`KnowledgeBase.search()` 对相关 query 返回合理排序的结果。
- [ ] 直接构造 `KnowledgeSearchTool` 并 `invoke({"query": ...})` 返回 `success=True`。
- [ ] `python -m src.cli --offline` 仍能启动（离线下该工具不注册，属预期）。

## 提交与边界

- 用 Conventional Commits 提交到**本 worktree 分支**。
- **不要** push、**不要** merge 回 main、**不要**开 PR —— 整合由 captain 完成（见 `000_delegation_guide.md`）。
- **不要**勾选 `docs/roadmap_zh.md`。
- 收尾前确保所有改动已提交。
