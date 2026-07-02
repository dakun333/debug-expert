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
