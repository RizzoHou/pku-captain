# 环境配置

## 密钥与凭据

所有密钥和账户凭据都放在 `secrets/` 目录下（整个目录已 gitignore），每个文件只存一行内容。当前布局：

```
secrets/
  api_keys/
    deepseek_key.txt     # 在线必需 —— DeepSeek 对话模型
    embedding_key.txt    # 仅 RAG 需要 —— 阿里云百炼 DashScope 嵌入模型
    kimi_key.txt         # 预留 —— Kimi 视觉模型（当前 agent 尚未接入，留作后续视觉功能）
  plib/
    email                # P-Lib（PKUHUB）账号邮箱
    password             # P-Lib 账号密码
  treehole/
    id                   # 树洞登录账号（IAAA 学号）
    password             # 树洞登录密码
```

- `api_keys/deepseek_key.txt`（在线必需）—— DeepSeek 对话模型。缺失时 `--online` 会回退到离线模式（`EchoLLMProvider`）。也兼容旧布局 `secrets/deepseek_key.txt`。
- `api_keys/embedding_key.txt`（仅 RAG 需要）—— 阿里云百炼 DashScope 嵌入模型（`text-embedding-v4`，OpenAI 兼容端点）。**只有显式开启 RAG（`--rag`）时才需要**；RAG 默认关闭，不开则启动不读此文件、也不发任何嵌入请求。获取 Key：<https://help.aliyun.com/zh/model-studio/get-api-key>。
- `plib/{email,password}`（P-Lib 必需）—— `PLibMaterialsTool` 会在每次调用前自动注入为 `PLIB_EMAIL` / `PLIB_PASSWORD` 环境变量，所以 search / quota / download 无需手动 `login`（P-Lib 登录是自愈的）。
- `treehole/{id,password}`（树洞必需）—— `TreeholeUpdatesTool` / `TreeholeAuthService` 从此目录读取登录凭据；首次在线运行会提示“需要短信验证”，在 GUI 树洞面板完成一次短信验证后会缓存 `secrets/treehole/session.json` 并复用。

```bash
python -m src --online          # DeepSeek + 实时工具，RAG 关闭（默认）
python -m src --online --rag     # 额外开启 RAG knowledge_search（需 embedding key）
python -m src.cli --rag          # CLI 同样支持 --rag
```

## pku3b（必需）

PKU Captain 通过 [`pku3b`](https://github.com/sshwy/pku3b) Rust CLI 读取 Blackboard 上的作业、课程通知与附件。**我们用的是 fork，不是上游**——fork 在 `assignment list` 上新增了 `--format json` 标志，让 Python 包装层（`src/tools/pku3b.py`）直接消费结构化输出，而不是用正则去解析渲染后的 ANSI 文本。装上游版本会让我们的工具直接报错。

### 系统依赖

- Rust toolchain（推荐 [`rustup`](https://rustup.rs/) 安装）
- `pkg-config` + `libssl-dev`

Debian / Ubuntu：

```bash
sudo apt install pkg-config libssl-dev
```

macOS：

```bash
brew install openssl pkg-config
```

### 安装

```bash
cargo install --git https://github.com/RizzoHou/pku3b --branch master
```

二进制会被放到 `~/.cargo/bin/pku3b`，确认它在 `PATH` 上（或自行 symlink 到 `~/.local/bin/`）。

### 验证

```bash
pku3b --version                              # 0.13.0+，来自我们的分支
pku3b assignment list --format json | jq .   # 验证 --format json 标志可用
pku3b identity --format json | jq .          # 验证身份摘要 JSON 可用（不要使用 --raw）
```

如果第二条命令报 `unknown flag --format`，说明装到了上游版本，重新跑上面的 `cargo install`。

### 首次登录

`pku3b` 需要交互式登录一次后才能拉数据。按 CLI 提示输入 IAAA 账号即可，凭据缓存在本地。Python 包装层只负责调用 CLI，不驱动登录流程。

### 已知小坑

`pku3b` 的 stdout 在重定向到普通文件时会失败（exit 1，空输出）——这是 compio 轮询后端的已知上游问题。管道是好的（`subprocess.run(capture_output=True)` 用的就是管道），所以 Python 包装层不受影响；如果你想在 shell 里手动调试，用管道（`pku3b ... | jq .`）而不是 `>`。

## P-Lib / plib-cli（P-Lib 资料检索需要）

`PLibMaterialsTool` 通过 [`plib-cli`](https://github.com/RizzoHou/plib-cli) 子进程检索、下载 PKUHUB 课程资料，模式和 `pku3b` 一致：跑 `plib --format json`，再 `json.loads` 它的稳定 JSON 信封。它需要独立 venv 安装，工具会按顺序在 `PATH`、`../plib-cli/.venv/bin/plib`、`<repo>/.local/bin/plib` 查找二进制。

推荐装法（克隆到工作区根目录，与 pku-captain 同级）：

```bash
cd ..
git clone https://github.com/RizzoHou/plib-cli
cd plib-cli
python3 -m venv .venv && .venv/bin/pip install -e .
```

P-Lib 账号是 PKUHUB 自注册的邮箱 / 密码（**不是** IAAA），在 <https://pkuhub.cn/register> 注册后把邮箱、密码分别写进 `secrets/plib/email`、`secrets/plib/password`（见上文“密钥与凭据”）。验证：

```bash
../plib-cli/.venv/bin/plib quota --format json   # 返回 {"ok": true, "data": {"download_remaining": N}}
```

普通账号每天 10 次下载额度，下载会保存到 `downloads/plib/`。

## 树洞（关注消息 / macOS 通知）

`TreeholeUpdatesTool` 通过 [`pku-treehole-cli`](https://github.com/RizzoHou/pku-treehole-cli) 读取关注/收藏树洞的新回复，模式和 `plib-cli` 一致：克隆到工作区根目录（与 pku-captain 同级），装独立 venv：

```bash
cd ..
git clone https://github.com/RizzoHou/pku-treehole-cli
cd pku-treehole-cli
python3 -m venv .venv && .venv/bin/pip install -e .
```

登录走 IAAA：在 GUI 里点 **◉ 树洞 → 登录**，输入学号/密码后按提示完成短信验证；凭据与会话会写进 `secrets/treehole/{id,password,session.json}`。

**macOS 桌面通知**（仅 macOS）：在树洞弹窗里点 **消息通知**，选择检查间隔后「开启通知」。后台会装一个用户级 LaunchAgent（`com.pku.captain.treehole.notify`），按间隔跑 `treehole monitor --notify`，复用上面 `secrets/treehole` 的登录会话——所以 GUI 登录一次即可，无需在 treehole-cli 里再登一遍。两个前提：

- 上面的 `pku-treehole-cli/.venv` 已装好（找不到 `treehole` 程序时「开启通知」按钮会禁用并提示）；
- 首条通知前需在「系统设置 › 通知」里允许 **“Script Editor”** 发送通知（投递走 `osascript`，会显示为 Script Editor 图标）。

间隔偏好存在 `data/treehole_notify.json`，「关闭通知」会卸载 LaunchAgent。

## 教务部（dean.pku.edu.cn 公开资源）

`DeanResourcesTool` 通过 [`pku-dean-cli`](https://github.com/RizzoHou/pku-dean-cli) 子进程读取北大教务部网站的**公开**资源（学生服务侧边栏、培养指南、校级/国家规章、可下载表格手册、信息公开文件），模式和 `plib-cli` 一致：跑 `dean --format json`，再 `json.loads` 它的稳定 JSON 信封。所有资源都无需登录，没有任何凭据要求。工具按顺序在 `PATH`、`../pku-dean-cli/.venv/bin/dean`、`<repo>/.local/bin/dean` 查找二进制。

推荐装法（克隆到工作区根目录，与 pku-captain 同级）：

```bash
cd ..
git clone https://github.com/RizzoHou/pku-dean-cli
cd pku-dean-cli
python3 -m venv .venv && .venv/bin/pip install -e .
```

验证：

```bash
../pku-dean-cli/.venv/bin/dean --format json rules list --scope school | jq .
```

工具暴露的是**只读**检索动作（`sidebar` / `guide` / `rules_list` / `rules_show` / `download_list` / `openinfo_list`）；CLI 的文件下载动作（`download get` / `openinfo get`，会把二进制写到磁盘）v1 暂未接入。`--all`（抓全部分页）也未暴露——它会逐页串行抓取、容易撑爆超时和对话上下文，调用方用 `page` 翻页即可（返回里带 `last_page`）。
