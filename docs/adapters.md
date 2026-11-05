# Adapters

An adapter reads one tool's logs. Adapters are the only code that knows a log format, so when a tool changes its format, one file breaks and nothing else does.

| Tool | Reads | Notes |
|---|---|---|
| `claude-code` | `~/.claude/projects/*/*.jsonl` and `<session>/subagents/*.jsonl` | usage from each assistant message; streamed chunks deduplicated by message id; subagent turns counted but not judged; compaction summaries, meta messages and `<synthetic>` error notices skipped |
| `codex` | `$CODEX_HOME/sessions/**/rollout-*.jsonl` | `token_count` events' `last_token_usage`; cached tokens split out of input; reasoning tokens are already inside output |
| `gemini` | `~/.gemini/tmp/*/chats/session-*.json` | per-message `tokens`; cached split out of input, thoughts added to output. Project folders are hashes, so the project shows as a hash prefix unless the file names a folder |
| `aider` | `.aider.chat.history.md` under `$AIDER_REPOS` (colon-separated) or `~/code`, `~/src`, `~/projects`, `~/dev` | parses `> Tokens: 12k sent, 1.2k received`; no cache data |
| `generic` | `~/.config/agentmeter/sessions/*.jsonl` | your own export, see below |

Only `claude-code` has been checked against real logs. If another adapter misreads yours, a trimmed, anonymised log file as a fixture in `tests/fixtures/` plus a failing test is the most useful bug report.

## Your own tool

Write one session per line to `~/.config/agentmeter/sessions/*.jsonl`:

```json
{"tool": "cursor", "id": "abc", "project": "shop", "prompts": ["add a cart page"],
 "turns": [{"ts": "2026-01-05T10:22:14Z", "model": "gpt-5", "input": 1200,
            "cache_write": 0, "cache_read": 9000, "output": 400}]}
```

A turn may add `"auto": true` when a subagent or the harness chose its model; it's counted but not judged.

## Writing an adapter

Add one file to `agentmeter/adapters/` that defines:

- `NAME`: the tool name, e.g. `"cursor"`
- `DESC`: one line for menus, e.g. `"Cursor"`
- `default_root()`: where the tool keeps its logs
- `sessions(root, since=None)`: yields `core.Session` objects. Skip files last modified before `since` (epoch seconds), so the hourly runs stay fast.

Then add it to `BUILTIN` in `agentmeter/adapters/__init__.py`, with a fixture and a test in `tests/test_adapters.py`. Python 3.9 and the standard library only.
