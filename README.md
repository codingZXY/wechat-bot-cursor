# wx-claw-bot

通过微信 **ilink / ClawBot** 协议（与 `@tencent-weixin/openclaw-weixin` 对齐）长轮询收消息，将**纯文本**对话交给本机 **Cursor Agent CLI**（`agent`），再把回复发回微信。

## 安全警告

- `agent` 可执行 Shell、修改工作区文件。请勿在未配置允许列表时暴露给不可信用户。
- 生产环境请设置 **`WX_CLAW_BOT_ALLOW_FROM`**，仅允许指定的 `xxx@im.wechat` 发消息触发 Agent。

## 环境要求

- Python 3.10+（推荐 3.11+）
- 已安装 [Cursor CLI](https://www.cursor.com/docs/cli/overview)。**Windows** 若用 `irm 'https://cursor.com/install?win32=true' | iex` 安装，可执行文件常见为 **`%LOCALAPPDATA%\cursor-agent\agent.cmd`**（本程序会自动尝试该路径）。若仍失败，请设置 **`WX_CLAW_BOT_AGENT_CMD`** 为该路径的完整字符串；修改**用户/系统环境变量**后须**完全退出并重新打开终端**（或 Cursor），进程才能读到新变量。亦可使用 `%USERPROFILE%\.cursor\bin\agent.exe` 等路径。

## 安装

**推荐在虚拟环境中安装**，并先升级 pip（pip **21.x** 等旧版本极易触发依赖解析「回溯」很久，日志里会出现 `backtracking` 提示）。

```bash
cd wx-claw-bot
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
# source .venv/bin/activate

python -m pip install -U "pip>=24" setuptools wheel
pip install -e ".[dev]"
```

若不需要跑单测，只使用命令行工具时依赖更少、解析更快：

```bash
pip install -e .
```

### pip 安装很慢或一直提示 backtracking

1. **升级 pip**（优先）：`python -m pip install -U "pip>=24" setuptools wheel`
2. **换干净 venv**，不要在装满科学计算 / 旧库的全局 Python 里装本项目。
3. 仍慢可换 **uv**（解析通常更快）：`pip install uv` 后执行 `uv pip install -e ".[dev]"`（需在已激活的 venv 或指定 `--python`）。

若必须使用旧版 pip，可临时（不推荐长期使用）：`pip install -e ".[dev]" --use-deprecated=legacy-resolver`

## 配置（环境变量）

| 变量 | 说明 |
|------|------|
| `WX_CLAW_BOT_STATE_DIR` | 状态目录，默认用户目录下 `.wx-claw-bot` |
| `WX_CLAW_BOT_BASE_URL` | API 基址，默认 `https://ilinkai.weixin.qq.com` |
| `WX_CLAW_BOT_AGENT_CMD` | Agent 可执行文件，默认 `agent` |
| `WX_CLAW_BOT_WORKSPACE` | 传给 `agent --workspace` 的工作区路径 |
| `WX_CLAW_BOT_AGENT_MODEL` | 可选，传给 `agent --model` |
| `WX_CLAW_BOT_AGENT_TIMEOUT_SEC` | Agent 超时秒数，默认 `600` |
| `WX_CLAW_BOT_CURSOR_PERSISTENT_SESSION` | 是否启用 Cursor Agent 持久会话（按用户复用对话上下文），默认 `true` |
| `WX_CLAW_BOT_CURSOR_RESUME_CHAT_ID_ARG` | resume 参数名（传给 Cursor CLI 用于恢复会话），默认 `--resume`；如无效可改成你当前 `agent --help` 看到的参数 |
| `WX_CLAW_BOT_ALLOW_FROM` | 逗号分隔的允许发件人 ID；**非空时**仅这些用户可触发回复 |
| `WX_CLAW_BOT_ROUTE_TAG` | 可选，请求头 `SKRouteTag`（与 OpenClaw 微信插件一致） |
| `WX_CLAW_BOT_LOG_LEVEL` | 日志级别，默认 `INFO` |
| `WX_CLAW_BOT_TERMINAL_VERBOSE` | 是否在终端打印对话与 Agent 子进程实时输出，默认 `true`；设为 `false` 可关闭 |
| `WX_CLAW_BOT_TERMINAL_MAX_INBOUND_PREVIEW` | 终端展示用户消息的最大字符数（超长时截断提示），默认 `2000` |
| `WX_CLAW_BOT_OUTBOUND_CHUNK_SIZE` | 出站文本消息每段最大字符数（微信端展示长度），默认 `1000` |

运行 `wx-claw-bot run` 时，默认会在终端依次看到：**用户消息**（过长会截断展示，但发给 Agent 的仍是全文）、**Cursor Agent 的 stdout/stderr 流**（`--print` 成功时 stdout 末尾多为 JSON）、**解析后即将发到微信的回复**。若只想减少 httpx 日志，可设 `WX_CLAW_BOT_LOG_LEVEL=WARNING`。

启用 Cursor Agent 持久会话后，会在 `WX_CLAW_BOT_STATE_DIR/cursor_agent_sessions/` 下按微信用户保存 `chat_id`（用于后续恢复会话）。

## 使用

1. 扫码登录（打开手机微信的clawbot插件扫一扫）：

   ```bash
   wx-claw-bot login
   ```

2. 启动轮询与回复：

   ```bash
   wx-claw-bot run
   ```

等价入口：`python -m wx_claw_bot login|run`

## 功能范围（当前版本）

- 文本消息入站 / 出站
- `get_updates_buf` 持久化，重启可续传
- Cursor Agent 持久会话：按微信用户保存 `chat_id`，必要时复用会话以获得上下文记忆（失败会自动回退，不影响回复）
- 媒体消息：仅回复固定提示「暂不支持媒体」
- 长回复按不超过 1000 字分段发送（可通过 `WX_CLAW_BOT_OUTBOUND_CHUNK_SIZE` 调整）