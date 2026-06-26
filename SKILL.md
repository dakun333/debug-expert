---
name: debug-expert
description: 全局错误经验库——记录本项目（及该 Claude Code 实例）历史上踩过的每一个坑。出现任何错误、异常、奇怪行为时，必须先查本 skill，避免重复排查已知问题。本 skill 由 CLAUDE.md 强制每个 session 预加载，优先级最高。
user-invocable: true
allowed-tools: []
---

# /debug-expert — 全局错误经验库（最高优先级）

**规则**：处理任何任务时，如果遇到报错、异常、网络不通、进程行为异常、工具调用失败等问题，**必须先检索本 skill**，看是否有匹配的已知坑，不要在已知问题上重复排查。

---

## 错误清单

### 1. asyncio.wait_for 超时后子进程变成孤儿，堆积不清理

- **标签**：`subprocess` `timeout` `orphan` `claude`
- **现象**：`claude.exe -p` 调用超时后，`asyncio.wait_for` 只取消 await 不杀子进程，`claude.exe` 及其派生的 `node.exe` 继续后台运行。多次超时 → 孤儿进程越积越多。如果有人用 `taskkill /IM claude.exe /F` 清理 → 会把用户正在用的其它 Claude Code 会话一起干掉。
- **根因**：`asyncio.wait_for(proc.communicate(), timeout=N)` 超时抛出 `TimeoutError`，但 `proc` 对象仍存活。如果异常分支没有显式 `proc.kill()` 或 `taskkill /PID`，子进程不会被终止。
- **修复**：在 `TimeoutError` 和 `Exception` 分支都调用 `_kill_proc_tree(proc)`，用 `taskkill /PID <pid> /T /F` 只杀本次任务的进程树（`/T` 包含它派生的 `node.exe` 等）。
- **红线**：**绝不**用 `taskkill /IM claude.exe` 或 `taskkill /IM node.exe` 按进程名群杀——这会把用户其它 Claude 会话一同干掉。永远只按 PID。
- **验证**：语法编译通过；端到端集成测试中正常超时后不再残留进程。

### 2. gh CLI 不在 Bash PATH 中

- **标签**：`gh` `PATH` `windows` `github`
- **现象**：在 Git Bash 中执行 `gh` 命令报 `command not found`。
- **根因**：`gh.exe` 安装在 `C:\Program Files\GitHub CLI\`，这个路径不在 Git Bash 的 `PATH` 里。
- **修复（两种方式）**：
  - PowerShell：`$env:Path = "C:\Program Files\GitHub CLI;" + $env:Path` 后直接执行
  - Bash：用绝对路径 `/c/Program Files/GitHub CLI/gh.exe` 或先 `export PATH="/c/Program Files/GitHub CLI:$PATH"`
- **推荐**：GitHub 操作优先在 PowerShell 中执行。

### 3. HTTPS / SSH 直连 GitHub 推送超时

- **标签**：`github` `push` `timeout` `network`
- **现象**：`git push`（SSH 端口 22）或 `gh repo create --push`（HTTPS）报 `Connection timed out after 300042 milliseconds`。
- **根因**：本机网络环境下，github.com SSH 22 端口和某些 HTTPS 路由可能不稳定。
- **修复（按优先顺序尝试）**：
  1. 用 `gh auth git-credential` 做 git credential helper，通过 HTTPS 443 推送（`git remote set-url origin https://github.com/...` 然后 `git config credential.helper "!gh auth git-credential"`）
  2. 用 oauth2 token URL 临时推送：获取 token `gh auth token`，设 remote `https://oauth2:<token>@github.com/<owner>/<repo>.git`，推送后**立即恢复**干净的 URL
- **安全注意**：token URL 方式推送后务必 `git remote set-url` 恢复干净地址，避免 token 留在配置文件里。

### 4. asyncio subprocess 大 stdout 行被缓冲区截断

- **标签**：`subprocess` `buffer` `stream-json` `claude`
- **现象**：Claude `stream-json` 输出中，某些事件行（如包含大段文本的工具结果）可能被 `asyncio.create_subprocess_exec` 的默认缓冲区截断，导致 JSON 解析失败或数据不完整。
- **根因**：`create_subprocess_exec` 的 `limit` 参数默认 **64KB**（`_winapi.PIPE_BUF`），一行超过此值会被截断。
- **修复**：创建子进程时显式设置 `limit=32 * 1024 * 1024`（32 MB），确保大事件行不被截断。
- **示例**：`await asyncio.create_subprocess_exec(*cmd, stdin=..., stdout=..., stderr=..., limit=32 * 1024 * 1024)`

### 5. PowerShell 5.1 中 `2>&1` 导致 NativeCommandError 误报

- **标签**：`powershell` `stderr` `error-handling`
- **现象**：在 PowerShell 5.1 中运行 `ssh -T git@github.com 2>&1`，即使功能正常（GitHub 返回 "Hi xxx! You've successfully authenticated"），PowerShell 仍报告 exit 1 + `NativeCommandError`。
- **根因**：PowerShell 5.1 中，将原生命令的 stderr 用 `2>&1` 重定向到 stdout 时，每一行 stderr 都会被封装为 `ErrorRecord`，导致 `$?` 被设为 `$false`。`ssh -T` 的成功信息正是写在 stderr 里的。
- **修复**：
  - 不要使用 `2>&1` 重定向原生命令的 stderr（stderr 已被工具自动捕获）
  - 判断原生命令成败用 `$LASTEXITCODE` 而非 `$?`
  - 或者在 PowerShell 7+ / pwsh 中执行（该问题在 pwsh 中已修复）

### 6. Claude Code CLI `--model` 传入不存在的模型名

- **标签**：`claude` `model` `api-error`
- **现象**：`claude -p --model claude-haiku-4-5-20251001` 返回 `API Error: 400 Invalid model name`。
- **根因**：模型 ID 硬编码了旧版本号，该项目所用的 API endpoint 不识该模型名。
- **修复**：
  - 不要硬编码模型名，始终通过环境变量 `CLAUDE_MODEL` 配置
  - 留空 `CLAUDE_MODEL` 即使用 CLI 默认模型
  - 如需指定，用 `claude --model` 查询或从 API `/v1/models` 确认可用模型名
- **原则**：模型名属于配置，不属于代码，不要在任何 `.py` 文件中硬编码。

### 7. Python 路径硬编码导致跨环境不可用

- **标签**：`python` `path` `cross-platform`
- **现象**：后台启动时用 `"C:\ProgramData\anaconda3\python.exe"` 硬编码路径，换一台机器（用 conda/miniconda/Python.org 不同安装路径）就失效。
- **根因**：Windows 各 Python 发行版安装路径不一：Anaconda `C:\ProgramData\anaconda3\`，Miniconda `%USERPROFILE%\miniconda3\`，Python.org `%LOCALAPPDATA%\Programs\Python\`。
- **修复（按优先级）**：
  1. 调试时用 `python -c "import sys; print(sys.executable)"` 确认当前 Python 路径
  2. 脚本中先 `$py = (Get-Command python -ErrorAction SilentlyContinue).Source` 动态获取
  3. 在 `.bat` 启动脚本里用 `python` 命令（依赖 PATH）而非绝对路径

### 8. Git Bash shell 与 PowerShell 的工具选择

- **标签**：`tool` `bash` `powershell` `跨环境`
- **现象**：在 Git Bash 环境中 `gh` 找不到、`ssh` 不通；切到 PowerShell 就正常。
- **根因**：Windows 上有两套 shell 环境（Git Bash / PowerShell），PATH、网络行为、环境变量各有差异。
- **原则**：
  - `gh` 操作 → 优先 **PowerShell**（`$env:Path = "...GitHub CLI;" + $env:Path`）
  - Git 操作（commit/push）→ 可在任一环境，但推送选 HTTPS+gh credential helper
  - Python → **不要**用 Bash 跑 Python（utf-8 编码可能在管道中乱码），用 PowerShell 并设 `$env:PYTHONIOENCODING='utf-8'`
  - 文件搜索 / 内容读写 → 优先用 Glob / Grep / Read / Write 工具，不要用 shell

### 9. 飞书回调 body 加密导致 JSON 解析失败

- **标签**：`feishu` `encryption` `callback`
- **现象**：飞书事件回调 POST 过来的 body 直接 `json.loads` 解析失败，或解析出的结构里找不到预期的 `event.message` 字段。
- **根因**：飞书在「事件订阅」里如果配置了 Encrypt Key，推送的 body 是加密的（`{"encrypt":"..."}`），需要先 AES 解密才能拿到真实事件。
- **修复**：
  - 检查 `encrypt` 字段是否存在 → 用 `AESCipher(ENCRYPT_KEY).decrypt_str(encrypt_str)` 解密
  - 纯文本 body 直接 `json.loads`
  - 已在 `main.py` 的 `decrypt_request()` 中实现

### 10. 飞书 callback 端点必须快速返回 200

- **标签**：`feishu` `callback` `timeout` `async`
- **现象**：飞书重复推送同一事件，日志里看到同一消息被处理多次。
- **根因**：飞书要求事件回调 endpoint 在 **1-3 秒**内返回 HTTP 200，否则认为失败并重试。如果在 callback handler 里同步做 LLM 调用（耗时几十秒），飞书会不断重试。
- **修复**：收到消息后立即 `asyncio.create_task()` 异步处理，回调端点马上返回 `{}` + 200。
- **原则**：飞书回调 handler **绝不**做同步耗时操作。

---

## 使用方式

### 遇到错误时
1. 先用本 skill 的标签和现象匹配已知坑
2. 命中 → 直接用已记录的修复方案，不要重新排查
3. 新坑 → 解决后追加到本文件末尾（含标签/现象/根因/修复/验证）

### Claude Code 调用
`/debug-expert` — 列出全部已知错误；或 `/debug-expert <关键词>` 搜索特定错误。
