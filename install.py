#!/usr/bin/env python3
"""Install the debug-expert skill into the user's Claude Code skills directory."""
import os
import shutil
import sys

SKILL_DIR = os.path.expanduser("~/.claude/skills/debug-expert")
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SKILL.md")

def main():
    os.makedirs(os.path.dirname(SKILL_DIR), exist_ok=True)
    if os.path.isdir(SKILL_DIR):
        shutil.rmtree(SKILL_DIR)
    os.makedirs(SKILL_DIR)
    shutil.copy2(SRC, os.path.join(SKILL_DIR, "SKILL.md"))

    print("✅ debug-expert skill installed to", SKILL_DIR)
    print()
    print("To make it auto-load every session, add this to your ~/.claude/CLAUDE.md:")
    print()
    print("  ## ⛔ debug-expert error knowledge base")
    print("  Before handling any error/exception, first scan")
    print("  ~/.claude/skills/debug-expert/SKILL.md for matching known issues.")
    print()
    print("  Invoke in-session: /debug-expert")
    return 0

if __name__ == "__main__":
    sys.exit(main())
