# PKU Captain

面向北大学生的桌面 AI 助手。统一信息总站（课表、DDL、课程通知）+ 对话式智能助手。OOP / 程序设计实践课程作业，三人团队作品。

---

## 📄 课程作业报告 & 🎬 演示录屏（助教评阅入口）

> **项目作业报告：[`docs/23-作业报告.pdf`](docs/23-作业报告.pdf)** — 程序功能介绍、项目各模块与类设计细节、小组成员分工、项目总结与反思。
>
> **演示录屏：<https://disk.pku.edu.cn/link/AA30E499DD94024C9BADC35DAF521CD5E1>** — 文件名 `pku-captain-v1.mp4`（北大网盘，链接有效期至 2026-08-05）。

---

## 文档

- [`docs/setup_zh.md`](docs/setup_zh.md) — 环境配置（pku3b 安装等）
- [`docs/design_reference_zh.md`](docs/design_reference_zh.md) — 设计参考
- [`docs/roadmap_zh.md`](docs/roadmap_zh.md) — 开发路线图
- [`docs/schedule_zh.md`](docs/schedule_zh.md) — 课程节点
- [`docs/integration_contract_zh.md`](docs/integration_contract_zh.md) — 后端 / GUI 接口契约

## GUI 启动

```bash
.venv/bin/python -m src          # 离线 GUI：EchoLLMProvider + 离线工具子集
.venv/bin/python -m src --online # 在线 GUI：DeepSeek + pku3b 等实时工具
```

在线模式需要 `secrets/deepseek_key.txt` 和 fork 版 `pku3b`。缺少 DeepSeek key 时 GUI 会自动回退离线模式；缺少 `pku3b` 时 DDL / 通知相关卡片会显示错误状态。
GUI 在线启动会跳过本地 BGE RAG 的预加载，避免首次启动下载大模型；后端 `build_agent()` 默认完整路径仍保留 `KnowledgeSearchTool`。

安装 `pku3b` 还需要本机先具备 Rust/Cargo：

```bash
cargo install --git https://github.com/RizzoHou/pku3b --branch master
pku3b --version
pku3b assignment list --format json
pku3b identity --format json
```

当前开发机也支持项目内工具链路径：

```bash
.local/cargo/bin/pku3b --version
```

录屏流程见 [`docs/gui_demo_zh.md`](docs/gui_demo_zh.md)，手动验收见 [`docs/gui_manual_test_zh.md`](docs/gui_manual_test_zh.md)。
