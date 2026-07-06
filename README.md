# PKU Captain

面向北大学生的桌面 AI 助手。统一信息总站（课表、DDL、课程通知、树洞 / 教务更新）+ 对话式智能助手。OOP / 程序设计实践课程作业，三人团队作品。

## 系统要求

- **macOS 或 Linux**：`install.sh` 是 bash 脚本；Windows 用户请用 WSL，或按下方「手动安装」步骤操作。
- **Python 3.11 或更高**：终端运行 `python3 --version` 检查。
- **git**：用于克隆仓库。
- 约 1 GB 磁盘空间（仓库 ~80 MB + PyQt6 等运行依赖装进 `.venv`）。**无需任何外部二进制**——pku3b / PKUHub 图书 / 树洞 / 教务客户端都已 vendored 进本仓库，PDF 渲染走进程内的 `pypdfium2`，不需要 poppler / Rust / node 等。

macOS 上若缺 Python 或 git，先安装 [Homebrew](https://brew.sh)，再：

```bash
brew install git python@3.12
```

## 安装（从零开始）

**1. 克隆仓库**（含文档库 PDF，约 80 MB，视网速需要几分钟）

用 `--depth 1` 浅克隆——只取最新版本，跳过历史里的大文件，明显更快：

```bash
git clone --depth 1 https://github.com/RizzoHou/pku-captain.git
cd pku-captain
```

（贡献者若需完整提交历史，去掉 `--depth 1` 做完整克隆即可。）

**2. 一键安装**（在仓库根目录运行——脚本会创建 `.venv` 并装好全部依赖，约 1–2 分钟，会下载 PyQt6 等）

```bash
./install.sh            # 核心安装
# 若报权限错误，改用：bash install.sh
```

可选参数（可叠加，脚本可重复运行）：

```bash
./install.sh --math     # 额外：聊天气泡的 LaTeX 渲染（PyQt6-WebEngine）
./install.sh --dev      # 额外：开发工具链（pytest / ruff / mypy）
```

**3. 启动**

```bash
.venv/bin/python -m src            # 离线：无需密钥，EchoLLMProvider + 离线工具子集
.venv/bin/python -m src --online   # 在线：文本 / 视觉模型 + pku3b 等实时工具
```

**4. 首次配置**（在线模式才需要）

启动后点右上角 **设置**，在弹窗的各标签页里填写，全部保存在本机 `secrets/`（已 gitignore），不必手动放置文件：

- **统一身份·树洞**：学号 + 门户密码（同一身份驱动 pku3b 的作业 / 通知 / 课表和树洞）。
- **PKUHub**：图书馆邮箱 + 密码。
- **模型配置**：文本模型（默认 DeepSeek）与视觉模型（默认 Kimi，读文档库用）的 API key 与 endpoint。
- **网络代理**：校外访问校内资源时按需设置。

`--online` 无需预先配置任何密钥即可启动：仪表盘工具与登录框都可用，聊天先用占位大脑，在 **模型配置** 里填好文本模型 key 后即时切换为真正的对话模型。`doc_read`（读培养方案文档）需要配置视觉模型。

### 手动安装（不用脚本）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # 加 ".[dev,math]" 可一并带上开发 / LaTeX 依赖
python -m src --online
```

### 命令行 REPL（同一 agent loop，便于调试）

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
