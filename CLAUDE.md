# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Ruleset

This project follows the shared CommonClaude conventions, vendored as a git
submodule at `external/CommonClaude`. The full ruleset is imported below and
covers: MIT code convention, debug file management (`claude_test/`), task
management (ToDo.md + GitHub issues via `gh`), testing rules, linting (Ruff),
MCP server usage (Serena / Context7 / Fetch), Conventional Commits, GitHub
Flow branching, SemVer, and PR guidelines.

@external/CommonClaude/CLAUDE.md

## Project Notes

- Hooks from the submodule are wired in `.claude/settings.json` and point at
  `external/CommonClaude/.claude/hooks/`. Update the submodule
  (`git submodule update --remote external/CommonClaude`) to pick up new
  rules and hooks.
- Project-specific rules added here take precedence over the imported
  CommonClaude ruleset (see its §1 Rule Priority).
