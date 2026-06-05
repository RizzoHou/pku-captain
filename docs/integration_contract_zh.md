# 后端 / 前端 集成契约

本文件定义后端（`src/core`、`src/llm`、`src/tools`、`src/workflows`、`src/rag`）与 PyQt6 GUI 之间的接口约定。目的是让两条 lane 能并行推进而不互相 block：GUI 只针对本文档约定的公共表面与事件契约编码，后端只要保证不破坏这些契约就可以自由重构内部实现。

本文件的优先级低于 `docs/design_reference_zh.md` 的"核心功能"清单，但高于任何临时口头约定。变更需在 PR 描述中显式标注 "BREAKING: integration contract"。

## 1. 公共 API 表面

GUI 只允许从下列符号导入。其他模块视为内部实现，随时可能改动。

| 子包 | 暴露给 GUI 的符号 | 用途 |
| --- | --- | --- |
| `src.core` | `Agent`, `AgentEvent`, `Conversation` | 启动 / 渲染对话历史 |
| `src.llm` | `ChatMessage`, `ToolCall`, `ChatResponse`, `ChatStreamEvent` | 仅作类型 / 渲染用，不要直接构造 Provider |
| `src.tools` | `ToolRegistry`, `Tool`, `ToolResult` | 仪表盘可直接调用某个 `Tool.invoke()`（见 §5） |
| `src.workflows` | `WorkflowRegistry`, `Workflow`, `WorkflowResult` | 工作流按钮 / 入口 |
| `src.rag` | `SourceRegistry`, `Source`, `Chunk` | 仪表盘信息源 |

**GUI 不应自己拼装 `Agent`**。后端在 `src/core/bootstrap.py` 提供工厂函数 `build_agent`，从 `src.core` 直接导入：

```python
from src.core import build_agent

agent = build_agent()              # 在线：DeepSeek + 完整 Week-1 工具集
agent = build_agent(offline=True)  # 离线：EchoLLMProvider + 仅 ClockTool
```

`offline=True` 时挂 `EchoLLMProvider` + 离线工具子集（当前为 `ClockTool`），便于 GUI 在没有 API Key 时也能跑通。GUI 只调 `build_agent()`，不应感知 `DeepSeekProvider`、`PKU3bAssignmentsTool` 等具体子类的存在 —— 这些会在演示窗口内频繁增删。系统提示由 `bootstrap` 注入，GUI 不需要也不应该自行追加。

`build_agent(enable_knowledge=True)` 是 RAG 检索的**显式开关，默认关闭**：仅当它为 True **且**在线时，才注册 `KnowledgeSearchTool`。关闭时启动不会触发任何嵌入 API 调用。嵌入走 DashScope `text-embedding-v4` 云端 API（不再下载本地模型），所以开启需要 `secrets/api_keys/embedding_key.txt`。GUI 通过 `--rag` 启动标志暴露该开关（`src/__main__.py` → `MainWindow(enable_knowledge=...)`），CLI 同样有 `--rag`。

> **BREAKING: integration contract** —— 旧的 `skip_knowledge`（默认 False、需显式 `=True` 才跳过）已被 `enable_knowledge`（默认 False、需显式 `=True` 才开启）取代，语义反转。GUI 侧 `build_agent(offline=offline, skip_knowledge=True)` 应改为 `build_agent(offline=offline, enable_knowledge=...)`；本仓库内已同步更新。

`Conversation` 对 GUI 是只读的：渲染历史时通过 `for msg in agent.conversation` 或 `agent.conversation.snapshot()` 拿 `ChatMessage` 列表，不要直接调 `add_user / add_assistant / add_tool_result`。所有写入由 `Agent.turn()` 完成（多会话的重置 / 恢复写入也走 `src.core` 的工厂，见下）。

**多会话持久化（新增）**：`src.core` 额外懒加载暴露 `build_session_store()`、`build_session_titler(*, offline)`、`reset_conversation(agent)`、`restore_conversation(agent, raw_messages)`（与 `build_agent` 同一 PEP 562 机制）。GUI 经 `build_session_store()` 拿到 `SessionStore`——每个会话一份 `data/sessions/<id>.json`（完整消息历史 + 标题 + `created_at/updated_at` + `offline`），在每个 turn 结束和窗口关闭时写盘（仅当已有用户消息，避免空会话留下垃圾文件）。`build_session_titler` 用轻量 `deepseek-v4-flash`**非思考模式**（请求体 `{"thinking": {"type": "disabled"}}`，由 `DeepSeekProvider(thinking=False)` 产生）异步生成会话标题；离线或无 key 时回退到启发式标题（首条用户消息截断），**绝不**经 `EchoLLMProvider`。新建 / 切换会话**不**直接写 `Conversation`：`reset_conversation` 重置为系统提示；`restore_conversation` 反序列化存档消息、剥离旧 `system` 后重新注入当前 `_SYSTEM_PROMPT`，加载后由 `ChatPanel.load_history(agent.conversation.snapshot())` 重绘，**不**重新触发 `final` 事件。GUI 入口为对话面板表头的「＋新对话」「历史会话」两个按钮（后者打开 `SessionHistoryDialog` 模态列表），turn 进行中禁用以避免在 worker 线程仍在写 `Conversation` 时换底。

> **BREAKING: integration contract** —— 本次新增上述 `src.core` 多会话符号，并落实 §6 的「持久化 `Conversation`」待定项（加载经 `ChatPanel.load_history` 重绘，不重发 `final`）。`DeepSeekProvider` 新增可选参数 `thinking: bool = True`，默认路径请求体与此前逐字节一致，仅供标题器以 `thinking=False` 走非思考模式。

## 2. 线程模型

`Agent.turn()` 内部包含：HTTP 调用 DeepSeek、子进程调用 `pku3b`、`requests.get` 调用 Open-Meteo。这些都是阻塞 I/O，**绝不能跑在 Qt 主线程上**，否则窗口会冻结数秒至数十秒。

约定：后端提供一个 `QObject` 子类 `AgentWorker`，在自己的 `QThread` 中运行，GUI 通过 Qt 信号 / 槽与之通信。建议放在 `src/ui/agent_worker.py`（GUI lane 拥有，但后端可贡献骨架），形态如下：

```python
class AgentWorker(QObject):
    event = pyqtSignal(object)        # AgentEvent
    finished = pyqtSignal()           # 一个 turn 全部完成（含 final 或 error）
    error = pyqtSignal(str)           # 不可恢复异常（见 §4）

    def __init__(self, agent: Agent) -> None: ...

    @pyqtSlot(str)
    def run_turn(self, user_message: str) -> None:
        try:
            for ev in self.agent.turn(user_message):
                self.event.emit(ev)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()
```

启动模板（GUI 端，仅一次）：

```python
self.thread = QThread(self)
self.worker = AgentWorker(build_agent())
self.worker.moveToThread(self.thread)
self.worker.event.connect(self._on_agent_event)
self.worker.error.connect(self._on_agent_error)
self.worker.finished.connect(self._on_turn_finished)
self.thread.start()
```

发送一个用户消息：用 `QMetaObject.invokeMethod(self.worker, "run_turn", Qt.ConnectionType.QueuedConnection, Q_ARG(str, text))`，**不要**直接调 `self.worker.run_turn(text)`（那会在主线程执行）。

并发约束：

- 同一时刻只允许一个 turn 在跑。GUI 在收到 `finished` 之前应禁用发送按钮。
- 取消：v1 不支持中途取消。后端会在 `max_tool_iterations`（默认 8）触发上限后自然结束。如果 GUI 需要取消按钮，作为 v2 议题。
- 仪表盘的刷新走另一条 worker（见 §5），与 agent worker 互不干扰。

## 3. 事件流契约

`Agent.turn()` 是一个生成器，按序 yield `AgentEvent(kind, payload)`。GUI 应根据 `kind` 分发到不同面板。下表是当前定义，**事件种类只增不删**（新增 kind 必须向后兼容：未识别的 kind GUI 应忽略而非抛错）。

| kind | payload 字段 | 触发时机 | GUI 行为 |
| --- | --- | --- | --- |
| `assistant_delta` | `text: str` | LLM 流式输出每收到一段 token 即触发；同一 turn 内可能 yield 多次 | 把 `text` 追加到当前正在生成的 assistant 气泡（"打字机"效果）；`final` 到达时收尾 |
| `reasoning_delta` | `text: str` | 思考模型（DeepSeek thinking）流式输出每段思维链 token 即触发，出现在同一段回答的 `assistant_delta` 之前 | 追加到该段的"思考过程"窗口（一个定高、自动滚到底的滑动窗口，避免长 CoT 淹没回答）；GUI 默认隐藏，由对话表头的「💭 思考」开关控制。非思考 provider（Echo / `thinking=False`）不会 yield 此事件 |
| `llm_response` | `text: str` | 每次 LLM 回复完成后立即触发，包括携带 tool_calls 的中间回复 | 累计或暂存；最终展示由 `final` 决定 |
| `tool_call` | `id: str`, `name: str`, `arguments: dict` | LLM 请求调用某个工具时 | 在工具调用面板新增一行（"调用中"） |
| `tool_result` | `id: str`, `name: str`, `result: ToolResult` | 工具执行完毕（成功或失败均会触发） | 用 `id` 匹配上面的行，渲染 `result.data` 或 `result.error` |
| `final` | `text: str` | 整个 turn 结束，`text` 是最终对用户可见的回答 | 在对话面板渲染最终消息（若已用 `assistant_delta` 流式渲染，`final` 用于定型） |

注意点：

- 一个 turn 至少 yield 一次 `final`（即便是上限超限也会 yield 一个 `kind="final"` 的兜底事件）。GUI 可以把 `final` 作为"展示最终回答"的唯一信号。
- `llm_response.text` 在中间步骤通常为空（模型只返回 tool_calls）。**不要**把每个 `llm_response` 都贴到对话面板，否则会出现空气泡。建议：仅当 `final` 触发时，用其 `text` 渲染最终回答。
- `tool_result.result` 是 `ToolResult` 数据类。`result.data` 类型由具体工具决定（`PKU3bAssignmentsTool` 返回结构化记录，`WeatherTool` 返回 dict，`ClockTool` 返回字符串）。GUI 可以先用 `repr()` 或 `json.dumps(default=str)` 打底渲染，需要美化时按 `name` 分发到专用渲染器。
- token 级流式由 `LLMProvider.stream_chat()` 提供，默认实现是把 `chat()` 的全文一次性包成一个 `ChatStreamEvent`。`DeepSeekProvider.stream_chat()` 走真正的 SSE。`Agent.turn()` 会优先调用 `stream_chat()`，把每段增量以 `assistant_delta` 事件 yield 给 GUI；若 provider 未返回最终 `response`，会回退到 `chat()`。GUI 在收到 `final` 之前应只用 `assistant_delta` 渲染气泡，避免与 `final` 重复。

## 4. 错误契约

错误分为三类，处理方式不同：

1. **工具失败（可恢复）** —— `Tool.invoke()` 返回 `ToolResult(success=False, error=...)`。Agent 会把错误字符串作为 `tool` 消息回喂给 LLM，让模型自行恢复。GUI 通过 `tool_result` 事件感知，**不需要**特殊处理（不弹窗、不中断 turn）。
2. **LLM / 网络异常（不可恢复）** —— `LLMProvider.chat()` 抛出（如 `DeepSeekAPIError`、`requests.ConnectionError`）。`AgentWorker` 必须捕获并发出 `error(str)` 信号；当前 turn 终止，`finished` 仍会触发。GUI 应在对话面板显示一条系统提示（红色 / 警告样式），**保留**之前已经显示的 `tool_call` / `tool_result` 信息以便用户复盘。
3. **超出工具调用上限** —— 不抛异常，而是 yield 一个 `kind="final"` 的事件，文本为 `"Agent exceeded max tool iterations."`。GUI 当作正常 final 渲染即可，可加一个浅色"达到上限"标签。

`Conversation` 的内部一致性错误（如 `add_tool_result` 找不到匹配的 `tool_call`）属于编程错误，不应在生产中出现 —— 若 worker 捕获到，按第 2 类处理。

## 5. 仪表盘的另一条数据通道

仪表盘 widget **不**走 `Agent`。它直接读：

- `Tool.invoke({})` —— 用于无参数即可出值的工具（如 `WeatherTool`、`ClockTool`、未来的 `PKU3bAssignmentsTool`）。仪表盘 widget 持有 `ToolRegistry`，按 `name` 取用。
- `Source.fetch()` —— Week 2 起的 RAG 信息源（`DeanSource`、`CalendarSource`）。仪表盘 widget 持有 `SourceRegistry`。

同样的阻塞 I/O 问题：`Tool.invoke` 与 `Source.fetch` 都可能耗时数秒。Week 1 demo 可以接受启动时一次性同步拉取（loading 几秒）；Week 2 起每个仪表盘 widget 应有自己的 `QThread + worker` 或 `QThreadPool` runnable，由 `QTimer` 按各自节奏触发刷新。

GUI lane 与后端 lane 的接缝：后端保证 `Tool` / `Source` 的 `invoke` / `fetch` 是线程安全的（不共享可变状态），GUI 可以放心在 worker 里调用。

**仪表盘的弹窗也遵守 §1 的工具获取规则**：树洞 / P-Lib / 公告 / 讲座 / 记忆 / 知识库等模态弹窗**不**自行构造 `Tool` 子类，而是从 `DashboardPanel` 注入的同一个 `ToolRegistry` 里按 `name` 取（`tools.find(name)` / `name in tools`）。在线专属入口以“工具是否注册”为唯一的在线判据：离线（`build_agent(offline=True)`）时这些工具不在 registry 中，对应按钮禁用、弹窗入口直接拒绝，所以 GUI 永远不会在离线模式触达网络 / 子进程工具。**唯一例外**是 `TreeholeAuthService`（登录 / 短信验证，不是 `Tool`），它由 `treehole_updates` 是否注册间接 gate。弹窗里任何阻塞调用（P-Lib 搜索 / 下载、公告详情子进程、知识库嵌入 API、树洞登录）都通过 `src/ui/tool_call_worker.py` 的 `run_async(fn, on_done, on_error)` 丢到 `QThreadPool`，回调在 GUI 线程触发——模态 `exec()` 期间事件循环仍在转，所以异步结果照常送达，窗口不冻结。

**窗口布局（2 栏）**：主窗口当前为 `dashboard | chat`（PR #4 起）。工具调用过程不再有独立的右侧面板，而是内联渲染在对话流中（`ChatPanel.add_tool_call` / `update_tool_result` + `InlineToolCall`），复用 `tool_trace_panel.py` 的 `_format_tool_result` / `_to_json` 格式化器。`ToolTracePanel` 类已不再挂载，保留备查。

## 6. 待定 / 后续

下列条目目前**未**进入契约，需要时再单独 PR：

- **turn 取消**：v1 不支持。如果加，需要在 `Agent.turn()` 中检查取消标记，并在 worker 层提供 `cancel()` 槽。
- **多 Agent 并发**：当前一个窗口一个 `Agent`。多 Agent（例如同时跑工作流 + 对话）需要重新设计 worker / signal 路由。
- ~~**持久化 `Conversation`**~~（**已实现**，见 §1「多会话持久化」）：落盘到 `data/sessions/<id>.json`，GUI 经「历史会话」弹窗加载；加载后通过 `ChatPanel.load_history` 重绘，**不**重新触发 `final` 事件。已知 v1 限制：`tool` 消息只存了 `str(result.data)`，重绘的工具行展示字符串化结果而非结构化渲染。
- **Workflow 事件流**：`Workflow.run()` 当前一次性返回 `WorkflowResult`，没有事件流。如果 GUI 要展示工作流的中间步骤，需要参照 `Agent.turn()` 改成生成器并扩展 `AgentEvent` 或新增 `WorkflowEvent`。

---

最后：本文件由 captain 维护。后端或 GUI 任何一方在自己 lane 内实现不一致或想改契约，先发 issue / 在 PR 描述里写 `BREAKING: integration contract` 触发 captain 评审，不要"代码先行，文档后补"。
