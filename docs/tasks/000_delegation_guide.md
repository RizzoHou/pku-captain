# Week 2 后端任务委派说明

本目录下的 `001`–`008` 是可独立交付的任务说明，每个用于委派给一个 **worktree Claude**。本文件说明如何委派与整合。读者是 captain（`RizzoHou`），不是 worktree Claude。

## 任务清单与依赖

| 编号 | 任务 | 依赖 | 可选 |
| --- | --- | --- | --- |
| 001 | `DeanSource` + `CalendarSource`（Source 子类） | 无 | |
| 002 | RAG 栈：BGE 嵌入器 + `KnowledgeBase` + `KnowledgeSearchTool` | 无 | |
| 003 | 记忆后端 + `MemoryTool` | 无 | |
| 004 | `ReminderTool` | 无 | |
| 005 | `LectureTool` | 无 | |
| 006 | `PKU3bAnnouncementsTool` | 无 | |
| 007 | `MorningBriefingWorkflow` | **005、006**（编排其工具）；建议 001 | |
| 008 | `KimiProvider`（视觉 LLM） | 无 | 可选，削减顺序第 1 位 |

**两波推进**：

- **A 波（001–006、008）**：彼此无依赖，可全部并行委派。
- **B 波（007）**：编排 005/006 的工具，应在 A 波合并进 `main` 后再委派 —— 否则它写出的工作流引用尚不存在的工具，无法端到端自测。

002 内部是 嵌入器 → KnowledgeBase → KnowledgeSearchTool 的顺序链，但由**同一个** worktree Claude 串行完成，对外仍是一个独立任务，没有跨 worktree 依赖。

## 委派方式

并行或顺序都可以。**关键区别只在于 merge 必须顺序进行**（见下一节），worktree 本身并行跑没有问题。

每个任务开一个 worktree，并**显式命名**。在仓库根目录执行：

```bash
cd /home/ubuntu/projects/pku-captain
claude --worktree worktree-004-reminder "请阅读并完整实现 docs/tasks/004_reminder_tool.md，按文件末尾的验收清单逐项自检，完成后用 Conventional Commits 提交到当前 worktree 分支。不要 push、不要 merge。"
```

把 `worktree-004-reminder` 与 `004_reminder_tool.md` 换成目标任务即可。每个任务一条命令、一个终端。

- worktree 名建议统一为 `worktree-NNN-<slug>`，分支名随之可预测，便于后续 merge。
- **必须给 `--worktree` 一个名字**：`--worktree` 的名字是可选参数，若写成 `claude --worktree "请阅读…"`，那段 prompt 会被当成 worktree 名。名字与 prompt 要分开两个参数。
- 名字以 `worktree-` 开头时，worktree Claude 能确认自己「在 worktree 中」，从而遵守「只提交、不 push」规则。

- **并行**：在多个终端同时跑多条上述命令（A 波 7 个任务可一次全开）。
- **顺序**：一次跑一条，等该 Claude 跑完并 merge 后再开下一个。

说明：

- 任务说明文件已在 `main` 上，每个 worktree 都能直接读到 —— 无需手动拷贝。
- 每个 worktree Claude 会自建 `.venv` 并安装依赖（`.venv/`、`secrets/` 是 gitignored，不会带进 worktree）。因此 worktree 里**只能跑离线校验**（`python -m src.cli --offline`、`py_compile`、`ruff`）；在线 agent 需要 DeepSeek key，跑不了，任务说明已据此设计验收项。
- **先试跑一个再铺开**：第一次委派，建议先单独跑任务 004（最小、完全独立、不联网），确认 worktree Claude 能读到任务文件、按验收项自检、并停在「只提交本分支、不 push」的边界上；确认无误后再并行铺开其余任务。

## 整合（merge）

worktree Claude 只提交到自己的分支，**不 push、不 merge**（这是 worktree 规则）。整合由你来做。

**按编号顺序 merge**（001 → 008）。007 在 005/006 之后，顺序天然满足。

```bash
cd /home/ubuntu/projects/pku-captain
git worktree list            # 列出各 worktree 路径与分支名
git checkout main

git merge worktree-001-sources
find src -name '*.py' -print0 | xargs -0 python -m py_compile   # 每次 merge 后校验
git merge worktree-002-rag-stack
find src -name '*.py' -print0 | xargs -0 python -m py_compile
# ... 依次合并 003–008（分支名以实际 git worktree list 输出为准）
```

### 共享文件冲突

worktree Claude 会改这些共享文件来注册自己的产物：

- `src/core/bootstrap.py` —— 注册新 Tool / Workflow / Source。
- `src/{tools,rag,workflows,llm}/__init__.py` —— 导出新符号。
- `pyproject.toml` —— 仅 002 会加嵌入相关依赖。

并行 merge 时这几个文件会冲突。冲突**全是 additive**（双方各加新行，没有改同一行的语义），解决方式恒定：**两边新增的行都保留**。按编号顺序 merge 可把多数冲突降为 git 自动合并。

worktree Claude **不会**改 `docs/roadmap_zh.md` —— roadmap 由 captain 维护。全部合并后由你勾选对应复选框并追加 involver。

## 收尾

全部合并后：

```bash
find src -name '*.py' -print0 | xargs -0 python -m py_compile
ruff check src
python -m src.cli --offline          # 离线 REPL 应能启动
python -m src.cli                    # 在线（需 secrets/deepseek_key.txt）
python scripts/smoke_deepseek.py     # 端到端探针
```

勾选 `docs/roadmap_zh.md` 第 2 周已完成条目并追加 `— @RizzoHou`，提交后 `git push`（main 已预授权）。清理 worktree：

```bash
git worktree remove <worktree-path>   # 对每个 worktree
```
