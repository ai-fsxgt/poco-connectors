# DingTalk operation notes

## Product routing

Common product filters include `calendar`, `todo`, `doc`, `drive`, `chat`, `contact`, `mail`, `minutes`, `aitable`, `sheet`, `oa`, `attendance`, `recruit`, `report`, `wiki`, `whiteboard`, `live`, `ding`, `audit`, `event`, `aisearch`, and `agoal`.

Search by the intended business action rather than guessing a command. Review required parameters, constraints, examples, effect, and confirmation from the returned catalog entry before execution.

## Runtime boundaries

- Each invocation is isolated and has no persistent local DWS state.
- DWS developer-daemon commands, Drive folder sync commands, local audit-history commands, local browser-policy commands, and commands that inspect or stop a previous local event listener are reported as unavailable on Poco.
- `event.consume` and `event.listen_im` require an explicit `duration` no longer than 15 seconds.
- `doc.update_document` always requires confirmation on Poco because the same DWS command also supports destructive whole-document replacement.
- File inputs total at most 180 KiB so the encoded request remains within Poco's connector gateway limit. Plain `text` input is limited to 32K characters; use `content_base64` for larger or binary content. Returned stdout and generated files are bounded by the connector response limit. Use narrower queries for larger data sets.
- Absolute paths and parent-directory traversal are rejected. Output files exist only in the tool result; they are not retained by the next invocation.

## Permissions

OAuth login establishes the DingTalk identity. DingTalk PAT scopes govern individual business APIs separately. On an insufficient-scope response, report the missing permission guidance and wait for an administrator to grant it; do not run PAT permission-changing commands automatically.
