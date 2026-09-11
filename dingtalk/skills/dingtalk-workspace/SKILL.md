---
name: dingtalk-workspace
description: Use a connected DingTalk workspace to find or act on calendars, tasks, documents, drive, chat, contacts, mail, approvals, tables, attendance, recruiting, reports, and other DingTalk business data.
---

# DingTalk Workspace

Use `search_commands` before choosing an operation. Search with a focused business verb and, when known, the product and effect. Use only the canonical command and flags returned by the catalog.

Route the command by its catalog metadata:

- `read` → `execute_read_command`
- `write` + `not_required` → `execute_write_command`
- `write` + `user_required` → `execute_confirmed_write_command`
- `destructive` → `execute_destructive_command`

Never move an operation to a lower-risk tool to avoid confirmation. Poco binds approval to the exact connection, command, and arguments.

For write or destructive failures, do not repeat the command. Query the remote object first because the operation may have completed before the response failed.

Use `file_inputs` for local file parameters. Supply text or base64 content and a plain file name; never pass server paths through `flags`. Returned small files appear as embedded resources.

For product routing, bounded event listening, local-runtime limits, and file size constraints, read [references/operations.md](references/operations.md).
