# 任务 008 — `KimiProvider`（视觉 LLM，**可选**）

> 委派给 worktree Claude。动手前先读 `CLAUDE.md` 与 `docs/integration_contract_zh.md`。
>
> **可选任务**：`KimiProvider` 是 `docs/roadmap_zh.md` 削减顺序的第 1 位。仅在 A 波其余任务都已顺利推进、且 06-01 里程碑有余量时才委派；否则直接跳过，DeepSeek 单独足以支撑演示。

## 目标

实现 `KimiProvider` —— Kimi 的 `LLMProvider` 子类，作为视觉 LLM 通道（按已定技术栈：DeepSeek 管 chat、Kimi 管 vision）。

## 背景

`LLMProvider` 抽象基类在 `src/llm/base.py`：实现 `chat(messages, tools=None) -> ChatResponse`。最贴近的参考实现是 `src/llm/deepseek.py`（`DeepSeekProvider`），它演示了 API key 注入、消息格式转换、工具调用透传。注意基类的 `ChatMessage` / `ChatResponse` 带 `reasoning_content` 字段 —— 那是 DeepSeek 思考模式专用，Kimi 不需要可留 `None`。

## 交付物

- 新建 `src/llm/kimi.py` —— `KimiProvider(LLMProvider)`。
- 修改 `src/llm/__init__.py` —— 导出 `KimiProvider`。
- **不需要**改 `bootstrap.py`：目前没有视觉调用入口，`build_agent()` 仍用 DeepSeek。本任务只交付可独立实例化、可注册进 `LLMProviderRegistry` 的子类。

## 实现要求

- 复刻 `DeepSeekProvider` 的结构：构造收 `api_key`，`chat()` 把 `list[ChatMessage]` 转成 Kimi API 请求、解析回 `ChatResponse`。
- 支持图像输入 —— 这是 Kimi 在本项目里的存在理由。`chat()` 的消息若含图像内容，按 Kimi 多模态格式发送。
- API 异常包成一个清晰的异常类型（参考 `DeepSeekAPIError`），不要静默吞掉。
- API key：约定放 `secrets/kimi_key.txt`（`secrets/` 已 gitignored）。worktree 里没有 `secrets/`，**联网自测做不了，属预期** —— 用离线校验代替（见验收）。
- subclass 模式；模块导入零副作用。
- 在本文件「实现备注」处记录 Kimi 的 base URL、模型名、多模态消息格式，方便 captain 整合期接视觉入口。

## 依赖

独立任务。

## 验收

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` 无报错。
- [ ] `ruff check src` 通过。
- [ ] `from src.llm import KimiProvider` 成功；能用假 key 构造实例（构造不应触发网络）。
- [ ] `KimiProvider` 能 `register()` 进 `LLMProviderRegistry`（`src/llm/base.py`）。
- [ ] `python -m src.cli --offline` 仍能启动。

## 提交与边界

- 用 Conventional Commits 提交到**本 worktree 分支**。
- **不要** push、**不要** merge 回 main、**不要**开 PR —— 整合由 captain 完成（见 `000_delegation_guide.md`）。
- **不要**勾选 `docs/roadmap_zh.md`。
- 收尾前确保所有改动已提交。
