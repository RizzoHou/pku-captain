# 环境配置

## 账号中心（推荐）

发布版不再要求手动往 `secrets/` 里放文件。启动 GUI 后点击仪表盘右上角 **「账号」** 打开统一的账号中心，三个标签页集中管理全部凭据，写入下方的 `secrets/` 布局：

- **统一身份 · 树洞** —— 北大 IAAA `学号`+密码 登录后完成一次短信验证（需在线模式；写入 `secrets/treehole/{id,password}` 并缓存 `session.json`）。登录成功后会**顺带把同一 IAAA 身份写入 `secrets/pku/{id,password}`**，因此这一次登录同时打通了 pku3b（作业/公告/课表/身份）——无需再手动放 `secrets/pku/` 文件。退出登录会同时清除树洞与 pku 两处凭据（含 `secrets/pku/cookies.json`）。
- **P-Lib 图书** —— 邮箱+密码，保存即持久化到 `secrets/plib/{email,password}`（旧版登录框只校验、不落盘，重启即失效，现已修复）。
- **模型配置** —— 对话模型按 **文本模型 / 视觉模型** 两个角色配置，各含 API 密钥、接口地址、模型名称。DeepSeek / Kimi 只是默认值，可改为任意 OpenAI 兼容端点；保存到 `secrets/models.json`，**重启应用后生效**。

离线启动也可打开账号中心录入以上凭据（树洞短信验证与 P-Lib 在线校验除外），下次以 `--online` 启动即生效。

## 密钥与凭据（文件布局）

所有密钥和账户凭据都放在 `secrets/` 目录下（整个目录已 gitignore）。账号中心会写入下列文件；也可手动创建（每个纯文本文件只存一行，`models.json` 为 JSON）：

```
secrets/
  models.json            # 对话模型配置：{"text": {...}, "visual": {...}}，每项含 api_key / base_url / model
  api_keys/
    deepseek_key.txt     # 兼容回退 —— 文本模型缺 api_key 时读取（旧布局）
    kimi_key.txt         # 兼容回退 —— 视觉模型缺 api_key 时读取（旧布局）
    embedding_key.txt    # 已弃用 —— 旧 RAG 嵌入模型（文档库取代后不再使用）
  plib/
    email                # P-Lib（PKUHUB）账号邮箱
    password             # P-Lib 账号密码
  treehole/
    id                   # 树洞登录账号（IAAA 学号）
    password             # 树洞登录密码
  pku/
    id                   # PKU IAAA 学号（教学网 Blackboard + 信息门户）
    password             # IAAA 门户密码（内嵌 pypku3b 登录用）
```

- `models.json`（在线必需）—— 两个模型角色的端点/模型/密钥。`text`（默认 DeepSeek V4 Pro，`https://api.deepseek.com/v1`）为默认 brain，`visual`（默认 Kimi K2.6，`https://api.moonshot.cn/v1`，原生多模态）驱动文档库视觉阅读。缺 `text` 的 api_key 时 `--online` 会回退到离线模式（`EchoLLMProvider`）。
- `api_keys/{deepseek,kimi}_key.txt`（兼容回退）—— 当 `models.json` 里对应角色没有 api_key 时，从这里读取旧布局的单文件密钥（也兼容更旧的扁平路径 `secrets/{deepseek,kimi}_key.txt`），因此老 checkout 无需迁移即可继续工作。
- **视觉模型的用途**：对话表头可把 brain 从文本模型切到视觉模型（256k 上下文、原生多模态）；文档库阅读时 `doc_read` 把 PDF 页面图片直接喂给视觉模型自己看，仪表盘「让 Captain 阅读」用封装式 `DocBaseReader` 直接问它。缺视觉模型密钥：对话只剩文本模型，文档库只能浏览 / 打开 PDF。
- `api_keys/embedding_key.txt`（已弃用）—— 旧 RAG 的阿里云百炼嵌入模型。文档库（拆分 PDF + 视觉阅读）取代 RAG 后不再读取此文件，保留仅为历史兼容。
- `plib/{email,password}`（P-Lib 必需）—— `PLibMaterialsTool` 会在每次调用前把它们作为 `Credentials` 直接传给内嵌的 `plib_cli` 库，所以 search / quota / download 无需手动 `login`（P-Lib 登录是自愈的）。
- `treehole/{id,password}`（树洞必需）—— `TreeholeUpdatesTool` / `TreeholeAuthService` 从此目录读取登录凭据；首次在线运行会提示“需要短信验证”，在账号中心「统一身份 · 树洞」完成一次短信验证后会缓存 `secrets/treehole/session.json` 并复用。
- `pku/{id,password}`（作业/公告/课表/身份必需）—— 内嵌的 `pypku3b` 用它登录 PKU IAAA（教学网 Blackboard + 信息门户）。登录成功后会话 cookie 缓存在 `secrets/pku/cookies.json`，后续调用复用会话（免重复登录/OTP）。见下文「pku3b（内嵌 pypku3b）」。

```bash
python -m src --online          # 文本模型 + 实时工具；表头可切换到视觉模型（需视觉模型密钥）
python -m src.cli               # CLI 走真实 DeepSeek
```

## pku3b（内嵌 pypku3b —— 无需 Rust）

PKU Captain 读取 Blackboard 上的作业、课程通知、个人课表与身份信息。**不再依赖外部 `pku3b` Rust 二进制**——这几个用到的功能已用纯 Python 重写为 [`pypku3b`](https://github.com/RizzoHou/pypku3b)，像 plib/dean/treehole 一样通过 `git subtree` **内嵌**在 `vendor/pypku3b/`，作为顶层 `pypku3b` 包由 pku-captain 自己的 `pip install -e ".[dev]"` 一并装好——**无需**装 Rust 工具链、`cargo install`，也没有子进程。工具在进程内直接驱动 `pypku3b.Client`。

### 凭据

**推荐**：直接在账号中心「统一身份 · 树洞」登录一次即可——它会把 IAAA `学号`/`密码` 同时写入 `secrets/treehole/` 与 `secrets/pku/`，pku3b 无需额外配置。

也可手动在 `secrets/pku/` 放两个文件（见上文「密钥与凭据」）：

```
secrets/pku/id           # IAAA 学号
secrets/pku/password     # IAAA 门户密码
```

`pypku3b` 用它们登录三个独立的 IAAA 应用：`blackboard`（作业/公告）、`portalPublicQuery`（课表）、`portal2017`（身份）。

### 系统依赖

无额外系统依赖——`requests` + `beautifulsoup4` + `lxml` 都在 `pip install -e ".[dev]"` 里。TLS 默认走**操作系统信任库**而非 certifi（`course.pku.edu.cn` 的 GlobalSign 证书链在部分 certifi 版本里验不过），这一点已内置无需配置。

### 验证

```bash
.venv/bin/python -c "from src.tools.pku3b_assignments import PKU3bAssignmentsTool; r=PKU3bAssignmentsTool().invoke({'include_completed': True}); print(r.success, len(r.data['assignments']) if r.success else r.error)"
.venv/bin/python -c "from src.tools.pku3b_coursetable import PKU3bCourseTableTool; r=PKU3bCourseTableTool().invoke({}); print(r.success, len(r.data['blocks']) if r.success else r.error)"
```

也可用内嵌库自带的 CLI（主要用于独立调试）：`.venv/bin/pypku3b assignment list --format json | jq .`。

### 首次登录 / OTP

首次在线运行会用 `secrets/pku` 的凭据自动登录，无需交互；登录会话 cookie 缓存在 `secrets/pku/cookies.json`，之后复用。若账号开启了手机令牌（OTP），课表工具可在仪表盘顶部输入 OTP 后刷新（身份/作业同理，凭据正确时多数账号无需 OTP）。

### 升级内嵌库

`pypku3b` 的**源头**是独立仓库 `~/projects/pypku3b`（不是 `vendor/` 里的副本）。改动流程：在独立仓库里改、跑 `pytest`、`git push`，然后在 pku-captain 里 `git subtree pull --prefix vendor/pypku3b git@github.com:RizzoHou/pypku3b.git main --squash`。独立仓库带一套网络回归测试（`tests/live/`，`PYPKU3B_LIVE=1` 才跑，需真实凭据），可对真实接口验证抓取是否正确。

## P-Lib（P-Lib 资料检索需要）

`PLibMaterialsTool` 检索、下载 PKUHUB 课程资料。[`plib-cli`](https://github.com/RizzoHou/plib-cli) 已通过 `git subtree` **内嵌**在 `vendor/plib-cli/`，作为顶层 `plib_cli` 包由 pku-captain 自己的 `pip install -e ".[dev]"` 一并装好——**无需**单独 clone 或建 venv，也没有子进程。工具在进程内直接驱动 `plib_cli.client.PlibClient`。

P-Lib 账号是 PKUHUB 自注册的邮箱 / 密码（**不是** IAAA），在 <https://pkuhub.cn/register> 注册后把邮箱、密码分别写进 `secrets/plib/email`、`secrets/plib/password`（见上文“密钥与凭据”）。验证：

```bash
.venv/bin/python -c "from src.tools.plib_materials import PLibMaterialsTool; print(PLibMaterialsTool().invoke({'action':'quota'}).data)"
# 已登录时返回 {"download_remaining": N}
```

普通账号每天 10 次下载额度，下载会保存到 `downloads/plib/`。升级内嵌库：`git subtree pull --prefix vendor/plib-cli git@github.com:RizzoHou/plib-cli.git main --squash`。

## 树洞（关注消息 / macOS 通知）

`TreeholeUpdatesTool` 读取关注/收藏树洞的新回复。[`pku-treehole-cli`](https://github.com/RizzoHou/pku-treehole-cli) 已通过 `git subtree` **内嵌**在 `vendor/pku-treehole-cli/`，作为顶层 `treehole` 包由 pku-captain 自己的 `pip install -e ".[dev]"` 一并装好——**无需**单独 clone 或建 venv（工具在进程内直接 `import treehole`）。

登录走 IAAA：在 GUI 里点 **◉ 树洞 → 登录**，输入学号/密码后按提示完成短信验证；凭据与会话会写进 `secrets/treehole/{id,password,session.json}`。

**macOS 桌面通知**（仅 macOS）：在树洞弹窗里点 **消息通知**，选择检查间隔后「开启通知」。后台会装一个用户级 LaunchAgent（`com.pku.captain.treehole.notify`），按间隔跑 `treehole monitor --notify`，复用上面 `secrets/treehole` 的登录会话——所以 GUI 登录一次即可。这里用的 `treehole` 程序由 pku-captain 自己 venv 的 console script 提供（`pyproject.toml` `[project.scripts]`），LaunchAgent 指向 `.venv/bin/treehole` 的绝对路径。两个前提：

- pku-captain 的 venv 已 `pip install -e .`（`.venv/bin/treehole` 存在；找不到时「开启通知」按钮会禁用并提示）；
- 首条通知前需在「系统设置 › 通知」里允许 **“Script Editor”** 发送通知（投递走 `osascript`，会显示为 Script Editor 图标）。

间隔偏好存在 `data/treehole_notify.json`，「关闭通知」会卸载 LaunchAgent。

## 教务部（dean.pku.edu.cn 公开资源）

`DeanResourcesTool` 读取北大教务部网站的**公开**资源（学生服务侧边栏、培养指南、校级/国家规章、通知公告、可下载表格手册、信息公开文件）。[`pku-dean-cli`](https://github.com/RizzoHou/pku-dean-cli) 已通过 `git subtree` **内嵌**在 `vendor/pku-dean-cli/`，作为顶层 `dean` 包由 pku-captain 自己的 `pip install -e ".[dev]"` 一并装好——**无需**单独 clone 或建 venv，也没有子进程。所有资源都无需登录，没有任何凭据要求；工具在进程内直接驱动 `dean.client.DeanClient` + `dean.resources.*`。

验证：

```bash
.venv/bin/python -c "from src.tools.dean_resources import DeanResourcesTool; print(len(DeanResourcesTool().invoke({'action':'sidebar'}).data))"
```

工具暴露**只读**检索动作（`sidebar` / `guide` / `rules_list` / `rules_show` / `notice_list` / `notice_show` / `download_list` / `openinfo_list`）以及文件下载动作（`download_get` / `openinfo_get`，把二进制写到 `downloads/dean/<kind>`）。`--all`（抓全部分页）未暴露——它会逐页串行抓取、容易撑爆超时和对话上下文，调用方用 `page` 翻页即可（返回里带 `last_page`）。升级内嵌库：`git subtree pull --prefix vendor/pku-dean-cli git@github.com:RizzoHou/pku-dean-cli.git main --squash`。

## 文档库 doc_base（拆分重建——仅在源 PDF 更新时需要）

`doc_base/` 用「拆分后的小 PDF + 视觉读取」取代了原先的向量知识库（培养方案 PDF 里大量图表，嵌入模型读不动）。`doc_base/original/` 放教务部原始大 PDF（培养方案文/理科卷、辅修双专业、选课手册），`scripts/split_doc_base.py` 把它们按大纲 / 印刷目录拆成 `学部/院系/专业.pdf` 这样的层级小文件，并生成 `doc_base/manifest.json` 索引。拆分结果**已提交进仓库**，正常使用无需重跑；只有当 `original/` 换了新一年的 PDF 时才需要重建。

**运行时**（用文档库回答问题，不是重建）：`doc_search` 只读 `manifest.json`，离线也能用，无依赖。读文档需要 (1) `secrets/api_keys/kimi_key.txt`，(2) 运行机上有 `pdftoppm`（`brew install poppler`）。两条路径：**对话里**——把 brain 切到 Kimi K2.6（或问培养方案类问题时自动切换），`doc_read` 把 PDF 页面图片直接喂给 Kimi 自己看图作答（DeepSeek brain 下不注册 `doc_read`）；**仪表盘文档库弹窗**——「让 Captain 阅读」用封装式 `DocBaseReader` 直接问 Kimi 返回文本答案。缺 Kimi key 时两条路径都不可用，文档库仍可浏览 / 打开 PDF。

重建依赖三个系统 CLI（不进 venv，`brew install` 即可）：

```bash
brew install qpdf poppler ghostscript   # qpdf 拆页 / poppler 取文字+大纲 / ghostscript 重做字体子集
.venv/bin/python scripts/split_doc_base.py        # 重建全部卷，覆写各卷目录（original/ 不动）
.venv/bin/python scripts/split_doc_base.py --dry-run   # 只算边界与逐页核对，不写文件
```

每卷的拆分策略见脚本顶部 `SOURCES`：培养方案两卷走 PDF 大纲（`outline`），选课手册与辅修双专业卷大纲不可靠 / 没有书签，改用脚本里人工核对过的章节表（`EXPLICIT_SECTIONS`）。脚本对每卷做逐页核对（拆出页数 + 丢弃页数 == 原始页数），并用 ghostscript 把每个小 PDF 的字体重新子集化（体积约降到 1/4，文字与图表无可见变化；`gs` 缺失或加 `--no-shrink` 时跳过，结果仍正确只是更大）。源 PDF 换版后需重新核对 `EXPLICIT_SECTIONS` 的页码（辅修双专业卷的页码 = 印刷目录页码 + 12，偏移量逐项验证过）。
