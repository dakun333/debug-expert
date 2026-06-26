# debug-expert

A Claude Code skill that records **every bug/trap/error** encountered across projects — so no issue is debugged twice.

> ⛔ Install once, auto-check before every troubleshooting session. Highest priority.

[📖 中文](README_zh.md)

## Install

```bash
git clone https://github.com/dakun333/debug-expert.git
cd debug-expert
python install.py
```

Or one-liner:
```bash
git clone https://github.com/dakun333/debug-expert.git ~/debug-expert && python ~/debug-expert/install.py
```

Then add to `~/.claude/CLAUDE.md`:
```markdown
## ⛔ Highest priority: debug-expert
Before handling any error or unexpected behavior, scan ~/.claude/skills/debug-expert/SKILL.md
for matching known issues first — don't re-debug what's already solved.
```

## Usage

In Claude Code:
```
/debug-expert              → list all known errors
/debug-expert <keyword>    → search (e.g. subprocess, github, asyncio)
```

## Rules

1. **Hits** → apply the recorded fix directly, do NOT re-investigate
2. **New pit** → solve it, then **append** to SKILL.md (tag + symptom + root cause + fix + verification)
3. This skill has the **highest priority** in all projects

## Why

Over the course of working across multiple repositories (feishu-bot, feishu-progress-push, manga-lineart, ComfyUI), a pattern emerged: the same mistakes were being re-debugged across sessions — orphan subprocesses, GitHub push timeouts, PowerShell stderr traps, hardcoded paths, etc.

This skill eliminates that waste. One place, growing, always checked first.

## License

MIT
