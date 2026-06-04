# PKU Captain — 项目功能设计文档

一句话简介：面向北大学生的桌面 AI 助手。将课业、讲座、食堂、校务办事流程等分散信息整合到一个对话+仪表盘界面中，由 LLM agent 通过工具调用与持续刷新的知识库检索，给出基于真实情境的答案与多步骤自动化。

## 项目动机

北大学生日常需在十多个互不连通的系统间切换：教学网查作业、北大讲座网看讲座、食堂神器看人流、教务部网站查办事流程（辅修申报、缓考申请等）、树洞/BBS 闲聊。每一处都需独立登录、适应不同界面，且信息易过期。通用 LLM 缺乏个人化背景，不知道你的课表、今日通知、临近 DDL。PKU Captain 把权威 PKU 数据源接入 LLM agent，使之能基于真实情境响应；并通过自动增量刷新的知识库，保证信息时效性。

## 核心功能

1. **统一仪表盘** — 今日课表、近期 DDL、未读课程通知、今日推荐讲座、~~天气~~（2026-06-04 砍掉：学生用手机看天气，应用内意义不大）、食堂建议，一屏呈现。
2. **对话侧栏** — 自然语言查询所有 PKU 数据；agent 工具调用过程对用户可见。
3. **工具集** — 可被 agent 调用的工具集合 — pku3b（作业/通知/课表）、食堂检索、讲座检索、~~天气~~（2026-06-04 砍掉：学生用手机看天气，应用内意义不大）、知识库检索、记忆、提醒。
4. **多步工作流** — 组合工具调用完成复杂任务，含 今日简报、周复盘、课程补课。
5. **PKU 知识库（RAG）+ 自动刷新** — 从权威页面（教务部、院系培养方案、校历、学工部等）抓取并向量化存储。后台调度器按各数据源自身节奏轮询；通过 SHA-256 哈希比对仅对变更块重新嵌入；新通知以仪表盘红点形式主动推送给用户。
6. **记忆系统** — 持久化存储个人偏好（食堂、口味、课程、学习习惯），并在每次响应中自然融入。

明确不在范围内：作业自动完成、自动选课、实时食堂人流（无公开数据源）。

## 系统架构

系统自上而下分五层：

- **UI 层（PyQt6）** — 仪表盘 · 对话窗口 · Agent 日志面板。
- **Agent 内核** — Conversation、Memory、ToolRegistry、WorkflowEngine；负责调度 LLM 调用与工具派发。
- **LLM 层（通过 LLMProvider 抽象）** — DeepSeek（对话）、Kimi（视觉），运行时可切换。
- **工具集** — pku3b（作业/通知/课表）、食堂、讲座、~~天气~~（2026-06-04 砍掉）、KnowledgeSearch、Memory、Reminder；均为 Tool 子类，附 JSON schema。
- **知识库 pipeline** — Source 子类（Dean、Department、Lecture、Calendar）→ Scheduler → Differ（SHA-256）→ Chunker → Embedder（BGE-large-zh）→ KnowledgeBase（SQLite + numpy）→ Retriever，对 agent 暴露为 KnowledgeSearch 工具。

## 类设计要点（OOP）

四条平行的多态继承体系构成 OOP 设计核心；新增工具/数据源/LLM 仅需"子类化 + 注册"，体现开闭原则。

- **Tool（抽象基类）** — PKU3bAssignmentsTool、PKU3bAnnouncementsTool、CanteenTool、LectureTool、KnowledgeSearchTool、MemoryTool、ReminderTool。各子类定义 JSON schema 与 `invoke(args) → Result`。
- **Workflow（抽象基类）** — MorningBriefingWorkflow、WeeklyReviewWorkflow、CourseCatchupWorkflow。各子类组合工具调用序列。
- **LLMProvider（抽象基类）** — DeepSeekProvider、KimiProvider。运行时可通过配置切换。
- **Source（抽象基类）** — DeanSource、DepartmentSource、LectureSource、CalendarSource。各子类实现自身抓取逻辑与 `refresh_interval`；采集 pipeline 对所有源统一处理。

## 技术栈

| 关注点 | 选型 |
| --- | --- |
| 语言 / GUI | Python 3.11 + PyQt6 |
| LLM | DeepSeek（对话）、Kimi（视觉）；通过 LLMProvider 抽象解耦 |
| 嵌入模型 | BAAI bge-large-zh-v1.5（本地、免费） |
| 向量存储 | SQLite + numpy 余弦搜索（约 500 块） |
| 教学网集成 | pku3b（Rust CLI）以子进程封装调用 |
| 网页抓取 | requests + BeautifulSoup |
| 持久化 | SQLite（记忆、KB 元数据、源内容哈希） |

## 团队分工

- **成员 A — 后端与工具**：pku3b 封装、工具实现、记忆模块、食堂/建筑数据整理。
- **成员 B — Agent 与知识库**：LLM provider、工作流引擎、KB 采集 pipeline（源、调度器、差分、分块、嵌入）、检索器。
- **成员 C — UI 与体验**：PyQt 主窗口、仪表盘、聊天面板、工具调用可视化、通知系统、视觉打磨。
