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

---

## ⚡ 自动化收录规则（给 Claude 自己看的）

每完成一个任务或一组操作后，**主动回顾**是否遇到新坑，满足以下任一条件立即追加：

1. 任何报错/异常/失败经过排查才解决
2. 工具/命令的行为与预期不符，导致走了弯路
3. 环境/平台的特定行为（Windows/网络/Python 版本差异等）
4. 某个配置或参数值设置不当导致的错误

追加后**必须**：
- `C:\Users\EDY\debug-expert` → git add index → commit → push 远端
- 同步 `C:\Users\EDY\.claude\skills\debug-expert\SKILL.md`（安装副本）
- 更新 `C:\Users\EDY\.claude\CLAUDE.md` 的速查列表（如果是高频坑）

**不需要收录**：纯业务逻辑 bug、一次性笔误、已在 skill 中记录的坑。

**绝对不要等用户提醒，自己判断、自己收录。**

---

### 11. Docker 容器内 MinIO URL 浏览器不可达

- **标签**：`docker` `minio` `url` `nginx` `proxy`
- **现象**：后端返回的图片 URL 是 `http://localhost:9000/bucket/key`，浏览器从 `10.60.0.26:5173` 访问时，`localhost` 指向用户本机而非服务器，图片加载失败。
- **根因**：MinIO 在 Docker 容器内，后端用内部 endpoint 生成 URL（`localhost:9000`），浏览器无法访问 Docker 内部网络。
- **修复**：
  1. 后端 `storage.py` 返回**相对路径** `/bucket/key`
  2. 前端 nginx 添加 MinIO 代理 location：
     ```
     location /canvas-assets/ { proxy_pass http://minio:9000/canvas-assets/; }
     location /canvas-artifacts/ { proxy_pass http://minio:9000/canvas-artifacts/; }
     ```
  3. 原理：浏览器请求 `http://10.60.0.26:5173/canvas-assets/xxx` → nginx 透明转发到 MinIO 容器
- **原则**：Docker 服务间用 service name 通信，但**面向浏览器的 URL 必须走 nginx 代理**或完整外部 IP/域名。

### 12. Konva React 图片坐标飘出 Frame 不可见

- **标签**：`konva` `canvas` `coordinates` `frontend` `react`
- **现象**：上传图片后端 200 OK，MinIO URL 可访问，但图片在前端画布上不显示（「上传了 3 张图没一张显示」）。
- **根因**：图片 transform 的 `cx/cy` 硬编码为 `{cx:600, cy:450}`，对于 width=1920 的大图，`imgX = cx - width/2 = 600-960 = -360`，图片被推到 Frame 可视范围之外。
- **修复**：
  1. 图片 `cx` 设为 Frame 中心：`cx = frameWidth / 2`
  2. 图片自适应缩放：`scale = Math.min(maxW / imgW, maxH / imgH, 1)`
  3. Frame Group **必须设置 x/y 定位**（Frame 左上角），子元素坐标相对 Group 内部
- **原则**：Canvas 中**子元素坐标始终相对于父容器左上角**，不要硬编码绝对像素值，大图必须先计算缩放因子。

### 13. nginx 默认 body 大小限制导致大图上传 413

- **标签**：`nginx` `upload` `413` `client_max_body_size`
- **现象**：用户上传较大图片（>1MB）时浏览器报 413 Request Entity Too Large。
- **根因**：nginx 默认 `client_max_body_size 1m`，超过 1MB 的图片直接拒绝。
- **修复**：nginx.conf 添加 `client_max_body_size 50m;`（server 级别 + `/api/` location 级别都加）。
- **原则**：任何走 nginx 代理的文件上传路径，必须在上线前调整 body 大小限制。

### 14. YAML 缩进错误导致 docker-compose 服务解析失败

- **标签**：`docker-compose` `yaml` `validation`
- **现象**：`docker-compose config --services` 报错 `Additional property environment is not allowed`，服务定义被错误解析到 `volumes` 顶级键下。
- **根因**：用 `cat >> file << 'EOF'` 追加 YAML 内容时，行首缩进与已有内容不一致，YAML 解析器把新服务的键值对绑到了错误的父级下。
- **修复**：不要用 shell heredoc 追加 YAML，用 Python `yaml.dump()` 来修改：
  ```python
  import yaml
  with open("docker-compose.yml") as f:
      d = yaml.safe_load(f)
  d["services"]["new-service"] = {...}
  with open("docker-compose.yml", "w") as f:
      yaml.dump(d, f, default_flow_style=False, sort_keys=False)
  ```
- **原则**：YAML 对缩进极度敏感，任何结构修改都通过 `yaml.safe_load` + `yaml.dump` 闭环，不要手写或 shell 拼接。修改后立即 `docker-compose config` 验证。

### 15. React Konva `onRef` 回调中调用 `setState` 导致 React #185 死循环

- **标签**：`react-konva` `onRef` `React185` `setState`
- **现象**：浏览器报 `Minified React error #185`，页面白屏。
- **根因**：Konva `onRef` 在 render 阶段调用，`onRef` 中 `setImageRefs((prev) => ({...}))` 触发渲染期间 setState → 无限重渲染崩溃。
- **修复**：State → useRef：`const imageRefs = useRef({})`，`onRef` 中直接赋值 `imageRefs.current[id] = node`。
- **原则**：Konva `onRef`/`ref` 回调禁止 `setState`，必须用 `useRef`。

### 16. Konva `getAbsoluteTransform().getScale()` 不存在

- **标签**：`konva` `api` `getAbsoluteScale`
- **现象**：`TypeError: getAbsoluteTransform(...).getScale is not a function`。
- **修复**：`node.getAbsoluteScale().x / node.getAbsoluteScale().y`
- **原则**：Konva scale 用 `node.scaleX()/scaleY()`（相对）或 `node.getAbsoluteScale()`（绝对）。

### 17. Docker 构建缓存导致旧文件持续部署

- **标签**：`docker` `build-cache` `vite` `frontend`
- **现象**：源码更新后 `docker-compose up -d --build` 仍使用旧 bundle，新功能不生效。
- **根因**：Docker `COPY package.json .` + `RUN npm install` 层被缓存，后面 `COPY . .` 和 `RUN vite build` 即使源码变了也复用旧层。
- **修复**：
  1. `docker-compose build --no-cache frontend` 强制重建
  2. 或先删除旧镜像 `docker rmi -f docker-frontend`
  3. 绝对不用 `docker cp` / `docker run --mount` 绕过构建流程
- **原则**：前端更新必须走 `docker-compose build --no-cache` 或先删镜像，不允许手动拷贝文件进容器。

### 18. MCP 服务器接入：完整操作流程与常见坑

- **标签**：`mcp` `plugin` `playwright` `.mcp.json` `.claude.json`
- **版本**：Claude Code v2.1.195（2026-06）

#### 配置文件优先级与位置

Claude Code v2.1.x 的 MCP 配置存在**两个位置**，会合并加载：

| 文件 | 路径 | 用途 |
|------|------|------|
| `.mcp.json` | `<工作目录>/.mcp.json`（如 `D:\.mcp.json`） | 项目级声明，**需用户批准** |
| `.claude.json` | `C:\Users\<用户名>\.claude.json` → `projects["<路径>"].mcpServers` | CLI `mcp add` 写入的实际生效位置 |

**关键坑**：`.mcp.json` 中的服务器必须经过用户批准才会连接。如果之前被拒绝过，会进入 `disabledMcpjsonServers` 列表，即使 `.mcp.json` 内容正确也不会生效。

#### 接入新 MCP 的正确流程

1. **用 CLI 添加**（推荐，一步到位）：
   ```
   claude mcp add <名称> -- <命令> [args...]
   ```
   示例：`claude mcp add playwright -- npx @playwright/mcp@latest`
   这会把配置写入 `.claude.json` 的 `projects["当前路径"].mcpServers`，**立即生效**。

2. **或手动编辑 `.mcp.json`**（需要额外批准步骤）：
   - 编辑 `<工作目录>/.mcp.json`
   - 重启 Claude Code → 会提示「New MCP server detected, approve?」
   - 如果看不到提示 → 可能之前被拒绝了，运行 `claude mcp reset-project-choices`

3. **从插件市场安装的 MCP**：
   - 插件只把 `.mcp.json` 写入 `~/.claude/plugins/marketplaces/.../` 插件目录
   - 不会自动合并到工作目录的 `.mcp.json` 或 `.claude.json`
   - **必须**手动执行步骤 1 或 2

#### 诊断命令

```
claude mcp list                        # 列出所有已连接的 MCP 服务器
claude mcp get <名称>                   # 查看某个服务器的详细状态
claude mcp reset-project-choices       # 重置项目的 .mcp.json 批准/拒绝状态
```

#### Playwright MCP 额外注意事项

- MCP 服务器（`npx @playwright/mcp@latest`）和 Playwright 浏览器是**分开的**
- 浏览器需要手动安装：`npx playwright install chromium`
- 浏览器安装可能因网络问题失败（`cdn.playwright.dev` TLS 连接被重置 → 多试几次）
- 安装后浏览器放在 `%LOCALAPPDATA%\ms-playwright\`

#### 验证 MCP 是否可用

在会话中调用 `ListMcpResourcesTool` 或直接尝试使用该 MCP 的工具。注意：**MCP 在 session 启动时加载**，修复配置后必须重启 Claude Code 才会生效。

### 19. 钉钉文档：keyboard.type() 无法创建 Markdown 表格，必须用 Ctrl+V 粘贴

- **标签**：`dingtalk` `钉钉` `markdown` `表格` `playwright`
- **现象**：用 Playwright `keyboard.type()` 逐字符输入 MD 内容到钉钉文档编辑器，`|...|` 表格分隔行被当作文本，所有后续内容挤进一个单元格。多行内容容易丢失。
- **根因**：
  1. 钉钉编辑器的 Markdown 表格解析器需要**整体内容**才能识别表格结构，`keyboard.type()` 逐字符输入不触发表格解析
  2. `keyboard.type()` 中的 `\n` 不是真正的 Enter 按键事件，编辑器不识别为换行
  3. 钉钉编辑器有约 40 行的实时输入缓冲区，超过会丢弃前面内容
  4. 钉钉编辑器使用虚拟滚动，Playwright 的 `locator()` 只能查到可见 DOM 元素（内容没丢只是不在视口）
- **修复**：
  1. **用 `Ctrl+V` 粘贴 MD 纯文本**（非 HTML！），钉钉编辑器会自动识别并转换 Markdown + 表格
  2. 流程：PowerShell 复制 MD 到剪贴板 → MCP Playwright 打开文档 → 编辑模式 → 全选清空 → Ctrl+V → 等 8 秒解析
  3. 验证时先 `Ctrl+Home` 回到顶部再检查标题
  4. 单次粘贴上限约 4000-5000 字符，超长文档需要分段
- **禁止操作**：
  - ❌ 用 `keyboard.type(md, delay=0)` 输入含表格的 MD
  - ❌ 把 `\n` 嵌入 `keyboard.type()` 字符串期望换行
  - ❌ 用 HTML 格式剪贴板（CF_HTML）粘贴
- **参考**：`D:\project\2026\dingtalk_md_sync_方法总结.md`、`C:\Users\EDY\.claude\projects\D--\memory\dingtalk-md-sync.md`

### 20. 🚫 禁止为解决一个问题删除/牺牲已有功能

- **标签**：`原则` `功能回退` `禁止` `最高优先级`
- **现象**：开发中遇到某个参数（如 Ollama 的 `options.num_predict`）导致空响应，直接把整个 options 功能删掉。
- **根因**：遇到问题时，条件反射式地"去掉导致问题的东西"，而不是找到既能保留功能又不触发问题的方案。
- **修复原则**：
  1. 先查文档、测试不同参数值，找到问题的精确根因
  2. 保留功能的完整性，只修改触发问题的具体参数值
  3. 如果不能直接解决，找替代方案（如 Ollama 用 `num_predict=512` 而非 256 或 0）
- **验证**：改动后确认所有原有功能仍可用，不是"功能少了但问题没了"。
- **红线**：任何改动不得以牺牲已有功能为代价。想不出保留功能的方案 → 停下、查文档、问用户。

### 20. ArXiv API HTTP → HTTPS 301 重定向

- **标签**：`arxiv` `api` `http` `301`
- **现象**：用 `http://export.arxiv.org/api/query` 请求返回 301 Moved Permanently，feedparser 解析为空。
- **根因**：ArXiv 已将所有 API 流量强制迁移到 HTTPS。
- **修复**：所有 ArXiv API 调用使用 `https://export.arxiv.org/api/query`。

### 21. Claude CLI 非交互模式子进程调用的坑

- **标签**：`claude` `subprocess` `non-interactive` `DEVNULL`
- **现象**：
  1. Claude CLI `--no-interactive-stdin` 标志在 v2.1.201 中**不存在**，传入会报 `error: unknown option`
  2. 不传 stdin 时 CLI 会等待 3 秒才继续（`Warning: no stdin data received in 3s`），但不影响输出
  3. 定时任务中 Claude CLI 使用 WebSearch/WebFetch 需要用户交互审批 → 阻塞
- **修复**：
  1. 使用 `stdin=subprocess.DEVNULL` 重定向 stdin（不是 `--no-interactive-stdin` 标志）
  2. 加 `--dangerously-skip-permissions` 跳过所有权限检查（仅限可信的定时脚本）
  3. stderr 中的 `Warning:` 不视为错误，正常处理 stdout 输出
- **示例**：
  ```python
  proc = await subprocess.create_subprocess_exec(
      claude_path, "-p", prompt, "--dangerously-skip-permissions",
      stdin=subprocess.DEVNULL,
      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      limit=32 * 1024 * 1024,
  )
  ```

### 22. 飞书文本消息 4000 字符限制

- **标签**：`feishu` `message` `limit` `split`
- **现象**：超长文本通过飞书 `im/v1/messages` 发送可能被截断或失败。
- **修复**：超过 3800 字符时分段发送，在 `\n` 处自然断开，段间间隔 1 秒。

### 23. LLM `max_tokens` 不足导致批量摘要 JSON 被截断 → digest 变成英文原文

- **标签**：`llm` `max_tokens` `truncation` `json` `日报`
- **现象**：AI 日报中，前 10 篇论文有规范的中文精炼摘要（📝做什么/💡创新点/📊效果/🔓开源），但后 10 篇的 digest 只有 `📝 ` 后面跟了截断的原始英文摘要前 100 字符，缺少结构化信息。同时日志中可能有 `摘要 JSON 解析失败` 的 warning。
- **根因**：`summarize_papers()` 每批 10 篇论文，`max_tokens=4096`。10 篇中文摘要（每篇约 120 字 + JSON 结构开销）输出量接近或超过 4096 tokens → LLM 输出被截断（`finish_reason=length`）→ JSON 数组不完整（缺少 `]` 或中间截断）→ 正则/JSON 解析失败 → 走了 fallback 逻辑，直接用 `p.get('summary', '暂无摘要')[:100]` 即英文原文前 100 字作为 digest。
- **为什么第一批 10 篇通常没问题**：不同论文的摘要长度有波动，第一批恰好没超过 4096 tokens，第二批加上累计的随机性可能超出。这是间歇性 bug，不是每次必现。
- **修复（3 层防护）**：
  1. **增大 `max_tokens`**：从 4096 → 16384（论文摘要），从 2048 → 8192（新闻摘要），确保批量输出不被截断
  2. **添加 `finish_reason` 检测**：当 `finish_reason == "length"` 时输出 warning，便于监控
  3. **添加逐条恢复 fallback**：当完整 JSON 数组解析失败时，用正则逐个匹配 `{"idx": N, "digest": "..."}` 对象单独提取，最大限度恢复数据
- **涉及文件**：`C:\Users\EDY\feishu-bot\ai_daily_report.py` — `summarize_papers()` 和 `summarize_news()` 函数
- **教训**：批处理调用 LLM 时，`max_tokens` 必须根据批量大小乘以单条输出预估来计算，不能只按「感觉够用」来设。10 篇 × 150 字中文 × 3 tokens/字 ≈ 4500 tokens，加上 JSON 格式开销和 prompt 说明，至少需要 6000-8000 tokens 才安全。

### 24. deploy.sh 在远程服务器失败：`docker compose`（无横杠）命令不存在 + 本地无 rsync

- **标签**：`deploy` `docker-compose` `rsync` `windows` `远程部署`
- **项目**：`D:\project\2026\hungry_arit\ollama_vlm_benchmark\deploy.sh` → 远程 `root@10.60.0.26:/opt/ollama_vlm_benchmark`
- **现象**：直接跑 `deploy.sh` 部署失败，两个独立问题：
  1. 本地 Git Bash 报 `rsync: command not found` —— Windows Git Bash 默认不带 rsync
  2. 远程 `docker compose version` 报 `docker: unknown command: docker compose` —— 远程 docker 老版本不认 v2 插件语法
- **根因**：
  1. `deploy.sh` 用 `rsync` 同步代码，但 Windows Git Bash 环境无 rsync（参见 #8 两套 shell 差异）
  2. `deploy.sh` 写的是 `docker compose`（v2 插件，无横杠），远程服务器只装了 `docker-compose`（v1 风格，带横杠）。注意：远程 `docker-compose` 实际版本可能是 v2.32.0（新版本号但旧命令名），**命令名必须带横杠**
- **修复**：
  1. **不用 rsync**，改用 `tar | ssh` 管道传文件（Git Bash 自带 tar）：
     ```bash
     cd 项目根目录
     tar --exclude='node_modules' --exclude='dist' -czf - -C frontend . \
       | ssh root@10.60.0.26 "mkdir -p /opt/xxx/frontend && cd /opt/xxx/frontend && tar -xzf -"
     ```
  2. **远程用 `docker-compose`（带横杠）**，不用 `docker compose`：
     ```bash
     ssh root@10.60.0.26 "cd /opt/xxx && docker-compose build --no-cache frontend && docker-compose up -d frontend"
     ```
- **只改前端时别用完整 deploy.sh**：`deploy.sh` 会 `docker compose build --no-cache`（无 `--no-cache` 只针对某服务时会重建全部）+ 重启所有服务，导致 backend 重新加载 vLLM 24GB 权重（几十秒~两分钟）。**只改前端时，只重建 frontend 服务**，backend/ollama 保持不动。
- **原则**：
  - 部署前先 `ssh` 探测远程：`docker-compose version`（带横杠）、`docker compose version`（无横杠）哪个能用
  - Windows 本地传文件优先 `tar | ssh`，不依赖 rsync
  - 增量部署：改哪个服务只重建哪个，避免无谓的 vLLM 重载
- **验证**：远程 `docker exec frontend容器 ls /usr/share/nginx/html/assets/` 看到 bundle hash 与本地 `npm run build` 产出的 hash 一致，`curl http://localhost/` 返回 200 且引用新 bundle。

### 25. 只重建 frontend 服务时不影响 backend（vLLM 不重载）

- **标签**：`deploy` `docker-compose` `vllm` `增量部署`
- **现象**：改前端 UI 后部署，担心 `docker-compose up -d` 会让 backend 容器重启 → 本地 vLLM 引擎重新加载 Qwen3.6-35B-A3B-AWQ（22GB 显存权重，加载耗时 30s~2min），期间识别接口不可用。
- **根因**：`docker-compose up -d <服务名>` 只会重建/重启**指定服务**及其依赖。frontend 不依赖 backend（docker-compose.yml 里 frontend `depends_on: backend`，但 backend 不依赖 frontend），所以单独 `up -d frontend` 不会动 backend。
- **验证**：部署前后 `docker ps` 看 backend 容器的 `Status` 的 `Up X days` 不变（没重启），`docker logs backend --tail 5` 无 `[vLLM] 开始加载` 日志。
- **原则**：docker-compose 增量部署时，`up -d <服务名>` 是安全的，只动该服务。但 `build --no-cache` 不带服务名会重建全部镜像（慢），**务必带服务名** `docker-compose build --no-cache frontend`。

### 27. nginx 不给 index.html 设 no-cache，浏览器缓存旧版导致部署"不生效"

- **标签**：`nginx` `cache` `index.html` `前端部署` `浏览器缓存`
- **现象**：远程容器里文件是最新的（`docker exec` 查 JS bundle hash 正确），`curl` 返回的 index.html 引用的也是新 bundle。但用户浏览器里**始终是旧版**——功能不生效、字体没变小。用户清缓存、开无痕窗口都不行（因为 nginx 没设 no-cache，浏览器默认缓存 index.html）。
- **根因**：nginx 默认不给 `index.html` 设 `Cache-Control` 头。虽然 Vite 给 assets 文件名带 hash（`index-Abc123.js`），但 `index.html` 本身没 hash——浏览器缓存了旧的 `index.html`，它引用的旧 bundle hash 已被 `rm -rf assets/*` 删除，浏览器加载的还是旧代码或 404 后 fallback。
- **修复**：nginx 配置加 `location = /index.html { add_header Cache-Control "no-cache, no-store, must-revalidate"; }`。assets 可保持长缓存（hash 变了自动失效）。
- **教训**：前端部署后只验证 `curl` 返回 200 +正确 hash 是**不够的**——还要确保浏览器不会缓存 `index.html`。这是部署验证的必要步骤，不是可选步骤。

### 28. contenteditable chip 的 ⌄ 按钮只在创建时添加，状态转换后丢失（状态转换遗漏 bug）

- **标签**：`contenteditable` `chip` `状态转换` `DOM 重建` `前端`
- **项目**：`D:\project\2026\hungry_arit\ollama_vlm_benchmark\frontend\src\App.tsx`
- **现象**：contenteditable 编辑器里的词条 chip 应该有 ⌄ 按钮点开下拉列表。但所有 chip 都**没有 ⌄ 按钮**，截图直接暴露了这个问题。
- **根因**：⌄ 按钮只在 chip **首次创建**时添加（`if (!el)` 分支），但 chip 创建时 marker 处于 `busy`（识别中）状态，`if (!m.busy && !m.error)` 为 false，跳过了添加 ⌄。等识别完成 marker 变成 ready，chip 已存在走 `else` 分支只更新文字内容，**永远不补 ⌄ 按钮**。
- **这是一个"状态转换遗漏"bug**：只考虑了创建时的静态状态，没有考虑 `busy → ready` 的动态转换。创建时 busy → 没 ⌄；转换后 ready → 也没人补 ⌄。
- **修复**：把 ⌄ 按钮的添加从"创建时一次性"改为"每次更新都检查"：
  ```js
  // 每次 renderEditorChips 都检查
  const hasArrow = el.querySelector('.chip-arrow')
  if (!m.busy && !m.error && !hasArrow) {
    // 补上 ⌄ 按钮
  }
  if ((m.busy || m.error) && hasArrow) {
    hasArrow.remove()  // busy/error 时移除
  }
  ```
- **教训**：
  1. 动态状态（busy→ready、loading→done）的 UI 元素，**不能只在创建时一次性决定渲染什么**，必须每次更新都检查"当前状态应该有什么、缺什么就补、多了就删"
  2. 用户说"没有下拉"时，应该**第一时间看实际渲染的 DOM**（截图/远程检查），而不是猜代码逻辑。我在这个问题上猜了 3 轮（先猜时序、再猜缓存、最后才看截图发现 ⌄ 根本不存在）

### 29. ⌄ 按钮 click + setTimeout mousedown 时序冲突，下拉"出现就消失"

- **标签**：`contenteditable` `事件时序` `mousedown` `click` `下拉列表`
- **现象**：点 ⌄ 按钮展开下拉列表，下拉"出现了一瞬间又消失"。第三个 chip 尤其明显。
- **根因**：⌄ 按钮用 `click` 事件打开下拉，同时 `setTimeout(() => { document.addEventListener('mousedown', onDown) }, 0)` 注册外部关闭监听器。但**点击 ⌄ 按钮的 mousedown 事件先于 click 触发**，冒泡到 document 时 `setTimeout` 里的监听器可能已注册（或时序接近），判定 `dd.contains(target)` 为 false（⌄ 按钮不在下拉容器里），**立即关闭了刚打开的下拉**。
- **修复**：
  1. ⌄ 按钮加 `mousedown` 事件 `e.stopPropagation()`，在 mousedown 阶段就拦住冒泡
  2. `setTimeout` → `requestAnimationFrame`，更可靠的延迟
  3. 外部关闭判断排除 `.chip-arrow`：`!(ev.target).closest('.chip-arrow')`
- **教训**：`click` + `setTimeout(mousedown)` 的组合有时序竞争。如果需要"点按钮打开浮层 + 点外部关闭"，按钮本身必须在 `mousedown` 阶段 `stopPropagation`，否则打开和关闭会打架。

### 30. 改造交互方案时丢旧功能（contenteditable 改造丢了下拉列表）

- **标签**：`改造` `功能丢失` `contenteditable` `红线`
- **现象**：把 textarea + 标签区改造成 contenteditable 富文本编辑器后，词条的**下拉列表功能整个丢了**（切换/编辑/添加/删除词条）。chip 变成了纯文本，没法操作词条。
- **根因**：改造时只关注新功能（contenteditable 整体删除），没列旧功能清单逐个确认新方案保留。EditableSelect 组件的代码虽然还在，但渲染位置从"独立标签区"移到了 contenteditable 内部，而 contenteditable 内部不能直接渲染 React 组件，导致功能丢失。
- **教训**：
  1. **改造前先列旧功能清单**，逐个确认新方案如何保留
  2. 改造后**逐个验证旧功能**，而不是只测新功能
  3. 这违反了 debug-expert 红线 #20（禁止为解决问题牺牲已有功能）的变体——不是主动牺牲，而是改造时遗漏

### 31. 部署后只验证 HTTP 200，没验证核心交互功能

- **标签**`部署验证` `功能验证` `前端`
- **现象**：多次部署后只 `curl` 验证 HTTP 200 + bundle hash 正确，就报告"部署完成"。但用户打开浏览器发现功能不生效。
- **根因**：部署验证只检查了"文件到位"，没检查"功能正常"。HTTP 200 只说明 nginx 在服务文件，不说明 JS 代码逻辑正确、DOM 渲染正确。
- **修复**：部署后验证清单应包括：
  1. ✅ HTTP 200 + bundle hash（文件到位）
  2. ✅ index.html 有 no-cache 头（浏览器不缓存旧版）
  3. ✅ 核心交互功能可用（如果有条件用 Playwright/curl 验证 DOM 结构）
- **教训**：部署验证 ≠ 文件验证。"部署完成"的判定标准必须是"功能可用"，不是"文件到位"。

### 26. docker cp 覆盖 nginx html 不删旧 assets，残留旧 bundle

- **标签**：`deploy` `docker-cp` `nginx` `vite` `前端增量`
- **项目**：`D:\project\2026\hungry_arit\ollama_vlm_benchmark\frontend` → 远程 `root@10.60.0.26` 容器 `ollama_vlm_benchmark-frontend-1`
- **现象**：纯前端 UI 改动，本地 `npm run build` 后用 `tar|ssh` 传 dist 到远程，再 `docker cp /tmp/fe_new/. <容器>:/usr/share/nginx/html/` + `nginx -s reload`。页面 200 OK、index.html 引用新 bundle，但容器 `assets/` 里**同时存在新旧两个 bundle**（如 `index-0DUtWkTw.js` 新 + `index-DL8nbbnM.js` 旧）。
- **根因**：`docker cp` 是**覆盖/新增**语义，不删除目标目录里源目录没有的文件。Vite 每次 build 生成 content-hash 文件名（`index-<hash>.js`），新 build 的 hash 与旧的不同 → 旧 bundle 永远不会被 cp 删除，逐次堆积。index.html 虽已指向新 hash，但旧文件残留占用空间、且易误导排查（以为还在用旧版）。
- **修复**：cp 后手动删旧 bundle，或先清空 assets 再 cp：
  ```bash
  # 方式 A：删旧 hash 文件（保留 index.html 已引用的）
  docker exec <容器> sh -c 'rm -f /usr/share/nginx/html/assets/index-*.js /usr/share/nginx/html/assets/index-*.css'
  docker cp /tmp/fe_new/. <容器>:/usr/share/nginx/html/
  # 方式 B：先清空整个 html 再 cp（更彻底）
  docker exec <容器> sh -c 'rm -rf /usr/share/nginx/html/*'
  docker cp /tmp/fe_new/. <容器>:/usr/share/nginx/html/
  docker exec <容器> nginx -s reload
  ```
- **验证**：`docker exec <容器> ls /usr/share/nginx/html/assets/` 只剩新 hash；`curl http://localhost/ | grep -o 'index-[A-Za-z0-9]*.js'` 与本地 `dist/assets/` 文件名一致。
- **原则**：用 `docker cp` 增量更新 hash 命名的静态资源时，**必须先清理旧 assets**，否则旧 bundle 永久残留。这条与 #17（docker build 缓存）互补：#17 讲 build 层缓存，本条讲 cp 不删除旧文件。

### 28. Windows 环境下 Bash 的 `/tmp` 路径可能被 Python 解释为 `\\tmp`

- **标签**：`windows` `bash` `tmp` `python` `路径`
- **现象**：通过 Bash 工具执行 `curl -o /tmp/file` 后，后续 Windows Python 读取 `Path('/tmp/file')` 报 `FileNotFoundError`，实际 Python 将 `/tmp/file` 解析成了 `\\tmp\\file`。
- **根因**：当前 Bash 调用链实际使用 Windows Python/文件系统语义，POSIX `/tmp` 不一定对应 Bash 的临时目录。
- **修复**：跨工具传递临时文件时使用 Windows 可访问的绝对路径，或避免落盘，直接通过管道传给 Python；验证路径时先检查 `python -c "import tempfile; print(tempfile.gettempdir())"`。
- **验证**：远程部署和 API 验证改用管道/HTTP 响应，不再依赖 `/tmp` 文件读取。

### 29. Docker backend 的公网 VLM 出站网络可能与本地电脑不同

- **标签**：`docker` `httpx` `ConnectError` `remote-vlm` `network`
- **现象**：本地电脑请求 `http://212.64.83.107:8686/v1/models` 成功，但 `10.60.0.26` 上的 backend 容器请求同一地址失败，日志出现 `httpx.ConnectError: All connection attempts failed`，前端切换远程模型后识别接口返回 500。
- **根因**：远程 VLM 的网络可达性是分环境的；部署服务器到目标公网 IP/端口可能没有出站路由、防火墙或安全组放行。不是模型名、图片格式或前端下拉框问题。
- **修复**：必须在部署服务器宿主机和 backend 容器内分别测试目标地址；若不可达，放行出站 TCP 8686 或配置路由。业务层应将连接异常转换为明确的 502。
- **验证**：本次 `10.60.0.26` backend 日志确认异常发生在 `RemoteVLMClient._chat_completion()` HTTP 连接阶段；服务器请求 `http://212.64.83.107:8686/v1/models` 超时，而本地请求成功。

### 30. 远程模型 ready 不能仅由静态配置决定

- **标签**：`remote-vlm` `health` `ready` `model-list`
- **现象**：模型列表中远程模型显示 ready，但实际点击请求因远程服务不可达返回 500。
- **根因**：模型列表把远程模型存在配置中直接当成已就绪，没有使用 `/v1/models` 健康探测结果。
- **修复**：ready 应来自远程健康探测；健康失败时显示不可用，warmup 返回 503，业务调用把底层连接异常转换为明确的 502。
- **验证**：本次 `/api/health` 返回 `remote_vlm=disconnected`，点击请求日志为 `httpx.ConnectError`。

### 31. vLLM 重启后的首次请求包含 lazy JIT 编译延迟，不能当稳定性能

- **标签**：`vllm` `JIT` `Triton` `冷启动` `性能`
- **现象**：增加 API 模型或修改 backend 后重启服务，用户感觉本地 Qwen3.6 速度明显变慢；服务日志出现 Triton kernel JIT compilation during inference。首次请求可能明显慢于后续请求。
- **根因**：backend 重启会重新加载 24GB 权重、torch.compile、CUDA graph，并且部分视觉/MoE/采样 kernel 按首次输入形状延迟编译。部署后的前几次请求包含模型冷启动和 lazy JIT 成本。
- **修复**：部署后等待本地 vLLM `ready=true`，再执行与真实图片/输入形状一致的预热请求；性能对比必须区分冷启动、首次 JIT 和稳定态，不要为解决冷启动删除已有 vLLM 功能。
- **验证**：本次日志记录 `init engine ... took 101.20 s`，随后出现 `_bilinear_pos_embed_kernel`、`fused_moe_kernel`、`rotary_kernel` 等首次推理 JIT；稳定单请求复测 `server_vlm=845.9ms`。

### 32. vLLM offline LLM.chat 的串行锁造成并发请求排队

- **标签**：`vllm` `LLM.chat` `threading.Lock` `并发` `排队`
- **现象**：单请求本地 VLM 约 846ms，但 10 并发时平均约 5738ms、P95 约 9150ms，用户会感知点击结果变慢。
- **根因**：为避免历史 vLLM offline `LLM.chat` 并发死锁，代码使用 `threading.Lock` 包住 `self._llm.chat()`；多个点击请求虽然并发进入 FastAPI，但实际推理串行排队。
- **修复**：保留锁直到有经过验证的 vLLM batch/AsyncLLMEngine 替代方案；不要直接删除锁。优化应单独设计并发调度和批处理，并做稳定性回归。
- **验证**：本地模型路由仍是 `qwen3.6:35b -> local_vllm -> QuantTrio/Qwen3.6-35B-A3B-AWQ`，没有切到 Ollama 或远程 API；单请求 845.9ms，10 并发整体约 10.7s。

### 33. React 异步回调用闭包捕获的旧序号，导致标记点序号与 UI 显示错位

- **标签**：`react` `闭包` `时序` `marker` `序号` `多图`
- **项目**：`D:\project\2026\hungry_arit_remote_tagging_service\local_app\frontend\src\MultiImageWorkspace.tsx`
- **现象**：多图场景快速连续添加标记点后，某标记点（如图片2的5号）识别结果与点击位置不对应；之前无论多少张图序号都正常。
- **根因**：`finishPointer()` 里 `setImages(renumberImages(...))` 是异步更新 state，随后 `await requestMarkerRecognition(image, marker, ...)` 用的是**闭包捕获的旧 marker**，其 `marker.index` 是添加前算的旧值。`renumberImages` 在 state 更新时重新全局编号；若中间有 marker 增删/图片移动，闭包旧 index 与新 UI 序号不一致。A 收到的 `marker_index` 是旧值，导致识别与位置错位。
- **加重因素**：基线有 `image.taggingStatus !== 'ready'` 守卫（等 A asset ready 才允许打标，天然序列化）；本次改为前端开关 `taggingEnabled` 后移除了 ready 等待，快速连点更容易触发。
- **修复**：在 `requestMarkerRecognition` 函数内**从最新 state 读取该 marker 的最新 index**（`images.flatMap(...).find(id)`），而不是用闭包旧 `marker.index`，再传给 A 的 `marker_index`。
- **验证**：快速连续添加多个标记点，A 返回的 marker_index 与 UI 显示序号一致。
- **教训**：异步回调（setState + await）中，凡是要传给下游/后端的数据，必须从最新 state 读取，不能用闭包捕获的旧对象字段。

### 34. 改动一个功能时，除非明确相关功能需要修改，否则禁止改动其他已确定功能

- **标签**：`原则` `功能边界` `最小改动` `回归`
- **现象**：为「直连 A 打标」改造时，移除了既有功能中的 `taggingStatus !== 'ready'` 守卫（改成前端开关），导致标记点序号时序 bug 被触发；该守卫属于「打标就绪等待」这一既有确定功能，本不需要为本次任务修改。
- **根因**：完成任务时条件反射式地修改了「看起来相关」的既有逻辑，没有先判断该逻辑是否属于本次需求范围。序号/就绪等待是已确定功能，改动它超出了任务边界。
- **修复原则**：
  1. 改功能前**列出现有功能清单**，明确本次要改哪些、哪些不动。
  2. 除非本次需求明确要求修改某既有功能，否则**禁止改动**它。
  3. 若觉得既有设计不合理，**先提出来和用户讨论**，不擅自改。
  4. 改动后**回归验证所有既有功能**，不只测新功能。
- **验证**：本次序号 bug 修复后，多图序号、打标、详情全部回归正常。
- **红线**：任何改动不得以牺牲既有功能为代价；想保留功能又想改 → 先讨论再动手。

### 35. FastAPI TestClient 多个会话复用模块级 asyncio.Queue/Event → "bound to a different event loop"

- **标签**：`fastapi` `testclient` `asyncio` `event-loop` `queue` `pytest`
- **现象**：在 Server A（FastAPI + pytest）里给模块级单例增加 asyncio 后台 worker（asyncio.Queue + worker task + asyncio.Event 监控循环）。多个测试函数各开 `with TestClient(app)` 会话，第二个会话起报 `RuntimeError: <Queue at 0x..> is bound to a different event loop` / `<asyncio.locks.Event object ...> is bound to a different event loop`，后台 task 报 `Task exception was never retrieved`。
- **根因**：asyncio.Queue / asyncio.Event / asyncio.Lock 在 Python 3.10+ 是"首次在某个事件循环中被 await 时绑定"；TestClient 每个会话都跑独立的 portal 事件循环。模块级单例的 Queue/Event 一旦被第一个会话绑定，第二个会话复用时跨 loop 崩溃。
- **修复**：单例的 `start()` 必须**每次重建** Queue/Event（并取消旧 task、关闭旧连接），再绑定当前运行循环：
  ```python
  def start(self):
      old = self._worker_task
      self._worker_task = None
      if old and not old.done():
          old.cancel()
      # 关闭旧 sqlite/redis 连接
      self._queue = asyncio.Queue(maxsize=self.max_queue)   # 重建！
      self._stop = asyncio.Event()                          # 重建！
      self._worker_task = asyncio.create_task(self._run_worker())
  ```
- **验证**：整库 23 个测试（含多个 TestClient 会话）全部通过，无 bound-to-loop 报错。
- **教训**：模块级单例承载 asyncio 原语 + 多 TestClient/pytest 场景，生命周期必须支持跨循环重建；不要假设 Queue/Event 可跨事件循环复用。

### 36. FastAPI `request.form()` 返回 starlette 的 UploadFile，不是 fastapi.UploadFile

- **标签**：`fastapi` `uploadfile` `request.form` `isinstance` `multipart`
- **现象**：在 FastAPI 端点里 `form = await request.form()` 后遍历 `form.keys()`，用 `isinstance(value, UploadFile)`（从 `fastapi` import）判断文件字段，结果**永远为 False**，multipart 里的图片文件全部被当成普通字段漏掉 → 后续报「缺少文件」。
- **根因**：`fastapi.UploadFile` 是 `starlette.datastructures.UploadFile` 的**子类**（`issubclass(FU, SU)=True`），但 `request.form()` 返回的是 **starlette** 的实例，`isinstance(starlette实例, fastapi.UploadFile)` 为 False（反向不成立）。这是继承方向问题：用子类去 isinstance 基类实例永远不通过。
- **修复**：不要依赖 `isinstance(value, fastapi.UploadFile)`，用鸭子类型判断（`hasattr(value, "filename") and hasattr(value, "read")`）或对 `starlette.datastructures.UploadFile` 做 isinstance。
- **验证**：改成鸭子类型后，multipart 中 `payload` JSON + `marked_1` 图片都能被正确识别；Server A 的 `/api/v1/multi/workflow` 端点测试通过。
- **教训**：`request.form()` 返回的 UploadFile 用 `from fastapi import UploadFile` 做 isinstance 是常见误判；文件字段识别用鸭子类型最稳。

### 37. pnpm 11 `ERR_PNPM_IGNORED_BUILDS`：`pnpm dev` 启动失败，且自动注入 allowBuilds 污染 pnpm-workspace.yaml

- **标签**：`pnpm` `ignored-builds` `vite` `git污染` `pnpm-workspace.yaml`
- **项目**：`D:\project\2026\gitlab\arti`（Vite + React 19，TuCool）
- **现象**：
  1. `pnpm install` 正常完成后报 `[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: @parcel/watcher, @sentry/cli, esbuild, unrs-resolver`
  2. 直接 `pnpm dev --port 3012` 启动失败：pnpm 在运行前做 deps status check，因 ignored builds 再次调用 `pnpm install` 返回 exit 1，整个命令失败
  3. 更隐蔽的是：pnpm 11 会自动向 `pnpm-workspace.yaml` **注入**一个 `allowBuilds:` 块，内容是占位符 `set this to true or false`，导致 `git status` 出现该文件被修改——污染工作区，若顺手 commit 就会把垃圾配置带进 gitlab
- **根因**：pnpm 11 默认拒绝未批准依赖的 postinstall 脚本（安全策略），但会提示并自动写入占位配置；`pnpm dev` 前的 `verify-deps-before-run` 检查把 "ignored builds 状态" 视为依赖未就绪而失败。
- **修复（不污染 git 的方案）**：绕过 pnpm 直接运行 vite：
  ```
  node node_modules/vite/bin/vite.js --port 3012 --open false
  ```
  esbuild 二进制在 `.pnpm/@esbuild+win32-x64@0.25.12/node_modules/@esbuild/win32-x64/esbuild.exe`（optionalDeps），即使 postinstall 被忽略也能被 esbuild 主包 fallback 找到，vite 正常工作。
  若要恢复 `pnpm dev`：先 `pnpm approve-builds` 批准脚本（或手动把 `pnpm-workspace.yaml` 的 `allowBuilds` 改成 `true/false`）。
- **验证**：vite 以 612ms 启动，`http://localhost:3012/` 返回 200；`git status` 干净。
- **教训**：Windows 上 git 克隆 + pnpm 项目，"只装依赖不动代码"也会产生工作区改动（pnpm-workspace.yaml 被注入）。跑完 install 后必须 `git status` 检查并还原，或用 node 直接跑 vite 绕开 pnpm 的 build 检查。

### 38. 系统 DNS(1.1.1.1/4.2.2.1) 无法解析公司内网 GitLab 域名，git clone 报 Could not resolve host

- **标签**：`dns` `hosts` `gitlab` `内网域名` `网络`
- **现象**：`git clone https://git-new.7k7k.com/data/arti.git` 报 `fatal: unable to access ... Could not resolve host: git-new.7k7k.com`。`nslookup` 显示 DNS request timed out（DNS 服务器是 1.1.1.1/4.2.2.1）。但 `ping 223.5.5.5`（阿里 DNS）正常——外网通，只是 DNS 服务器不可用/被墙。
- **根因**：本机网卡手动配置了 1.1.1.1/4.2.2.1 作 DNS，这两个国外 DNS 在本网络不可达；且 7k7k 是公司域名，公网 DNS（223.5.5.5/114.114.114.114）可解析出 `106.75.6.140`，内网子域名 `git-new-inner.7k7k.com` → `10.9.133.53`。
- **修复**：
  1. 用国内 DNS 显式解析：`nslookup git-new.7k7k.com 223.5.5.5`
  2. 把解析结果写入 hosts：`Add-Content $env:WINDIR\System32\drivers\etc\hosts "106.75.6.140 git-new.7k7k.com"`（需管理员权限；`git-new-inner.7k7k.com` 是 pnpm 依赖 `@fe/auth-tool` 的 git 源，也要一并写入）
  3. 或永久方案：把网卡 DNS 改成 223.5.5.5
- **验证**：写 hosts 后 `git clone git@git-new.7k7k.com:data/arti.git` 成功；`ssh -T git@git-new.7k7k.com` 返回 `Welcome to GitLab, @zhangshikun!`
- **教训**：本机 DNS 配置（1.1.1.1/4.2.2.1）不可靠，凡是遇到 git/curl/npm 报 DNS 解析失败，先用 `nslookup <域名> 223.5.5.5` 确认公网/内网可达性再决定是否改 hosts，不要直接在不能解析的 DNS 上反复重试。hosts 修改是持久性系统改动，完成后应提醒用户考虑换 DNS。

### 39. Vite dev server 模块转换缓存损坏 → lazy 路由页面白屏崩溃 `TypeError: Cannot convert object to primitive value`

- **标签**：`vite` `react` `lazy` `缓存` `crash` `前端`
- **项目**：`D:\project\2026\gitlab\arti`（TuCool，Vite 7 + React 19 + pnpm）
- **现象**：某个懒加载路由页面（如 `/share`）崩溃，浏览器 console 报 `TypeError: Cannot convert object to primitive value`，component stack 最内层是 `at Lazy (<anonymous>)` / `at Suspense`，Vite 服务端日志却**没有编译错误**。直接 `curl http://localhost:3012/src/views/create/share/page.tsx` 返回只有 `"use strict";` 的**空模块（14 字节）**，而同项目其他模块正常（几 KB~几百 KB）。
- **根因**：长时间运行的 vite dev server 在频繁 HMR 后，其模块图缓存里某个模块的 transform 结果被损坏成空；浏览器 `import()` 拿到空模块 → `React.lazy` 解析不到 `default` export → 抛错白屏。
- **排查关键线索**：新起一个 vite server 实例（`createServer().transformRequest(url)`）转换同一文件时，抛 `Cannot find package 'babel-plugin-react-compiler' imported from D:\project\2026\gitlab\babel-virtual-resolve-base.js`。注意 babel 解析插件的 base 是 **process.cwd()**：在项目目录（`arti`）下运行转换正常，在上级目录（`gitlab`）运行就失败（上级目录没有 `node_modules`）。这是 cwd 假象，真实 server 的根因是**缓存损坏**而非 cwd。
- **修复**：重启 dev server。`Get-NetTCPConnection -LocalPort 3012 -State Listen` 找占用 PID → `Stop-Process` → 在项目目录后台重启 `node node_modules/vite/bin/vite.js --port 3012 --open false`（见 #37 绕开 pnpm 的方式）。重启后再 `curl` 该模块 URL，确认返回完整 JS（本例恢复 73KB）。
- **验证**：`curl` 模块 URL 由 14 字节恢复到完整代码；页面正常渲染。
- **教训**：dev server 长期运行 + 反复 HMR 后页面莫名白屏崩溃、且服务端日志无报错时，**先 curl 该模块 URL 看返回内容是否异常/为空**，比猜代码快得多；再考虑重启 server。

### 40. antd Input 的 className 直接落在最外层元素上，SCSS Module 却写"后代选择器"，导致描边/圆角覆盖不生效

- **标签**：`antd` `input` `css-modules` `scss` `选择器` `border` `样式不生效`
- **项目**：`D:\project\2026\gitlab\arti`（TuCool，Vite 7 + React 19 + antd v6）
- **现象**：给 `/share` 页面搜索框改胶囊圆角 + 去掉灰白描边，在 SCSS Module 里写 `.promptFilter :global(.ant-input-affix-wrapper) { border: 0; border-radius: 999px; }`，浏览器里外框样式完全没生效，只有背景变了，一度怀疑改错了页面。
- **根因**：`className={styles.promptFilter}` 是直接加在 antd Input **最外层元素**上的——而这个最外层元素**就是** `.ant-input-affix-wrapper`（带 prefix/suffix 时 antd 把该 className 渲染到根节点上）。SCSS 写成 `.promptFilter :global(.ant-input-affix-wrapper)`（后代选择器）要求 `.promptFilter` 是 `.ant-input-affix-wrapper` 的**祖先**，但两者是**同一个元素**，规则永不命中；背景生效是因为 `.promptFilter` 自身的 background 声明碰巧命中。
- **修复**：
  1. 直接在根元素上写样式，不要后代选择器：`.promptFilter { border: 0 !important; border-radius: 999px !important; }`（className 与 `.ant-input-affix-wrapper` 同元素，直接写根类即可覆盖）
  2. 要彻底去掉 antd 描边，优先用组件官方属性 `variant='borderless'`（antd v5/v6），比硬抗 CSS-in-JS 干净
  3. 覆盖 hover/focus 态补 `&:hover, &:focus, &:focus-within`，必要时 `!important`（antd CSS-in-JS 动态注入，普通优先级可能被反超）
- **验证**：`.promptFilter` 直接设 `border-radius: 999px !important; border: 0 !important; background: #1a1c20 !important;` + `variant='borderless'`，搜索框变胶囊且无描边；`curl http://localhost:3012/src/views/create/share/page.module.scss` 可见编译后的 `._promptFilter_xxx` 规则直接作用于自身。
- **教训**：给 antd 组件传 `className` 前，先确认该 className 落在哪个 DOM 节点——antd 很多组件（Input/Select 等）会把 className 直接给根节点。SCSS Module 里"同名类 + 全局类"的后代选择器不命中时，改成直接写根类本身，并优先用组件官方 variant 属性。

### 41. Windows 下 SQLite 连接未关闭导致 pytest `TemporaryDirectory` 清理报 `PermissionError`

- **标签**：`sqlite` `windows` `pytest` `临时目录` `文件锁` `PermissionError`
- **项目**：`D:\project\2026\canvas-agent-unified`（Canvas Agent Unified，FastAPI）
- **现象**：`PYTHONPATH=. pytest -q` 在 Windows 上 4 个用例全挂，报 `PermissionError: [WinError 32] 另一个程序正在使用此文件`，路径指向 pytest `TemporaryDirectory` 里的 `test.db`。README 写「4 passed」是 Linux 沙箱的结果，本机 Windows 却失败——但 HTTP smoke 全过，说明不是业务逻辑问题。
- **根因**：`Database` 类（`apps/api/app/db.py`）在 `__init__` 里 `sqlite3.connect(...)` 后**从不 close 连接**。Windows 对已打开的文件加锁，`TemporaryDirectory` 上下文退出时删不掉仍被连接的 `test.db`（及其 WAL/shm 文件），报 WinError 32。Linux 允许删除已打开文件，所以 Linux 上不报错——这是纯平台差异。
- **修复**：
  1. `Database` 增加 `close()` 方法：`with self._lock: self._conn.close()`（套 try/except 兜底）
  2. 测试里在 `with TemporaryDirectory() as tmp:` 块内用 `try/finally: db.close()`，确保连接在临时目录清理前释放
- **教训**：测试里创建了持有文件句柄/连接的对象（sqlite3、打开的文件等）必须显式 close，不能依赖对象被 GC——`__del__` 在 `TemporaryDirectory` 清理前不触发（局部变量仍在栈上，引用计数 >0）。跨平台跑 pytest 时，Windows 的文件锁会让「Linux 能过、Windows 挂」的用例暴露出来。
- **验证**：`PYTHONPATH=. pytest -q` → `4 passed`；`/api/health` 返回 `{"ok":true,"version":"0.2.0"}`。

### 42. Canvas Agent 本地 `.env` 仍是 mock provider，前端功能完成但远程标记接口不会被调用

- **标签**：`canvas-agent` `marker` `provider` `.env` `mock` `remote` `配置`
- **项目**：`D:\project\2026\canvas-agent-unified`
- **现象**：前端 marker UI 已发送 `/api/capabilities/run`，后端 Job 也成功完成，但返回 `provider=mock` 和本地固定文案，用户认为「标记点接口没通」。
- **根因**：项目的本地 `apps/api/.env` 明确配置 `MARKER_PROVIDER=mock`；README/.env.example 中虽然提供了远程地址 `http://117.50.195.214:8100/api/v1`，但示例配置不会自动覆盖已有本地 `.env`。重启前进程也不会重新读取环境变量。
- **修复**：
  1. 将 `apps/api/.env` 设置为：`MARKER_PROVIDER=remote`、`MARKER_BASE_URL=http://117.50.195.214:8100/api/v1`。
  2. 完整重启 API 进程，让 `Settings` 和 capability registry 按新配置重建。
  3. 用真实图执行 `POST /api/capabilities/run`，检查 Job `output.provider == "remote-marker"`；区域标记还应保留 `marker_id`、`bbox` 与 `geometry_support`。
- **远程协议校准**：该服务的 `/marker/upload` 接受 `file`，同时支持 `original_width`、`original_height`；`/marker/recognize-by-id` 接受 JSON `image_id`、`point_x`、`point_y`、`marker_index`、`instruction` 和可选 `bbox`。
- **验证**：实际接口探测中 `POST http://117.50.195.214:8100/api/v1/marker/upload` 返回 `image_id`；经 Canvas Agent Job 调用后返回 `status=succeeded provider=remote-marker marker_id=remote-verify-marker bbox_x1=8 geometry=point_with_bbox_context`。

### 43. 删除全局 CSS 类规则时把它"顺带"提供的定位声明也删了 → 后代绝对定位元素失去包含块撑满祖先

- **标签**：`css` `position:absolute` `回归` `marker` `canvas-agent`
- **项目**：`D:\project\2026\canvas-agent-unified`
- **现象**：为去掉画布标记点的红色背景，删除了 `styles.css` 里的旧规则 `.tag-pin{position:absolute;...;width:25px;height:25px;...}`。刷新后水滴标记变成巨大的蓝色水滴撑满整张图片节点。
- **根因**：被删的旧规则恰好是 `.tag-pin` 唯一的 `position:absolute` 声明来源。水滴内部的 svg 是 `.tag-pin svg{position:absolute;inset:0;width:100%;height:100%}`——删除后 `.tag-pin` 变回 static，svg 的绝对定位包含块回退到最近的 positioned 祖先（图片节点），于是撑满整个节点。
- **修复**：在模块级样式（`marker.css`）补 `.tag-pin{position:absolute;display:block}`，并在审计脚本中加入 `.tag-pin{position:absolute` 静态检查防回退。
- **教训**：删除"看起来是遗留/错误"的 CSS 类规则前，先检查该类自身的子元素样式（`inset:0`、`absolute` 后代）是否依赖这个类的定位声明；删除后必须在目标模块补回必要定位，并加审计规则。

### 44. overflow:auto 容器内的绝对定位下拉菜单被裁剪不可见 → 改 position:fixed + getBoundingClientRect

- **标签**：`css` `dropdown` `overflow` `clipping` `position:fixed` `canvas-agent`
- **项目**：`D:\project\2026\canvas-agent-unified`
- **现象**：共享词条下拉（`.marker-menu`，`position:absolute;bottom:calc(100%+4px)` 向上弹出）在 Agent 面板里看不见/点不到。
- **根因**：菜单定位参考 `.marker-card`（`position:relative`），但祖先 `.marker-context{max-height:112px;overflow:auto}` 是滚动容器，向上弹出的菜单被 `overflow` 裁剪。absolute 后代只要包含块在滚动容器内部就会被裁剪。
- **修复**：
  1. `.marker-menu{position:fixed}`（祖先无 transform/filter 时 fixed 脱离所有 overflow 裁剪）
  2. 打开时用 `event.currentTarget.closest('.marker-card').getBoundingClientRect()` 计算视口坐标写入内联 style；向上弹用 `transform:translateY(-100%)`
  3. 防溢出：`rect.top < 262` 时改为向下弹（`top=rect.bottom+4`、无 transform）
  4. 补外部点击关闭：document `pointerdown` 监听，`closest('.marker-menu')/.marker-menu-trigger` 之外即关闭（触发器自身 `onPointerDown stopPropagation`）
- **教训**：在 `overflow:auto/hidden` 的容器内做弹出层（下拉、tooltip、popover），不要用 absolute 贴父元素；直接用 fixed + 矩形坐标，或 portal 到 body。注意祖先若有 `transform`/`filter`/`will-change` 会成为 fixed 的包含块使 fixed 失效。

### 45. Canvas Agent `Database` 有表名白名单，新增持久化桶必须同步建表+放行

- **标签**：`canvas-agent` `sqlite` `database` `白名单` `unsupported table`
- **项目**：`D:\project\2026\canvas-agent-unified`
- **现象**：新增 workflow 目录缓存（`WorkflowService` 用 `db.put_json('workflow_catalog', ...)`）后，`GET /api/workflows/catalog` 报 500，traceback 末尾 `ValueError: unsupported table`。
- **根因**：`app/db.py` 的 `Database._check` 只放行 `{'canvases','artifacts','jobs'}`；`_init` 也只建这三张表 + trajectories。任何新的 `put_json` 桶名都会先被白名单拦下。
- **修复**：`_init` 的 executescript 里 `CREATE TABLE IF NOT EXISTS <新桶> (id TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at ...)`，并把桶名加进 `_check` 白名单，两处都要改。
- **教训**：在该项目用 `db.put_json/get_json` 引入新数据桶时，永远同时改 `_init` 建表与 `_check` 白名单，缺一即运行时 500。

### 46. Bash 工具内 `Start-Process` 后台服务会被 `ChildProcess.kill` 回收

- **标签**：`powershell` `start-process` `后台进程` `uvicorn` `工具行为`
- **项目**：`D:\project\2026\canvas-agent-unified`（重启 8000 端口 API）
- **现象**：在 bash 工具命令里 `Start-Process python -m uvicorn ... -RedirectStandardOutput/-Error`，命令返回 `Unknown: ChildProcess.kill`，看似启动失败。
- **根因**：工具会追踪命令派生的子进程并在命令结束时尝试清理，`Start-Process` 拉起的 uvicorn 被当作子进程回收（但有时实际存活）。
- **正确做法**：不要以返回码判断成败；启动后单独执行 `Get-NetTCPConnection -LocalPort 8000 -State Listen` 确认监听 PID，再 `Invoke-WebRequest` 打健康/业务接口验证。进程确实在跑就忽略 kill 报信息。
- **追加**：`Start-Process -FilePath` 用相对路径（如 `.\.venv\Scripts\python.exe`）会直接报"找不到指定的文件"，即使给了 `-WorkingDirectory`；`-FilePath` 与重定向路径都必须用绝对路径。

### 47. Vite dev 服务器会吐出过时的模块（改了源码但浏览器/HTTP 拿到的还是旧代码）

- **标签**：`vite` `hmr` `stale-module` `dev-server` `白屏` `空白页面`
- **项目**：`D:\project\2026\canvas-agent-unified`
- **现象**：编辑 `apps/web/src/*.ts(x)` 后，浏览器白屏/报错 `The requested module '/src/api.ts' does not provide an export named 'X'`；直接 HTTP 请求 `http://localhost:5174/src/<file>` 返回的内容也不含新增导出——vite 的 transform 缓存/watcher 漏掉了该次文件变更。
- **排查口径**：不要只看进程在不在、`npm run build` 过不过（build 是新起进程，永远是新代码）；必须 `Invoke-WebRequest http://localhost:5174/src/<改动文件>` 后 `$Content.Contains('新增标识符')` 验证 dev 服务器真实吐出的内容。
- **修复**：杀掉 5174 端口进程重启 vite dev（清空 transform 缓存），再让用户 Ctrl+F5 强刷浏览器（浏览器侧 HMR 模块图也可能残留）。
- **教训**：canvas-agent 项目里只要改完前端就顺手 curl 验证 dev server 输出；出现白屏/缺导出先怀疑 vite 缓存而不是自己代码。

### 48. httpx 默认走 Windows 系统代理，本地 Clash 会劫持公司域名（getaddrinfo failed / 502）

- **标签**：`httpx` `trust_env` `代理` `clash` `dns` `getaddrinfo` `canvas-agent`
- **项目**：`D:\project\2026\canvas-agent-unified`（工作流网关 `aigc-test.youxi123.com` + OSS 上传/产物下载）
- **现象**：工作流 job 失败报 `ConnectError: [Errno 11001] getaddrinfo failed`，或 `502 Bad Gateway`；同一请求时好时坏，而 PowerShell `Resolve-DnsName` 与直连 httpx 测试都正常。
- **根因**：机器开了 Windows 系统代理（HKCU Internet Settings `ProxyServer=127.0.0.1:7897`，Clash）。httpx `trust_env=True`（默认）读系统代理把公司域名流量转发给本地代理；代理状态不稳/DNS 被其 hook 时，报 getaddrinfo failed（DNS 挂）或 502（上游挂）。
- **修复**：
  1. 所有出站公司请求用 `httpx.AsyncClient(..., trust_env=False)` 绕过系统代理直连。
  2. 对 `httpx.ConnectError` 加有限重试（3 次、1s/2s 退避）抗瞬时 DNS 抖动；写接口只在"连接从未建立"（ConnectError）时重试才安全，避免重复建任务。
  3. 诊断口径：先 `Get-ItemProperty HKCU:\...\Internet Settings` 看 `ProxyEnable/ProxyServer`；同一 URL 分别 `trust_env=True/False` 各打一遍，差异即坐实代理劫持。
- **教训**：Windows 上 httpx/aiohttp 报 getaddrinfo/502 而命令行解析正常，第一怀疑系统代理劫持而非 DNS 本身；对内网/公司固定域名永远 `trust_env=False` + ConnectError 重试。

### 49. PowerShell 读写含中文文件不带 `-Encoding UTF8` 时字符串匹配全假阴性

- **标签**：`powershell` `编码` `utf-8` `get-content` `中文匹配`
- **项目**：`D:\project\2026\canvas-agent-unified`
- **现象**：用 `Get-Content -Raw` + `.Contains('中文')` 验证源码改动，全部返回 False，甚至对确定存在的字符串也 False，误以为改动丢失。
- **根因**：Windows PowerShell 5.1 的 `Get-Content` 默认用系统 ANSI 代码页（GBK）读文件，UTF-8 中文被读成乱码；命令里的中文字面量是 UTF-8，两边不匹配。同理 `Set-Content`/`Add-Content` 不带 `-Encoding UTF8` 会以 ANSI/UTF16 写回破坏文件。
- **修复/口径**：凡读写含中文的文件一律显式 `-Encoding UTF8`；或改用 ASCII 锚点（标识符、类名）做 Contains 验证；注意 vite/esbuild 交付内容可能把中文转义成 `\uXXXX`，验证 dev server 输出优先用 ASCII 锚点。

### 50. TuCool 网关偶发 `cannot complete comfyui task <id> from status running` —— 瞬时竞态，重跑即过

- **标签**：`comfyui` `workflow` `网关` `瞬时故障` `outpaint`
- **项目**：`D:\project6\canvas-agent-unified`
- **现象**：e2e 提交 `outpaint` 工作流任务，后端 Job 轮询到终态 `failed`，fail_reason 为 `cannot complete comfyui task 787 from status running`；**同样输入立刻重跑即成功**。
- **原因**：aigc 网关内部状态机竞态——任务实际已跑完，但网关在状态仍为 running 时尝试 complete 而失败。与我方代码、图片格式、代理设置均无关。
- **修复/约定**：不要为它改代码/换图片格式；把它当瞬时故障——重新执行同一任务通常成功。本项目不自动重试 Job（避免重复生成/计费），失败消息进聊天由用户手动重跑。e2e 脚本（`scripts/e2e_outpaint.py`）遇此错直接再跑一遍。
- **教训**：网关类服务的 failed 终态要先看 fail_reason 判断是「输入错误」还是「服务端竞态」；偶发的 `from status running` 属于后者，先重跑验证再怀疑自己的参数。
