# debug-expert

Claude Code 全局错误经验库 —— 收录跨项目历史上踩过的每一个坑，避免同一个问题被反复排查。

> ⛔ 装一次，每个 session 自动启用。最高优先级。

[📖 English](README.md)

## 安装

```bash
git clone https://github.com/dakun333/debug-expert.git
cd debug-expert
python install.py
```

或一行：
```bash
git clone https://github.com/dakun333/debug-expert.git ~/debug-expert && python ~/debug-expert/install.py
```

然后在 `~/.claude/CLAUDE.md` 中加：
```markdown
## ⛔ 最高优先级：debug-expert

每个 session 开始处理任何任务之前，必须先用 Read 读取
~/.claude/skills/debug-expert/SKILL.md，匹配当前任务相关的已知坑。
命中了直接用已知修复方案，不要重新排查。
```

## 用法

在 Claude Code 中：
```
/debug-expert              → 列出全部已知错误
/debug-expert <关键词>     → 搜索（如 subprocess、github、asyncio）
```

## 规则

1. **命中** → 直接用已有修复方案，不要重新排查
2. **新坑** → 解决后**追加**到 SKILL.md（含标签 / 现象 / 根因 / 修复 / 验证）
3. 本 skill 在所有项目中拥有**最高优先级**

## 为什么需要它

在跨多个仓库（feishu-bot、feishu-progress-push、manga-lineart、ComfyUI）的工作中，经常出现同一个坑被不同 session 反复排查的问题 —— 孤儿子进程、GitHub 推送超时、PowerShell stderr 误报、硬编码路径等。

这个 skill 解决了这个问题。一个地方，持续增长，总是优先检查。

## License

MIT
