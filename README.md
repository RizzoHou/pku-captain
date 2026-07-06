# PKU Captain

面向北大学生的桌面 AI 助手。统一信息总站（课表、DDL、课程通知、树洞 / 教务更新）+ 对话式智能助手。OOP / 程序设计实践课程作业，三人团队作品。

## 快速安装（推荐）

普通用户无需 git、无需克隆源码——直接下载打包好的压缩包，解压后一键安装。

**1. 下载**

打开 [最新 Release](https://github.com/RizzoHou/pku-captain/releases/latest)，在 **Assets** 里下载 `pku-captain-1.0.0.zip`（约 80 MB，已包含运行所需的一切：程序、vendored 客户端、文档库 PDF）。

**2. 解压**

解压到任意目录，例如 `~/Downloads/pku-captain`。之后所有命令都在这个解压出来的目录里运行。

**3. 一键安装**（创建 `.venv` 并装好全部依赖，约 1–2 分钟，会下载 PyQt6 等）

```bash
cd ~/Downloads/pku-captain     # 换成你的解压目录
./install.sh                   # 若报权限错误：bash install.sh
```

可选：`./install.sh --math` 额外装聊天气泡的 LaTeX 渲染（PyQt6-WebEngine）。脚本可重复运行。

**4. 启动**

```bash
.venv/bin/python -m src            # 离线：无需密钥，EchoLLMProvider + 离线工具子集
.venv/bin/python -m src --online   # 在线：文本 / 视觉模型 + pku3b 等实时工具
```

## 系统要求

- **macOS 或 Linux**：`install.sh` 是 bash 脚本；Windows 用户请用 WSL。
- **Python 3.11 或更高**：终端运行 `python3 --version` 检查。macOS 若缺 Python，先装 [Homebrew](https://brew.sh) 再 `brew install python@3.12`。
- 约 1 GB 磁盘空间（解压后 ~80 MB + PyQt6 等运行依赖装进 `.venv`）。**无需任何外部二进制**——pku3b / PKUHub 图书 / 树洞 / 教务客户端都已 vendored，PDF 渲染走进程内的 `pypdfium2`，不需要 poppler / Rust / node 等。

## 首次配置（仅在线模式需要）

启动后点右上角 **设置**，在弹窗的各标签页里填写，全部保存在本机 `secrets/`（已 gitignore），不必手动放置文件：

- **统一身份·树洞**：学号 + 门户密码（同一身份驱动 pku3b 的作业 / 通知 / 课表和树洞）。
- **PKUHub**：图书馆邮箱 + 密码。
- **模型配置**：文本模型（默认 DeepSeek）与视觉模型（默认 Kimi，读文档库用）的 API key 与 endpoint。
- **网络代理**：校外访问校内资源时按需设置。

`--online` 无需预先配置任何密钥即可启动：仪表盘工具与登录框都可用，聊天先用占位大脑，在 **模型配置** 里填好文本模型 key 后即时切换为真正的对话模型。`doc_read`（读培养方案文档）需要配置视觉模型。

## 从源码运行（贡献者）

```bash
git clone --depth 1 https://github.com/RizzoHou/pku-captain.git   # 去掉 --depth 1 取完整历史
cd pku-captain
./install.sh --dev                 # 额外带上 pytest / ruff / mypy
.venv/bin/python -m src --online
```

- 手动安装（不用脚本）：`python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev,math]"`。
- 命令行 REPL（同一 agent loop，便于调试）：`.venv/bin/python -m src.cli --offline`（无密钥）/ `.venv/bin/python -m src.cli`（在线）。
- 打包 Release 压缩包：`scripts/package_release.sh` → `dist/pku-captain-<version>.zip`（只含安装运行必需文件 + README）。

---

## 📄 课程作业报告 & 🎬 演示录屏（助教评阅入口）

> **项目作业报告：[`docs/23-作业报告.pdf`](docs/23-作业报告.pdf)** — 程序功能介绍、项目各模块与类设计细节、小组成员分工、项目总结与反思。
>
> **演示录屏：<https://disk.pku.edu.cn/link/AA30E499DD94024C9BADC35DAF521CD5E1>** — 文件名 `pku-captain-v1.mp4`（北大网盘，链接有效期至 2026-08-05）。

---

## 文档

- [环境配置与凭证](https://github.com/RizzoHou/pku-captain/blob/main/docs/setup_zh.md)
- [设计参考](https://github.com/RizzoHou/pku-captain/blob/main/docs/design_reference_zh.md) · [路线图](https://github.com/RizzoHou/pku-captain/blob/main/docs/roadmap_zh.md) · [课程节点](https://github.com/RizzoHou/pku-captain/blob/main/docs/schedule_zh.md) · [接口契约](https://github.com/RizzoHou/pku-captain/blob/main/docs/integration_contract_zh.md)
- 录屏流程 [gui_demo_zh](https://github.com/RizzoHou/pku-captain/blob/main/docs/gui_demo_zh.md) · 手动验收 [gui_manual_test_zh](https://github.com/RizzoHou/pku-captain/blob/main/docs/gui_manual_test_zh.md)
