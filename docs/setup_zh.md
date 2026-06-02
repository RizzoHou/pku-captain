# 环境配置

## API Keys

密钥都放在 `secrets/` 目录下（整个目录已 gitignore），每个文件只存一行密钥：

- `secrets/deepseek_key.txt`（在线必需）—— DeepSeek 对话模型。缺失时 `--online` 会回退到离线模式（`EchoLLMProvider`）。
- `secrets/embedding_key.txt`（仅 RAG 需要）—— 阿里云百炼 DashScope 嵌入模型（`text-embedding-v4`，OpenAI 兼容端点）。**只有显式开启 RAG（`--rag`）时才需要**；RAG 默认关闭，不开则启动不读此文件、也不发任何嵌入请求。也支持读取工作区共享路径 `../secrets/api_key.txt`。获取 Key：<https://help.aliyun.com/zh/model-studio/get-api-key>。

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
cargo install --git https://github.com/RizzoHou/pku3b --branch feat/assignment-list-json-output
```

二进制会被放到 `~/.cargo/bin/pku3b`，确认它在 `PATH` 上（或自行 symlink 到 `~/.local/bin/`）。

### 验证

```bash
pku3b --version                              # 0.13.0+，来自我们的分支
pku3b assignment list --format json | jq .   # 验证 --format json 标志可用
```

如果第二条命令报 `unknown flag --format`，说明装到了上游版本，重新跑上面的 `cargo install`。

### 首次登录

`pku3b` 需要交互式登录一次后才能拉数据。按 CLI 提示输入 IAAA 账号即可，凭据缓存在本地。Python 包装层只负责调用 CLI，不驱动登录流程。

### 已知小坑

`pku3b` 的 stdout 在重定向到普通文件时会失败（exit 1，空输出）——这是 compio 轮询后端的已知上游问题。管道是好的（`subprocess.run(capture_output=True)` 用的就是管道），所以 Python 包装层不受影响；如果你想在 shell 里手动调试，用管道（`pku3b ... | jq .`）而不是 `>`。
