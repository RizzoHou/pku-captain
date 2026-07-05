# PKU Captain

面向北大学生的桌面 AI 助手。统一信息总站（课表、DDL、课程通知、树洞 / 教务更新）+ 对话式智能助手。OOP / 程序设计实践课程作业，三人团队作品。

## 安装

需要 Python 3.11+。**无需任何外部二进制**——PDF 渲染走进程内的 `pypdfium2`，pku3b / 图书馆 / 树洞 / 教务客户端都已 vendored 进本仓库。

```bash
./install.sh            # 一键安装：创建 .venv 并装好依赖
./install.sh --math     # 额外安装聊天气泡的 LaTeX 渲染（PyQt6-WebEngine）
./install.sh --dev      # 额外安装开发工具链（pytest / ruff / mypy）
```

或手动：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .        # 加 ".[dev,math]" 可一并带上开发 / LaTeX 依赖
```

## 启动

```bash
.venv/bin/python -m src          # 离线：EchoLLMProvider + 离线工具子集，无需密钥
.venv/bin/python -m src --online # 在线：文本 / 视觉模型 + pku3b 等实时工具
```

首次克隆离线即可运行。在线模式的**模型密钥与账号**都在应用内 **设置** 弹窗里填写，不必手动放置文件；缺少文本模型密钥时会自动回退离线模式。

命令行 REPL（同一 agent loop，便于调试）：

```bash
.venv/bin/python -m src.cli --offline   # 无密钥，EchoLLMProvider
.venv/bin/python -m src.cli             # 在线 DeepSeek
```

## 文档

- [`docs/setup_zh.md`](docs/setup_zh.md) — 环境配置与凭证说明
- [`docs/design_reference_zh.md`](docs/design_reference_zh.md) — 设计参考
- [`docs/roadmap_zh.md`](docs/roadmap_zh.md) — 开发路线图
- [`docs/schedule_zh.md`](docs/schedule_zh.md) — 课程节点
- [`docs/integration_contract_zh.md`](docs/integration_contract_zh.md) — 后端 / GUI 接口契约

录屏流程见 [`docs/gui_demo_zh.md`](docs/gui_demo_zh.md)，手动验收见 [`docs/gui_manual_test_zh.md`](docs/gui_manual_test_zh.md)。
