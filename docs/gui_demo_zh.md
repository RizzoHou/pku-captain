# GUI 演示脚本

本脚本用于 2026-06-06 初版录屏。目标是在 30-60 秒内展示 PKU Captain 的三条主线：仪表盘主入口、对话侧栏、可见工具调用。

## 启动前检查

在仓库根目录执行：

```bash
test -f secrets/api_keys/deepseek_key.txt && echo "DeepSeek key ready"
pku3b --version  # 或仓库本地 .local/cargo/bin/pku3b --version
.venv/bin/python -m src --help
```

如果需要代理：

```bash
export http_proxy=http://127.0.0.1:7897
export https_proxy=http://127.0.0.1:7897
export all_proxy=http://127.0.0.1:7897
```

## 启动 GUI

```bash
.venv/bin/python -m src --online
```

## 录屏流程

1. 启动后停留在仪表盘，展示“近期 DDL / 课程通知 / 讲座推荐”卡片。
   画面重点：北大红标题、白色信息卡片、红色主按钮。
2. 如课表需要 OTP，在右上角 `课表 OTP` 输入框输入手机令牌；点击“刷新”，展示卡片进入加载态并恢复为真实数据。
3. 点击“今日简报”，展示对话侧栏出现系统提示和简报结果。
4. 在对话输入框输入：

```text
今天和最近有什么作业？
```

5. 发送后展示右侧工具调用面板：先出现调用中，再出现摘要结果。
6. 对话侧栏展示最终回答后结束录屏。

## 失败时的兜底说明

- 如果 DeepSeek 不可用，GUI 会回退离线模式；可展示界面结构和 Dashboard 刷新。
- 如果 pku3b 网络失败，Dashboard 卡片会显示错误状态；保留工具调用面板错误用于说明系统有可诊断 UX。
